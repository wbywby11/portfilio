"""迁移后验证脚本"""
from pymongo import MongoClient

db = MongoClient("mongodb://localhost:27017")["asset_allocation"]

print("--- 新字段分布 ---")
for f in ["instrument_type", "asset_class", "security_type"]:
    pipeline = [
        {"$group": {"_id": "$" + f, "c": {"$sum": 1}}},
        {"$sort": {"c": -1}},
    ]
    print(f"\n{f}:")
    for r in db["assets"].aggregate(pipeline):
        key = r["_id"] or "(null)"
        print(f"  {key:12s} : {r['c']}")

print("\n--- 抽样验证（含新旧字段对照）---")
samples = [
    "SH000300", "510300.SH", "518880.SH", "ZQGZ10", "B00Y",
    "IRON", "SHSN", "DM", "CVTBND", "512400.SH", "ZZ000001",
    "UST10", "YSJS", "510500.SH", "HSTECH",
]
for c in samples:
    d = db["assets"].find_one(
        {"code": c},
        {
            "name": 1,
            "instrument_type": 1,
            "asset_class": 1,
            "security_type": 1,
            "asset_type": 1,
        },
    )
    if d:
        print(
            f"  {c:12s} {d.get('name', '')[:20]:20s} | "
            f"inst={d.get('instrument_type', '-'):6s} "
            f"class={d.get('asset_class', '-'):6s} "
            f"sec={d.get('security_type', '-'):6s} | "
            f"old={d.get('asset_type')}"
        )
