"""
通用数据接入 — 连接器元数据（注册表）

首期内置：subject_opinion_risk（与原主体观点风险完全一致集合与字段）
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from app.config.settings import settings
from app.models.subject_risk import SUBJECT_RISK_FIELDS, SUBJECT_RISK_DATE_FIELDS


class MongoIndexSpec(BaseModel):
    """单条 Mongo 索引声明"""

    name: str
    fields: List[Tuple[str, int]] = Field(
        ...,
        description="字段名与方向：1 ASC, -1 DESC",
    )
    unique: bool = False


class UIImportFieldSpec(BaseModel):
    """导入表单控件描述（前端动态渲染）"""

    key: str
    label: str
    component: Literal[
        "daterange", "number", "text", "readonly"
    ] = "text"
    default: Optional[Any] = None
    hint: Optional[str] = None
    min_: Optional[float] = Field(None, alias="min")
    max_: Optional[float] = Field(None, alias="max")
    bind_start: Optional[str] = Field(
        None, description="daterange：对应 paramMaps 起始字段名"
    )
    bind_end: Optional[str] = Field(
        None, description="daterange：对应 paramMaps 结束字段名"
    )

    model_config = {"populate_by_name": True}


class UIFilterFieldSpec(BaseModel):
    """筛选区字段（前端可选用）"""

    key: str
    label: str
    component: Literal["keyword", "enum_multi", "enum", "daterange", "text"] = "text"
    enum_source: Literal["distinct", None] = None
    mongo_field: Optional[str] = None


class ChartRecipeSpec(BaseModel):
    """统计图表配方（后端聚合 + 前端 ECharts）"""

    id: str
    title: str
    chart_type: Literal["pie", "bar_horizontal"] = "pie"
    group_by_field: str
    limit: int = 10
    legacy_flat_key: Optional[str] = Field(
        None,
        description="兼容旧 stats/overview 顶层数组字段名（如 risk_signal_level）",
    )


ImportParamStyle = Literal["date_range"]


class ConnectorDefinition(BaseModel):
    connector_id: str
    title: str
    description: str = ""
    family: Literal["get_py_result"] = "get_py_result"
    default_upstream_url: str = Field(default_factory=lambda: settings.DATA_HUB_UPSTREAM_URL)
    import_param_style: ImportParamStyle = "date_range"
    # 导入请求体中与 paramMaps 并行的字段别名（daterange UI 拆解）
    import_param_keys: List[str] = Field(
        default_factory=lambda: ["startDate", "endDate"]
    )

    records_collection: str
    batches_collection: str
    primary_key: str

    records_path: str = "data"
    success_code_values: frozenset = Field(
        default=frozenset({"0", "200"}),
    )
    msg_list_path: str = "msg_list"
    ind_name_list_path: str = "ind_name_list"

    date_fields: List[str] = Field(default_factory=list)
    allowlist_fields: List[str] = Field(default_factory=list)
    records_indexes: List[MongoIndexSpec] = Field(
        default_factory=list,
        description="records_collection 索引",
    )
    batches_indexes: List[MongoIndexSpec] = Field(
        default_factory=list,
        description="batches_collection 索引",
    )

    keyword_search_fields: List[str] = Field(
        default_factory=list,
        description="keyword 模糊 OR 匹配的字段列表",
    )
    distinct_allowlist_fields: List[str] = Field(default_factory=list)

    badge_field: Optional[str] = None
    ui_import_fields: List[UIImportFieldSpec] = Field(default_factory=list)
    ui_filter_fields: List[UIFilterFieldSpec] = Field(default_factory=list)
    chart_recipes: List[ChartRecipeSpec] = Field(default_factory=list)

    resource_default: str = Field(default_factory=lambda: settings.SUBJECT_RISK_RESOURCE)
    supports_upstream_url_override: bool = True

    #: 前端表格优先列顺序（仅展示用，连接器列表 API 透出）
    column_display_priority: List[str] = Field(default_factory=list)


def _subject_opinion_risk() -> ConnectorDefinition:
    """内置：主体观点风险"""
    rec_ix: List[MongoIndexSpec] = [
        MongoIndexSpec(name=f"uq_{SUBJECT_RISK_FIELDS[0]}", fields=[("risk_id", 1)], unique=True),
        MongoIndexSpec(name="ix_biz_date", fields=[("biz_date", 1)], unique=False),
        MongoIndexSpec(name="ix_risk_signal_level", fields=[("risk_signal_level", 1)], unique=False),
        MongoIndexSpec(name="ix_province", fields=[("affiliated_province", 1)], unique=False),
        MongoIndexSpec(name="ix_imported_at", fields=[("_imported_at", -1)], unique=False),
        MongoIndexSpec(name="ix_batch_id", fields=[("_batch_id", 1)], unique=False),
    ]
    bat_ix: List[MongoIndexSpec] = [
        MongoIndexSpec(name="uq_batch_id", fields=[("batch_id", 1)], unique=True),
        MongoIndexSpec(name="ix_started_at_batches", fields=[("started_at", -1)], unique=False),
    ]
    return ConnectorDefinition(
        connector_id="subject_opinion_risk",
        title="主体观点风险",
        description="上游 adm_subject_opinion_risk_stats，按 risk_id upsert",
        import_param_style="date_range",
        records_collection="subject_risk_records",
        batches_collection="subject_risk_import_batches",
        primary_key="risk_id",
        date_fields=list(SUBJECT_RISK_DATE_FIELDS),
        allowlist_fields=list(SUBJECT_RISK_FIELDS),
        records_indexes=rec_ix,
        batches_indexes=bat_ix,
        keyword_search_fields=[
            "subject_name",
            "signal_dascribe",
            "risk_id",
            "unified_social_credit_code",
        ],
        distinct_allowlist_fields=list(SUBJECT_RISK_FIELDS),
        badge_field="risk_signal_level",
        ui_import_fields=[
            UIImportFieldSpec(
                key="dateRangeUi",
                label="日期区间",
                component="daterange",
                bind_start="startDate",
                bind_end="endDate",
            ),
            UIImportFieldSpec(
                key="rownum",
                label="单次最大行数",
                component="number",
                default=100000,
                min=1,
                max=1_000_000,
            ),
            UIImportFieldSpec(
                key="startrow",
                label="起始行",
                component="number",
                default=1,
                min=1,
            ),
            UIImportFieldSpec(
                key="resource",
                label="上游 resource",
                component="readonly",
                default=settings.SUBJECT_RISK_RESOURCE,
            ),
        ],
        ui_filter_fields=[
            UIFilterFieldSpec(key="keyword", label="关键字", component="keyword"),
            UIFilterFieldSpec(
                key="risk_signal_level",
                label="风险等级",
                component="enum_multi",
                enum_source="distinct",
                mongo_field="risk_signal_level",
            ),
            UIFilterFieldSpec(key="biz_date", label="业务日期", component="daterange", mongo_field="biz_date"),
            UIFilterFieldSpec(
                key="affiliated_province",
                label="所属省份",
                component="enum",
                enum_source="distinct",
                mongo_field="affiliated_province",
            ),
            UIFilterFieldSpec(
                key="enterprise_nature",
                label="企业性质",
                component="enum",
                enum_source="distinct",
                mongo_field="enterprise_nature",
            ),
            UIFilterFieldSpec(
                key="unified_social_credit_code",
                label="统一社会信用代码",
                component="text",
                mongo_field="unified_social_credit_code",
            ),
        ],
        chart_recipes=[
            ChartRecipeSpec(
                id="risk_level",
                title="风险等级分布",
                chart_type="pie",
                group_by_field="risk_signal_level",
                limit=20,
                legacy_flat_key="risk_signal_level",
            ),
            ChartRecipeSpec(
                id="province_top",
                title="省份 Top10",
                chart_type="bar_horizontal",
                group_by_field="affiliated_province",
                limit=10,
                legacy_flat_key="affiliated_province_top10",
            ),
            ChartRecipeSpec(
                id="enterprise_top",
                title="企业性质 Top10",
                chart_type="bar_horizontal",
                group_by_field="enterprise_nature",
                limit=10,
                legacy_flat_key="enterprise_nature_top10",
            ),
        ],
    )


CONNECTOR_REGISTRY: Dict[str, ConnectorDefinition] = {
    "subject_opinion_risk": _subject_opinion_risk(),
}


def get_connector(connector_id: str) -> Optional[ConnectorDefinition]:
    return CONNECTOR_REGISTRY.get(connector_id)


def list_connector_ids() -> List[str]:
    return list(CONNECTOR_REGISTRY.keys())


def list_connectors_public() -> List[Dict[str, Any]]:
    """GET /data-hub/connectors 返回可给前端的元数据"""
    out: List[Dict[str, Any]] = []
    for c in CONNECTOR_REGISTRY.values():
        out.append(
            {
                "connector_id": c.connector_id,
                "title": c.title,
                "description": c.description,
                "family": c.family,
                "import_param_style": c.import_param_style,
                "default_upstream_url": c.default_upstream_url,
                "resource_default": c.resource_default,
                "primary_key": c.primary_key,
                "badge_field": c.badge_field,
                "supports_upstream_url_override": c.supports_upstream_url_override,
                "ui_import_fields": [
                    f.model_dump(mode="json", by_alias=True) for f in c.ui_import_fields
                ],
                "ui_filter_fields": [
                    f.model_dump(mode="json", by_alias=True) for f in c.ui_filter_fields
                ],
                "chart_hints": [h.model_dump(mode="json", by_alias=True) for h in c.chart_recipes],
                "column_display_priority": list(c.column_display_priority),
            }
        )
    return out
