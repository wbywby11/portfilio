# -*- coding: utf-8 -*-
"""临时调试：量化 xlsx 日历 vs 行情日历的偏移，及每月信号日差异。"""
from pathlib import Path
import pandas as pd

PROTO_ROOT = Path("d:/project/portfilio/gmsi2_replication")

td_df = pd.read_excel(PROTO_ROOT / "data" / "trade_dates.xlsx")
td = pd.DatetimeIndex(pd.to_datetime(td_df["trade_dates"]).sort_values())
td = td.drop_duplicates()

frames = {}
for f in sorted((PROTO_ROOT / "data" / "gmap_adj").glob("*.csv")):
    df = pd.read_csv(f)
    frames[f.stem.upper()] = pd.Series(df["settle"].values, index=pd.to_datetime(df["trade_date"]))
prices = pd.DataFrame(frames).sort_index()
data_idx = prices.index

td_set, data_set = set(td), set(data_idx)
both = sorted(td_set & data_set)
only_td = sorted(td_set - data_set)
only_data = sorted(data_set - td_set)
print(f"交集={len(both)}  xlsx独有={len(only_td)}  行情独有={len(only_data)}")
print("xlsx 独有日期范围分布（按年）:")
print(pd.Series([d.year for d in only_td]).value_counts().sort_index().to_dict())
print("行情独有日期范围分布（按年）:")
print(pd.Series([d.year for d in only_data]).value_counts().sort_index().to_dict())

# 每月信号日对比：xlsx 月末日 vs 行情月末日
td_s = pd.Series(td, index=td)
data_s = pd.Series(data_idx, index=data_idx)
ym_td = td_s.groupby([td.year * 100 + td.month]).last()
ym_data = data_s.groupby([data_idx.year * 100 + data_idx.month]).last()
comp = pd.DataFrame({"xlsx_sig": ym_td, "data_sig": ym_data})
comp["same"] = comp["xlsx_sig"] == comp["data_sig"]
print(f"\n月末信号日一致的月份: {comp['same'].sum()} / {len(comp)}")
diff_sig = comp[~comp["same"] & comp["xlsx_sig"].notna() & comp["data_sig"].notna()]
print("信号日不一致的月份（2014 起，前 30 个）:")
for ym, row in diff_sig.head(30).iterrows():
    print(f"  {ym}: xlsx={row['xlsx_sig'].date()}  data={row['data_sig'].date()}")

# 执行日偏移统计：原型执行日（xlsx pos+2）相对行情日历的信号日+1/+2/+3
td_sorted = td.sort_values()
td_pos = {d: i for i, d in enumerate(td_sorted)}
offsets = []
for ym, row in comp.iterrows():
    sig, exec_x = row["xlsx_sig"], None
    if pd.isna(sig):
        continue
    if sig in td_pos and td_pos[sig] + 2 < len(td_sorted):
        exec_x = td_sorted[td_pos[sig] + 2]
    if exec_x is None or pd.isna(row["data_sig"]):
        continue
    # 行情日历中 sig_data 到 exec_x 的交易日数
    ds = row["data_sig"]
    if exec_x not in data_set:
        offsets.append(("exec不在行情", ym))
        continue
    i0 = data_idx.get_loc(ds)
    i1 = data_idx.get_loc(exec_x)
    offsets.append((i1 - i0, ym))
off_vals = pd.Series([o[0] for o in offsets])
print("\n执行日相对行情信号日的偏移分布（行情交易日数）:")
print(off_vals.value_counts().sort_index().to_dict() if off_vals.dtype != object else off_vals.value_counts().to_dict())
