# -*- coding: utf-8 -*-
"""组合层第二段引擎运行：统一引擎路径的组合回测编排.

将多个子策略 NAV 在**统一引擎内逐日撮合**形成组合（替代 composite_engine
的 NAV 级复合）：
  1. 各子策略 NAV 折算为合成资产价格矩阵（app.backtesting.synthetic_feed）；
  2. 组合权重模型经 PortfolioWeightAllocator 适配为引擎 allocator；
  3. 合成资产 + allocator 构成 CompositionPipeline，经 runner.run_unified
     由同一个 BacktestEngine 逐日推进——与单策略回测共用调度/撮合/风控逻辑。

入参签名与 composite_engine.run_portfolio_backtest 保持一致（成本参数除外），
便于双跑比对与调用方切换。返回相同的 PortfolioBacktestResult 结构。

与旧路径的可解释差异（双跑报告量化）：
- 期初口径窗口：旧路径 eff_weights.shift(delay).fillna(初始权重)，前 delay 日
  按初始配置权重计收益；新路径首日收盘按期初权重建仓、次日起承接收益。
- 组合层成本：旧路径零成本；新路径可配置 commission_rate/slippage（默认 0）。
- 权重快照口径：weight_drift=False 时新路径快照权重为市值漂移后的展示值，
  收益口径仍经每日结算复位保持恒定。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from app.analysis.performance import DEFAULT_RISK_FREE_RATE
from app.backtesting import RunSpec, run_unified
from app.backtesting.analytics import PerformanceAnalyzer, PerformanceSummary
from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.schedule import ExecutionSchedule, ScheduleResolver
from app.backtesting.synthetic_feed import build_synthetic_prices
from app.backtesting.types import PortfolioSnapshot
from app.portfolio.weight_models import (
    FixedWeightModel,
    PortfolioWeightAllocator,
    PortfolioWeightModel,
)

logger = logging.getLogger(__name__)


@dataclass
class PortfolioBacktestResult:
    """投资组合回测结果"""

    # 投资组合 NAV（起始=initial_nav）
    portfolio_nav: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    # 各子策略 NAV（各自起始=initial_nav）
    sub_navs: Dict[str, pd.Series] = field(default_factory=dict)

    # 投资组合日收益率
    portfolio_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    # 各子策略日收益率
    sub_returns: Dict[str, pd.Series] = field(default_factory=dict)

    # 投资组合绩效
    performance: Optional[PerformanceSummary] = None

    # 各子策略绩效
    sub_performances: Dict[str, PerformanceSummary] = field(default_factory=dict)

    # 权重历史
    weight_history: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())

    # 逐日收益贡献矩阵（index=日期, columns=子策略）
    # 供 portfolio_analytics 做可加性闭合的收益归因。
    sub_contributions: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())

    # 子策略交易记录（带策略名称标签）
    trades: List[Dict[str, Any]] = field(default_factory=list)

    # 再平衡日期列表
    rebalance_dates: List[Any] = field(default_factory=list)


def _performance_from_nav(
    nav: pd.Series,
    analyzer: PerformanceAnalyzer,
    rebalance_dates: Optional[List[Any]] = None,
) -> PerformanceSummary:
    """从 NAV 序列构造 PortfolioSnapshot，统一调用 PerformanceAnalyzer.from_results.

    确保组合路径与 BacktestEngine 走同一条绩效计算路径（统一内核
    app.analysis.performance），年化因子、夏普与回撤口径完全一致。

    rebalance_dates : 调仓日列表（pd.Timestamp），用于标记快照的 is_rebalance_day，
    使 PerformanceAnalyzer 能基于调仓周期收益正确计算胜率；不传则胜率为 0。
    """
    if nav is None or nav.empty:
        return PerformanceSummary(
            total_return=0.0, annual_return=0.0, volatility=0.0,
            annual_volatility=0.0, max_drawdown=0.0, sharpe_ratio=0.0,
            calmar_ratio=0.0, return_drawdown_ratio=0.0, win_rate=0.0,
        )

    rebal_set = set()
    if rebalance_dates:
        for d in rebalance_dates:
            try:
                rebal_set.add(pd.Timestamp(d).normalize())
            except Exception:
                continue

    snapshots = [
        PortfolioSnapshot(
            time=t,
            total_value=float(v),
            cash=0.0,
            holdings_value=float(v),
            weights={},
            is_rebalance_day=(pd.Timestamp(t).normalize() in rebal_set) if rebal_set else False,
        )
        for t, v in nav.items()
    ]
    return analyzer.from_results(snapshots)


def run_composite_unified(
    sub_nav_series: Dict[str, pd.Series],
    sub_weights: Dict[str, float],
    initial_nav: float = 1000.0,
    rebalance_freq: str = "monthly",
    mother_vol_target: Optional[float] = None,
    mother_vol_short: int = 20,
    mother_vol_long: int = 60,
    mother_vol_method: str = "rolling",
    mother_annualize_factor: Optional[float] = None,
    mother_leverage_min: Optional[float] = None,
    mother_leverage_max: Optional[float] = None,
    execution_schedule: Optional[ExecutionSchedule] = None,
    weight_model: Optional[PortfolioWeightModel] = None,
    rebalance_signal: Optional[pd.Series] = None,
    weight_drift: bool = True,
    commission_rate: float = 0.0,
    slippage: float = 0.0,
) -> PortfolioBacktestResult:
    """统一引擎路径的组合回测（composite_engine.run_portfolio_backtest 的替代）.

    参数语义与 run_portfolio_backtest 一致，另增：
    commission_rate / slippage: 组合层交易成本（默认 0，与旧路径零成本可比）。
    """
    if not sub_nav_series:
        raise ValueError("sub_nav_series 为空，无法构建投资组合")

    total_w = sum(sub_weights.values())
    if total_w <= 0:
        raise ValueError(f"sub_weights 总和无效: {total_w}")
    norm_weights = {k: v / total_w for k, v in sub_weights.items()}
    keys = list(sub_weights.keys())

    # 1. 合成资产价格矩阵（日期并集 + ffill/bfill，与旧路径对齐）
    prices = build_synthetic_prices(sub_nav_series, base=float(initial_nav))
    dates = prices.index

    # 2. 调度口径：与旧路径相同的原始调度（周期默认 T+1，事件默认 T+2）
    if execution_schedule is not None:
        raw_sched = execution_schedule
    else:
        default_delay = 2 if rebalance_signal is not None else 1
        raw_sched = ExecutionSchedule(
            rebalance_freq=rebalance_freq, execution_delay=default_delay
        )
    exec_delay = int(raw_sched.execution_delay)

    # 3. 权重模型
    if weight_model is None:
        weight_model = FixedWeightModel(norm_weights)

    # 4. 期初建仓权重（对齐旧路径首日口径）：
    #    首日为再平衡日 → 取权重模型目标权重；否则用配置权重
    if rebalance_signal is not None:
        sig0 = rebalance_signal.reindex(dates).ffill()
        rebal_day0 = bool(len(sig0) and sig0.iloc[0] is not None and not pd.isna(sig0.iloc[0]))
    else:
        resolver0 = ScheduleResolver(raw_sched, list(dates))
        rebal_day0 = dates[0] in set(resolver0.resolve_signal_dates(dates[0], dates[-1]))
    if rebal_day0:
        target_w0 = weight_model.compute_weights(sub_nav_series, dates[0])
        initial_weights = {
            k: float(target_w0.get(k, norm_weights.get(k, 0.0))) for k in keys
        }
    else:
        initial_weights = dict(norm_weights)

    # 5. 引擎配置：合成资产为标的，首日按期初权重建仓
    config = BacktestConfig(
        name="composite_unified",
        thscodes=keys,
        start_date=dates[0].strftime("%Y%m%d"),
        end_date=dates[-1].strftime("%Y%m%d"),
        rebalance_freq="monthly",  # 实际调度由 allocator 声明接管
        initial_cash=float(initial_nav),
        initial_nav=float(initial_nav),
        commission_rate=float(commission_rate),
        slippage=float(slippage),
        initial_weights=initial_weights,
    )

    # 6. allocator 适配器 + 三层编排配置
    allocator = PortfolioWeightAllocator(
        weight_model=weight_model,
        sub_keys=keys,
        prices_matrix=prices,
        rebalance_freq=raw_sched.rebalance_freq,
        execution_delay=exec_delay,
        event_signal=rebalance_signal,
        weight_drift=weight_drift,
        initial_weights=initial_weights,
    )
    composition: Dict[str, Any] = {
        "selector": None,
        "allocator": "portfolio_weight",
        "controller": None,
    }
    strategy_params: Dict[str, Any] = {}

    # 7. 母层波动率定标 → 策略参数 vol_targeting_*（引擎收益层逐日缩放，
    #    等价旧路径 contrib × leverage.shift(1)），不经过控制器层
    if mother_vol_target is not None and mother_vol_target > 0:
        from app.analysis.performance import PERIODS_PER_YEAR

        strategy_params.update({
            "vol_targeting_enabled": True,
            "vol_targeting_target": float(mother_vol_target),
            "vol_targeting_short_window": int(mother_vol_short or 20),
            "vol_targeting_long_window": int(mother_vol_long or 60),
            "vol_targeting_annualization": int(mother_annualize_factor or PERIODS_PER_YEAR),
            "vol_targeting_method": str(mother_vol_method or "rolling").lower(),
            "vol_targeting_leverage_min": float(mother_leverage_min) if mother_leverage_min is not None else 0.1,
            "vol_targeting_leverage_max": float(mother_leverage_max) if mother_leverage_max is not None else 5.0,
        })

    # 8. 第二段引擎运行（唯一入口 runner.run_unified）
    feed = DataFeed(prices=prices, config=config, strategy_prices=prices)
    result = run_unified(RunSpec(
        config=config,
        data_feed=feed,
        allocator=allocator,
        composition=composition,
        strategy_params=strategy_params,
        thscodes=keys,
    ))

    # 9. 结果聚合为 PortfolioBacktestResult（与旧路径同结构）
    return _aggregate_result(
        result=result,
        prices=prices,
        keys=keys,
        initial_nav=float(initial_nav),
        initial_weights=initial_weights,
    )


def _aggregate_result(
    result,
    prices: pd.DataFrame,
    keys: List[str],
    initial_nav: float,
    initial_weights: Dict[str, float],
) -> PortfolioBacktestResult:
    """引擎快照/成交 → PortfolioBacktestResult（字段与旧路径对齐）."""
    idx = pd.DatetimeIndex([s.time for s in result.snapshots])
    portfolio_nav = pd.Series(
        [float(s.total_value) for s in result.snapshots], index=idx, name="portfolio_nav"
    )
    portfolio_returns = portfolio_nav.pct_change(fill_method=None).fillna(0.0)

    # 权重历史：快照实际权重（市值口径）
    weight_history = pd.DataFrame(
        [{k: float((s.weights or {}).get(k, 0.0)) for k in keys} for s in result.snapshots],
        index=idx,
    )

    # 收益贡献（近似口径）：T 日生效权重 ≈ T-1 日收盘权重 × T 日合成资产收益；
    # 母层杠杆经 return-level 定标内嵌于持仓，已体现在市值权重中。
    # portfolio_analytics 归因输入即此序列（可加性闭合）。
    eff_weights = weight_history.shift(1)
    for k in keys:
        eff_weights[k] = eff_weights[k].fillna(float(initial_weights.get(k, 0.0)))
    sub_returns_df = prices.pct_change(fill_method=None).fillna(0.0)
    sub_contributions = eff_weights * sub_returns_df.reindex(idx).fillna(0.0)

    rebalance_dates = [s.time for s in result.snapshots if s.is_rebalance_day]

    analyzer = PerformanceAnalyzer(risk_free_rate=DEFAULT_RISK_FREE_RATE)
    portfolio_perf = _performance_from_nav(portfolio_nav, analyzer, rebalance_dates)
    sub_perfs = {
        k: _performance_from_nav(prices[k], analyzer) for k in keys
    }

    return PortfolioBacktestResult(
        portfolio_nav=portfolio_nav,
        sub_navs={k: prices[k] for k in keys},
        portfolio_returns=portfolio_returns,
        sub_returns={k: sub_returns_df[k] for k in keys},
        performance=portfolio_perf,
        sub_performances=sub_perfs,
        weight_history=weight_history,
        sub_contributions=sub_contributions,
        rebalance_dates=rebalance_dates,
    )
