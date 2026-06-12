"""
Task 7: 验证数据扩充完整性
检查跨表外键、时间连续性、分布合理性。
"""
import sys
sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

DB_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"


def main():
    client = MongoClient(DB_URI)
    db = client[DB_NAME]

    checks_passed = 0
    checks_failed = 0

    def check(name, condition, detail=""):
        nonlocal checks_passed, checks_failed
        if condition:
            checks_passed += 1
            print(f"  [PASS] {name}")
        else:
            checks_failed += 1
            print(f"  [FAIL] {name} — {detail}")

    print("=" * 70)
    print("DataHub 多维数据集完整性验证")
    print("=" * 70)

    # ─── 1. 数据量检查 ───
    print("\n>>> 1. 数据量检查")
    tables_expected = {
        "subject_risk_records": 500,
        "zysc_ptl_info_records": 70,
        "zysc_ptl_holder_records": 1000,
        "dwd_isr_institution": 50,
        "dwd_ptl_ast_hld": 400,
        "subject_risk_import_batches": 30,
        "zysc_ptl_holder_import_batches": 10,
    }
    for table, min_count in tables_expected.items():
        actual = db[table].count_documents({})
        check(f"{table} >= {min_count}", actual >= min_count, f"actual={actual}")

    # ─── 2. 跨表外键完整性 ───
    print("\n>>> 2. 跨表外键完整性")

    # risk.subject_name ⊆ ISR.ISR_NM
    risk_subjects = set(db["subject_risk_records"].distinct("subject_name"))
    isr_names = set(db["dwd_isr_institution"].distinct("ISR_NM"))
    orphan_risk = risk_subjects - isr_names
    check("risk.subject_name ⊆ ISR.ISR_NM", len(orphan_risk) == 0,
          f"{len(orphan_risk)} orphans: {list(orphan_risk)[:3]}")

    # holder.产品代码 ⊆ ptl_info.产品代码
    holder_codes = set(db["zysc_ptl_holder_records"].distinct("产品代码"))
    info_codes = set(db["zysc_ptl_info_records"].distinct("产品代码"))
    orphan_holder = holder_codes - info_codes
    check("holder.产品代码 ⊆ ptl_info.产品代码", len(orphan_holder) == 0,
          f"{len(orphan_holder)} orphans: {list(orphan_holder)[:3]}")

    # ptl_ast_hld.PORT_ID ⊆ dwd_ptl_info.PORT_ID
    hld_ports = set(db["dwd_ptl_ast_hld"].distinct("PORT_ID"))
    dwd_ports = set(db["dwd_ptl_info"].distinct("PORT_ID"))
    orphan_hld = hld_ports - dwd_ports
    check("ptl_ast_hld.PORT_ID ⊆ dwd_ptl_info.PORT_ID", len(orphan_hld) == 0,
          f"{len(orphan_hld)} orphans: {list(orphan_hld)[:3]}")

    # ptl_ast_hld.AST_CD ⊆ dwd_ast_info.AST_CD
    hld_asts = set(db["dwd_ptl_ast_hld"].distinct("AST_CD"))
    ast_codes = set(db["dwd_ast_info"].distinct("AST_CD"))
    orphan_ast = hld_asts - ast_codes
    check("ptl_ast_hld.AST_CD ⊆ dwd_ast_info.AST_CD", len(orphan_ast) == 0,
          f"{len(orphan_ast)} orphans: {list(orphan_ast)[:3]}")

    # ─── 3. 时间维度连续性 ───
    print("\n>>> 3. 时间维度连续性")

    # 风险记录每月有数据
    risk_months = set()
    for d in db["subject_risk_records"].aggregate([
        {"$project": {"month": {"$substr": ["$biz_date", 0, 7]}}},
        {"$group": {"_id": "$month"}},
    ]):
        risk_months.add(d["_id"])
    check("风险记录覆盖 >= 20 个月", len(risk_months) >= 20, f"actual={len(risk_months)} months")

    # 持有人每季有数据
    holder_periods = sorted(db["zysc_ptl_holder_records"].distinct("生效日期"))
    check("持有人覆盖 >= 12 个报告期", len(holder_periods) >= 12, f"actual={len(holder_periods)} periods")

    # ─── 4. 批次溯源可查 ───
    print("\n>>> 4. 批次溯源可查")

    risk_batches = set(db["subject_risk_records"].distinct("_batch_id"))
    batch_ids = set(db["subject_risk_import_batches"].distinct("batch_id"))
    orphan_batch = risk_batches - batch_ids
    check("risk._batch_id 全部在 batches 表中", len(orphan_batch) <= 2,
          f"{len(orphan_batch)} orphans (允许<=2个历史遗留)")

    # ─── 5. 分布合理性 ───
    print("\n>>> 5. 分布合理性")

    # 风险等级分布：高应占15-35%
    total_risk = db["subject_risk_records"].count_documents({})
    high_risk = db["subject_risk_records"].count_documents({"risk_signal_level": "高"})
    high_pct = high_risk / total_risk if total_risk > 0 else 0
    check("高风险占比 15-35%", 0.15 <= high_pct <= 0.35, f"actual={high_pct:.1%}")

    # 产品风险等级：R3 应最多
    r3_count = db["zysc_ptl_info_records"].count_documents({"风险等级": "R3"})
    total_ptl = db["zysc_ptl_info_records"].count_documents({})
    check("R3 产品占比最高 (>=35%)", r3_count / total_ptl >= 0.35, f"R3={r3_count}/{total_ptl}")

    # 管理人分散（>= 2个）
    managers = db["zysc_ptl_info_records"].distinct("管理人")
    check("管理人 >= 2 个", len(managers) >= 2, f"actual={len(managers)}: {managers}")

    # 行业覆盖 >= 8 个
    industries = db["subject_risk_records"].distinct("industry_classification_gb")
    check("行业覆盖 >= 8 个", len(industries) >= 8, f"actual={len(industries)}")

    # 省份覆盖 >= 10 个
    provinces = db["subject_risk_records"].distinct("affiliated_province")
    check("省份覆盖 >= 10 个", len(provinces) >= 10, f"actual={len(provinces)}")

    # ─── 6. L3 穿透闭环验证 ───
    print("\n>>> 6. L3 穿透闭环验证")

    # risk主体 → ISR_ID → AST_CD → 持仓 PORT_ID
    # 验证至少有一个高风险主体的发行资产被某产品持有
    high_risk_names = db["subject_risk_records"].distinct("subject_name", {"risk_signal_level": "高"})
    if high_risk_names:
        # 找到这些主体在 ISR 表中的 ISR_ID
        isr_ids = db["dwd_isr_institution"].distinct("ISR_ID", {"ISR_NM": {"$in": high_risk_names}})
        # 找到这些 ISR_ID 发行的资产
        ast_by_isr = db["dwd_ast_info"].distinct("AST_CD", {"ISR_ID": {"$in": isr_ids}}) if isr_ids else []
        # 这些资产是否被某产品持有
        held = db["dwd_ptl_ast_hld"].count_documents({"AST_CD": {"$in": ast_by_isr}}) if ast_by_isr else 0
        check("L3穿透: 高风险主体→资产→持仓有交集", held > 0,
              f"high_risk_subjects={len(high_risk_names)}, isr_ids={len(isr_ids)}, asts={len(ast_by_isr)}, held={held}")
    else:
        check("L3穿透: 有高风险主体", False, "无高风险数据")

    # ─── 汇总 ───
    print("\n" + "=" * 70)
    total = checks_passed + checks_failed
    print(f"验证完成: {checks_passed}/{total} 通过, {checks_failed} 失败")
    if checks_failed == 0:
        print("ALL CHECKS PASSED!")
    print("=" * 70)

    client.close()
    return checks_failed


if __name__ == "__main__":
    sys.exit(main())
