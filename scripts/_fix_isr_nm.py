"""修复 dwd_isr_institution 的 ISR_NM 字段"""
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["portfilio"]
coll = db["dwd_isr_institution"]

fixed = 0
for doc in coll.find({"CUSTOMER_NAME": {"$ne": None}}):
    updates = {"ISR_NM": doc["CUSTOMER_NAME"]}
    if doc.get("CUSTOMER_ABBR"):
        updates["ISR_SHORT_NM"] = doc["CUSTOMER_ABBR"]
    coll.update_one({"_id": doc["_id"]}, {"$set": updates})
    fixed += 1

print(f"Fixed {fixed} documents")
print("\nVerification:")
for d in coll.find({}, {"ISR_ID": 1, "ISR_NM": 1, "ISR_SHORT_NM": 1, "_id": 0}).limit(8):
    print(f"  {d.get('ISR_ID')} -> ISR_NM={d.get('ISR_NM')}, SHORT={d.get('ISR_SHORT_NM')}")

client.close()
