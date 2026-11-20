# -*- coding: utf-8 -*-
"""临时调试：打印引擎调度映射（信号日→成交日），与原型 T+2 生效日核对。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.database import Database  # noqa: E402
from app.models.strategy_model import StrategyModel  # noqa: E402

GMAP_NAME = "GMSI2-GMAP 商品动量策略"
PROTO_ROOT = Path("d:/project/portfilio/gmsi2_replication")


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
        start_date="20181201", end_date="20190601",
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
    print("pipeline schedule keys:", list(strategy.get_execution_schedule().keys()))
    engine = BacktestEngine(
        config=config, data_feed=data_feed, strategy=strategy,
        risk_manager=RiskManager(_build_risk_config_from_params(strategy_params)),
        execution_engine=ExecutionEngine(config),
    )
    resolver = engine._schedule_resolver
    s2e = resolver.build_signal_to_execute_map(pd.Timestamp("2018-09-01"), pd.Timestamp("2019-06-01"))
    print("引擎调度映射（信号日 → 成交日）:")
    for sig, ed in sorted(s2e.items()):
        print(f"  信号 {sig.date()} -> 成交 {ed.date()}")

    # 原型映射核对
    sys.path.insert(0, str(PROTO_ROOT))
    from gmsi2.gmap import _load_trade_dates, _build_rebalance_schedule
    td = _load_trade_dates(str(PROTO_ROOT / "data" / "trade_dates.xlsx"))
    frames = {}
    for f in sorted((PROTO_ROOT / "data" / "gmap_adj").glob("*.csv")):
        df = pd.read_csv(f)
        frames[f.stem.upper()] = pd.Series(df["settle"].values, index=pd.to_datetime(df["trade_date"]))
    prices = pd.DataFrame(frames).sort_index()
    dates = prices.pct_change(fill_method=None).iloc[1:].index
    sigs, execs, s2e_p = _build_rebalance_schedule(dates, td)
    print("\n原型映射（信号日 → 生效日）:")
    for sig in sigs:
        if pd.Timestamp("2018-09-01") <= sig <= pd.Timestamp("2019-06-01"):
            print(f"  信号 {pd.Timestamp(sig).date()} -> 生效 {pd.Timestamp(s2e_p[sig]).date()}")


if __name__ == "__main__":
    asyncio.run(main())
