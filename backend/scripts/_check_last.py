"""Check last remaining DSML message."""
import sys
sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["asset_allocation"]
msg = db["agent_messages"].find_one({"_id": "69eb1f4ad20b1d121aa44dd3"})
if msg:
    content = msg.get("content", "")
    for i, line in enumerate(content.split("\n")):
        if "DSML" in line or "tool_call" in line:
            print(f"L{i}: {repr(line[:200])}")
client.close()
