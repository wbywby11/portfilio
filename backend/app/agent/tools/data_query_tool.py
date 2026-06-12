"""
动态数据查询工具

支持4种操作模式：discover / schema / query / aggregate
已知集合名时可直接 query/aggregate，不确定时先 discover 探索。
"""

from typing import Any

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.services.collection_registry import (
    CollectionNotFoundError,
    CollectionRegistry,
    DOMAIN_METADATA,
)
from app.services.generic_query_engine import GenericQueryEngine

# 模块级单例
_registry = CollectionRegistry()
_engine = GenericQueryEngine(registry=_registry)


class DataQueryTool(BaseTool):
    """动态数据查询引擎工具"""

    name = "data_query"
    description = """动态数据查询引擎。可查询系统中任意数据集合，无需预知数据结构。
支持4种操作：discover(探索可用数据集)、schema(查看结构)、query(查询数据)、aggregate(聚合统计)。
已知集合名时可直接使用 query/aggregate，无需先 discover。
不确定有哪些数据时，用 discover 探索可用集合。
source_ref 可引用会话中前序步骤的数据，避免重复查询。"""

    category = "data"
    tags = ["查询", "数据", "动态", "集合", "聚合", "统计"]

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["discover", "schema", "query", "aggregate"],
                "description": "操作模式",
            },
            "collection": {
                "type": "string",
                "description": "集合名称（schema/query/aggregate时必填）",
            },
            "filters": {
                "type": "array",
                "description": "查询条件数组，每项: {field, op, value}。op支持: eq/ne/gt/gte/lt/lte/in/nin/contains/regex/exists",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "op": {
                            "type": "string",
                            "enum": ["eq", "ne", "gt", "gte", "lt", "lte",
                                     "in", "nin", "contains", "regex", "exists"],
                        },
                        "value": {"description": "比较值，类型取决于字段"},
                    },
                },
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "返回字段列表（不指定则返回全部字段）",
            },
            "sort": {
                "type": "array",
                "description": "排序规则: [{field, direction: asc/desc}]",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "direction": {"type": "string", "enum": ["asc", "desc"]},
                    },
                },
            },
            "limit": {
                "type": "integer",
                "description": "返回数量上限，默认50，最大500。查询历史行情等大批量数据时请设置为所需条数（如一年日线设 limit=260）",
            },
            "skip": {
                "type": "integer",
                "description": "跳过前N条（分页用）",
            },
            "source_ref": {
                "type": "string",
                "description": "引用会话中前序步骤的数据集，如 'step_1'。指定后直接使用该数据，无需重新查询数据库。",
            },
            "domain": {
                "type": "string",
                "description": "业务域过滤（discover时可选，如 product/asset/customer）",
            },
            "group_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "聚合分组字段（aggregate时使用）",
            },
            "metrics": {
                "type": "array",
                "description": "聚合指标: [{field, agg, alias}]。agg支持: sum/avg/count/min/max/first/last",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "agg": {
                            "type": "string",
                            "enum": ["sum", "avg", "count", "min", "max", "first", "last"],
                        },
                        "alias": {"type": "string"},
                    },
                },
            },
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> dict:
        """执行数据查询操作 — 调度器"""
        # ── source_ref 引用机制：优先从 DataContext 获取前序数据 ──
        source_ref: str | None = kwargs.get("source_ref")
        if source_ref:
            conversation_id: str | None = kwargs.get("conversation_id")
            if not conversation_id:
                result = ToolResult.error("source_ref 需要会话上下文，缺少 conversation_id")
                result["_lineage_meta"] = self._build_lineage_meta(
                    operation="query", collection="", fields=[], result_count=0
                )
                return result
            from app.agent.services.data_context import DataContext
            ctx = DataContext.get_instance(conversation_id)
            ref_data = ctx.get(source_ref)
            if ref_data is None:
                available = ctx.list_datasets()
                keys = [d["key"] for d in available]
                result = ToolResult.error(f"数据引用 '{source_ref}' 不存在。可用的数据集：{keys}")
                result["_lineage_meta"] = self._build_lineage_meta(
                    operation="query", collection="", fields=[], result_count=0
                )
                return result
            record_count = len(ref_data) if isinstance(ref_data, list) else 1
            result = ToolResult.success(
                data={"records": ref_data if isinstance(ref_data, list) else [ref_data]},
                summary=f"从 {source_ref} 获取 {record_count} 条记录",
                data_shape="table",
                record_count=record_count,
            )
            result["_lineage_meta"] = self._build_lineage_meta(
                operation="query", collection=f"ref:{source_ref}", fields=[], result_count=record_count
            )
            return result

        action: str = kwargs.get("action", "")

        if action == "discover":
            return await self._handle_discover(**kwargs)
        if action == "schema":
            return await self._handle_schema(**kwargs)
        if action == "query":
            return await self._handle_query(**kwargs)
        if action == "aggregate":
            return await self._handle_aggregate(**kwargs)

        result = ToolResult.error(
            f"不支持的操作: {action}，可选: discover/schema/query/aggregate"
        )
        result["_lineage_meta"] = self._build_lineage_meta(
            operation=action, collection="", fields=[], result_count=0
        )
        return result

    async def _handle_discover(self, **kwargs: Any) -> dict:
        """调度: discover"""
        result = await self._do_discover(kwargs.get("domain"))
        result["_lineage_meta"] = self._build_lineage_meta(
            operation="discover", collection="", fields=[], result_count=0
        )
        return result

    async def _handle_schema(self, **kwargs: Any) -> dict:
        """调度: schema"""
        collection: str = kwargs.get("collection", "")
        if not collection:
            result = ToolResult.error("schema 操作需要指定 collection 参数")
            result["_lineage_meta"] = self._build_lineage_meta(
                operation="schema", collection="", fields=[], result_count=0
            )
            return result
        result = await self._do_schema(collection)
        result["_lineage_meta"] = self._build_lineage_meta(
            operation="schema", collection=collection, fields=[], result_count=0
        )
        return result

    async def _handle_query(self, **kwargs: Any) -> dict:
        """调度: query"""
        collection: str = kwargs.get("collection", "")
        if not collection:
            result = ToolResult.error("query 操作需要指定 collection 参数")
            result["_lineage_meta"] = self._build_lineage_meta(
                operation="query", collection="", fields=[], result_count=0
            )
            return result
        result = await self._do_query(collection, kwargs)
        fields: list[str] = kwargs.get("fields") or []
        record_count = result.get("metadata", {}).get("record_count", 0) if result.get("success") else 0
        result["_lineage_meta"] = self._build_lineage_meta(
            operation="query", collection=collection, fields=fields, result_count=record_count
        )
        return result

    async def _handle_aggregate(self, **kwargs: Any) -> dict:
        """调度: aggregate"""
        collection: str = kwargs.get("collection", "")
        if not collection:
            result = ToolResult.error("aggregate 操作需要指定 collection 参数")
            result["_lineage_meta"] = self._build_lineage_meta(
                operation="aggregate", collection="", fields=[], result_count=0
            )
            return result
        result = await self._do_aggregate(collection, kwargs)
        # 聚合操作：fields 取 group_by + metrics 中的字段
        agg_fields: list[str] = list(kwargs.get("group_by") or [])
        for m in (kwargs.get("metrics") or []):
            if isinstance(m, dict) and m.get("field"):
                agg_fields.append(m["field"])
        record_count = result.get("metadata", {}).get("record_count", 0) if result.get("success") else 0
        result["_lineage_meta"] = self._build_lineage_meta(
            operation="aggregate", collection=collection, fields=agg_fields, result_count=record_count
        )
        return result

    async def _do_discover(self, domain: str | None) -> dict:
        """发现可查询的集合列表（增强版：从 DOMAIN_METADATA 返回丰富元数据）"""
        try:
            # 构建增强的集合列表
            enhanced_collections: list[dict] = []
            domains_summary: dict[str, dict] = {}

            for domain_key, domain_info in DOMAIN_METADATA.items():
                # 域过滤
                if domain and domain_key != domain:
                    continue

                tables = domain_info.get("tables", {})
                domain_display = domain_info.get("display_name", domain_key)
                domain_desc = domain_info.get("description", "")

                # 构建域汇总
                domains_summary[domain_key] = {
                    "name": domain_display,
                    "table_count": len(tables),
                    "description": domain_desc,
                }

                for table_name, table_meta in tables.items():
                    # 推导 related_tables（基于 foreign_keys）
                    fk = table_meta.get("foreign_keys", {})
                    related_tables = list(set(
                        ref.split(".")[0] for ref in fk.values() if "." in ref
                    ))

                    # 也将引用本表的其他表加入 related（反向引用）
                    for other_domain_info in DOMAIN_METADATA.values():
                        for other_table, other_meta in other_domain_info.get("tables", {}).items():
                            if other_table == table_name:
                                continue
                            other_fk = other_meta.get("foreign_keys", {})
                            for ref in other_fk.values():
                                if ref.startswith(f"{table_name}."):
                                    if other_table not in related_tables:
                                        related_tables.append(other_table)
                                    break

                    enhanced_collections.append({
                        "name": table_name,
                        "display_name": table_meta.get("display_name", table_name),
                        "domain": domain_key,
                        "domain_name": domain_display,
                        "description": table_meta.get("description", ""),
                        "record_count": 0,  # 静态元数据，实际数量需运行时查询
                        "key_fields": table_meta.get("key_fields", []),
                        "typical_queries": table_meta.get("typical_queries", []),
                        "related_tables": related_tables,
                    })

            # 尝试从 registry 补充实际 record_count
            try:
                registry_collections = await _registry.list_collections(domain=domain)
                rc_map = {
                    c["collection_name"]: c.get("record_count", 0)
                    for c in registry_collections
                }
                for col in enhanced_collections:
                    if col["name"] in rc_map:
                        col["record_count"] = rc_map[col["name"]]
            except Exception:
                pass  # 非关键，元数据仍可用

            total_tables = len(enhanced_collections)
            summary = f"发现 {total_tables} 个可查询数据集合"
            if domain:
                summary += f"（域: {domain}）"

            return ToolResult.success(
                data={
                    "collections": enhanced_collections,
                    "domains_summary": domains_summary,
                    "total_tables": total_tables,
                },
                summary=summary,
                record_count=total_tables,
                data_shape="list",
            )
        except Exception as e:
            logger.error("[DataQuery] discover 失败: {}", e)
            return ToolResult.error(f"发现集合失败: {e}")

    async def _do_schema(self, collection: str) -> dict:
        """获取集合的完整 Schema"""
        try:
            schema = await _registry.get_schema(collection)
            field_count = len(schema.get("fields", []))
            return ToolResult.success(
                data=schema,
                summary=f"集合 '{collection}' 共 {field_count} 个字段，{schema.get('record_count', 0)} 条记录",
                record_count=field_count,
                data_shape="schema",
            )
        except CollectionNotFoundError as e:
            # 获取可用集合列表提供友好提示
            available = await self._get_available_names()
            hint = f"可用集合: {', '.join(available[:10])}" if available else "暂无可用集合"
            return ToolResult.error(f"{e}。{hint}")
        except Exception as e:
            logger.error("[DataQuery] schema 失败: {}", e)
            return ToolResult.error(f"获取 Schema 失败: {e}")

    async def _do_query(self, collection: str, kwargs: dict) -> dict:
        """条件查询"""
        try:
            filters: list[dict] | None = kwargs.get("filters")
            fields: list[str] | None = kwargs.get("fields")
            sort: list[dict] | None = kwargs.get("sort")
            limit: int = kwargs.get("limit", 50)
            skip: int = kwargs.get("skip", 0)
            try:
                limit = int(limit)
            except (ValueError, TypeError):
                limit = 50
            try:
                skip = int(skip)
            except (ValueError, TypeError):
                skip = 0

            # 合理上限：尊重用户请求，但不超过 500
            limit = max(1, min(limit, 500))

            # 适配排序参数：工具接口用 direction，引擎用 order
            engine_sort: list[dict] | None = None
            if sort:
                engine_sort = [
                    {"field": s["field"], "order": s.get("direction", "asc")}
                    for s in sort
                ]

            result = await _engine.find(
                collection=collection,
                filters=filters,
                fields=fields,
                sort=engine_sort,
                limit=limit,
                skip=skip,
            )

            total = result.get("total", 0)
            data_rows = result.get("data", [])
            page_info = result.get("page_info", {})
            has_more = page_info.get("has_more", False)

            summary = f"查询集合 '{collection}'：返回 {len(data_rows)} 条（共 {total} 条）"
            if has_more:
                summary += "，还有更多数据"

            response_data: dict[str, Any] = {
                "records": data_rows,
                "total": total,
                "page_info": page_info,
            }
            # 传递字段校验警告
            if result.get("warnings"):
                response_data["warnings"] = result["warnings"]

            # 溯源标记：从查询结果或 filters 中识别资产代码与名称，构建 traceable_assets
            try:
                traceable_assets = self._extract_traceable_assets(data_rows, filters)
                # 校验存在性 + 补全名称（不存在的资产标记 valid=false，前端不再请求 K 线）
                if traceable_assets:
                    await self._validate_and_enrich_assets(traceable_assets)
                    # 资产较多时进行主题代表性筛选（标记 is_representative）
                    self._mark_representative_assets(traceable_assets)
                    response_data["traceable_assets"] = traceable_assets
            except Exception as te:  # 非关键路径，失败不阻塞查询
                logger.warning("[DataQuery] traceable_assets 构建失败(non-blocking): {}", te)

            return ToolResult.success(
                data=response_data,
                summary=summary,
                record_count=len(data_rows),
                data_shape="table",
            )
        except CollectionNotFoundError as e:
            available = await self._get_available_names()
            hint = f"可用集合: {', '.join(available[:10])}" if available else "暂无可用集合"
            return ToolResult.error(f"{e}。{hint}")
        except Exception as e:
            logger.error("[DataQuery] query 失败: {}", e)
            return ToolResult.error(f"查询失败: {e}")

    async def _do_aggregate(self, collection: str, kwargs: dict) -> dict:
        """聚合查询"""
        try:
            filters: list[dict] | None = kwargs.get("filters")
            group_by: list[str] | None = kwargs.get("group_by")
            metrics: list[dict] | None = kwargs.get("metrics")

            if not metrics:
                return ToolResult.error("aggregate 操作需要指定 metrics 参数")

            result = await _engine.aggregate(
                collection=collection,
                filters=filters,
                group_by=group_by,
                metrics=metrics,
            )

            data_rows = result.get("data", [])
            group_count = result.get("group_count", 0)

            summary = f"聚合集合 '{collection}'：共 {group_count} 个分组"
            if group_by:
                summary += f"（按 {', '.join(group_by)} 分组）"

            return ToolResult.success(
                data={"groups": data_rows, "group_count": group_count},
                summary=summary,
                record_count=group_count,
                data_shape="aggregate",
            )
        except CollectionNotFoundError as e:
            available = await self._get_available_names()
            hint = f"可用集合: {', '.join(available[:10])}" if available else "暂无可用集合"
            return ToolResult.error(f"{e}。{hint}")
        except Exception as e:
            logger.error("[DataQuery] aggregate 失败: {}", e)
            return ToolResult.error(f"聚合查询失败: {e}")

    async def _get_available_names(self) -> list[str]:
        """获取可用集合名称列表（用于错误提示）"""
        try:
            collections = await _registry.list_collections()
            return [c["collection_name"] for c in collections]
        except Exception:
            return []

    # ── 血缘溯源元数据 ──────────────────────────────────────────────────────────

    def _build_lineage_meta(self, operation: str, collection: str, fields: list, result_count: int) -> dict:
        """构造血缘溯源元数据"""
        meta = {
            "tables_used": [collection] if collection else [],
            "domains_involved": [],
            "fields_accessed": {},
            "join_path": "",
            "records_returned": result_count,
            "query_operation": operation,
        }

        if collection:
            domain = self._infer_domain(collection)
            if domain:
                meta["domains_involved"] = [domain]
            if fields:
                meta["fields_accessed"][collection] = fields

        return meta

    @staticmethod
    def _infer_domain(collection: str) -> str:
        """从集合名推断所属域"""
        prefix_map = {
            "dwd_ast_": "asset",
            "dwd_isr_": "subject",
            "dwd_ptl_": "product",
            "dwd_val_": "valuation",
            "dwd_trn_": "transaction",
            "dwd_sale_": "seller",
            "dwd_cust_": "customer",
            "dwd_rsk_": "risk",
            "dwd_mkt_": "market",
            "tag_ptl_": "product",
        }
        for prefix, domain in prefix_map.items():
            if collection.startswith(prefix):
                return domain
        return ""

    # 公共：可识别为资产代码 / 名称的字段名集合
    _CODE_KEYS = ("asset_code", "code", "symbol", "ticker", "fund_code", "product_code")
    _NAME_KEYS = ("asset_name", "name", "fund_name", "product_name")

    @classmethod
    def _extract_traceable_assets(
        cls,
        data_rows: list[dict],
        filters: list[dict] | None = None,
    ) -> list[dict]:
        """从查询结果或 filters 中提取资产溯源标记。

        识别顺序：
        1) 优先从 records 中识别 code/name 列；
        2) records 中无 code 列时，从 filters 中查找 code 类字段（eq/in）作为兜底，
           解决「按资产过滤后只选择 date/close 列」场景下查询结果不含 code 列的问题。
        """
        seen: set[str] = set()
        result: list[dict] = []

        # 1) 优先：从 records 中识别
        if data_rows:
            sample = data_rows[0] if isinstance(data_rows[0], dict) else None
            if sample:
                code_key = next((k for k in cls._CODE_KEYS if k in sample), None)
                name_key = next((k for k in cls._NAME_KEYS if k in sample), None)
                if code_key:
                    for row in data_rows:
                        if not isinstance(row, dict):
                            continue
                        code_val = row.get(code_key)
                        if code_val is None:
                            continue
                        code_str = str(code_val).strip()
                        if not code_str or code_str in seen:
                            continue
                        seen.add(code_str)
                        name_val = row.get(name_key) if name_key else None
                        name_str = str(name_val).strip() if name_val is not None else ""
                        result.append({
                            "code": code_str,
                            "name": name_str or code_str,
                            "has_kline": True,
                        })

        # 2) 兜底：从 filters 中识别
        if not result and filters:
            for f in filters:
                if not isinstance(f, dict):
                    continue
                field = str(f.get("field", "")).strip().lower()
                op = str(f.get("op", "eq")).lower()
                value = f.get("value")
                if field not in cls._CODE_KEYS:
                    continue
                # 收集 value（eq -> 单值；in/nin -> 列表）
                values: list = []
                if op == "in" and isinstance(value, (list, tuple)):
                    values = list(value)
                elif op in ("eq", "contains", "regex"):
                    if value is not None:
                        values = [value]
                else:
                    continue
                for v in values:
                    if v is None:
                        continue
                    s = str(v).strip()
                    if not s or s in seen:
                        continue
                    seen.add(s)
                    result.append({
                        "code": s,
                        "name": s,  # 名称待后续 _enrich_asset_names 补全
                        "has_kline": True,
                    })
        return result

    @staticmethod
    async def _validate_and_enrich_assets(assets: list[dict]) -> None:
        """校验资产存在性并补全名称。

        - 通过 assets 集合按 code 反查，命中则补名称、保持 has_kline=True
        - 未命中（资产不存在）则打 valid=False、has_kline=False，前端据此降级展示
        非关键路径，失败不抛出。
        """
        if not assets:
            return
        codes = [a.get("code") for a in assets if a.get("code")]
        if not codes:
            return
        # assets 集合的实际字段名是 code/name（见 AssetService.get_asset_by_code），
        # 同时兼容另一种可能的命名 asset_code/asset_name，避免某些集合变体全部反查不命中。
        mapping: dict[str, str] = {}
        candidate_specs = (
            ("code", "name"),
            ("asset_code", "asset_name"),
        )
        for code_field, name_field in candidate_specs:
            try:
                res = await _engine.find(
                    collection="assets",
                    filters=[{"field": code_field, "op": "in", "value": codes}],
                    fields=[code_field, name_field],
                    limit=len(codes),
                )
            except Exception as e:
                logger.warning(
                    "[DataQuery] _validate_and_enrich_assets find 失败 field={}(non-blocking): {}",
                    code_field,
                    e,
                )
                continue
            rows = res.get("data", []) if isinstance(res, dict) else []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                c = str(r.get(code_field, "")).strip()
                n = str(r.get(name_field, "")).strip()
                if c and c not in mapping:
                    mapping[c] = n or c
            # 任一套字段命中足够资产即可提前结束，减少多余查询
            if len(mapping) >= len(codes):
                break
        for a in assets:
            c = a.get("code")
            if c in mapping:
                # 资产存在：补名称
                if not a.get("name") or a.get("name") == c:
                    a["name"] = mapping[c]
                a["valid"] = True
            else:
                # 资产不存在：降级
                a["valid"] = False
                a["has_kline"] = False
        # 直接剔除系统中不存在的资产，避免前端展示 "6999/xh003/3/22" 等无意义 code
        before = len(assets)
        assets[:] = [a for a in assets if a.get("valid") is not False]
        removed = before - len(assets)
        if removed:
            logger.debug(
                "[DataQuery] _validate_and_enrich_assets 过滤无效资产 {}/{} 个",
                removed,
                before,
            )

    # 主题关键词分组：每组优先各选 1 个代表，其余降级为参考
    _THEME_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("A500", ("A500",)),
        ("A1000", ("A1000",)),
        ("沪深300", ("沪深300", "HS300", "SH000300")),
        ("中证500", ("中证500", "ZZ500")),
        ("中证1000", ("中证1000", "ZZ1000")),
        ("创业板", ("创业板", "创业")),
        ("科创", ("科创",)),
        ("红利", ("红利",)),
        ("成长", ("成长",)),
        ("价值", ("价值",)),
        ("消费", ("消费",)),
        ("医药", ("医药", "生物", "医疗")),
        ("科技", ("科技",)),
        ("算力", ("算力", "AI", "人工智能")),
        ("芯片半导体", ("芯片", "半导体")),
        ("通信", ("通信", "5G")),
        ("传媒", ("传媒",)),
        ("金融", ("金融", "银行", "证券", "保险")),
        ("能源", ("能源", "煤炭", "石油", "油气")),
        ("电力", ("电力", "电网")),
        ("新能源", ("新能源", "光伏", "风电")),
        ("汽车", ("汽车",)),
        ("贵金属", ("黄金", "白银", "贵金属", "GLD")),
        ("有色", ("有色", "铜", "铝", "锂")),
        ("地产", ("地产", "房地产")),
        ("基建", ("基建", "建筑")),
        ("军工", ("军工", "国防")),
        ("债券", ("债", "国债", "信用债")),
        ("海外", ("标普", "纳斯达克", "道琼斯", "恒生", "日经", "德国", "SPX", "HSTECH")),
    )
    _REPRESENTATIVE_THRESHOLD = 12

    @classmethod
    def _mark_representative_assets(cls, assets: list[dict]) -> None:
        """按名称关键词聚类，资产数超过阈值时挑选每组代表。

        - assets 数 <= 阈值：全部 is_representative=True
        - 否则：每个主题挑首个匹配资产为代表，主题外资产标记 is_representative=False
        """
        if not assets:
            return
        if len(assets) <= cls._REPRESENTATIVE_THRESHOLD:
            for a in assets:
                a.setdefault("is_representative", True)
            return

        used_themes: set[str] = set()
        for a in assets:
            name = (a.get("name") or "") + " " + (a.get("code") or "")
            theme: str | None = None
            for tname, kws in cls._THEME_KEYWORDS:
                for kw in kws:
                    if kw and kw in name:
                        theme = tname
                        break
                if theme:
                    break
            # 资产无效不参与代表挑选
            if a.get("valid") is False:
                a["is_representative"] = False
                continue
            if theme and theme not in used_themes:
                used_themes.add(theme)
                a["is_representative"] = True
                a["theme"] = theme
            else:
                # 同主题已有代表，或无主题：默认仅前 8 个无主题资产作为代表，其余降级
                a["is_representative"] = False
                if theme:
                    a["theme"] = theme

        # 兜底：若代表数过少（<3），按顺序补足到 8 个
        rep_count = sum(1 for a in assets if a.get("is_representative"))
        if rep_count < 3:
            for a in assets:
                if rep_count >= 8:
                    break
                if a.get("valid") is False:
                    continue
                if not a.get("is_representative"):
                    a["is_representative"] = True
                    rep_count += 1

    @staticmethod
    async def _enrich_asset_names(assets: list[dict]) -> None:
        """补全资产名称：对 name == code 的资产，从 assets 集合查询真实名称。

        非关键路径，失败不抛出。
        """
        if not assets:
            return
        # 找出 name 缺失或与 code 相同的资产
        pending = [a for a in assets if a.get("name") in (None, "", a.get("code"))]
        if not pending:
            return
        codes = [a["code"] for a in pending]
        # assets 集合实际字段为 code/name，同时兼容 asset_code/asset_name。
        mapping: dict[str, str] = {}
        for code_field, name_field in (("code", "name"), ("asset_code", "asset_name")):
            try:
                res = await _engine.find(
                    collection="assets",
                    filters=[{"field": code_field, "op": "in", "value": codes}],
                    fields=[code_field, name_field],
                    limit=len(codes),
                )
            except Exception as e:
                logger.warning(
                    "[DataQuery] _enrich_asset_names find 失败 field={}(non-blocking): {}",
                    code_field,
                    e,
                )
                continue
            rows = res.get("data", []) if isinstance(res, dict) else []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                c = str(r.get(code_field, "")).strip()
                n = str(r.get(name_field, "")).strip()
                if c and n and c not in mapping:
                    mapping[c] = n
            if len(mapping) >= len(codes):
                break
        for a in assets:
            c = a.get("code")
            if c in mapping:
                a["name"] = mapping[c]
