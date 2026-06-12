"""Check the last remaining tool_call message."""
import sys
sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["asset_allocation"]
msg = db["agent_messages"].find_one({"content": {"$regex": "tool_call"}}, {"_id": 1, "content": 1})
if msg:
    content = msg.get("content", "")
    msg_id = msg["_id"]
    print(f"MSG: {msg_id}")
    for i, line in enumerate(content.split("\n")):
        if "tool_call" in line:
            print(f"  L{i}: {repr(line[:200])}")
else:
    print("No messages found")
client.close()
