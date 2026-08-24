# -*- coding: utf-8 -*-
"""更新种子产品数据匹配真实市场价格 + 运行估值验证"""
from pymongo import MongoClient
from datetime import datetime

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

# 获取最新市场价格
prices = {}
for code in ["SH000300", "SH000016", "SH000905", "SZ399006"]:
    doc = db["asset_prices"].find_one({"asset_code": code}, sort=[("date", -1)])
    if doc:
        prices[code] = doc["close"]
        print(f"  {code}: {doc['date']} close={doc['close']:.2f}")

print()

# 更新产品参数 (spot_ref = 当前市场价)
updates = [
    # SNOW_001: 雪球, 沪深300, spot_ref应为当前指数价
    {"product_id": "SNOW_001", "params.spot_ref": prices.get("SH000300", 5059.66),
     "params.knock_out": 1.03, "params.knock_in": 0.75, "params.coupon_year": 0.18},
    # SNOW_002: 雪球, 中证500
    {"product_id": "SNOW_002", "params.spot_ref": prices.get("SH000905", 8868.78),
     "params.knock_out": 1.05, "params.knock_in": 0.70, "params.coupon_year": 0.20},
    # PHX_001: 凤凰, 上证50
    {"product_id": "PHX_001", "params.spot_ref": prices.get("SH000016", 3012.65),
     "params.knock_out": 1.03, "params.knock_in": 0.80},
    # SHARK_001: 鲨鱼鳍, 沪深300
    {"product_id": "SHARK_001", "params.spot_ref": prices.get("SH000300", 5059.66),
     "params.strike": prices.get("SH000300", 5059.66)},
    # DBL_001: 双鲨, 创业板指
    {"product_id": "DBL_001", "params.spot_ref": prices.get("SZ399006", 4359.39),
     "params.strike": prices.get("SZ399006", 4359.39)},
    # BIN_001: 二元, 沪深300
    {"product_id": "BIN_001", "params.strike": prices.get("SH000300", 5059.66) * 1.02},
    # SPD_001: 价差, 上证50
    {"product_id": "SPD_001", "params.strike_low": prices.get("SH000016", 3012.65) * 0.95,
     "params.strike_high": prices.get("SH000016", 3012.65) * 1.05},
    # ASN_001: 亚式, 沪深300
    {"product_id": "ASN_001", "params.spot_ref": prices.get("SH000300", 5059.66),
     "params.strike": prices.get("SH000300", 5059.66)},
    # RNG_001: 区间累积, 沪深300
    {"product_id": "RNG_001", "params.spot_ref": prices.get("SH000300", 5059.66),
     "params.lower_barrier": prices.get("SH000300", 5059.66) * 0.90,
     "params.upper_barrier": prices.get("SH000300", 5059.66) * 1.10},
    # DIG_001: 数字区间, 沪深300
    {"product_id": "DIG_001", "params.lower": prices.get("SH000300", 5059.66) * 0.90,
     "params.upper": prices.get("SH000300", 5059.66) * 1.10,
     "params.payoff": 200000},
]

for u in updates:
    pid = u.pop("product_id")
    result = db["option_products"].update_one(
        {"product_id": pid},
        {"$set": u}
    )
    if result.modified_count > 0:
        print(f"  Updated {pid}: {list(u.keys())}")
    else:
        print(f"  No change for {pid}")

# 清除旧的估值结果
db["option_valuations"].delete_many({})
db["option_valuation_history"].delete_many({})
print("\n  Cleared old valuation results")

# 验证产品数据
print("\n=== 产品数据验证 ===")
for p in db["option_products"].find():
    pid = p["product_id"]
    params = p.get("params", {})
    spot_ref = params.get("spot_ref", params.get("strike", "-"))
    print(f"  {pid:12s} type={p['type']:16s} underlying={p['underlying']:10s} "
          f"principal={p['principal']:>12,.0f} spot_ref={spot_ref}")

c.close()
print("\nDone! 现在可以运行估值了。")
