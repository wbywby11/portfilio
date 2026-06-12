"""验证 data_hub 数据关联性与分析价值"""
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["asset_allocation"]

print("=" * 70)
print("  data_hub 数据关联性验证报告")
print("=" * 70)

# 1. subject_risk_records 与 dwd_isr_institution 主体名称匹配
risk_names = set(db["subject_risk_records"].distinct("subject_name"))
isr_names = set(db["dwd_isr_institution"].distinct("ISR_NM"))
matched = risk_names & isr_names
print(f"\n[1] 风险主体 ↔ 主体域 名称匹配")
print(f"    风险表主体数: {len(risk_names)}")
print(f"    主体域机构数: {len(isr_names)}")
print(f"    匹配数量: {len(matched)}")
print(f"    匹配主体: {', '.join(sorted(matched)[:10])}...")

# 风险等级分布
print(f"\n[2] 风险等级分布:")
pipeline = [{"$group": {"_id": "$risk_signal_level", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
for d in db["subject_risk_records"].aggregate(pipeline):
    print(f"    {d['_id']}: {d['count']} 条 ({d['count']/40*100:.0f}%)")

# 高风险主体
print(f"\n[3] 高风险主体:")
for d in db["subject_risk_records"].find({"risk_signal_level": "高"}, {"subject_name": 1, "enterprise_nature": 1, "rule_medium": 1}):
    print(f"    {d['subject_name']} ({d['enterprise_nature']}) — {d['rule_medium']}")

# 2. zysc_ptl_info_records 与 dwd_ptl_info 产品匹配
ptl_codes = set(db["zysc_ptl_info_records"].distinct("产品代码"))
dwd_codes = set(db["dwd_ptl_info"].distinct("PORT_ID"))
matched_ptl = ptl_codes & dwd_codes
print(f"\n[4] 产品信息 ↔ 产品域 产品代码匹配")
print(f"    外部产品数: {len(ptl_codes)}")
print(f"    产品域产品数: {len(dwd_codes)}")
print(f"    匹配数量: {len(matched_ptl)} ({len(matched_ptl)/len(ptl_codes)*100:.0f}%)")

# 产品风险等级分布
print(f"\n[5] 产品风险等级分布:")
pipeline = [{"$group": {"_id": "$风险等级", "count": {"$sum": 1}}}, {"$sort": {"_id": 1}}]
for d in db["zysc_ptl_info_records"].aggregate(pipeline):
    print(f"    {d['_id']}: {d['count']} 个")

# 3. zysc_ptl_holder_records 持有人结构分析
print(f"\n[6] 持有人结构分析 (第一期 2025-06-30):")
pipeline = [
    {"$match": {"生效日期": "2025-06-30"}},
    {"$addFields": {"total_shr": {"$add": ["$机构份额", "$个人份额"]}}},
    {"$project": {"产品代码": 1, "inst_ratio": {"$divide": ["$机构份额", "$total_shr"]}, "_id": 0}},
    {"$sort": {"inst_ratio": -1}},
    {"$limit": 5}
]
print(f"    机构占比 TOP5:")
for d in db["zysc_ptl_holder_records"].aggregate(pipeline):
    print(f"      {d['产品代码']}: 机构 {d['inst_ratio']*100:.1f}%")

# 两期变化对比
print(f"\n[7] 持有人结构变化 (第一期→第二期):")
p1 = {d["产品代码"]: d for d in db["zysc_ptl_holder_records"].find({"生效日期": "2025-06-30"})}
p2 = {d["产品代码"]: d for d in db["zysc_ptl_holder_records"].find({"生效日期": "2025-12-31"})}
changes = []
for code in p1:
    if code in p2:
        r1 = p1[code]["机构份额"] / (p1[code]["机构份额"] + p1[code]["个人份额"]) if (p1[code]["机构份额"] + p1[code]["个人份额"]) > 0 else 0
        r2 = p2[code]["机构份额"] / (p2[code]["机构份额"] + p2[code]["个人份额"]) if (p2[code]["机构份额"] + p2[code]["个人份额"]) > 0 else 0
        changes.append((code, r1, r2, r2 - r1))
changes.sort(key=lambda x: abs(x[3]), reverse=True)
print(f"    机构占比变化最大 TOP5:")
for code, r1, r2, delta in changes[:5]:
    print(f"      {code}: {r1*100:.1f}% → {r2*100:.1f}% ({'+' if delta > 0 else ''}{delta*100:.1f}%)")

# 4. 批次表验证
print(f"\n[8] 导入批次表:")
for col in ["subject_risk_import_batches", "zysc_ptl_info_import_batches", "zysc_ptl_holder_import_batches"]:
    docs = list(db[col].find())
    print(f"    {col}: {len(docs)} 批次, 状态: {[d['status'] for d in docs]}")

# 5. 跨域穿透能力
print(f"\n[9] 跨域穿透示例:")
# 高风险主体 → 是否有对应产品持有其债券
high_risk_names = list(db["subject_risk_records"].find({"risk_signal_level": "高"}).distinct("subject_name"))
print(f"    高风险主体: {high_risk_names[:3]}...")
# 检查这些主体在资产域是否有债券
for name in high_risk_names[:3]:
    bonds = list(db["dwd_ast_info"].find({"AST_NM": {"$regex": name[:4]}}))
    print(f"    '{name[:4]}' 关联债券数: {len(bonds)}")

print("\n" + "=" * 70)
print("  验证完成")
print("=" * 70)
client.close()
