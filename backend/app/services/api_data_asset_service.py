"""
API 数据资产服务层

提供数据资产全生命周期管理：CRUD、同步、统计、种子初始化。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger
from pymongo import ASCENDING, DESCENDING

from app.config.database import Database
from app.models.api_data_asset import (
    ApiDataAssetCreate,
    ApiDataAssetUpdate,
    AssetStatus,
    DataAssetType,
    SyncStatus,
)
from app.models.data_connector import CONNECTOR_REGISTRY

# ─── 本地导入型资产种子定义 ─────────────────────────────────────────────────────

LOCAL_ASSETS: List[Dict[str, Any]] = [
    {
        "name": "资产基础数据",
        "asset_type": "local_import",
        "target_collection": "assets",
        "description": "通过Excel模板导入的基金/ETF/指数等资产基础信息",
        "primary_key": ["code"],
        "tags": ["资产", "基础数据"],
    },
    {
        "name": "资产行情数据",
        "asset_type": "local_import",
        "target_collection": "asset_prices",
        "description": "资产日频K线行情数据（开高低收量额规模）",
        "primary_key": ["asset_code", "date"],
        "tags": ["行情", "价格"],
    },
    {
        "name": "外汇汇率数据",
        "asset_type": "local_import",
        "target_collection": "fx_rates",
        "description": "EUR/USD/HKD/CNH对人民币汇率日频数据",
        "primary_key": ["date"],
        "tags": ["汇率", "FX"],
    },
]


class ApiDataAssetService:
    """API 数据资产 CRUD 服务"""

    COLLECTION = "api_data_assets"

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    def _coll(self):
        return self.db[self.COLLECTION]

    # ─── 列表查询 ─────────────────────────────────────────────────────────────

    async def list_assets(
        self,
        filters: Optional[Dict[str, Any]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询资产列表，支持 asset_type/status/tags/keyword 筛选"""
        query: Dict[str, Any] = {}
        if filters:
            if filters.get("asset_type"):
                query["asset_type"] = filters["asset_type"]
            if filters.get("status"):
                query["status"] = filters["status"]
            if filters.get("tags"):
                query["tags"] = {"$in": filters["tags"] if isinstance(filters["tags"], list) else [filters["tags"]]}
            if filters.get("keyword"):
                kw = filters["keyword"].strip()
                query["$or"] = [
                    {"name": {"$regex": kw, "$options": "i"}},
                    {"description": {"$regex": kw, "$options": "i"}},
                    {"target_collection": {"$regex": kw, "$options": "i"}},
                ]

        col = self._coll()
        total = await col.count_documents(query)
        skip = (page - 1) * page_size
        cursor = col.find(query, {"_id": 0}).sort("created_at", DESCENDING).skip(skip).limit(page_size)
        items = [doc async for doc in cursor]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if page_size else 0,
        }

    # ─── 获取单个 ─────────────────────────────────────────────────────────────

    async def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """获取单个资产详情"""
        doc = await self._coll().find_one({"asset_id": asset_id}, {"_id": 0})
        return doc

    # ─── 创建 ─────────────────────────────────────────────────────────────────

    async def create_asset(self, data: ApiDataAssetCreate) -> Dict[str, Any]:
        """创建资产记录，自动生成 asset_id 和时间戳"""
        now = datetime.utcnow()
        asset_id = uuid.uuid4().hex[:12]

        doc: Dict[str, Any] = data.model_dump(mode="json")
        doc["asset_id"] = asset_id
        doc["created_at"] = now.isoformat()
        doc["updated_at"] = now.isoformat()
        doc["last_sync_at"] = None
        doc["last_sync_status"] = SyncStatus.never.value
        doc["last_sync_count"] = 0
        doc["total_records"] = doc.get("total_records", 0)

        await self._coll().insert_one(doc)
        doc.pop("_id", None)
        logger.info("[api-data-asset] 创建资产 asset_id={} name={}", asset_id, data.name)
        return doc

    # ─── 更新 ─────────────────────────────────────────────────────────────────

    async def update_asset(self, asset_id: str, data: ApiDataAssetUpdate) -> Optional[Dict[str, Any]]:
        """更新资产信息"""
        update_fields = data.model_dump(mode="json", exclude_none=True)
        if not update_fields:
            return await self.get_asset(asset_id)

        update_fields["updated_at"] = datetime.utcnow().isoformat()

        result = await self._coll().update_one(
            {"asset_id": asset_id},
            {"$set": update_fields},
        )
        if result.matched_count == 0:
            return None

        logger.info("[api-data-asset] 更新资产 asset_id={} fields={}", asset_id, list(update_fields.keys()))
        return await self.get_asset(asset_id)


    # ─── 触发同步 ─────────────────────────────────────────────────────────────

    async def sync_asset(self, asset_id: str) -> Dict[str, Any]:
        """触发数据同步

        对 api_upstream 类型，调用上游 HTTP 拉取逻辑。
        更新 last_sync_at, last_sync_status, last_sync_count。
        返回同步结果摘要。
        """
        asset = await self.get_asset(asset_id)
        if not asset:
            return {"status": "error", "message": f"资产不存在: {asset_id}"}

        asset_type = asset.get("asset_type")
        if asset_type != DataAssetType.api_upstream.value:
            return {"status": "skipped", "message": f"资产类型 {asset_type} 不支持主动同步"}

        source_url = asset.get("source_url")
        source_resource = asset.get("source_resource")
        source_params = asset.get("source_params") or {}
        target_collection = asset.get("target_collection")

        if not source_url:
            return {"status": "error", "message": "资产未配置 source_url"}

        now = datetime.utcnow()
        sync_count = 0
        sync_status = SyncStatus.failed.value

        try:
            # 构造请求体
            payload: Dict[str, Any] = {
                "resource": source_resource or "",
                **source_params,
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    source_url,
                    json=payload,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
            resp.raise_for_status()
            upstream = resp.json()

            # 解析数据列表
            data_list = upstream.get("data") if isinstance(upstream, dict) else None
            if not isinstance(data_list, list):
                data_list = []

            sync_count = len(data_list)

            # 写入目标集合
            if data_list and target_collection:
                col = self.db[target_collection]
                primary_key = asset.get("primary_key") or []
                imported_at = now.isoformat()

                for record in data_list:
                    if not isinstance(record, dict):
                        continue
                    record["_imported_at"] = imported_at
                    if primary_key and all(record.get(k) for k in primary_key):
                        filter_doc = {k: record[k] for k in primary_key}
                        await col.update_one(filter_doc, {"$set": record}, upsert=True)
                    else:
                        await col.insert_one(record)

            sync_status = SyncStatus.success.value
            logger.info("[api-data-asset] 同步成功 asset_id={} count={}", asset_id, sync_count)

        except httpx.TimeoutException as e:
            logger.warning("[api-data-asset] 同步超时 asset_id={}: {}", asset_id, e)
            sync_status = SyncStatus.failed.value
        except httpx.HTTPStatusError as e:
            logger.warning("[api-data-asset] 同步HTTP错误 asset_id={}: {}", asset_id, e)
            sync_status = SyncStatus.failed.value
        except Exception as e:
            logger.exception("[api-data-asset] 同步异常 asset_id={}: {}", asset_id, e)
            sync_status = SyncStatus.failed.value

        # 更新资产同步状态
        await self._coll().update_one(
            {"asset_id": asset_id},
            {"$set": {
                "last_sync_at": now.isoformat(),
                "last_sync_status": sync_status,
                "last_sync_count": sync_count,
                "updated_at": now.isoformat(),
            }},
        )

        return {
            "status": sync_status,
            "asset_id": asset_id,
            "sync_count": sync_count,
            "sync_at": now.isoformat(),
        }

    # ─── 刷新统计 ─────────────────────────────────────────────────────────────

    async def refresh_stats(self, asset_id: str) -> Dict[str, Any]:
        """刷新统计信息

        查询 target_collection 的文档数 -> total_records。
        如果集合中有日期字段，推断 date_range_start/end。
        """
        asset = await self.get_asset(asset_id)
        if not asset:
            return {"status": "error", "message": f"资产不存在: {asset_id}"}

        target_collection = asset.get("target_collection")
        if not target_collection:
            return {"status": "error", "message": "资产未配置 target_collection"}

        col = self.db[target_collection]
        total_records = await col.count_documents({})

        update_doc: Dict[str, Any] = {
            "total_records": total_records,
            "updated_at": datetime.utcnow().isoformat(),
        }

        # 尝试推断日期范围（常见日期字段）
        date_field_candidates = ["date", "biz_date", "trade_date", "data_date"]
        for date_field in date_field_candidates:
            sample = await col.find_one({date_field: {"$exists": True, "$ne": None}})
            if sample:
                # 找最小值
                earliest = await col.find_one(
                    {date_field: {"$exists": True, "$ne": None}},
                    sort=[(date_field, ASCENDING)],
                )
                latest = await col.find_one(
                    {date_field: {"$exists": True, "$ne": None}},
                    sort=[(date_field, DESCENDING)],
                )
                if earliest and latest:
                    update_doc["date_range_start"] = str(earliest[date_field])
                    update_doc["date_range_end"] = str(latest[date_field])
                break

        await self._coll().update_one({"asset_id": asset_id}, {"$set": update_doc})

        logger.info("[api-data-asset] 刷新统计 asset_id={} total_records={}", asset_id, total_records)
        return {
            "status": "success",
            "asset_id": asset_id,
            "total_records": total_records,
            "date_range_start": update_doc.get("date_range_start"),
            "date_range_end": update_doc.get("date_range_end"),
        }

    # ─── 从连接器种子初始化 ───────────────────────────────────────────────────

    async def seed_from_connectors(self) -> Dict[str, Any]:
        """从现有 CONNECTOR_REGISTRY 批量初始化资产记录

        读取 data_connector.py 中的 CONNECTOR_REGISTRY，对每个连接器检查是否已存在对应资产。
        不存在则创建。同时创建本地导入型资产。
        返回 {created: N, skipped: N}
        """
        created = 0
        skipped = 0
        now = datetime.utcnow()
        col = self._coll()

        # 从连接器注册表创建 api_upstream 型资产
        for connector_id, conn in CONNECTOR_REGISTRY.items():
            existing = await col.find_one({"connector_id": connector_id})
            if existing:
                skipped += 1
                continue

            asset_id = uuid.uuid4().hex[:12]
            doc: Dict[str, Any] = {
                "asset_id": asset_id,
                "name": conn.title,
                "asset_type": DataAssetType.api_upstream.value,
                "description": conn.description or f"来自连接器 {connector_id}",
                "source_url": conn.default_upstream_url,
                "source_resource": conn.resource_default,
                "source_params": {},
                "auth_type": "none",
                "target_collection": conn.records_collection,
                "primary_key": [conn.primary_key],
                "schema_fields": [],
                "sync_strategy": "manual",
                "sync_cron": None,
                "last_sync_at": None,
                "last_sync_status": SyncStatus.never.value,
                "last_sync_count": 0,
                "total_records": 0,
                "date_range_start": None,
                "date_range_end": None,
                "connector_id": connector_id,
                "tags": ["上游接入", connector_id],
                "owner": "",
                "status": AssetStatus.active.value,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            await col.insert_one(doc)
            created += 1
            logger.info("[api-data-asset] seed 创建上游资产 connector_id={} asset_id={}", connector_id, asset_id)

        # 创建本地导入型资产
        for local_def in LOCAL_ASSETS:
            existing = await col.find_one({"target_collection": local_def["target_collection"], "asset_type": "local_import"})
            if existing:
                skipped += 1
                continue

            asset_id = uuid.uuid4().hex[:12]
            doc = {
                "asset_id": asset_id,
                "name": local_def["name"],
                "asset_type": DataAssetType.local_import.value,
                "description": local_def.get("description", ""),
                "source_url": None,
                "source_resource": None,
                "source_params": {},
                "auth_type": "none",
                "target_collection": local_def["target_collection"],
                "primary_key": local_def.get("primary_key", []),
                "schema_fields": [],
                "sync_strategy": "manual",
                "sync_cron": None,
                "last_sync_at": None,
                "last_sync_status": SyncStatus.never.value,
                "last_sync_count": 0,
                "total_records": 0,
                "date_range_start": None,
                "date_range_end": None,
                "connector_id": None,
                "tags": local_def.get("tags", []),
                "owner": "",
                "status": AssetStatus.active.value,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            await col.insert_one(doc)
            created += 1
            logger.info("[api-data-asset] seed 创建本地资产 name={} asset_id={}", local_def["name"], asset_id)

        logger.info("[api-data-asset] seed 完成 created={} skipped={}", created, skipped)
        return {"created": created, "skipped": skipped}

    # ─── 汇总统计 ─────────────────────────────────────────────────────────────

    async def get_summary_stats(self) -> Dict[str, Any]:
        """汇总统计（扁平结构，匹配前端字段）

        返回:
        - total: 总资产数
        - active: 活跃资产数
        - api_upstream: API上游类型数量
        - local_import: 本地导入类型数量
        - computed: 计算衍生类型数量
        - sync_failed: 最近同步失败的数量
        - last_sync_at: 最近一次同步时间
        """
        col = self._coll()
        total = await col.count_documents({})

        # 按类型统计
        type_pipeline = [
            {"$group": {"_id": "$asset_type", "count": {"$sum": 1}}},
        ]
        type_agg = [item async for item in col.aggregate(type_pipeline)]
        by_type: Dict[str, int] = {
            DataAssetType.api_upstream.value: 0,
            DataAssetType.local_import.value: 0,
            DataAssetType.computed.value: 0,
        }
        for item in type_agg:
            key = item.get("_id")
            if key in by_type:
                by_type[key] = item.get("count", 0)

        # 按状态统计
        status_pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        status_agg = [item async for item in col.aggregate(status_pipeline)]
        by_status: Dict[str, int] = {
            AssetStatus.active.value: 0,
            AssetStatus.deprecated.value: 0,
        }
        for item in status_agg:
            key = item.get("_id")
            if key in by_status:
                by_status[key] = item.get("count", 0)

        # 最近同步失败数
        sync_failed = await col.count_documents({"last_sync_status": SyncStatus.failed.value})

        # 最近一次同步时间
        latest_synced = await col.find_one(
            {"last_sync_at": {"$ne": None}},
            {"last_sync_at": 1},
            sort=[("last_sync_at", DESCENDING)],
        )
        last_sync_at = latest_synced.get("last_sync_at") if latest_synced else None

        # 返回扁平结构，直接匹配前端字段名
        return {
            "total": total,
            "active": by_status.get(AssetStatus.active.value, 0),
            "api_upstream": by_type.get(DataAssetType.api_upstream.value, 0),
            "local_import": by_type.get(DataAssetType.local_import.value, 0),
            "computed": by_type.get(DataAssetType.computed.value, 0),
            "sync_failed": sync_failed,
            "last_sync_at": last_sync_at,
        }
