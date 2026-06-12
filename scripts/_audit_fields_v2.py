# -*- coding: utf-8 -*-
"""审计每张目标表的字段映射（DB 实际字段 vs 前端 schema 字段）"""
from collections import Counter
from pymongo import MongoClient

db = MongoClient("mongodb://localhost:27017")["asset_allocation"]

TABLES = ["dwd_cust_info", "dwd_cust_make_pstn_info", "dwd_ast_exe_plan", "dwd_ast_info"]

for cname in TABLES:
    coll = db[cname]
    total = coll.count_documents({})
    cnt = Counter()
    samples = {}
    for d in coll.find({}).limit(50):
        for k, v in d.items():
            if k == "_id":
                continue
            cnt[k] += 1
            if v not in (None, "", [], {}) and k not in samples:
                samples[k] = v
    print(f"\n=== {cname} (total={total}, sampled=50) ===")
    for k in sorted(cnt.keys()):
        eg = samples.get(k, "<empty>")
        eg_s = str(eg)[:50]
        print(f"  {k:28s} count={cnt[k]:3d} eg={eg_s}")
