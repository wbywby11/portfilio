# -*- coding: utf-8 -*-
"""临时调试：量化 GMAP/GCMI 各品种 csv 的"内部缺日"（并集日历中有、该品种缺失的日期）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

PROTO_ROOT = Path("d:/project/portfilio/gmsi2_replication")


def analyze(dir_name: str, codes: list) -> None:
    frames = {}
    for f in sorted((PROTO_ROOT / dir_name).glob("*.csv")):
        code = f.stem if not f.stem.upper().islower() else f.stem.upper()
        code = f.stem.upper()
        if codes is not None and code not in codes:
            continue
        df = pd.read_csv(f)
        frames[code] = pd.Series(df["settle"].values, index=pd.to_datetime(df["trade_date"]))
    prices = pd.DataFrame(frames).sort_index()
    union_idx = prices.index
    print(f"== {dir_name}: {len(frames)} 品种, 并集日历 {len(union_idx)} 天 ({union_idx[0].date()} ~ {union_idx[-1].date()})")
    total_gap = 0
    for code in sorted(frames):
        s = prices[code]
        fv = s.first_valid_index()
        lv = s.last_valid_index()
        interior = union_idx[(union_idx >= fv) & (union_idx <= lv)]
        gaps = interior[s.loc[interior].isna()]
        if len(gaps):
            total_gap += len(gaps)
            print(f"  {code:>4}: 内部缺日 {len(gaps)} 个: {[str(x.date()) for x in gaps]}")
    print(f"  合计内部缺日: {total_gap}")
    # 缺日影响的信号日统计：缺日后 20 个交易日内的月末信号日
    if total_gap:
        mom_bad_dates = set()
        for code in sorted(frames):
            s = prices[code]
            fv = s.first_valid_index()
            lv = s.last_valid_index()
            interior = union_idx[(union_idx >= fv) & (union_idx <= lv)]
            gaps = interior[s.loc[interior].isna()]
            for g in gaps:
                pos = union_idx.get_loc(g)
                for j in range(pos, min(pos + 21, len(union_idx))):
                    mom_bad_dates.add((code, union_idx[j]))
        # 统计影响到的月末信号日（并集日历的月末日）
        ym = pd.Series(union_idx.year * 100 + union_idx.month, index=union_idx)
        month_last = pd.Series(union_idx, index=union_idx).groupby(ym.values).max()
        affected = {c: [] for c in set(x[0] for x in mom_bad_dates)}
        for d in month_last:
            for c in affected:
                if (c, d) in mom_bad_dates:
                    affected[c].append(str(pd.Timestamp(d).date()))
        print("  受缺日 NaN 传播影响的月末信号日（该品种动量=NaN 被 dropna）:")
        for c, ds in sorted(affected.items()):
            print(f"    {c:>4}: {ds}")


if __name__ == "__main__":
    gmap_codes = ["AU", "CU", "FG", "I", "IC", "IF", "IM", "M", "T", "TF"]
    analyze("data/gmap_adj", gmap_codes)
    print()
    analyze("data/gcmi_adj", None)
