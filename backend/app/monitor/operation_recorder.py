# -*- coding: utf-8 -*-
"""
监控服务 Mixin：操作指令记录（monitor_operations）

职责：
1. 运行前预置月度调仓指令（信号日即预展示，T+2 执行日前可见）
2. 逐日推演后落库指令事件（执行/触发/取消/主观执行）
3. 从 event_log 同步历史指令（研究员独立引擎等无步进事件路径）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from app.models.monitor import OperationStatus, OperationType
from app.services.monitor_operation_service import MonitorOperationService


class OperationRecorderMixin:
    """操作指令记录方法群。

    依赖宿主（MonitorService）属性：_is_strategy_model_monitor_id。
    """

    _operation_service: Optional[MonitorOperationService] = None

    @property
    def operation_service(self) -> MonitorOperationService:
        """操作指令服务（懒加载单例）。"""
        if OperationRecorderMixin._operation_service is None:
            OperationRecorderMixin._operation_service = MonitorOperationService()
        return OperationRecorderMixin._operation_service

    def _op_batch_id(self) -> Optional[str]:
        """当前运行批次号（由宿主 MonitorService 的批次上下文提供）。

        ``operation_service`` 是跨 MonitorService 实例共享的**类级单例**，
        因此批次号必须逐调用显式传入，不能挂在服务实例上（否则并发跑批会串批次）。
        """
        getter = getattr(self, "_current_batch_id", None)
        if not callable(getter):
            return None
        try:
            return getter() or None
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 预置与落库
    # ------------------------------------------------------------------

    async def _seed_monthly_operations(
        self,
        monitor_id: str,
        monthly_rebalance_map: Dict[Any, Any],
        reset: bool = False,
    ) -> None:
        """运行前预置月度调仓指令，保证信号日~执行日窗口内可预展示。

        Args:
            monitor_id: 监控实例 ID
            monthly_rebalance_map: {执行日 Timestamp: {'weights': ..., 'calc_date': ...}}
            reset: True 时先删除**当前批次**的自动指令（初始化重跑）；
                旧批次已封存的指令不受影响
        """
        try:
            batch_id = self._op_batch_id()
            strategy_name = await self._operation_strategy_display_name(monitor_id)
            if reset:
                await self.operation_service.delete_by_monitor(
                    monitor_id, batch_id=batch_id
                )
            for exec_ts, info in (monthly_rebalance_map or {}).items():
                calc_date = str(info.get("calc_date") or "")[:10]
                exec_date = str(exec_ts)[:10]
                if not calc_date:
                    continue
                await self.operation_service.upsert_auto_operation(
                    monitor_id=monitor_id,
                    strategy_key=monitor_id,
                    op_type=OperationType.MONTHLY_REBALANCE.value,
                    signal_date=calc_date,
                    execute_date=exec_date,
                    target_weights=info.get("weights") or {},
                    strategy_name=strategy_name,
                    batch_id=batch_id,
                )
        except Exception as e:
            logger.warning(f"预置月度操作指令失败（不影响推演）: {e}")

    async def _record_operation_events(
        self, monitor_id: str, result: Dict[str, Any]
    ) -> None:
        """将单日推演产出的指令事件落库（幂等，失败不阻断推演）。"""
        events = result.get("operation_events") if isinstance(result, dict) else None
        if not events:
            return
        try:
            strategy_name = await self._operation_strategy_display_name(monitor_id)
            for ev in events:
                await self._apply_operation_event(monitor_id, strategy_name, ev)
        except Exception as e:
            logger.warning(f"操作指令落库失败（不影响推演）: {e}")

    async def _apply_operation_event(
        self, monitor_id: str, strategy_name: str, ev: Dict[str, Any]
    ) -> None:
        """分发单条指令事件到对应服务方法（均限定在当前批次）。"""
        kind = ev.get("kind")
        svc = self.operation_service
        batch_id = self._op_batch_id()
        if kind == "monthly_executed":
            await svc.mark_executed(
                monitor_id, monitor_id,
                OperationType.MONTHLY_REBALANCE.value,
                ev["execute_date"], ev.get("prev_weights"),
                batch_id=batch_id,
            )
        elif kind == "vol_executed":
            await svc.mark_executed(
                monitor_id, monitor_id,
                OperationType.VOL_RESET.value,
                ev["execute_date"], ev.get("prev_weights"),
                batch_id=batch_id,
            )
        elif kind == "vol_cancelled":
            await svc.mark_cancelled_by_key(
                monitor_id, monitor_id,
                OperationType.VOL_RESET.value, ev["signal_date"],
                reason=ev.get("reason"), batch_id=batch_id,
            )
        elif kind == "vol_triggered":
            await svc.upsert_auto_operation(
                monitor_id=monitor_id,
                strategy_key=monitor_id,
                op_type=OperationType.VOL_RESET.value,
                signal_date=ev["signal_date"],
                execute_date=ev["execute_date"],
                target_weights=ev.get("target_weights") or {},
                strategy_name=strategy_name,
                suggestion=ev.get("suggestion") or {},
                batch_id=batch_id,
            )
        elif kind == "subjective_executed":
            await svc.mark_override_executed(
                ev.get("override_ref") or "", batch_id=batch_id
            )

    # ------------------------------------------------------------------
    # 从 event_log 同步（研究员独立引擎等路径）
    # ------------------------------------------------------------------

    async def _sync_operations_from_event_log(
        self, monitor_id: str, event_log: List[Dict[str, Any]]
    ) -> None:
        """根据状态事件日志重建自动指令（幂等，仅限当前批次）。

        适用于研究员独立引擎等不经过步进指令事件的路径；
        月度调仓信号日无法从事件还原时，以执行日兼作信号日。
        """
        try:
            batch_id = self._op_batch_id()
            await self.operation_service.delete_by_monitor(
                monitor_id, batch_id=batch_id
            )
            strategy_name = await self._operation_strategy_display_name(monitor_id)
            for ev in event_log or []:
                await self._sync_single_event(monitor_id, strategy_name, ev)
        except Exception as e:
            logger.warning(f"event_log 同步操作指令失败（不影响推演）: {e}")

    async def _sync_single_event(
        self, monitor_id: str, strategy_name: str, ev: Dict[str, Any]
    ) -> None:
        """同步单条事件日志为已执行指令（仅处理自动调仓类事件）。"""
        etype = ev.get("type")
        date = str(ev.get("date") or "")[:10]
        if not date or etype not in ("monthly", "vol_reset"):
            return
        if etype == "vol_reset" and ev.get("stage") == "trigger":
            # 触发明细在下次触发事件中重建，跳过避免残留
            return
        if etype == "vol_reset" and ev.get("stage") not in (None, "execute"):
            return
        op_type = {
            "monthly": OperationType.MONTHLY_REBALANCE.value,
            "vol_reset": OperationType.VOL_RESET.value,
        }[etype]
        # 信号日：规范键为 signal_date，存量事件写的是 calc_date（同值）
        signal_date = (
            str(ev.get("signal_date") or ev.get("calc_date") or "")[:10] or date
        )
        batch_id = self._op_batch_id()
        op_id = await self.operation_service.upsert_auto_operation(
            monitor_id=monitor_id,
            strategy_key=monitor_id,
            op_type=op_type,
            signal_date=signal_date,
            execute_date=date,
            target_weights=ev.get("new_weights") or {},
            strategy_name=strategy_name,
            batch_id=batch_id,
        )
        if op_id:
            await self.operation_service.mark_executed(
                monitor_id, monitor_id, op_type, date, ev.get("old_weights"),
                batch_id=batch_id,
            )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    async def _operation_strategy_display_name(self, monitor_id: str) -> str:
        """获取监控实例对应的策略展示名（策略模型名；其余返回空）。"""
        try:
            if hasattr(self, "_is_strategy_model_monitor_id") and \
                    self._is_strategy_model_monitor_id(monitor_id):
                from app.services.strategy_model_service import StrategyModelService
                model = await StrategyModelService().get_model(monitor_id)
                if model:
                    return getattr(model, "name", "") or ""
        except Exception:
            pass
        return ""
