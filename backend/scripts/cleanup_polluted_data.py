# -*- coding: utf-8 -*-
"""清理种子数据污染，保留真实数据"""
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

print("=== 清理污染数据 ===\n")

# 1. option_market_data: 删除 source=seed/manual 和 无data_source字段的
r1a = db["option_market_data"].delete_many({"data_source": "seed/manual"})
r1b = db["option_market_data"].delete_many({"data_source": {"$exists": False}})
print(f"[1] option_market_data: 删除 {r1a.deleted_count + r1b.deleted_count} 条 seed/manual 记录")
print(f"    剩余: {db['option_market_data'].count_documents({})} 条 (tushare)")

# 2. option_vol_surfaces: 删除无 date 字段的种子曲面
r2a = db["option_vol_surfaces"].delete_many({"date": {"$exists": False}})
r2b = db["option_vol_surfaces"].delete_many({"date": None})
print(f"\n[2] option_vol_surfaces: 删除 {r2a.deleted_count + r2b.deleted_count} 条无date种子曲面")
print(f"    剩余: {db['option_vol_surfaces'].count_documents({})} 条 (tushare)")

# 3. option_valuations: 删除污染版本
print("\n    当前估值版本:")
for v in db["option_valuations"].find({}, {"date": 1, "version": 1, "snapshot.total_value": 1}):
    sv = v.get("snapshot", {})
    print(f"      {v.get('date')} v{v.get('version')} total={sv.get('total_value', 0):,.2f}")

# 删除 2026-06-22 的 v1 和 v2
r3a = db["option_valuations"].delete_many({"date": "2026-06-22", "version": 1})
r3b = db["option_valuations"].delete_many({"date": "2026-06-22", "version": 2})
# 删除 2026-06-17 的所有版本（基于种子数据）
r3c = db["option_valuations"].delete_many({"date": "2026-06-17"})
print(f"\n[3] option_valuations: 删除 {r3a.deleted_count + r3b.deleted_count + r3c.deleted_count} 条污染版本")
print(f"    剩余: {db['option_valuations'].count_documents({})} 条")
for v in db["option_valuations"].find({}, {"date": 1, "version": 1, "snapshot.total_value": 1}):
    sv = v.get("snapshot", {})
    print(f"    保留: {v.get('date')} v{v.get('version')} total={sv.get('total_value', 0):,.2f}")

# 4. option_valuation_history: 删除污染记录
r4a = db["option_valuation_history"].delete_many({"version": 1})
r4b = db["option_valuation_history"].delete_many({"version": 2})
r4c = db["option_valuation_history"].delete_many({"date": "2026-06-17"})
print(f"\n[4] option_valuation_history: 删除 {r4a.deleted_count + r4b.deleted_count + r4c.deleted_count} 条污染记录")
print(f"    剩余: {db['option_valuation_history'].count_documents({})} 条")

# 5. option_accounting_entries: 清空
r5 = db["option_accounting_entries"].delete_many({})
print(f"\n[5] option_accounting_entries: 清空 {r5.deleted_count} 条")

# 最终统计
print("\n=== 最终数据状态 ===")
for col in ["asset_prices", "option_products", "option_market_data", 
            "option_vol_surfaces", "option_contracts", "option_iv_data",
            "option_valuations", "option_valuation_history", 
            "option_accounting_entries", "option_lifecycle_events"]:
    cnt = db[col].count_documents({})
    print(f"  {col:35s}: {cnt:>8,}")

c.close()
print("\n=== 清理完成 ===")
