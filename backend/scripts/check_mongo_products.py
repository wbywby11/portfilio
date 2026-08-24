# -*- coding: utf-8 -*-
"""Check product documents in MongoDB directly"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

for p in db["option_products"].find({}, {"product_id": 1, "underlying": 1, "underlying_asset": 1, "params": 1}).limit(3):
    print(f"{p.get('product_id')}:")
    print(f"  underlying: '{p.get('underlying', '')}'")
    print(f"  underlying_asset: '{p.get('underlying_asset', '')}'")
    params = p.get("params", {})
    print(f"  params keys: {list(params.keys())[:8]}")
    print(f"  params.underlying: '{params.get('underlying', '')}'")
    print()

c.close()
