"""
ZY 数据域查询 API - FastAPI 实现

功能:
- 提供 /api/v1/zy-data/ 系列接口
- 支持分页查询、过滤、统计
- 前端 zyDataDomain.js 已适配此接口契约

部署说明:
1. 将此文件复制到 portfilio-end/app/api/v1/zy_data.py
2. 在 portfilio-end/app/main.py 中注册路由
3. 确保 MongoDB 可访问

使用方法:
    from app.api.v1 import zy_data
    app.include_router(zy_data.router)
"""
from fastapi import APIRouter, Query, HTTPException, Depends
from pymongo import MongoClient
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
import json
import logging

# 字段别名映射（双保险层，防止 MongoDB 字段未对齐导致前端字段为空）
try:
    from .zy_data_field_aliases import apply_field_aliases
except ImportError:
    try:
        from zy_data_field_aliases import apply_field_aliases
    except ImportError:
        def apply_field_aliases(collection, record):
            return record

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/zy-data", tags=["ZY数据域"])

# MongoDB 配置(应从 .env 读取)
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "portfilio"

# MongoDB 连接池
mongo_client = None

def get_db():
    """获取数据库连接(单例模式)"""
    global mongo_client
    if mongo_client is None:
        mongo_client = MongoClient(MONGO_URI)
    return mongo_client[DB_NAME]


# ============ 请求/响应模型 ============

class QueryResponse(BaseModel):
    """分页查询响应"""
    records: List[Dict[str, Any]]
    total: int
    page: int
    pageSize: int


class CountResponse(BaseModel):
    """计数响应"""
    count: int


class CollectionsResponse(BaseModel):
    """集合列表响应"""
    collections: List[str]


# ============ API 接口 ============

@router.get("/collections", response_model=CollectionsResponse)
def list_collections():
    """
    列出所有可用的 collection
    
    Returns:
        集合名称列表
    """
    try:
        db = get_db()
        collections = db.list_collection_names()
        # 过滤系统集合
        collections = [c for c in collections if not c.startswith("system.")]
        return {"collections": sorted(collections)}
    except Exception as e:
        logger.error(f"列出集合失败: {e}")
        raise HTTPException(status_code=500, detail=f"数据库错误: {str(e)}")


@router.get("/{collection}", response_model=QueryResponse)
def query_collection(
    collection: str,
    page: int = Query(1, ge=1, description="页码"),
    pageSize: int = Query(20, ge=1, le=100, description="每页数量"),
    filters_json: Optional[str] = Query(None, description="过滤条件 JSON 字符串")
):
    """
    查询集合数据(支持分页和过滤)
    
    Args:
        collection: 集合名称 (如 dwd_ast_info, dwd_ptl_info)
        page: 页码,从 1 开始
        pageSize: 每页数量,最大 100
        filters_json: 过滤条件,JSON 格式 (如 {"AST_TYPE": "BOND"})
    
    Returns:
        查询结果 {records, total, page, pageSize}
    
    Examples:
        GET /api/v1/zy-data/dwd_ast_info?page=1&pageSize=20
        GET /api/v1/zy-data/dwd_ast_info?filters_json={"AST_TYPE":"BOND"}
    """
    try:
        db = get_db()
        
        # 验证集合是否存在
        if collection not in db.list_collection_names():
            raise HTTPException(
                status_code=404, 
                detail=f"集合 '{collection}' 不存在。使用 /collections 查看可用集合"
            )
        
        # 解析过滤器
        filters = {}
        if filters_json:
            try:
                filters = json.loads(filters_json)
                if not isinstance(filters, dict):
                    raise ValueError("filters_json 必须是 JSON 对象")
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=400, 
                    detail=f"filters_json 格式错误: {str(e)}"
                )
        
        # 构建查询
        query = {**filters}
        
        # 统计总数
        total = db[collection].count_documents(query)
        
        # 分页查询
        skip = (page - 1) * pageSize
        cursor = db[collection].find(query).skip(skip).limit(pageSize)
        records = list(cursor)
        
        # 转换 _id 为字符串(MongoDB ObjectId 不可 JSON 序列化)
        # 同时应用字段别名映射，确保前端 schema 期望的字段都存在
        for rec in records:
            if '_id' in rec:
                rec['_id'] = str(rec['_id'])
            apply_field_aliases(collection, rec)
        
        return {
            "records": records,
            "total": total,
            "page": page,
            "pageSize": pageSize
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询集合 '{collection}' 失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/{collection}/count", response_model=CountResponse)
def count_collection(collection: str):
    """
    统计集合记录数
    
    Args:
        collection: 集合名称
    
    Returns:
        记录总数
    """
    try:
        db = get_db()
        
        if collection not in db.list_collection_names():
            raise HTTPException(
                status_code=404, 
                detail=f"集合 '{collection}' 不存在"
            )
        
        count = db[collection].count_documents({})
        return {"count": count}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"统计集合 '{collection}' 失败: {e}")
        raise HTTPException(status_code=500, detail=f"统计失败: {str(e)}")


@router.post("/{collection}", status_code=201)
def create_record(collection: str, payload: Dict[str, Any]):
    """
    新增记录
    
    Args:
        collection: 集合名称
        payload: 记录数据
    
    Returns:
        新增的记录(含 _id)
    """
    try:
        db = get_db()
        
        if collection not in db.list_collection_names():
            raise HTTPException(
                status_code=404, 
                detail=f"集合 '{collection}' 不存在"
            )
        
        # 插入记录
        result = db[collection].insert_one(payload)
        
        # 返回新增记录
        record = db[collection].find_one({"_id": result.inserted_id})
        record['_id'] = str(record['_id'])
        
        return record
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/{collection}/{record_id}")
def update_record(collection: str, record_id: str, payload: Dict[str, Any]):
    """
    更新记录(全量更新)
    
    Args:
        collection: 集合名称
        record_id: 记录 _id
        payload: 更新数据
    
    Returns:
        更新后的记录
    """
    try:
        db = get_db()
        
        if collection not in db.list_collection_names():
            raise HTTPException(
                status_code=404, 
                detail=f"集合 '{collection}' 不存在"
            )
        
        # 更新记录
        result = db[collection].update_one(
            {"_id": record_id},
            {"$set": payload}
        )
        
        if result.matched_count == 0:
            raise HTTPException(
                status_code=404, 
                detail=f"记录 '{record_id}' 不存在"
            )
        
        # 返回更新后的记录
        record = db[collection].find_one({"_id": record_id})
        record['_id'] = str(record['_id'])
        
        return record
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.delete("/{collection}/{record_id}")
def delete_record(collection: str, record_id: str):
    """
    删除记录
    
    Args:
        collection: 集合名称
        record_id: 记录 _id
    
    Returns:
        {"ok": true}
    """
    try:
        db = get_db()
        
        if collection not in db.list_collection_names():
            raise HTTPException(
                status_code=404, 
                detail=f"集合 '{collection}' 不存在"
            )
        
        # 删除记录
        result = db[collection].delete_one({"_id": record_id})
        
        if result.deleted_count == 0:
            raise HTTPException(
                status_code=404, 
                detail=f"记录 '{record_id}' 不存在"
            )
        
        return {"ok": True}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# ============ 健康检查 ============

@router.get("/health")
def health_check():
    """健康检查接口"""
    try:
        db = get_db()
        # 测试 MongoDB 连接
        db.command('ping')
        collections = len([c for c in db.list_collection_names() if not c.startswith("system.")])
        return {
            "status": "ok",
            "database": DB_NAME,
            "collections": collections
        }
    except Exception as e:
        return {
            "status": "error",
            "detail": str(e)
        }
