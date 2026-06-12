# -*- coding: utf-8 -*-
"""
验证所有调仓日是否按 trade_dates 的 T+2 规则执行（与 2015-01-06 一致）

规则：执行日 = 月末最后交易日后的第2个交易日

运行：cd d:\portfilio-end && python verify_t2_rebalance.py
"""
import pandas as pd
from pathlib import Path

p = Path(__file__).parent / "data" / "trade_dates.xlsx"
if not p.exists():
    p = Path(__file__).parent.parent / "动量策略相关资料" / "trade_dates.xlsx"
df = pd.read_excel(p)
col = df["trade_dates"] if "trade_dates" in df.columns else df.iloc[:, 0]
trade_dates_list = sorted(pd.Timestamp(d) for d in pd.to_datetime(col).dropna().unique().tolist())

selection_start = pd.Timestamp("2014-01-31")
month_last_trade = {}
for d in trade_dates_list:
    if d >= selection_start:
        month_last_trade[d.to_period("M")] = d

_REBALANCE_EXCLUDE = {
    pd.Timestamp("2015-01-01"),
    pd.Timestamp("2015-01-02"),
    pd.Timestamp("2015-01-05"),
}


def skip_excluded(ed, trade_list):
    if ed not in _REBALANCE_EXCLUDE:
        return ed
    next_d = [d for d in trade_list if d > ed]
    return next_d[0] if next_d else ed


print("T+2 调仓执行日验证（与 2015-01-06 规则一致）")
print("=" * 85)
print(f"{'月份':<10} {'月末最后交易日':<14} {'T+1':<12} {'T+2(执行日)':<14} {'最终执行日':<12}")
print("-" * 85)

for period in sorted(month_last_trade.keys()):
    if period < pd.Period("2014-02"):
        continue
    effective_calc = month_last_trade[period]
    future = [d for d in trade_dates_list if d > effective_calc]
    if len(future) < 2:
        print(f"{period}  future_dates不足2个，跳过")
        continue
    t1 = future[0]
    t2 = future[1]
    final = skip_excluded(t2, trade_dates_list)
    print(
        f"{str(period):<10} {effective_calc.strftime('%Y-%m-%d'):<14} "
        f"{t1.strftime('%Y-%m-%d'):<12} {t2.strftime('%Y-%m-%d'):<14} {final.strftime('%Y-%m-%d'):<12}"
    )
