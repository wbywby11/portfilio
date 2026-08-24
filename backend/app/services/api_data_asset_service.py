"""
数据资产服务 - 基于 MongoDB 实际集合的元数据注册表

扫描数据库中所有实际存在的集合，实时采集统计信息。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from pymongo import ASCENDING, DESCENDING

from app.config.database import Database
from app.models.api_data_asset import (
    AssetStatus,
    CollectionAsset,
    CollectionAssetUpdate,
)

# 系统集合前缀/名称（不展示给用户）
SYSTEM_COLLECTIONS = {
    "system.views", "system.profile", "system.js",
}
SYSTEM_PREFIXES = ("system.",)

# 常见日期字段名（按优先级探测）
DATE_FIELD_CANDIDATES = [
    "date", "biz_date", "trade_date", "data_date",
    "created_at", "updated_at", "timestamp", "day",
]


class ApiDataAssetService:
    """数据资产服务 - 扫描 MongoDB 实际集合"""

    COLLECTION = "_data_asset_registry"

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    def _registry(self):
        """人工编辑信息注册表（存储 description/tags/owner 等）"""
        return self.db[self.COLLECTION]

    # ─── 扫描数据库 ──────────────────────────────────────────────────────────

    async def scan_database(self) -> Dict[str, Any]:
        """扫描 MongoDB 所有实际集合，返回统计信息

        对每个集合：
        - count_documents({}) 获取记录数
        - collStats 获取存储大小
        - 采样第 1 条记录推断字段列表
        - 自动探测日期字段并获取 min/max
        """
        collection_names = await self.db.list_collection_names()
        # 过滤系统集合
        collection_names = [
            name for name in collection_names
            if name not in SYSTEM_COLLECTIONS
            and not any(name.startswith(p) for p in SYSTEM_PREFIXES)
        ]
        collection_names.sort()

        scanned = []
        total_records = 0
        total_storage = 0

        for name in collection_names:
            try:
                asset = await self._scan_single_collection(name)
                scanned.append(asset)
                total_records += asset.record_count
                total_storage += asset.storage_size_bytes
            except Exception as e:
                logger.warning("[data-asset] 扫描集合 {} 失败: {}", name, e)
                scanned.append(CollectionAsset(
                    collection_name=name,
                    record_count=0,
                    storage_size_bytes=0,
                    fields=[],
                    field_count=0,
                ))

        # 更新注册表中的扫描时间
        now = datetime.utcnow().isoformat()
        for asset in scanned:
            asset.last_scanned_at = now
            # 合并人工编辑信息
            existing = await self._registry().find_one(
                {"collection_name": asset.collection_name}, {"_id": 0}
            )
            if existing:
                asset.description = existing.get("description", "")
                asset.tags = existing.get("tags", [])
                asset.owner = existing.get("owner", "")
                asset.status = AssetStatus(existing.get("status", "active"))

        logger.info(
            "[data-asset] 扫描完成: {} 个集合, {} 条记录, {} 字节",
            len(scanned), total_records, total_storage,
        )

        return {
            "collections": [a.model_dump() for a in scanned],
            "total": len(scanned),
            "total_records": total_records,
            "total_storage_bytes": total_storage,
            "scanned_at": now,
        }

    async def _scan_single_collection(self, name: str) -> CollectionAsset:
        """扫描单个集合的实际统计信息"""
        coll = self.db[name]

        # 记录数
        record_count = await coll.count_documents({})

        # 存储大小
        storage_size = 0
        try:
            stats = await self.db.command("collStats", name)
            storage_size = stats.get("size", 0)
        except Exception:
            pass

        # 字段采样（取第 1 条）
        fields = []
        sample = await coll.find_one({}, {"_id": 0})
        if sample:
            fields = list(sample.keys())

        # 日期字段探测
        date_field = None
        date_range = None
        for candidate in DATE_FIELD_CANDIDATES:
            if candidate in fields:
                date_field = candidate
                try:
                    earliest = await coll.find_one(
                        {candidate: {"$exists": True, "$ne": None}},
                        {candidate: 1, "_id": 0},
                        sort=[(candidate, ASCENDING)],
                    )
                    latest = await coll.find_one(
                        {candidate: {"$exists": True, "$ne": None}},
                        {candidate: 1, "_id": 0},
                        sort=[(candidate, DESCENDING)],
                    )
                    if earliest and latest:
                        date_range = {
                            "min": str(earliest[candidate]),
                            "max": str(latest[candidate]),
                        }
                except Exception:
                    pass
                break

        return CollectionAsset(
            collection_name=name,
            record_count=record_count,
            storage_size_bytes=storage_size,
            fields=fields,
            field_count=len(fields),
            date_field=date_field,
            date_range=date_range,
        )

    # ─── 刷新单个资产 ────────────────────────────────────────────────────────

    async def refresh_asset(self, collection_name: str) -> Dict[str, Any]:
        """刷新单个集合的实时统计信息"""
        if collection_name not in await self.db.list_collection_names():
            return {"status": "error", "message": f"集合不存在: {collection_name}"}

        asset = await self._scan_single_collection(collection_name)
        asset.last_scanned_at = datetime.utcnow().isoformat()

        # 合并人工编辑信息
        existing = await self._registry().find_one(
            {"collection_name": collection_name}, {"_id": 0}
        )
        if existing:
            asset.description = existing.get("description", "")
            asset.tags = existing.get("tags", [])
            asset.owner = existing.get("owner", "")
            asset.status = AssetStatus(existing.get("status", "active"))

        return {"status": "success", "asset": asset.model_dump()}

    # ─── 数据预览 ────────────────────────────────────────────────────────────

    async def preview_collection(self, collection_name: str, limit: int = 10) -> Dict[str, Any]:
        """预览集合的前 N 条数据"""
        coll = self.db[collection_name]
        total = await coll.count_documents({})
        cursor = coll.find({}, {"_id": 0}).limit(limit)
        records = await cursor.to_list(length=limit)

        # 序列化特殊类型
        def _serialize(doc):
            if not isinstance(doc, dict):
                return doc
            result = {}
            for k, v in doc.items():
                if hasattr(v, "isoformat"):
                    result[k] = v.isoformat()
                elif isinstance(v, dict):
                    result[k] = _serialize(v)
                else:
                    result[k] = v
            return result

        return {
            "collection_name": collection_name,
            "total": total,
            "records": [_serialize(r) for r in records],
        }

    # ─── 更新人工编辑信息 ──────────────────────────────────────────────────────

    async def update_asset(self, collection_name: str, data: CollectionAssetUpdate) -> Optional[Dict[str, Any]]:
        """更新人工编辑信息（description/tags/owner/status）"""
        update_fields = data.model_dump(mode="json", exclude_none=True)
        if not update_fields:
            return await self.get_asset(collection_name)

        update_fields["updated_at"] = datetime.utcnow().isoformat()

        await self._registry().update_one(
            {"collection_name": collection_name},
            {"$set": update_fields, "$setOnInsert": {"collection_name": collection_name, "created_at": datetime.utcnow().isoformat()}},
            upsert=True,
        )
        return await self.get_asset(collection_name)

    # ─── 获取单个 ────────────────────────────────────────────────────────────

    async def get_asset(self, collection_name: str) -> Optional[Dict[str, Any]]:
        """获取单个集合的完整信息（实时统计 + 人工编辑）"""
        if collection_name not in await self.db.list_collection_names():
            return None

        asset = await self._scan_single_collection(collection_name)
        asset.last_scanned_at = datetime.utcnow().isoformat()

        # 合并人工编辑信息
        existing = await self._registry().find_one(
            {"collection_name": collection_name}, {"_id": 0}
        )
        if existing:
            asset.description = existing.get("description", "")
            asset.tags = existing.get("tags", [])
            asset.owner = existing.get("owner", "")
            asset.status = AssetStatus(existing.get("status", "active"))
            asset.created_at = existing.get("created_at")

        return asset.model_dump()

    # ─── 列表查询 ────────────────────────────────────────────────────────────

    async def list_assets(
        self,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """列出所有集合资产（分页）

        先扫描数据库获取实时统计，再合并注册表中的人工编辑信息。
        """
        scan_result = await self.scan_database()
        items = scan_result["collections"]

        # 筛选
        if keyword:
            kw = keyword.lower()
            items = [
                i for i in items
                if kw in i["collection_name"].lower()
                or kw in (i.get("description") or "").lower()
                or any(kw in t.lower() for t in (i.get("tags") or []))
            ]
        if status:
            items = [i for i in items if i.get("status") == status]

        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        paged_items = items[start:end]

        return {
            "items": paged_items,
            "total": total,
            "total_records": scan_result["total_records"],
            "total_storage_bytes": scan_result["total_storage_bytes"],
            "scanned_at": scan_result["scanned_at"],
        }

    # ─── 汇总统计 ────────────────────────────────────────────────────────────

    async def get_summary_stats(self) -> Dict[str, Any]:
        """汇总统计"""
        scan_result = await self.scan_database()
        collections = scan_result["collections"]

        active_count = sum(1 for c in collections if c.get("status") == "active")

        return {
            "total": len(collections),
            "active": active_count,
            "total_records": scan_result["total_records"],
            "total_storage_bytes": scan_result["total_storage_bytes"],
            "scanned_at": scan_result["scanned_at"],
        }