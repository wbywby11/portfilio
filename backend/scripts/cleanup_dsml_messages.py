"""彻底清理 MongoDB 中所有 DSML/tool_call 残留标签 (v3)"""
import re
import sys
sys.path.insert(0, r"d:\portfilio-end")
from pymongo import MongoClient

# Build tag strings using chr() to avoid XML-like syntax in source
LT = chr(60)
GT = chr(62)
SL = chr(47)

TAGS_TO_STRIP = [
    LT + "tool_call" + GT,           # open tag
    LT + SL + "tool_call" + GT,      # close tag
    LT + "tool_calls" + GT,          # open tag (plural)
    LT + SL + "tool_calls" + GT,     # close tag (plural)
    LT + "task" + GT,                # task open
    LT + SL + "task" + GT,           # task close
]

# DSML tag pattern (full-width or ASCII bars)
DSML_ANY_TAG = re.compile(
    r"<[/]?\s*[\uff5c|]+\s*DSML\s*[\uff5c|]+\s*\w*\s*>",
    re.IGNORECASE,
)
# Complete tool_call blocks (open...close)
TOOL_CALL_BLOCK = re.compile(
    r"\s*" + re.escape(LT + "tool_call" + GT) + r".*?" + re.escape(LT + SL + "tool_call" + GT) + r"\s*",
    re.DOTALL,
)
# Bare JSON tool calls
BARE_JSON = re.compile(
    r'\s*\{[\s]*"name"[\s]*:[\s]*"\w+"[\s]*,[\s]*"arguments"[\s]*:[\s]*\{.*?\}\s*\}\s*',
    re.DOTALL,
)


def strip_all(content):
    if not content:
        return content
    # 1. Remove complete tool_call blocks
    c = TOOL_CALL_BLOCK.sub("", content)
    # 2. Remove DSML tags
    c = DSML_ANY_TAG.sub("", c)
    # 3. Remove bare JSON tool calls
    c = BARE_JSON.sub("", c)
    # 4. Remove orphan tool_call/tool_calls/task tags
    for tag in TAGS_TO_STRIP:
        c = c.replace(tag, "")
    # 5. Clean up excessive whitespace
    c = re.sub(r"\n{3,}", "\n\n", c)
    return c.strip()


def main():
    client = MongoClient("mongodb://localhost:27017")
    db = client["asset_allocation"]
    msgs = list(
        db["agent_messages"].find(
            {
                "$or": [
                    {"content": {"$regex": "DSML"}},
                    {"content": {"$regex": "tool_call"}},
                    {"content": {"$regex": '"name".*"arguments"'}},
                ]
            },
            {"_id": 1, "content": 1, "role": 1},
        )
    )
    print(f"Found {len(msgs)} messages")
    fixed = 0
    still_bad = 0
    for msg in msgs:
        content = msg.get("content", "")
        cleaned = strip_all(content)
        if cleaned != content:
            db["agent_messages"].update_one(
                {"_id": msg["_id"]}, {"$set": {"content": cleaned}}
            )
            bad = any(kw in cleaned for kw in ["DSML", "tool_call", "tool_calls"])
            if bad:
                still_bad += 1
                print(f"  WARN: {msg['_id']} still has residue")
            fixed += 1
    print(f"Fixed: {fixed}, Still has residue: {still_bad}")
    client.close()


if __name__ == "__main__":
    main()
