# -*- coding: utf-8 -*-
"""临时调试：全时段逐信号日对比引擎与原型 GMAP 权重。

已确认 2019-12-31 信号日权重值完全一致。本脚本：
  1. 跑引擎回测，提取每个调仓信号日的未缩放目标权重
  2. 与原型 weights_at_signal（信号日权重）逐月对比
  3. 对比逐日未缩放权重的归属（切换时点是否一致）
  4. 输出收益差异的日期分布
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
    strategy_params = build_backtest_params(model, model_data=doc)
    spec = build_strategy_composition(model.template_code, model.asset_codes, strategy_params)

    config = BacktestConfig(
        name="dbg_gmap_full", thscodes=model.asset_codes,
        start_date="20140103", end_date="20260610",
        rebalance_freq="monthly", initial_cash=10_000_000,
        commission_rate=0.0, slippage=0.0,
        # 原型首次执行前权重 = fillna(1/n) 等权满仓；引擎以等权期初建仓对齐
        initial_weights={c: 1.0 / len(model.asset_codes) for c in model.asset_codes},
    )
    ms = MarketService()
    data_feed = await DataFeed.from_market_service(ms, config, lookback_days=500)
    strategy_service = await create_strategy_service_from_database(ms)
    strategy_cls = strategy_service.get_strategy_class(model.template_code)
    strategy = CompositionPipeline(
        allocator=strategy_cls(), thscodes=model.asset_codes,
        composition=spec.composition, strategy_params=strategy_params,
    )
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

    # ── 1. 逐日收益差异分布 ──
    common = sys_ret.dropna().index.intersection(proto_ret.dropna().index)
    rs, rp = sys_ret.loc[common], proto_ret.loc[common]
    corr = float(np.corrcoef(rs.values, rp.values)[0, 1])
    delta = (rs - rp).abs()
    print(f"日收益 corr={corr:.4f} | Δ>0.05% 天数={int((delta > 0.0005).sum())} "
          f"| Δ>0.01% 天数={int((delta > 0.0001).sum())} / {len(common)}")
    print("差异最大 top10:")
    for dt in delta.sort_values(ascending=False).head(10).index:
        print(f"  {dt.date()}  sys={rs[dt]*100:+.4f}%  proto={rp[dt]*100:+.4f}%")

    # ── 2. 逐日未缩放权重差异（归属时点）──
    sw = sys_unscaled.loc[common].reindex(columns=proto_w.columns).fillna(0.0)
    pw = proto_w.loc[common].fillna(0.0)
    wdiff = (sw - pw).abs().max(axis=1)
    bad_w = wdiff[wdiff > 0.005]
    print(f"\n未缩放权重 max|Δw|>0.005 天数: {len(bad_w)} / {len(common)}")
    # 按年分布
    by_year = bad_w.groupby(bad_w.index.year).size()
    print("按年分布:", by_year.to_dict())
    print("差异日期样例（前 20）:", [str(x.date()) for x in bad_w.index[:20]])

    # ── 3. 引擎切换日 vs 原型切换日 ──
    sys_change = sys_unscaled.diff().abs().sum(axis=1)
    proto_change = proto_w.diff().abs().sum(axis=1)
    sc = sys_change[sys_change > 0.01].index
    pc = proto_change[proto_change > 0.01].index
    sc_set, pc_set = set(sc), set(pc)
    print(f"\n引擎切换日 {len(sc)} 个，原型切换日 {len(pc)} 个，"
          f"共同 {len(sc_set & pc_set)}，引擎独有 {len(sc_set - pc_set)}，原型独有 {len(pc_set - sc_set)}")
    only_proto = sorted(pc_set - sc_set)
    only_sys = sorted(sc_set - pc_set)
    print("原型独有切换日:", [str(x.date()) for x in only_proto[:20]])
    print("引擎独有切换日:", [str(x.date()) for x in only_sys[:20]])

    # ── 4. 共同切换日：切换后权重值是否一致 ──
    common_switch = sorted(sc_set & pc_set)
    n_mismatch = 0
    for dt in common_switch:
        dv = (sw.loc[dt] - pw.loc[dt]).abs().max()
        if dv > 0.005:
            n_mismatch += 1
            if n_mismatch <= 10:
                detail = {c: f"{sw.loc[dt, c]:.3f}/{pw.loc[dt, c]:.3f}"
                          for c in (sw.loc[dt] - pw.loc[dt]).abs().sort_values(ascending=False).head(3).index}
                print(f"  [切换日权重差] {dt.date()} maxΔ={dv:.4f} | {detail}")
    print(f"共同切换日权重不一致数: {n_mismatch} / {len(common_switch)}")


if __name__ == "__main__":
    asyncio.run(main())
