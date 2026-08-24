# -*- coding: utf-8 -*-
"""临时调试：对比引擎侧价格矩阵（MarketService+sanitize）与原型 csv
在 2019-01-31 的动量分数，定位 T/M 排名翻转根因。"""
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

PROTO_ROOT = Path("d:/project/portfilio/gmsi2_replication")
SIGNAL = pd.Timestamp("2019-01-31")
CODES = ["AU", "CU", "FG", "I", "IC", "IF", "IM", "M", "T", "TF"]


def load_proto_prices() -> pd.DataFrame:
    frames = {}
    for f in sorted((PROTO_ROOT / "data" / "gmap_adj").glob("*.csv")):
        df = pd.read_csv(f)
        frames[f.stem.upper()] = pd.Series(df["settle"].values, index=pd.to_datetime(df["trade_date"]))
    return pd.DataFrame(frames).sort_index()


def momentum_row(prices: pd.DataFrame, window: int = 20) -> pd.Series:
    returns = prices.pct_change(fill_method=None).iloc[1:]
    mom = returns.rolling(window, min_periods=window).apply(lambda x: np.prod(1 + x) - 1)
    return mom.loc[SIGNAL]


async def main() -> None:
    Database.connect()
    from app.services.market_service import MarketService
    from app.backtesting.data_feed import DataFeed
    from app.backtesting.config import BacktestConfig

    # ---- 引擎侧（与 debug_gmap_2019.py 完全相同的构建方式）----
    ms = MarketService()
    config = BacktestConfig(
        name="dbg", thscodes=CODES,
        start_date="20181201", end_date="20191231",
        rebalance_freq="monthly", initial_cash=10_000_000,
    )
    feed = await DataFeed.from_market_service(ms, config, lookback_days=500)
    eng_prices = feed.prices[feed.prices.index <= SIGNAL]
    print(f"引擎价格矩阵: {eng_prices.shape}, {eng_prices.index[0].date()} ~ {eng_prices.index[-1].date()}")
    print(f"引擎矩阵 NaN 数(截断后): {int(eng_prices.isna().sum().sum())}")

    # ---- 原型侧 ----
    proto_prices = load_proto_prices()
    proto_prices = proto_prices.loc[proto_prices.index <= SIGNAL]
    print(f"原型价格矩阵: {proto_prices.shape}, {proto_prices.index[0].date()} ~ {proto_prices.index[-1].date()}")

    # ---- 1. 指数（日期行）差异 ----
    eng_idx = eng_prices.index
    proto_idx = proto_prices.index
    only_eng = eng_idx.difference(proto_idx)
    only_proto = proto_idx.difference(eng_idx)
    print(f"\n日期差异: 引擎独有 {len(only_eng)} 个, 原型独有 {len(only_proto)} 个")
    if len(only_eng):
        print("  引擎独有:", [str(x.date()) for x in only_eng[:20]])
    if len(only_proto):
        print("  原型独有:", [str(x.date()) for x in only_proto[:20]])

    # ---- 2. 窗口内（2018-12-20 ~ 2019-01-31）逐日价格差异 ----
    lo = pd.Timestamp("2018-12-15")
    common_dates = eng_idx.intersection(proto_idx)
    win = common_dates[(common_dates >= lo) & (common_dates <= SIGNAL)]
    ep = eng_prices.loc[win].reindex(columns=CODES)
    pp = proto_prices.loc[win].reindex(columns=CODES)
    diff = (ep - pp).abs()
    diff_max = diff.max().max()
    print(f"\n窗口内价格最大绝对差: {diff_max:.2e}")
    if diff_max > 1e-8:
        bad = diff.stack()
        bad = bad[bad > 1e-8]
        print("差异明细:")
        print(bad.head(30))

    # ---- 3. 动量分数对比 ----
    eng_mom = momentum_row(eng_prices.reindex(columns=CODES)).sort_values(ascending=False)
    proto_mom = momentum_row(proto_prices.reindex(columns=CODES)).sort_values(ascending=False)
    print("\n动量分数对比（2019-01-31, window=20）:")
    print(f"{'code':>5} {'引擎':>12} {'原型':>12} {'差':>12}  引擎排名/原型排名")
    eng_rank = {c: i + 1 for i, c in enumerate(eng_mom.dropna().index)}
    proto_rank = {c: i + 1 for i, c in enumerate(proto_mom.dropna().index)}
    for c in CODES:
        ev, pv = eng_mom.get(c, np.nan), proto_mom.get(c, np.nan)
        print(f"{c:>5} {ev:>12.6f} {pv:>12.6f} {(ev - pv):>12.2e}   {eng_rank.get(c, '-'):>3}/{proto_rank.get(c, '-'):>3}")
    print("\n引擎 top8:", list(eng_mom.dropna().index[:8]))
    print("原型 top8:", list(proto_mom.dropna().index[:8]))

    # ---- 4. M/T 窗口内收益率逐日对比 ----
    for c in ["M", "T"]:
        er = eng_prices[c].pct_change(fill_method=None)
        pr = proto_prices[c].pct_change(fill_method=None)
        cd = common_dates[(common_dates > (SIGNAL - pd.Timedelta(days=40))) & (common_dates <= SIGNAL)]
        print(f"\n{c} 逐日收益对比（最后30行）:")
        cmp_df = pd.DataFrame({"eng": er.reindex(cd), "proto": pr.reindex(cd)})
        cmp_df["diff"] = cmp_df["eng"] - cmp_df["proto"]
        print(cmp_df.tail(30).to_string(float_format=lambda v: f"{v:.6f}"))


if __name__ == "__main__":
    asyncio.run(main())
