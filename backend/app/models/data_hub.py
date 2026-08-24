"""
通用数据接入 Hub — 请求模型
"""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class DataHubFilterClause(BaseModel):
    """受控查询条件（字段必须在连接器 allowlist_query 内校验）"""

    field: str = Field(..., description="Mongo 字段名")
    op: Literal["eq", "in", "regex", "gte", "lte"]
    value: Any = None


class DataHubQueryRequest(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=500)
    sort_by: str = Field("_imported_at", description="排序字段，须为允许列表内")
    sort_desc: bool = True
    batch_id: Optional[str] = Field(None, description="按批次 ID 过滤 _batch_id")
    keyword: Optional[str] = Field(None, description="多字段模糊")
    filters: List[DataHubFilterClause] = Field(default_factory=list)


class DataHubImportJsonBody(BaseModel):
    """
    POST /data-hub/{connector_id}/import 请求体

    get_py_result 族：与 SubjectRiskImportRequest 字段对齐
    """

    startDate: str = Field(..., description="YYYY-MM-DD")
    endDate: str = Field(..., description="YYYY-MM-DD")
    rownum: int = Field(100000, ge=1, le=1_000_000)
    startrow: int = Field(1, ge=1)
    resource: Optional[str] = None
    timeout: float = Field(180.0, ge=5.0, le=600.0)
    upstream_url: Optional[str] = None


def build_get_py_result_payload(body: DataHubImportJsonBody, resource_default: str) -> dict:
    res = (body.resource or "").strip() or resource_default
    return {
        "resource": res,
        "paramMaps": {"startDate": body.startDate, "endDate": body.endDate},
        "rownum": body.rownum,
        "startrow": body.startrow,
    }
