"""诊断 _async_load_precomputed_weights 的加载情况"""
import asyncio, sys
sys.path.insert(0, r'd:\project\portfilio\portfilio-end')
import pandas as pd
from app.config.database import Database
from app.monitor.time_norm import normalize_calendar_timestamp

async def main():
    Database.connect()
    db = Database.db
    
    # 模拟 _async_load_precomputed_weights 的逻辑
    from app.monitor.mongo_asset_codes import canonical_price_code
    
    # 加载价格数据获取月末日期
    codes = ['SH000300', 'ZZ000905', 'SZ399006', 'SPX', 'NDX', 'N225',
             'ZQGZ10', 'ZQGZ5', 'ZQGZ2', 'UST10', 'UST2',
             'CVTBND', 'GLD', 'B00Y', 'SHCU', 'SHAL', 'SHSN', 'DM']
    
    coll_prices = db['asset_prices']
    docs = await coll_prices.find(
        {"asset_code": {"$in": codes}},
        {"asset_code": 1, "date": 1, "_id": 0}
    ).to_list(length=100000)
    
    if not docs:
        print("asset_prices 中没有数据！")
        return
    
    df = pd.DataFrame(docs)
    df['date'] = pd.to_datetime(df['date'])
    prices_df = df.pivot(index='date', columns='asset_code', values='close')
    prices_df.sort_index(inplace=True)
    
    # 构建月末日期
    month_end_dates = []
    ym_series = pd.Series(prices_df.index, index=prices_df.index)
    for (year, month), group in ym_series.groupby([ym_series.index.year, ym_series.index.month]):
        month_end = normalize_calendar_timestamp(group.index[-1])
        month_end_dates.append(month_end)
    
    calc_date_strs = [d.strftime('%Y-%m-%d') for d in month_end_dates]
    print(f"prices_df 月末日数: {len(calc_date_strs)}")
    print(f"前5个: {calc_date_strs[:5]}")
    print(f"后5个: {calc_date_strs[-5:]}")
    
    # 查询 MongoDB
    coll = db['sharpe_rebalance_weights']
    cursor = coll.find({"calc_date": {"$in": calc_date_strs}})
    docs = await cursor.to_list(length=500)
    print(f"\nMongoDB 匹配到: {len(docs)} 条")
    
    if docs:
        print(f"第一条: calc_date={docs[0]['calc_date']}, weights keys={list(docs[0].get('weights',{}).keys())[:5]}")
    
    # 检查 MongoDB 中所有 calc_date
    all_docs = await coll.find({}).to_list(length=200)
    all_dates = sorted([d['calc_date'] for d in all_docs])
    print(f"\nMongoDB 总 calc_date 数: {len(all_dates)}")
    print(f"前5个: {all_dates[:5]}")
    print(f"后5个: {all_dates[-5:]}")
    
    # 对比
    mongo_set = set(all_dates)
    calc_set = set(calc_date_strs)
    matched = calc_set & mongo_set
    only_calc = calc_set - mongo_set
    only_mongo = mongo_set - calc_set
    print(f"\n匹配: {len(matched)}, 仅prices: {len(only_calc)}, 仅mongo: {len(only_mongo)}")
    if only_calc:
        print(f"  仅prices中的前5: {sorted(only_calc)[:5]}")
    if only_mongo:
        print(f"  仅mongo中的前5: {sorted(only_mongo)[:5]}")

asyncio.run(main())
