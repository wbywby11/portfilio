# -*- coding: utf-8 -*-
"""
分段计时：混合动量全链路回测 vs 监控侧月度预计算，用于定位耗时环节。
运行:  cd portfilio-end && python scripts/benchmark_backtest_phases.py
"""
from __future__ import annotations

import cProfile
import io
import logging
import pstats
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# 项目根
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.getLogger().setLevel(logging.WARNING)
try:
    from loguru import logger as _loguru_logger
    _loguru_logger.remove()
except Exception:
    pass


def _fake_prices(n_days: int = 3500, n_assets: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    dates = pd.date_range("2010-01-01", periods=n_days, freq="B")
    rets = rng.normal(0, 0.01, size=(n_days, n_assets))
    levels = np.exp(np.cumsum(rets, axis=0))
    cols = [f"A{i:02d}" for i in range(n_assets)]
    return pd.DataFrame(levels, index=dates, columns=cols)


def bench_hybrid_momentum_cprofile(prices: pd.DataFrame) -> None:
    from app.backtesting.hybrid_momentum_engine import (
        HybridMomentumConfig,
        run_hybrid_momentum_backtest,
    )

    cfg = HybridMomentumConfig(
        base_date=pd.Timestamp("2014-02-10"),
        selection_start_date=pd.Timestamp("2014-01-31"),
        min_history_days=260,
        top_momentum=7,
    )
    pr = cProfile.Profile()
    pr.enable()
    t0 = time.perf_counter()
    run_hybrid_momentum_backtest(prices, cfg)
    wall = time.perf_counter() - t0
    pr.disable()
    print(f"\n=== 混合动量 run_hybrid_momentum_backtest 墙钟 {wall:.2f}s ===")
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats(pstats.SortKey.CUMULATIVE).print_stats(35)
    print(s.getvalue())


def bench_hybrid_step12_only(prices: pd.DataFrame) -> None:
    """仅 step1+step2 循环（与 hybrid_momentum_engine 内层一致）。"""
    from app.selection.engine_reference import calc_weights_for_date, select_assets_for_date

    selection_start = pd.Timestamp("2014-01-31")
    prices_for_calc = prices[prices.index >= selection_start]
    raw = prices_for_calc.groupby(prices_for_calc.index.to_period("M")).apply(
        lambda x: x.index[-1]
    )
    calc_dates_list = raw.tolist() if hasattr(raw, "tolist") else [raw]
    calc_dates_list = [d for d in calc_dates_list if pd.Timestamp(d) >= selection_start]

    t0 = time.perf_counter()
    n_ok = 0
    for calc_date in calc_dates_list:
        try:
            date_idx = prices.index.get_loc(calc_date)
        except (KeyError, TypeError):
            continue
        if date_idx < 260:
            continue
        nav = prices.iloc[: date_idx + 1]
        sel = select_assets_for_date(
            nav=nav,
            date_idx=date_idx,
            calc_date=pd.Timestamp(calc_date),
            min_history=260,
            top_momentum=7,
        )
        selection_row = sel.get("入选矩阵_row", {})
        if not sel.get("最终入选"):
            continue
        calc_weights_for_date(
            nav=nav,
            date_idx=date_idx,
            selection_row=selection_row,
            all_assets=list(prices.columns),
            target_vol=0.05,
            max_leverage=4.0,
            weight_caps={c: 0.1 for c in prices.columns},
            fillna_zero=False,
        )
        n_ok += 1
    elapsed = time.perf_counter() - t0
    print(
        f"\n=== 仅 step1+step2 月度循环: {len(calc_dates_list)} 个计算日, "
        f"有效权重 {n_ok} 次, 耗时 {elapsed:.2f}s ==="
    )


def bench_monitor_monthly_map(prices: pd.DataFrame) -> None:
    """监控 _build_monthly_rebalance_map 等价：每月 run_asset_selection + run_weight_calculation。"""
    from app.monitor import config as mcfg
    from app.monitor.strategy_engine import StrategyEngine

    engine = StrategyEngine()
    trade_dates = prices.index.tolist()
    month_end_dates = []
    ds = pd.Series(prices.index, index=prices.index)
    for (_, _), group in ds.groupby([ds.index.year, ds.index.month]):
        month_end_dates.append(group.index[-1])
    month_end_dates.sort()

    t0 = time.perf_counter()
    for calc_date in month_end_dates:
        try:
            sel = engine.run_asset_selection(prices, calc_date, rt=None)
            engine.run_weight_calculation(prices, sel, calc_date, rt=None)
        except Exception:
            pass
    elapsed = time.perf_counter() - t0
    print(
        f"\n=== 监控引擎 月度×2 (selection+weight, rt=None): "
        f"{len(month_end_dates)} 月, 耗时 {elapsed:.2f}s ==="
    )


def main() -> None:
    prices = _fake_prices(3500, 12)
    print(f"模拟行情: {prices.shape[0]} 行 × {prices.shape[1]} 列")
    bench_hybrid_step12_only(prices)
    bench_monitor_monthly_map(prices)
    bench_hybrid_momentum_cprofile(prices)


if __name__ == "__main__":
    main()
