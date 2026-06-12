"""Fix last DSML/tool_call contamination in MongoDB."""
import re, sys
sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient
LT, GT, SL = chr(60), chr(62), chr(47)
BAR = chr(0xFF5C)
def build_orphan_patterns():
    tags = ["task", "tool_call", "tool_calls", "function_calls", "invoke", "parameter"]
    pats = []
    for t in tags:
        pats.append(re.escape(LT + SL + t + GT))
        pats.append(re.escape(LT + t + GT))
    pats.append(re.escape(LT + SL + "task" + "tool_call" + GT))
    pats.append(re.escape("task" + LT + SL + "task" + GT))
    pats.append(re.escape(LT + SL + "tasktool_call" + GT))
    pats.append(re.escape(LT + BAR))
    return re.compile("|".join(pats))
ORPHAN = build_orphan_patterns()
DSML_TAG = re.compile(r"<[/]?\s*[" + BAR + r"|]+\s*DSML\s*[" + BAR + r"|]+\s*\w*\s*>", re.I)
TOOL_BLOCK = re.compile(r"\s*" + re.escape(LT+"tool_call"+GT) + r".*?" + re.escape(LT+SL+"tool_call"+GT) + r"\s*", re.DOTALL)
BARE_JSON = re.compile(r'\s*\{[\s]*"name"[\s]*:[\s]*"\w+"[\s]*,[\s]*"arguments"[\s]*:[\s]*\{.*?\}\s*\}\s*', re.DOTALL)
def clean(content):
    if not content:
        return content
    c = TOOL_BLOCK.sub("", content)
    c = DSML_TAG.sub("", c)
    c = BARE_JSON.sub("", c)
    c = ORPHAN.sub("", c)
    c = re.sub(r"\n{3,}", "\n\n", c)
    return c.strip()
client = MongoClient("mongodb://localhost:27017")
db = client["asset_allocation"]
kw_list = ["DSML", "tool_call", "tool_calls"]
for kw in kw_list:
    cnt = db["agent_messages"].count_documents({"content": {"$regex": kw}})
    print("Before - contains %r: %d" % (kw, cnt))
msgs = list(db["agent_messages"].find(
    {"$or": [{"content": {"$regex": k}} for k in kw_list]},
    {"_id": 1, "content": 1}
))
print("Found %d messages to fix" % len(msgs))
for msg in msgs:
    old = msg.get("content", "")
    new = clean(old)
    if new != old:
        db["agent_messages"].update_one({"_id": msg["_id"]}, {"$set": {"content": new}})
        print("Fixed: %s" % msg["_id"])
        print("  Preview: %s" % new[:120])
for kw in kw_list:
    cnt = db["agent_messages"].count_documents({"content": {"$regex": kw}})
    print("After - contains %r: %d" % (kw, cnt))
client.close()
print("DONE")
