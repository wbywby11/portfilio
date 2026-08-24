"""检查数据库中资产的实际类型分布"""
from pymongo import MongoClient

db = MongoClient("mongodb://localhost:27017")["asset_allocation"]
pipeline = [
    {"$group": {"_id": "$asset_type", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
]
results = list(db["assets"].aggregate(pipeline))
print("Current asset_type distribution:")
for r in results:
    print(f"  {(r['_id'] or '(null)'):20s} : {r['count']:>3d}")

print("\n--- Sample futures/spot assets ---")
for t in ["期货类", "现货类", "指数类"]:
    print(f"\n[{t}]:")
    for doc in db["assets"].find({"asset_type": t}, {"code": 1, "name": 1, "rollover_days": 1, "substitute_code": 1}).limit(3):
        print(f"  code={doc.get('code'):10s} name={doc.get('name'):30s} "
              f"rollover_days={doc.get('rollover_days')} substitute_code={doc.get('substitute_code')}")
