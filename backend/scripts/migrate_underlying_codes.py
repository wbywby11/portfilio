# -*- coding: utf-8 -*-
"""
Migration: Unify product underlying codes to match asset_prices format.
SH000300 -> 000300.SH
SZ000001 -> 000001.SZ
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

# Get available asset codes from asset_prices
asset_codes = set()
for doc in db["asset_prices"].aggregate([{"$group": {"_id": "$asset_code"}}]):
    asset_codes.add(doc["_id"])

print(f"asset_prices codes sample: {sorted(list(asset_codes))[:5]}")

def convert_code(old_code):
    """Convert SH000300 -> 000300.SH, SZ000001 -> 000001.SZ"""
    if not old_code:
        return ""
    # Already in target format
    if "." in old_code:
        return old_code
    # SH/SZ prefix format
    if old_code.startswith("SH") and len(old_code) > 2:
        return old_code[2:] + ".SH"
    if old_code.startswith("SZ") and len(old_code) > 2:
        return old_code[2:] + ".SZ"
    return old_code

print("\n=== Product underlying migration ===\n")
updated = 0
for p in db["option_products"].find({}):
    old = p.get("underlying", "")
    new = convert_code(old)
    if old != new:
        # Verify new code exists in asset_prices
        exists = new in asset_codes
        status = "OK" if exists else "NOT_FOUND"
        print(f"  {p['product_id']}: '{old}' -> '{new}' [{status}]")
        db["option_products"].update_one(
            {"_id": p["_id"]},
            {"$set": {"underlying": new, "underlying_asset": new}}
        )
        updated += 1
    else:
        print(f"  {p['product_id']}: '{old}' (no change)")

print(f"\n=== Updated {updated} products ===")

# Verify
print("\n=== Verification ===")
for p in db["option_products"].find({}, {"product_id": 1, "underlying": 1}):
    in_data = p.get("underlying", "") in asset_codes
    mark = "[OK]" if in_data else "[WARN]"
    print(f"  {mark} {p['product_id']}: {p.get('underlying', '')}")

c.close()
