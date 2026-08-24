# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

# Check which index codes exist
target_codes = ["000300.SH", "000905.SH", "000016.SH", "399006.SZ", "000001.SH"]
for code in target_codes:
    cnt = db["asset_prices"].count_documents({"asset_code": code})
    print(f"  {code}: {cnt} records")

# List all SH/SZ codes  
print("\nAll .SH codes:")
for doc in db["asset_prices"].aggregate([
    {"$match": {"asset_code": {"$regex": "\\.SH$"}}},
    {"$group": {"_id": "$asset_code", "cnt": {"$sum": 1}}},
    {"$sort": {"_id": 1}},
    {"$limit": 10}
]):
    print(f"  {doc['_id']}: {doc['cnt']}")

print("\nAll .SZ codes (first 10):")
for doc in db["asset_prices"].aggregate([
    {"$match": {"asset_code": {"$regex": "\\.SZ$"}}},
    {"$group": {"_id": "$asset_code", "cnt": {"$sum": 1}}},
    {"$sort": {"_id": 1}},
    {"$limit": 10}
]):
    print(f"  {doc['_id']}: {doc['cnt']}")

c.close()
