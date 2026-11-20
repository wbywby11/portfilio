# -*- coding: utf-8 -*-
"""临时调试：单独跑 GMAP 子策略回测并打印完整堆栈"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.database import Database  # noqa: E402
from app.models.strategy_model import StrategyModel  # noqa: E402
from app.portfolio.portfolio_service import PortfolioService  # noqa: E402

GMAP_NAME = "GMSI2-GMAP 商品动量策略"


async def main() -> None:
    Database.connect()
    pf_svc = PortfolioService()
    svc = pf_svc.strategy_model_service
    doc = await svc.collection.find_one({"name": GMAP_NAME})
    if not doc:
        raise SystemExit("模型不存在")
    doc["_id"] = str(doc["_id"])
    model = StrategyModel(**doc)
    print("parameters:", model.parameters)
    print("selector_parameters:", model.selector_parameters)
    print("controller_code:", model.controller_code, model.controller_parameters)

    # 直接重放 _run_sub_strategy_backtest 内部逻辑以拿到堆栈
    from bson import ObjectId as _ObjId
    from app.services.strategy_model_service import build_backtest_params
    from app.backtesting.composition_builder import build_strategy_composition

    sub_model_data = await svc.collection.find_one({"_id": _ObjId(model.id)})
    strategy_params = build_backtest_params(model, model_data=sub_model_data)
    print("strategy_params keys:", sorted(strategy_params.keys()))
    print("  controller_parameters:", strategy_params.get("controller_parameters"))
    print("  selector_parameters:", strategy_params.get("selector_parameters"))
    print("  controller_code:", strategy_params.get("controller_code"))

    spec = build_strategy_composition(model.template_code, model.asset_codes, strategy_params)
    print("composition:", spec.composition)
    print("force_month_end:", spec.force_month_end)

    from app.backtesting.config import BacktestConfig
    from app.backtesting.data_feed import DataFeed
    from app.backtesting.engine import BacktestEngine
    from app.backtesting.risk import RiskManager, RiskConfig
    from app.backtesting.execution import ExecutionEngine
    from app.allocation.services.registry import create_strategy_service_from_database
    from app.services.market_service import MarketService
    from app.backtesting.composition_pipeline import CompositionPipeline

    end_date = datetime.now().strftime("%Y-%m-%d")
    config = BacktestConfig(
        name="dbg_gmap", thscodes=model.asset_codes,
        start_date="20150901", end_date=end_date,
        rebalance_freq="month_end", initial_cash=10_000_000,
    )
    market_service = MarketService()
    data_feed = await DataFeed.from_market_service(
        market_service, config, lookback_days=500, strategy_type=model.template_code,
    )
    print("prices shape:", data_feed.prices.shape, "cols:", list(data_feed.prices.columns))
    print("prices range:", data_feed.prices.index.min(), "->", data_feed.prices.index.max())

    strategy_service = await create_strategy_service_from_database(market_service)
    strategy_cls = strategy_service.get_strategy_class(model.template_code)
    strategy = CompositionPipeline(
        allocator=strategy_cls(), thscodes=model.asset_codes,
        composition=spec.composition, strategy_params=strategy_params,
    )
    engine = BacktestEngine(
        config=config, data_feed=data_feed, strategy=strategy,
        risk_manager=RiskManager(RiskConfig()),
        execution_engine=ExecutionEngine(config),
    )

    # ── 完整引擎回测 ──
    try:
        result = engine.run()
        print("snapshots:", len(result.snapshots))
        import pandas as _pd
        nav = _pd.Series({s.time: s.total_value for s in result.snapshots}).sort_index()
        print("nav head:", nav.head(3).to_dict())
        print("nav tail:", nav.tail(3).to_dict())
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
