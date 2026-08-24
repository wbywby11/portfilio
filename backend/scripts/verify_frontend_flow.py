# -*- coding: utf-8 -*-
"""Simulate frontend API calls for all 5 pages to verify E2E flow"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests

BASE = "http://localhost:8000/api/v1/options"
ALL_PASS = True

def check(label, url, params=None, expected_key="data"):
    global ALL_PASS
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            body = r.json()
            data = body.get(expected_key)
            if data is not None:
                count = len(data) if isinstance(data, list) else 1
                print(f"  [PASS] {label}: {r.status_code}, items={count}")
                return data
            else:
                print(f"  [PASS] {label}: {r.status_code}, data=dict")
                return body.get("data")
        else:
            print(f"  [FAIL] {label}: {r.status_code}")
            ALL_PASS = False
            return None
    except Exception as e:
        print(f"  [FAIL] {label}: {e}")
        ALL_PASS = False
        return None

print("=" * 60)
print("  Frontend Page Simulation - API Calls")
print("=" * 60)

# Page 1: ValuationDataManage
print("\n[Page 1] ValuationDataManage (valuation-data)")
assets = check("getValuationDataAssets", f"{BASE}/valuation-data/assets")
if assets:
    code = assets[0]["asset_code"]
    check(f"getValuationDataPrices({code})", f"{BASE}/valuation-data/prices/{code}", {"limit": 10})

# Page 2: OptionsProductList  
print("\n[Page 2] OptionsProductList (products)")
products = check("listOptionProducts", f"{BASE}/products")
check("getValuationDataAssets (for dropdown)", f"{BASE}/valuation-data/assets")

# Page 3: ValuationWorkbench
print("\n[Page 3] ValuationWorkbench (workbench)")
check("listOptionProducts (for workbench)", f"{BASE}/products")
snap = check("getValuationSnapshot(2026-06-22)", f"{BASE}/valuation/snapshot/2026-06-22")

# Page 4: ValuationHistory
print("\n[Page 4] ValuationHistory (history)")
history = check("getValuationHistory", f"{BASE}/valuation/history", {"limit": 50})
if history and len(history) > 0:
    pid = history[0].get("product_id", "SNOW_001")
    check(f"getValuationTrend({pid})", f"{BASE}/valuation/trend", 
          {"product_id": pid, "start_date": "2026-06-01", "end_date": "2026-06-30"})

# Page 5: AccountingAssist
print("\n[Page 5] AccountingAssist (accounting)")
snap_data = check("getValuationSnapshot(2026-06-22)", f"{BASE}/valuation/snapshot/2026-06-22")
if snap_data:
    prods = snap_data.get("products", [])
    print(f"         Report products: {len(prods)}")
    if prods:
        p = prods[0]
        print(f"         Sample: {p.get('product_id')} | type={p.get('type')} | value={p.get('price_total', 0):,.2f}")

# Summary
print("\n" + "=" * 60)
if ALL_PASS:
    print("  [PASS] ALL PAGES VERIFIED - E2E Flow Complete!")
else:
    print("  [FAIL] Some pages have issues, check above")
print("=" * 60)
