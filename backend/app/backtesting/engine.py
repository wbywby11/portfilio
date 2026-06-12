from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple

import pandas as pd

from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.strategy_api import IStrategy
from app.backtesting.risk import RiskManager
from app.backtesting.execution import ExecutionEngine, ExecutionResult
from app.backtesting.types import Position, PortfolioSnapshot, Bar, Trade
from app.backtesting.index_nav import IndexNavCalculator, IndexNavConfig

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
        
        # 初始化指数净值计算器（如果启用）
        self._index_nav_calculator: Optional[IndexNavCalculator] = None
        self._tr_series = config.tr_series or None  # {asset_code: Series(TR)}
        if config.use_index_nav:
            nav_config = IndexNavConfig(
                initial_nav=config.index_nav_initial,
                fx_rates=config.fx_rates or {},
                transaction_costs=config.transaction_costs or {},
                replication_costs=config.replication_costs or {},
            )
            self._index_nav_calculator = IndexNavCalculator(nav_config)

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

    def _get_tr_values_for_date(self, date: pd.Timestamp, codes, bar: Bar) -> dict:
        """根据TR序列获取指定日期的样本点位，若缺失则回退到收盘价.

        当配置了tr_series时优先使用TR样本点位；
        对于缺失TR的资产或日期，则使用当日收盘价近似作为样本点位，
        保证指数净值模式在TR不完整时仍可运行。
        """
        # 防御性检查：确保 bar.close 是字典
        if not isinstance(bar.close, dict):
            raise TypeError(
                f"bar.close 必须是字典类型，实际类型为 {type(bar.close)}。"
                f"可能是数据格式问题，请检查数据源。"
            )
        
        if not getattr(self, "_tr_series", None):
            return {code: bar.close.get(code, 0.0) for code in codes if code in bar.close}

        tr_values = {}
        for code in codes:
            series = self._tr_series.get(code) if self._tr_series else None
            if series is not None:
                try:
                    if date in series.index:
                        tr_values[code] = float(series.loc[date])
                        continue
                except Exception:
                    # 任意异常都回退到收盘价
                    pass
            # 使用 get 方法安全访问，避免 KeyError
            if code in bar.close:
                tr_values[code] = bar.close.get(code, 0.0)
        return tr_values

    def _execute_rebalance_index_nav(
        self,
        time: pd.Timestamp,
        bar: Bar,
        target_signal,
        trades_all: List[Trade],
    ) -> tuple[float, Position]:
        """指数净值模式下的调仓执行."""
        if self._index_nav_calculator is None:
            raise RuntimeError("Index NAV calculator is not initialized.")
        tr_values = self._get_tr_values_for_date(time, target_signal.target_weights.keys(), bar)
        
        # 在调仓之前保存当前权重（用于生成交易记录）
        current_weights_before_rebalance = self._index_nav_calculator.get_current_weights()
        
        # 执行调仓（这会更新内部的权重）
        adjusted_nav = self._index_nav_calculator.on_rebalance(
            date=time,
            target_weights=target_signal.target_weights,
            tr_values=tr_values,
        )
        
        # 生成模拟交易记录（用于前端展示）
        # 注意：这些是模拟的交易，实际指数净值计算不依赖这些记录
        
        # 调试信息：打印当前权重和目标权重
        print(f"[指数净值调仓] 时间={time.strftime('%Y-%m-%d')}, 调仓前权重={current_weights_before_rebalance}")
        print(f"[指数净值调仓] 目标权重={target_signal.target_weights}")
        
        trades_count = 0
        for thscode, target_weight in target_signal.target_weights.items():
            current_weight = current_weights_before_rebalance.get(thscode, 0.0)
            weight_change = target_weight - current_weight
            
            # 如果权重有变化，生成交易记录
            if abs(weight_change) > 1e-6:  # 忽略极小的权重变化
                # 使用TR值或收盘价作为交易价格
                price = tr_values.get(thscode, bar.close.get(thscode, 0.0))
                if price > 0:
                    # 计算模拟的交易数量（基于当前净值和权重变化）
                    # quantity = (净值 × 权重变化) / 价格
                    quantity = (adjusted_nav * weight_change) / price
                    
                    # 确定交易方向
                    side = "buy" if weight_change > 0 else "sell"
                    
                    # 计算手续费（基于权重变化的绝对值）
                    tc_rate = self._config.transaction_costs.get(thscode, 0.0) if self._config.transaction_costs else 0.0
                    commission = abs(adjusted_nav * weight_change) * tc_rate
                    
                    # 滑点成本（使用配置的滑点率）
                    slippage_cost = abs(quantity * price * self._config.slippage)
                    
                    trades_all.append(Trade(
                        time=time,
                        thscode=thscode,
                        side=side,
                        quantity=abs(quantity),  # 数量取绝对值，方向由side表示
                        price=price,
                        commission=commission,
                        slippage_cost=slippage_cost
                    ))
                    trades_count += 1
                    print(f"  生成交易: {thscode}, 方向={side}, 权重变化={weight_change:.4f}, 数量={abs(quantity):.2f}, 价格={price:.4f}")
        
        print(f"[指数净值调仓] 本次生成 {trades_count} 条交易记录")
        
        # 指数净值模式下，Position仅作为占位对象
        position = Position(quantity={}, cash=0.0)
        return adjusted_nav, position

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

    def _update_nav_and_weights_index_mode(
        self,
        time: pd.Timestamp,
        bar: Bar,
        do_rebalance: bool,
        total_value: float,
    ):
        """指数净值模式下的净值与权重更新."""
        if self._index_nav_calculator is None:
            raise RuntimeError("Index NAV calculator is not initialized.")
        if not do_rebalance:
            tr_values = self._get_tr_values_for_date(time, self._index_nav_calculator.ledgers.keys(), bar)
            total_value = self._index_nav_calculator.compute_nav(
                date=time,
                tr_values=tr_values,
            )
        weights = self._index_nav_calculator.get_current_weights()
        holdings_value = total_value
        cash_value = 0.0
        return total_value, holdings_value, cash_value, weights

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

    def _apply_traditional_replication_cost(
        self,
        time: pd.Timestamp,
        bar: Bar,
        position: Position,
        last_rc_date: Optional[pd.Timestamp],
    ) -> Tuple[Position, pd.Timestamp]:
        """传统市值模式下每日复制费拖拽（与监控引擎对齐）。

        只在未启用指数净值计算器（主观策略路径）且 config.replication_costs 非空
        时生效；IndexNavCalculator 路径已在其内部处理复制费，不需重复扣减。

        费用公式与监控 portfolio_tracker.update_daily_pnl 一致：
            daily_rc = sum_assets( |qty * close| * rc_rate / 365 * days_between )
        拖拽仅从 position.cash 中扣减，并不改变持仓 quantity，使后续 total_value
        = cash + sum(qty*price) 自然反映复制费。
        """
        rc_map = getattr(self._config, "replication_costs", None) or {}
        if not rc_map or not position.quantity:
            return position, last_rc_date if last_rc_date is not None else time
        if last_rc_date is None:
            return position, time
        days_between = (time - last_rc_date).days
        if days_between <= 0:
            return position, last_rc_date
        if not isinstance(bar.close, dict):
            return position, time
        daily_rc_total = 0.0
        for code, qty in position.quantity.items():
            if not qty:
                continue
            rc_rate = float(rc_map.get(code, 0.0) or 0.0)
            if rc_rate <= 0:
                continue
            price = float(bar.close.get(code, 0.0) or 0.0)
            if price <= 0:
                continue
            pos_value = abs(qty * price)
            daily_rc_total += pos_value * (rc_rate / 365.0) * days_between
        if daily_rc_total > 0:
            position.cash -= daily_rc_total
            logger.info(
                "[主观回测][RC] %s 扣除复制费 %.4f（跨 %d 天），现金余额=%.4f",
                pd.Timestamp(time).strftime("%Y-%m-%d"),
                daily_rc_total,
                days_between,
                position.cash,
            )
        return position, time

    def _is_hybrid_momentum_risk_budget(self) -> bool:
        """判断是否为 risk_budget_target_vol 的混合动量策略（需用目标权重展示，支持杠杆>1时权重和超过100%）。"""
        if not hasattr(self._strategy, "_base_strategy"):
            return False  # 混合动量需启用资产选择（StrategyAdapterWithSelection）
        impl = getattr(self._strategy._base_strategy, "_impl", None)
        return impl is not None and type(impl).__name__ == "RiskBudgetTargetVolStrategy"

    def run(self) -> BacktestResult:
        """执行回测.
        
        交易逻辑:
        - T日: 用T-1日收盘价计算权重, T日收盘价成交
        - T日没有收益(资金调整中)
        - T+1日开始享受收益
        
        波动率重置逻辑:
        - 每日检查组合波动率；超过阈值时记录「信号日」（仅当该日不是常规调仓日时才记录）
        - 执行日 = 信号日后第2个交易日（故信号日当天不会调仓）
        - 若执行日同时也是常规调仓日，优先执行波动率重置并标记为 vol_reset
        """
        position = Position(quantity={}, cash=self._config.initial_cash)
        snapshots: List[PortfolioSnapshot] = []
        trades_all: List[Trade] = []
        last_rebalance_date = None  # 记录上次调仓日期
        last_target_weights = {}  # 最近一次调仓的目标权重（仅 risk_budget_target_vol 混合动量策略时用于持仓权重图展示）
        use_target_weights_for_snapshot = self._is_hybrid_momentum_risk_budget()

        # 波动率重置相关状态
        vol_reset_signal_date = None  # 波动率重置信号日
        vol_reset_trigger_value = None  # 触发时的波动率值
        trading_days_count = 0  # 交易日计数器

        # month_end 模式：预计算月末最后一个交易日（与编制规则 step1/step2/trade_dates 一致）
        if self._config.rebalance_freq == "month_end":
            prices_idx = self._data_feed.prices.index
            start_dt = pd.to_datetime(self._config.start_date)
            end_dt = pd.to_datetime(self._config.end_date)
            in_range = prices_idx[(prices_idx >= start_dt) & (prices_idx <= end_dt)]
            # 按年月分组，取每月最后一个日期（价格数据日历的月末 = 月末最后一个交易日）
            month_ends = in_range.to_series().groupby(in_range.to_period("M")).last().values
            self._month_end_dates_set = set(pd.Timestamp(d) for d in month_ends)
            # 编制规则：2015-01-05 为元旦后第1个交易日，永不调仓（执行日=月末后第2个交易日）
            self._month_end_dates_set.discard(pd.Timestamp("2015-01-05"))
        else:
            self._month_end_dates_set = set()

        first_bar_in_range = True  # 用于期初建仓：首日按策略权重建仓
        last_rc_date: Optional[pd.Timestamp] = None  # 传统模式复制费上一计算日
        for time, bar in self._data_feed.iter_bars():
            # 仅在回测设置的区间内进行模拟
            if time < pd.to_datetime(self._config.start_date):
                continue
            if time > pd.to_datetime(self._config.end_date):
                break

            # 传统市值模式：每日开始时扣除与监控对齐的复制费拖拽
            # 仅在 IndexNavCalculator 未启用且 replication_costs 配置非空时生效（主观策略）
            if self._index_nav_calculator is None:
                position, last_rc_date = self._apply_traditional_replication_cost(
                    time=time, bar=bar, position=position, last_rc_date=last_rc_date,
                )

            # 当前组合总市值与权重（用于波动率监控与净值更新）
            if self._index_nav_calculator is not None:
                # 指数净值模式：从计算器取当前权重与净值，保证每日监控到真实持仓
                codes = list(self._index_nav_calculator.ledgers.keys()) if self._index_nav_calculator.ledgers else list(bar.close.keys())
                tr_values = self._get_tr_values_for_date(time, codes, bar)
                if self._index_nav_calculator.ledgers:
                    total_value = self._index_nav_calculator.compute_nav(
                        date=time, tr_values=tr_values
                    )
                    current_weights = pd.Series(
                        self._index_nav_calculator.get_current_weights()
                    )
                else:
                    total_value = self._config.initial_cash
                    current_weights = pd.Series(dtype=float)
            else:
                total_value = self._compute_total_value(position, bar)
                current_weights = pd.Series({
                    code: (qty * bar.close.get(code, 0.0) / total_value) if total_value > 0 else 0.0
                    for code, qty in position.quantity.items()
                })

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
                        
                        # 2. 检查是否触发波动率重置（支持特定策略逻辑）
                        if hasattr(self._strategy, 'check_volatility_trigger'):
                            is_triggered, vol_value = self._strategy.check_volatility_trigger(
                                current_weights=current_weights,
                                prices=history,
                                **self._config.__dict__  # 传递配置参数
                            )
                            
                            # 如果策略没在 monitoring_metrics 中返回波动率，则使用 vol_value
                            if portfolio_vol is None and vol_value is not None:
                                portfolio_vol = vol_value
                            # 如果触发且当前没有待处理的重置信号：始终记录信号（含常规调仓日），T+2 再执行重置
                            if is_triggered and vol_reset_signal_date is None and vol_value is not None:
                                vol_reset_signal_date = time
                                vol_reset_trigger_value = vol_value
                                trading_days_count = 0
                                if self._should_rebalance(time):
                                    print(f"[波动率重置] 信号日记录(同日常规调仓): {time.date()} 组合波动率={vol_value:.4%}，T+2 执行重置")
                                else:
                                    print(f"[波动率重置] 信号日记录: {time.date()} 组合波动率={vol_value:.4%}，T+2 执行重置")
                        
                        # 3. 兜底：仍无波动率时由引擎统一计算（保证步进/单策略均有有效波动率）
                        if portfolio_vol is None:
                            from app.strategies.models.base import _default_portfolio_vol
                            portfolio_vol = _default_portfolio_vol(current_weights, history)
                    except Exception as e:
                        # 波动率监控/触发计算失败时打印，便于排查“未触发重置”问题
                        import traceback
                        print(f"[波动率重置] 监控计算异常 {time.date()}: {e}")
                        traceback.print_exc()

            # 是否在该时点调仓
            # 优先级：期初建仓 > 交互式权重调整 > 波动率重置 > 常规调仓
            do_rebalance = False
            rebalance_type = None
            rebalance_reason = None

            manual_adjustments = getattr(self._config, "manual_weight_adjustments", None) or {}
            date_str = time.strftime("%Y%m%d")
            rebalance_only_preset = getattr(self._config, "rebalance_only_on_preset_dates", False)
            initial_weights = getattr(self._config, "initial_weights", None) or {}

            # 期初建仓：若配置了 initial_weights 且当前无持仓，则在首日按该权重建仓（主观策略）
            if initial_weights and sum((v or 0) for v in initial_weights.values()) > 0:
                has_position = bool(position.quantity)
                if self._index_nav_calculator is not None:
                    has_position = bool(self._index_nav_calculator.ledgers)
                if not has_position:
                    do_rebalance = True
                    rebalance_type = "manual_adjustment"
                    rebalance_reason = "期初建仓"

            # 期初建仓（量化策略）：首日无持仓且未配置有效 initial_weights 时，按策略权重建仓
            # 与常规调仓一致，调用 generate_target_weights；risk_budget_target_vol 混合动量会执行资产选择（7+1 动量/反转）
            if not do_rebalance and first_bar_in_range:
                has_position = bool(position.quantity)
                if self._index_nav_calculator is not None:
                    has_position = bool(self._index_nav_calculator.ledgers)
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
                    trading_days_count += 1
                    if trading_days_count >= 2:
                        do_rebalance = True
                        rebalance_type = "vol_reset"
                        _vol_signal_date = vol_reset_signal_date
                        _vol_trigger_val = vol_reset_trigger_value
                        if _vol_trigger_val is not None:
                            try:
                                rebalance_reason = f"波动率重置触发（信号日年化波动率={_vol_trigger_val:.4%}）"
                            except Exception:
                                rebalance_reason = "波动率重置触发"
                        else:
                            rebalance_reason = "波动率重置触发"
                        vol_reset_signal_date = None
                        vol_reset_trigger_value = None
                        trading_days_count = 0
                        # 暂存供执行时写入 vol_reset_events_collector
                        setattr(self, "_pending_vol_reset_info", {"signal_date": _vol_signal_date, "vol_trigger": _vol_trigger_val})
                        print(f"[波动率重置] 执行日: {time.date()} (信号日后第2个交易日)")
                    elif self._should_rebalance(time):
                        # 信号日或 T+1：若今日也是常规调仓日，照常执行常规调仓，保留 T+2 波动率重置
                        do_rebalance = True
                        rebalance_type = "regular"
                        rebalance_reason = "周期性调仓"
                elif self._should_rebalance(time):
                    do_rebalance = True
                    rebalance_type = "regular"
                    rebalance_reason = "周期性调仓"

            if do_rebalance:
                # 历史窗口（不含未来，避免前视偏差）；交互式权重调整不依赖历史数据
                history = self._data_feed.get_history_window(time)

                if history.empty and rebalance_type != "manual_adjustment":
                    if rebalance_type == "vol_reset":
                        print(f"[波动率重置] 跳过执行(历史数据为空): {time.date()}")
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
                    pending = getattr(self, "_pending_vol_reset_info", {})
                    vol_trigger_signal = pending.get("vol_trigger")
                    params_for_reset = dict(self._config.__dict__)
                    if vol_trigger_signal is not None:
                        params_for_reset["_vol_trigger"] = vol_trigger_signal
                    reset_weights = self._strategy.compute_volatility_reset_weights(
                        current_weights=current_weights,
                        prices=history,
                        **params_for_reset
                    )

                    if reset_weights is not None:
                        from app.backtesting.signal import TargetWeightSignal
                        target_signal = TargetWeightSignal(time=time, target_weights=reset_weights.to_dict())
                        # 混合动量导出：记录波动率重置事件
                        collector = getattr(self._config, "vol_reset_events_collector", None)
                        if collector is not None:
                            pending = getattr(self, "_pending_vol_reset_info", {})
                            trigger_w = current_weights.to_dict() if hasattr(current_weights, "to_dict") else dict(current_weights)
                            reset_w = reset_weights.to_dict() if hasattr(reset_weights, "to_dict") else dict(reset_weights)
                            # 从策略参数获取（config 可能不含）
                            sp = {}
                            if hasattr(self._strategy, "_base_strategy"):
                                sp = getattr(self._strategy._base_strategy, "_params", {}) or {}
                            threshold_val = float(sp.get("vol_reset_threshold") or getattr(self._config, "vol_reset_threshold", 0.06) or 0.06)
                            target_vol_val = float(sp.get("target_vol") or getattr(self._config, "target_vol", 0.05) or 0.05)
                            vol_trig = pending.get("vol_trigger") or 0.0
                            scale_f = target_vol_val / vol_trig if vol_trig > 0 else 1.0
                            collector.append({
                                "signal_date": pending.get("signal_date"),
                                "execute_date": time,
                                "vol_trigger": vol_trig,
                                "threshold": threshold_val,
                                "target_vol": target_vol_val,
                                "scale_factor": scale_f,
                                "trigger_weights": trigger_w,
                                "reset_weights": reset_w,
                            })
                        if hasattr(self, "_pending_vol_reset_info"):
                            delattr(self, "_pending_vol_reset_info")
                    else:
                        print(f"[波动率重置] 跳过执行(compute_volatility_reset_weights 返回空): {time.date()}")
                        continue
                else:
                    # 常规调仓：策略生成目标权重
                    target_signal = self._strategy.generate_target_weights(history, as_of=time)

                # 风控调整
                target_signal = self._risk.apply_risk_checks(target_signal, history)
                
                # 常规调仓时：若新权重预期波动率仍超阈值，先做波动率缩放，避免月度调仓撤销波动率重置导致「快速回弹」
                if rebalance_type == "regular" and hasattr(self._strategy, "compute_monitoring_metrics"):
                    try:
                        sp = getattr(getattr(self._strategy, "_base_strategy", self._strategy), "_params", {}) or {}
                        enable_vr = sp.get("enable_vol_reset", True) and getattr(self._config, "enable_vol_reset", True)
                        if enable_vr and not history.empty:
                            w_new = pd.Series({k: float(v or 0) for k, v in target_signal.target_weights.items()})
                            if w_new.abs().sum() > 0:
                                m = self._strategy.compute_monitoring_metrics(
                                    current_weights=w_new, history_prices=history, **{**sp, **self._config.__dict__}
                                )
                                vol_new = m.get("portfolio_volatility")
                                thresh = float(sp.get("vol_reset_threshold") or getattr(self._config, "vol_reset_threshold", 0.06) or 0.06)
                                tvol = float(sp.get("target_vol") or getattr(self._config, "target_vol", 0.05) or 0.05)
                                if vol_new is not None and vol_new > thresh:
                                    scale = tvol / vol_new
                                    scaled = {k: float(v or 0) * scale for k, v in target_signal.target_weights.items()}
                                    from app.backtesting.signal import TargetWeightSignal
                                    target_signal = TargetWeightSignal(time=time, target_weights=scaled)
                    except Exception:
                        pass
                
                # 记录目标权重供快照展示（支持杠杆>1时权重和超过100%）
                last_target_weights = {}
                for code in self._config.thscodes:
                    last_target_weights[code] = float(target_signal.target_weights.get(code, 0.0))

                # 根据净值计算模式执行调仓
                if self._index_nav_calculator is not None:
                    # 指数净值模式：直接通知计算器调仓，内部自动扣除交易费用
                    total_value, position = self._execute_rebalance_index_nav(
                        time=time,
                        bar=bar,
                        target_signal=target_signal,
                        trades_all=trades_all,
                    )
                else:
                    # 传统模式：使用ExecutionEngine执行调仓
                    total_value, position = self._execute_rebalance_traditional(
                        bar=bar,
                        position=position,
                        target_signal=target_signal,
                        trades_all=trades_all,
                    )
                
                last_rebalance_date = time

            # 计算当日净值（根据模式）
            if self._index_nav_calculator is not None:
                total_value, holdings_value, cash_value, weights = self._update_nav_and_weights_index_mode(
                    time=time,
                    bar=bar,
                    do_rebalance=do_rebalance,
                    total_value=total_value,
                )
            else:
                total_value, holdings_value, cash_value, weights = self._update_nav_and_weights_traditional_mode(
                    bar=bar,
                    position=position,
                    total_value=total_value,
                )
            
            # 调仓日：用调仓后权重重算波动率，使监控图展示正确的「调仓后预期波动率」（编制规则 4.3.4）
            if do_rebalance and last_target_weights and not history.empty:
                try:
                    w_new = pd.Series({k: float(v or 0) for k, v in last_target_weights.items()})
                    if len(w_new) > 0 and w_new.abs().sum() > 0:
                        metrics_post = self._strategy.compute_monitoring_metrics(
                            current_weights=w_new,
                            history_prices=history,
                        )
                        vol_post = metrics_post.get("portfolio_volatility")
                        if vol_post is not None:
                            portfolio_vol = vol_post
                            monitoring_metrics["portfolio_volatility"] = vol_post
                except Exception:
                    pass
            
            # 记录组合快照(每天都记录)
            # 标记是否为调仓日(调仓日无收益)
            is_rebalance_day = (last_rebalance_date == time)
            # 指数净值模式 + 混合动量：调仓日使用计算器 get_target_weights（未归一化，与交易一致）
            # 非调仓日用 last_target_weights，解决「波动率调仓后净值权重未更新」问题
            if self._index_nav_calculator is not None and use_target_weights_for_snapshot:
                if is_rebalance_day:
                    calc_tw = self._index_nav_calculator.get_target_weights()
                    if calc_tw:
                        snapshot_weights = {code: float(calc_tw.get(code, 0.0)) for code in self._config.thscodes}
                    else:
                        snapshot_weights = last_target_weights if last_target_weights else weights
                else:
                    snapshot_weights = last_target_weights if last_target_weights else weights
            else:
                snapshot_weights = (last_target_weights if last_target_weights else weights) if use_target_weights_for_snapshot else weights

            snapshots.append(
                PortfolioSnapshot(
                    time=time,
                    total_value=total_value,
                    cash=cash_value,
                    holdings_value=holdings_value,
                    weights=snapshot_weights,
                    is_rebalance_day=is_rebalance_day,  # 标记调仓日
                    rebalance_type=rebalance_type if is_rebalance_day else None,  # 调仓类型
                    portfolio_volatility=portfolio_vol,  # 组合波动率
                    monitoring_metrics=monitoring_metrics,  # 所有监控指标
                    rebalance_reason=rebalance_reason if is_rebalance_day else None,  # 调仓原因
                )
            )

            first_bar_in_range = False  # 首日已处理，后续不再触发期初建仓

        print(f"\n=== 回测结束 ===")
        print(f"快照数量: {len(snapshots)}")
        print(f"交易记录数量: {len(trades_all)}")
        if trades_all:
            print(f"首条交易: {trades_all[0].time.strftime('%Y-%m-%d')} {trades_all[0].thscode} {trades_all[0].quantity:.2f}")
            print(f"末条交易: {trades_all[-1].time.strftime('%Y-%m-%d')} {trades_all[-1].thscode} {trades_all[-1].quantity:.2f}")
        else:
            print("警告: 没有生成任何交易记录！")
        if len(snapshots) == 0:
            prices_len = len(self._data_feed.prices) if self._data_feed.prices is not None else 0
            print(
                f"提示: 回测无数据。可能原因：1) 建仓日晚于今日；2) 回测区间 [{self._config.start_date}~{self._config.end_date}] "
                f"与行情数据无交集（已加载 {prices_len} 行）；3) 日期配置错误。请核查。"
            )
        print("===============\n")
        
        return BacktestResult(snapshots=snapshots, trades=trades_all, config=self._config)

    def run_step(
        self,
        stop_before_date: Optional[str] = None,
        initial_state: Optional[Dict[str, Any]] = None,
        override_decision: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[PortfolioSnapshot], List[Trade], Optional[Dict[str, Any]], Optional[str]]:
        """
        步进回测：可运行到指定日期前停止并返回状态，或从给定状态恢复并用 override_decision 处理当日。
        仅支持传统市值模式（use_index_nav=False）。
        返回 (snapshots, trades, state_at_last_day, stopped_at_date)。
        stopped_at_date 不为 None 表示在该日期前暂停；为 None 表示已跑完整个区间。
        """
        if self._index_nav_calculator is not None:
            raise ValueError("步进回测暂仅支持传统市值模式，请关闭指数净值计算")
        position = Position(quantity={}, cash=self._config.initial_cash)
        snapshots: List[PortfolioSnapshot] = []
        trades_all: List[Trade] = []
        last_rebalance_date = None
        vol_reset_signal_date = None
        vol_reset_trigger_value = None
        trading_days_count = 0
        last_state: Optional[Dict[str, Any]] = None
        stopped_at: Optional[str] = None
        manual_adjustments = getattr(self._config, "manual_weight_adjustments", None) or {}
        rebalance_only_preset = getattr(self._config, "rebalance_only_on_preset_dates", False)
        initial_weights = getattr(self._config, "initial_weights", None) or {}
        override_date = override_decision.get("date") if override_decision else None
        override_action = override_decision.get("action") if override_decision else None
        override_weights = override_decision.get("weights") if override_decision else None
        override_auto_norm = override_decision.get("auto_normalize", False) if override_decision else False
        restored = False
        last_rc_date: Optional[pd.Timestamp] = None  # 传统模式复制费上一计算日

        for time, bar in self._data_feed.iter_bars():
            if time < pd.to_datetime(self._config.start_date):
                continue
            if time > pd.to_datetime(self._config.end_date):
                break

            date_str = time.strftime("%Y%m%d")
            if initial_state and date_str <= initial_state.get("date", ""):
                continue
            if initial_state and not restored and date_str > initial_state.get("date", ""):
                pos = initial_state.get("position", {})
                position = Position(
                    quantity=dict(pos.get("quantity", {})),
                    cash=float(pos.get("cash", 0)),
                )
                restored = True

            if stop_before_date and date_str >= stop_before_date:
                stopped_at = stop_before_date
                break

            # 传统市值模式：每日开始时扣除与监控对齐的复制费拖拽。
            # run_step 仅主观策略使用，始终为传统模式；config.replication_costs 由
            # API 层 _build_manual_replication_costs 注入。
            position, last_rc_date = self._apply_traditional_replication_cost(
                time=time, bar=bar, position=position, last_rc_date=last_rc_date,
            )

            total_value = self._compute_total_value(position, bar)
            current_weights = pd.Series({
                code: (qty * bar.close.get(code, 0.0) / total_value) if total_value > 0 else 0.0
                for code, qty in position.quantity.items()
            })

            portfolio_vol = None
            monitoring_metrics = {}
            if len(current_weights) > 0:
                history = self._data_feed.get_history_window(time)
                if not history.empty:
                    try:
                        monitoring_metrics = self._strategy.compute_monitoring_metrics(
                            current_weights=current_weights, history_prices=history
                        )
                        portfolio_vol = monitoring_metrics.get("portfolio_volatility")
                        if hasattr(self._strategy, "check_volatility_trigger"):
                            is_triggered, vol_value = self._strategy.check_volatility_trigger(
                                current_weights=current_weights, prices=history, **self._config.__dict__
                            )
                            if portfolio_vol is None and vol_value is not None:
                                portfolio_vol = vol_value
                            if is_triggered and vol_reset_signal_date is None and vol_value is not None:
                                vol_reset_signal_date = time
                                vol_reset_trigger_value = vol_value
                                trading_days_count = 0
                                print(f"[步进] 波动率重置信号日: {time.date()} 组合波动率={vol_value:.4%}，T+2 执行重置")
                        if portfolio_vol is None:
                            from app.strategies.models.base import _default_portfolio_vol
                            portfolio_vol = _default_portfolio_vol(current_weights, history)
                    except Exception as e:
                        import traceback
                        print(f"[步进] 波动率计算异常 {time.date()}: {e}")
                        traceback.print_exc()

            do_rebalance = False
            rebalance_type = None
            rebalance_reason = None

            # 期初建仓（仅首段、无 initial_state 时）：无持仓则按 initial_weights 建仓
            if not initial_state and initial_weights and not position.quantity and sum((v or 0) for v in initial_weights.values()) > 0:
                do_rebalance = True
                rebalance_type = "manual_adjustment"
                rebalance_reason = "期初建仓"

            if override_date and date_str == override_date:
                if override_action == "rebalance" and override_weights and any((v or 0) != 0 for v in (override_weights or {}).values()):
                    do_rebalance = True
                    rebalance_type = "manual_adjustment"
                    rebalance_reason = "交互式调仓"
            elif date_str in manual_adjustments and not (override_date and date_str == override_date):
                do_rebalance = True
                rebalance_type = "manual_adjustment"
                rebalance_reason = "预设调仓"

            # 波动率阈值重置：无论 rebalance_only_preset 与否均执行，与单策略一致
            _vol_trigger_for_reset = None
            if not do_rebalance and vol_reset_signal_date is not None:
                trading_days_count += 1
                if trading_days_count >= 2:
                    do_rebalance = True
                    rebalance_type = "vol_reset"
                    _vol_trigger_for_reset = vol_reset_trigger_value
                    rebalance_reason = f"波动率重置触发（信号日年化波动率={vol_reset_trigger_value:.4%}）" if vol_reset_trigger_value is not None else "波动率重置触发"
                    vol_reset_signal_date = None
                    vol_reset_trigger_value = None
                    trading_days_count = 0
                    print(f"[步进] 波动率重置执行日: {time.date()} (信号日后第2个交易日)")

            if not rebalance_only_preset and not do_rebalance:
                if self._should_rebalance(time):
                    do_rebalance = True
                    rebalance_type = "regular"
                    rebalance_reason = "周期性调仓"

            if do_rebalance:
                history = self._data_feed.get_history_window(time)
                if history.empty and rebalance_type != "manual_adjustment":
                    if rebalance_type == "vol_reset":
                        pass
                    pass
                else:
                    if rebalance_type == "manual_adjustment":
                        if rebalance_reason == "期初建仓":
                            weights_dict = {k: float(v or 0) for k, v in initial_weights.items() if k in self._config.thscodes}
                            for code in self._config.thscodes:
                                if code not in weights_dict:
                                    weights_dict[code] = 0.0
                            if getattr(self._config, "initial_weights_auto_normalize", False) and weights_dict:
                                total = sum(weights_dict.values())
                                if total > 0:
                                    weights_dict = {k: v / total for k, v in weights_dict.items()}
                        elif override_date and date_str == override_date and override_weights is not None:
                            weights_dict = dict(override_weights)
                            auto_norm = override_auto_norm
                        else:
                            adj_item = manual_adjustments.get(date_str, {})
                            weights_dict = dict(adj_item.get("weights", {}))
                            auto_norm = adj_item.get("auto_normalize", False)
                        if rebalance_reason != "期初建仓":
                            if auto_norm and weights_dict:
                                total = sum(weights_dict.values())
                                if total > 0:
                                    weights_dict = {k: v / total for k, v in weights_dict.items()}
                        for code in self._config.thscodes:
                            if code not in weights_dict:
                                weights_dict[code] = 0.0
                        weights_dict = {k: v for k, v in weights_dict.items() if k in self._config.thscodes}
                        from app.backtesting.signal import TargetWeightSignal
                        target_signal = TargetWeightSignal(time=time, target_weights=weights_dict)
                    elif rebalance_type == "vol_reset" and hasattr(self._strategy, "compute_volatility_reset_weights"):
                        params_reset = dict(self._config.__dict__)
                        if _vol_trigger_for_reset is not None:
                            params_reset["_vol_trigger"] = _vol_trigger_for_reset
                        reset_weights = self._strategy.compute_volatility_reset_weights(
                            current_weights=current_weights, prices=history, **params_reset
                        )
                        if reset_weights is not None:
                            from app.backtesting.signal import TargetWeightSignal
                            target_signal = TargetWeightSignal(time=time, target_weights=reset_weights.to_dict())
                        else:
                            target_signal = None
                    else:
                        target_signal = self._strategy.generate_target_weights(history, as_of=time)
                    if target_signal is not None:
                        target_signal = self._risk.apply_risk_checks(target_signal, history)
                        # 常规调仓：若新权重预期波动率超阈值，先做波动率缩放
                        if rebalance_type == "regular" and hasattr(self._strategy, "compute_monitoring_metrics"):
                            try:
                                sp = getattr(getattr(self._strategy, "_base_strategy", self._strategy), "_params", {}) or {}
                                if sp.get("enable_vol_reset", True) and getattr(self._config, "enable_vol_reset", True) and not history.empty:
                                    w_new = pd.Series({k: float(v or 0) for k, v in target_signal.target_weights.items()})
                                    if w_new.abs().sum() > 0:
                                        m = self._strategy.compute_monitoring_metrics(
                                            current_weights=w_new, history_prices=history, **{**sp, **self._config.__dict__}
                                        )
                                        vol_new = m.get("portfolio_volatility")
                                        thresh = float(sp.get("vol_reset_threshold") or 0.06)
                                        tvol = float(sp.get("target_vol") or 0.05)
                                        if vol_new is not None and vol_new > thresh:
                                            scale = tvol / vol_new
                                            scaled = {k: float(v or 0) * scale for k, v in target_signal.target_weights.items()}
                                            from app.backtesting.signal import TargetWeightSignal
                                            target_signal = TargetWeightSignal(time=time, target_weights=scaled)
                            except Exception:
                                pass
                        total_value, position = self._execute_rebalance_traditional(
                            bar=bar, position=position, target_signal=target_signal, trades_all=trades_all
                        )
                        last_rebalance_date = time

            total_value = self._compute_total_value(position, bar)
            holdings_value = total_value - position.cash
            cash_value = position.cash
            weights = {
                code: (qty * bar.close.get(code, 0.0) / total_value) if total_value > 0 else 0.0
                for code, qty in position.quantity.items()
            }
            is_rebalance_day = last_rebalance_date == time
            # 调仓日：用调仓后权重重算波动率，使监控图展示正确的「调仓后预期波动率」
            if is_rebalance_day and len(weights) > 0:
                try:
                    hist = self._data_feed.get_history_window(time)
                    if not hist.empty:
                        w_new = pd.Series(weights)
                        if w_new.abs().sum() > 0:
                            metrics_post = self._strategy.compute_monitoring_metrics(
                                current_weights=w_new, history_prices=hist
                            )
                            vol_post = metrics_post.get("portfolio_volatility")
                            if vol_post is not None:
                                portfolio_vol = vol_post
                                monitoring_metrics["portfolio_volatility"] = vol_post
                except Exception:
                    pass
            snapshots.append(
                PortfolioSnapshot(
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
                )
            )
            last_state = {
                "date": date_str,
                "position": {"quantity": dict(position.quantity), "cash": position.cash},
                "total_value": total_value,
                "weights": weights,
            }

        return (snapshots, trades_all, last_state, stopped_at)

    def _should_rebalance(self, time: pd.Timestamp) -> bool:
        """根据配置判断当前时点是否需要调仓.

        支持六种调仓频率：
        - daily: 每个交易日都调仓
        - weekly: 每周一调仓
        - monthly: 每月第一个交易日调仓
        - month_end: 每月最后一个交易日调仓（与编制规则 step1/step2/trade_dates 一致）
        - quarterly: 每季度第一个交易日调仓
        - yearly: 每年第一个交易日调仓

        编制规则：执行日=月末后第2个交易日，2015-01-05 为元旦后第1个交易日，永不调仓
        """
        if time == pd.Timestamp("2015-01-05"):
            return False
        if self._config.rebalance_freq == "daily":
            return True
        elif self._config.rebalance_freq == "month_end":
            return time in getattr(self, "_month_end_dates_set", set())
        elif self._config.rebalance_freq == "weekly":
            # 每周一调仓（weekday() 返回 0=周一）
            return time.weekday() == 0
        elif self._config.rebalance_freq == "monthly":
            # 每月第一个交易日调仓
            if not hasattr(self, '_last_rebalance_month'):
                self._last_rebalance_month = None
            
            current_month = time.month
            if self._last_rebalance_month != current_month:
                self._last_rebalance_month = current_month
                return True
            return False
        elif self._config.rebalance_freq == "quarterly":
            # 每季度第一个交易日调仓（1月、4月、7月、10月）
            if not hasattr(self, '_last_rebalance_quarter'):
                self._last_rebalance_quarter = None
            
            current_quarter = (time.month - 1) // 3  # 0=Q1, 1=Q2, 2=Q3, 3=Q4
            if self._last_rebalance_quarter != current_quarter:
                self._last_rebalance_quarter = current_quarter
                return True
            return False
        elif self._config.rebalance_freq == "yearly":
            # 每年第一个交易日调仓
            if not hasattr(self, '_last_rebalance_year'):
                self._last_rebalance_year = None
            
            current_year = time.year
            if self._last_rebalance_year != current_year:
                self._last_rebalance_year = current_year
                return True
            return False
        else:
            # 默认每日调仓
            return True
