"""
Task 4: 生成 zysc_ptl_holder_records 多期持有人数据
73产品 x 15期 = 1095条，机构/个人占比按风险等级分化，链式递推漂移。
配套生成 zysc_ptl_holder_import_batches。
"""
import sys
import random
from datetime import datetime

sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

random.seed(46)

DB_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"

# 15 个报告期（2024Q1 ~ 2027Q3）
PERIODS = [
    "2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31",
    "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31",
    "2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31",
    "2027-03-31", "2027-06-30", "2027-09-30",
]

# 风险等级 → 机构占比基线
RISK_INST_BASELINE = {
    "R1": (0.75, 0.90),  # 机构占比 75-90%
    "R2": (0.65, 0.80),
    "R3": (0.50, 0.70),
    "R4": (0.30, 0.50),
    "R5": (0.25, 0.40),
}

# 风险等级 → 每期漂移幅度
RISK_DRIFT = {
    "R1": 0.01, "R2": 0.015, "R3": 0.03, "R4": 0.06, "R5": 0.08,
}

# 产品规模范围（万元）
SCALE_RANGE = {
    "R1": (50000, 200000),
    "R2": (30000, 150000),
    "R3": (20000, 100000),
    "R4": (10000, 80000),
    "R5": (5000, 50000),
}


def generate_holder_data(products):
    """为所有产品生成15期持有人数据"""
    all_docs = []
    batch_map = {}  # period -> batch_id

    for period in PERIODS:
        batch_id = f"batch_holder_enriched_{period}"
        batch_map[period] = batch_id

    # 为每个产品生成基线和链式递推
    for prod in products:
        code = prod["产品代码"]
        risk = prod.get("风险等级", "R3")
        inst_range = RISK_INST_BASELINE.get(risk, (0.50, 0.70))
        drift = RISK_DRIFT.get(risk, 0.03)
        scale_range = SCALE_RANGE.get(risk, (20000, 100000))

        # 基线：第一期
        base_scale = random.uniform(*scale_range) * 10000  # 转为元
        inst_ratio = random.uniform(*inst_range)
        top10_ratio = random.uniform(0.4, 0.85)  # 前十集中度与规模反相关
        if base_scale > 1e9:
            top10_ratio *= 0.7  # 大产品分散

        prev_inst_ratio = inst_ratio
        prev_scale = base_scale

        for period_idx, period in enumerate(PERIODS):
            # 链式漂移
            if period_idx > 0:
                inst_drift = random.uniform(-drift, drift)
                prev_inst_ratio = max(0.1, min(0.95, prev_inst_ratio + inst_drift))
                scale_drift = random.uniform(-0.05, 0.08)  # 规模微涨
                prev_scale = prev_scale * (1 + scale_drift)

            total_amount = prev_scale
            inst_amount = total_amount * prev_inst_ratio
            personal_amount = total_amount * (1 - prev_inst_ratio)

            # 份额≈金额/净值（假设净值在0.95~1.05间）
            nav = random.uniform(0.95, 1.05)
            inst_share = inst_amount / nav
            personal_share = personal_amount / nav
            top10_share = (inst_share + personal_share) * top10_ratio * random.uniform(0.92, 1.08)

            doc = {
                "产品代码": code,
                "生效日期": period,
                "_holder_row_uid": f"{code}|{period}",
                "机构份额": round(inst_share, 2),
                "机构金额": round(inst_amount, 2),
                "个人份额": round(personal_share, 2),
                "个人金额": round(personal_amount, 2),
                "前十份额": round(top10_share, 2),
                "前十金额": round(top10_share * nav, 2),
                "数据日期": period,
                "数据时间": "00:00:00",
                "数据来源": "ZYSC",
                "导入方法": "API",
                "_batch_id": batch_map[period],
                "_imported_at": datetime.now().isoformat(),
                "_created_at": datetime.now().isoformat(),
            }
            all_docs.append(doc)

    return all_docs, batch_map


def main():
    client = MongoClient(DB_URI)
    db = client[DB_NAME]

    # 获取所有产品
    products = list(db["zysc_ptl_info_records"].find({}, {"产品代码": 1, "风险等级": 1}))
    print(f"产品总数: {len(products)}")

    # 清除旧扩充数据 + 原始数据（将被全量替换）
    del_result = db["zysc_ptl_holder_records"].delete_many({})
    print(f"清除全部holder: {del_result.deleted_count} 条（将重新生成含15期全量数据）")

    # 生成
    all_docs, batch_map = generate_holder_data(products)
    print(f"生成持有人记录: {len(all_docs)} 条")

    # 插入（分批）
    if all_docs:
        batch_size = 500
        for i in range(0, len(all_docs), batch_size):
            db["zysc_ptl_holder_records"].insert_many(all_docs[i:i + batch_size])
        print("持有人记录插入完成")

    # 生成配套 batches
    db["zysc_ptl_holder_import_batches"].delete_many({"batch_id": {"$regex": "^batch_holder_enriched_"}})
    batch_docs = []
    for period, batch_id in batch_map.items():
        count = sum(1 for d in all_docs if d["_batch_id"] == batch_id)
        status = "success" if random.random() < 0.85 else "partial"
        batch_docs.append({
            "batch_id": batch_id,
            "connector_id": "zysc_dwd_ptl_holder_summary",
            "status": status,
            "started_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat(),
            "duration_ms": random.randint(500, 3000),
            "total_returned": count,
            "inserted": count,
            "updated": 0,
            "failed": 0 if status == "success" else random.randint(1, 3),
            "_created_at": datetime.now().isoformat(),
        })

    for bd in batch_docs:
        db["zysc_ptl_holder_import_batches"].update_one(
            {"batch_id": bd["batch_id"]}, {"$set": bd}, upsert=True
        )
    print(f"批次记录upsert完成: {len(batch_docs)} 条")

    # 统计
    final = db["zysc_ptl_holder_records"].count_documents({})
    periods = db["zysc_ptl_holder_records"].distinct("生效日期")
    print(f"\n最终 zysc_ptl_holder_records: {final} 条")
    print(f"报告期数: {len(periods)}")
    print(f"报告期列表: {sorted(periods)[:5]}...{sorted(periods)[-3:]}")

    # 检查机构占比分化
    print("\n按风险等级的平均机构占比（最新期）:")
    for risk in ["R1", "R2", "R3", "R4", "R5"]:
        codes = [p["产品代码"] for p in products if p.get("风险等级") == risk]
        if not codes:
            continue
        pipeline = [
            {"$match": {"产品代码": {"$in": codes}, "生效日期": "2027-09-30"}},
            {"$project": {"ratio": {"$divide": ["$机构份额", {"$add": ["$机构份额", "$个人份额"]}]}}},
            {"$group": {"_id": None, "avg": {"$avg": "$ratio"}, "count": {"$sum": 1}}},
        ]
        res = list(db["zysc_ptl_holder_records"].aggregate(pipeline))
        if res:
            print(f"  {risk}: avg_inst_ratio={res[0]['avg']:.2%} ({res[0]['count']}个产品)")

    client.close()


if __name__ == "__main__":
    main()
