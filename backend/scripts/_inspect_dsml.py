"""Inspect remaining DSML contamination in MongoDB messages."""
import sys
sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["asset_allocation"]
msgs = list(db["agent_messages"].find(
    {"content": {"$regex": "tool_call"}},
    {"_id": 1, "content": 1},
).limit(5))

for msg in msgs:
    content = msg.get("content", "")
    msg_id = msg["_id"]
    print(f"--- MSG {msg_id} ---")
    for i, line in enumerate(content.split("\n")):
        if "DSML" in line or "tool_call" in line:
            print(f"  L{i}: {repr(line[:200])}")
    print()

client.close()
