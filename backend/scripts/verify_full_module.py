# -*- coding: utf-8 -*-
"""全面验证期权模块数据 + 接口"""
import requests
BASE = "http://127.0.0.1:8000/api/v1/options"

def get(path):
    r = requests.get(f"{BASE}{path}")
    return r.status_code, r.json() if r.ok else r.text

def post(path, data=None):
    r = requests.post(f"{BASE}{path}", json=data or {})
    return r.status_code, r.json() if r.ok else r.text

print("=== 接口验证 ===\n")

# 1. 产品列表
s, d = get("/products")
products = d.get("data", []) if s == 200 else []
print(f"[1] 产品列表: {s} -> {len(products)} 个产品")
for p in products:
    print(f"  {p['product_id']:12s} type={p['type']:16s} underlying={p['underlying']}")

# 2. 市场数据 (最新日期)
s, d = get("/market-data/2026-06-22")
mkt = d.get("data", []) if s == 200 else []
print(f"\n[2] 市场数据 2026-06-22: {s} -> {len(mkt)} 条")
for m in mkt:
    print(f"  {m['underlying']:10s} spot={m['spot']:.2f} vol_1m={m.get('vol_1m',0)*100:.1f}%")

# 3. 波动率曲面
s, d = get("/vol-surface")
surfaces = d.get("data", []) if s == 200 else []
print(f"\n[3] 波动率曲面: {s} -> {len(surfaces)} 个")
for vs in surfaces[:3]:
    code = vs.get("underlying", "?")
    has_grid = "tenor_grid" in vs
    grid_size = f"{len(vs.get('moneyness_grid',[]))}x{len(vs.get('tenor_grid',[]))}" if has_grid else "no grid"
    print(f"  {code} date={vs.get('date','?')} grid={grid_size}")

# 4. 期权合约
from pymongo import MongoClient
c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]
contract_cnt = db["option_contracts"].count_documents({})
iv_cnt = db["option_iv_data"].count_documents({})
print(f"\n[4] MongoDB 数据:")
print(f"  option_contracts: {contract_cnt}")
print(f"  option_iv_data: {iv_cnt}")

# 5. 估值运行
s, d = post("/valuation/run", {"date": "2026-06-22", "skip_lifecycle": True})
print(f"\n[5] 估值运行: {s}")
if s == 200:
    result = d.get("data", {})
    if result.get("error"):
        print(f"  ERROR: {result['error']}")
    else:
        print(f"  version={result.get('version')} success={result['success_count']} error={result['error_count']} total={result['total_value']:,.2f}")
        for p in result.get("products", []):
            pct = (p['price_total']/p['principal']-1)*100 if p['principal'] > 0 else 0
            err = f" ERR:{p['error'][:25]}" if p.get("error") else ""
            print(f"    {p['product_id']:12s} {p['type']:16s} price={p['price_total']:>14,.2f} ({pct:+.2f}%){err}")
else:
    print(f"  {d}")

# 6. 会计分录生成
s, d = post("/accounting/generate", {"date": "2026-06-22"})
print(f"\n[6] 会计分录生成: {s}")
if s == 200:
    r = d.get("data", {})
    print(f"  entries={r.get('total_entries', 0)}")
else:
    print(f"  {d[:200] if isinstance(d, str) else d}")

c.close()
print("\n=== 验证完成 ===")
