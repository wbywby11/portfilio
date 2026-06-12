"""
主体观点风险统计 - Pydantic Schema

对应上游接口：
POST http://zylcorms.wmverify.com:8080/jxdatamid/apiManage/getPyResult
resource = "adm_subject_opinion_risk_stats"
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.config.settings import settings


# 允许写入 Mongo 的字段白名单（与上游返回 data 中的字段保持一致）
SUBJECT_RISK_FIELDS: List[str] = [
    "risk_id",
    "biz_date",
    "data_date",
    "sign_date",
    "subject_name",
    "subject_type",
    "unified_social_credit_code",
    "enterprise_nature",
    "industry_classification_gb",
    "risk_signal_level",
    "signal_dascribe",
    "rule_large",
    "rule_medium",
    "rule_small",
    "affiliated_province",
    "affiliated_city",
    "affiliated_county_town",
    "is_approved_investment_quota_client",
    "is_partner_access_client",
    "is_parent_bank_veto_client",
    "parent_bank_classify_queue_type",
    "parent_bank_monitor_manager_type",
    "wealth_child_monitor_manager_type",
    "financial_lease_monitor_manager_type",
]

# 日期型字段（导入时尝试标准化，失败保留原字符串）
SUBJECT_RISK_DATE_FIELDS: List[str] = ["biz_date", "data_date", "sign_date"]


class SubjectRiskImportRequest(BaseModel):
    """导入请求：后端代理调用上游 getPyResult"""

    startDate: str = Field(..., description="起始日期 YYYY-MM-DD")
    endDate: str = Field(..., description="结束日期 YYYY-MM-DD")
    rownum: int = Field(100000, ge=1, le=1_000_000, description="单次拉取最大行数")
    startrow: int = Field(1, ge=1, description="起始行（1-based）")
    resource: str = Field(default_factory=lambda: settings.SUBJECT_RISK_RESOURCE, description="上游资源标识")
    timeout: float = Field(default_factory=lambda: settings.DATA_HUB_UPSTREAM_TIMEOUT, ge=5.0, le=600.0, description="上游请求超时秒")
    upstream_url: Optional[str] = Field(
        None, description="自定义上游 URL（默认 settings.DATA_HUB_UPSTREAM_URL）"
    )

    @field_validator("startDate", "endDate")
    @classmethod
    def _check_date(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError("日期必须为 YYYY-MM-DD 格式")
        return v

    @field_validator("endDate")
    @classmethod
    def _end_ge_start(cls, v: str, info) -> str:
        start = info.data.get("startDate")
        if start and v < start:
            raise ValueError("endDate 必须大于等于 startDate")
        return v


class UpstreamMsg(BaseModel):
    """上游 msg_list 内单项结构"""

    message_code: Optional[str] = None
    message_content: Optional[str] = None
    message_type: Optional[str] = None


class IndNameItem(BaseModel):
    """上游 ind_name_list 内单项结构（字段元数据）"""

    ind_code: Optional[str] = None
    ind_name: Optional[str] = None
    sourceTableLabel: Optional[str] = None
    labelType: Optional[str] = None


class SubjectRiskQueryRequest(BaseModel):
    """查询请求"""

    page: int = Field(1, ge=1, description="页码 1-based")
    page_size: int = Field(20, ge=1, le=500, description="每页数量")
    risk_signal_level: Optional[List[str]] = Field(None, description="风险等级多选")
    subject_name: Optional[str] = Field(None, description="主体名称模糊匹配")
    unified_social_credit_code: Optional[str] = Field(None, description="统一社会信用代码")
    affiliated_province: Optional[str] = Field(None, description="归属省份")
    affiliated_city: Optional[str] = Field(None, description="归属地市")
    enterprise_nature: Optional[str] = Field(None, description="企业性质")
    subject_type: Optional[str] = Field(None, description="主体类型")
    biz_date_start: Optional[str] = Field(None, description="业务日期起 YYYY-MM-DD")
    biz_date_end: Optional[str] = Field(None, description="业务日期止 YYYY-MM-DD")
    batch_id: Optional[str] = Field(None, description="按批次过滤")
    keyword: Optional[str] = Field(None, description="关键字（主体名/描述/risk_id 模糊）")
    sort_by: Optional[str] = Field("_imported_at", description="排序字段")
    sort_desc: bool = Field(True, description="是否降序")


class SubjectRiskRecordOut(BaseModel):
    """Mongo 中单条记录的返回结构"""

    risk_id: Optional[str] = None
    biz_date: Optional[str] = None
    data_date: Optional[str] = None
    sign_date: Optional[str] = None
    subject_name: Optional[str] = None
    subject_type: Optional[str] = None
    unified_social_credit_code: Optional[str] = None
    enterprise_nature: Optional[str] = None
    industry_classification_gb: Optional[str] = None
    risk_signal_level: Optional[str] = None
    signal_dascribe: Optional[str] = None
    rule_large: Optional[str] = None
    rule_medium: Optional[str] = None
    rule_small: Optional[str] = None
    affiliated_province: Optional[str] = None
    affiliated_city: Optional[str] = None
    affiliated_county_town: Optional[str] = None
    is_approved_investment_quota_client: Optional[str] = None
    is_partner_access_client: Optional[str] = None
    is_parent_bank_veto_client: Optional[str] = None
    parent_bank_classify_queue_type: Optional[str] = None
    parent_bank_monitor_manager_type: Optional[str] = None
    wealth_child_monitor_manager_type: Optional[str] = None
    financial_lease_monitor_manager_type: Optional[str] = None
    _batch_id: Optional[str] = None
    _imported_at: Optional[str] = None

    class Config:
        extra = "allow"


class ImportBatchOut(BaseModel):
    """批次元数据"""

    batch_id: str
    status: str = Field(..., description="success/partial/failed_network/failed_upstream/failed_unknown")
    started_at: str
    finished_at: Optional[str] = None
    duration_ms: int = 0
    params: Dict[str, Any] = Field(default_factory=dict)
    upstream_url: Optional[str] = None
    upstream_code: Optional[str] = None
    upstream_message: Optional[str] = None
    msg_list: List[UpstreamMsg] = Field(default_factory=list)
    ind_name_list: List[IndNameItem] = Field(default_factory=list)
    total_returned: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_no_key: int = 0
    failed: int = 0
    error: Optional[str] = None
    sample_errors: List[str] = Field(default_factory=list)
