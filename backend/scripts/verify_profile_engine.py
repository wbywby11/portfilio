"""验证 ProfileEngine 加载与语义画像内容"""
import sys
sys.path.insert(0, r"d:\portfilio-end")

from app.services.semantic_profiles.profile_engine import ProfileEngine

engine = ProfileEngine.get_instance()
print(f"域概览: {len(engine._domain_overviews)} 个")
print(f"表画像: {len(engine._table_profiles)} 个")
print(f"L2画像: {len(engine._intra_domain_profiles)} 个")
print(f"L3画像: {len(engine._cross_domain_profiles)} 个")

# 检查 data_hub 画像
print("\n=== data_hub 域概览 ===")
ov = engine._domain_overviews.get("data_hub")
if ov:
    print(f"  域名称: {ov.domain_name}")
    print(f"  表数量: {ov.table_count}")
    print(f"  核心场景: {ov.core_scenarios[:3]}...")

print("\n=== data_hub 表画像 ===")
for t in ["subject_risk_records", "zysc_ptl_info_records", "zysc_ptl_holder_records"]:
    p = engine._table_profiles.get(t)
    if p:
        print(f"  {t}: distribution[:80]={p.distribution[:80]}...")

print("\n=== data_hub L2 ===")
l2 = engine._intra_domain_profiles.get("data_hub")
if l2:
    print(f"  consistency[:80]={l2.consistency[:80]}...")
    print(f"  distribution[:120]={l2.distribution[:120]}...")
else:
    print(f"  data_hub L2: NOT FOUND")
    print(f"  available keys: {list(engine._intra_domain_profiles.keys())}")

print("\n=== data_hub L3 ===")
# Try both key formats
l3_found = False
for lid in ["datahub_risk_subject", "datahub_product_bridge", "l3_datahub_risk_subject", "l3_datahub_product_bridge"]:
    l3 = engine._cross_domain_profiles.get(lid)
    if l3:
        print(f"  {lid}: found! profile_name={l3.profile_name}")
        print(f"    join_path[:80]={l3.join_path[:80]}...")
        l3_found = True
if not l3_found:
    print(f"  NOT FOUND. available keys: {list(engine._cross_domain_profiles.keys())}")

print("\n验证完成!")
