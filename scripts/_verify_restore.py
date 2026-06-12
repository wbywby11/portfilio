# -*- coding: utf-8 -*-
"""验证 asset_allocation 数据库恢复结果"""
import json
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)
db = client["asset_allocation"]

print("=" * 60)
print("[VERIFY] assets 集合")
print("=" * 60)
print(f"count: {db.assets.count_documents({})}")
print("前 2 条记录:")
for doc in db.assets.find({}, {"_id": 0}).limit(2):
    print(json.dumps(doc, ensure_ascii=False, default=str, indent=2))

print()
print("=" * 60)
print("[VERIFY] asset_prices 集合")
print("=" * 60)
print(f"count: {db.asset_prices.count_documents({})}")
print("前 2 条记录:")
for doc in db.asset_prices.find({}, {"_id": 0}).limit(2):
    print(json.dumps(doc, ensure_ascii=False, default=str, indent=2))

# 额外：每个 asset_code 的行情条数 Top 5
print()
print("[EXTRA] 每个 asset_code 的行情条数 Top 5:")
pipeline = [
    {"$group": {"_id": "$asset_code", "n": {"$sum": 1}}},
    {"$sort": {"n": -1}},
    {"$limit": 5},
]
for row in db.asset_prices.aggregate(pipeline):
    print(f"  {row['_id']}: {row['n']}")
