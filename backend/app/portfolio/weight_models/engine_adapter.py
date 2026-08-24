# -*- coding: utf-8 -*-
"""组合权重模型的引擎适配器：PortfolioWeightModel → BaseStrategyModel.

将组合层权重模型（fixed / risk_budget / quadrant）包装为统一引擎可消费的
allocator，使组合层以「第二段引擎运行」落地：各子策略 NAV 折算的合成资产
（见 app.backtesting.synthetic_feed）作为标的，经 runner.run_unified 由同一
个 BacktestEngine 逐日撮合。

语义保留（与 composite_engine 对齐，见双跑比对报告）：
- 周期驱动再平衡：rebalance_freq + execution_delay；调度声明携带完整行情
  日历作为 signal_calendar，「信号日 + delay 计数得生效日、生效日前一个
  交易日收盘成交」，等价 composite_engine 的 eff_weights.shift(exec_delay)。
- 事件驱动再平衡：象限等信号值变化日经 ExecutionSchedule.event_dates 声明，
  T+N 经同一延迟机制生效（四象限 signal_driven 模式 T+2）。
- weight_drift=False（四象限 monthly 模式月内不漂移）：每日结算钩子将持仓
  无成本复位到最近目标权重，等价周期内权重恒定的收益口径。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from app.allocation.models.base import BaseStrategyModel
from app.backtesting.types import Position
from app.portfolio.weight_models.base import PortfolioWeightModel


class PortfolioWeightAllocator(BaseStrategyModel):
    """组合权重模型 → 引擎 allocator 适配器.

    allocate() 收到的 prices 各列即子策略的合成资产价格（与 NAV 收益率
    同构），直接作为 sub_navs 传给权重模型的 compute_weights()。
    """

    def __init__(
        self,
        weight_model: PortfolioWeightModel,
        sub_keys: List[str],
        prices_matrix: pd.DataFrame,
        rebalance_freq: str = "monthly",
        execution_delay: int = 1,
        event_signal: Optional[pd.Series] = None,
        weight_drift: bool = True,
        initial_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Args:
            weight_model: 组合层权重模型实例（fixed / risk_budget / quadrant）
            sub_keys: 子策略标识列表（与合成资产价格矩阵列一致）
            prices_matrix: 合成资产价格全矩阵（index=组合日历），供每日结算
                复位取价与调度日历声明使用
            rebalance_freq: 周期驱动调仓频率（事件驱动模式下忽略）
            execution_delay: 信号日到执行日的交易日延迟（T+N）
            event_signal: 事件驱动信号序列（如四象限象限序列）；非 None 时
                信号值变化日触发再平衡（对齐 composite_engine rebalance_signal）
            weight_drift: 周期内权重是否自然漂移；False 时每日结算无成本复位
            initial_weights: 期初目标权重（首日建仓后供结算复位使用）
        """
        self._model = weight_model
        self._sub_keys = list(sub_keys)
        self._prices_matrix = prices_matrix
        self._calendar = [pd.Timestamp(d) for d in prices_matrix.index]
        self._rebalance_freq = rebalance_freq
        self._execution_delay = int(execution_delay)
        self._weight_drift = bool(weight_drift)
        self._last_weights: Optional[Dict[str, float]] = (
            {k: float(v) for k, v in initial_weights.items()} if initial_weights else None
        )
        self._event_dates = (
            self._derive_event_dates(event_signal) if event_signal is not None else None
        )

    # ------------------------------------------------------------------
    # BaseStrategyModel 接口
    # ------------------------------------------------------------------

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """以合成资产价格列作为子策略 NAV，调用权重模型计算目标权重."""
        as_of = prices.index[-1]
        sub_navs = {k: prices[k] for k in self._sub_keys if k in prices.columns}
        weights = self._model.compute_weights(sub_navs, as_of)
        out = {k: float(weights.get(k, 0.0)) for k in self._sub_keys}
        self._last_weights = dict(out)
        return pd.Series(out)

    def get_execution_schedule(self) -> dict:
        """调度声明：事件驱动用 event_dates，周期驱动用 rebalance_freq.

        execution_delay > 0 时声明完整行情日历为 signal_calendar：
        「信号日 + delay」在日历上计数为新权重生效日，成交日 = 生效日前
        最后一个交易日（收盘成交、生效日起承接全日收益），与
        composite_engine 的 eff_weights.shift(exec_delay) 口径一致。
        """
        sched: dict = {"execution_delay": self._execution_delay}
        if self._event_dates:
            # event_dates 声明后 rebalance_freq 周期识别失效（见 ScheduleResolver）
            sched["rebalance_freq"] = "daily"
            sched["event_dates"] = list(self._event_dates)
        else:
            sched["rebalance_freq"] = self._rebalance_freq
        if self._execution_delay > 0 and self._calendar:
            sched["signal_calendar"] = list(self._calendar)
        return sched

    def on_daily_settle(self, time, position, total_value, bar_extra=None):
        """weight_drift=False：每日收盘后无成本复位到最近目标权重.

        引擎先估值记录快照、再调用本钩子；复位后的持仓承接次日收益，
        等价 composite_engine 周期内权重恒定（不随子策略收益漂移）口径。
        """
        if self._weight_drift or not position.quantity:
            return None
        if not self._last_weights or self._prices_matrix is None:
            return None
        ts = pd.Timestamp(time)
        if ts not in self._prices_matrix.index:
            return None
        row = self._prices_matrix.loc[ts]
        quantity: Dict[str, float] = {}
        invested = 0.0
        for key, w in self._last_weights.items():
            price = row.get(key)
            if price is None or pd.isna(price) or price <= 0:
                continue
            qty = float(w) * float(total_value) / float(price)
            quantity[key] = qty
            invested += qty * float(price)
        return Position(quantity=quantity, cash=float(total_value) - invested), float(total_value)

    # ------------------------------------------------------------------
    # 参数 Schema（Pipeline 能力声明读取）
    # ------------------------------------------------------------------

    @classmethod
    def get_param_schema(cls):
        """返回适配器的 Schema 声明（无内部杠杆、无权重上限）."""
        return {
            "weight_model_type": "portfolio_weight",
            "display_name": "组合权重模型适配器",
            "description": "将组合层权重模型包装为统一引擎 allocator",
            "params": [],
        }

    # ------------------------------------------------------------------
    # 事件信号日推导（私有）
    # ------------------------------------------------------------------

    def _derive_event_dates(self, signal: pd.Series) -> Optional[List[pd.Timestamp]]:
        """从事件信号序列推导触发日（口径与 composite_engine 完全一致）.

        信号 reindex 到组合日历后 ffill，值发生变化的日期触发再平衡；
        首日若信号有效也视为触发点，但**排除在调度声明之外**：首日事件
        已由 config.initial_weights 期初建仓承载（composite_runner 在
        rebal_day0 时取同一权重模型的首日目标权重），若重复声明会使
        引擎在第二交易日再做一次同信号调仓，而旧路径 shift(delay) 下
        首日事件只产生一份生效权重。
        """
        if self._calendar is None or len(self._calendar) == 0:
            return None
        dates = pd.DatetimeIndex(self._calendar)
        sig = signal.reindex(dates).ffill()
        if sig.empty or sig.isna().all():
            return None
        changed = sig != sig.shift(1)
        changed.iloc[0] = False  # 首日事件由期初建仓承载，不重复声明
        return [pd.Timestamp(d) for d, flag in zip(dates, changed) if bool(flag)]
