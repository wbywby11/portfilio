# -*- coding: utf-8 -*-
"""验证种子数据"""
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

print("=== Data Verification ===")
n = db["option_products"].count_documents({})
print(f"option_products: {n}")
for doc in db["option_products"].find({}, {"product_id": 1, "type": 1, "underlying": 1, "principal": 1}):
    print(f"  {doc['product_id']:12s} type={doc['type']:16s} underlying={doc['underlying']:10s} principal={doc['principal']:,.0f}")

print(f"\noption_market_data: {db['option_market_data'].count_documents({})}")
dates = sorted(db["option_market_data"].distinct("date"))
print(f"  dates: {dates}")
for d in dates:
    underlyings = db["option_market_data"].distinct("underlying", {"date": d})
    print(f"  {d}: {underlyings}")

print(f"\noption_vol_surfaces: {db['option_vol_surfaces'].count_documents({})}")
for doc in db["option_vol_surfaces"].find({}, {"underlying": 1}):
    print(f"  {doc['underlying']}")

print(f"\noption_accounting_config: {db['option_accounting_config'].count_documents({})}")

print("\nasset_prices for underlyings:")
for code in ["SH000300", "SH000016", "SH000905", "SZ399006"]:
    cnt = db["asset_prices"].count_documents({"asset_code": code})
    latest = db["asset_prices"].find_one({"asset_code": code}, sort=[("date", -1)])
    if latest:
        print(f"  {code}: {cnt} docs, latest={latest['date']} close={latest['close']}")
    else:
        print(f"  {code}: 0 docs")

print("\n=== All OK ===")
c.close()
