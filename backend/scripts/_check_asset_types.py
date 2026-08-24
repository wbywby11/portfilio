# -*- coding: utf-8 -*-
"""查询 MongoDB 中 assets 集合的 asset_type 分布"""
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["asset_allocation"]

print("=" * 60)
print("资产分类统计")
print("=" * 60)

# 按 asset_type 分组统计
pipeline = [{"$group": {"_id": "$asset_type", "count": {"$sum": 1}}}]
types = list(db["assets"].aggregate(pipeline))
for t in types:
    tp = t.get("_id") or "未设置"
    cnt = t.get("count", 0)
    print(f"  {tp}: {cnt} 个")

print()
print("=" * 60)
print("资产明细")
print("=" * 60)

all_assets = list(db["assets"].find({}, {"code": 1, "name": 1, "asset_type": 1, "asset_class": 1, "_id": 0}).sort("asset_type", 1))
for a in all_assets:
    code = a.get("code", "?")
    name = a.get("name", "?")
    atype = a.get("asset_type", "未设置")
    aclass = a.get("asset_class", "")
    print(f"  {code:15s}  {name:15s}  type={atype:8s}  class={aclass}")

print(f"\n共 {len(all_assets)} 个资产")
client.close()
