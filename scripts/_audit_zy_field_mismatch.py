# -*- coding: utf-8 -*-
"""
全面审计 ZY 数据域字段名不匹配 / 空值问题
聚焦集合（用户截图反馈异常）：
- dwd_ast_info        : 100 条，AST_NM 仍为占位符
- dwd_cust_info       : 200 条，客户ID/客户名称为空
- dwd_cust_ast_hld    : 609 条，多字段为空
- dwd_ast_exe_plan    : 12 条，行权日/行权价格为空
"""
from pymongo import MongoClient
from collections import Counter

MONGO_URI = "mongodb://localhost:27017"
TARGET_DB = "asset_allocation"   # 后端实际查询库
SOURCE_DB = "portfilio"          # HERMES 真实数据所在库

TARGETS = ["dwd_ast_info", "dwd_cust_info", "dwd_cust_ast_hld",
           "dwd_ast_exe_plan", "dwd_ptl_info"]

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


def field_stats(coll, max_keys=40):
    """统计前 max_keys 个字段的非空率与样本值"""
    docs = list(coll.find({}).limit(50))
    if not docs:
        return {}, 0
    counter = Counter()
    samples = {}
    for d in docs:
        for k, v in d.items():
            if k == "_id":
                continue
            counter[k] += 1
            if v not in (None, "", [], {}) and k not in samples:
                samples[k] = v
    total = len(docs)
    stats = {}
    for k, c in counter.most_common(max_keys):
        non_empty = sum(
            1 for d in docs
            if d.get(k) not in (None, "", [], {})
        )
        stats[k] = {
            "presence": f"{c}/{total}",
            "non_empty": f"{non_empty}/{total}",
            "sample": samples.get(k, "<all empty>"),
        }
    return stats, total


for db_name in [TARGET_DB, SOURCE_DB]:
    db = client[db_name]
    cols = db.list_collection_names()
    print("\n" + "=" * 80)
    print(f"DATABASE: {db_name}")
    print("=" * 80)
    for tname in TARGETS:
        if tname not in cols:
            print(f"\n[{tname}]  ❌ 集合不存在")
            continue
        coll = db[tname]
        total = coll.count_documents({})
        print(f"\n[{tname}]  total={total}")
        stats, sampled = field_stats(coll)
        if not stats:
            print("  (空集合)")
            continue
        print(f"  -- 抽样 {sampled} 条，每字段非空率 --")
        for k, s in stats.items():
            sample_str = str(s["sample"])
            if len(sample_str) > 60:
                sample_str = sample_str[:60] + "..."
            print(f"    {k:30s} present={s['presence']:6s} non_empty={s['non_empty']:6s} eg={sample_str}")

print("\n\nDone.")
