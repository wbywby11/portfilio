# -*- coding: utf-8 -*-
"""策略档案服务 —— 按 manifest_key 幂等 upsert，保留人工字段.

幂等口径：
    - 身份键是 ``manifest_key``（= STRATEGY_MANIFEST 的键），不是 ``name``、
      不是 ``class_path``；
    - 已存在的文档**只更新采集侧字段**（name/description/class_path/
      strategy_form/pillar/aliases/component_set_declared/data_contract_snapshot/
      panel_datasets_snapshot/pending_scope），``strategy_id`` 与人工字段
      （``trial_count`` / ``owner`` / ``tags`` / ``lifecycle_stage``）不动；
    - 唯一性由索引兜底（4 个唯一索引在 app/config/index_specs.py 声明），
      本服务不做「先查后插」的并发竞争式判重。

索引库键口径：
    ``strategy_registry`` 的 ``(pillar, lifecycle_stage)`` 复合索引与
    ``tags`` 多键索引由启动引导建，本服务只负责保证查询走这些键。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config.collections import COL_STRATEGY_REGISTRY
from app.config.database import Database
from app.models.strategy_registry import DEFAULT_LIFECYCLE_STAGE, StrategyRegistryEntry

logger = logging.getLogger(__name__)

__all__ = ["StrategyRegistryService"]

# 采集器负责维护的字段：upsert 时整块覆盖
_COLLECTOR_FIELDS = (
    "name",
    "description",
    "class_path",
    "strategy_form",
    "pillar",
    "signal_family",
    "aliases",
    "component_set_declared",
    "pending_scope",
    "data_contract_snapshot",
    "panel_datasets_snapshot",
)

# 人工维护字段与默认值：仅在新插入时写入，已存在时绝不覆盖
_MANUAL_DEFAULTS: Dict[str, Any] = {
    "trial_count": 0,
    "owner": None,
    "tags": [],
    "lifecycle_stage": DEFAULT_LIFECYCLE_STAGE,
}


class StrategyRegistryService:
    """策略档案读写"""

    @property
    def collection(self):
        return Database.get_database()[COL_STRATEGY_REGISTRY]

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    async def upsert_entry(
        self,
        manifest_key: str,
        strategy_id: str,
        payload: Dict[str, Any],
    ) -> bool:
        """按 ``manifest_key`` upsert 一条档案.

        Args:
            manifest_key: STRATEGY_MANIFEST 的键。
            strategy_id: 新插入时使用的 UUID；已存在则忽略（身份不可变）。
            payload: 采集侧字段（``_COLLECTOR_FIELDS`` 子集）。

        Returns:
            是否发生写入（新增或更新）。失败只记 warning 并返回 False。
        """
        now = datetime.now()
        set_fields = {
            k: v for k, v in payload.items() if k in _COLLECTOR_FIELDS
        }
        set_fields["updated_at"] = now
        set_on_insert: Dict[str, Any] = {
            "strategy_id": strategy_id,
            "manifest_key": manifest_key,
            "component_set_resolved": {},
            "parameter_search_space": {},
            "created_at": now,
            **_MANUAL_DEFAULTS,
        }
        try:
            await self.collection.update_one(
                {"manifest_key": manifest_key},
                {"$set": set_fields, "$setOnInsert": set_on_insert},
                upsert=True,
            )
            return True
        except Exception as exc:  # 唯一索引冲突/库抖动只 warn，不中断启动
            logger.warning(
                "[strategy_registry] upsert 失败 manifest_key=%s: %s", manifest_key, exc
            )
            return False

    async def set_lifecycle_stage(self, strategy_id: str, stage: str) -> bool:
        """更新研发成熟度（人工/迁移脚本入口，upsert 不会覆盖）."""
        result = await self.collection.update_one(
            {"strategy_id": strategy_id},
            {"$set": {"lifecycle_stage": stage, "updated_at": datetime.now()}},
        )
        return result.matched_count > 0

    async def increment_trial_count(self, strategy_id: str, count: int) -> None:
        """写回去重后的试错计数（绝对值覆盖，避免累加漂移）."""
        await self.collection.update_one(
            {"strategy_id": strategy_id},
            {"$set": {"trial_count": int(count), "updated_at": datetime.now()}},
        )

    async def set_parameter_search_space(
        self, strategy_id: str, space: Dict[str, List[Any]]
    ) -> None:
        await self.collection.update_one(
            {"strategy_id": strategy_id},
            {"$set": {"parameter_search_space": space, "updated_at": datetime.now()}},
        )

    async def refresh_trial_count(self, strategy_id: str) -> Optional[int]:
        """按 ``param_hash`` 去重统计回测次数并写回（同参数不同区间算 1 次）.

        口径：同一模型同一参数组合在不同起止日期跑多次，只算一次试错；
        参数改一版就算第二次。分组依据是 ``backtest_records.param_hash``
        （S10 写入），没有该字段的历史记录不参与计数。

        **排除监控批次**：``run_kind=monitor`` 的记录是日常监控跑批产物，
        与参数试错无关；不排除的话每日监控会把 trial_count 抬高到失真。
        存量记录无 run_kind 字段，用 ``$ne`` 同时命中缺失与显式 backtest。

        Returns:
            去重后的次数；参数缺失或查询失败返回 None（不抛）。
        """
        if not strategy_id:
            return None
        from app.config.collections import COL_BACKTEST_RECORDS
        from app.models.strategy_model import RunKind

        pipeline = [
            {"$match": {
                "strategy_id": strategy_id,
                "param_hash": {"$type": "string"},
                "run_kind": {"$ne": RunKind.MONITOR.value},
            }},
            {"$group": {"_id": "$param_hash"}},
            {"$count": "n"},
        ]
        try:
            rows = await (
                Database.get_database()[COL_BACKTEST_RECORDS]
                .aggregate(pipeline, allowDiskUse=True)
                .to_list(length=1)
            )
            count = int(rows[0]["n"]) if rows else 0
            await self.increment_trial_count(strategy_id, count)
            return count
        except Exception as exc:  # noqa: BLE001 —— 计数失败不得影响回测保存
            logger.warning(
                "[strategy_registry] 试错计数刷新失败 strategy_id=%s: %s",
                strategy_id, exc,
            )
            return None

    async def refresh_parameter_search_space(
        self, strategy_id: str, template_code: Optional[str]
    ) -> Optional[Dict[str, List[Any]]]:
        """从 ``get_param_schema()`` 重新推导搜索空间，变化时才回写.

        网格随策略类静态声明固定；与库内已有值相等时跳过写入，
        避免每次回测都产生一次无意义的 update。
        """
        if not strategy_id or not template_code:
            return None
        try:
            from app.services.backtest_analysis_service import get_param_grid

            space = get_param_grid(template_code)
            entry = await self.get_by_strategy_id(strategy_id)
            if entry is None:
                return None
            if dict(entry.parameter_search_space or {}) == dict(space):
                return space
            await self.set_parameter_search_space(strategy_id, space)
            return space
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[strategy_registry] 搜索空间刷新失败 strategy_id=%s code=%s: %s",
                strategy_id, template_code, exc,
            )
            return None

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    async def get_by_manifest_key(
        self, manifest_key: str
    ) -> Optional[StrategyRegistryEntry]:
        doc = await self.collection.find_one({"manifest_key": manifest_key})
        return self._to_model(doc)

    async def get_by_strategy_id(self, strategy_id: str) -> Optional[StrategyRegistryEntry]:
        doc = await self.collection.find_one({"strategy_id": strategy_id})
        return self._to_model(doc)

    async def get_by_template_code(
        self, template_code: str
    ) -> Optional[StrategyRegistryEntry]:
        """按策略码查档案（先直接命中 manifest_key，再走别名归一）."""
        doc = await self.collection.find_one({"manifest_key": template_code})
        if doc is None:
            from app.allocation.strategy_manifest import canonical_code

            code = canonical_code(template_code)
            if code != template_code:
                doc = await self.collection.find_one({"manifest_key": code})
        return self._to_model(doc)

    async def list_entries(
        self,
        pillar: Optional[str] = None,
        family_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        lifecycle_stage: Optional[str] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> List[StrategyRegistryEntry]:
        query: Dict[str, Any] = {}
        if pillar:
            query["pillar"] = pillar
        if family_id:
            query["family_id"] = family_id
        if lifecycle_stage:
            query["lifecycle_stage"] = lifecycle_stage
        if tags:
            query["tags"] = {"$in": list(tags)}
        cursor = (
            self.collection.find(query)
            .sort("manifest_key", 1)
            .skip(max(0, int(skip)))
            .limit(max(1, int(limit)))
        )
        return [self._to_model(doc) async for doc in cursor if doc]

    async def count(self) -> int:
        return int(await self.collection.count_documents({}))

    @staticmethod
    def _to_model(doc: Optional[Dict[str, Any]]) -> Optional[StrategyRegistryEntry]:
        if not doc:
            return None
        data = dict(doc)
        data["_id"] = str(data["_id"])
        return StrategyRegistryEntry(**data)
