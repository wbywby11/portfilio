"""
语义画像查询工具

为Agent提供数据语义画像的统一访问入口。在进行数据查询/分析前，
应先调用本工具了解数据表的业务画像，避免盲目查询。

支持7种操作：
- overview        : 9大业务域全景概览
- table_profile   : L1 单表画像
- domain_profile  : L2 域内关联画像
- cross_domain    : L3 跨域穿透画像
- resonance       : L4 域间联动画像
- search          : 按关键词搜索最相关画像
- scenario_view   : 查询/执行典型分析场景视图
"""

from difflib import get_close_matches
from typing import Any

from loguru import logger

from app.agent.tools.base import BaseTool
from app.services.semantic_profiles.profile_engine import ProfileEngine
from app.services.semantic_profiles.profile_merger import ProfileMerger


class SemanticProfileTool(BaseTool):
    """数据语义画像查询工具"""

    name = "semantic_profile"
    description = """数据语义画像查询工具。在进行数据查询分析前，应先调用此工具了解数据表的业务画像。

支持7种操作：
- overview: 获取9大业务域全景概览，了解系统数据全貌
- table_profile: 获取指定表的L1单表画像（业务语义、分布、趋势、异常、适用场景）
- domain_profile: 获取指定域的L2域内关联画像（表间关联结构、一致性约束）
- cross_domain: 获取L3跨域穿透画像（跨域关联路径、业务视图）
- resonance: 获取L4域间联动画像（系统性风险传导链条）
- search: 按业务关键词搜索最相关的画像
- scenario_view: 查询/执行典型分析场景视图（含数据来源标签和查询结果）

使用策略：
1. 不确定查哪张表 → 先调用 overview 或 search
2. 确定了表但不确定字段 → 调用 table_profile
3. 需要跨表分析 → 调用 domain_profile 或 cross_domain
4. 涉及系统性风险分析 → 调用 resonance
5. 需要执行典型分析场景 → 调用 scenario_view"""

    category = "data"
    tags = ["语义", "画像", "数据发现", "元数据", "数据字典"]

    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "overview",
                    "table_profile",
                    "domain_profile",
                    "cross_domain",
                    "resonance",
                    "search",
                    "scenario_view",
                ],
                "description": "操作类型",
            },
            "target": {
                "type": "string",
                "description": (
                    "目标标识。table_profile时为表名(如dwd_ast_info)；"
                    "domain_profile时为域代码(如asset/product/market)；"
                    "cross_domain时为画像ID(如ptl_ast_isr)；"
                    "resonance时为画像ID(如alm_resonance)"
                ),
            },
            "query": {
                "type": "string",
                "description": "search操作时的自然语言搜索词；scenario_view操作时为场景ID(如datahub_s1_high_risk_scan)或关键词",
            },
            "include_dynamic": {
                "type": "boolean",
                "description": "是否包含动态统计数据（实际记录数等），默认true",
                "default": True,
            },
        },
        "required": ["operation"],
    }

    # 已知的可用域代码（用于错误提示）
    _KNOWN_DOMAINS: tuple[str, ...] = (
        "asset", "subject", "product", "valuation",
        "transaction", "customer", "risk", "market", "seller", "data_hub",
    )

    # 域代码 → 中英文双语名称
    _DOMAIN_NAMES: dict[str, dict] = {
        "asset":        {"en": "Asset",        "cn": "资产域"},
        "subject":      {"en": "Subject",      "cn": "主体域"},
        "product":      {"en": "Product",      "cn": "产品域"},
        "valuation":    {"en": "Valuation",    "cn": "估值域"},
        "transaction":  {"en": "Transaction",  "cn": "交易域"},
        "customer":     {"en": "Customer",     "cn": "客户域"},
        "risk":         {"en": "Risk",         "cn": "风险域"},
        "market":       {"en": "Market",       "cn": "行情域"},
        "seller":       {"en": "Seller",       "cn": "销售域"},
        "data_hub":     {"en": "DataHub",      "cn": "通用数据接入域"},
    }

    # 表名 → 中文显示名（核心表）
    _TABLE_DISPLAY_NAMES: dict[str, str] = {
        "subject_risk_records":           "主体观点风险记录表",
        "subject_risk_import_batches":    "主体风险导入批次表",
        "zysc_ptl_info_records":          "产品信息记录表",
        "zysc_ptl_info_import_batches":   "产品信息导入批次表",
        "zysc_ptl_holder_records":        "产品持有人汇总记录表",
        "zysc_ptl_holder_import_batches": "产品持有人导入批次表",
        "dwd_ast_info":                   "资产信息主表",
        "dwd_isr_institution":            "机构/发行人主表",
        "dwd_ptl_info":                   "产品主表",
        "dwd_ptl_ast_hld":               "产品持仓明细",
        "dwd_val_summary":               "估值汇总表",
        "dwd_rsk_credit":                "内部信用评级表",
        "dwd_rsk_sentiment":             "舆情事件表",
        "dwd_mkt_bond":                  "债券行情表",
        "dwd_cust_info":                 "客户主表",
    }

    async def execute(self, **kwargs: Any) -> dict:
        """工具执行入口"""
        operation: str = kwargs.get("operation", "")
        target: str = (kwargs.get("target") or "").strip()
        query: str = (kwargs.get("query") or "").strip()
        include_dynamic: bool = kwargs.get("include_dynamic", True)

        try:
            engine = ProfileEngine.get_instance()
            merger = ProfileMerger()

            if operation == "overview":
                result = await self._handle_overview(engine, merger)
                result["_lineage_meta"] = self._build_profile_lineage(
                    operation="semantic_overview", target="", profiles_referenced=[]
                )
                return result

            if operation == "table_profile":
                result = await self._handle_table_profile(
                    engine, merger, target, include_dynamic
                )
                result["_lineage_meta"] = self._build_profile_lineage(
                    operation="semantic_table_profile",
                    target=target,
                    profiles_referenced=[f"l1_{target}"] if target else [],
                )
                return result

            if operation == "domain_profile":
                result = await self._handle_domain_profile(engine, merger, target)
                result["_lineage_meta"] = self._build_profile_lineage(
                    operation="semantic_domain_profile",
                    target=target,
                    profiles_referenced=[f"l2_{target}"] if target else [],
                    domains_involved=[target] if target else [],
                )
                return result

            if operation == "cross_domain":
                result = await self._handle_cross_domain(engine, merger, target)
                result["_lineage_meta"] = self._build_profile_lineage(
                    operation="semantic_cross_domain",
                    target=target,
                    profiles_referenced=[f"l3_{target}"] if target else [],
                )
                return result

            if operation == "resonance":
                result = await self._handle_resonance(engine, merger, target)
                result["_lineage_meta"] = self._build_profile_lineage(
                    operation="semantic_resonance",
                    target=target,
                    profiles_referenced=[f"l4_{target}"] if target else [],
                )
                return result

            if operation == "search":
                result = await self._handle_search(engine, query)
                result["_lineage_meta"] = self._build_profile_lineage(
                    operation="semantic_search",
                    target=query,
                    profiles_referenced=[],
                )
                return result

            if operation == "scenario_view":
                result = await self._handle_scenario_view(engine, query, target)
                result["_lineage_meta"] = self._build_profile_lineage(
                    operation="semantic_scenario_view",
                    target=query or target,
                    profiles_referenced=[],
                    activated_views=[query or target] if (query or target) else [],
                )
                return result

            result = {
                "status": "error",
                "message": (
                    f"未知操作'{operation}'，支持："
                    "overview/table_profile/domain_profile/cross_domain/resonance/search/scenario_view"
                ),
            }
            result["_lineage_meta"] = self._build_profile_lineage(
                operation=f"semantic_{operation}", target="", profiles_referenced=[]
            )
            return result
        except Exception as e:
            logger.exception("[SemanticProfile] 执行失败 operation={}: {}", operation, e)
            result = {"status": "error", "message": f"语义画像查询失败: {e}"}
            result["_lineage_meta"] = self._build_profile_lineage(
                operation=f"semantic_{operation}", target=target, profiles_referenced=[]
            )
            return result

    # ── 各操作处理 ─────────────────────────────────────────

    async def _handle_overview(
        self, engine: ProfileEngine, merger: ProfileMerger
    ) -> dict:
        overviews = await engine.get_overview()
        if not overviews:
            return {"status": "error", "message": "暂无可用的域级概览画像"}
        text = merger.format_overview(overviews)
        return {"status": "success", "data": text}

    async def _handle_table_profile(
        self,
        engine: ProfileEngine,
        merger: ProfileMerger,
        target: str,
        include_dynamic: bool,
    ) -> dict:
        if not target:
            return {
                "status": "error",
                "message": "table_profile操作需要指定target（表名）",
            }
        profile = await engine.get_table_profile(target, include_dynamic)
        if not profile:
            suggestions = self._suggest_tables(target, engine)
            msg = f"未找到表'{target}'的画像"
            if suggestions:
                msg += f"，相近的表：{', '.join(suggestions)}"
            return {
                "status": "error",
                "message": msg,
                "suggestions": suggestions,
            }
        text = merger.format_table_profile(profile)
        return {"status": "success", "data": text}

    async def _handle_domain_profile(
        self, engine: ProfileEngine, merger: ProfileMerger, target: str
    ) -> dict:
        if not target:
            return {
                "status": "error",
                "message": "domain_profile操作需要指定target（域代码）",
            }
        profile = await engine.get_domain_profile(target)
        if not profile:
            available = sorted(engine._intra_domain_profiles.keys()) or list(
                self._KNOWN_DOMAINS
            )
            return {
                "status": "error",
                "message": (
                    f"未找到域'{target}'的画像，可用域：{'/'.join(available)}"
                ),
            }
        text = merger.format_intra_domain_profile(profile)
        return {"status": "success", "data": text}

    async def _handle_cross_domain(
        self, engine: ProfileEngine, merger: ProfileMerger, target: str
    ) -> dict:
        profiles = engine._cross_domain_profiles
        if not target:
            if not profiles:
                return {
                    "status": "error",
                    "message": "暂无可用的L3跨域画像",
                }
            listing = "\n".join(
                f"- {k}: {v.profile_name}" for k, v in profiles.items()
            )
            return {
                "status": "success",
                "data": (
                    f"可用的L3跨域画像：\n{listing}\n\n"
                    "请用target参数指定画像ID获取详情。"
                ),
            }
        profile = await engine.get_cross_domain_profile(target)
        if not profile:
            suggestions = get_close_matches(target, list(profiles.keys()), n=3, cutoff=0.4)
            msg = f"未找到跨域画像'{target}'"
            if suggestions:
                msg += f"，相近的画像：{', '.join(suggestions)}"
            return {"status": "error", "message": msg, "suggestions": suggestions}
        text = merger.format_cross_domain_profile(profile)
        return {"status": "success", "data": text}

    async def _handle_resonance(
        self, engine: ProfileEngine, merger: ProfileMerger, target: str
    ) -> dict:
        profiles = engine._resonance_profiles
        if not target:
            if not profiles:
                return {
                    "status": "error",
                    "message": "暂无可用的L4联动画像",
                }
            listing = "\n".join(
                f"- {k}: {v.scenario_name}" for k, v in profiles.items()
            )
            return {
                "status": "success",
                "data": (
                    f"可用的L4联动画像：\n{listing}\n\n"
                    "请用target参数指定画像ID获取详情。"
                ),
            }
        profile = await engine.get_resonance_profile(target)
        if not profile:
            suggestions = get_close_matches(target, list(profiles.keys()), n=3, cutoff=0.4)
            msg = f"未找到联动画像'{target}'"
            if suggestions:
                msg += f"，相近的画像：{', '.join(suggestions)}"
            return {"status": "error", "message": msg, "suggestions": suggestions}
        text = merger.format_resonance_profile(profile)
        return {"status": "success", "data": text}

    async def _handle_search(self, engine: ProfileEngine, query: str) -> dict:
        if not query:
            return {
                "status": "error",
                "message": "search操作需要指定query参数（自然语言搜索词）",
            }
        results = await engine.search_profiles(query)
        text = self._format_search_results(results, engine, query)
        return {"status": "success", "data": text}

    async def _handle_scenario_view(
        self, engine: ProfileEngine, query: str, target: str
    ) -> dict:
        """处理 scenario_view 操作：查询/执行典型分析场景视图"""
        from app.services.semantic_profiles.static_profiles.datahub_scenario_views import (
            DATAHUB_SCENARIO_VIEWS,
            execute_scenario,
        )

        sid = (query or target or "").strip()

        # 无参数时列出所有可用场景
        if not sid:
            lines = ["可用的典型分析场景视图：\n"]
            for k, sv in DATAHUB_SCENARIO_VIEWS.items():
                lines.append(f"- {k}: {sv.scenario_name}")
                lines.append(f"  描述: {sv.description[:80]}...")
                lines.append(f"  涉及表: {', '.join(sv.tables_involved)}")
                lines.append(f"  分析维度: {', '.join(sv.analysis_dimensions)}")
                lines.append("")
            lines.append("请用 query 参数指定场景ID执行查询。")
            return {"status": "success", "data": "\n".join(lines)}

        # 精确匹配场景ID
        if sid in DATAHUB_SCENARIO_VIEWS:
            sv = DATAHUB_SCENARIO_VIEWS[sid]
            # 构建中英双语来源标签
            source_tags = self._build_source_tags_for_scenario(sv, engine)
            # 尝试执行查询
            try:
                from pymongo import MongoClient
                db = MongoClient("mongodb://localhost:27017")["asset_allocation"]
                results = execute_scenario(sid, db)
                # 构建带来源标签的输出
                output = self._format_scenario_result(sv, results, source_tags)
                return {
                    "status": "success",
                    "data": output,
                    "_source_tags": source_tags,
                    "_activated_view": {
                        "scenario_id": sv.scenario_id,
                        "scenario_name": sv.scenario_name,
                        "tables_involved": sv.tables_involved,
                        "analysis_dimensions": sv.analysis_dimensions,
                        "related_profiles": sv.related_profiles,
                    },
                }
            except Exception as e:
                logger.warning("[ScenarioView] 查询执行失败 {}: {}", sid, e)
                # 查询失败仍返回场景定义
                return {
                    "status": "success",
                    "data": (
                        f"场景: {sv.scenario_name}\n"
                        f"描述: {sv.description}\n"
                        f"涉及表: {', '.join(sv.tables_involved)}\n"
                        f"分析维度: {', '.join(sv.analysis_dimensions)}\n"
                        f"关联画像: {', '.join(sv.related_profiles)}\n\n"
                        f"查询执行异常: {e}"
                    ),
                    "_source_tags": source_tags,
                }

        # 关键词模糊匹配
        matches = []
        for k, sv in DATAHUB_SCENARIO_VIEWS.items():
            searchable = f"{k} {sv.scenario_name} {sv.description}".lower()
            if sid.lower() in searchable:
                matches.append((k, sv))

        if matches:
            lines = [f"匹配到 {len(matches)} 个相关场景：\n"]
            for k, sv in matches:
                lines.append(f"- {k}: {sv.scenario_name}")
                lines.append(f"  {sv.description[:80]}...")
            lines.append("\n请用完整场景ID执行查询。")
            return {"status": "success", "data": "\n".join(lines)}

        return {
            "status": "error",
            "message": f"未找到场景 '{sid}'，可用场景: {', '.join(DATAHUB_SCENARIO_VIEWS.keys())}",
        }

    # ── 辅助方法 ──────────────────────────────────────────

    # ── 血缘溯源元数据 ──────────────────────────────────────────

    @staticmethod
    def _build_profile_lineage(
        operation: str,
        target: str,
        profiles_referenced: list[str],
        domains_involved: list[str] | None = None,
        activated_views: list[str] | None = None,
    ) -> dict:
        """构造语义画像工具的血缘溯源元数据"""
        return {
            "tables_used": [],
            "domains_involved": domains_involved or [],
            "fields_accessed": {},
            "join_path": "",
            "records_returned": 0,
            "query_operation": operation,
            "profiles_referenced": profiles_referenced,
            "activated_views": activated_views or [],
        }

    def _build_source_tags_for_scenario(self, scenario, engine: ProfileEngine) -> dict:
        """为场景视图构建中英双语来源标签"""
        tables = []
        domains = set()
        for t in scenario.tables_involved:
            cn = self._TABLE_DISPLAY_NAMES.get(t, t)
            tables.append({"name": t, "display_name": cn})
            # 从引擎推断域
            tp = engine._table_profiles.get(t)
            if tp and tp.domain:
                domains.add(tp.domain)

        domain_tags = []
        for d in sorted(domains):
            info = self._DOMAIN_NAMES.get(d, {"en": d, "cn": d})
            domain_tags.append({"code": d, "en": info["en"], "cn": info["cn"]})

        return {
            "tables": tables,
            "domains": domain_tags,
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.scenario_name,
        }

    @staticmethod
    def _format_scenario_result(scenario, results: dict, source_tags: dict) -> str:
        """将场景执行结果格式化为可读文本"""
        lines = [
            f"【场景视图: {scenario.scenario_name}】",
            f"场景ID: {scenario.scenario_id}",
            f"涉及表: {', '.join(t['display_name'] + '(' + t['name'] + ')' for t in source_tags['tables'])}",
            f"涉及域: {', '.join(d['cn'] + '(' + d['en'] + ')' for d in source_tags['domains'])}",
            f"分析维度: {', '.join(scenario.analysis_dimensions)}",
            "",
        ]

        for pipeline_name, data in results.items():
            if isinstance(data, list):
                lines.append(f"▸ {pipeline_name}: {len(data)}条结果")
                for i, doc in enumerate(data[:5]):
                    lines.append(f"  [{i+1}] {doc}")
                if len(data) > 5:
                    lines.append(f"  ...还有{len(data)-5}条")
            elif isinstance(data, dict):
                if "error" in data:
                    lines.append(f"▸ {pipeline_name}: 错误 - {data['error']}")
                else:
                    # 多表结果
                    for sub_name, sub_data in data.items():
                        if isinstance(sub_data, list):
                            lines.append(f"▸ {pipeline_name}.{sub_name}: {len(sub_data)}条结果")
                        elif isinstance(sub_data, dict) and "error" in sub_data:
                            lines.append(f"▸ {pipeline_name}.{sub_name}: 错误 - {sub_data['error']}")
            lines.append("")

        if scenario.analysis_narrative:
            lines.append(f"分析叙述模板: {scenario.analysis_narrative[:200]}...")

        return "\n".join(lines)

    def _suggest_tables(self, target: str, engine: ProfileEngine) -> list[str]:
        """根据输入表名做模糊匹配，返回最多5个候选表名。

        匹配策略：
        1. 子串包含（双向）
        2. difflib 近似匹配兜底
        """
        all_tables = list(engine._table_profiles.keys())
        if not all_tables or not target:
            return []

        target_lower = target.lower()
        # 子串包含优先
        substr_hits: list[str] = []
        for t in all_tables:
            tl = t.lower()
            if target_lower in tl or tl in target_lower:
                substr_hits.append(t)
            if len(substr_hits) >= 5:
                break

        if substr_hits:
            return substr_hits[:5]

        # difflib 兜底
        return get_close_matches(target, all_tables, n=5, cutoff=0.4)

    def _format_search_results(
        self, results: dict, engine: ProfileEngine, query: str
    ) -> str:
        """将搜索结果格式化为可读文本"""
        l1 = results.get("l1_tables", []) or []
        l2 = results.get("l2_domains", []) or []
        l3 = results.get("l3_cross_domain", []) or []
        l4 = results.get("l4_resonance", []) or []

        total = len(l1) + len(l2) + len(l3) + len(l4)
        lines: list[str] = [f"【语义画像搜索 - 关键词：{query}】"]
        lines.append(f"共匹配到 {total} 条相关画像\n")

        if l1:
            lines.append(f"■ L1 单表画像（{len(l1)}）：")
            for name in l1[:10]:
                p = engine._table_profiles.get(name)
                disp = p.display_name if p and p.display_name else ""
                purpose = (p.purpose[:40] + "…") if p and len(p.purpose) > 40 else (p.purpose if p else "")
                tail = f"｜{purpose}" if purpose else ""
                lines.append(f"  - {name}（{disp}）{tail}".rstrip("｜"))
            if len(l1) > 10:
                lines.append(f"  …还有 {len(l1) - 10} 张表未列出")
            lines.append("  → 用 operation=table_profile, target=<表名> 获取详情\n")

        if l2:
            lines.append(f"■ L2 域内画像（{len(l2)}）：")
            for name in l2:
                p = engine._intra_domain_profiles.get(name)
                disp = p.domain_name if p and p.domain_name else ""
                lines.append(f"  - {name}（{disp}）")
            lines.append("  → 用 operation=domain_profile, target=<域代码> 获取详情\n")

        if l3:
            lines.append(f"■ L3 跨域画像（{len(l3)}）：")
            for name in l3:
                p = engine._cross_domain_profiles.get(name)
                disp = p.profile_name if p else ""
                lines.append(f"  - {name}: {disp}")
            lines.append("  → 用 operation=cross_domain, target=<画像ID> 获取详情\n")

        if l4:
            lines.append(f"■ L4 联动画像（{len(l4)}）：")
            for name in l4:
                p = engine._resonance_profiles.get(name)
                disp = p.scenario_name if p else ""
                lines.append(f"  - {name}: {disp}")
            lines.append("  → 用 operation=resonance, target=<画像ID> 获取详情\n")

        if total == 0:
            lines.append("未匹配到相关画像。建议：")
            lines.append("  - 尝试更通用的关键词（如『风险』『资产』『净值』）")
            lines.append("  - 或调用 operation=overview 浏览全部业务域")

        return "\n".join(lines).rstrip()
