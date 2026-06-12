"""
生成多报告期产品持有人汇总数据

基于已有的 2025-06-30 / 2025-12-31 两期数据，生成额外 3 期：
  2026-03-31, 2026-06-30, 2026-09-30

确保：
- 产品代码与 zysc_ptl_info_records 一致
- 机构/个人占比在相邻期间合理漂移（±5%）
- 前十份额/金额合理波动
- 新增对应导入批次记录

用法：
  python scripts/generate_holder_multi_period.py            # 执行写入
  python scripts/generate_holder_multi_period.py --dry-run  # 仅预览
"""
import sys, random
sys.path.insert(0, r"d:\portfilio-end")
from datetime import datetime, timedelta
from pymongo import MongoClient

random.seed(2026)

def main():
    dry_run = "--dry-run" in sys.argv

    client = MongoClient("mongodb://localhost:27017")
    db = client["asset_allocation"]
    holder_col = db["zysc_ptl_holder_records"]
    batch_col = db["zysc_ptl_holder_import_batches"]
    ptl_info_col = db["zysc_ptl_info_records"]

    now_iso = datetime.now().isoformat()

    # ── 1. 读取最近一期数据作为基线 ──
    latest_period = "2025-12-31"
    baseline = {}
    for doc in holder_col.find({"生效日期": latest_period}):
        baseline[doc["产品代码"]] = doc

    if not baseline:
        # 退回到第一期
        latest_period = "2025-06-30"
        for doc in holder_col.find({"生效日期": latest_period}):
            baseline[doc["产品代码"]] = doc

    print(f"基线期: {latest_period}, 产品数: {len(baseline)}")

    # ── 2. 获取产品风险等级（影响漂移幅度） ──
    risk_map = {}
    for doc in ptl_info_col.find({}, {"产品代码": 1, "风险等级": 1, "管理人": 1}):
        risk_map[doc["产品代码"]] = doc.get("风险等级", "R3")

    # ── 3. 生成新报告期 ──
    NEW_PERIODS = [
        ("2026-03-31", "2026-03-31", "batch_holder_03"),
        ("2026-06-30", "2026-06-30", "batch_holder_04"),
        ("2026-09-30", "2026-09-30", "batch_holder_05"),
    ]

    new_docs = []
    batch_docs = []

    for period_idx, (eff_date, data_date, batch_id) in enumerate(NEW_PERIODS):
        period_drift_count = 0
        for port_code, prev_doc in baseline.items():
            risk = risk_map.get(port_code, "R3")

            # ── 份额/金额基础值（基于上一期，加入合理波动） ──
            prev_total_shr = prev_doc["个人份额"] + prev_doc["机构份额"]
            prev_total_amt = prev_doc["个人金额"] + prev_doc["机构金额"]

            # 总量增减 ±8%（模拟申赎）
            vol_factor = 1 + random.uniform(-0.08, 0.08)
            total_shr = round(prev_total_shr * vol_factor, 2)
            total_amt = round(prev_total_amt * vol_factor * random.uniform(0.98, 1.03), 2)

            # ── 机构/个人占比漂移 ──
            prev_inst_shr = prev_doc["机构份额"]
            prev_inst_ratio = prev_inst_shr / prev_total_shr if prev_total_shr > 0 else 0.5

            # R1/R2 低风险产品个人占比更稳定，漂移小
            if risk in ("R1", "R2"):
                drift = random.uniform(-0.03, 0.03)
            elif risk == "R3":
                drift = random.uniform(-0.05, 0.05)
            else:  # R4 高风险产品漂移更大
                drift = random.uniform(-0.07, 0.07)

            inst_ratio = max(0.10, min(0.95, prev_inst_ratio + drift))
            personal_ratio = round(1 - inst_ratio, 4)
            inst_ratio = round(inst_ratio, 4)

            inst_shr = round(total_shr * inst_ratio, 2)
            inst_amt = round(total_amt * inst_ratio, 2)
            personal_shr = round(total_shr * personal_ratio, 2)
            personal_amt = round(total_amt * personal_ratio, 2)

            # ── 前十份额/金额（集中度合理变化） ──
            prev_top10_shr = prev_doc["前十份额"]
            prev_top10_ratio = prev_top10_shr / prev_total_shr if prev_total_shr > 0 else 0.5
            top10_drift = random.uniform(-0.05, 0.05)
            top10_ratio = max(0.20, min(0.90, prev_top10_ratio + top10_drift))
            top10_shr = round(total_shr * top10_ratio, 2)
            top10_amt = round(total_amt * top10_ratio, 2)

            holder_row_uid = f"{port_code}|{eff_date}"
            doc = {
                "_holder_row_uid": holder_row_uid,
                "产品代码": port_code,
                "生效日期": eff_date,
                "前十份额": top10_shr,
                "前十金额": top10_amt,
                "个人份额": personal_shr,
                "个人金额": personal_amt,
                "机构份额": inst_shr,
                "机构金额": inst_amt,
                "数据日期": data_date,
                "数据时间": "00:00:00",
                "数据来源": "ZYSC",
                "导入方法": "API",
                "_batch_id": batch_id,
                "_imported_at": now_iso,
                "_created_at": now_iso,
            }
            new_docs.append(doc)
            period_drift_count += 1

        print(f"  报告期 {eff_date}: 生成 {period_drift_count} 条")

        # ── 导入批次记录 ──
        started = datetime.strptime(eff_date, "%Y-%m-%d") + timedelta(days=random.randint(3, 10), hours=random.randint(8, 17))
        dur = random.randint(1200, 5000)
        finished = started + timedelta(milliseconds=dur)
        total_ret = period_drift_count
        batch_doc = {
            "batch_id": batch_id,
            "status": "success",
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_ms": dur,
            "params": {"startDate": data_date, "endDate": data_date, "rownum": 100000},
            "upstream_url": "http://zylcorms.wmverify.com:8080/jxdatamid/apiManage/getPyResult",
            "upstream_code": "200",
            "upstream_message": "OK",
            "msg_list": [],
            "ind_name_list": [],
            "total_returned": total_ret,
            "inserted": total_ret,
            "updated": 0,
            "skipped_no_key": 0,
            "failed": 0,
            "error": None,
            "sample_errors": [],
        }
        batch_docs.append(batch_doc)

        # 链式递推：下一期基于本期数据
        baseline = {d["产品代码"]: d for d in new_docs[-period_drift_count:]}

    # ── 4. 写入 ──
    if dry_run:
        print(f"\n[DRY-RUN] 新增持有人记录: {len(new_docs)} 条")
        print(f"[DRY-RUN] 新增批次记录: {len(batch_docs)} 条")
        # 打印样本
        if new_docs:
            print("\n样本记录:")
            for k, v in new_docs[0].items():
                print(f"  {k}: {v}")
    else:
        # 去重：删除已有同 _holder_row_uid 的记录
        for doc in new_docs:
            holder_col.delete_one({"_holder_row_uid": doc["_holder_row_uid"]})
        for doc in batch_docs:
            batch_col.delete_one({"batch_id": doc["batch_id"]})

        r1 = holder_col.insert_many(new_docs)
        r2 = batch_col.insert_many(batch_docs)
        print(f"\n写入完成:")
        print(f"  持有人记录: {len(r1.inserted_ids)} 条")
        print(f"  批次记录: {len(r2.inserted_ids)} 条")

        # 验证
        total = holder_col.count_documents({})
        print(f"\n验证 - 总记录数: {total}")
        pipeline = [
            {"$group": {"_id": "$生效日期", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        print("生效日期分布:")
        for d in holder_col.aggregate(pipeline):
            print(f"  {d['_id']}: {d['count']} 条")


if __name__ == "__main__":
    main()
