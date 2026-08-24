"""BacktestEngine：计算引擎的逐日推进主循环（计算内核层，模式无关）.

按价格日历逐日推进：信号时点（execution_bar）→ 调仓调度（ScheduleResolver）
→ 三层权重编排（CompositionPipeline / IStrategy）→ 撮合（ExecutionEngine）
→ 风控约束（RiskManager）→ NAV 累计。全量回测、监控推演、模拟交易等
计算模式均经此主循环，模式差异（费率、区间）由 BacktestConfig / 调用参数表达，
不在策略逻辑内分叉。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple

import pandas as pd
import numpy as np

from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.strategy_api import IStrategy
from app.backtesting.risk import RiskManager
from app.backtesting.execution import ExecutionEngine, ExecutionResult
from app.backtesting.types import Position, PortfolioSnapshot, Bar, Trade
from app.backtesting.schedule import (
    ExecutionSchedule,
    ScheduleResolver,
    resolve_execution_schedule,
)

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """回测结果聚合对象."""

    snapshots: List[PortfolioSnapshot]
    trades: List[Trade]
    config: BacktestConfig


class BacktestEngine:
    """回测引擎.

    负责按时间推进，协调数据、策略、风控和执行模块的调用。
    """

    def __init__(
        self,
        config: BacktestConfig,
        data_feed: DataFeed,
        strategy: IStrategy,
        risk_manager: RiskManager,
        execution_engine: ExecutionEngine,
    ) -> None:
        self._config = config
        self._data_feed = data_feed
        self._strategy = strategy
        self._risk = risk_manager
        self._exec = execution_engine

        # 执行调度：从策略声明读取调度规则，构建 ScheduleResolver
        # （解析口径与 Step1 generate_targets 同源，见 schedule.resolve_execution_schedule）
        self._schedule_resolver: Optional[ScheduleResolver] = None
        self._execute_to_signal: Dict[pd.Timestamp, pd.Timestamp] = {}
        schedule = resolve_execution_schedule(self._strategy, config)
        trade_dates = list(data_feed.prices.index)
        self._schedule_resolver = ScheduleResolver(schedule, trade_dates)

        # 行情日历注入：声明 set_price_calendar 的策略可获得完整价格日历，
        # 用于信号时序的精确判定（如月末锁定选择器判断自定义信号日历上
        # 计数的生效日是否为窗口末行的下一价格交易日）
        if hasattr(self._strategy, "set_price_calendar"):
            try:
                self._strategy.set_price_calendar(trade_dates)
            except Exception as exc:
                logger.warning("[引擎] set_price_calendar 注入失败，策略退回近似时序判定: %s", exc)

        # 缺日保真：策略声明 preserve_price_gaps 时，信号计算用保留缺日 NaN 的
        # strategy_prices（对齐原型品种缺日→窗口 NaN 传播口径）；逐日估值仍用 prices。
        self._preserve_price_gaps = bool(
            self._get_strategy_data_feed_options().get("preserve_price_gaps", False)
        )

    def _get_strategy_data_feed_options(self) -> dict:
        """从策略实例读取数据源选项声明（如 preserve_price_gaps）."""
        strategy = self._strategy
        if hasattr(strategy, '_base_strategy'):
            strategy = strategy._base_strategy
        if hasattr(strategy, 'get_data_feed_options'):
            try:
                return dict(strategy.get_data_feed_options() or {})
            except Exception as exc:  # 声明异常不应阻断回测，回退默认行为
                logger.warning("[引擎] get_data_feed_options 调用失败，使用默认数据源选项: %s", exc)
        return {}

    def _build_schedule_maps(self, start: pd.Timestamp, end: pd.Timestamp) -> None:
        """构建执行日→信号日映射表（在 run() 开始时调用）."""
        if self._schedule_resolver:
            self._execute_to_signal = self._schedule_resolver.build_execute_to_signal_map(start, end)
        else:
            self._execute_to_signal = {}

    def _is_execute_day(self, time: pd.Timestamp) -> bool:
        """判断当前时点是否为某个信号的执行日."""
        time_norm = pd.Timestamp(time.date()) if hasattr(time, 'date') else time.normalize()
        return time_norm in self._execute_to_signal

    def _compute_total_value(self, position: Position, bar: Bar) -> float:
        """根据当前持仓和最新价格计算组合总市值."""
        # 防御性检查：确保 bar.close 是字典
        if not isinstance(bar.close, dict):
            raise TypeError(
                f"bar.close 必须是字典类型，实际类型为 {type(bar.close)}。"
                f"可能是数据格式问题，请检查数据源。"
            )
        return position.cash + sum(
            qty * bar.close.get(code, 0.0)
            for code, qty in position.quantity.items()
        )

    def _compute_traditional_value_and_weights(
        self, position: Position, bar: Bar
    ) -> Tuple[float, pd.Series]:
        """传统市值模式：计算组合总市值与当前权重（run/run_step 公共逻辑）."""
        total_value = self._compute_total_value(position, bar)
        current_weights = pd.Series({
            code: (qty * bar.close.get(code, 0.0) / total_value) if total_value > 0 else 0.0
            for code, qty in position.quantity.items()
        })
        return total_value, current_weights

    def _recalc_post_rebalance_vol(
        self,
        time: pd.Timestamp,
        bar: Bar,
        weights: Dict[str, float],
        portfolio_vol: float | None,
        monitoring_metrics: Dict[str, Any],
    ) -> Tuple[float | None, Dict[str, Any]]:
        """调仓日用调仓后权重重算波动率，使监控图展示正确的「调仓后预期波动率」（run/run_step 公共逻辑）."""
        if not weights:
            return portfolio_vol, monitoring_metrics
        try:
            hist = self._data_feed.get_history_window(time)
            if not hist.empty:
                w_new = pd.Series({k: float(v or 0) for k, v in weights.items()})
                if w_new.abs().sum() > 0:
                    metrics_post = self._strategy.compute_monitoring_metrics(
                        current_weights=w_new, history_prices=hist,
                    )
                    vol_post = metrics_post.get("portfolio_volatility")
                    if vol_post is not None:
                        portfolio_vol = vol_post
                        monitoring_metrics["portfolio_volatility"] = vol_post
        except Exception as exc:
            logger.warning(
                "[波动率监控] %s 调仓后波动率重算失败，保留调仓前取值：%s",
                pd.Timestamp(time).strftime("%Y-%m-%d"), exc,
            )
        return portfolio_vol, monitoring_metrics

    def _build_snapshot(
        self,
        time: pd.Timestamp,
        total_value: float,
        cash_value: float,
        holdings_value: float,
        weights: Dict[str, float],
        is_rebalance_day: bool,
        rebalance_type: str | None,
        rebalance_reason: str | None,
        portfolio_vol: float | None,
        monitoring_metrics: Dict[str, Any],
        signal_date: pd.Timestamp | None = None,
        execution_delay_days: int = 0,
    ) -> PortfolioSnapshot:
        """构建每日组合快照（run/run_step 公共逻辑）."""
        return PortfolioSnapshot(
            time=time,
            total_value=total_value,
            cash=cash_value,
            holdings_value=holdings_value,
            weights=weights,
            is_rebalance_day=is_rebalance_day,
            rebalance_type=rebalance_type if is_rebalance_day else None,
            portfolio_volatility=portfolio_vol,
            monitoring_metrics=monitoring_metrics,
            rebalance_reason=rebalance_reason if is_rebalance_day else None,
            signal_date=signal_date if is_rebalance_day else None,
            execution_delay_days=execution_delay_days if is_rebalance_day else 0,
        )

    def _run_daily_settle(
        self,
        time: pd.Timestamp,
        position: Position,
        total_value: float,
        bar_extra=None,
    ) -> tuple[Position, float]:
        """每日结算钩子，在快照构建后调用。

        若策略模型实现了 on_daily_settle(time, position, total_value, bar_extra) 方法，
        则调用它执行每日结算逻辑（如闲置资金利息、GC001 回购利息等）。
        返回更新后的 position 和 total_value。
        未实现该方法的策略自动跳过，零侵入。
        """
        settle_fn = getattr(self._strategy, "on_daily_settle", None)
        if settle_fn is None or not callable(settle_fn):
            return position, total_value
        try:
            result = settle_fn(time, position, total_value, bar_extra=bar_extra)
            if result is None:
                return position, total_value
            # on_daily_settle 可返回 (new_position, new_total_value) 或仅 new_position
            if isinstance(result, tuple) and len(result) == 2:
                return result[0], result[1]
            if isinstance(result, Position):
                new_val = result.cash + sum(
                    qty * (total_value / max(total_value, 1e-12))
                    for qty in result.quantity.values()
                )
                return result, result.cash + (total_value - position.cash)
        except Exception as e:
            logger.warning(f"on_daily_settle 执行失败: {e}")
        return position, total_value

    def _execute_rebalance_traditional(
        self,
        bar: Bar,
        position: Position,
        target_signal,
        trades_all: List[Trade],
    ) -> tuple[float, Position]:
        """传统市值模式下的调仓执行."""
        exec_result: ExecutionResult = self._exec.rebalance_to_target(
            bar=bar,
            current_position=position,
            target_signal=target_signal,
        )
        position = exec_result.position
        trades_all.extend(exec_result.trades)
        total_value = self._compute_total_value(position, bar)
        return total_value, position

    def _update_nav_and_weights_traditional_mode(
        self,
        bar: Bar,
        position: Position,
        total_value: float,
    ):
        """传统市值模式下的净值与权重更新."""
        holdings_value = total_value - position.cash
        cash_value = position.cash
        weights = {
            code: (qty * bar.close.get(code, 0.0) / total_value) if total_value > 0 else 0.0
            for code, qty in position.quantity.items()
        }
        return total_value, holdings_value, cash_value, weights

    def _resolve_snapshot_weight_source(self) -> str:
        """读取策略声明的快照权重口径（actual / target）.

        杠杆类策略的目标权重和可 >1，按市值归一化的实际权重会抹平杠杆，
        因此需用目标权重展示。引擎只读策略能力声明，不得按策略类名分支。
        """
        strategy = getattr(self._strategy, "_base_strategy", self._strategy)
        getter = getattr(strategy, "get_capabilities", None)
        if not callable(getter):
            return "actual"
        try:
            capabilities = getter() or {}
        except Exception as exc:
            logger.warning("[能力声明] 读取失败，快照回退到实际权重：%s", exc)
            return "actual"
        return str(capabilities.get("snapshot_weight_source") or "actual")

    # ------------------------------------------------------------------
    # return-level 波动率定标（对齐 GMSI 2.0 原型 raw_ret × leverage.shift(1)）
    # ------------------------------------------------------------------

    def _get_return_targeting_params(self) -> Optional[Dict[str, Any]]:
        """读取策略声明的 return-level 波动率定标参数；未声明时返回 None.

        触发条件：策略参数 vol_targeting_enabled 为真（由分配器 schema 声明、
        前端策略建模界面配置，随模型 parameters 持久化）。定标是策略自身
        收益流计算的一部分（GMSI 2.0 口径 raw_ret × leverage.shift(1)），
        不经过控制器；引擎基于「未缩放组合收益序列」逐日重算 leverage。
        """
        sp = getattr(self._strategy, "_strategy_params", None)
        if not isinstance(sp, dict):
            # 兼容包装策略（如研究员策略适配器）：从内层 Pipeline 读取
            inner = getattr(self._strategy, "_base_strategy", None)
            sp = getattr(inner, "_strategy_params", None) if inner is not None else None
        if not isinstance(sp, dict):
            return None
        enabled = sp.get("vol_targeting_enabled", False)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
        if not enabled:
            return None
        return {
            "target_vol": float(sp.get("vol_targeting_target", 0.03)),
            "vc_short": int(sp.get("vol_targeting_short_window", 20)),
            "vc_long": int(sp.get("vol_targeting_long_window", 60)),
            "annualization_factor": int(sp.get("vol_targeting_annualization", 260)),
            "vol_method": str(sp.get("vol_targeting_method", "rolling")).lower(),
            "leverage_min": float(sp.get("vol_targeting_leverage_min", 0.1)),
            "leverage_max": float(sp.get("vol_targeting_leverage_max", 5.0)),
        }

    @staticmethod
    def _compute_return_level_leverage(raw_returns: List[float], p: Dict[str, Any]) -> float:
        """从未缩放收益序列计算 leverage = clip(target/vol_est, lb, ub).

        vol_est = (短期 + 长期) / 2，口径与 DualWindowVolMonitor 一致：
        ewma 用 span=窗口、min_periods=max(窗口一半, 下限)；历史不足时返回 1.0。
        """
        n = len(raw_returns)
        if n < 10:
            return 1.0
        s = pd.Series(raw_returns)
        af = p["annualization_factor"]
        if p["vol_method"] == "ewma":
            vol_short = s.ewm(span=p["vc_short"], min_periods=max(5, p["vc_short"] // 2)).std().iloc[-1]
            vol_long = s.ewm(span=p["vc_long"], min_periods=max(10, p["vc_long"] // 2)).std().iloc[-1]
        else:
            vol_short = s.rolling(p["vc_short"], min_periods=max(5, p["vc_short"] // 2)).std().iloc[-1]
            vol_long = s.rolling(p["vc_long"], min_periods=max(10, p["vc_long"] // 2)).std().iloc[-1]
        if pd.isna(vol_short) or pd.isna(vol_long):
            return 1.0
        vol_est = (vol_short + vol_long) / 2.0 * np.sqrt(af)
        if not (vol_est > 0):
            return 1.0
        return float(np.clip(p["target_vol"] / vol_est, p["leverage_min"], p["leverage_max"]))

    def run(self) -> BacktestResult:
        """执行回测.
        
        交易逻辑:
        - T日: 用T-1日收盘价计算权重, T日收盘价成交
        - T日按当日收盘价估值新持仓，调仓收益从T+1日开始体现
        
        波动率重置逻辑:
        - 每日检查组合波动率；超过阈值时记录「信号日」
        - 执行日 = 信号日后第2个交易日（故信号日当天不会调仓）
        - 若执行日同时也是常规调仓日，优先执行波动率重置并标记为 vol_reset
        """
        position = Position(quantity={}, cash=self._config.initial_cash)
        snapshots: List[PortfolioSnapshot] = []
        trades_all: List[Trade] = []
        last_rebalance_date = None  # 记录上次调仓日期
        last_target_weights = {}  # 最近一次调仓的目标权重（仅 risk_budget_target_vol 混合动量策略时用于持仓权重图展示）
        use_target_weights_for_snapshot = self._resolve_snapshot_weight_source() == "target"

        # 波动率重置相关状态
        vol_reset_signal_date = None  # 波动率重置信号日
        vol_reset_trigger_value = None  # 触发时的波动率值
        vol_reset_execute_date = None  # 波动率重置执行日（由 ScheduleResolver 计算）

        # 构建调度映射表（执行日 → 信号日）
        start_dt = pd.to_datetime(self._config.start_date)
        end_dt = pd.to_datetime(self._config.end_date)
        self._build_schedule_maps(start_dt, end_dt)
        self._month_end_dates_set = set()

        first_bar_in_range = True  # 用于期初建仓：首日按策略权重建仓
        # 信号时点能力：signal_timing="execution_bar" 表示策略用执行日当日收盘价做信号
        # （如类雪球 Delta 对冲，对齐四象限原型“当日收盘定价+调仓”语义）；
        # 默认 T-1 信号（用前一日收盘算权重，当日收盘成交），避免前视偏差。
        _signal_uses_execution_bar = False
        try:
            _caps = self._strategy.get_capabilities() if hasattr(self._strategy, "get_capabilities") else {}
            _signal_uses_execution_bar = (_caps or {}).get("signal_timing") == "execution_bar"
        except Exception:
            _signal_uses_execution_bar = False

        # return-level 波动率定标状态（对齐 GMSI 2.0 原型 raw_ret × leverage.shift(1)）：
        # 策略声明 vol_targeting_enabled 后，Pipeline 输出未缩放权重，
        # 引擎从实际净值收益反推未缩放收益序列，逐日重算 leverage，
        # 每日快照后按 leverage 变化无成本调整仓位敞口（指数级缩放）。
        rt_params = self._get_return_targeting_params()
        rt_raw_returns: List[float] = []
        rt_leverage = 1.0            # 最新计算的 leverage（lev_t）
        rt_applied_leverage = 1.0    # 当前持仓内嵌的缩放倍数（lev_{t-1}）
        rt_prev_total_value: Optional[float] = None

        for time, bar in self._data_feed.iter_bars():
            # 仅在回测设置的区间内进行模拟
            if time < pd.to_datetime(self._config.start_date):
                continue
            if time > pd.to_datetime(self._config.end_date):
                break

            # 当前组合总市值与权重（用于波动率监控与净值更新）
            total_value, current_weights = self._compute_traditional_value_and_weights(position, bar)

            # return-level 定标：从已实现净值收益反推未缩放收益，重算当日 leverage
            if rt_params is not None and rt_prev_total_value and rt_prev_total_value > 0:
                realized_ret = total_value / rt_prev_total_value - 1.0
                if rt_applied_leverage > 1e-12:
                    raw_ret = realized_ret / rt_applied_leverage
                else:
                    raw_ret = realized_ret
                rt_raw_returns.append(float(raw_ret))
                rt_leverage = self._compute_return_level_leverage(rt_raw_returns, rt_params)

            # 每日监控指标（仅当有持仓时）
            portfolio_vol = None
            monitoring_metrics = {}
            if len(current_weights) > 0:
                history = self._data_feed.get_history_window(time)
                if not history.empty:
                    try:
                        # 1. 获取通用监控指标（支持自定义指标扩展）
                        monitoring_metrics = self._strategy.compute_monitoring_metrics(
                            current_weights=current_weights,
                            history_prices=history
                        )
                        portfolio_vol = monitoring_metrics.get("portfolio_volatility")
                        
                        # 2. 检查是否触发波动率重置（触发参数均来自策略参数，回测配置不参与）
                        if hasattr(self._strategy, 'check_volatility_trigger'):
                            is_triggered, vol_value = self._strategy.check_volatility_trigger(
                                current_weights=current_weights,
                                prices=history,
                            )
                            
                            # 如果策略没在 monitoring_metrics 中返回波动率，则使用 vol_value
                            if portfolio_vol is None and vol_value is not None:
                                portfolio_vol = vol_value
                            # 如果触发且当前没有待处理的重置信号：始终记录信号（含常规调仓日），通过 ScheduleResolver 计算执行日
                            if is_triggered and vol_reset_signal_date is None and vol_value is not None:
                                vol_reset_signal_date = time
                                vol_reset_trigger_value = vol_value
                                # 用 ScheduleResolver 计算执行日（+delay 并处理 skip_dates）
                                time_norm = pd.Timestamp(time.date()) if hasattr(time, 'date') else time.normalize()
                                vol_reset_execute_date = self._schedule_resolver.resolve_execute_date(time_norm) if self._schedule_resolver else None
                                if self._is_execute_day(time):
                                    logger.info(f"[波动率重置] 信号日记录(同日常规调仓): {time.date()} 组合波动率={vol_value:.4%}，执行日={vol_reset_execute_date.date() if vol_reset_execute_date else 'N/A'}")
                                else:
                                    logger.info(f"[波动率重置] 信号日记录: {time.date()} 组合波动率={vol_value:.4%}，执行日={vol_reset_execute_date.date() if vol_reset_execute_date else 'N/A'}")
                        
                        # 3. 波动率公式属于策略/控制层：策略未给出时引擎不自行计算，
                        #    仅记录为空（快照会如实上报 None，前端跳过该点）。
                        if portfolio_vol is None:
                            logger.debug(
                                "[波动率监控] %s 策略未返回组合波动率，快照记为空",
                                pd.Timestamp(time).strftime("%Y-%m-%d"),
                            )
                    except Exception as e:
                        # 波动率监控/触发计算失败时记录，便于排查“未触发重置”问题
                        logger.warning(f"[波动率重置] 监控计算异常 {time.date()}: {e}")
                        logger.debug(f"[波动率重置] 异常详情", exc_info=True)

            # 是否在该时点调仓
            # 优先级：期初建仓 > 交互式权重调整 > 波动率重置 > 常规调仓
            do_rebalance = False
            rebalance_type = None
            rebalance_reason = None
            _signal_date: pd.Timestamp | None = None  # 本次调仓的原始信号日
            _exec_delay_days: int = 0  # 本次调仓的延迟交易日数

            manual_adjustments = getattr(self._config, "manual_weight_adjustments", None) or {}
            date_str = time.strftime("%Y%m%d")
            rebalance_only_preset = getattr(self._config, "rebalance_only_on_preset_dates", False)
            initial_weights = getattr(self._config, "initial_weights", None) or {}

            # 期初建仓：若配置了 initial_weights 且当前无持仓，则在首日按该权重建仓（主观策略）
            if initial_weights and sum((v or 0) for v in initial_weights.values()) > 0:
                has_position = bool(position.quantity)
                if not has_position:
                    do_rebalance = True
                    rebalance_type = "manual_adjustment"
                    rebalance_reason = "期初建仓"

            # 期初建仓（量化策略）：首日无持仓且未配置有效 initial_weights 时，按策略权重建仓
            # 与常规调仓一致，调用 generate_target_weights；risk_budget_target_vol 混合动量会执行资产选择（7+1 动量/反转）
            if not do_rebalance and first_bar_in_range:
                has_position = bool(position.quantity)
                init_sum = sum((v or 0) for v in (initial_weights or {}).values())
                if not has_position and init_sum == 0:
                    do_rebalance = True
                    rebalance_type = "期初建仓"
                    rebalance_reason = "期初建仓"

            # 交互式权重调整：指定日期使用用户预设的权重（仅当配置了 manual_weight_adjustments 时）
            if not do_rebalance and date_str in manual_adjustments:
                adj_item = manual_adjustments.get(date_str, {})
                if adj_item.get("weights") and len(adj_item.get("weights", {})) > 0:
                    do_rebalance = True
                    rebalance_type = "manual_adjustment"
                    rebalance_reason = "预设调仓"

            # 主观策略仅按预设日期调仓：不执行周期性调仓与波动率阈值重置
            if not rebalance_only_preset:
                if not do_rebalance and vol_reset_signal_date is not None:
                    # 通过 ScheduleResolver 计算的执行日判断是否到达执行日
                    time_norm = pd.Timestamp(time.date()) if hasattr(time, 'date') else time.normalize()
                    if vol_reset_execute_date is not None and time_norm >= vol_reset_execute_date:
                        do_rebalance = True
                        rebalance_type = "vol_reset"
                        _vol_signal_date = vol_reset_signal_date
                        _vol_trigger_val = vol_reset_trigger_value
                        # 记录延迟信息
                        _signal_date = _vol_signal_date
                        if _vol_signal_date is not None and vol_reset_execute_date is not None:
                            # 计算交易日延迟数
                            try:
                                td = self._schedule_resolver._trade_dates
                                sig_idx = np.searchsorted(td, _vol_signal_date)
                                exec_idx = np.searchsorted(td, time_norm)
                                _exec_delay_days = max(exec_idx - sig_idx, 0)
                            except (AttributeError, TypeError, ValueError) as exc:
                                logger.warning(
                                    "[波动率重置] %s 无法推算信号日到执行日的交易日延迟，记为 0：%s",
                                    time_norm.strftime("%Y-%m-%d"), exc,
                                )
                                _exec_delay_days = 0
                        if _vol_trigger_val is not None:
                            rebalance_reason = f"波动率重置触发（信号日年化波动率={_vol_trigger_val:.4%}）"
                        else:
                            rebalance_reason = "波动率重置触发"
                        logger.info(f"[波动率重置] 执行日: {time.date()} (信号日={_vol_signal_date.date() if hasattr(_vol_signal_date, 'date') else _vol_signal_date})")
                        vol_reset_signal_date = None
                        vol_reset_trigger_value = None
                        vol_reset_execute_date = None
                    elif self._is_execute_day(time):
                        # 信号日或 T+1：若今日也是常规调仓日，照常执行常规调仓，保留 T+2 波动率重置
                        do_rebalance = True
                        rebalance_type = "regular"
                        rebalance_reason = "周期性调仓"
                elif not do_rebalance and self._is_execute_day(time):
                    do_rebalance = True
                    rebalance_type = "regular"
                    rebalance_reason = "周期性调仓"
                    # 记录延迟信息：从 execute_to_signal 映射获取信号日
                    time_norm = pd.Timestamp(time.date()) if hasattr(time, 'date') else time.normalize()
                    _signal_date = self._execute_to_signal.get(time_norm)
                    if _signal_date is not None and _signal_date != time_norm:
                        try:
                            td = self._schedule_resolver._trade_dates
                            sig_idx = np.searchsorted(td, _signal_date)
                            exec_idx = np.searchsorted(td, time_norm)
                            _exec_delay_days = max(exec_idx - sig_idx, 0)
                        except (AttributeError, TypeError, ValueError) as exc:
                            logger.warning(
                                "[调仓] %s 无法推算信号日到执行日的交易日延迟，记为 0：%s",
                                time_norm.strftime("%Y-%m-%d"), exc,
                            )
                            _exec_delay_days = 0

            if do_rebalance:
                # 历史窗口（不含未来，避免前视偏差）；交互式权重调整不依赖历史数据
                # 缺日保真策略使用保留缺日 NaN 的 strategy_prices，其余策略用 ffill 后的 prices
                if self._preserve_price_gaps and self._data_feed.strategy_prices is not None:
                    _hist_src = self._data_feed.strategy_prices
                    history = _hist_src.loc[_hist_src.index < time]
                else:
                    _hist_src = self._data_feed.prices
                    history = self._data_feed.get_history_window(time)
                # 声明 execution_bar 的策略：信号窗口包含当日 bar（当日收盘决策、当日收盘成交）
                if _signal_uses_execution_bar and time in _hist_src.index:
                    history = pd.concat([history, _hist_src.loc[[time]]])
                elif _signal_date is not None:
                    # prev_close 口径：信号在信号日收盘计算，延迟执行时
                    # 成交日的历史窗口会含信号日之后的行情（前视），
                    # 必须截断到信号日（对齐原型 signal_dates_in_dates 口径）
                    sig_ts = pd.Timestamp(_signal_date)
                    if not history.empty and history.index[-1] > sig_ts:
                        history = history.loc[history.index <= sig_ts]

                if history.empty and rebalance_type != "manual_adjustment":
                    if rebalance_type == "vol_reset":
                        logger.debug(f"[波动率重置] 跳过执行(历史数据为空): {time.date()}")
                    continue

                # 根据调仓类型生成目标权重
                if rebalance_type == "manual_adjustment":
                    if rebalance_reason == "期初建仓":
                        # 期初建仓：使用 config.initial_weights；是否归一化由 initial_weights_auto_normalize 控制
                        weights_dict = {k: float(v or 0) for k, v in initial_weights.items() if k in self._config.thscodes}
                        for code in self._config.thscodes:
                            if code not in weights_dict:
                                weights_dict[code] = 0.0
                        if getattr(self._config, "initial_weights_auto_normalize", False) and weights_dict:
                            total = sum(weights_dict.values())
                            if total > 0:
                                weights_dict = {k: v / total for k, v in weights_dict.items()}
                    else:
                        # 交互式权重调整：使用用户预设的权重
                        adj_item = manual_adjustments.get(date_str, {})
                        weights_dict = dict(adj_item.get("weights", {}))
                        auto_norm = adj_item.get("auto_normalize", False)
                        for code in self._config.thscodes:
                            if code not in weights_dict:
                                weights_dict[code] = 0.0
                        if auto_norm and weights_dict:
                            total = sum(weights_dict.values())
                            if total > 0:
                                weights_dict = {k: v / total for k, v in weights_dict.items()}
                    weights_dict = {k: v for k, v in weights_dict.items() if k in self._config.thscodes}
                    from app.backtesting.signal import TargetWeightSignal
                    target_signal = TargetWeightSignal(time=time, target_weights=weights_dict)
                elif rebalance_type == "vol_reset" and hasattr(self._strategy, 'compute_volatility_reset_weights'):
                    # 使用信号日记录的 VolTrigger 进行等比例缩放，避免执行日重算波动率导致不缩放（编制规则 4.3.4）
                    # 只传回测层真正拥有的变量：信号日波动率与显式配置的目标波动率；
                    # 其余参数由策略自己提供（全量透传 config 会用 None 覆盖策略参数）。
                    params_for_reset: Dict[str, Any] = {}
                    if getattr(self._config, "target_vol", None) is not None:
                        params_for_reset["target_vol"] = self._config.target_vol
                    if _vol_trigger_val is not None:
                        params_for_reset["_vol_trigger"] = _vol_trigger_val
                    reset_weights = self._strategy.compute_volatility_reset_weights(
                        current_weights=current_weights,
                        prices=history,
                        **params_for_reset
                    )

                    if reset_weights is not None:
                        from app.backtesting.signal import TargetWeightSignal
                        target_signal = TargetWeightSignal(time=time, target_weights=reset_weights.to_dict())
                    else:
                        logger.debug(f"[波动率重置] 跳过执行(compute_volatility_reset_weights 返回空): {time.date()}")
                        continue
                else:
                    # 常规调仓：策略生成目标权重
                    try:
                        target_signal = self._strategy.generate_target_weights(history, as_of=time)
                    except ValueError as exc:
                        # 对齐四象限原型：子策略起点早于数据覆盖时（如多资产 2017-01-03 起跑、
                        # 数据库行情自 2017-01-04 起），早期调仓历史不足导致选择器报
                        # 「没有资产满足最小历史数据要求/未选出任何资产」。
                        # 原型语义为空仓持有现金（select_assets 无合格资产返回零权重），
                        # 此处跳过本次调仓（维持空仓），待历史累积足够后自然恢复。
                        _msg = str(exc)
                        _is_insufficient_history = (
                            "最小历史数据" in _msg
                            or "历史数据不足" in _msg
                            or "未选出任何资产" in _msg
                            # 预热期信号窗口未满时复合信号为空（如趋势-截面复合
                            # 前 tf_lookback/cs_lookback 日），与原型预热期零收益语义一致：
                            # 空仓持有现金，待历史累积足够后自然恢复
                            or "未收到复合信号" in _msg
                            # 分配器预热期数据不足（如反方差预算需要 vol 窗口）
                            or "预算模式数据不足" in _msg
                            or "1/σ² 之和 <= 0" in _msg
                        )
                        if _is_insufficient_history:
                            logger.info(
                                "[调仓] %s 历史数据不足，本次调仓跳过（空仓持有现金，对齐原型预热语义）：%s",
                                pd.Timestamp(time).strftime("%Y-%m-%d"), exc,
                            )
                            do_rebalance = False
                            continue
                        raise

                # 风控调整
                target_signal = self._risk.apply_risk_checks(target_signal, history)
                
                # 说明：此处原有一段「常规调仓后再做波动率缩放」逻辑，其开关依赖
                # config.enable_vol_reset（BacktestConfig 并无此字段），恰好永不生效；
                # 且它在引擎内重写了 w × target_vol / vol 的缩放公式。波动率缩放属于
                # 控制层（compute_volatility_reset_weights），故此处已删除，不在引擎重建公式。

                # 记录目标权重供快照展示（支持杠杆>1时权重和超过100%）
                last_target_weights = {}
                for code in self._config.thscodes:
                    last_target_weights[code] = float(target_signal.target_weights.get(code, 0.0))

                # 执行调仓：使用ExecutionEngine（手续费 + 滑点在其内部扣减）
                total_value, position = self._execute_rebalance_traditional(
                    bar=bar,
                    position=position,
                    target_signal=target_signal,
                    trades_all=trades_all,
                )

                # return-level 定标：调仓后持仓为未缩放权重，内嵌缩放倍数重置为 1.0，
                # 快照后的无成本调整步骤会按当日 leverage 重新上缩放
                if rt_params is not None:
                    rt_applied_leverage = 1.0

                last_rebalance_date = time

            # 计算当日净值
            total_value, holdings_value, cash_value, weights = self._update_nav_and_weights_traditional_mode(
                bar=bar,
                position=position,
                total_value=total_value,
            )
            
            # 调仓日：用调仓后权重重算波动率，使监控图展示正确的「调仓后预期波动率」（编制规则 4.3.4）
            if do_rebalance and last_target_weights:
                portfolio_vol, monitoring_metrics = self._recalc_post_rebalance_vol(
                    time, bar, last_target_weights, portfolio_vol, monitoring_metrics,
                )
            
            # 记录组合快照(每天都记录)
            is_rebalance_day = (last_rebalance_date == time)
            # 杠杆类策略按能力声明使用目标权重展示（权重和可 >1），否则用市值归一化的实际权重
            snapshot_weights = (last_target_weights if last_target_weights else weights) if use_target_weights_for_snapshot else weights

            snapshots.append(self._build_snapshot(
                time=time,
                total_value=total_value,
                cash_value=cash_value,
                holdings_value=holdings_value,
                weights=snapshot_weights,
                is_rebalance_day=is_rebalance_day,
                rebalance_type=rebalance_type,
                rebalance_reason=rebalance_reason,
                portfolio_vol=portfolio_vol,
                monitoring_metrics=monitoring_metrics,
                signal_date=_signal_date,
                execution_delay_days=_exec_delay_days,
            ))

            # 每日结算钩子：策略可执行闲置资金利息、GC001回购利息等每日调整
            position, total_value = self._run_daily_settle(time, position, total_value, bar.extra)

            # return-level 定标：快照已记录当日净值，此处按 leverage 变化无成本调整
            # 仓位敞口（持仓数量×k、现金反向补偿，净值不变），使次日收益体现 lev_t
            if (
                rt_params is not None
                and position.quantity
                and abs(rt_leverage - rt_applied_leverage) > 1e-12
            ):
                if rt_applied_leverage > 1e-12:
                    k = rt_leverage / rt_applied_leverage
                else:
                    k = rt_leverage
                if abs(k - 1.0) > 1e-12:
                    holdings_val = sum(
                        qty * bar.close.get(code, 0.0)
                        for code, qty in position.quantity.items()
                    )
                    position = Position(
                        quantity={c: q * k for c, q in position.quantity.items()},
                        cash=position.cash + holdings_val * (1.0 - k),
                    )
                rt_applied_leverage = rt_leverage

            rt_prev_total_value = total_value

            first_bar_in_range = False  # 首日已处理，后续不再触发期初建仓

        logger.info(f"回测结束: 快照={len(snapshots)}, 交易={len(trades_all)}")
        if trades_all:
            logger.debug(f"首条交易: {trades_all[0].time.strftime('%Y-%m-%d')} {trades_all[0].thscode} {trades_all[0].quantity:.2f}")
            logger.debug(f"末条交易: {trades_all[-1].time.strftime('%Y-%m-%d')} {trades_all[-1].thscode} {trades_all[-1].quantity:.2f}")
        else:
            logger.warning("没有生成任何交易记录")
        if len(snapshots) == 0:
            prices_len = len(self._data_feed.prices) if self._data_feed.prices is not None else 0
            logger.warning(
                f"回测无数据。可能原因：1) 建仓日晚于今日；2) 回测区间 [{self._config.start_date}~{self._config.end_date}] "
                f"与行情数据无交集（已加载 {prices_len} 行）；3) 日期配置错误。请核查。"
            )
        
        return BacktestResult(snapshots=snapshots, trades=trades_all, config=self._config)

