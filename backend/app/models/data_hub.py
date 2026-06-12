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


def _ptl_nullable_tree(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return None if s == "" else s


class PtlInfoImportRequest(BaseModel):
    """产品信息表 getPyResult：paramMaps 为 SYS_ID / PROD_CDS / asset_tree / port_tree"""

    SYS_ID: str = Field("", description="系统号，可空")
    PROD_CDS: str = Field("", description="产品代码，可空（全量时可能触发上游行数限制）")
    asset_tree: Optional[str] = Field(None, description="维度树 code，可空")
    port_tree: Optional[str] = Field(None, description="组合树 code，可空")
    rownum: int = Field(100000, ge=1, le=1_000_000)
    startrow: int = Field(1, ge=1)
    resource: Optional[str] = Field(None, description="上游 resource，默认连接器 resource_default")
    timeout: float = Field(180.0, ge=5.0, le=600.0)
    upstream_url: Optional[str] = None


def build_ptl_param_maps_payload(body: PtlInfoImportRequest, resource_default: str) -> dict:
    res = (body.resource or "").strip() or resource_default
    return {
        "resource": res,
        "paramMaps": {
            "SYS_ID": (body.SYS_ID or "").strip(),
            "PROD_CDS": (body.PROD_CDS or "").strip(),
            "asset_tree": _ptl_nullable_tree(body.asset_tree),
            "port_tree": _ptl_nullable_tree(body.port_tree),
        },
        "rownum": body.rownum,
        "startrow": body.startrow,
    }
