"""
数据资产管理路由

前缀：/api/v1/data-assets
基于 MongoDB 实际集合的元数据注册表。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.models.api_data_asset import CollectionAssetUpdate
from app.schemas.response import Response
from app.services.api_data_asset_service import ApiDataAssetService

router = APIRouter()


def _get_service() -> ApiDataAssetService:
    return ApiDataAssetService()


# ─── 扫描 ────────────────────────────────────────────────────────────────────


@router.post("/scan", summary="扫描数据库所有集合")
async def scan_database():
    """扫描 MongoDB 所有实际集合，返回实时统计信息"""
    try:
        svc = _get_service()
        data = await svc.scan_database()
        return Response.success(data=data)
    except Exception as e:
        logger.exception("[data-asset] scan 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── 汇总 ────────────────────────────────────────────────────────────────────


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


# ─── 列表 ────────────────────────────────────────────────────────────────────


@router.get("", summary="列出所有集合资产")
async def list_data_assets(
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    status: Optional[str] = Query(None, description="状态筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量"),
):
    """列出所有集合资产（分页）"""
    try:
        svc = _get_service()
        data = await svc.list_assets(
            keyword=keyword, status=status, page=page, page_size=page_size
        )
        return Response.success(data=data)
    except Exception as e:
        logger.exception("[data-asset] list 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─── 单个操作 ────────────────────────────────────────────────────────────────


@router.get("/{collection_name}", summary="获取单个集合详情")
async def get_data_asset(collection_name: str):
    """获取单个集合的完整信息"""
    try:
        svc = _get_service()
        doc = await svc.get_asset(collection_name)
        if not doc:
            raise HTTPException(status_code=404, detail=f"集合不存在: {collection_name}")
        return Response.success(data=doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-asset] get {} 异常: {}", collection_name, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{collection_name}", summary="更新集合描述/标签")
async def update_data_asset(collection_name: str, data: CollectionAssetUpdate):
    """更新人工编辑信息"""
    try:
        svc = _get_service()
        doc = await svc.update_asset(collection_name, data)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"集合不存在: {collection_name}")
        return Response.success(data=doc, message="更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[data-asset] update {} 异常: {}", collection_name, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{collection_name}/refresh", summary="刷新单个集合统计")
async def refresh_asset(collection_name: str):
    """刷新单个集合的实时统计信息"""
    try:
        svc = _get_service()
        result = await svc.refresh_asset(collection_name)
        return Response.success(data=result)
    except Exception as e:
        logger.exception("[data-asset] refresh {} 异常: {}", collection_name, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{collection_name}/preview", summary="数据预览")
async def preview_collection(
    collection_name: str,
    limit: int = Query(10, ge=1, le=100, description="返回记录数"),
):
    """预览集合的前 N 条数据"""
    try:
        svc = _get_service()
        data = await svc.preview_collection(collection_name, limit=limit)
        return Response.success(data=data)
    except Exception as e:
        logger.exception("[data-asset] preview {} 异常: {}", collection_name, e)
        raise HTTPException(status_code=500, detail=str(e))


