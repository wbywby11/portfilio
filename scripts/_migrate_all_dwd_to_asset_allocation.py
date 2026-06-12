"""
批量迁移 portfilio 库中所有 dwd_ 开头的集合到 asset_allocation 库。

背景:
- 后端 settings.DATABASE_NAME = "asset_allocation"
- 但 HERMES 真实数据全部导入到 portfilio 库
- 导致前端通过后端API读到的依然是 asset_allocation 中的占位数据

策略:
- 遍历 portfilio 中所有 dwd_ 开头的集合（以及若存在的 tag_ptl_info / core_data 等 ZY 数据域集合）
- 源集合非空 -> 清空目标集合并写入源数据
- 源集合为空但目标已有数据 -> 跳过(保留目标)
- 不做备份(已有 backup 集合, 且 asset_allocation 旧数据均为占位符)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pymongo import MongoClient


SOURCE_DB_NAME = "portfilio"
TARGET_DB_NAME = "asset_allocation"
MONGO_URI = "mongodb://localhost:27017"

# 额外要处理的非 dwd_ 前缀但属于 ZY 数据域的集合
EXTRA_ZY_COLLS = ["tag_ptl_info", "core_data"]

# 抽查的代表性集合
SAMPLE_COLLS = [
    "dwd_isr_institution",
    "dwd_ast_info",
    "dwd_ptl_basic",
    "dwd_cust_info",
    "dwd_trd_record",
    "dwd_mkt_quote",
    "dwd_val_daily",
    "dwd_risk_indicator",
]


def main() -> int:
    started_at = datetime.now()
    print(f"[{started_at:%Y-%m-%d %H:%M:%S}] 开始迁移: {SOURCE_DB_NAME} -> {TARGET_DB_NAME}")

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # 触发一次连接确认
    client.admin.command("ping")

    source_db = client[SOURCE_DB_NAME]
    target_db = client[TARGET_DB_NAME]

    src_all = source_db.list_collection_names()
    dwd_colls = sorted([c for c in src_all if c.startswith("dwd_")])

    extra_present = [c for c in EXTRA_ZY_COLLS if c in src_all]
    candidate_colls = dwd_colls + extra_present

    print(f"  源库共 {len(src_all)} 个集合, 其中 dwd_ 集合 {len(dwd_colls)} 个, 额外 ZY 集合 {len(extra_present)} 个")
    print(f"  待处理总数: {len(candidate_colls)} 个集合")
    print("-" * 80)

    migrated = 0
    skipped_empty = 0
    skipped_keep_target = 0
    total_src_records = 0
    total_tgt_records = 0
    failed: list[tuple[str, str]] = []

    for coll_name in candidate_colls:
        try:
            src_coll = source_db[coll_name]
            tgt_coll = target_db[coll_name]

            src_count = src_coll.count_documents({})
            tgt_before = tgt_coll.count_documents({})

            if src_count == 0:
                if tgt_before > 0:
                    print(f"  ⏭️  {coll_name}: 源为空, 目标已有 {tgt_before} 条 -> 保留目标")
                    skipped_keep_target += 1
                else:
                    skipped_empty += 1
                continue

            # 读取源 -> 移除 _id -> 清空目标 -> 写入
            docs = list(src_coll.find({}))
            for d in docs:
                d.pop("_id", None)

            tgt_coll.delete_many({})
            if docs:
                # 分批写入避免单批过大
                batch_size = 1000
                for i in range(0, len(docs), batch_size):
                    tgt_coll.insert_many(docs[i:i + batch_size], ordered=False)

            tgt_after = tgt_coll.count_documents({})
            total_src_records += src_count
            total_tgt_records += tgt_after
            migrated += 1
            print(f"  ✅ {coll_name}: {src_count} -> {tgt_after} (目标原 {tgt_before})")

        except Exception as exc:  # noqa: BLE001
            failed.append((coll_name, str(exc)))
            print(f"  ❌ {coll_name}: 迁移失败 - {exc}")

    print("-" * 80)
    print(f"完成: 迁移 {migrated} 个集合 | 源空且目标空跳过 {skipped_empty} | 源空保留目标 {skipped_keep_target} | 失败 {len(failed)}")
    print(f"总迁移记录数: 源 {total_src_records} -> 目标 {total_tgt_records}")

    if failed:
        print("\n失败明细:")
        for name, msg in failed:
            print(f"  - {name}: {msg}")

    # 抽查验证
    print("\n" + "=" * 80)
    print("抽查验证 (asset_allocation 库):")
    print("=" * 80)
    for name in SAMPLE_COLLS:
        if name not in target_db.list_collection_names():
            print(f"  - {name}: [集合不存在]")
            continue
        coll = target_db[name]
        cnt = coll.count_documents({})
        sample = coll.find_one({})
        # 取一些有代表性字段
        preview_fields = {}
        if sample:
            for key in (
                "isr_nm", "ast_nm", "ptl_nm", "cust_nm",
                "isr_id", "ast_id", "ptl_id", "cust_id",
                "name", "code",
            ):
                if key in sample:
                    preview_fields[key] = sample[key]
        print(f"  📊 {name}: {cnt} 条 | 样本字段: {preview_fields}")

    # 重点验证机构名
    print("\n重点验证 dwd_isr_institution 真实机构名:")
    isr_coll = target_db.get_collection("dwd_isr_institution")
    real_names = []
    for doc in isr_coll.find({}, {"_id": 0, "isr_nm": 1, "isr_id": 1}).limit(10):
        real_names.append(doc)
    for d in real_names:
        print(f"    - {d}")

    expected_keyword = "财政部"
    has_real = isr_coll.count_documents({"isr_nm": {"$regex": expected_keyword}}) > 0
    if has_real:
        print(f"  ✅ 检测到真实机构名 (包含 '{expected_keyword}')")
    else:
        print(f"  ⚠️  未在 dwd_isr_institution.isr_nm 中检索到 '{expected_keyword}', 请人工确认")

    finished_at = datetime.now()
    print(f"\n[{finished_at:%Y-%m-%d %H:%M:%S}] 迁移结束, 耗时 {(finished_at - started_at).total_seconds():.2f}s")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
