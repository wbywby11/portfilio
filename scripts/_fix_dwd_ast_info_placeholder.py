# -*- coding: utf-8 -*-
"""
修复 dwd_ast_info 占位数据残留问题

根因：
- 后端 portfilio-end/app/config/settings.py 的 DATABASE_NAME = "asset_allocation"
- HERMES 真实数据被导入到了 portfilio 库
- asset_allocation.dwd_ast_info 仍是 100 条占位符 (AST_000001/国债_0001 ...)
- 前端通过后端 API 读 asset_allocation 库 -> 看到的就是占位符

修复方案：
1) 备份 asset_allocation.dwd_ast_info -> dwd_ast_info__backup_placeholder
2) 用 portfilio.dwd_ast_info 的真实数据覆盖 asset_allocation.dwd_ast_info
3) 校验占位符数量为 0
"""
import sys
import json
from datetime import datetime
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
SOURCE_DB = "portfilio"          # 真实数据所在库
TARGET_DB = "asset_allocation"   # 后端实际查询库
COLL = "dwd_ast_info"
BACKUP_COLL = f"{COLL}__backup_placeholder_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

PLACEHOLDER_AST_NM = {"$regex": r"_\d{2,4}$"}
PLACEHOLDER_AST_CD = {"$regex": r"^AST_\d{6}$"}


def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    src = client[SOURCE_DB][COLL]
    tgt = client[TARGET_DB][COLL]

    # ---- 校验 source ----
    src_total = src.count_documents({})
    src_ph = src.count_documents({"$or": [{"AST_NM": PLACEHOLDER_AST_NM},
                                          {"AST_CD": PLACEHOLDER_AST_CD}]})
    print(f"[源] {SOURCE_DB}.{COLL}: total={src_total}, placeholder={src_ph}")
    if src_total == 0:
        print("ERROR: 源库为空，无法迁移。中止。")
        sys.exit(1)
    if src_ph > 0:
        print(f"ERROR: 源库仍含 {src_ph} 条占位数据，不能用作真实数据源。中止。")
        sys.exit(1)

    # ---- 校验 target 当前状态 ----
    tgt_total_before = tgt.count_documents({})
    tgt_ph_before = tgt.count_documents({"$or": [{"AST_NM": PLACEHOLDER_AST_NM},
                                                 {"AST_CD": PLACEHOLDER_AST_CD}]})
    print(f"[标] {TARGET_DB}.{COLL}: total={tgt_total_before}, placeholder={tgt_ph_before}")

    # ---- 备份 target ----
    if tgt_total_before > 0:
        backup = client[TARGET_DB][BACKUP_COLL]
        # 清空备份集合（防止重名）
        backup.drop()
        docs = list(tgt.find({}))
        if docs:
            backup.insert_many(docs)
        print(f"[备份] {TARGET_DB}.{BACKUP_COLL}: {backup.count_documents({})} 条")

    # ---- 拷贝 source -> target ----
    src_docs = list(src.find({}))
    # 移除 _id 避免冲突
    for d in src_docs:
        d.pop("_id", None)
    tgt.delete_many({})
    if src_docs:
        tgt.insert_many(src_docs)

    # ---- 校验 ----
    tgt_total_after = tgt.count_documents({})
    tgt_ph_after = tgt.count_documents({"$or": [{"AST_NM": PLACEHOLDER_AST_NM},
                                                {"AST_CD": PLACEHOLDER_AST_CD}]})
    print(f"[结果] {TARGET_DB}.{COLL}: total={tgt_total_after}, placeholder={tgt_ph_after}")

    print("\n样本（前 10 条）:")
    for d in tgt.find({}, {"AST_CD": 1, "AST_NM": 1, "ISR_NM": 1, "_id": 0}).limit(10):
        print(f"  {d}")

    if tgt_ph_after == 0 and tgt_total_after == src_total:
        print(f"\n✅ 修复成功：{TARGET_DB}.{COLL} 已替换为真实数据，占位符 0 条")
        print(f"   备份集合：{TARGET_DB}.{BACKUP_COLL}")
    else:
        print("\n❌ 修复异常：请检查")
        sys.exit(2)


if __name__ == "__main__":
    main()
