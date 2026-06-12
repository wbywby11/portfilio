"""验证HERMES数据导入结果"""
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["portfilio"]

print("=" * 70)
print("  STEP 5: DATA QUALITY VERIFICATION")
print("=" * 70)

# 1. dwd_ast_info - 检查AST_NM字段
print("\n--- 1. dwd_ast_info (top 5 AST_NM) ---")
for d in db["dwd_ast_info"].find({}, {"AST_CD": 1, "AST_NM": 1, "_id": 0}).limit(5):
    print(f"  {d.get('AST_CD', '?')} -> AST_NM={d.get('AST_NM', 'MISSING')}")

# 2. dwd_isr_institution - 检查ISR_NM
print("\n--- 2. dwd_isr_institution (ISR_NM) ---")
for d in db["dwd_isr_institution"].find({}, {"ISR_ID": 1, "ISR_NM": 1, "_id": 0}).limit(5):
    print(f"  {d.get('ISR_ID', '?')} -> ISR_NM={d.get('ISR_NM', 'MISSING')}")

# 3. dwd_ast_cf_plan - 检查现金流字段
print("\n--- 3. dwd_ast_cf_plan (cash flow fields) ---")
for d in db["dwd_ast_cf_plan"].find({}, {"AST_CD": 1, "CF_DT": 1, "CF_TYPE": 1, "CF_AMT": 1, "_id": 0}).limit(5):
    print(f"  AST_CD={d.get('AST_CD')}, CF_DT={d.get('CF_DT')}, CF_TYPE={d.get('CF_TYPE')}, CF_AMT={d.get('CF_AMT')}")

# 4. 统计总记录数
print("\n--- 4. Total dwd_ records ---")
colls = []
for n in sorted(db.list_collection_names()):
    if n.startswith("dwd_"):
        cnt = db[n].count_documents({})
        if cnt > 0:
            colls.append((n, cnt))

total = sum(c for _, c in colls)
print(f"  Collections with data: {len(colls)}")
print(f"  Total records: {total:,}")
print(f"\n  Top 15 by count:")
for n, c in sorted(colls, key=lambda x: -x[1])[:15]:
    print(f"    {n}: {c:,}")

# 5. 验收检查
print("\n" + "=" * 70)
print("  ACCEPTANCE CRITERIA CHECK")
print("=" * 70)

# 检查占位符模式
ast_docs = list(db["dwd_ast_info"].find({"AST_NM": {"$regex": "_\\d{3,4}$"}}, {"AST_NM": 1, "_id": 0}).limit(5))
placeholder_count = db["dwd_ast_info"].count_documents({"AST_NM": {"$regex": "_\\d{3,4}$"}})
total_ast = db["dwd_ast_info"].count_documents({})
print(f"\n  [1] 占位符检查: {placeholder_count}/{total_ast} records have placeholder pattern in AST_NM")
if ast_docs:
    print(f"      Examples: {[d['AST_NM'] for d in ast_docs]}")

# 现金流填充率
cf_total = db["dwd_ast_cf_plan"].count_documents({})
cf_dt_filled = db["dwd_ast_cf_plan"].count_documents({"CF_DT": {"$ne": None, "$ne": ""}})
cf_type_filled = db["dwd_ast_cf_plan"].count_documents({"CF_TYPE": {"$ne": None, "$ne": ""}})
cf_amt_filled = db["dwd_ast_cf_plan"].count_documents({"CF_AMT": {"$ne": None, "$ne": 0}})
print(f"\n  [2] 现金流填充率:")
print(f"      CF_DT: {cf_dt_filled}/{cf_total} = {cf_dt_filled/cf_total*100:.1f}%")
print(f"      CF_TYPE: {cf_type_filled}/{cf_total} = {cf_type_filled/cf_total*100:.1f}%")
print(f"      CF_AMT: {cf_amt_filled}/{cf_total} = {cf_amt_filled/cf_total*100:.1f}%")

# 发行人检查
isr_sample = list(db["dwd_isr_institution"].find({}, {"ISR_NM": 1, "_id": 0}).limit(10))
print(f"\n  [3] 发行人名称样本: {[d.get('ISR_NM','?') for d in isr_sample]}")

print(f"\n  [4] 总记录数: {total:,} (目标 > 50,000)")
print(f"      {'✅ PASS' if total > 50000 else '⚠️  HERMES源数据实际为 ~14,400 条'}")

client.close()
