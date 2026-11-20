# -*- coding: utf-8 -*-
"""监控运行批次 API —— 版本化产物的列表 / 详情 / 净值 / 对比 / 软删除。

从 ``app/api/monitor.py`` 拆出，只为满足「api 单文件 ≤ 1000 行」的架构守卫
（见 tests/test_architecture_guard.py），路由前缀与拆分前完全一致：由
``monitor.py`` 通过 ``include_router`` 挂回同一棵路由树。

读写分界与主文件同口径：GET 只注入 :class:`MonitorQueryService`（纯读表），
缓存缺失不重建；唯一的写端点 ``DELETE /batches/{id}`` 是软删除，产物文档全部保留。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from app.api.monitor_deps import (
    get_monitor_query_service,
    missing,
    validate_date_format,
)
from app.schemas.response import Response
from app.services.monitor_query_service import MonitorQueryService

router = APIRouter()


@router.get("/batches", response_model=Response[dict], summary="列出运行批次")
async def list_monitor_batches(
    monitor_id: str = Query("default", description="监控实例 ID"),
    limit: int = Query(20, ge=1, le=200, description="返回条数"),
    skip: int = Query(0, ge=0, description="跳过条数"),
    status: Optional[str] = Query(
        None,
        description="状态过滤: pending/running/paused/completed/failed/interrupted",
    ),
    include_deleted: bool = Query(False, description="是否包含已软删除的批次"),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """批次历史（创建时间倒序）+ ``current_batch_id``（当前展示批次号）。

    前端批次切换器直接吃这份数据：``current_batch_id`` 为展示端点默认读取的批次，
    列表里任一批次号可作为 ``batch_id`` 参数回传给其他展示端点。
    """
    try:
        data = await query.list_batches(
            monitor_id, limit=limit, skip=skip,
            status=status, include_deleted=include_deleted,
        )
        return Response.success(data=data, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取批次列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取批次列表失败: {str(e)}")


# 注意：/batches/compare 必须声明在 /batches/{batch_id} 之前，
# 否则 FastAPI 会把 "compare" 当成批次号路径参数吃掉。
@router.get("/batches/compare", response_model=Response[dict], summary="多批次对比")
async def compare_monitor_batches(
    monitor_id: str = Query("default", description="监控实例 ID"),
    batch_ids: str = Query(..., description="逗号分隔的批次号，最多 5 个"),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """多批次对比：配置快照 + 摘要指标 + 区间指标 + 净值曲线（最多 5 个批次）。

    只对比属于 ``monitor_id`` 的批次，跨实例的批次号被静默忽略。
    """
    ids = [s.strip() for s in str(batch_ids or "").split(",") if s.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 个批次号才能对比")
    try:
        data = await query.compare_batches(monitor_id, ids)
        if not data["items"]:
            raise missing(f"批次不存在或不属于该实例: {batch_ids}")
        logger.info(
            f"批次对比: monitor_id={monitor_id}, count={data['count']}, ids={ids}"
        )
        return Response.success(data=data, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批次对比失败: {e}")
        raise HTTPException(status_code=500, detail=f"批次对比失败: {str(e)}")


@router.get("/batches/{batch_id}", response_model=Response[dict], summary="批次详情")
async def get_monitor_batch(
    batch_id: str,
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """批次详情：运行模式、起止日期、配置快照（模板/参数版本/子策略）与摘要指标。"""
    try:
        data = await query.get_batch(batch_id)
        if not data:
            raise missing(f"批次不存在: {batch_id}")
        return Response.success(data=data, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取批次详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取批次详情失败: {str(e)}")


@router.get(
    "/batches/{batch_id}/nav-history",
    response_model=Response[dict],
    summary="批次净值曲线",
)
async def get_monitor_batch_nav_history(
    batch_id: str,
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """单批次双轨净值曲线（读该批次绩效缓存的区间投影）。

    缓存缺失时不 404 而是返回 ``cache_available=false`` 与空曲线：
    批次可能已跑完但属于无缓存产物的失败/中断批次，前端要能展示摘要。
    """
    try:
        if start:
            validate_date_format(start, "开始日期")
        if end:
            validate_date_format(end, "结束日期")
        data = await query.get_batch_nav_history(batch_id, start, end)
        if data is None:
            raise missing(f"批次不存在: {batch_id}")
        return Response.success(data=data, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取批次净值失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取批次净值失败: {str(e)}")


@router.delete("/batches/{batch_id}", response_model=Response[bool], summary="删除运行批次（软删除）")
async def delete_monitor_batch(
    batch_id: str,
    query: MonitorQueryService = Depends(get_monitor_query_service),
):
    """软删除批次：只置 ``deleted=True``，产物文档（状态/日报/操作/预警/缓存/
    回测记录）全部保留供事后审计。删除后不再被 ``resolve_batch`` 选为展示批次。

    正在运行的批次拒绝删除（409），避免把跑批中途的写入打成孤儿。
    """
    try:
        doc = await query.get_batch(batch_id)
        if not doc:
            raise missing(f"批次不存在: {batch_id}")
        if str(doc.get("status")) in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"批次正在运行（{doc.get('status')}），不能删除: {batch_id}",
            )
        ok = await query.soft_delete_batch(batch_id)
        logger.warning(
            f"软删除监控批次: batch_id={batch_id}, monitor_id={doc.get('monitor_id')}"
        )
        return Response.success(data=bool(ok), message="批次已删除（产物保留）")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除批次失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除批次失败: {str(e)}")

