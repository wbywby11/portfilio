# -*- coding: utf-8 -*-
"""探测 tushare 期权相关接口可用性"""
import tushare as ts

TOKEN = "286fd29627e9ce67299c961761cc79b1aad18937fc58373f87793775"
pro = ts.pro_api(TOKEN)

# 1. 指数日线 - 沪深300, 上证50, 中证500, 创业板指
print("=== 1. 指数日线 (index_daily) ===")
try:
    df = pro.index_daily(ts_code='000300.SH', start_date='20260601', end_date='20260622')
    print(f"  沪深300: {len(df)} rows, columns: {list(df.columns)}")
    if len(df) > 0:
        print(f"  latest: {df.iloc[0][['trade_date','close','vol']].to_dict()}")
except Exception as e:
    print(f"  ERROR: {e}")

# 2. SHIBOR 利率
print("\n=== 2. SHIBOR 利率 (shibor) ===")
try:
    df = pro.shibor(start_date='20260601', end_date='20260622')
    print(f"  rows: {len(df)}, columns: {list(df.columns)}")
    if len(df) > 0:
        print(f"  latest: {df.iloc[0].to_dict()}")
except Exception as e:
    print(f"  ERROR: {e}")

# 3. LPR 利率
print("\n=== 3. LPR (shibor_lpr) ===")
try:
    df = pro.shibor_lpr(start_date='20260101', end_date='20260622')
    print(f"  rows: {len(df)}, columns: {list(df.columns)}")
    if len(df) > 0:
        print(f"  latest: {df.iloc[0].to_dict()}")
except Exception as e:
    print(f"  ERROR: {e}")

# 4. 期权合约基本信息
print("\n=== 4. 期权合约 (opt_basic) ===")
try:
    df = pro.opt_basic(exchange='SSE', fields='ts_code,name,call_put,list_date,delist_date,exercise_price,s_month')
    print(f"  SSE contracts: {len(df)}")
    if len(df) > 0:
        print(f"  columns: {list(df.columns)}")
        # 找到活跃的300ETF期权
        active = df[df['delist_date'] >= '20260622']
        print(f"  active (not expired): {len(active)}")
        if len(active) > 0:
            print(f"  sample: {active.iloc[0].to_dict()}")
except Exception as e:
    print(f"  ERROR: {e}")

# 5. 期权日线行情
print("\n=== 5. 期权日线 (opt_daily) ===")
try:
    # 先查最近的合约
    df_basic = pro.opt_basic(exchange='SSE', fields='ts_code,name,call_put,delist_date,exercise_price')
    active = df_basic[df_basic['delist_date'] >= '20260622']
    if len(active) > 0:
        sample_code = active.iloc[0]['ts_code']
        df = pro.opt_daily(ts_code=sample_code, start_date='20260601', end_date='20260622')
        print(f"  {sample_code}: {len(df)} rows, columns: {list(df.columns)}")
        if len(df) > 0:
            print(f"  latest: {df.iloc[0].to_dict()}")
except Exception as e:
    print(f"  ERROR: {e}")

# 6. 交易日历
print("\n=== 6. 交易日历 (trade_cal) ===")
try:
    df = pro.trade_cal(exchange='SSE', start_date='20260601', end_date='20260622')
    print(f"  rows: {len(df)}, columns: {list(df.columns)}")
    open_days = df[df['is_open'] == 1]
    print(f"  open days: {len(open_days)}")
    if len(df) > 0:
        print(f"  sample: {df.iloc[0].to_dict()}")
except Exception as e:
    print(f"  ERROR: {e}")

# 7. 指数成分股和权重 (用于计算分红率)
print("\n=== 7. 指数权重 (index_weight) ===")
try:
    df = pro.index_weight(index_code='000300.SH', start_date='20260501', end_date='20260531')
    print(f"  rows: {len(df)}, columns: {list(df.columns)}")
    if len(df) > 0:
        print(f"  sample: {df.iloc[0].to_dict()}")
except Exception as e:
    print(f"  ERROR: {e}")

# 8. 股息率 (stk_dividend)
print("\n=== 8. 沪深300ETF基金分红 (fund_div) ===")
try:
    df = pro.fund_div(ts_code='510300.SH', start_date='20250101', end_date='20260622')
    print(f"  rows: {len(df)}, columns: {list(df.columns)}")
    if len(df) > 0:
        print(f"  sample: {df.iloc[0].to_dict()}")
except Exception as e:
    print(f"  ERROR: {e}")

# 9. 尝试获取隐含波动率
print("\n=== 9. 期权隐含波动率 ===")
try:
    # opt_daily 里有隐含波动率字段吗？
    df_basic = pro.opt_basic(exchange='SSE', fields='ts_code,name,call_put,delist_date,exercise_price,s_month')
    active_300 = df_basic[df_basic['ts_code'].str.contains('1000') & (df_basic['delist_date'] >= '20260622')]
    if len(active_300) > 0:
        sample_code = active_300.iloc[0]['ts_code']
        df = pro.opt_daily(ts_code=sample_code, start_date='20260615', end_date='20260622')
        print(f"  {sample_code}: {len(df)} rows")
        if len(df) > 0:
            print(f"  ALL columns: {list(df.columns)}")
            print(f"  latest row: {df.iloc[0].to_dict()}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== DONE ===")
