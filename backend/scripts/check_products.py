# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests

BASE = "http://localhost:8000/api/v1/options"
r = requests.get(f"{BASE}/products")
products = r.json()["data"]
for p in products:
    ua = p.get("underlying_asset", "")
    params_u = p.get("params", {}).get("underlying", "")
    print(f"{p['product_id']}: underlying_asset='{ua}', params.underlying='{params_u}'")
