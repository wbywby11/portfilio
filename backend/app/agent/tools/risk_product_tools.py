"""
主体风险舆情与产品 Hub 专用查询工具。

封装 DataHubService.query_records，提供 LLM 友好参数；
通用 explore 仍走 data_query。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.config.settings import settings
from app.models.data_hub import DataHubFilterClause, DataHubQueryRequest
from app.services.data_hub_service import DataHubService

_hub = DataHubService()

SUBJECT_RISK_CONNECTOR = "subject_opinion_risk"
PRODUCT_CONNECTORS = frozenset({"zysc_dwd_ptl_info", "zysc_dwd_ptl_holder_summary"})

# 同一会话（conversation_id）内上游已成功同步过一次则跳过，避免智能体会话中重复拉超大流量 API
_subject_risk_conv_upstream_done: set[str] = set()

SUBJECT_RISK_SLIM_FIELDS: tuple[str, ...] = (
    "risk_id",
    "biz_date",
    "sign_date",
    "data_date",
    "subject_name",
    "unified_social_credit_code",
    "enterprise_nature",
    "subject_type",
    "industry_classification_gb",
    "risk_signal_level",
    "rule_large",
    "rule_medium",
    "rule_small",
    "affiliated_province",
    "affiliated_city",
    "parent_bank_classify_queue_type",
    "signal_dascribe",
)


def _slim_subject_risk_item(raw: dict, signal_max_len: int = 480) -> dict:
    """仅保留分析常用字段并截断长文本，降低工具结果进入 LLM 前的体量。"""
    out: dict[str, Any] = {}
    for k in SUBJECT_RISK_SLIM_FIELDS:
        if k not in raw:
            continue
        v = raw.get(k)
        if k == "signal_dascribe" and isinstance(v, str) and len(v) > signal_max_len:
            full_len = len(v)
            v = (
                v[:signal_max_len]
                + f"…（共{full_len}字，完整内容在库 subject_risk_records）"
            )
        out[k] = v
    return out


# 同一会话 × connector：产品 Hub 上游已成功同步过则跳过
_product_hub_conv_upstream_done: set[tuple[str, str]] = set()

# 理财产品信息：仅向 LLM 暴露高信号字段，避免单条数十列撑爆上下文
PRODUCT_PTL_SLIM_KEYS: tuple[str, ...] = (
    "产品代码",
    "产品简称",
    "产品名称",
    "产品系列",
    "产品系列细分",
    "产品性质",
    "产品类型",
    "风险等级",
    "产品起息日",
    "产品到期日",
    "募集开始日",
    "估值方法",
    "币种",
    "管理人",
    "合约基准",
    "合约基准上限",
    "合约基准下限",
    "合约基准平均",
    "市场基准",
    "内部基准",
    "交易日历",
    "数据日期",
    "募集方式",
    "产品模式",
)


def _slim_product_ptl_item(raw: dict) -> dict:
    out: dict[str, Any] = {}
    for k in PRODUCT_PTL_SLIM_KEYS:
        if k in raw:
            out[k] = raw.get(k)
    # 部分库内历史字段名下划线写法
    if "合约基准上限" not in out and raw.get("合约基准_上限") is not None:
        out["合约基准上限"] = raw.get("合约基准_上限")
    if "合约基准下限" not in out and raw.get("合约基准_下限") is not None:
        out["合约基准下限"] = raw.get("合约基准_下限")
    if "合约基准平均" not in out and raw.get("合约基准_平均") is not None:
        out["合约基准平均"] = raw.get("合约基准_平均")
    return out


async def _try_sync_subject_risk(
    months: int,
    skip_upstream_sync: bool,
    conversation_id: str | None = None,
    force_upstream_sync: bool = False,
) -> dict[str, Any]:
    """先调上游 getPyResult 类接口落库；异常或非 success/partial 仅记元数据，不影响后续本地查询。"""
    meta: dict[str, Any] = {
        "attempted": False,
        "connector_id": SUBJECT_RISK_CONNECTOR,
        "outcome": "skipped",
    }
    cid = (conversation_id or "").strip()
    if (
        settings.AGENT_SUBJECT_RISK_ONE_SYNC_PER_CONVERSATION
        and cid
        and cid in _subject_risk_conv_upstream_done
        and not skip_upstream_sync
        and not force_upstream_sync
    ):
        meta["reason"] = "conversation_upstream_already_completed_use_local_db"
        return meta

    if skip_upstream_sync or not settings.AGENT_SYNC_HUB_BEFORE_QUERY:
        meta["reason"] = "skip_upstream_sync_or_config_disabled"
        return meta

    start_s, end_s = biz_date_window_for_months(months)
    rownum = max(1, min(int(settings.AGENT_HUB_IMPORT_ROWNUM), 1_000_000))
    timeout = float(settings.AGENT_HUB_IMPORT_TIMEOUT)
    body = {
        "startDate": start_s,
        "endDate": end_s,
        "rownum": rownum,
        "startrow": 1,
        "timeout": timeout,
    }
    meta["attempted"] = True
    meta["import_range"] = {"startDate": start_s, "endDate": end_s}
    try:
        imp = await _hub.import_from_upstream(SUBJECT_RISK_CONNECTOR, body)
    except Exception as e:
        logger.warning("subject_risk_search upstream import exception: {}", e)
        meta["outcome"] = "exception"
        meta["error"] = str(e)
        return meta

    meta["batch_id"] = imp.get("batch_id")
    meta["status"] = imp.get("status")
    meta["error"] = imp.get("error")
    meta["inserted"] = imp.get("inserted")
    meta["updated"] = imp.get("updated")
    meta["total_returned"] = imp.get("total_returned")
    st = str(imp.get("status") or "")
    if st in ("success", "partial"):
        meta["outcome"] = "ok"
        if cid:
            _subject_risk_conv_upstream_done.add(cid)
    else:
        meta["outcome"] = "failed_or_empty"
        logger.info(
            "subject_risk_search upstream import finished with status={} err={}",
            st,
            imp.get("error"),
        )
    return meta


async def _try_sync_product(
    connector_id: str,
    prod_code: Optional[str],
    skip_upstream_sync: bool,
    conversation_id: str | None = None,
    force_upstream_sync: bool = False,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "attempted": False,
        "connector_id": connector_id,
        "outcome": "skipped",
    }
    conv = (conversation_id or "").strip()
    hub_key = (conv, connector_id) if conv else None
    if (
        settings.AGENT_PRODUCT_HUB_ONE_SYNC_PER_CONVERSATION
        and hub_key
        and hub_key in _product_hub_conv_upstream_done
        and not skip_upstream_sync
        and not force_upstream_sync
    ):
        meta["reason"] = "conversation_upstream_already_completed_use_local_db"
        return meta

    if skip_upstream_sync or not settings.AGENT_SYNC_HUB_BEFORE_QUERY:
        meta["reason"] = "skip_upstream_sync_or_config_disabled"
        return meta

    rownum = max(1, min(int(settings.AGENT_HUB_IMPORT_ROWNUM), 1_000_000))
    timeout = float(settings.AGENT_HUB_IMPORT_TIMEOUT)
    cds = (prod_code or "").strip()
    body = {
        "SYS_ID": "",
        "PROD_CDS": cds,
        "asset_tree": None,
        "port_tree": None,
        "rownum": rownum,
        "startrow": 1,
        "timeout": timeout,
    }
    meta["attempted"] = True
    try:
        imp = await _hub.import_from_upstream(connector_id, body)
    except Exception as e:
        logger.warning("product_hub_query upstream import exception: {}", e)
        meta["outcome"] = "exception"
        meta["error"] = str(e)
        return meta

    meta["batch_id"] = imp.get("batch_id")
    meta["status"] = imp.get("status")
    meta["error"] = imp.get("error")
    meta["inserted"] = imp.get("inserted")
    meta["updated"] = imp.get("updated")
    meta["total_returned"] = imp.get("total_returned")
    st = str(imp.get("status") or "")
    if st in ("success", "partial"):
        meta["outcome"] = "ok"
        if hub_key:
            _product_hub_conv_upstream_done.add(hub_key)
    else:
        meta["outcome"] = "failed_or_empty"
        logger.info(
            "product_hub_query upstream import status={} err={}",
            st,
            imp.get("error"),
        )
    return meta


def biz_date_window_for_months(months: int) -> tuple[str, str]:
    """近 N 个月业务日期区间 (start,end)，YYYY-MM-DD，含端点由 Hub gte/lte 表达。"""
    m = max(1, min(int(months), 120))
    end = date.today()
    start = end - timedelta(days=30 * m)
    return start.isoformat(), end.isoformat()


def _normalize_levels(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def build_subject_risk_filters(
    months: int,
    biz_date_field: str,
    affiliated_province: Optional[str] = None,
    industry_contains: Optional[str] = None,
    risk_signal_level: Any = None,
    signal_keyword: Optional[str] = None,
) -> list[DataHubFilterClause]:
    """构造主体风险查询 filters（供单测断言）。"""
    start_s, end_s = biz_date_window_for_months(months)
    field = (biz_date_field or "biz_date").strip() or "biz_date"
    clauses: list[DataHubFilterClause] = [
        DataHubFilterClause(field=field, op="gte", value=start_s),
        DataHubFilterClause(field=field, op="lte", value=end_s),
    ]
    prov = (affiliated_province or "").strip()
    if prov:
        clauses.append(DataHubFilterClause(field="affiliated_province", op="eq", value=prov))
    ind = (industry_contains or "").strip()
    if ind:
        clauses.append(
            DataHubFilterClause(field="industry_classification_gb", op="regex", value=ind)
        )
    levels = _normalize_levels(risk_signal_level)
    if levels:
        clauses.append(DataHubFilterClause(field="risk_signal_level", op="in", value=levels))
    kw = (signal_keyword or "").strip()
    if kw:
        clauses.append(DataHubFilterClause(field="signal_dascribe", op="regex", value=kw))
    return clauses


def _sync_hint_cn(meta: dict[str, Any]) -> str:
    reason = meta.get("reason") or ""
    if reason == "conversation_upstream_already_completed_use_local_db":
        return (
            "本会话内已对当前数据源完成过一次上游同步，本次仅查本地库（避免重复大流量 API）；"
            "需重新拉取请使用 force_upstream_sync=true"
        )
    if not meta.get("attempted"):
        return ""
    oc = meta.get("outcome")
    if oc == "ok":
        ins = meta.get("inserted")
        upd = meta.get("updated")
        tr = meta.get("total_returned")
        return f"上游同步成功（status={meta.get('status')}，本批返回约 {tr} 条，写入 insert≈{ins} update≈{upd}）"
    if oc == "exception":
        return f"上游同步异常已忽略，改查本地库：{meta.get('error', '')[:120]}"
    if oc == "failed_or_empty":
        return f"上游同步未成功（{meta.get('status')}），已改查本地库"
    return ""


class SubjectRiskSearchTool(BaseTool):
    """主体企业风险 / 舆情 / 处罚类记录查询（连接器 subject_opinion_risk → subject_risk_records）"""

    name = "subject_risk_search"
    description = (
        "从主体风险舆情库检索企业相关风险信号与描述。默认会先请求上游接口按当前查询窗口拉数落库，再查 Mongo；"
        "若上游不可达或返回失败，会自动仅查本地已存数据分析。"
        "**同一会话内：上游同步成功过一次后，后续调用默认仅查本地库**（减少重复 API 与超大返回）；"
        "需要强制再拉上游时设 force_upstream_sync=true，或仅本地查设 skip_upstream_sync=true。"
        "深化分析、聚合统计可配合 data_query 查询集合 subject_risk_records。"
        "适用于：某地/某省近数月舆情处罚、行业维度风险聚合、按风险等级筛选、信号描述关键字等。"
        "本题明确落在「主体」「风险」「舆情」「处罚」时请优先本工具，勿与通用 data_query 混用。"
    )
    category = "data"
    tags = ["企业风险", "舆情", "DataHub", "主体"]

    parameters = {
        "type": "object",
        "properties": {
            "months": {
                "type": "integer",
                "description": "回看月数（近 N 个月 biz_date），默认 3，最大约 120",
            },
            "biz_date_field": {
                "type": "string",
                "description": "业务日期字段名，默认 biz_date",
            },
            "affiliated_province": {
                "type": "string",
                "description": "所属省份筛选（精确匹配，例如「江苏省」），可选",
            },
            "industry_contains": {
                "type": "string",
                "description": "行业分类包含的关键字（映射 industry_classification_gb 模糊匹配），可选",
            },
            "risk_signal_level": {
                "description": "风险等级，可为单个字符串或字符串数组（in）",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
            "signal_keyword": {
                "type": "string",
                "description": "风险信号描述 signal_dascribe 中包含的关键字，可选",
            },
            "keyword": {
                "type": "string",
                "description": "全局关键字模糊（主体名、信号描述等 Hub 配置的 keyword_search_fields），与筛选项同时生效",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数 page_size，默认 30，最大 200",
            },
            "page": {
                "type": "integer",
                "description": "页码，从 1 开始",
            },
            "skip_upstream_sync": {
                "type": "boolean",
                "description": "为 true 时跳过上游拉数，仅查本地库（默认 false：按会话策略可能先同步再查）",
            },
            "force_upstream_sync": {
                "type": "boolean",
                "description": "为 true 时无视「每会话只同步一次」限制，强制再请求上游拉数（慎用，数据量大）",
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs) -> dict:
        months = int(kwargs.get("months", 3) or 3)
        biz_field = str(kwargs.get("biz_date_field", "biz_date") or "biz_date").strip() or "biz_date"
        page = max(1, int(kwargs.get("page", 1) or 1))
        raw_limit = kwargs.get("limit", 30)
        try:
            page_size = min(200, max(1, int(raw_limit or 30)))
        except (TypeError, ValueError):
            page_size = 30

        skip_sync = bool(kwargs.get("skip_upstream_sync"))
        force_sync = bool(kwargs.get("force_upstream_sync"))
        conversation_id = str(kwargs.get("conversation_id") or "").strip() or None
        sync_meta = await _try_sync_subject_risk(
            months,
            skip_sync,
            conversation_id=conversation_id,
            force_upstream_sync=force_sync,
        )

        filters = build_subject_risk_filters(
            months=months,
            biz_date_field=biz_field,
            affiliated_province=kwargs.get("affiliated_province"),
            industry_contains=kwargs.get("industry_contains"),
            risk_signal_level=kwargs.get("risk_signal_level"),
            signal_keyword=kwargs.get("signal_keyword"),
        )
        kw = kwargs.get("keyword")
        hub_kw = (str(kw).strip() if kw is not None else "") or None
        req = DataHubQueryRequest(
            page=page,
            page_size=page_size,
            sort_by=biz_field if biz_field != "biz_date" else "biz_date",
            sort_desc=True,
            keyword=(hub_kw or None),
            filters=filters,
        )
        try:
            out = await _hub.query_records(SUBJECT_RISK_CONNECTOR, req)
        except Exception as e:
            logger.exception("subject_risk_search failed")
            return ToolResult.error(f"查询失败：{e}")

        items = out.get("items") or []
        slim_items = [_slim_subject_risk_item(x) for x in items if isinstance(x, dict)]
        total = out.get("total", 0)
        parts = [f"近约 {months} 个月 biz_date"]
        if kwargs.get("affiliated_province"):
            parts.append(f"省={kwargs['affiliated_province']}")
        if kwargs.get("industry_contains"):
            parts.append(f"行业含「{kwargs['industry_contains']}」")
        if _normalize_levels(kwargs.get("risk_signal_level")):
            parts.append(f"等级={kwargs.get('risk_signal_level')}")
        hint = _sync_hint_cn(sync_meta)
        if hint:
            parts.insert(0, hint)

        # 如果上游失败且当前条件查询无结果，尝试放宽条件查询本地库
        if total == 0 and sync_meta.get("outcome") in ("exception", "failed_or_empty"):
            # 用无筛选条件查询，判断本地库是否真的没有数据
            loose_req = DataHubQueryRequest(
                page=1,
                page_size=page_size,
                sort_by="_imported_at",
                sort_desc=True,
                filters=[],
                keyword=None,
            )
            try:
                loose_out = await _hub.query_records(SUBJECT_RISK_CONNECTOR, loose_req)
                loose_total = loose_out.get("total", 0)
            except Exception:
                loose_total = 0

            if loose_total > 0:
                # 本地库有数据，只是当前条件（时间窗口/省份/行业/等级）太严格
                logger.info(
                    "subject_risk_search: 原条件无结果，放宽查询后找到 {} 条本地历史记录",
                    loose_total,
                )
                out = loose_out
                total = loose_total
                items = out.get("items") or []
                slim_items = [_slim_subject_risk_item(x) for x in items if isinstance(x, dict)]
                # 尝试提取本地库数据的日期范围供用户参考
                date_range_hint = ""
                try:
                    dates = [
                        x.get(biz_field) or x.get("biz_date") or ""
                        for x in items if isinstance(x, dict)
                    ]
                    valid_dates = sorted([d for d in dates if d])
                    if valid_dates:
                        date_range_hint = f"（本地数据日期范围：{valid_dates[0]} ~ {valid_dates[-1]}）"
                except Exception:
                    pass
                parts.insert(
                    0,
                    f"⚠️ 上游接口连接失败；按原条件未匹配到数据，已自动放宽查询条件，"
                    f"找到 {loose_total} 条本地历史记录{date_range_hint}",
                )
            else:
                # 本地库确实没有任何数据
                summary = (
                    f"主体风险舆情查询：上游接口同步失败且本地库确实无历史数据，无法获取结果。"
                    "请勿重复调用本工具，建议直接向用户说明数据源暂时不可用。"
                )
                if parts:
                    summary += "；" + "；".join(parts)
                result = ToolResult.success(
                    data={
                        "items": [],
                        "total": 0,
                        "upstream_sync": sync_meta,
                        "_no_retry": True,
                        "_instruction": "数据源不可用，请勿重复调用本工具，直接向用户说明情况。",
                    },
                    summary=summary,
                    record_count=0,
                    data_shape="tabular",
                )
                result["_lineage_meta"] = {
                    "tables_used": ["subject_risk_records"],
                    "domains_involved": ["data_hub"],
                    "fields_accessed": {"subject_risk_records": []},
                    "join_path": "",
                    "records_returned": 0,
                    "total_in_collection": 0,
                    "query_operation": "subject_risk_search",
                }
                return result

        summary = (
            f"主体风险舆情查询：共命中 {total} 条（本页 {len(slim_items)} 条，返回为精简字段；"
            f"完整记录在库 subject_risk_records，可用 data_query 续查）；"
            + "，".join(parts)
        )
        # ⚠️ 反幻觉指令：明确要求只使用实际返回的数据进行分析
        summary += (
            f"\n⚠️ 【重要】本次返回 {len(slim_items)} 条实际数据，请仅基于这些数据进行分析。"
            f"禁止虚构或推测任何统计数字（如记录总数、占比等）。"
            f"如需完整统计，请使用 data_query 的 analyze 功能进行聚合查询。"
        )
        # 当数据量较大时，给 LLM 明确提示不要重复拉取
        if total > 100:
            summary += (
                f"\nℹ️ 数据量较大（{total}条），请基于当前返回的 {len(slim_items)} 条样本数据直接进行分析总结，"
                "无需再次调用 subject_risk_search 或 data_query 重复获取相同数据。"
            )
        result = ToolResult.success(
            data={
                "items": slim_items,
                "items_full_fields_in_db": True,
                "total": total,
                "page": page,
                "page_size": page_size,
                "upstream_sync": sync_meta,
            },
            summary=summary,
            record_count=len(slim_items),
            data_shape="tabular",
        )
        result["_lineage_meta"] = {
            "tables_used": ["subject_risk_records"],
            "domains_involved": ["data_hub"],
            "fields_accessed": {
                "subject_risk_records": [
                    "risk_signal_level", "subject_name", "signal_dascribe",
                    "rule_large", "rule_medium", "rule_small",
                    "affiliated_province", "enterprise_nature",
                    "industry_classification_gb", "biz_date",
                ]
            },
            "join_path": "",
            "records_returned": len(slim_items),
            "total_in_collection": total,
            "query_operation": "subject_risk_search",
        }
        return result


class ProductHubQueryTool(BaseTool):
    """产品信息表 / 持有人汇总已入库数据的受控查询。"""

    name = "product_hub_query"
    description = (
        "查询已接入 Hub 的产品信息（zysc_dwd_ptl_info，Mongo 集合 zysc_ptl_info_records）"
        "或持有人汇总（zysc_dwd_ptl_holder_summary）。"
        "默认先尝试上游同步再查本地；**同一会话内每个 connector 成功同步一次后，后续默认仅查本地**（减重复 API）；"
        "强制刷新设 force_upstream_sync=true；仅本地设 skip_upstream_sync=true。"
        "已知产品代码时务必传 prod_code 以缩小上游拉取。"
        "返回的产品信息行为精简字段列表，完整列可用 data_query 查同一集合；limit 建议不超过 50。"
    )
    category = "data"
    tags = ["产品", "持有人", "DataHub"]

    parameters = {
        "type": "object",
        "properties": {
            "connector_id": {
                "type": "string",
                "enum": ["zysc_dwd_ptl_info", "zysc_dwd_ptl_holder_summary"],
                "description": "数据源：产品信息表 或 产品持有人汇总",
            },
            "prod_code": {
                "type": "string",
                "description": "产品代码精确匹配（字段名「产品代码」），可选",
            },
            "keyword": {
                "type": "string",
                "description": "Hub 关键字模糊（连接器配置的 keyword_search_fields），可选",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数，默认 25，最大 200；列表场景建议≤30以免上下文过大",
            },
            "page": {"type": "integer", "description": "页码，从 1 开始"},
            "skip_upstream_sync": {
                "type": "boolean",
                "description": "为 true 时跳过上游拉数，仅查本地库（默认 false）",
            },
            "force_upstream_sync": {
                "type": "boolean",
                "description": "为 true 时无视「每会话每 connector 只同步一次」限制，强制再拉上游（慎用）",
            },
        },
        "required": ["connector_id"],
    }

    async def execute(self, **kwargs) -> dict:
        cid = str(kwargs.get("connector_id") or "").strip()
        if cid not in PRODUCT_CONNECTORS:
            return ToolResult.error(
                "connector_id 必须是 zysc_dwd_ptl_info 或 zysc_dwd_ptl_holder_summary"
            )

        page = max(1, int(kwargs.get("page", 1) or 1))
        try:
            page_size = min(200, max(1, int(kwargs.get("limit", 25) or 25)))
        except (TypeError, ValueError):
            page_size = 25

        pc_raw = kwargs.get("prod_code")
        prod = str(pc_raw).strip() if pc_raw is not None and str(pc_raw).strip() else None
        skip_sync = bool(kwargs.get("skip_upstream_sync"))
        force_sync = bool(kwargs.get("force_upstream_sync"))
        conversation_id = str(kwargs.get("conversation_id") or "").strip() or None
        sync_meta = await _try_sync_product(
            cid, prod, skip_sync,
            conversation_id=conversation_id,
            force_upstream_sync=force_sync,
        )

        filters: list[DataHubFilterClause] = []
        if prod:
            filters.append(DataHubFilterClause(field="产品代码", op="eq", value=prod))

        kw = kwargs.get("keyword")
        hub_kw = (str(kw).strip() if kw is not None else "") or None

        req = DataHubQueryRequest(
            page=page,
            page_size=page_size,
            sort_by="_imported_at",
            sort_desc=True,
            keyword=hub_kw or None,
            filters=filters,
        )
        try:
            out = await _hub.query_records(cid, req)
        except Exception as e:
            logger.exception("product_hub_query failed")
            return ToolResult.error(f"查询失败：{e}")

        items = out.get("items") or []
        if cid == "zysc_dwd_ptl_info":
            slim_items = [_slim_product_ptl_item(x) for x in items if isinstance(x, dict)]
            payload_items = slim_items
            full_note = "完整字段见库 zysc_ptl_info_records，可用 data_query 指定 projection/limit"
        else:
            payload_items = items
            full_note = ""
        total = out.get("total", 0)
        hint = _sync_hint_cn(sync_meta)
        summary = f"产品 Hub 查询（{cid}）：共 {total} 条（本页 {len(payload_items)} 条）"
        if cid == "zysc_dwd_ptl_info":
            summary += f"；{full_note}"
        if hint:
            summary = hint + "；" + summary
        if prod:
            summary += f"；产品代码={prod}"

        # 根据 connector_id 推断实际使用的 MongoDB 集合
        _collection_map = {
            "zysc_dwd_ptl_info": "zysc_ptl_info_records",
            "zysc_dwd_ptl_holder_summary": "zysc_ptl_holder_records",
        }
        _table = _collection_map.get(cid, cid)
        result = ToolResult.success(
            data={
                "connector_id": cid,
                "items": payload_items,
                "items_full_fields_in_db": bool(cid == "zysc_dwd_ptl_info"),
                "total": total,
                "page": page,
                "page_size": page_size,
                "upstream_sync": sync_meta,
            },
            summary=summary,
            record_count=len(payload_items),
            data_shape="tabular",
        )
        result["_lineage_meta"] = {
            "tables_used": [_table],
            "domains_involved": ["data_hub"],
            "fields_accessed": {_table: list(payload_items[0].keys()) if payload_items else []},
            "join_path": "",
            "records_returned": len(payload_items),
            "total_in_collection": total,
            "query_operation": f"product_hub_query:{cid}",
        }
        return result
