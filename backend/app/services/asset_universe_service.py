# -*- coding: utf-8 -*-
"""资产池版本服务 —— 追加写版本 + 按日期解析 active 版本.

写入口径：
    - ``version`` 由本服务按 ``max(version)+1`` 计算，调用方不指定；
    - ``(universe_id, version)`` 唯一索引兜底（app/config/index_specs.py），
      并发重复写入捕获 DuplicateKeyError 后回查返回；
    - 资产代码排序去重后入库存，``pool_hash`` 与发布快照/回测侧的池哈希同口径
      （:func:`app.services.strategy_fingerprint.pool_hash`）。

解析口径：
    ``resolve_active`` 按 ``universe_id`` 降序扫版本，返回第一个区间命中 as_of
    的版本；区间按**日期**比较（含两端），``effective_to`` 为空视为无截止日。
    扫描在应用层做而不是拼 Mongo 日期查询：版本数极少（单池通常个位数），
    而按日期比较能避开「effective_to 当天是否算生效」的时区/时分歧义。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

try:  # pymongo 3.x/4.x 路径差异
    from pymongo.errors import DuplicateKeyError
except Exception:  # pragma: no cover - 极老版本兜底
    DuplicateKeyError = Exception  # type: ignore

from app.config.collections import COL_ASSET_UNIVERSE_VERSIONS
from app.config.database import Database
from app.models.asset_universe_version import AssetUniverseVersion
from app.services.strategy_fingerprint import normalize_codes, pool_hash

logger = logging.getLogger(__name__)

__all__ = ["AssetUniverseService", "to_date"]


def to_date(value: Any) -> Optional[date]:
    """把 datetime / date / ISO 字符串归一为 date；无法解析返回 None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:19]).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


class AssetUniverseService:
    """资产池版本读写"""

    @property
    def collection(self):
        return Database.get_database()[COL_ASSET_UNIVERSE_VERSIONS]

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    async def write_version(
        self,
        universe_id: str,
        asset_codes: List[str],
        asset_names: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
        source: str = "model",
        effective_from: Any = None,
        effective_to: Any = None,
        created_by: Optional[str] = None,
    ) -> Optional[AssetUniverseVersion]:
        """追加一个资产池版本，返回落库后的文档；失败只 warn 返回 None."""
        uid = str(universe_id or "").strip()
        if not uid:
            return None
        codes = normalize_codes(asset_codes)
        if not codes:
            return None

        next_version = await self._next_version(uid)
        now = datetime.now()
        doc = {
            "universe_id": uid,
            "version": next_version,
            "name": name,
            "asset_codes": codes,
            "asset_names": {str(k): str(v) for k, v in (asset_names or {}).items()},
            "pool_hash": pool_hash(codes),
            "source": source if source in ("model", "tags", "preset") else "model",
            "effective_from": self._as_datetime(effective_from) or now,
            "effective_to": self._as_datetime(effective_to),
            "frozen_at": now,
            "created_by": created_by,
        }
        try:
            await self.collection.insert_one(doc)
        except DuplicateKeyError:
            # 并发写同一版本：回查已存在文档（append-only，不覆盖）
            existing = await self.collection.find_one(
                {"universe_id": uid, "version": next_version}
            )
            return self._to_model(existing)
        except Exception as exc:  # noqa: BLE001 —— 调用方按可降级处理
            logger.warning("[asset_universe] 版本写入失败 universe_id=%s: %s", uid, exc)
            return None
        return self._to_model({**doc, "_id": None})

    async def _next_version(self, universe_id: str) -> int:
        latest = await self.collection.find_one(
            {"universe_id": universe_id}, sort=[("version", -1)], projection={"version": 1}
        )
        return int((latest or {}).get("version") or 0) + 1

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    async def resolve_active(
        self, universe_id: str, as_of: Any = None
    ) -> Optional[AssetUniverseVersion]:
        """解析 ``as_of`` 当天生效的版本（含两端；as_of 缺省为今天）."""
        uid = str(universe_id or "").strip()
        if not uid:
            return None
        target = to_date(as_of) or datetime.now().date()
        cursor = self.collection.find({"universe_id": uid}).sort("version", -1)
        async for doc in cursor:
            start = to_date(doc.get("effective_from"))
            end = to_date(doc.get("effective_to"))
            if start is not None and start > target:
                continue
            if end is not None and end < target:
                continue
            return self._to_model(doc)
        return None

    async def resolve_active_for_model(
        self, model: Any, as_of: Any = None
    ) -> Optional[AssetUniverseVersion]:
        """按模型 ``parameters["asset_universe_ref"]`` 解析 active 版本.

        未绑定资产池的模型直接返回 None，**不查库**（发布主链路上绝大多数模型
        走这条分支，不能为未绑定的模型加一次无谓往返）。
        """
        params = getattr(model, "parameters", None) or {}
        ref = params.get("asset_universe_ref") if isinstance(params, dict) else None
        if not ref:
            return None
        return await self.resolve_active(str(ref), as_of=as_of)

    async def list_versions(
        self, universe_id: str, limit: int = 50
    ) -> List[AssetUniverseVersion]:
        uid = str(universe_id or "").strip()
        if not uid:
            return []
        cursor = (
            self.collection.find({"universe_id": uid})
            .sort("version", -1)
            .limit(max(1, int(limit)))
        )
        return [self._to_model(doc) async for doc in cursor if doc]  # type: ignore[list-item]

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _as_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text[:19])
        except ValueError:
            parsed = to_date(text)
            return datetime(parsed.year, parsed.month, parsed.day) if parsed else None

    @staticmethod
    def _to_model(doc: Optional[Dict[str, Any]]) -> Optional[AssetUniverseVersion]:
        if not doc:
            return None
        data = dict(doc)
        if data.get("_id") is not None:
            data["_id"] = str(data["_id"])
        return AssetUniverseVersion(**data)
