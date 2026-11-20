# -*- coding: utf-8 -*-
"""策略配置版本服务 —— append-only 写入与版本链查询.

追加写约束（R3）：
    - 只在主操作成功之后调用；调用方用整块 try/except 包裹，本服务失败只
      warn，绝不向上抛（不改变发布的原返回值与 return 分支）；
    - 幂等：同一 ``(model_id, version_no)`` 重复写入时返回已存在的
      ``version_id``，不覆盖正文（并发重复发布时唯一索引兜底，捕获
      DuplicateKeyError 后回查）。

``strategy_id`` 反查策略：
    优先用调用方传入值；未传时按 ``template_code`` 查 ``strategy_registry``
    （走 ``get_by_template_code``，兼容旧别名），查不到记 None 而不是报错 ——
    版本链的价值在正文与指纹，身份回填失败不该阻塞发布。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

try:  # pymongo 3.x/4.x 路径差异
    from pymongo.errors import DuplicateKeyError
except Exception:  # pragma: no cover - 极老版本兜底
    DuplicateKeyError = Exception  # type: ignore

from app.config.collections import COL_STRATEGY_VERSIONS
from app.config.database import Database
from app.models.strategy_version import SOURCE_ACTIONS, StrategyVersion
from app.services.strategy_fingerprint import contract_hash as _contract_hash
from app.services.strategy_fingerprint import pool_hash as _pool_hash

logger = logging.getLogger(__name__)

__all__ = ["StrategyVersionService"]


def resolve_contract_hash(template_code: Optional[str]) -> Optional[str]:
    """按策略码静态反射 ``get_data_contract()`` 并取契约指纹.

    全部异常吞掉返回 None：契约缺失不是发布失败的理由，只是版本里少一个
    指纹键（读取侧按 Optional 处理）。
    """
    code = str(template_code or "").strip()
    if not code:
        return None
    try:
        from app.allocation.strategy_manifest import resolve_class_safe

        cls = resolve_class_safe(code)
        getter = getattr(cls, "get_data_contract", None) if cls is not None else None
        if not callable(getter):
            return None
        return _contract_hash(getter())
    except Exception as exc:  # noqa: BLE001 —— 反射失败只降级
        logger.warning("[strategy_versions] 契约指纹计算失败 template_code=%s: %s", code, exc)
        return None


class StrategyVersionService:
    """策略配置版本读写（写入只有 append 一条路径）"""

    @property
    def collection(self):
        return Database.get_database()[COL_STRATEGY_VERSIONS]

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    async def append_version(
        self,
        model_id: str,
        version_no: int,
        source_action: str,
        snapshot_body: Dict[str, Any],
        config_fingerprint: Optional[str] = None,
        template_code: Optional[str] = None,
        operator: Optional[str] = None,
        strategy_id: Optional[str] = None,
    ) -> Optional[str]:
        """追加一条版本记录，返回 version_id；已存在同版本返回原 version_id."""
        model_id = str(model_id or "").strip()
        if not model_id:
            return None
        version_no = int(version_no or 0)
        if version_no <= 0:
            return None

        existing = await self.get_version(model_id, version_no)
        if existing is not None:
            return existing.version_id

        parent = await self.latest_version(model_id)
        resolved_strategy_id = strategy_id or await self._lookup_strategy_id(template_code)
        body = dict(snapshot_body or {})
        doc = {
            "version_id": str(uuid.uuid4()),
            "strategy_id": resolved_strategy_id,
            "model_id": model_id,
            "template_code": template_code,
            "version_no": version_no,
            "source_action": source_action if source_action in SOURCE_ACTIONS else "publish",
            "parent_version_id": parent.version_id if parent else None,
            "snapshot_body": body,
            "config_fingerprint": config_fingerprint,
            "asset_pool_hash": _pool_hash(body.get("asset_codes") or []),
            "contract_hash": resolve_contract_hash(template_code),
            "operator": operator,
            "created_at": datetime.now(),
            "schema_version": 1,
        }
        try:
            await self.collection.insert_one(doc)
            return doc["version_id"]
        except DuplicateKeyError:
            # 并发重复发布：回查已存在文档，保持 append-only 不覆盖
            dup = await self.get_version(model_id, version_no)
            return dup.version_id if dup else None
        except Exception as exc:  # noqa: BLE001 —— 由调用方决定是否记录，本层不抛
            logger.warning(
                "[strategy_versions] 版本追加失败 model_id=%s version_no=%s: %s",
                model_id, version_no, exc,
            )
            return None

    async def _lookup_strategy_id(self, template_code: Optional[str]) -> Optional[str]:
        code = str(template_code or "").strip()
        if not code:
            return None
        try:
            from app.services.strategy_registry_service import StrategyRegistryService

            entry = await StrategyRegistryService().get_by_template_code(code)
            return entry.strategy_id if entry else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[strategy_versions] strategy_id 反查失败 code=%s: %s", code, exc)
            return None

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    async def get_version(self, model_id: str, version_no: int) -> Optional[StrategyVersion]:
        doc = await self.collection.find_one({"model_id": model_id, "version_no": int(version_no)})
        return self._to_model(doc)

    async def get_by_version_id(self, version_id: str) -> Optional[StrategyVersion]:
        if not version_id:
            return None
        doc = await self.collection.find_one({"version_id": version_id})
        return self._to_model(doc)

    async def latest_version(self, model_id: str) -> Optional[StrategyVersion]:
        if not model_id:
            return None
        doc = await self.collection.find_one(
            {"model_id": model_id}, sort=[("version_no", -1)]
        )
        return self._to_model(doc)

    async def latest_version_id(self, model_id: str) -> Optional[str]:
        """供回测/监控身份回填（S12/S13）取当前配置版本 ID."""
        latest = await self.latest_version(model_id)
        return latest.version_id if latest else None

    async def list_versions(
        self,
        model_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[StrategyVersion]:
        """按模型或按策略本体列版本（策略库查询 API 用 strategy_id）."""
        query: Dict[str, Any] = {}
        if model_id:
            query["model_id"] = model_id
        if strategy_id:
            query["strategy_id"] = strategy_id
        if not query:
            return []
        cursor = (
            self.collection.find(query)
            .sort([("version_no", -1), ("created_at", -1)])
            .skip(max(0, int(skip)))
            .limit(max(1, int(limit)))
        )
        return [self._to_model(doc) async for doc in cursor if doc]  # type: ignore[list-item]

    async def count(self, model_id: Optional[str] = None) -> int:
        query: Dict[str, Any] = {"model_id": model_id} if model_id else {}
        return int(await self.collection.count_documents(query))

    @staticmethod
    def _to_model(doc: Optional[Dict[str, Any]]) -> Optional[StrategyVersion]:
        if not doc:
            return None
        data = dict(doc)
        data["_id"] = str(data["_id"])
        return StrategyVersion(**data)
