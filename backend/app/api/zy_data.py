"""
ZY 通用数据域 REST API
提供对所有注册业务集合的 CRUD 操作，供前端 zyDataDomain.js 调用。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Path, Query
from loguru import logger

from app.config.database import Database
from app.services.collection_registry import (
    CollectionNotFoundError,
    CollectionRegistry,
    DOMAIN_METADATA,
)
from app.services.generic_query_engine import GenericQueryEngine

router = APIRouter()

# 模块级单例
_registry = CollectionRegistry()
_engine = GenericQueryEngine(registry=_registry)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _get_db():
    """获取 MongoDB 数据库实例"""
    return Database.get_database()


def _serialize_doc(doc: dict) -> dict:
    """序列化 MongoDB 文档：ObjectId → str，datetime → ISO 字符串"""
    if doc is None:
        return {}
    result = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, dict):
            result[key] = _serialize_doc(value)
        elif isinstance(value, list):
            result[key] = [_serialize_doc(v) if isinstance(v, dict) else (
                str(v) if isinstance(v, ObjectId) else (
                    v.isoformat() if isinstance(v, datetime) else v
                )
            ) for v in value]
        else:
            result[key] = value
    return result


def _get_whitelisted_collections() -> set[str]:
    """获取所有已注册集合名（白名单）"""
    names = set()
    for domain_info in DOMAIN_METADATA.values():
        for table_name in domain_info["tables"]:
            names.add(table_name)
    return names


def _validate_collection_access(collection: str) -> None:
    """校验集合是否在白名单中，不在则 404"""
    allowed = _get_whitelisted_collections()
    if collection not in allowed:
        raise HTTPException(
            status_code=404,
            detail=f"集合 '{collection}' 未注册或不允许访问",
        )


# ---------------------------------------------------------------------------
# GET /collections - 列出所有注册集合（按域分组）
# ---------------------------------------------------------------------------

@router.get("/collections", summary="列出所有注册集合")
async def list_collections(domain: str = Query(None, description="按域筛选")):
    """列出所有可查询的业务集合"""
    try:
        collections = await _registry.list_collections(domain=domain)

        # 如果为空，可能首次启动还未扫描
        if not collections:
            await _registry.refresh()
            collections = await _registry.list_collections(domain=domain)

        return {"collections": collections}
    except Exception as e:
        logger.exception("[zy-data] list_collections 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /{collection}/count - 计数（放在 /{collection} 之前避免路由冲突）
# ---------------------------------------------------------------------------

@router.get("/{collection}/count", summary="集合记录计数")
async def count_records(
    collection: str = Path(...),
    filters_json: str = Query(None, description="JSON格式的过滤条件"),
):
    """计数"""
    _validate_collection_access(collection)
    try:
        filters = json.loads(filters_json) if filters_json else None
        total = await _engine.count(collection=collection, filters=filters)
        return {"count": total}
    except CollectionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="filters_json 格式错误，需要有效的 JSON")
    except Exception as e:
        logger.exception("[zy-data] count 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /{collection}/schema - 获取Schema
# ---------------------------------------------------------------------------

@router.get("/{collection}/schema", summary="获取集合结构定义")
async def get_schema(collection: str = Path(...)):
    """获取集合结构定义"""
    _validate_collection_access(collection)
    try:
        schema = await _registry.get_schema(collection)
        return schema
    except CollectionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("[zy-data] schema 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /{collection} - 查询数据（分页+过滤+排序）
# ---------------------------------------------------------------------------

@router.get("/{collection}", summary="查询集合数据")
async def query_records(
    collection: str = Path(...),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=500),
    filters_json: str = Query(None, description="JSON格式的过滤条件"),
    sort_json: str = Query(None, description="JSON格式的排序条件"),
):
    """查询集合数据，支持分页和过滤"""
    _validate_collection_access(collection)
    try:
        # 解析过滤条件
        filters = None
        if filters_json:
            try:
                filters = json.loads(filters_json)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="filters_json 格式错误")

        # 解析排序条件
        sort = None
        if sort_json:
            try:
                sort = json.loads(sort_json)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="sort_json 格式错误")

        # 计算 skip
        skip = (page - 1) * pageSize

        # 适配排序参数：前端用 direction，引擎用 order
        engine_sort = None
        if sort:
            engine_sort = [
                {"field": s.get("field", ""), "order": s.get("direction", s.get("order", "asc"))}
                for s in sort
            ] if isinstance(sort, list) else None

        result = await _engine.find(
            collection=collection,
            filters=filters,
            sort=engine_sort,
            limit=pageSize,
            skip=skip,
        )

        total = result.get("total", 0)
        data_rows = result.get("data", [])

        # 序列化
        records = [_serialize_doc(doc) for doc in data_rows]

        return {
            "records": records,
            "total": total,
            "page": page,
            "pageSize": pageSize,
        }
    except HTTPException:
        raise
    except CollectionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("[zy-data] query 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /{collection} - 新增记录
# ---------------------------------------------------------------------------

@router.post("/{collection}", summary="新增记录")
async def create_record(
    collection: str = Path(...),
    payload: dict = Body(...),
):
    """新增一条记录"""
    _validate_collection_access(collection)
    try:
        db = _get_db()
        col = db[collection]

        # 追加审计字段
        payload["etl_dt"] = datetime.now(timezone.utc).isoformat()
        payload["src_sys"] = "zy_data_api"

        result = await col.insert_one(payload)
        payload["_id"] = str(result.inserted_id)

        return _serialize_doc(payload)
    except Exception as e:
        logger.exception("[zy-data] create 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# PUT /{collection}/{record_id} - 更新记录
# ---------------------------------------------------------------------------

@router.put("/{collection}/{record_id}", summary="更新记录")
async def update_record(
    collection: str = Path(...),
    record_id: str = Path(...),
    payload: dict = Body(...),
):
    """更新一条记录"""
    _validate_collection_access(collection)
    try:
        db = _get_db()
        col = db[collection]

        # 移除 payload 中的 _id（避免覆盖）
        payload.pop("_id", None)

        # 追加审计字段
        payload["etl_dt"] = datetime.now(timezone.utc).isoformat()
        payload["src_sys"] = "zy_data_api"

        # 尝试按 ObjectId 查找
        query: dict[str, Any]
        try:
            query = {"_id": ObjectId(record_id)}
        except Exception:
            # 非 ObjectId 格式，尝试字符串 _id
            query = {"_id": record_id}

        result = await col.find_one_and_update(
            query,
            {"$set": payload},
            return_document=True,
        )

        if not result:
            raise HTTPException(status_code=404, detail=f"记录 '{record_id}' 不存在")

        return _serialize_doc(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[zy-data] update 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# DELETE /{collection}/{record_id} - 删除记录
# ---------------------------------------------------------------------------

@router.delete("/{collection}/{record_id}", summary="删除记录")
async def delete_record(
    collection: str = Path(...),
    record_id: str = Path(...),
):
    """删除一条记录"""
    _validate_collection_access(collection)
    try:
        db = _get_db()
        col = db[collection]

        # 尝试按 ObjectId 查找
        try:
            query = {"_id": ObjectId(record_id)}
        except Exception:
            query = {"_id": record_id}

        result = await col.delete_one(query)

        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail=f"记录 '{record_id}' 不存在")

        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[zy-data] delete 异常: {}", e)
        raise HTTPException(status_code=500, detail=str(e))
