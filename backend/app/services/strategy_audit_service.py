# -*- coding: utf-8 -*-
"""治理审计结构化（S15）：状态动作 → 生命周期事件 + 血缘边.

入口只有一个：``LivePublishService.log_live_change``。它原先只写
``strategy_live_change_logs``（人工排障用的自由文本 before/after），
本服务把同一动作再投影成**可查询的结构化事件**：

    strategy_lifecycle_events:
        strategy_id / model_id / version_id / action / from_stage / to_stage /
        operator / source / snapshot_ref / status / created_at
        ``snapshot_ref`` 只指向 ``strategy_versions.version_id``，不复制正文（R1）。

    lineage_nodes / lineage_edges:
        ``strategy_model:{model_id}`` --uses_config--> ``config_version:{version_id}``
        确定性 edge_id + upsert，重复动作不会产生重复边。

覆盖 5 个状态动作：publish / republish / unpublish / live_publish / live_unpublish。
``live_publish_portfolio`` / ``live_config_update`` 等其它动作不在这里处理，
``strategy_live_change_logs`` 的字段与写入路径保持原样（读端零影响）。

全部失败只 warn：审计是旁路，不能反向影响发布/取消发布。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from bson import ObjectId
from loguru import logger

from app.config.collections import (
    COL_LINEAGE_EDGES,
    COL_LINEAGE_NODES,
    COL_STRATEGY_MODELS,
)
from app.config.database import Database
from app.services.strategy_lifecycle_service import StrategyLifecycleService
from app.services.strategy_registry_service import StrategyRegistryService
from app.services.strategy_version_service import StrategyVersionService

__all__ = ["AUDITED_ACTIONS", "LINEAGE_RELATION", "StrategyAuditService"]

# 需要结构化留痕的 5 个状态动作（顺序即业务生命周期顺序）
AUDITED_ACTIONS = (
    "publish",
    "republish",
    "unpublish",
    "live_publish",
    "live_unpublish",
)

# 血缘边语义：模型「使用」了某一版冻结配置
LINEAGE_RELATION = "uses_config"


class StrategyAuditService:
    """状态动作审计（append-only，读端通过 version_id 反查）"""

    @property
    def models_collection(self):
        return Database.get_database()[COL_STRATEGY_MODELS]

    @property
    def nodes_collection(self):
        return Database.get_database()[COL_LINEAGE_NODES]

    @property
    def edges_collection(self):
        return Database.get_database()[COL_LINEAGE_EDGES]

    async def record_action(
        self,
        *,
        model_id: str,
        action: str,
        source: Optional[str] = None,
        operator: Optional[str] = None,
        version_id: Optional[str] = None,
        snapshot_ref: Optional[str] = None,
    ) -> Optional[str]:
        """把一次状态动作写成 1 条生命周期事件（同一 version_id 可反查）.

        Returns:
            关联到的 ``version_id``（解析不到时为 None）。失败返回 None，不抛。
        """
        if action not in AUDITED_ACTIONS or not model_id:
            return None
        try:
            doc = await self._load_model_doc(model_id)
            if doc is None:
                return None
            template_code = doc.get("template_code")
            if version_id is None:
                version_id = await self._resolve_version_id(model_id, doc, action)

            entry = None
            if template_code:
                entry = await StrategyRegistryService().get_by_template_code(template_code)
            strategy_id = entry.strategy_id if entry else None
            stage = entry.lifecycle_stage if entry else None

            ok = await StrategyLifecycleService().append_event(
                model_id=model_id,
                strategy_id=strategy_id,
                version_id=version_id,
                action=action,
                from_stage=stage,
                to_stage=stage,
                operator=operator,
                source=source,
                snapshot_ref=snapshot_ref or version_id,
                status="applied",
            )
            if not ok:
                return version_id
            if version_id:
                await self._link_version(model_id, version_id)
            return version_id
        except Exception as exc:  # noqa: BLE001 —— 审计旁路不得影响主流程
            logger.warning(
                "[strategy_audit] 治理事件写入失败 model_id=%s action=%s: %s",
                model_id, action, exc,
            )
            return None

    async def _load_model_doc(self, model_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(model_id):
            return None
        return await self.models_collection.find_one(
            {"_id": ObjectId(model_id)},
            projection={
                "template_code": 1,
                "published_version": 1,
                "live_published_version": 1,
            },
        )

    @staticmethod
    async def _resolve_version_id(
        model_id: str, doc: dict, action: str
    ) -> Optional[str]:
        """按动作选版本号：实盘动作对齐 live 版本，发布动作对齐 published 版本.

        发布/重发布会先追加版本正文（调用点已保证顺序），这里能直接查到。
        """
        version_no = None
        if action in ("live_publish", "live_unpublish"):
            version_no = doc.get("live_published_version")
        if not version_no:
            version_no = doc.get("published_version")
        if not version_no:
            return None
        try:
            version = await StrategyVersionService().get_version(model_id, int(version_no))
            return version.version_id if version else None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[strategy_audit] 版本解析失败 model_id=%s v%s: %s",
                model_id, version_no, exc,
            )
            return None

    async def _link_version(self, model_id: str, version_id: str) -> None:
        """写血缘节点与边（确定性 ID + upsert，幂等）."""
        try:
            now = datetime.now()
            model_node = f"strategy_model:{model_id}"
            version_node = f"config_version:{version_id}"
            await self.nodes_collection.update_one(
                {"node_id": model_node},
                {
                    "$setOnInsert": {
                        "node_id": model_node,
                        "node_type": "strategy_model",
                        "ref_id": model_id,
                        "created_at": now,
                    }
                },
                upsert=True,
            )
            await self.nodes_collection.update_one(
                {"node_id": version_node},
                {
                    "$setOnInsert": {
                        "node_id": version_node,
                        "node_type": "config_version",
                        "ref_id": version_id,
                        "created_at": now,
                    }
                },
                upsert=True,
            )
            edge_id = f"{model_node}|{LINEAGE_RELATION}|{version_node}"
            await self.edges_collection.update_one(
                {"edge_id": edge_id},
                {
                    "$setOnInsert": {
                        "edge_id": edge_id,
                        "from_node": model_node,
                        "to_node": version_node,
                        "relation": LINEAGE_RELATION,
                        "created_at": now,
                    }
                },
                upsert=True,
            )
        except Exception as exc:  # noqa: BLE001 —— 血缘失败不影响事件
            logger.warning(
                "[strategy_audit] 血缘写入失败 model_id=%s version_id=%s: %s",
                model_id, version_id, exc,
            )
