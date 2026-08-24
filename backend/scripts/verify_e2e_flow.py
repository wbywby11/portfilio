# -*- coding: utf-8 -*-
"""端到端验证：估值数据 -> 产品管理 -> 估值工作台 -> 估值历史 -> 核算辅助"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests

BASE = "http://localhost:8000/api/v1/options"

print("=" * 60)
print("  E2E Data Flow Verification")
print("  valuation-data -> products -> workbench -> history -> accounting")
print("=" * 60)

# Step 1: 估值数据 (asset_prices)
print("\n[Step 1] 估值数据源 - asset_prices 可用标的")
r = requests.get(f"{BASE}/valuation-data/assets")
assert r.status_code == 200, f"FAIL: {r.status_code}"
assets = r.json()["data"]
print(f"  [OK] {len(assets)} assets available")
# 确认产品使用的标的在数据源中
product_codes = set()

# Step 2: 产品管理 - 产品定义引用估值数据中的标的
print("\n[Step 2] 产品管理 - 产品定义")
r = requests.get(f"{BASE}/products")
assert r.status_code == 200, f"FAIL: {r.status_code}"
products = r.json()["data"]
print(f"  [OK] {len(products)} products")
asset_codes_in_data = {a["asset_code"] for a in assets}
for p in products:
    ua = p.get("underlying_asset", "")
    product_codes.add(p.get("product_id"))
    status = "[OK]" if ua in asset_codes_in_data else "[WARN]"
    print(f"    {status} {p.get('product_id')}: asset={ua}, type={p.get('type')}, principal={p.get('principal', 0):,.0f}")

# Step 3: 估值工作台 - 运行估值（只验证快照存在）
print("\n[Step 3] 估值工作台 - 估值快照")
r = requests.get(f"{BASE}/valuation/snapshot/2026-06-22")
assert r.status_code == 200, f"FAIL: {r.status_code}"
snap = r.json()["data"]
print(f"  [OK] date: {snap['date']}, version: v{snap['version']}")
print(f"    total_value: {snap['snapshot']['total_value']:,.2f}")
print(f"    total_products: {snap['snapshot']['total_products']}")
print(f"    success_count: {snap['snapshot']['success_count']}")
print(f"    error_count: {snap['snapshot'].get('error_count', 0)}")

# Step 4: 估值历史 - 读取工作台产出的历史记录
print("\n[Step 4] 估值历史 - 回溯估值结果")
r = requests.get(f"{BASE}/valuation/history", params={"limit": 50})
assert r.status_code == 200, f"FAIL: {r.status_code}"
history = r.json()["data"]
print(f"  [OK] {len(history)} history records")
# count products covered
hist_products = set(h.get("product_id") for h in history)
print(f"    products covered: {len(hist_products)}")
for h in history[:3]:
    print(f"    {h.get('date')} | {h.get('product_id')} | {h.get('price_total', 0):,.2f}")

# Step 5: 核算辅助 - 基于估值快照生成报告
print("\n[Step 5] 核算辅助 - 估值报告模板化输出")
# 核算辅助读取的就是 valuation snapshot 数据
if snap:
    details = snap["snapshot"].get("details", [])
    print(f"  [OK] report ready: {len(details)} product details")
    for d in details[:3]:
        print(f"    {d.get('product_id')}: {d.get('type')} | "
              f"principal={d.get('principal', 0):,.0f} | "
              f"value={d.get('price_total', 0):,.2f} | "
              f"method={d.get('method')}")

# 数据流完整性检查
print("\n" + "=" * 60)
print("  数据流完整性检查")
print("=" * 60)
checks = [
    ("valuation-data has assets", len(assets) > 0),
    ("products defined", len(products) > 0),
    ("snapshot valid", snap is not None and snap.get("snapshot", {}).get("total_value", 0) > 0),
    ("history exists", len(history) > 0),
    ("accounting data ready", snap is not None and len(snap.get("snapshot", {}).get("details", [])) > 0),
]
all_pass = True
for name, ok in checks:
    symbol = "[PASS]" if ok else "[FAIL]"
    print(f"  {symbol} {name}")
    if not ok:
        all_pass = False

print(f"\n{'  [PASS] All checks passed! E2E data flow is intact.' if all_pass else '  [FAIL] Data flow broken, please check.'}")
print("=" * 60)
