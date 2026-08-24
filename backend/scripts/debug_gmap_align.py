# -*- coding: utf-8 -*-
"""临时调试：GMAP 逐日对齐诊断

对比维度：
  1. 逐日收益：系统回测 vs 原型 portfolio_returns_
  2. 未缩放权重：系统快照权重归一化 vs 原型 final_weights_
  3. 隐含杠杆：系统快照权重之和 vs 原型 leverage.shift(1)
目的：定位 GMAP corr~0.93 的差异来源（选股/权重/时序/杠杆）。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.database import Database  # noqa: E402
from app.models.strategy_model import StrategyModel  # noqa: E402

GMAP_NAME = "GMSI2-GMAP 商品动量策略"
PROTO_ROOT = Path("d:/project/portfilio/gmsi2_replication")


def load_proto_prices() -> pd.DataFrame:
    frames = {}
    for f in sorted((PROTO_ROOT / "data" / "gmap_adj").glob("*.csv")):
        df = pd.read_csv(f)
        frames[f.stem.upper()] = pd.Series(df["settle"].values, index=pd.to_datetime(df["trade_date"]))
    return pd.DataFrame(frames).sort_index()


async def main() -> None:
    Database.connect()
    from app.services.strategy_model_service import StrategyModelService, build_backtest_params
    from app.backtesting.composition_builder import build_strategy_composition
    from app.backtesting.composition_pipeline import CompositionPipeline
    from app.backtesting.config import BacktestConfig
    from app.backtesting.data_feed import DataFeed
    from app.backtesting.engine import BacktestEngine
    from app.backtesting.risk import RiskManager
    from app.backtesting.execution import ExecutionEngine
    from app.allocation.services.registry import create_strategy_service_from_database
    from app.services.market_service import MarketService
    from app.portfolio.portfolio_service import _build_risk_config_from_params

    svc = StrategyModelService()
    doc = await svc.collection.find_one({"name": GMAP_NAME})
    doc["_id"] = str(doc["_id"])
    model = StrategyModel(**doc)
    print("模型 parameters:", doc.get("parameters"))
    strategy_params = build_backtest_params(model, model_data=doc)
    print("strategy_params execution_delay:", strategy_params.get("execution_delay"))
    spec = build_strategy_composition(model.template_code, model.asset_codes, strategy_params)

    config = BacktestConfig(
        name="dbg_gmap", thscodes=model.asset_codes,
        start_date="20140103", end_date="20260610",
        rebalance_freq=model.rebalance_frequency or "monthly",
        initial_cash=10_000_000, commission_rate=0.0, slippage=0.0,
    )
    ms = MarketService()
    data_feed = await DataFeed.from_market_service(ms, config, lookback_days=500)
    strategy_service = await create_strategy_service_from_database(ms)
    strategy_cls = strategy_service.get_strategy_class(model.template_code)
    strategy = CompositionPipeline(
        allocator=strategy_cls(), thscodes=model.asset_codes,
        composition=spec.composition, strategy_params=strategy_params,
    )
    print("pipeline schedule:", strategy.get_execution_schedule())
    engine = BacktestEngine(
        config=config, data_feed=data_feed, strategy=strategy,
        risk_manager=RiskManager(_build_risk_config_from_params(strategy_params)),
        execution_engine=ExecutionEngine(config),
    )
    result = engine.run()
    sys_nav = pd.Series({s.time: s.total_value for s in result.snapshots}).sort_index()
    sys_ret = sys_nav.pct_change(fill_method=None)
    sys_w = pd.DataFrame({s.time: pd.Series(s.weights) for s in result.snapshots}).T.sort_index().fillna(0.0)
    sys_lev = sys_w.sum(axis=1)
    sys_unscaled = sys_w.div(sys_lev.replace(0, np.nan), axis=0).fillna(0.0)
    print("系统快照:", sys_w.shape)

    # ── 原型 ──
    sys.path.insert(0, str(PROTO_ROOT))
    from gmsi2.gmap import GMAP
    proto_prices = load_proto_prices()
    proto = GMAP(
        target_vol=0.03, momentum_window=20, top_n=8, vol_window=60,
        vc_short_window=20, vc_long_window=60, single_asset_cap=0.30,
        vol_method="ewma", vol_combine="arithmetic",
        trade_dates_file=str(PROTO_ROOT / "data" / "trade_dates.xlsx"),
    )
    proto.run(proto_prices)
    proto_ret = proto.portfolio_returns_
    proto_w = proto.final_weights_

    # 原型杠杆路径（复算）
    from gmsi2.data import compute_vol, combine_vol
    raw_ret = (proto_w * proto_prices.pct_change(fill_method=None).iloc[1:]).sum(axis=1).dropna()
    vs = compute_vol(raw_ret, method="ewma", window=20)
    vl = compute_vol(raw_ret, method="ewma", window=60)
    ve = combine_vol(vs, vl, method="arithmetic")
    proto_lev = np.clip(0.03 / ve.replace(0, np.nan).fillna(0.03), 0.1, 5.0).shift(1).fillna(1.0)

    # ── 1. 逐日收益对比 ──
    common = sys_ret.dropna().index.intersection(proto_ret.dropna().index)
    rs, rp = sys_ret.loc[common], proto_ret.loc[common]
    d = (rs - rp).abs().sort_values(ascending=False)
    corr = float(np.corrcoef(rs.values, rp.values)[0, 1])
    print(f"\n日收益 corr={corr:.4f}，差异最大 top20:")
    for dt in d.head(20).index:
        print(f"  {dt.date()}  sys={rs[dt]*100:+.4f}%  proto={rp[dt]*100:+.4f}%  Δ={d[dt]*100:.4f}%")

    # ── 2. 未缩放权重对比 ──
    cw = common
    sw = sys_unscaled.loc[cw].reindex(columns=proto_w.columns).fillna(0.0)
    pw = proto_w.loc[cw].fillna(0.0)
    wdiff = (sw - pw).abs().max(axis=1)
    bad_w = wdiff[wdiff > 0.01].sort_values(ascending=False)
    print(f"\n未缩放权重 max|Δw|>0.01 的天数: {len(bad_w)} / {len(cw)}")
    for dt in bad_w.head(15).index:
        row = (sw.loc[dt] - pw.loc[dt]).abs().sort_values(ascending=False).head(3)
        detail = " ".join(f"{c}:{sw.loc[dt, c]:.3f}/{pw.loc[dt, c]:.3f}" for c in row.index)
        print(f"  {dt.date()} maxΔ={wdiff[dt]:.3f} | {detail}")

    # ── 3. 杠杆对比 ──
    sl = sys_lev.loc[cw]
    pl = proto_lev.reindex(cw)
    lev_diff = (sl - pl).abs()
    lcorr = float(np.corrcoef(sl.values, pl.fillna(1.0).values)[0, 1])
    print(f"\n隐含杠杆 corr={lcorr:.4f}  mean|Δlev|={lev_diff.mean():.4f}  max={lev_diff.max():.4f}")
    worst_lev = lev_diff.sort_values(ascending=False).head(10)
    for dt in worst_lev.index:
        print(f"  {dt.date()}  sys_lev={sl[dt]:.3f}  proto_lev={pl[dt]:.3f}")

    # ── 4. 调仓日检查：每月权重切换时点 ──
    print("\n月切换时点（系统权重发生变化的日期 vs 原型）:")
    sys_change = sys_unscaled.diff().abs().sum(axis=1)
    proto_change = proto_w.diff().abs().sum(axis=1)
    sc_dates = sys_change[sys_change > 0.01].index
    pc_dates = proto_change[proto_change > 0.01].index
    print(f"  系统切换日 {len(sc_dates)} 个: {[str(x.date()) for x in sc_dates[:8]]} ...")
    print(f"  原型切换日 {len(pc_dates)} 个: {[str(x.date()) for x in pc_dates[:8]]} ...")

    # ── 5. 月末信号日动量选股对比（定位选股反转根因）──
    returns = proto_prices.pct_change(fill_method=None)
    proto_mom = returns.rolling(20, min_periods=20).apply(lambda x: np.prod(1 + x) - 1)
    idx = proto_prices.index
    ym = pd.Series(idx, index=idx).groupby([idx.year, idx.month]).last()
    month_ends = [pd.Timestamp(d) for d in ym.values if 2019 <= pd.Timestamp(d).year <= 2020]
    from app.selection import create_selector
    selector = create_selector("cross_sectional_momentum")
    n_flip = 0
    for me in month_ends:
        if me not in proto_mom.index:
            continue
        p_row = proto_mom.loc[me].dropna()
        p_top = set(p_row.sort_values(ascending=False).index[:8])
        # 系统选择器：用截至信号日的历史（prev_close 口径）
        hist = proto_prices.loc[:me]
        res = selector.select(hist, 8, momentum_window=20)
        s_top = set(res.selected_assets)
        if p_top != s_top:
            n_flip += 1
            print(f"\n[选股分歧] {me.date()}: proto={sorted(p_top)} sys={sorted(s_top)}")
            for c in sorted(p_top ^ s_top):
                pv = p_row.get(c, float("nan"))
                sv = res.scores.get(c, float("nan"))
                print(f"    {c}: proto_mom={pv:+.4f} sys_mom={sv:+.4f}")
    print(f"\n2019-2020 月末选股分歧月数: {n_flip} / {len(month_ends)}")


if __name__ == "__main__":
    asyncio.run(main())
