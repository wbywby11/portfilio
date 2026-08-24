"""组合统一引擎路径语义守卫测试.

P3 退役 composite_engine 后，本文件守卫 run_composite_unified（合成资产 +
PortfolioWeightAllocator + 统一引擎逐日撮合）的核心计算语义，对照独立
解析基准（持仓数量直接模拟）逐位断言。覆盖四种核心口径：

- 固定权重 / 月度 T+1 / 周期内漂移（GMSI2 60/40 口径）
- 固定权重 / 月度 T+1 / 周期内不漂移（每日结算复位）
- 四象限事件驱动（signal_driven，象限切换 T+2）
- 母层波动率 targeting（dual_window_vol return-level）

历史口径说明：旧路径（NAV 级复合）的 eff_weights = w_series.shift(delay)
叠加逐日漂移后，t 日实际使用 t-2 日收盘市值权重，比严格市值漂移滞后一天；
统一引擎路径为严格市值漂移（t-1 日收盘），差异量化见
docs/组合适配统一引擎双跑比对报告.md。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.schedule import ExecutionSchedule, ScheduleResolver
from app.backtesting.synthetic_feed import build_synthetic_prices
from app.portfolio.composite_runner import run_composite_unified
from app.portfolio.weight_models import FixedWeightModel, QuadrantWeightModel


def _make_sub_navs(n: int = 420, seed: int = 42):
    """构造确定性的两路合成子策略 NAV（不同波动水平，便于权重模型区分）."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", periods=n)
    navs = {}
    for i, key in enumerate(["sub_a", "sub_b"]):
        rets = rng.normal(0.0003 + 0.0001 * i, 0.008 + 0.005 * i, size=n)
        navs[key] = pd.Series(1000.0 * np.cumprod(1.0 + rets), index=dates)
    return navs, dates


def _analytic_nav(navs, weights_at_signal, dates, initial_weights, initial_nav=1000.0):
    """独立解析基准：持仓数量直接模拟（市值漂移严格，零成本）.

    信号日收盘按目标权重换仓（权重消费截止信号日 NAV），期间持仓
    数量不变自然漂移；首日收盘按期初权重建仓。与新路径的
    「信号日 = 生效日前一交易日收盘成交」调度口径一致。

    输入价格与引擎同源：使用 build_synthetic_prices 的合成价格
    （首列归一 base，首日收益为 0），保证逐位可比。

    Args:
        weights_at_signal: {信号日: 目标权重 dict}（信号日必须落在 dates 内）
    """
    prices = build_synthetic_prices(navs, base=float(initial_nav))
    keys = list(initial_weights.keys())
    qty = {k: initial_weights[k] * initial_nav / prices[k].iloc[0] for k in keys}
    nav_out = {}
    for i, d in enumerate(dates):
        if i > 0:
            nav = sum(qty[k] * prices[k].iloc[i] for k in keys)
            if d in weights_at_signal:
                tw = weights_at_signal[d]
                qty = {k: tw.get(k, 0.0) * nav / prices[k].iloc[i] for k in keys}
            nav_out[d] = nav
        else:
            nav_out[d] = initial_nav  # 首日收盘建仓，净值不变
    return pd.Series(nav_out)


def _analytic_nav_no_drift(navs, weights, dates, initial_nav=1000.0):
    """独立解析基准：周期内不漂移（每日收盘无成本复位到固定权重）.

    日收益 = Σ_k w_k × 合成资产日收益（权重恒定，收益口径每日复位）。
    """
    prices = build_synthetic_prices(navs, base=float(initial_nav))
    rets = prices.pct_change(fill_method=None).fillna(0.0)
    daily = sum(weights[k] * rets[k] for k in weights)
    nav = initial_nav * (1.0 + daily).cumprod()
    nav.iloc[0] = initial_nav  # 首日收盘建仓，净值不变
    return nav


def _monthly_signal_dates(dates):
    """按月度调度解析信号日（与引擎同源 ScheduleResolver）."""
    sched = ExecutionSchedule(rebalance_freq="monthly", execution_delay=1)
    resolver = ScheduleResolver(sched, list(dates))
    return set(resolver.resolve_signal_dates(dates[0], dates[-1]))


def _compare_nav(ref_nav: pd.Series, new_nav: pd.Series, anchor_pos: int, rtol: float):
    """锚点归一化后比对逐日 NAV（消除期初建仓窗口的固定比例差）."""
    common = ref_nav.index.intersection(new_nav.index)
    assert len(common) > anchor_pos + 10
    ref = ref_nav.reindex(common)
    new = new_nav.reindex(common)
    ref_n = ref / ref.iloc[anchor_pos]
    new_n = new / new.iloc[anchor_pos]
    rel_diff = (new_n - ref_n).abs().max()
    assert rel_diff < rtol, f"锚点后逐日 NAV 最大相对差异 {rel_diff:.2e} 超过容差 {rtol:.1e}"
    return rel_diff


def test_fixed_monthly_drift_matches_analytic():
    """固定权重 / 月度 T+1 / 周期内漂移：与持仓数量模拟逐位一致."""
    navs, dates = _make_sub_navs()
    weights = {"sub_a": 0.6, "sub_b": 0.4}
    sched = ExecutionSchedule(rebalance_freq="monthly", execution_delay=1)

    new = run_composite_unified(
        sub_nav_series=navs, sub_weights=weights, initial_nav=1000.0,
        execution_schedule=sched, weight_drift=True,
    )

    sig_dates = _monthly_signal_dates(dates)
    weights_at_signal = {d: dict(weights) for d in sig_dates if d != dates[0]}
    analytic = _analytic_nav(navs, weights_at_signal, dates, weights)
    _compare_nav(analytic, new.portfolio_nav, anchor_pos=1, rtol=1e-9)


def test_fixed_monthly_no_drift_matches_analytic():
    """固定权重 / 月度 T+1 / 周期内不漂移：每日结算复位语义逐位一致."""
    navs, dates = _make_sub_navs()
    weights = {"sub_a": 0.6, "sub_b": 0.4}
    sched = ExecutionSchedule(rebalance_freq="monthly", execution_delay=1)

    new = run_composite_unified(
        sub_nav_series=navs, sub_weights=weights, initial_nav=1000.0,
        execution_schedule=sched, weight_drift=False,
    )
    analytic = _analytic_nav_no_drift(navs, weights, dates)
    _compare_nav(analytic, new.portfolio_nav, anchor_pos=1, rtol=1e-9)


def _make_quadrant_components(navs, dates):
    """构造四象限模型（缩短窗口便于测试）+ 事件信号."""
    rng = np.random.default_rng(7)
    sig_dates = pd.bdate_range(dates[0] - pd.Timedelta(days=600), dates[-1])
    sig_ret = rng.normal(0.0, 0.012, size=len(sig_dates))
    signal_prices = pd.Series(100.0 * np.cumprod(1.0 + sig_ret), index=sig_dates)

    model = QuadrantWeightModel(
        signal_prices=signal_prices,
        rebalance_mode="signal_driven",
        vol_window=60,
        sma_window=20,
        hv_window=10,
        vol_percentile_window=60,
        quadrant_strategy_map={
            "up_low_vol": "sub_a",
            "up_high_vol": "sub_b",
            "down_low_vol": "sub_b",
            "down_high_vol": "sub_a",
        },
    )
    return model


def test_quadrant_signal_driven_matches_analytic():
    """四象限事件驱动（象限切换 T+2）：与持仓数量模拟逐位一致.

    事件日 d 的目标权重消费截止 d 的 NAV，经 T+2 在 d+2 生效，
    成交日为 d+1 收盘（signal_calendar 口径）；解析基准按此复现。
    首日事件由 config.initial_weights 期初建仓承载，不重复声明。
    """
    navs, dates = _make_sub_navs()
    weights = {"sub_a": 0.5, "sub_b": 0.5}
    model = _make_quadrant_components(navs, dates)
    rebalance_signal = model.get_quadrant_series()
    sched = ExecutionSchedule(rebalance_freq="daily", execution_delay=2)

    new = run_composite_unified(
        sub_nav_series=navs, sub_weights=weights, initial_nav=1000.0,
        execution_schedule=sched, weight_model=model,
        rebalance_signal=rebalance_signal, weight_drift=True,
    )

    # 事件驱动路径必须真实发生调仓
    assert len(new.rebalance_dates) > 3, "新路径未产生事件调仓"

    # 事件日 d 取权重（NAV 截止 d），d+1 收盘换仓
    sig = rebalance_signal.reindex(dates).ffill()
    changed = sig != sig.shift(1)
    changed.iloc[0] = not pd.isna(sig.iloc[0])
    event_days = [dates[i] for i in range(len(dates)) if bool(changed.iloc[i])]
    init_w0 = model.compute_weights(navs, dates[0]) if event_days and event_days[0] == dates[0] else weights
    weights_at_signal = {}
    pos = {d: i for i, d in enumerate(dates)}
    for d in event_days:
        if d == dates[0]:
            continue  # 首日事件由期初建仓承载
        i = pos[d]
        if i + 1 >= len(dates):
            continue
        tw = model.compute_weights({k: navs[k].loc[:d] for k in weights}, d)
        weights_at_signal[dates[i + 1]] = {k: float(tw.get(k, 0.0)) for k in weights}
    analytic = _analytic_nav(
        navs, weights_at_signal, dates,
        {k: float(init_w0.get(k, weights[k])) for k in weights},
    )
    _compare_nav(analytic, new.portfolio_nav, anchor_pos=3, rtol=1e-9)


def test_mother_vol_targeting_semantics():
    """母层波动率 targeting：return-level 定标将组合波动压向目标值.

    引擎在收益层逐日缩放（等价 leverage.shift(1) 作用于当日收益），
    预热窗口（≥10 个已实现收益）之后定标生效。断言：
    1. 控制后波动显著低于无控制路径（目标 0.08 低于子策略自然波动）；
    2. 控制后年化波动落在目标的合理邻域内（定标为逐日近似，非精确锁定）。
    """
    navs, _ = _make_sub_navs()
    weights = {"sub_a": 0.6, "sub_b": 0.4}
    sched = ExecutionSchedule(rebalance_freq="monthly", execution_delay=1)

    target = 0.08
    controlled = run_composite_unified(
        sub_nav_series=navs, sub_weights=weights, initial_nav=1000.0,
        execution_schedule=sched, weight_drift=True,
        mother_vol_target=target, mother_vol_short=20, mother_vol_long=60,
        mother_vol_method="rolling",
    )
    uncontrolled = run_composite_unified(
        sub_nav_series=navs, sub_weights=weights, initial_nav=1000.0,
        execution_schedule=sched, weight_drift=True,
    )

    warmup = 30
    vol_c = float(controlled.portfolio_returns.iloc[warmup:].std() * np.sqrt(252))
    vol_u = float(uncontrolled.portfolio_returns.iloc[warmup:].std() * np.sqrt(252))
    assert vol_u > target, "测试数据自然波动低于目标，无法验证压制效果"
    assert vol_c < vol_u, "波动率控制未降低组合波动"
    assert 0.5 * target < vol_c < 2.0 * target, (
        f"控制后年化波动 {vol_c:.4f} 偏离目标 {target} 过远"
    )


def test_composite_unified_result_structure():
    """输出结构完备（供调用方消费：NAV/权重/贡献/绩效/调仓日）."""
    navs, _ = _make_sub_navs(n=120)
    weights = {"sub_a": 0.5, "sub_b": 0.5}
    result = run_composite_unified(
        sub_nav_series=navs, sub_weights=weights, initial_nav=1000.0,
        weight_model=FixedWeightModel(weights),
        execution_schedule=ExecutionSchedule(rebalance_freq="monthly", execution_delay=1),
    )
    assert not result.portfolio_nav.empty
    assert set(result.sub_navs.keys()) == set(weights.keys())
    assert not result.weight_history.empty
    assert list(result.weight_history.columns) == list(weights.keys())
    assert not result.sub_contributions.empty
    assert result.performance is not None
    assert len(result.rebalance_dates) > 0
    # 组合收益与贡献可加性（近似：贡献按 T-1 收盘权重口径）
    contrib_sum = result.sub_contributions.sum(axis=1)
    diff = (contrib_sum - result.portfolio_returns).abs().iloc[2:].max()
    assert diff < 1e-6, f"贡献矩阵与组合收益不可加，最大差 {diff:.2e}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
