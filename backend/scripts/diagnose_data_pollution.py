# -*- coding: utf-8 -*-
"""诊断数据污染情况：区分种子数据 vs tushare真实数据"""
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

print("=== 数据污染诊断 ===\n")

# 1. option_products - 检查哪些是种子数据
print("[1] option_products")
for p in db["option_products"].find({}, {"product_id":1, "type":1, "underlying":1, "created_at":1, "params":1}):
    params = p.get("params", {})
    spot_ref = params.get("spot_ref", "N/A")
    created = p.get("created_at", "unknown")
    print(f"  {p['product_id']:12s} type={p['type']:16s} underlying={p['underlying']:10s} spot_ref={spot_ref} created={created}")

# 2. option_market_data - 检查来源
print("\n[2] option_market_data")
for m in db["option_market_data"].find({}).sort("date", -1).limit(10):
    src = m.get("data_source", "seed/manual")
    print(f"  date={m['date']} underlying={m['underlying']:10s} spot={m['spot']:.2f} source={src}")

# 3. option_valuations - 检查版本
print("\n[3] option_valuations (versions)")
for v in db["option_valuations"].find({}, {"date":1, "version":1, "is_final":1, "snapshot.total_value":1, "snapshot.success_count":1}):
    sv = v.get("snapshot", {})
    print(f"  date={v.get('date')} v{v.get('version')} final={v.get('is_final',False)} "
          f"value={sv.get('total_value',0):,.2f} success={sv.get('success_count',0)}")

# 4. option_vol_surfaces - 检查来源
print("\n[4] option_vol_surfaces")
for vs in db["option_vol_surfaces"].find({}, {"underlying":1, "date":1, "moneyness_grid":1, "tenor_grid":1, "updated_at":1}):
    m_grid = vs.get("moneyness_grid", [])
    t_grid = vs.get("tenor_grid", [])
    grid = f"{len(m_grid)}x{len(t_grid)}" if m_grid else "no grid"
    print(f"  {vs.get('underlying'):10s} date={vs.get('date','?')} grid={grid} updated={vs.get('updated_at','?')}")

# 5. option_contracts
print(f"\n[5] option_contracts: {db['option_contracts'].count_documents({})}")

# 6. option_iv_data
print(f"[6] option_iv_data: {db['option_iv_data'].count_documents({})}")

# 7. option_lifecycle_events
print(f"[7] option_lifecycle_events: {db['option_lifecycle_events'].count_documents({})}")

# 8. option_accounting_entries
print(f"[8] option_accounting_entries: {db['option_accounting_entries'].count_documents({})}")

# 9. option_valuation_history
print(f"[9] option_valuation_history: {db['option_valuation_history'].count_documents({})}")
for h in db["option_valuation_history"].find({}).sort("date", -1).limit(5):
    print(f"  date={h.get('date')} product={h.get('product_id')} price={h.get('price_total',0):,.2f}")

# 10. asset_prices (主系统数据 - tushare真实数据)
print(f"\n[10] asset_prices: {db['asset_prices'].count_documents({})} (tushare真实数据)")
for code in ["SH000300", "SH000016", "SH000905", "SZ399006"]:
    cnt = db["asset_prices"].count_documents({"asset_code": code})
    latest = db["asset_prices"].find_one({"asset_code": code}, sort=[("date", -1)])
    if latest:
        print(f"  {code}: {cnt} docs, latest={latest['date']} close={latest['close']:.4f}")

# 11. 检查 option_market_data 和 asset_prices 的价格是否一致
print("\n[11] 价格一致性检查")
mkt = list(db["option_market_data"].find({"date": "2026-06-22"}))
for m in mkt:
    code = m["underlying"]
    ap = db["asset_prices"].find_one({"asset_code": code, "date": "2026-06-22"})
    mkt_spot = m["spot"]
    ap_close = ap["close"] if ap else None
    match = "MATCH" if ap_close and abs(mkt_spot - ap_close) < 0.01 else "MISMATCH"
    print(f"  {code}: market_data={mkt_spot:.4f} asset_prices={ap_close} {match}")

c.close()
print("\n=== 诊断完成 ===")
