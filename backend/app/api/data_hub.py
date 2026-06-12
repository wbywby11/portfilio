"""
通用数据接入 Hub API

前缀：/api/v1/data-hub
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from loguru import logger

from app.models.data_connector import list_connectors_public, get_connector
from app.models.data_hub import DataHubQueryRequest, PtlInfoImportRequest
from app.models.subject_risk import SubjectRiskImportRequest
from app.schemas.response import Response
from app.services.data_hub_service import DataHubService


def get_hub() -> DataHubService:
    return DataHubService()


router = APIRouter()


@router.get("/connectors", summary="列出已注册连接器（供前端渲染）")
async def connectors_list():
    try:
        return Response.success(data={"items": list_connectors_public()})
    except Exception as e:
        logger.exception("[data-hub] connectors 列表异常 {}", e)
        raise HTTPException(status_code=500, detail=str(e))


def _connector_or_404(cid: str):
    c = get_connector(cid)
    if not c:
        raise HTTPException(status_code=404, detail=f"未知连接器: {cid}")
    return c


@router.post("/{connector_id}/import", response_model=Response[dict], summary="连接器导入上游")
async def hub_import(
    connector_id: str = Path(..., description="连接器 ID"),
    body: Dict[str, Any] = Body(...),
    hub: DataHubService = Depends(get_hub),
):
    try:
        conn = _connector_or_404(connector_id)
        if conn.family != "get_py_result":
            raise HTTPException(status_code=400, detail="该连接器暂未开放通用导入接口")
        if getattr(conn, "import_param_style", "date_range") == "ptl_param_maps":
            payload = PtlInfoImportRequest(**body).model_dump(mode="json")
        else:
            payload = SubjectRiskImportRequest(**body).model_dump(mode="json")
        result = await hub.import_from_upstream(connector_id, payload)
        status = result.get("status", "unknown")
        if status in ("failed_network", "failed_upstream"):
            return Response(code=502, message=result.get("error") or "上游导入失败", data=result)
        msg = "导入成功" if status == "success" else (
            "部分记录未入库，请查看批次详情" if status == "partial" else "导入完成"
        )
        return Response.success(data=result, message=msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-hub] import {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{connector_id}/records", response_model=Response[dict], summary="分页查询记录")
async def hub_records(
    connector_id: str,
    q: DataHubQueryRequest = Body(default_factory=DataHubQueryRequest),
    hub: DataHubService = Depends(get_hub),
):
    try:
        _connector_or_404(connector_id)
        data = await hub.query_records(connector_id, q)
        return Response.success(data=data)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-hub] records {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connector_id}/records/{pk}", response_model=Response[dict], summary="按主键查单条")
async def hub_one_record(
    connector_id: str,
    pk: str = Path(..., description="主键值 URL 编码"),
    hub: DataHubService = Depends(get_hub),
):
    try:
        _connector_or_404(connector_id)
        doc = await hub.get_record_by_pk(connector_id, pk)
        if not doc:
            raise HTTPException(status_code=404, detail="记录不存在")
        return Response.success(data=doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-hub] record one {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connector_id}/batches", response_model=Response[dict])
async def hub_batches_list(
    connector_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    hub: DataHubService = Depends(get_hub),
):
    try:
        _connector_or_404(connector_id)
        return Response.success(await hub.list_batches(connector_id, page, page_size))
    except Exception as e:
        logger.exception("[data-hub] batches {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connector_id}/batches/{batch_id}", response_model=Response[dict])
async def hub_batch_detail(
    connector_id: str,
    batch_id: str,
    hub: DataHubService = Depends(get_hub),
):
    try:
        _connector_or_404(connector_id)
        doc = await hub.get_batch(connector_id, batch_id)
        if not doc:
            raise HTTPException(status_code=404, detail="批次不存在")
        return Response.success(data=doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-hub] batch detail {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connector_id}/stats/overview", response_model=Response[dict])
async def hub_stats(connector_id: str, hub: DataHubService = Depends(get_hub)):
    try:
        _connector_or_404(connector_id)
        return Response.success(await hub.stats_overview(connector_id))
    except Exception as e:
        logger.exception("[data-hub] stats {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connector_id}/fields", response_model=Response[dict])
async def hub_fields(connector_id: str, hub: DataHubService = Depends(get_hub)):
    try:
        _connector_or_404(connector_id)
        ind_name_list = await hub.get_latest_fields(connector_id)
        return Response.success(data={"ind_name_list": ind_name_list})
    except Exception as e:
        logger.exception("[data-hub] fields {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connector_id}/distinct", response_model=Response[dict])
async def hub_distinct(
    connector_id: str,
    field: str = Query(...),
    limit: int = Query(200, ge=1, le=2000),
    hub: DataHubService = Depends(get_hub),
):
    try:
        _connector_or_404(connector_id)
        values = await hub.distinct_values(connector_id, field, limit=limit)
        return Response.success(data={"field": field, "values": values})
    except Exception as e:
        logger.exception("[data-hub] distinct {}", e)
        raise HTTPException(status_code=500, detail=str(e))
