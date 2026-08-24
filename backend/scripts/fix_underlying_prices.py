# -*- coding: utf-8 -*-
"""补充 SH000300 和 SZ399006 近6天的指数级别行情"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import MongoClient
from pymongo.operations import UpdateOne
from datetime import datetime, timedelta

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

today = datetime.now().date()

def trading_dates_ending(ref_date, n):
    dates = []
    d = ref_date
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d -= timedelta(days=1)
    return list(reversed(dates))

dates = trading_dates_ending(today, 6)

configs = {
    "SH000300": {"spot_base": 3850.0},
    "SZ399006": {"spot_base": 2100.0},
}

ops = []
for i, d in enumerate(dates):
    ds = d.isoformat()
    for code, cfg in configs.items():
        phase = i * 0.3
        spot = cfg["spot_base"] * (1 + 0.02 * math.sin(phase) + 0.005 * (i - 2.5))
        spot = round(spot, 2)
        ops.append(UpdateOne(
            {"asset_code": code, "date": ds},
            {"$set": {
                "close": spot,
                "open": round(spot * 0.998, 2),
                "high": round(spot * 1.01, 2),
                "low": round(spot * 0.99, 2),
                "volume": 100000000,
                "amount": 5000000000,
            }},
            upsert=True,
        ))

if ops:
    result = db["asset_prices"].bulk_write(ops, ordered=False)
    print(f"Updated: {result.modified_count}, Inserted: {result.upserted_count}")

# Verify
for code in configs:
    latest = db["asset_prices"].find_one({"asset_code": code}, sort=[("date", -1)])
    print(f"  {code}: latest={latest['date']} close={latest['close']}")

c.close()
print("Done")
