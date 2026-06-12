"""
智能自动分析工具 (SmartAutoAnalyze)
=====================================

一站式工具：从问题出发，自动完成「选表 → 查询 → 聚合 → 关联」的完整链路，
返回带血缘的分析结果。本工具是 SmartTableRouterTool 的下游工具，专为
"我不想分多次调用工具"的场景设计。

工作流：
    1) 调用 smart_table_router 选取候选表（top_k）
    2) 对每张候选表执行 MongoDB 实际查询（带 filters、group_by、metrics）
    3) 自动合并结果，生成跨表分析报告
    4) 返回 _lineage_meta，记录每张表的实际访问字段、记录数

与既有工具区别：
    - data_query：要求显式指定 collection（用户必须知道表名）
    - domain_query：支持 join 但需要预先指定左右表
    - smart_auto_analyze：完全黑盒，给问题→拿结果，自动溯源

使用示例：
    # 单表自动分析
    smart_auto_analyze(question="按省份统计高风险主体分布",
                       group_by=["affiliated_province"],
                       metrics=[{"agg": "count"}])

    # 多表自动分析（启用跨表）
    smart_auto_analyze(question="按风险等级分组各省份的产品持有人结构",
                       enable_multi_table=True,
                       max_tables=3)
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.smart_router_tool import SmartTableRouterTool
from app.config.database import Database

# 场景视图执行器
from app.services.semantic_profiles.static_profiles.datahub_scenario_views import (
    DATAHUB_SCENARIO_VIEWS,
)


# 可信的聚合操作
_AGG_OP_MAP = {
    "sum": "$sum", "avg": "$avg", "min": "$min", "max": "$max",
}

# MongoDB 操作符映射
_OP_MAP = {
    "eq": "$eq", "ne": "$ne", "gt": "$gt", "gte": "$gte",
    "lt": "$lt", "lte": "$lte", "in": "$in",
}


def _build_mongo_filter(filters: Any) -> dict:
    """将简化 filters 转成 MongoDB 查询条件。"""
    if not filters or not isinstance(filters, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in filters.items():
        if isinstance(v, dict) and v:
            cond: dict[str, Any] = {}
            for op, val in v.items():
                mongo_op = _OP_MAP.get(op)
                if mongo_op:
                    cond[mongo_op] = val
            if cond:
                out[k] = cond
        else:
            out[k] = v
    return out


def _serialize(doc: dict) -> dict:
    """序列化文档，去除 ObjectId 等不可 JSON 化字段。"""
    if not isinstance(doc, dict):
        return doc
    out = {}
    for k, v in doc.items():
        if k == "_id":
            continue
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _serialize(v)
        elif isinstance(v, list):
            out[k] = [_serialize(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


async def _execute_table_analysis(
    collection: str,
    group_by: list[str] | None,
    metrics: list[dict] | None,
    filters: dict | None,
    limit: int,
) -> dict:
    """对单张表执行聚合分析。"""
    db = Database.get_database()
    col = db[collection]

    pipeline: list[dict] = []

    # $match
    mongo_filter = _build_mongo_filter(filters)
    if mongo_filter:
        pipeline.append({"$match": mongo_filter})

    # 没有聚合指标时退化为 find（带 limit）
    if not metrics:
        cursor = col.find(mongo_filter).limit(limit)
        docs = []
        async for doc in cursor:
            docs.append(_serialize(doc))
        total = await col.count_documents(mongo_filter)
        return {
            "mode": "find",
            "records": docs,
            "record_count": len(docs),
            "total_in_collection": total,
        }

    # 有聚合指标 → aggregate
    group_stage: dict[str, Any] = {}
    if group_by:
        if len(group_by) == 1:
            group_stage["_id"] = f"${group_by[0]}"
        else:
            group_stage["_id"] = {g: f"${g}" for g in group_by}
    else:
        group_stage["_id"] = None

    sort_field: str | None = None
    for m in metrics:
        field = m.get("field", "_id")
        agg_op = m.get("agg", "count")
        alias = m.get("alias", f"{agg_op}_{field}")
        if agg_op == "count":
            group_stage[alias] = {"$sum": 1}
        elif agg_op in _AGG_OP_MAP:
            group_stage[alias] = {_AGG_OP_MAP[agg_op]: f"${field}"}
        else:
            group_stage[alias] = {"$sum": 1}
        if sort_field is None:
            sort_field = alias

    pipeline.append({"$group": group_stage})
    if sort_field:
        pipeline.append({"$sort": {sort_field: -1}})
    pipeline.append({"$limit": limit})

    docs: list[dict] = []
    async for doc in col.aggregate(pipeline):
        gid = doc.pop("_id", None)
        if isinstance(gid, dict):
            doc.update(gid)
        elif gid is not None:
            if group_by and len(group_by) == 1:
                doc[group_by[0]] = gid
            else:
                doc["group"] = gid
        docs.append(_serialize(doc))

    total = await col.count_documents(mongo_filter)
    return {
        "mode": "aggregate",
        "groups": docs,
        "group_count": len(docs),
        "total_in_collection": total,
    }


async def _execute_scenario_view(view_id: str, limit_per_pipeline: int = 50) -> dict:
    """执行 DataHub 场景视图（异步版本）。

    与 datahub_scenario_views.execute_scenario 同义，但采用 motor 异步驱动。
    """
    scenario = DATAHUB_SCENARIO_VIEWS.get(view_id)
    if not scenario:
        return {"error": f"场景 {view_id} 不存在"}

    db = Database.get_database()
    qt = scenario.query_template
    results: dict[str, Any] = {}
    tables_touched: list[str] = []
    total_records = 0

    try:
        # 单表场景（pipelines 在顶层）
        if "collection" in qt and "pipelines" in qt:
            col_name = qt["collection"]
            tables_touched.append(col_name)
            for name, pipeline in qt["pipelines"].items():
                pipeline_capped = list(pipeline) + [{"$limit": limit_per_pipeline}]
                docs: list[dict] = []
                async for doc in db[col_name].aggregate(pipeline_capped):
                    docs.append(_serialize(doc))
                results[name] = docs
                total_records += len(docs)

        # 多表场景（同 pipelines 应用到多表）
        elif "collections" in qt and "pipelines" in qt:
            for col_name in qt["collections"]:
                tables_touched.append(col_name)
                col_results: dict[str, Any] = {}
                for name, pipeline in qt["pipelines"].items():
                    pipeline_capped = list(pipeline) + [{"$limit": limit_per_pipeline}]
                    docs = []
                    try:
                        async for doc in db[col_name].aggregate(pipeline_capped):
                            docs.append(_serialize(doc))
                    except Exception as e:
                        col_results[name] = {"error": str(e)}
                        continue
                    col_results[name] = docs
                    total_records += len(docs)
                results[col_name] = col_results

        # 多步骤场景（steps）
        elif "steps" in qt:
            for step_name, step_cfg in qt["steps"].items():
                col_name = step_cfg["collection"]
                if col_name not in tables_touched:
                    tables_touched.append(col_name)
                pipeline = list(step_cfg["pipeline"]) + [{"$limit": limit_per_pipeline}]
                docs = []
                try:
                    async for doc in db[col_name].aggregate(pipeline):
                        docs.append(_serialize(doc))
                except Exception as e:
                    results[step_name] = {"error": str(e), "collection": col_name}
                    continue
                results[step_name] = {"collection": col_name, "docs": docs}
                total_records += len(docs)

    except Exception as e:
        return {"error": f"场景执行异常: {e}", "tables_touched": tables_touched}

    return {
        "view_id": view_id,
        "view_name": scenario.scenario_name,
        "tables_touched": tables_touched,
        "total_records": total_records,
        "pipeline_results": results,
        "narrative_template": scenario.analysis_narrative,
    }


class SmartAutoAnalyzeTool(BaseTool):
    """智能自动分析：从问题→自动选表→执行查询→返回带溯源的结果"""

    name = "smart_auto_analyze"
    description = (
        "【智能自动分析】一站式工具：从自然语言问题出发，自动完成"
        "「选表/选视图→查询→聚合」全过程，返回带完整血缘的分析结果。\n\n"
        "**工作模式**：\n"
        "- mode='auto'（默认）：智能路由，如果命中可执行场景视图（DataHub S1-S5）则优先执行场景，否则查单表或多表\n"
        "- mode='table'：强制走单表/多表查询路径\n"
        "- mode='scenario'：强制执行场景视图（需提供 view_id）\n\n"
        "**与其他工具的区别**：\n"
        "- 不需要预先知道表名或视图 ID\n"
        "- 不需要分多步调用（不像 smart_table_router 只返回候选清单）\n"
        "- 自动对每张表/每个场景执行查询，_lineage_meta 完整\n\n"
        "**适用场景**：\n"
        "- 用户问题模糊，不确定查哪张表\n"
        "- 跨表统计（如「各省份高风险主体的产品持有结构」）\n"
        "- 多场景一次性执行（如高风险扫描+产品风险匹配+持有人变迁）\n"
        "- 需要数据溯源透明\n\n"
        "**注意**：\n"
        "- 默认只查得分最高的 1 张表或 1 个场景；启用 enable_multi_table=true 时可同时查多个\n"
        "- filters/group_by/metrics 是可选的，仅对表查询生效（场景视图使用预定义 pipeline）"
    )
    category = "data"
    tags = ["智能", "自动", "选表", "分析", "溯源"]

    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "用户的自然语言问题（必填）",
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "table", "scenario"],
                "description": "执行模式：auto=智能路由（默认） / table=只查表 / scenario=只执行场景视图",
            },
            "view_id": {
                "type": "string",
                "description": "可选：明确指定要执行的场景视图 ID（如 datahub_s1_high_risk_scan），传入后跳过路由直接执行",
            },
            "filters": {
                "type": "object",
                "description": "查询过滤条件（仅对 mode='table' 生效）",
            },
            "group_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "分组字段名（仅对 mode='table' 生效）",
            },
            "metrics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "agg": {"type": "string", "enum": ["count", "sum", "avg", "min", "max"]},
                        "alias": {"type": "string"},
                    }
                },
                "description": "聚合指标（仅对 mode='table' 生效）",
            },
            "enable_multi_table": {
                "type": "boolean",
                "description": "是否对多张候选表都执行查询（默认 false，仅查 top1）",
            },
            "enable_multi_scenario": {
                "type": "boolean",
                "description": "是否对多个候选场景都执行（默认 false）",
            },
            "max_tables": {
                "type": "integer",
                "description": "启用多表时最多查询的表数，默认 3，最大 5",
            },
            "max_scenarios": {
                "type": "integer",
                "description": "启用多场景时最多执行的场景数，默认 2，最大 5",
            },
            "limit": {
                "type": "integer",
                "description": "每张表/每条 pipeline 返回的最大记录/分组数，默认 100",
            },
            "domain_filter": {
                "type": "string",
                "description": "可选：限定到某个域",
            },
        },
        "required": ["question"],
    }

    async def execute(self, **kwargs) -> dict:
        question = (kwargs.get("question") or "").strip()
        if not question:
            return ToolResult.error("question 不能为空")

        mode = (kwargs.get("mode") or "auto").strip().lower()
        if mode not in ("auto", "table", "scenario"):
            mode = "auto"
        explicit_view_id = (kwargs.get("view_id") or "").strip() or None
        enable_multi = bool(kwargs.get("enable_multi_table", False))
        enable_multi_scenario = bool(kwargs.get("enable_multi_scenario", False))
        max_tables = max(1, min(5, int(kwargs.get("max_tables") or 3)))
        max_scenarios = max(1, min(5, int(kwargs.get("max_scenarios") or 2)))
        limit = max(1, min(500, int(kwargs.get("limit") or 100)))
        filters = kwargs.get("filters") or {}
        group_by = kwargs.get("group_by") or []
        metrics = kwargs.get("metrics") or []
        domain_filter = (kwargs.get("domain_filter") or "").strip() or None

        try:
            # ── 快路径：用户明确指定 view_id ──
            if explicit_view_id:
                return await self._run_scenarios(
                    question, [explicit_view_id], limit
                )

            # ── 调用路由 ──
            router = SmartTableRouterTool()
            route_res = await router.execute(
                question=question,
                top_k=10,
                top_k_views=5,
                domain_filter=domain_filter,
                enable_cross_table=False,
            )
            if not route_res.get("success"):
                return route_res

            tables_cands: list[dict] = route_res["data"]["tables_selected"]
            views_cands: list[dict] = route_res["data"].get("views_selected", [])

            # ── 决策使用哪条路径 ──
            executable_views = [v for v in views_cands if v.get("executable")]
            top_view_score = executable_views[0]["score"] if executable_views else 0
            top_table_score = tables_cands[0]["score"] if tables_cands else 0

            chosen_path: str
            if mode == "scenario":
                if not executable_views:
                    return ToolResult.error(
                        f"mode='scenario' 但未命中可执行场景视图。"
                        f"候选视图={[v['view_id'] for v in views_cands]}（仅 DataHub S1-S5 可直接执行）。"
                    )
                chosen_path = "scenario"
            elif mode == "table":
                if not tables_cands:
                    return ToolResult.error(f"未找到与「{question}」相关的表")
                chosen_path = "table"
            else:  # auto
                # 启发式决策：
                # 1) 问题含「全景/扫描/变迁/变化/跨期/合规/审计/交叉/预警/所有」等表示多维度分析的词 → 优先场景
                # 2) 问题同时涉及多个业务词说明跨表需求 → 优先场景
                # 3) 场景评分 >= 单表评分 → 优先场景
                multi_dim_keywords = [
                    "全景", "扫描", "变迁", "变化", "跨期", "合规", "审计",
                    "交叉", "预警", "多维度", "报告",
                ]
                cross_table_keywords = [
                    ("主体", "产品"), ("风险", "产品"), ("持有人", "产品"),
                    ("产品", "资产"), ("资产", "主体"),
                ]
                use_scenario_first = False
                if executable_views:
                    if any(kw in question for kw in multi_dim_keywords):
                        use_scenario_first = True
                    elif any(a in question and b in question for a, b in cross_table_keywords):
                        use_scenario_first = True
                    elif top_view_score >= top_table_score:
                        use_scenario_first = True

                if use_scenario_first:
                    chosen_path = "scenario"
                elif tables_cands:
                    chosen_path = "table"
                elif executable_views:
                    chosen_path = "scenario"
                else:
                    return ToolResult.error(
                        f"未找到与「{question}」相关的表或可执行视图。"
                        f"已遍历 {route_res['data'].get('total_candidates_evaluated', 0)} 张表、"
                        f"{route_res['data'].get('total_views_evaluated', 0)} 个视图。"
                    )

            # ── 路径 A：执行场景视图 ──
            if chosen_path == "scenario":
                target_views = (
                    [v["view_id"] for v in executable_views[:max_scenarios]]
                    if enable_multi_scenario
                    else [executable_views[0]["view_id"]]
                )
                return await self._run_scenarios(question, target_views, limit, route_res)

            # ── 路径 B：执行表查询 ──
            tables_to_query = tables_cands[:max_tables] if enable_multi else tables_cands[:1]
            return await self._run_tables(
                question, tables_to_query, filters, group_by, metrics, limit, route_res
            )

        except Exception as e:
            logger.exception("[SmartAutoAnalyze] 执行失败: {}", e)
            return ToolResult.error(f"智能自动分析失败: {e}")

    # ============================================================
    # 子路径 1：执行场景视图
    # ============================================================
    async def _run_scenarios(
        self, question: str, view_ids: list[str], limit: int,
        route_res: dict | None = None,
    ) -> dict:
        per_scenario_results: list[dict] = []
        all_tables_touched: list[str] = []
        all_domains: list[str] = ["data_hub"]
        total_records = 0

        for vid in view_ids:
            res = await _execute_scenario_view(vid, limit_per_pipeline=limit)
            per_scenario_results.append({
                "view_id": vid,
                "result": res,
            })
            if res.get("error"):
                continue
            for tbl in res.get("tables_touched", []):
                if tbl not in all_tables_touched:
                    all_tables_touched.append(tbl)
            total_records += res.get("total_records", 0)

        # 构造摘要
        summary_lines = [
            f"【智能自动分析-场景模式】问题「{question}」",
            f"执行场景视图 {len(view_ids)} 个：",
        ]
        for r in per_scenario_results:
            res = r["result"]
            if res.get("error"):
                summary_lines.append(f"  ✗ {r['view_id']}（执行失败：{res['error']}）")
            else:
                tables = res.get("tables_touched", [])
                summary_lines.append(
                    f"  ✓ {r['view_id']}（{res.get('view_name')}）→ 表={tables}，输出记录={res.get('total_records', 0)}"
                )
        summary_lines.append(
            "⚠️ 【数据真实性】本次返回的 pipeline_results 是 MongoDB aggregation 实际输出，"
            "请仅基于该数据进行分析，付与 narrative_template 填充后作为结论；禁止虚构其他统计。"
        )
        summary = "\n".join(summary_lines)

        result = ToolResult.success(
            data={
                "question": question,
                "execution_path": "scenario",
                "scenarios_executed": view_ids,
                "per_scenario": per_scenario_results,
                "router_summary": (
                    {
                        "tables_routed": [
                            {"table": t["table"], "score": t["score"]}
                            for t in (route_res or {}).get("data", {}).get("tables_selected", [])[:5]
                        ],
                        "views_routed": [
                            {"view_id": v["view_id"], "score": v["score"], "executable": v.get("executable")}
                            for v in (route_res or {}).get("data", {}).get("views_selected", [])[:5]
                        ],
                    } if route_res else None
                ),
            },
            summary=summary,
            record_count=total_records,
            data_shape="scenario_views",
        )
        result["_lineage_meta"] = {
            "tables_used": all_tables_touched,
            "domains_involved": all_domains,
            "fields_accessed": {tbl: ["<scenario_pipeline>"] for tbl in all_tables_touched},
            "views_referenced": [
                {"view_id": vid, "view_type": "datahub_scenario"} for vid in view_ids
            ],
            "join_path": "",
            "records_returned": total_records,
            "total_in_collection": 0,
            "query_operation": "smart_auto_analyze:scenario",
        }
        return result

    # ============================================================
    # 子路径 2：执行表查询
    # ============================================================
    async def _run_tables(
        self, question: str, tables_to_query: list[dict],
        filters: dict, group_by: list, metrics: list, limit: int,
        route_res: dict,
    ) -> dict:
        per_table_results: list[dict] = []
        lineage_tables: list[str] = []
        lineage_fields: dict[str, list[str]] = {}
        lineage_domains: list[str] = []
        total_records = 0

        for cand in tables_to_query:
            table = cand["table"]
            table_keys = set(cand.get("key_fields", []) or [])
            table_keys.update(cand.get("primary_keys", []) or [])
            try:
                db = Database.get_database()
                sample = await db[table].find_one({})
                sample_keys = set(sample.keys()) if sample else set()
            except Exception:
                sample_keys = set()
            allowed_keys = table_keys | sample_keys

            applied_filters = {k: v for k, v in filters.items() if k in allowed_keys}
            applied_group_by = [g for g in group_by if g in allowed_keys]
            applied_metrics: list[dict] = []
            for m in metrics:
                fld = m.get("field")
                if fld is None or m.get("agg") == "count" or fld in allowed_keys:
                    applied_metrics.append(m)

            try:
                res = await _execute_table_analysis(
                    collection=table,
                    group_by=applied_group_by,
                    metrics=applied_metrics,
                    filters=applied_filters,
                    limit=limit,
                )
                per_table_results.append({
                    "table": table,
                    "domain": cand["domain"],
                    "display_name": cand["display_name"],
                    "score": cand["score"],
                    "applied_filters": applied_filters,
                    "applied_group_by": applied_group_by,
                    "applied_metrics": applied_metrics,
                    "result": res,
                })
                lineage_tables.append(table)
                if cand["domain"] not in lineage_domains:
                    lineage_domains.append(cand["domain"])
                accessed = list(applied_filters.keys()) + applied_group_by
                for m in applied_metrics:
                    if m.get("field"):
                        accessed.append(m["field"])
                lineage_fields[table] = list(set(accessed))[:20]
                rc = res.get("record_count") or res.get("group_count") or 0
                total_records += rc
            except Exception as e:
                logger.warning("[SmartAutoAnalyze] 表 {} 查询失败: {}", table, e)
                per_table_results.append({
                    "table": table,
                    "domain": cand["domain"],
                    "display_name": cand["display_name"],
                    "score": cand["score"],
                    "result": {"error": str(e)},
                })

        summary_lines = [
            f"【智能自动分析-表查询】问题「{question}」\n"
            f"路由选取 {len(route_res['data']['tables_selected'])} 张候选表，"
            f"实际查询 {len(tables_to_query)} 张：",
        ]
        for r in per_table_results:
            res = r.get("result", {})
            if res.get("error"):
                summary_lines.append(f"  ✗ {r['table']}（查询失败：{res['error']}）")
            else:
                rc = res.get("record_count") or res.get("group_count") or 0
                total = res.get("total_in_collection", 0)
                summary_lines.append(
                    f"  ✓ {r['table']}（{r['display_name']}）→ {rc} 条结果（库内共 {total} 条）"
                )
        summary_lines.append(
            "⚠️ 【数据真实性】所有数字都来自上述实际查询，_lineage_meta 中记录了每张表的访问字段。"
        )
        summary = "\n".join(summary_lines)

        result = ToolResult.success(
            data={
                "question": question,
                "execution_path": "table",
                "candidates_routed": [
                    {"table": c["table"], "domain": c["domain"], "score": c["score"]}
                    for c in route_res["data"]["tables_selected"]
                ],
                "tables_queried": [r["table"] for r in per_table_results],
                "per_table": per_table_results,
                "views_available": [
                    {"view_id": v["view_id"], "executable": v.get("executable")}
                    for v in route_res["data"].get("views_selected", [])[:3]
                ],
            },
            summary=summary,
            record_count=total_records,
            data_shape="multi_table_aggregate",
        )
        result["_lineage_meta"] = {
            "tables_used": lineage_tables,
            "domains_involved": lineage_domains,
            "fields_accessed": lineage_fields,
            "join_path": "",
            "records_returned": total_records,
            "total_in_collection": sum(
                r.get("result", {}).get("total_in_collection", 0)
                for r in per_table_results
            ),
            "query_operation": "smart_auto_analyze:table",
            "candidates_evaluated": route_res["data"].get("total_candidates_evaluated", 0),
        }
        return result
