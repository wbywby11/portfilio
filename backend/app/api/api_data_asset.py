"""
API 数据资产管理路由

前缀：/api/v1/data-assets
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.models.api_data_asset import ApiDataAssetCreate, ApiDataAssetUpdate
from app.schemas.response import Response
from app.services.api_data_asset_service import ApiDataAssetService

router = APIRouter()


def _get_service() -> ApiDataAssetService:
    return ApiDataAssetService()


# ─── 列表查询 ─────────────────────────────────────────────────────────────────


@router.get("/summary", summary="获取汇总统计")
async def get_summary():
    """获取汇总统计"""
    try:
        svc = _get_service()
        data = await svc.get_summary_stats()
        return Response.success(data=data)
    except Exception as e:
        logger.exception("[data-asset] summary 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seed", summary="从现有连接器初始化数据资产")
async def seed_from_connectors():
    """从现有连接器初始化数据资产"""
    try:
        svc = _get_service()
        data = await svc.seed_from_connectors()
        return Response.success(data=data, message="种子初始化完成")
    except Exception as e:
        logger.exception("[data-asset] seed 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", summary="分页查询数据资产列表")
async def list_data_assets(
    asset_type: Optional[str] = Query(None, description="资产类型筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    tags: Optional[str] = Query(None, description="标签筛选（逗号分隔）"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """分页查询数据资产列表"""
    try:
        svc = _get_service()
        filters = {}
        if asset_type:
            filters["asset_type"] = asset_type
        if status:
            filters["status"] = status
        if tags:
            filters["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        if keyword:
            filters["keyword"] = keyword

        data = await svc.list_assets(filters=filters, page=page, page_size=page_size)
        return Response.success(data=data)
    except Exception as e:
        logger.exception("[data-asset] list 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── 单个资产操作 ──────────────────────────────────────────────────────────────


@router.get("/{asset_id}", summary="获取单个数据资产详情")
async def get_data_asset(asset_id: str):
    """获取单个数据资产详情"""
    try:
        svc = _get_service()
        doc = await svc.get_asset(asset_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"数据资产不存在: {asset_id}")
        return Response.success(data=doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-asset] get {} 异常: {}", asset_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", summary="创建数据资产")
async def create_data_asset(data: ApiDataAssetCreate):
    """创建数据资产"""
    try:
        svc = _get_service()
        doc = await svc.create_asset(data)
        return Response.success(data=doc, message="创建成功")
    except Exception as e:
        logger.exception("[data-asset] create 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{asset_id}", summary="更新数据资产")
async def update_data_asset(asset_id: str, data: ApiDataAssetUpdate):
    """更新数据资产"""
    try:
        svc = _get_service()
        doc = await svc.update_asset(asset_id, data)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"数据资产不存在: {asset_id}")
        return Response.success(data=doc, message="更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-asset] update {} 异常: {}", asset_id, e)
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/{asset_id}/sync", summary="触发数据同步")
async def sync_data_asset(asset_id: str):
    """触发数据同步"""
    try:
        svc = _get_service()
        asset = await svc.get_asset(asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail=f"数据资产不存在: {asset_id}")
        result = await svc.sync_asset(asset_id)
        return Response.success(data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-asset] sync {} 异常: {}", asset_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{asset_id}/refresh-stats", summary="刷新统计信息")
async def refresh_stats(asset_id: str):
    """刷新统计信息"""
    try:
        svc = _get_service()
        asset = await svc.get_asset(asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail=f"数据资产不存在: {asset_id}")
        result = await svc.refresh_stats(asset_id)
        return Response.success(data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-asset] refresh-stats {} 异常: {}", asset_id, e)
        raise HTTPException(status_code=500, detail=str(e))
