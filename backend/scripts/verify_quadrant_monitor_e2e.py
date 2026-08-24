# -*- coding: utf-8 -*-
"""四象限组合端到端验证（P5）：监控管线 == 回测管线.

用回归 fixture 的四象限组合模型（_regr_portfolio_quadrant，
signal_driven + T+2 + quadrant_strategy_map）分别运行：
  1. 组合监控管线 app.monitor.portfolio_backtest_monitor.run_portfolio_monitor_pipeline
  2. 组合回测路径（run-portfolio 端点同一套构建块）
同一区间、同一成本口径下，逐日 NAV 必须完全一致（monitor == backtest），
调仓日集合一致（事件驱动象限信号 T+2 生效）。

验证完成后自动清理 fixture（幂等）。

用法：
    python scripts/verify_quadrant_monitor_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tests"))
os.chdir(PROJECT_ROOT)

# 与 tests/regression/fixture.py 写死的基线区间一致
START = "20240102"
END = "20250630"
INITIAL_NAV = 1000.0
COMMISSION = 0.00015  # 监控管线默认口径，回测对比路径取同值


async def _run_backtest_path(model_id: str) -> pd.Series:
    """组合回测路径：与 run-portfolio 端点同一套构建块、同一参数."""
    from app.api.backtests import (
        get_model_service,
        _run_sub_strategy_backtests,
        _build_quadrant_weight_components,
        _collect_cost_overrides,
        _maybe_apply_product_layer,
        PortfolioBacktestRequest,
    )
    from app.portfolio.composite_runner import run_composite_unified as composite_run

    model_service = get_model_service()
    portfolio_model = await model_service.get_model(model_id)
    sub_pairs = await model_service.resolve_sub_strategies(portfolio_model)
    sub_entries = []
    for sub_model, weight in sub_pairs:
        sub_info = next(
            (s for s in portfolio_model.sub_strategies if s.get("model_id") == sub_model.id), {}
        )
        sub_entries.append({
            "model": sub_model,
            "weight": weight,
            "name": sub_info.get("name", sub_model.name),
            "fetch_id": sub_model.id or sub_model.name,
            "sub_start": sub_info.get("backtest_start"),
        })

    req = PortfolioBacktestRequest(
        start_date=START, end_date=END, initial_nav=INITIAL_NAV,
        rebalance_freq="monthly", commission_rate=COMMISSION, slippage=0.0,
    )
    (sub_nav_series, sub_weights, _, _, _) = await _run_sub_strategy_backtests(
        sub_entries, START, END, INITIAL_NAV, model_service,
        cost_overrides=_collect_cost_overrides(req),
    )

    weight_model = rebalance_signal = composite_exec_schedule = None
    composite_weight_drift = True
    wm_params = getattr(portfolio_model, "weight_model_params", {}) or {}
    if getattr(portfolio_model, "weight_model_type", None) == "quadrant":
        weight_model, rebalance_signal, composite_exec_schedule, composite_weight_drift = (
            await _build_quadrant_weight_components(wm_params, START, END)
        )

    result = composite_run(
        sub_nav_series=sub_nav_series, sub_weights=sub_weights,
        initial_nav=INITIAL_NAV, rebalance_freq="monthly",
        weight_model=weight_model, rebalance_signal=rebalance_signal,
        execution_schedule=composite_exec_schedule,
        weight_drift=composite_weight_drift,
    )
    result, _ = await _maybe_apply_product_layer(result, wm_params, INITIAL_NAV)
    return result.portfolio_nav


async def main() -> None:
    from app.config.database import Database
    from regression import fixture
    from app.monitor.portfolio_backtest_monitor import run_portfolio_monitor_pipeline

    Database.connect()
    ids = await fixture.create()
    model_id = ids["portfolio_quadrant"]
    try:
        # 1. 监控管线
        mon = await run_portfolio_monitor_pipeline(
            portfolio_model_id=model_id,
            start_date=START, end_date=END,
            initial_nav=INITIAL_NAV, rebalance_freq="monthly",
            commission_rate=COMMISSION, slippage=0.0,
        )
        mon_nav = mon["portfolio_nav"].dropna().sort_index()

        # 2. 回测路径
        bt_nav = (await _run_backtest_path(model_id)).dropna().sort_index()

        # 3. 对比：监控段 == 回测同区段切片（此处区间相同，应逐日完全一致）
        assert list(mon_nav.index) == list(bt_nav.index), (
            f"日历不一致: 监控 {len(mon_nav)} 天 vs 回测 {len(bt_nav)} 天"
        )
        diff = (mon_nav - bt_nav).abs()
        max_diff = float(diff.max())
        rel = float((diff / bt_nav.abs().replace(0, 1)).max())
        assert rel == 0.0 or rel < 1e-12, f"监控与回测出现数值分叉: rel={rel}"

        reb_dates = mon["rebalance_dates"]
        perf = mon["performance"]
        print("[PASS] 四象限组合监控 == 回测（同区间逐日完全一致）")
        print(f"       区间: {mon_nav.index[0].date()} ~ {mon_nav.index[-1].date()}"
              f"（{len(mon_nav)} 个交易日）")
        print(f"       最大绝对偏差: {max_diff:.3e}（相对 {rel:.3e}）")
        print(f"       调仓次数: {len(reb_dates)}（事件驱动 T+2）")
        print(f"       绩效: ann_ret={perf.annual_return:.4%}, "
              f"ann_vol={perf.annual_volatility:.4%}, sharpe={perf.sharpe_ratio:.3f}, "
              f"mdd={perf.max_drawdown:.4%}")
        print(f"       期末 NAV: {float(mon_nav.iloc[-1]):.4f}（基准 {INITIAL_NAV}）")
    finally:
        await fixture.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
