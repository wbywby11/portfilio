"""监测策略 CRUD 服务

管理 monitored_strategies 集合：列表/新增/改名/暂停/归档/删除。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from loguru import logger
from pymongo.errors import DuplicateKeyError

from app.config.database import Database
from app.models.monitored_strategy import MonitoredStrategy, MonitoredSourceType, MonitoredStatus


class MonitoredStrategyService:
    """监测策略管理服务"""

    COLLECTION = "monitored_strategies"

    def __init__(self):
        self.db = Database.get_database()
        self.collection = self.db[self.COLLECTION]

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def ensure_researcher_seeded(self) -> None:
        """确保所有研究员策略已注册到 monitored_strategies（幂等）。

        首次调用时自动将 registry 中的研究员策略写入集合，
        后续调用检测到已存在则跳过。已归档的保持归档状态不变，
        仅当用户通过「添加策略」显式操作时才重新激活。
        """
        from app.monitor.researcher_strategies import RESEARCHER_STRATEGY_REGISTRY

        for code, strategy in RESEARCHER_STRATEGY_REGISTRY.items():
            existing = await self.get_by_source_ref("researcher", code)
            if existing is None:
                doc = strategy.to_monitored_strategy_doc()
                try:
                    await self.create(doc)
                    logger.info(f"自动注册研究员策略: {code} ({strategy.display_name})")
                except DuplicateKeyError:
                    logger.debug(f"研究员策略已存在(并发种子): {code}")
            # 已归档的策略保持归档状态，不自动重新激活

    async def sync_live_published(self) -> None:
        """将已实盘发布的策略/组合同步到 monitored_strategies（幂等）。

        遍历 strategy_models 中 live_publish_enabled=True 的文档：
        - 尚无对应条目 → 自动创建；
        - 已实盘发布但条目被归档（如取消实盘后又重新实盘发布）→ 重新激活；
        - 已不再实盘发布 → 条目归档下架（monitor_states 与历史记录保留）。
        """
        from app.services.strategy_model_service import StrategyModelService

        svc = StrategyModelService()
        live_refs: List[str] = []
        # 查询所有已实盘发布的模型
        cursor = svc.collection.find(
            {"live_publish_enabled": True},
            {"name": 1, "is_portfolio": 1, "template_code": 1, "asset_codes": 1},
        )
        async for doc in cursor:
            model_id = str(doc["_id"])
            live_refs.append(model_id)
            is_portfolio = doc.get("is_portfolio", False)
            source_type = "portfolio" if is_portfolio else "system_strategy"

            existing = await self.get_by_source_ref(source_type, model_id)
            if existing is not None:
                # 已归档但模型重新实盘发布 → 自动重新激活
                if (
                    existing.get("status") == "archived"
                    and doc.get("live_publish_enabled")
                ):
                    await self.update_status(str(existing["_id"]), "active")
                    logger.info(
                        f"重新激活已归档的实盘策略: {existing.get('display_name')} ({source_type}/{model_id})"
                    )
                continue

            name = doc.get("name", f"策略{model_id[:8]}")
            new_doc = {
                "display_name": name,
                "source_type": source_type,
                "source_ref": model_id,
                "description": f"实盘发布{'组合' if is_portfolio else '策略'}（{doc.get('template_code', '')}）",
                "asset_codes": doc.get("asset_codes", []),
                "status": "active",
            }
            try:
                await self.create(new_doc)
                logger.info(f"同步实盘发布到监控: {name} ({source_type}/{model_id})")
            except DuplicateKeyError:
                logger.debug(f"实盘策略已存在(并发同步): {model_id}")

        # 已取消实盘发布 → 条目归档下架（不删除 monitor_states / 变更日志）
        if live_refs:
            archive_filter = {
                "source_type": {"$in": ["system_strategy", "portfolio"]},
                "status": {"$ne": "archived"},
                "source_ref": {"$nin": live_refs},
            }
        else:
            archive_filter = {
                "source_type": {"$in": ["system_strategy", "portfolio"]},
                "status": {"$ne": "archived"},
            }
        now = datetime.now()
        result = await self.collection.update_many(
            archive_filter,
            {
                "$set": {
                    "status": "archived",
                    "archive_reason": "not_live_published",
                    "archived_at": now,
                    "updated_at": now,
                }
            },
        )
        if result.modified_count:
            logger.info(f"归档已取消实盘发布的监控条目: {result.modified_count} 条")

    async def list(
        self,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """列出监测策略（默认排除 archived）。首次调用自动种子研究员策略并同步实盘发布。"""
        # 自动确保研究员策略已注册 + 实盘发布同步
        try:
            await self.ensure_researcher_seeded()
        except Exception as e:
            logger.warning(f"研究员策略种子失败(不影响列表): {e}")
        try:
            await self.sync_live_published()
        except Exception as e:
            logger.warning(f"实盘同步失败(不影响列表): {e}")

        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        else:
            query["status"] = {"$ne": "archived"}
        if source_type:
            query["source_type"] = source_type

        cursor = (
            self.collection.find(query)
            .sort("created_at", 1)
            .skip(skip)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)
        return docs

    async def count(self, status: Optional[str] = None) -> int:
        """计数。"""
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        else:
            query["status"] = {"$ne": "archived"}
        return await self.collection.count_documents(query)

    async def get(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取单条。"""
        if not ObjectId.is_valid(strategy_id):
            return None
        return await self.collection.find_one({"_id": ObjectId(strategy_id)})

    async def get_by_source_ref(
        self, source_type: str, source_ref: str
    ) -> Optional[Dict[str, Any]]:
        """按来源查找（用于去重）。"""
        return await self.collection.find_one(
            {"source_type": source_type, "source_ref": source_ref}
        )

    # ------------------------------------------------------------------
    # 新增
    # ------------------------------------------------------------------

    async def create(self, data: Dict[str, Any]) -> str:
        """新增监测策略。

        Args:
            data: 策略文档（含 display_name/source_type/source_ref/composition 等）

        Returns:
            新文档 ID（str）
        """
        now = datetime.now()
        data["created_at"] = now
        data["updated_at"] = now
        data.setdefault("status", "active")

        result = await self.collection.insert_one(data)
        logger.info(f"新增监测策略: {data.get('display_name')} (id={result.inserted_id})")
        return str(result.inserted_id)

    async def create_from_researcher(self, code: str) -> str:
        """从研究员策略 code 创建监测策略条目。"""
        from app.monitor.researcher_strategies import get_researcher_strategy

        strategy = get_researcher_strategy(code)
        if strategy is None:
            raise ValueError(f"未知的研究员策略: {code!r}")

        # 检查是否已存在（含已归档）
        existing = await self.get_by_source_ref("researcher", code)
        if existing:
            # 若已归档则重新激活
            if existing.get("status") == "archived":
                await self.update_status(str(existing["_id"]), "active")
            return str(existing["_id"])

        doc = strategy.to_monitored_strategy_doc()
        return await self.create(doc)

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------

    async def rename(self, strategy_id: str, new_name: str) -> bool:
        """改名。"""
        if not ObjectId.is_valid(strategy_id):
            return False
        result = await self.collection.update_one(
            {"_id": ObjectId(strategy_id)},
            {"$set": {"display_name": new_name, "updated_at": datetime.now()}},
        )
        return result.modified_count > 0

    async def update_status(self, strategy_id: str, status: str) -> bool:
        """更新状态（active/paused/archived）。"""
        if not ObjectId.is_valid(strategy_id):
            return False
        if status not in ("active", "paused", "archived"):
            return False
        result = await self.collection.update_one(
            {"_id": ObjectId(strategy_id)},
            {"$set": {"status": status, "updated_at": datetime.now()}},
        )
        return result.modified_count > 0

    async def update(self, strategy_id: str, updates: Dict[str, Any]) -> bool:
        """通用更新（仅允许安全字段）。"""
        if not ObjectId.is_valid(strategy_id):
            return False
        allowed_fields = {"display_name", "status", "description"}
        safe_updates = {k: v for k, v in updates.items() if k in allowed_fields and v is not None}
        if not safe_updates:
            return False
        safe_updates["updated_at"] = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(strategy_id)},
            {"$set": safe_updates},
        )
        return result.modified_count > 0

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    async def delete(self, strategy_id: str) -> bool:
        """硬删除（仅用于清理测试数据，正常流程用 archived）。"""
        if not ObjectId.is_valid(strategy_id):
            return False
        result = await self.collection.delete_one({"_id": ObjectId(strategy_id)})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    async def ensure_indexes(self):
        """确保集合索引存在。"""
        await self.collection.create_index(
            [("source_type", 1), ("source_ref", 1)], unique=True
        )
        await self.collection.create_index([("status", 1)])
