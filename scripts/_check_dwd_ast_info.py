# -*- coding: utf-8 -*-
"""排查 dwd_ast_info 占位数据残留问题"""
import re
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)

print("=" * 70)
print("Step 1: 列出所有数据库")
print("=" * 70)
for db_name in client.list_database_names():
    print(f"  - {db_name}")

# 候选数据库
candidate_dbs = ["portfilio", "portfolio", "zy_data", "asset_allocation", "portfilio_db"]

print()
print("=" * 70)
print("Step 2: 各候选数据库中含 'ast' 的集合及其文档数")
print("=" * 70)
for db_name in client.list_database_names():
    db = client[db_name]
    cols = [c for c in db.list_collection_names() if "ast" in c.lower()]
    if not cols:
        continue
    print(f"\n[{db_name}]")
    for c in cols:
        cnt = db[c].count_documents({})
        print(f"  {c}: {cnt}")

print()
print("=" * 70)
print("Step 3: 检查 dwd_ast_info 占位符（按各数据库）")
print("=" * 70)
ph_re = {"$regex": r"_\d{2,4}$"}
for db_name in client.list_database_names():
    db = client[db_name]
    if "dwd_ast_info" not in db.list_collection_names():
        continue
    coll = db["dwd_ast_info"]
    total = coll.count_documents({})
    ph_by_nm = coll.count_documents({"AST_NM": ph_re})
    ph_by_cd = coll.count_documents({"AST_CD": {"$regex": r"^AST_\d{6}$"}})
    print(f"\n[{db_name}.dwd_ast_info] total={total}, placeholder(AST_NM)={ph_by_nm}, placeholder(AST_CD)={ph_by_cd}")
    print("  -- 前 10 条样本 --")
    for d in coll.find({}, {"AST_CD": 1, "AST_NM": 1, "ISR_NM": 1, "_id": 0}).limit(10):
        print(f"    {d}")
    if ph_by_nm or ph_by_cd:
        print("  -- 占位符样本 (前5条) --")
        for d in coll.find({"$or": [{"AST_NM": ph_re}, {"AST_CD": {"$regex": r"^AST_\d{6}$"}}]},
                           {"AST_CD": 1, "AST_NM": 1, "ISR_NM": 1, "_id": 0}).limit(5):
            print(f"    {d}")

print()
print("=" * 70)
print("Step 4: 检查 assets 集合（前端可能直接读这个）")
print("=" * 70)
for db_name in client.list_database_names():
    db = client[db_name]
    if "assets" in db.list_collection_names():
        coll = db["assets"]
        cnt = coll.count_documents({})
        print(f"\n[{db_name}.assets] total={cnt}")
        for d in coll.find({}, {"code": 1, "name": 1, "asset_code": 1, "asset_name": 1, "_id": 0}).limit(5):
            print(f"  {d}")

print()
print("Done.")
