# -*- coding: utf-8 -*-
"""临时调试：劫持截面动量选择器，观察引擎回测真实输入与原型差异。

已知：选择器对相同 proto_prices 输入与原型 0 分歧（2019-2020 24 个月末），
但引擎回测的选股在 2019-12、2020-07 等月末与原型反转。
结论候选：引擎链路传入选择器的价格矩阵与原型不同（日期/数值/对齐）。
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
TARGET_SIGNALS = [pd.Timestamp("2019-12-31"), pd.Timestamp("2020-07-31")]

captured = []


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
    from app.selection.selectors import cross_sectional_momentum as csm

    # 劫持选择器：记录每次调用的输入尾部与输出
    orig_select = csm.CrossSectionalMomentumSelector.select

    def spy_select(self, prices, n_assets, **params):
        res = orig_select(self, prices, n_assets, **params)
        last = prices.index[-1] if len(prices) else None
        captured.append({
            "last_date": last, "n_rows": len(prices),
            "selected": list(res.selected_assets),
            "scores": dict(res.scores),
            "tail_prices": prices.tail(3).copy(),
        })
        return res

    csm.CrossSectionalMomentumSelector.select = spy_select

    svc = StrategyModelService()
    doc = await svc.collection.find_one({"name": GMAP_NAME})
    doc["_id"] = str(doc["_id"])
    model = StrategyModel(**doc)
    strategy_params = build_backtest_params(model, model_data=doc)
    spec = build_strategy_composition(model.template_code, model.asset_codes, strategy_params)

    config = BacktestConfig(
        name="dbg_gmap_spy", thscodes=model.asset_codes,
        start_date="20190601", end_date="20200930",
        rebalance_freq="monthly",
        initial_cash=10_000_000, commission_rate=0.0, slippage=0.0,
    )
    ms = MarketService()
    data_feed = await DataFeed.from_market_service(ms, config, lookback_days=500)
    print("DataFeed 价格矩阵:", data_feed.prices.shape,
          "范围:", data_feed.prices.index.min().date(), "~", data_feed.prices.index.max().date())
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
    engine.run()

    # ── 原型动量 ──
    frames = {}
    for f in sorted((PROTO_ROOT / "data" / "gmap_adj").glob("*.csv")):
        df = pd.read_csv(f)
        frames[f.stem.upper()] = pd.Series(df["settle"].values, index=pd.to_datetime(df["trade_date"]))
    proto_prices = pd.DataFrame(frames).sort_index()
    proto_mom = proto_prices.pct_change(fill_method=None).rolling(20, min_periods=20).apply(
        lambda x: np.prod(1 + x) - 1)

    print(f"\n引擎选择器共调用 {len(captured)} 次")
    for cap in captured:
        ld = cap["last_date"]
        # 找对应信号日：引擎 last_date 应为信号日 M（执行日 M+1 的 prev_close 历史）
        print(f"\n== 引擎调用: last_date={ld.date() if ld is not None else None} rows={cap['n_rows']}")
        print(f"   引擎选出: {sorted(cap['selected'])}")
        # 原型在 last_date 的动量排名
        if ld in proto_mom.index:
            p_row = proto_mom.loc[ld].dropna()
            p_top = list(p_row.sort_values(ascending=False).index[:8])
            print(f"   原型 top8@{ld.date()}: {sorted(p_top)}")
            if set(p_top) != set(cap["selected"]):
                print("   >>> 分歧！分数对比（引擎 vs 原型）:")
                for c in sorted(set(proto_mom.columns)):
                    sv = cap["scores"].get(c, float("nan"))
                    pv = p_row.get(c, float("nan"))
                    mark = " <<<" if abs(sv - pv) > 1e-9 or (sv != pv) else ""
                    print(f"      {c}: eng={sv:+.6f} proto={pv:+.6f}{mark}")
        else:
            print(f"   原型动量索引无 {ld}！原型最近日期: {proto_mom.index.max().date()}")
        # 引擎价格 vs 原型价格（尾部3天）
        if ld is not None:
            eng_tail = cap["tail_prices"]
            for d in eng_tail.index:
                if d in proto_prices.index:
                    diff = (eng_tail.loc[d] - proto_prices.loc[d]).abs()
                    if diff.max() > 1e-9:
                        print(f"   >>> 价格差异 @{d.date()}: {diff[diff > 1e-9].to_dict()}")
                else:
                    print(f"   >>> 引擎日期 {d.date()} 不在原型日历中！")


if __name__ == "__main__":
    asyncio.run(main())
