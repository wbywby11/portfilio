# -*- coding: utf-8 -*-
"""临时调试：聚焦 2019-12 信号，对比引擎与原型 GMAP 的完整权重生成链路。

输出：
  1. 原型 final_weights_ 在 2019-12-27 ~ 2020-01-10 的逐日值（看切换日与权重）
  2. 原型信号日 2019-12-31 的 inv_var 权重（逐步：vol → inv_var → mask → cap）
  3. 引擎 generate_target_weights(history<=2019-12-31, as_of=2020-01-02) 的输出
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

    seg = proto.final_weights_.loc["2019-12-27":"2020-01-10"]
    print("原型 final_weights_（2019-12-27~2020-01-10，只显示>0.005 的权重）:")
    for dt, row in seg.iterrows():
        nz = {c: round(v, 3) for c, v in row.items() if v > 0.005}
        print(f"  {dt.date()}: {nz}")

    # 原型信号日逐步复算
    from gmsi2.data import compute_vol
    returns = proto_prices.pct_change(fill_method=None).iloc[1:]
    vol = compute_vol(returns, method="ewma", window=60)
    sig = pd.Timestamp("2019-12-31")
    print(f"\n原型信号日 {sig.date()} 各品种 ewma(60) 年化 vol:")
    print(vol.loc[sig].round(4).to_dict())
    inv_var = (1.0 / vol.loc[sig] ** 2)
    mom = returns.rolling(20, min_periods=20).apply(lambda x: np.prod(1 + x) - 1).loc[sig]
    top8 = set(mom.dropna().sort_values(ascending=False).index[:8])
    print(f"top8: {sorted(top8)}")
    masked = inv_var.where(inv_var.index.isin(top8), 0.0)
    w = masked / masked.sum()
    print("反方差权重(截断前):", w.round(4).to_dict())
    w2 = w.clip(upper=0.30)
    w3 = w2 / w2.sum()
    print("clip0.3 后:", w2.round(4).to_dict())
    print("归一化后:", w3.round(4).to_dict())

    # ── 引擎侧：generate_target_weights ──
    from app.services.strategy_model_service import StrategyModelService, build_backtest_params
    from app.backtesting.composition_builder import build_strategy_composition
    from app.backtesting.composition_pipeline import CompositionPipeline
    from app.backtesting.config import BacktestConfig
    from app.backtesting.data_feed import DataFeed
    from app.allocation.services.registry import create_strategy_service_from_database
    from app.services.market_service import MarketService

    svc = StrategyModelService()
    doc = await svc.collection.find_one({"name": GMAP_NAME})
    doc["_id"] = str(doc["_id"])
    model = StrategyModel(**doc)
    strategy_params = build_backtest_params(model, model_data=doc)
    spec = build_strategy_composition(model.template_code, model.asset_codes, strategy_params)
    config = BacktestConfig(
        name="dbg", thscodes=model.asset_codes,
        start_date="20140103", end_date="20200131",
        rebalance_freq="monthly", initial_cash=10_000_000,
        commission_rate=0.0, slippage=0.0,
    )
    ms = MarketService()
    data_feed = await DataFeed.from_market_service(
        ms, config, lookback_days=500, strategy_type=model.template_code,
    )
    print("\nDataFeed 起点:", data_feed.prices.index.min().date(), "行数:", len(data_feed.prices))
    strategy_service = await create_strategy_service_from_database(ms)
    strategy_cls = strategy_service.get_strategy_class(model.template_code)
    strategy = CompositionPipeline(
        allocator=strategy_cls(), thscodes=model.asset_codes,
        composition=spec.composition, strategy_params=strategy_params,
    )
    hist = data_feed.prices.loc[data_feed.prices.index <= sig]
    print(f"引擎 history 截止: {hist.index[-1].date()}, 行数={len(hist)}")
    signal = strategy.generate_target_weights(hist, as_of=pd.Timestamp("2020-01-02"))
    eng_w = {k: round(v, 4) for k, v in signal.target_weights.items() if abs(v) > 0.0005}
    print("引擎目标权重:", eng_w)

    # 直接对比引擎传入 allocator 的价格与原型价格
    eng_tail = hist.tail(3)
    proto_tail = proto_prices.loc[eng_tail.index]
    diff = (eng_tail - proto_tail).abs()
    print("引擎 history 尾部 vs 原型价格 max|Δ|:", float(diff.max().max()))


if __name__ == "__main__":
    asyncio.run(main())
