# -*- coding: utf-8 -*-
"""临时调试：系统隐含杠杆 vs 原型 leverage.shift(1) 路径对比"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROTO_ROOT = Path("d:/project/portfilio/gmsi2_replication")
sys.path.insert(0, str(PROTO_ROOT))

from gmsi2.gcmi import GCMI  # noqa: E402
from gmsi2.data import compute_vol, combine_vol  # noqa: E402


def main() -> None:
    frames = {}
    for f in sorted((PROTO_ROOT / "data" / "gcmi_adj").glob("*.csv")):
        df = pd.read_csv(f)
        frames[f.stem.upper()] = pd.Series(df["settle"].values, index=pd.to_datetime(df["trade_date"]))
    prices = pd.DataFrame(frames).sort_index()

    proto = GCMI(tf_lookback=25, cs_lookback_months=8, combo_weight_tf=0.5,
                 combo_weight_cs=0.5, target_vol=0.03, vol_method="ewma")
    proto.run(prices)
    returns = prices.pct_change(fill_method=None)
    raw_ret = (0.5 * (proto.tf_weights_.shift(1) * returns).sum(axis=1)
               + 0.5 * (proto.cs_weights_ * returns).sum(axis=1))
    raw_ret = raw_ret.reindex(proto.nav_.index).fillna(0)
    vs = compute_vol(raw_ret, method="ewma", window=20)
    vl = compute_vol(raw_ret, method="ewma", window=60)
    vest = combine_vol(vs, vl, method="mean")
    lev_p = np.clip(0.03 / vest.replace(0, np.nan).fillna(0.03), 0.1, 5.0).shift(1).fillna(1.0)

    d = pd.read_csv("dbg_gcmi_nav_compare.csv", index_col=0, parse_dates=True)
    rs = d["sys"].pct_change()
    lev_implied = rs / raw_ret.reindex(rs.index)
    m = pd.DataFrame({"lev_proto": lev_p.reindex(rs.index), "lev_implied": lev_implied}).dropna()
    m = m[m["lev_proto"] > 0]
    print("整体: lev_proto均值=%.3f lev_implied均值=%.3f 比值均值=%.3f"
          % (m["lev_proto"].mean(), m["lev_implied"].mean(),
             (m["lev_implied"] / m["lev_proto"]).mean()))
    m["year"] = m.index.year
    print(m.groupby("year")[["lev_proto", "lev_implied"]].mean().round(3).to_string())

    ratio = (m["lev_implied"] / m["lev_proto"] - 1).abs()
    bad = ratio.sort_values(ascending=False).head(10)
    print("\n比值偏离最大 top10:")
    for dt in bad.index:
        print(f"  {dt.date()}: implied={m.loc[dt, 'lev_implied']:.3f} proto={m.loc[dt, 'lev_proto']:.3f}")

    # 相关性
    print("\ncorr(lev_implied, lev_proto) =", round(m["lev_implied"].corr(m["lev_proto"]), 4))


if __name__ == "__main__":
    main()
