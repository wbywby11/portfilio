# -*- coding: utf-8 -*-
"""临时调试：定位 2019 年未缩放权重差异 66 天的来源。"""
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
        name="dbg", thscodes=model.asset_codes,
        start_date="20181201", end_date="20191231",
        rebalance_freq="monthly", initial_cash=10_000_000,
        commission_rate=0.0, slippage=0.0,
    )
    ms = MarketService()
    data_feed = await DataFeed.from_market_service(
        ms, config, lookback_days=500, strategy_type=model.template_code,
    )
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
    # 探针：记录每次目标权重生成的输入尾部与输出
    orig_gen = strategy.generate_target_weights

    def spy_gen(history_prices, as_of):
        sig = orig_gen(history_prices, as_of)
        tail = history_prices.index[-1].date() if len(history_prices) else None
        w = {k: round(v, 3) for k, v in sig.target_weights.items() if abs(v) > 0.005}
        print(f"  [生成] as_of={as_of.date()} hist尾={tail} rows={len(history_prices)} -> {w}")
        return sig

    strategy.generate_target_weights = spy_gen
    result = engine.run()
    print("快照中的调仓记录（is_rebalance_day）:")
    for s in result.snapshots:
        if s.is_rebalance_day:
            print(f"  {s.time.date()} type={s.rebalance_type} reason={s.rebalance_reason} "
                  f"signal_date={getattr(s, 'signal_date', None)} delay={getattr(s, 'execution_delay_days', None)}")
    sys_w = pd.DataFrame({s.time: pd.Series(s.weights) for s in result.snapshots}).T.sort_index().fillna(0.0)
    sys_lev = sys_w.sum(axis=1)
    sys_unscaled = sys_w.div(sys_lev.replace(0, np.nan), axis=0).fillna(0.0)

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
    proto_w = proto.final_weights_

    cw = sys_unscaled.index.intersection(proto_w.index)
    sw = sys_unscaled.loc[cw].reindex(columns=proto_w.columns).fillna(0.0)
    pw = proto_w.loc[cw].fillna(0.0)
    wdiff = (sw - pw).abs().max(axis=1)
    bad = wdiff[wdiff > 0.005]
    print(f"权重差异天数: {len(bad)}")
    print("差异日期:", [str(x.date()) for x in bad.index])
    # 挑 3 个差异日看细节
    for dt in bad.index[:5]:
        print(f"\n== {dt.date()}")
        print("  sys:", {c: round(v, 3) for c, v in sw.loc[dt].items() if v > 0.005})
        print("  proto:", {c: round(v, 3) for c, v in pw.loc[dt].items() if v > 0.005})
    # 原型权重切换日 vs 系统快照切换日（2019）
    pc = proto_w.diff().abs().sum(axis=1)
    sc = sys_unscaled.diff().abs().sum(axis=1)
    print("\n原型切换日(2019):", [str(x.date()) for x in pc[pc > 0.01].index])
    print("系统切换日(2019):", [str(x.date()) for x in sc[sc > 0.01].index])


if __name__ == "__main__":
    asyncio.run(main())
