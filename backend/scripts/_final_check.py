"""Final check for any remaining DSML contamination."""
import sys
sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["asset_allocation"]

keywords = ["DSML", "tool_call", "tool_calls"]
for kw in keywords:
    count = db["agent_messages"].count_documents({"content": {"$regex": kw}})
    print(f"Messages containing '{kw}': {count}")

# Also check the specific message
msg = db["agent_messages"].find_one({"_id": "69eb1f4ad20b1d121aa44dd3"})
if msg:
    content = msg.get("content", "")
    for kw in keywords:
        if kw in content:
            print(f"  MSG 69eb1f4ad20b1d121aa44dd3 still has: {kw}")
            idx = content.find(kw)
            print(f"    Context: ...{repr(content[max(0,idx-30):idx+30])}...")
    if not any(kw in content for kw in keywords):
        print("  MSG 69eb1f4ad20b1d121aa44dd3 is CLEAN")

client.close()
