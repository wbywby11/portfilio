# -*- coding: utf-8 -*-
"""临时调试：原型 GCMI leverage 序列 vs 系统 targeting scale 对比

结论目标：系统 _compute_portfolio_vol 用"当前权重×全历史收益"估 vol，
原型用"未缩放组合实际收益序列(raw_ret)"估 vol —— 量化两者 leverage 差异。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROTO_ROOT = Path("d:/project/portfilio/gmsi2_replication")
sys.path.insert(0, str(PROTO_ROOT))

from gmsi2.gcmi import GCMI  # noqa: E402
from gmsi2.data import compute_vol, combine_vol  # noqa: E402


def load_proto_prices() -> pd.DataFrame:
    frames = {}
    for f in sorted((PROTO_ROOT / "data" / "gcmi_adj").glob("*.csv")):
        df = pd.read_csv(f)
        frames[f.stem.upper()] = pd.Series(df["settle"].values, index=pd.to_datetime(df["trade_date"]))
    return pd.DataFrame(frames).sort_index()


def main() -> None:
    prices = load_proto_prices()
    proto = GCMI(tf_lookback=25, cs_lookback_months=8, combo_weight_tf=0.5,
                 combo_weight_cs=0.5, target_vol=0.03, vol_method="ewma")
    nav = proto.run(prices)
    raw_ret = 0.5 * proto.tf_returns_ + 0.5 * proto.cs_returns_
    vol_short = compute_vol(raw_ret, method="ewma", window=20)
    vol_long = compute_vol(raw_ret, method="ewma", window=60)
    vol_est = combine_vol(vol_short, vol_long, method="arithmetic")
    leverage = np.clip(0.03 / vol_est.replace(0, np.nan).fillna(0.03), 0.1, 5.0)

    test_dates = [pd.Timestamp("2016-06-15"), pd.Timestamp("2018-03-12"), pd.Timestamp("2020-09-08")]
    print("原型 leverage（信号日口径，shift(1) 前）：")
    for d in test_dates:
        if d in leverage.index:
            print(f"  {d.date()}: vol_est={vol_est.loc[d]:.5f}  leverage={leverage.loc[d]:.4f}")

    lev = leverage.dropna()
    print(f"\n原型 leverage 统计: mean={lev.mean():.3f} median={lev.median():.3f} "
          f"min={lev.min():.3f} max={lev.max():.3f}  std={lev.std():.3f}")
    print("(系统诊断值对照: 2016-06-15 scale=1.0556 / 2018-03-12 scale=1.5581 / 2020-09-08 scale=1.3200)")


if __name__ == "__main__":
    main()
