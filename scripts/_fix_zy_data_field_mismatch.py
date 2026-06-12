# -*- coding: utf-8 -*-
"""
批量修复 ZY 数据域字段不匹配 / 占位数据问题。

后端 portfilio-end/app/config/settings.py 配置的实际查询库为 asset_allocation，
但 HERMES 真实数据（含 schema 对齐字段）落在 portfilio 库。

本脚本对以下表执行 portfilio -> asset_allocation 的全量替换迁移，
迁移前会自动备份 asset_allocation.<coll>__backup_YYYYMMDD_HHMMSS。

涉及表：
- dwd_cust_info        : 缺 CUSTOMER_ID/CUST_NM/PHONE/OPEN_DT 等 schema 对齐字段
- dwd_cust_make_pstn_info : 当前是资产维度数据污染，需替换为客户持仓
- dwd_ast_exe_plan     : 字段已对齐，但确保数据一致

注意：dwd_ast_info 已在 _fix_dwd_ast_info_placeholder.py 中处理，本脚本跳过。
"""
import sys
from datetime import datetime
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
SOURCE_DB = "portfilio"
TARGET_DB = "asset_allocation"

TABLES_TO_MIGRATE = [
    "dwd_cust_info",
    "dwd_cust_make_pstn_info",
    "dwd_ast_exe_plan",
]

# 必须存在 schema 对齐字段才认为源是合格的
SCHEMA_FIELD_REQUIREMENTS = {
    "dwd_cust_info": ["CUSTOMER_ID", "CUST_NM"],
    "dwd_cust_make_pstn_info": ["CUSTOMER_ID", "PORT_ID", "HLD_SHR", "HLD_AMT"],
    "dwd_ast_exe_plan": ["AST_CD", "EXE_DT"],
}


def migrate_table(client, coll_name):
    src = client[SOURCE_DB][coll_name]
    tgt = client[TARGET_DB][coll_name]

    src_total = src.count_documents({})
    tgt_total = tgt.count_documents({})
    print(f"\n--- {coll_name} ---")
    print(f"  源 [{SOURCE_DB}.{coll_name}]:  total={src_total}")
    print(f"  标 [{TARGET_DB}.{coll_name}]:  total={tgt_total}")

    if src_total == 0:
        print(f"  ⚠️ 源库为空，跳过 {coll_name}")
        return False

    # 校验 schema 字段是否在源库存在
    required = SCHEMA_FIELD_REQUIREMENTS.get(coll_name, [])
    sample = src.find_one()
    missing = [f for f in required if f not in (sample or {})]
    if missing:
        print(f"  ❌ 源库缺失 schema 必需字段 {missing}，跳过 {coll_name}")
        return False

    # 备份
    if tgt_total > 0:
        backup_name = f"{coll_name}__backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup = client[TARGET_DB][backup_name]
        backup.drop()
        docs = list(tgt.find({}))
        if docs:
            backup.insert_many(docs)
        print(f"  ✓ 已备份 {tgt_total} 条 -> {TARGET_DB}.{backup_name}")

    # 迁移
    src_docs = list(src.find({}))
    for d in src_docs:
        d.pop("_id", None)
    tgt.delete_many({})
    if src_docs:
        tgt.insert_many(src_docs)

    new_total = tgt.count_documents({})
    print(f"  ✅ 迁移完成: {new_total} 条")

    # 校验示例
    sample = tgt.find_one()
    schema_fields = SCHEMA_FIELD_REQUIREMENTS.get(coll_name, [])
    sample_check = {f: sample.get(f) for f in schema_fields if sample}
    print(f"  样本 schema 字段: {sample_check}")
    return True


def main():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    print("=" * 70)
    print("ZY 数据域批量修复（portfilio -> asset_allocation）")
    print("=" * 70)

    success = 0
    for tname in TABLES_TO_MIGRATE:
        try:
            if migrate_table(client, tname):
                success += 1
        except Exception as e:
            print(f"  ❌ 异常: {e}")

    print("\n" + "=" * 70)
    print(f"完成：{success}/{len(TABLES_TO_MIGRATE)} 张表迁移成功")
    print("=" * 70)


if __name__ == "__main__":
    main()
