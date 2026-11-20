# -*- coding: utf-8 -*-
"""策略生命周期状态机与准入（S14）.

两个维度并存**不映射**：
    - ``ModelStatus``（草稿 / 已发布 / 已归档）是**配置冻结状态**，
      由发布/归档动作驱动，已用于入参校验与前端四态筛选；
    - ``lifecycle_stage``（research / shadow / paper / live / retired）是
      **研发成熟度**，由策略库治理动作驱动。
唯一保留的单向蕴含是 ``live ⇒ status == PUBLISHED ∧ live_publish_enabled``；
反向不成立——「已发布」不等于「已实盘」，「实盘开关打开」也不自动等于成熟度 live。

开关：``LIFECYCLE_ENFORCE`` 默认 False。关闭时 ``can_enter`` 恒放行，
本模块只提供能力，不改变任何既有链路行为；打开后：
    - ``live_publish_model`` 只允许 ``paper`` / ``live`` 阶段的模型进入 live；
    - ``_prepare_monitor_run`` 只允许已处于 ``live`` 阶段的模型跑日常监控；
    - 拒绝时抛 ``ValueError``（API 层转 4xx）并写 ``strategy_lifecycle_events``。

写入约束：``lifecycle_stage`` 字段的低层写入只经 ``StrategyRegistryService``，
本服务是它唯一的业务调用方；迁移脚本也走本服务的 ``backfill_stage``。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from app.config.collections import COL_STRATEGY_LIFECYCLE_EVENTS
from app.config.database import Database
from app.models.strategy_model import ModelStatus
from app.models.strategy_registry import DEFAULT_LIFECYCLE_STAGE, LIFECYCLE_STAGES
from app.services.strategy_registry_service import StrategyRegistryService

logger = logging.getLogger(__name__)

__all__ = [
    "LIFECYCLE_ENFORCE",
    "STAGE_TRANSITIONS",
    "STAGE_ACTIONS",
    "StrategyLifecycleService",
]

# 执行开关（默认 False：写全能力但行为不变）
LIFECYCLE_ENFORCE = os.getenv("LIFECYCLE_ENFORCE", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# 显式迁移表：键为当前阶段，值为允许进入的下一阶段（单向，不回退）
STAGE_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "research": ("shadow", "retired"),
    "shadow": ("paper", "retired"),
    "paper": ("live", "retired"),
    "live": ("retired",),
    "retired": (),
}

# 审计动作白名单（S15 的 5 个状态动作 + 阶段推进 + 监控准入）
STAGE_ACTIONS = (
    "publish",
    "republish",
    "unpublish",
    "live_publish",
    "live_unpublish",
    "stage_change",
    "monitor_run",
)


class StrategyLifecycleService:
    """生命周期准入与阶段推进（事件 append-only）"""

    @property
    def events_collection(self):
        return Database.get_database()[COL_STRATEGY_LIFECYCLE_EVENTS]

    # ------------------------------------------------------------------
    # 读 / 判定
    # ------------------------------------------------------------------

    @staticmethod
    def _label(model: Any) -> str:
        return (
            str(getattr(model, "name", None) or getattr(model, "template_code", None) or "")
            or str(getattr(model, "id", None) or "")
            or "未命名策略"
        )

    async def resolve_stage(self, model: Any) -> str:
        """解析模型当前研发阶段：模型字段优先，其次策略档案，最后 research.

        档案读取失败不阻断，回落 ``research``（开启强制时即 fail-closed）。
        """
        stage = str(getattr(model, "lifecycle_stage", "") or "").strip()
        if stage in LIFECYCLE_STAGES:
            return stage
        code = getattr(model, "template_code", None)
        if code:
            try:
                entry = await StrategyRegistryService().get_by_template_code(code)
                if entry and entry.lifecycle_stage in LIFECYCLE_STAGES:
                    return entry.lifecycle_stage
            except Exception as exc:  # noqa: BLE001 —— 读档案失败按默认阶段处理
                logger.warning("[lifecycle] 阶段解析失败 template_code=%s: %s", code, exc)
        return DEFAULT_LIFECYCLE_STAGE

    async def can_enter(
        self,
        stage: str,
        model: Any,
        *,
        require_current: bool = False,
    ) -> Tuple[bool, str]:
        """模型能否进入（或停留在）``stage``.

        Args:
            stage: 目标阶段（LIFECYCLE_STAGES 之一）
            model: 策略模型（提供 template_code / status / live_publish_enabled）
            require_current: True 表示要求**已经**处于该阶段（运行态准入），
                False 表示允许按迁移表推进到该阶段（动作准入）

        Returns:
            ``(allowed, reason)``；``reason`` 在拒绝时包含当前阶段与允许路径。
        """
        if not LIFECYCLE_ENFORCE:
            return True, ""
        if stage not in LIFECYCLE_STAGES:
            return False, f"未知生命周期阶段「{stage}」，合法值：{'/'.join(LIFECYCLE_STAGES)}"

        current = await self.resolve_stage(model)
        label = self._label(model)
        if current == stage:
            if stage == "live":
                ok, why = self._check_live_invariant(model, label)
                if not ok:
                    return False, why
            return True, ""

        if require_current:
            return False, (
                f"策略「{label}」当前研发阶段为「{current}」，未达到「{stage}」；"
                f"请先在策略库推进研发阶段。研发成熟度（lifecycle_stage）与发布状态（status）"
                f"是两个维度，发布/实盘开关不会自动推进成熟度。"
            )

        allowed_next = STAGE_TRANSITIONS.get(current, ())
        if stage not in allowed_next:
            path = "、".join(allowed_next) if allowed_next else "（终态，不可再进入其他阶段）"
            return False, (
                f"策略「{label}」当前研发阶段为「{current}」，不能进入「{stage}」；"
                f"允许的下一阶段：{path}。研发成熟度（lifecycle_stage）与发布状态（status）"
                f"是两个维度，发布状态不等于研发成熟度。"
            )
        if stage == "live":
            # 动作准入只要求「已发布」；live_publish 动作本身才会开启 live_publish_enabled，
            # 因此这里不能校验开关（否则首次实盘发布必然被自己挡住）。
            ok, why = self._check_published(model, label)
            if not ok:
                return False, why
        return True, ""

    @staticmethod
    def _check_published(model: Any, label: str) -> Tuple[bool, str]:
        status = getattr(model, "status", None)
        published = status == ModelStatus.PUBLISHED or str(status) == ModelStatus.PUBLISHED.value
        if not published:
            return False, (
                f"策略「{label}」状态不是「{ModelStatus.PUBLISHED.value}」，不能进入 live 阶段；"
                f"live 阶段要求状态为已发布。"
            )
        return True, ""

    @staticmethod
    def _check_live_invariant(model: Any, label: str) -> Tuple[bool, str]:
        """单向蕴含：``live ⇒ status == PUBLISHED ∧ live_publish_enabled``."""
        ok, why = StrategyLifecycleService._check_published(model, label)
        if not ok:
            return False, why.replace("不能进入 live 阶段", "研发阶段为「live」")
        if not bool(getattr(model, "live_publish_enabled", False)):
            return False, (
                f"策略「{label}」研发阶段为「live」但实盘开关未开启；"
                f"live 阶段要求已实盘发布。"
            )
        return True, ""

    async def enforce(
        self,
        stage: str,
        model: Any,
        *,
        action: str,
        operator: Optional[str] = None,
        source: Optional[str] = None,
        require_current: bool = False,
    ) -> None:
        """准入判定：拒绝时写 rejected 事件并抛 ``ValueError``.

        开关关闭时零副作用直接返回（不查库、不写事件）。
        """
        if not LIFECYCLE_ENFORCE:
            return
        allowed, reason = await self.can_enter(
            stage, model, require_current=require_current
        )
        current = await self.resolve_stage(model)
        if allowed:
            # 允许不落事件：S15 只为 5 个状态动作各写 1 条，日常监控放行不刷事件。
            return

        await self.append_event(
            model=model,
            action=action,
            from_stage=current,
            to_stage=stage,
            operator=operator,
            source=source,
            status="rejected",
            reason=reason,
        )
        raise ValueError(f"[lifecycle] {reason}")

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    async def append_event(
        self,
        *,
        model: Any = None,
        model_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        version_id: Optional[str] = None,
        action: str = "stage_change",
        from_stage: Optional[str] = None,
        to_stage: Optional[str] = None,
        operator: Optional[str] = None,
        source: Optional[str] = None,
        snapshot_ref: Optional[str] = None,
        status: str = "applied",
        reason: Optional[str] = None,
    ) -> bool:
        """写一条生命周期事件；失败只 warn 并返回 False（不拖垮主流程）.

        ``model_id`` 可直接传入（审计转发场景只有 ID，没有模型对象）。
        """
        try:
            if strategy_id is None and model is not None:
                strategy_id = await self._resolve_strategy_id(model)
            resolved_model_id = model_id
            if resolved_model_id is None and model is not None:
                resolved_model_id = str(
                    getattr(model, "id", None)
                    or getattr(model, "model_id", None)
                    or ""
                ) or None
            doc: Dict[str, Any] = {
                "strategy_id": strategy_id,
                "model_id": resolved_model_id,
                "version_id": version_id,
                "action": action if action in STAGE_ACTIONS else "stage_change",
                "from_stage": from_stage,
                "to_stage": to_stage,
                "operator": operator,
                "source": str(source or "unknown"),
                # snapshot_ref 只存 version_id 引用，绝不复制快照正文（R1 同口径）
                "snapshot_ref": snapshot_ref or version_id,
                "status": status,
                "reason": reason,
                "created_at": datetime.now(),
            }
            payload = {k: v for k, v in doc.items() if v is not None}
            await self.events_collection.insert_one(payload)
            return True
        except Exception as exc:  # noqa: BLE001 —— 治理事件不得影响主流程
            logger.warning("[lifecycle] 事件写入失败 action=%s: %s", action, exc)
            return False

    async def _resolve_strategy_id(self, model: Any) -> Optional[str]:
        sid = str(getattr(model, "strategy_id", "") or "").strip()
        if sid:
            return sid
        code = getattr(model, "template_code", None)
        if not code:
            return None
        try:
            entry = await StrategyRegistryService().get_by_template_code(code)
            return entry.strategy_id if entry else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[lifecycle] strategy_id 解析失败 template_code=%s: %s", code, exc)
            return None

    async def set_stage(
        self,
        strategy_id: str,
        stage: str,
        *,
        model_id: Optional[str] = None,
        operator: Optional[str] = None,
        source: str = "manual",
        action: str = "stage_change",
        version_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """按迁移表推进阶段；非法迁移写 rejected 事件并返回 False."""
        if stage not in LIFECYCLE_STAGES:
            return False
        entry = await StrategyRegistryService().get_by_strategy_id(strategy_id)
        if entry is None:
            return False
        current = entry.lifecycle_stage
        if current == stage:
            return True
        allowed_next = STAGE_TRANSITIONS.get(current, ())
        if stage not in allowed_next:
            await self.append_event(
                strategy_id=strategy_id,
                model=None,
                version_id=version_id,
                action=action,
                from_stage=current,
                to_stage=stage,
                operator=operator,
                source=source,
                status="rejected",
                reason=reason
                or (
                    f"不允许从「{current}」直接进入「{stage}」；"
                    f"允许的下一阶段：{'、'.join(allowed_next) or '（终态）'}"
                ),
            )
            return False
        ok = await StrategyRegistryService().set_lifecycle_stage(strategy_id, stage)
        if ok:
            await self.append_event(
                strategy_id=strategy_id,
                model=None,
                version_id=version_id,
                action=action,
                from_stage=current,
                to_stage=stage,
                operator=operator,
                source=source,
                status="applied",
                reason=reason,
            )
        if model_id:
            logger.info(
                "[lifecycle] 阶段推进 model_id=%s %s -> %s operator=%s",
                model_id, current, stage, operator,
            )
        return ok

    async def backfill_stage(
        self,
        strategy_id: str,
        stage: str,
        *,
        source: str = "migration",
        reason: Optional[str] = None,
    ) -> bool:
        """存量回填：按当前业务状态直接落阶段，**跳过迁移表**.

        仅供 ``scripts/migrate_lifecycle_stage.py`` 使用：把「先有实盘发布、
        后有 lifecycle_stage 字段」的历史模型映射到其在迁移时刻实际所处的阶段。
        正常推进一律走 ``set_stage``。
        """
        if stage not in LIFECYCLE_STAGES:
            return False
        entry = await StrategyRegistryService().get_by_strategy_id(strategy_id)
        if entry is None:
            return False
        current = entry.lifecycle_stage
        if current == stage:
            return True
        ok = await StrategyRegistryService().set_lifecycle_stage(strategy_id, stage)
        if ok:
            await self.append_event(
                strategy_id=strategy_id,
                action="stage_change",
                from_stage=current,
                to_stage=stage,
                source=source,
                status="applied",
                reason=reason or "存量回填（跳过迁移表）",
            )
        return ok
