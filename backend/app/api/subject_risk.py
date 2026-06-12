"""
主体观点风险统计 API

路由前缀：/api/v1/subject-risk
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from loguru import logger

from app.models.subject_risk import (
    SubjectRiskImportRequest,
    SubjectRiskQueryRequest,
)
from app.schemas.response import Response
from app.services.subject_risk_service import SubjectRiskService


def get_service() -> SubjectRiskService:
    return SubjectRiskService()


router = APIRouter()


@router.post("/import", response_model=Response[dict], summary="从上游拉取并导入主体观点风险数据")
async def import_subject_risk(
    req: SubjectRiskImportRequest = Body(...),
    service: SubjectRiskService = Depends(get_service),
):
    """
    调用上游 `getPyResult` 接口，按 `risk_id` 为唯一键 upsert 入库。

    - 支持自定义 `timeout` 与 `upstream_url`（不传则用默认值）
    - 记录完整批次元数据（参数、摘要、msg_list、ind_name_list），可在 `/batches` 查看
    - 异常分级：
        - `failed_network` 网络超时/连接失败
        - `failed_upstream` 上游协议非成功 code/status
        - `partial` 有部分记录失败/跳过（无 risk_id 等）
        - `success` 全量成功
    """
    try:
        result = await service.import_from_upstream(req)
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
        logger.exception("[subject-risk] /import 未捕获异常: {}", e)
        raise HTTPException(status_code=500, detail=f"导入服务内部错误：{e}")


@router.post("/records", response_model=Response[dict], summary="分页查询主体观点风险记录")
async def query_records(
    q: SubjectRiskQueryRequest = Body(default_factory=SubjectRiskQueryRequest),
    service: SubjectRiskService = Depends(get_service),
):
    try:
        data = await service.query_records(q)
        return Response.success(data=data)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[subject-risk] /records 查询异常: {}", e)
        raise HTTPException(status_code=500, detail=f"查询失败：{e}")


@router.get("/records/{risk_id}", response_model=Response[dict], summary="按 risk_id 查询单条记录")
async def get_record(
    risk_id: str = Path(..., description="风险记录唯一标识"),
    service: SubjectRiskService = Depends(get_service),
):
    try:
        doc = await service.get_record(risk_id)
        if not doc:
            raise HTTPException(status_code=404, detail="记录不存在")
        return Response.success(data=doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[subject-risk] /records/{} 查询异常: {}", risk_id, e)
        raise HTTPException(status_code=500, detail=f"查询失败：{e}")


@router.get("/batches", response_model=Response[dict], summary="分页查询导入批次历史")
async def list_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: SubjectRiskService = Depends(get_service),
):
    try:
        data = await service.list_batches(page=page, page_size=page_size)
        return Response.success(data=data)
    except Exception as e:
        logger.exception("[subject-risk] /batches 查询异常: {}", e)
        raise HTTPException(status_code=500, detail=f"批次查询失败：{e}")


@router.get("/batches/{batch_id}", response_model=Response[dict], summary="批次详情")
async def get_batch(
    batch_id: str = Path(..., description="批次 ID"),
    service: SubjectRiskService = Depends(get_service),
):
    try:
        doc = await service.get_batch(batch_id)
        if not doc:
            raise HTTPException(status_code=404, detail="批次不存在")
        return Response.success(data=doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[subject-risk] /batches/{} 查询异常: {}", batch_id, e)
        raise HTTPException(status_code=500, detail=f"批次查询失败：{e}")


@router.get("/stats/overview", response_model=Response[dict], summary="统计概览")
async def stats_overview(service: SubjectRiskService = Depends(get_service)):
    try:
        data = await service.stats_overview()
        return Response.success(data=data)
    except Exception as e:
        logger.exception("[subject-risk] /stats/overview 查询异常: {}", e)
        raise HTTPException(status_code=500, detail=f"概览查询失败：{e}")


@router.get("/fields", response_model=Response[dict], summary="字段元数据（来自最近批次）")
async def get_fields(service: SubjectRiskService = Depends(get_service)):
    try:
        ind_name_list = await service.get_latest_fields()
        return Response.success(data={"ind_name_list": ind_name_list})
    except Exception as e:
        logger.exception("[subject-risk] /fields 查询异常: {}", e)
        raise HTTPException(status_code=500, detail=f"字段元数据查询失败：{e}")


@router.get("/distinct", response_model=Response[dict], summary="某字段的枚举值（用于筛选）")
async def distinct_values(
    field: str = Query(..., description="字段名，例如 risk_signal_level/affiliated_province"),
    limit: int = Query(200, ge=1, le=2000),
    service: SubjectRiskService = Depends(get_service),
):
    try:
        values = await service.distinct_values(field, limit=limit)
        return Response.success(data={"field": field, "values": values})
    except Exception as e:
        logger.exception("[subject-risk] /distinct 查询异常 field={}: {}", field, e)
        raise HTTPException(status_code=500, detail=f"枚举值查询失败：{e}")
