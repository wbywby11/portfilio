"""
智能表路由工具 (SmartTableRouter)
================================

职责：
    根据用户的自然语言问题，从全库 82+ 张表中**自动选取**最相关的 1~N 张表，
    并提供字段映射、关联路径与推荐工具，避免 LLM 把分析固定到单张表导致数据
    不全或溯源失真。

设计原则：
    1. 系统不固定访问某张表 —— LLM 拿到候选清单后自己决定查 1 张还是 N 张
    2. 评分基于真实业务语义（display_name / description / key_fields /
       typical_queries），而不是表名前缀字符串
    3. 输出可直接驱动后续工具调用：
       - tables_selected：候选表清单（含相关度评分）
       - join_hints：基于 foreign_keys 自动推断的连接路径
       - recommended_tools：根据候选表所属域推荐合适的查询工具
       - lineage_baseline：预填血缘元数据，确保后续工具调用都带溯源

使用示例：
    smart_table_router(question="按省份统计高风险主体分布", top_k=3)
    smart_table_router(question="哪些产品的机构持有占比最高", top_k=5)
    smart_table_router(question="风险等级为高的主体持有了哪些产品", top_k=8,
                       enable_cross_table=True)
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.services.collection_registry import DOMAIN_METADATA

# 视图源：DataHub 场景视图 / L3 跨域画像 / L4 共振画像
try:
    from app.services.semantic_profiles.static_profiles.datahub_scenario_views import (
        DATAHUB_SCENARIO_VIEWS,
    )
except Exception:  # pragma: no cover
    DATAHUB_SCENARIO_VIEWS = {}

try:
    from app.services.semantic_profiles.static_profiles.l3_profiles import (
        CROSS_DOMAIN_PROFILES,
    )
except Exception:
    CROSS_DOMAIN_PROFILES = {}

try:
    from app.services.semantic_profiles.static_profiles.l4_profiles import (
        RESONANCE_PROFILES,
    )
except Exception:
    RESONANCE_PROFILES = {}


# ── 业务关键词字典（语义→候选表/域） ──────────────────────────────────────
# key 是常见业务词，value 是该词高度暗示的表名（用于加权评分）
_BUSINESS_KEYWORDS: dict[str, list[str]] = {
    # 主体/风险/舆情
    "风险": ["subject_risk_records", "dwd_isr_sentiment", "dwd_rsk_alert", "dwd_rsk_credit", "dwd_ptl_risk", "dwd_cust_risk"],
    "舆情": ["subject_risk_records", "dwd_isr_sentiment"],
    "主体": ["subject_risk_records", "dwd_isr_institution", "dwd_isr_rating", "dwd_isr_sentiment"],
    "企业": ["subject_risk_records", "dwd_isr_institution", "dwd_isr_institution_finance"],
    "信号": ["subject_risk_records", "dwd_isr_sentiment", "dwd_rsk_sentiment"],
    "评级": ["dwd_isr_rating", "dwd_mkt_rating", "dwd_mkt_rating_change"],
    # 产品
    "产品": ["zysc_ptl_info_records", "dwd_ptl_info", "dwd_ptl_manager"],
    "理财": ["zysc_ptl_info_records", "dwd_ptl_info"],
    "持有人": ["zysc_ptl_holder_records", "dwd_ptl_holder_summary"],
    "持仓": ["dwd_ptl_pstn_detail", "dwd_ptl_ast_hld"],
    # 资产
    "资产": ["dwd_ast_info", "dwd_ast_yield_info", "dwd_ast_info_ch"],
    "债券": ["dwd_ast_info", "dwd_mkt_bond", "dwd_ast_info_ch"],
    "基金": ["dwd_mkt_fund", "dwd_ast_fund_manager"],
    "股票": ["dwd_mkt_stock", "dwd_mkt_stock_yield"],
    # 估值/交易
    "估值": ["dwd_val_summary", "dwd_val_detail", "dwd_ast_info_ch"],
    "交易": ["dwd_trn_trade_ptl", "dwd_trn_trade_ast", "dwd_trn_trade_fund"],
    "成交": ["dwd_trn_trade_ptl", "dwd_trn_trade_ast"],
    # 客户/销售
    "客户": ["dwd_cust_info", "dwd_cust_tag", "dwd_cust_trade"],
    "销售": ["dwd_sls_sales", "dwd_seller_info"],
    # 市场
    "汇率": ["dwd_mkt_exrate", "fx_rates"],
    "利率": ["dwd_mkt_rate", "dwd_mkt_rate_quote"],
    # 维度词
    "省份": ["subject_risk_records", "dwd_cust_info"],
    "行业": ["subject_risk_records", "dwd_isr_institution", "dwd_mkt_industry_index"],
    "性质": ["subject_risk_records", "dwd_isr_institution"],
}

# 域 → 推荐工具映射（用于结果中的 recommended_tools 字段）
_DOMAIN_TO_TOOLS: dict[str, list[str]] = {
    "data_hub": ["subject_risk_search", "product_hub_query", "data_query"],
    "asset": ["query_assets", "query_asset_prices", "data_query"],
    "subject": ["data_query", "domain_query"],
    "product": ["data_query", "domain_query"],
    "risk": ["data_query", "domain_query"],
    "market": ["data_query", "domain_query"],
    "transaction": ["data_query", "domain_query"],
    "customer": ["data_query", "domain_query"],
    "valuation": ["data_query", "domain_query"],
    "seller": ["data_query", "domain_query"],
}


def _tokenize_question(question: str) -> set[str]:
    """对中文问题做简单切词：抽取连续中文片段 + 英文/数字片段。"""
    if not question:
        return set()
    # 抽取所有中文 2~6 字片段（滑动窗口）+ 英文单词
    cn_chars = re.findall(r"[\u4e00-\u9fff]+", question)
    tokens: set[str] = set()
    for seg in cn_chars:
        # 单字也保留（覆盖"高/低/黄"等单字风险等级）
        if len(seg) == 1:
            tokens.add(seg)
            continue
        # 滑动窗口生成 2~min(len, 6) 字的子串
        for n in range(2, min(len(seg), 6) + 1):
            for i in range(len(seg) - n + 1):
                tokens.add(seg[i:i + n])
    # 英文/数字
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", question):
        tokens.add(w.lower())
    return tokens


def _score_table(question: str, tokens: set[str], table_name: str, table_meta: dict) -> tuple[float, dict]:
    """
    为单张表计算与问题的相关度得分。
    返回 (score, breakdown)，breakdown 用于解释为什么选中。
    """
    score = 0.0
    breakdown: dict[str, Any] = {
        "matched_keywords": [],
        "matched_fields": [],
        "matched_typical_queries": [],
        "matched_in_description": False,
        "matched_in_display_name": False,
    }

    display_name = table_meta.get("display_name", "") or ""
    description = table_meta.get("description", "") or ""
    key_fields = table_meta.get("key_fields", []) or []
    typical_queries = table_meta.get("typical_queries", []) or []

    # 1. 业务关键词命中（最高权重）
    for kw, target_tables in _BUSINESS_KEYWORDS.items():
        if kw in question and table_name in target_tables:
            score += 5.0
            breakdown["matched_keywords"].append(kw)

    # 2. display_name 直接命中
    for tok in tokens:
        if len(tok) >= 2 and tok in display_name:
            score += 3.0
            breakdown["matched_in_display_name"] = True
            break

    # 3. description 命中
    desc_hits = 0
    for tok in tokens:
        if len(tok) >= 2 and tok in description:
            desc_hits += 1
    if desc_hits > 0:
        score += min(desc_hits * 0.8, 4.0)
        breakdown["matched_in_description"] = True

    # 4. key_fields 命中（字段名常用中文翻译/英文缩写）
    matched_fields = []
    for fld in key_fields:
        fld_lower = fld.lower()
        for tok in tokens:
            if len(tok) >= 2 and (tok in fld_lower or tok in fld):
                matched_fields.append(fld)
                score += 1.5
                break
    breakdown["matched_fields"] = list(set(matched_fields))[:6]

    # 5. typical_queries 命中（最能反映"问句意图"）
    for tq in typical_queries:
        # 计算 question 与 tq 的字符重合度
        common = sum(1 for tok in tokens if len(tok) >= 2 and tok in tq)
        if common >= 1:
            score += min(common * 1.2, 3.0)
            breakdown["matched_typical_queries"].append(tq)

    return score, breakdown


def _build_join_hints(selected: list[dict]) -> list[dict]:
    """根据 foreign_keys 推断候选表之间的连接路径。"""
    name_set = {item["table"] for item in selected}
    hints: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for item in selected:
        table = item["table"]
        fk = item.get("foreign_keys", {}) or {}
        for left_field, ref in fk.items():
            if "." not in ref:
                continue
            right_table, right_field = ref.split(".", 1)
            if right_table in name_set:
                pair = tuple(sorted([table, right_table]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                hints.append({
                    "left_table": table,
                    "left_field": left_field,
                    "right_table": right_table,
                    "right_field": right_field,
                    "join_type": "inner",
                    "reason": "foreign_key",
                })
    return hints


# ============================================================
# 视图评分（场景视图 / L3 跨域 / L4 共振）
# ============================================================

def _score_view(question: str, tokens: set[str], view_text_fields: list[str],
                tables_involved: list[str], domains_involved: list[str]) -> tuple[float, dict]:
    """为一个视图（场景/L3/L4）计算与问题的相关度得分。

    评分维度：
      1) 名称/描述/场景描述的 token 命中（主要语义匹配）
      2) tables_involved 中的表含「在问题中出现的业务词」的数量（体现多表价值）
      3) 多域加成：问题同时涉及多个域时，跨域视图得分高
    """
    score = 0.0
    breakdown: dict[str, Any] = {
        "matched_tokens": [],
        "matched_tables": [],
        "matched_domains": [],
        "multi_domain_bonus": 0.0,
    }

    full_text = " ".join(view_text_fields)
    # 1) 文本命中
    text_hits = 0
    matched: set[str] = set()
    for tok in tokens:
        if len(tok) >= 2 and tok in full_text:
            text_hits += 1
            matched.add(tok)
    if text_hits > 0:
        score += min(text_hits * 1.2, 8.0)
        breakdown["matched_tokens"] = list(matched)[:8]

    # 2) tables_involved 与问题业务词的交集
    matched_tables: list[str] = []
    for tbl in tables_involved:
        # 表名本身在问题中（用户主动提及表名）
        if tbl in question:
            score += 4.0
            matched_tables.append(tbl)
            continue
        # 表名含的关键词被问题覆盖
        # 例如 question 含"风险"，tbl=subject_risk_records
        for kw, target_tables in _BUSINESS_KEYWORDS.items():
            if kw in question and tbl in target_tables:
                score += 1.5
                if tbl not in matched_tables:
                    matched_tables.append(tbl)
                break
    breakdown["matched_tables"] = matched_tables[:8]

    # 3) 多域加成：问题是否同时涉及多个域的业务词
    domain_hits: set[str] = set()
    domain_keywords = {
        "asset": ["资产", "债券", "股票", "基金", "AST"],
        "product": ["产品", "理财", "组合", "持仓"],
        "subject": ["主体", "企业", "机构", "发行人"],
        "risk": ["风险", "信用", "预警", "舆情"],
        "market": ["行情", "市场", "利率", "曲线", "汇率"],
        "valuation": ["估值", "净值", "财报"],
        "transaction": ["交易", "成交", "订单"],
        "customer": ["客户", "申赎"],
        "data_hub": ["外部", "上游", "导入", "接口"],
    }
    for d in domains_involved:
        kws = domain_keywords.get(d, [])
        for kw in kws:
            if kw in question:
                domain_hits.add(d)
                break
    breakdown["matched_domains"] = sorted(domain_hits)
    if len(domain_hits) >= 2:
        # 多域问题命中跨域视图，加成很大
        bonus = min(len(domain_hits) * 2.5, 8.0)
        score += bonus
        breakdown["multi_domain_bonus"] = bonus

    return score, breakdown


def _collect_view_candidates(question: str, tokens: set[str], min_score: float) -> list[dict]:
    """扫描 S1-S5 场景、L3 跨域、L4 共振画像，返回超过阈值的视图候选。"""
    out: list[dict] = []

    # 1) DataHub 场景视图 S1-S5
    for vid, sv in DATAHUB_SCENARIO_VIEWS.items():
        text_fields = [
            getattr(sv, "scenario_name", "") or "",
            getattr(sv, "description", "") or "",
            " ".join(getattr(sv, "analysis_dimensions", []) or []),
            " ".join(getattr(sv, "tables_involved", []) or []),
        ]
        tables_involved = list(getattr(sv, "tables_involved", []) or [])
        # 根据表名推断实际涉及的业务域（不仅仅是 data_hub）
        domains: list[str] = ["data_hub"]
        for tbl in tables_involved:
            tbl_low = tbl.lower()
            if "risk" in tbl_low and "risk" not in domains:
                domains.append("risk")
            if "subject" in tbl_low and "subject" not in domains:
                domains.append("subject")
            if "holder" in tbl_low or "_ptl_" in tbl_low or "ptl_info" in tbl_low:
                if "product" not in domains:
                    domains.append("product")
            if "holder" in tbl_low and "customer" not in domains:
                domains.append("customer")
        score, breakdown = _score_view(question, tokens, text_fields, tables_involved, domains)
        # 可执行场景加成：能直接产出结果的视图优先级更高
        if score > 0:
            score += 3.0
            breakdown["executable_bonus"] = 3.0
        if score < min_score:
            continue
        out.append({
            "view_id": vid,
            "view_type": "datahub_scenario",
            "view_name": getattr(sv, "scenario_name", vid),
            "description": getattr(sv, "description", ""),
            "tables_involved": tables_involved,
            "domains_involved": domains,
            "analysis_dimensions": list(getattr(sv, "analysis_dimensions", []) or [])[:8],
            "score": round(score, 2),
            "match_reason": breakdown,
            "executable": True,  # 可通过 execute_scenario 执行
            "executor_hint": "semantic_profile(operation='scenario_view', target='" + vid + "')",
        })

    # 2) L3 跨域画像
    for pid, p in CROSS_DOMAIN_PROFILES.items():
        text_fields = [
            getattr(p, "profile_name", "") or "",
            getattr(p, "structure", "") or "",
            getattr(p, "distribution", "") or "",
            getattr(p, "trend", "") or "",
            getattr(p, "anomaly", "") or "",
            " ".join(getattr(p, "scenarios", []) or []),
            " ".join(getattr(p, "tables_involved", []) or []),
        ]
        tables_involved = list(getattr(p, "tables_involved", []) or [])
        domains = list(getattr(p, "domains_involved", []) or [])
        score, breakdown = _score_view(question, tokens, text_fields, tables_involved, domains)
        if score < min_score:
            continue
        out.append({
            "view_id": pid,
            "view_type": "l3_cross_domain",
            "view_name": getattr(p, "profile_name", pid),
            "description": (getattr(p, "structure", "") or "")[:200],
            "tables_involved": tables_involved,
            "domains_involved": domains,
            "join_path": getattr(p, "join_path", ""),
            "scenarios": list(getattr(p, "scenarios", []) or [])[:6],
            "score": round(score, 2),
            "match_reason": breakdown,
            "executable": False,  # L3 是描述性画像，需 LLM 手动拼 join
            "executor_hint": "参考 join_path 调用 domain_query(action='join') 或多次 data_query 后在应用层关联",
        })

    # 3) L4 共振画像
    for pid, p in RESONANCE_PROFILES.items():
        text_fields = [
            getattr(p, "scenario_name", "") or "",
            getattr(p, "structure", "") or "",
            getattr(p, "resonance_chain", "") or "",
            getattr(p, "extreme_features", "") or "",
            " ".join(getattr(p, "warning_indicators", []) or []),
            " ".join(getattr(p, "scenarios", []) or []),
        ]
        # L4 画像不直接绑定 tables，仅有 domains
        tables_involved: list[str] = []
        domains = list(getattr(p, "domains_involved", []) or [])
        score, breakdown = _score_view(question, tokens, text_fields, tables_involved, domains)
        if score < min_score:
            continue
        out.append({
            "view_id": pid,
            "view_type": "l4_resonance",
            "view_name": getattr(p, "scenario_name", pid),
            "description": (getattr(p, "structure", "") or "")[:200],
            "tables_involved": tables_involved,
            "domains_involved": domains,
            "resonance_chain": getattr(p, "resonance_chain", ""),
            "warning_indicators": list(getattr(p, "warning_indicators", []) or [])[:6],
            "scenarios": list(getattr(p, "scenarios", []) or [])[:6],
            "score": round(score, 2),
            "match_reason": breakdown,
            "executable": False,
            "executor_hint": "采用 semantic_profile(operation='resonance', target='" + pid + "') 查看全貌，按 warning_indicators 逐个查表",
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


class SmartTableRouterTool(BaseTool):
    """智能表路由：根据问题自动选取 1~N 张相关表"""

    name = "smart_table_router"
    description = (
        "【智能表/视图路由】根据自然语言问题同时选取「单表」与「多表跨域视图」。**处理不确定表/视图的问题时的首选第一步**：\n"
        "1. **单表选取**：从全库 82+ 张表中按 description/key_fields/typical_queries 评分，返回 top-N 候选表\n"
        "2. **多表跨域视图选取**：从 18 个预定义视图（DataHub 场景 S1-S5、L3 跨域画像 7 个、L4 共振画像 6 个）中评分选出最相关的视图\n"
        "3. 返回的 tables_selected 可驱动 data_query/domain_query/subject_risk_search；views_selected 可驱动 semantic_profile(operation='scenario_view'/'cross_domain'/'resonance')\n"
        "4. 多域问题会自动加成跨域视图评分；DataHub 场景视图可直接执行（executable=true），L3/L4 为描述性画像\n\n"
        "适用场景：\n"
        "- 问题含业务词但没指定表名/视图名\n"
        "- 不确定查 1 张表 vs 需要多表 join vs 调用预定义场景\n"
        "- 跨域问题（例如「高风险主体对产品持仓的影响」同时涉及主体/产品两个域）\n\n"
        "**禁止**：跳过本工具直接猜表名或视图 ID。"
    )
    category = "data"
    tags = ["路由", "智能选表", "跨表", "跨域视图", "溯源"]
    
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "用户的自然语言问题（必填），如「按省份统计高风险主体分布」",
            },
            "top_k": {
                "type": "integer",
                "description": "返回最相关的 N 张表，默认 5，最大 15",
            },
            "top_k_views": {
                "type": "integer",
                "description": "返回最相关的 N 个视图（场景/L3/L4），默认 3，最大 10；设为 0 则不返回视图",
            },
            "min_score": {
                "type": "number",
                "description": "表最小相关度得分阈值，默认 1.5",
            },
            "min_view_score": {
                "type": "number",
                "description": "视图最小相关度得分阈值，默认 2.0",
            },
            "domain_filter": {
                "type": "string",
                "description": "可选：限定到某个域（asset/subject/product/data_hub/...）",
            },
            "enable_cross_table": {
                "type": "boolean",
                "description": "是否启用跨表关系扩展（默认 true）：根据外键自动加入相关表",
            },
            "view_types": {
                "type": "array",
                "items": {"type": "string", "enum": ["datahub_scenario", "l3_cross_domain", "l4_resonance"]},
                "description": "可选：限定视图类型，不传为全部",
            },
        },
        "required": ["question"],
    }

    async def execute(self, **kwargs) -> dict:
        question = (kwargs.get("question") or "").strip()
        if not question:
            return ToolResult.error("question 不能为空")

        top_k = max(1, min(15, int(kwargs.get("top_k") or 5)))
        top_k_views = max(0, min(10, int(kwargs.get("top_k_views") or 3)))
        min_score = float(kwargs.get("min_score") or 1.5)
        min_view_score = float(kwargs.get("min_view_score") or 2.0)
        domain_filter = (kwargs.get("domain_filter") or "").strip() or None
        enable_cross_table = bool(kwargs.get("enable_cross_table", True))
        view_types_filter = kwargs.get("view_types") or []

        try:
            tokens = _tokenize_question(question)
            scored: list[dict] = []

            # 遍历所有域所有表，逐张评分
            for domain_key, domain_info in DOMAIN_METADATA.items():
                if domain_filter and domain_key != domain_filter:
                    continue
                tables = domain_info.get("tables", {}) or {}
                for table_name, table_meta in tables.items():
                    score, breakdown = _score_table(question, tokens, table_name, table_meta)
                    if score < min_score:
                        continue
                    scored.append({
                        "table": table_name,
                        "domain": domain_key,
                        "domain_name": domain_info.get("display_name", domain_key),
                        "display_name": table_meta.get("display_name", table_name),
                        "description": table_meta.get("description", ""),
                        "key_fields": table_meta.get("key_fields", [])[:10],
                        "primary_keys": table_meta.get("primary_keys", []),
                        "foreign_keys": table_meta.get("foreign_keys", {}),
                        "typical_queries": table_meta.get("typical_queries", [])[:3],
                        "score": round(score, 2),
                        "match_reason": breakdown,
                    })

            # 按得分降序，取 top_k
            scored.sort(key=lambda x: x["score"], reverse=True)
            primary = scored[:top_k]

            # 跨表扩展：把候选表外键引用的表也加入（即使原本得分低）
            if enable_cross_table and primary:
                primary_names = {t["table"] for t in primary}
                added: list[dict] = []
                for item in primary:
                    fk = item.get("foreign_keys", {}) or {}
                    for ref in fk.values():
                        if "." not in ref:
                            continue
                        ref_table = ref.split(".", 1)[0]
                        if ref_table in primary_names:
                            continue
                        # 找到 ref_table 元数据
                        for d_key, d_info in DOMAIN_METADATA.items():
                            if ref_table in d_info.get("tables", {}):
                                t_meta = d_info["tables"][ref_table]
                                added.append({
                                    "table": ref_table,
                                    "domain": d_key,
                                    "domain_name": d_info.get("display_name", d_key),
                                    "display_name": t_meta.get("display_name", ref_table),
                                    "description": t_meta.get("description", ""),
                                    "key_fields": t_meta.get("key_fields", [])[:10],
                                    "primary_keys": t_meta.get("primary_keys", []),
                                    "foreign_keys": t_meta.get("foreign_keys", {}),
                                    "typical_queries": t_meta.get("typical_queries", [])[:3],
                                    "score": 0.5,
                                    "match_reason": {
                                        "expanded_via_foreign_key": True,
                                        "referenced_by": item["table"],
                                    },
                                })
                                primary_names.add(ref_table)
                                break
                primary.extend(added)

            # 推断连接路径
            join_hints = _build_join_hints(primary)

            # 推荐工具
            recommended_tools: list[str] = []
            for item in primary:
                for t in _DOMAIN_TO_TOOLS.get(item["domain"], ["data_query"]):
                    if t not in recommended_tools:
                        recommended_tools.append(t)

            # 涉及的域
            domains_involved = sorted({item["domain"] for item in primary})

            # ── 视图选取（场景视图 / L3 / L4） ──
            views_selected: list[dict] = []
            if top_k_views > 0:
                all_views = _collect_view_candidates(question, tokens, min_view_score)
                if view_types_filter:
                    all_views = [v for v in all_views if v["view_type"] in view_types_filter]
                views_selected = all_views[:top_k_views]
                # 视图里出现的表同步合并到 domains_involved
                for v in views_selected:
                    for d in v.get("domains_involved", []):
                        if d not in domains_involved:
                            domains_involved.append(d)
                domains_involved = sorted(set(domains_involved))

            # 构造摘要（让 LLM 一眼能理解）
            summary_lines = [
                f"【智能路由】问题「{question}」 命中 {len(primary)} 张表、{len(views_selected)} 个视图，涉及 {len(domains_involved)} 个域："
            ]
            # 单表候选
            if primary:
                summary_lines.append("【单表候选】")
                for item in primary[:8]:
                    kws = item.get("match_reason", {}).get("matched_keywords", [])
                    kw_str = f"，关键词={kws}" if kws else ""
                    summary_lines.append(
                        f"  • [{item['domain']}] {item['table']}（{item['display_name']}, score={item['score']}{kw_str}）"
                    )
                if len(primary) > 8:
                    summary_lines.append(f"  ... 还有 {len(primary) - 8} 张表")
            # 多表跨域视图候选
            if views_selected:
                summary_lines.append("【多表跨域视图候选】")
                view_type_label = {
                    "datahub_scenario": "📊 场景视图",
                    "l3_cross_domain": "🔗 L3跨域画像",
                    "l4_resonance": "🔥 L4共振画像",
                }
                for v in views_selected:
                    label = view_type_label.get(v["view_type"], v["view_type"])
                    exec_flag = "✅可执行" if v.get("executable") else "仅描述"
                    domains_str = "·".join(v.get("domains_involved", []))
                    tables_count = len(v.get("tables_involved", []))
                    summary_lines.append(
                        f"  {label} {v['view_id']}（{v['view_name']}, score={v['score']}, {exec_flag}, 表数={tables_count}, 域=[{domains_str}]）"
                    )
                    if v.get("join_path"):
                        summary_lines.append(f"     join_path: {v['join_path'][:120]}{'...' if len(v.get('join_path', '')) > 120 else ''}")
            # 关联路径
            if join_hints:
                summary_lines.append(f"💡 推断表间连接路径 {len(join_hints)} 条：")
                for h in join_hints[:5]:
                    summary_lines.append(
                        f"  - {h['left_table']}.{h['left_field']} → {h['right_table']}.{h['right_field']}"
                    )
            summary_lines.append(f"🔧 推荐使用工具：{', '.join(recommended_tools)}")
            summary_lines.append(
                "⚠️ 【重要】下一步必须基于 tables_selected/views_selected 中的实际表名或视图 ID 调用查询工具，"
                "禁止使用本结果之外的表名/视图 ID；最终回答的数据溯源以查询工具返回的 _lineage_meta 为准。"
            )
            summary = "\n".join(summary_lines)

            result = ToolResult.success(
                data={
                    "question": question,
                    "tables_selected": primary,
                    "views_selected": views_selected,
                    "join_hints": join_hints,
                    "recommended_tools": recommended_tools,
                    "domains_involved": domains_involved,
                    "total_candidates_evaluated": sum(
                        len(d.get("tables", {})) for d in DOMAIN_METADATA.values()
                    ),
                    "total_views_evaluated": (
                        len(DATAHUB_SCENARIO_VIEWS) + len(CROSS_DOMAIN_PROFILES) + len(RESONANCE_PROFILES)
                    ),
                    "params": {
                        "top_k": top_k,
                        "top_k_views": top_k_views,
                        "min_score": min_score,
                        "min_view_score": min_view_score,
                        "domain_filter": domain_filter,
                        "enable_cross_table": enable_cross_table,
                        "view_types": view_types_filter,
                    },
                },
                summary=summary,
                record_count=len(primary) + len(views_selected),
                data_shape="routing",
            )

            # 预填血缘元数据 baseline（路由阶段只读取元数据，未访问业务数据）
            # 表名合集：单表 + 视图中的表
            all_lineage_tables = [item["table"] for item in primary]
            for v in views_selected:
                for tbl in v.get("tables_involved", []):
                    if tbl not in all_lineage_tables:
                        all_lineage_tables.append(tbl)
            result["_lineage_meta"] = {
                "tables_used": all_lineage_tables,
                "domains_involved": domains_involved,
                "fields_accessed": {
                    item["table"]: item.get("key_fields", []) for item in primary
                },
                "views_referenced": [
                    {"view_id": v["view_id"], "view_type": v["view_type"], "view_name": v["view_name"]}
                    for v in views_selected
                ],
                "join_path": " | ".join(
                    f"{h['left_table']}.{h['left_field']}={h['right_table']}.{h['right_field']}"
                    for h in join_hints
                ),
                "records_returned": 0,
                "total_in_collection": 0,
                "query_operation": "smart_table_router",
                "note": "本结果仅基于元数据评分推荐，实际数据访问以后续工具的 _lineage_meta 为准",
            }
            return result

        except Exception as e:
            logger.exception("[SmartTableRouter] 执行失败: {}", e)
            return ToolResult.error(f"智能路由失败: {e}")
