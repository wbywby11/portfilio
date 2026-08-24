# -*- coding: utf-8 -*-
"""临时调试：核对原型 trade_dates.xlsx 日历 vs 行情数据日历，解释原型切换日偏移。"""
from pathlib import Path
import pandas as pd

PROTO_ROOT = Path("d:/project/portfilio/gmsi2_replication")

td_df = pd.read_excel(PROTO_ROOT / "data" / "trade_dates.xlsx")
print("trade_dates.xlsx 列:", list(td_df.columns))
col = 'trade_dates' if 'trade_dates' in td_df.columns else td_df.columns[1]
td = pd.DatetimeIndex(pd.to_datetime(td_df[col]).sort_values())
print("日历范围:", td.min().date(), "~", td.max().date(), "共", len(td), "天")
print("重复日期数:", td.duplicated().sum())

frames = {}
for f in sorted((PROTO_ROOT / "data" / "gmap_adj").glob("*.csv")):
    df = pd.read_csv(f)
    frames[f.stem.upper()] = pd.Series(df["settle"].values, index=pd.to_datetime(df["trade_date"]))
prices = pd.DataFrame(frames).sort_index()
data_idx = prices.index

# 2014-04-25 ~ 2014-05-12 区间对比
lo, hi = pd.Timestamp("2014-04-25"), pd.Timestamp("2014-05-12")
td_seg = td[(td >= lo) & (td <= hi)]
data_seg = data_idx[(data_idx >= lo) & (data_idx <= hi)]
print("\n2014-04-25~05-12 xlsx 日历:", [str(x.date()) for x in td_seg])
print("2014-04-25~05-12 行情日期:", [str(x.date()) for x in data_seg])

# 全量差异
td_set, data_set = set(td), set(data_idx)
only_td = sorted(td_set - data_set)
only_data = sorted(data_set - td_set)
print(f"\nxlsx 有而行情无: {len(only_td)} 个，样例:", [str(x.date()) for x in only_td[:20]])
print(f"行情有而 xlsx 无: {len(only_data)} 个，样例:", [str(x.date()) for x in only_data[:20]])

# 复算原型信号→执行映射（gmap 逻辑）
dates = prices.pct_change(fill_method=None).iloc[1:].index
valid_td = td[(td >= dates[0]) & (td <= dates[-1])]
td_series = pd.Series(valid_td, index=valid_td)
ym = pd.Series(valid_td.year * 100 + valid_td.month, index=valid_td)
signal_dates = list(td_series.groupby(ym).last().values)
td_sorted = valid_td.sort_values()
td_pos = {d: i for i, d in enumerate(td_sorted)}
print("\n2014 年信号日→执行日（原型逻辑）：")
for sig in signal_dates:
    if pd.Timestamp(sig).year != 2014:
        continue
    pos = td_pos[sig]
    exec_d = td_sorted[pos + 2] if pos + 2 < len(td_sorted) else None
    in_data = exec_d in dates if exec_d is not None else False
    print(f"  信号 {pd.Timestamp(sig).date()} -> 执行 {exec_d.date() if exec_d is not None else None}  在行情索引={in_data}")
