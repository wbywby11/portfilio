# -*- coding: utf-8 -*-
"""验证导入数据"""
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

print("=== 数据验证 ===\n")

# 1. 资产价格
print("[1] asset_prices (指数日线)")
for code in ["SH000300", "SH000016", "SH000905", "SZ399006"]:
    cnt = db["asset_prices"].count_documents({"asset_code": code})
    latest = db["asset_prices"].find_one({"asset_code": code}, sort=[("date", -1)])
    if latest:
        print(f"  {code}: {cnt} docs, latest={latest['date']} close={latest['close']:.2f}")

print("\n[2] option_market_data (综合市场数据)")
for code in ["SH000300", "SH000016", "SH000905", "SZ399006"]:
    docs = list(db["option_market_data"].find({"underlying": code}).sort("date", -1).limit(1))
    if docs:
        d = docs[0]
        print(f"  {code}: date={d['date']} spot={d['spot']:.2f} "
              f"vol_1m={d['vol_1m']*100:.1f}% vol_12m={d['vol_12m']*100:.1f}% "
              f"rate_1y={d['rate_1y']*100:.2f}%")

print("\n[3] option_iv_data (隐含波动率)")
iv_cnt = db["option_iv_data"].count_documents({})
iv_dates = db["option_iv_data"].distinct("date")
print(f"  {iv_cnt} records, {len(iv_dates)} trading days")
# 看最近的IV样本
latest_iv = list(db["option_iv_data"].find().sort("date", -1).limit(5))
for iv in latest_iv:
    print(f"  {iv['date']} strike={iv['strike']:.2f} moneyness={iv['moneyness']:.3f} "
          f"tenor={iv['tenor']:.3f}y iv={iv['iv']*100:.1f}%")

print("\n[4] option_contracts (期权合约)")
contract_cnt = db["option_contracts"].count_documents({})
call_cnt = db["option_contracts"].count_documents({"call_put": "C"})
put_cnt = db["option_contracts"].count_documents({"call_put": "P"})
print(f"  {contract_cnt} active (Call={call_cnt}, Put={put_cnt})")

print("\n[5] option_products (收益凭证产品)")
prod_cnt = db["option_products"].count_documents({})
for p in db["option_products"].find({}, {"product_id": 1, "type": 1, "principal": 1, "underlying": 1}):
    print(f"  {p['product_id']:12s} type={p['type']:16s} "
          f"principal={p['principal']:>12,.0f} underlying={p['underlying']}")

print("\n[6] 集合总览")
for col_name in ["asset_prices", "option_market_data", "option_contracts",
                  "option_iv_data", "option_vol_surfaces", "option_products",
                  "option_valuations", "option_valuation_history",
                  "option_accounting_entries", "option_lifecycle_events"]:
    cnt = db[col_name].count_documents({})
    print(f"  {col_name:35s}: {cnt:>8,}")

print("\n=== 验证完成 ===")
c.close()
