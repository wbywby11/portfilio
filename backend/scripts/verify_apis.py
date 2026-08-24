# -*- coding: utf-8 -*-
"""验证估值模块所有API端点"""
import requests

BASE = "http://localhost:8000/api/v1/options"

print("=== 估值模块 API 验证 ===\n")

# 1. 估值数据 - 获取可用标的
print("[1] GET /valuation-data/assets")
r = requests.get(f"{BASE}/valuation-data/assets")
print(f"    Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()["data"]
    print(f"    标的数: {len(data)}")
    for a in data[:3]:
        print(f"      {a['asset_code']}: {a['count']}条, {a['earliest_date']}~{a['latest_date']}, close={a['latest_close']}")
else:
    print(f"    ERROR: {r.text[:200]}")

# 2. 估值数据 - 获取行情
if r.status_code == 200 and data:
    code = data[0]["asset_code"]
    print(f"\n[2] GET /valuation-data/prices/{code}")
    r2 = requests.get(f"{BASE}/valuation-data/prices/{code}", params={"limit": 5})
    print(f"    Status: {r2.status_code}")
    if r2.status_code == 200:
        prices = r2.json()["data"]
        print(f"    返回 {len(prices)} 条行情")
        for p in prices[:2]:
            print(f"      {p['date']}: close={p['close']}, vol={p.get('volume')}")

# 3. 产品列表
print(f"\n[3] GET /products")
r3 = requests.get(f"{BASE}/products")
print(f"    Status: {r3.status_code}")
if r3.status_code == 200:
    products = r3.json()["data"]
    print(f"    产品数: {len(products)}")
    for p in products[:3]:
        print(f"      {p.get('product_id')}: {p.get('product_name')} ({p.get('type')})")

# 4. 估值历史
print(f"\n[4] GET /valuation/history")
r4 = requests.get(f"{BASE}/valuation/history")
print(f"    Status: {r4.status_code}")
if r4.status_code == 200:
    history = r4.json()["data"]
    print(f"    历史记录: {len(history)} 条")

# 5. 估值快照
print(f"\n[5] GET /valuation/snapshot/2026-06-22")
r5 = requests.get(f"{BASE}/valuation/snapshot/2026-06-22")
print(f"    Status: {r5.status_code}")
if r5.status_code == 200:
    snap = r5.json()["data"]
    if snap:
        print(f"    快照日期: {snap.get('date')}, 版本: v{snap.get('version')}")
        print(f"    总估值: {snap.get('snapshot', {}).get('total_value', 0):,.2f}")

print("\n=== 验证完成 ===")
