"""扫描并修复 model_templates 中 parameters[*].options 非数组的脏数据。

在远端后端机器执行（连远端 MongoDB）。
规则与后端 coerce_options 一致：
  - JSON 字符串可解析 -> 还原为数组
  - 其余字符串/非数组 -> 置 None
先 --check 仅扫描不写库；确认后去掉 --check 执行修复。
"""
import json
import sys
import pymongo

CHECK_ONLY = "--check" in sys.argv

db = pymongo.MongoClient("localhost", 27017)["asset_allocation"]

fixed = 0
for doc in db.model_templates.find({}):
    params = doc.get("parameters") or []
    dirty_idx = []
    for i, p in enumerate(params):
        v = p.get("options")
        if v is None or isinstance(v, list):
            continue
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                try:
                    params[i]["options"] = json.loads(s)
                    dirty_idx.append((i, "JSON还原"))
                    continue
                except Exception:
                    pass
        params[i]["options"] = None
        dirty_idx.append((i, f"置空(原值={str(v)[:40]!r})"))
    if dirty_idx:
        fixed += 1
        print(f"模板 {doc['_id']} code={doc.get('code')} 脏参数: {dirty_idx}")
        if not CHECK_ONLY:
            db.model_templates.update_one({"_id": doc["_id"]}, {"$set": {"parameters": params}})

print(f"\n{'[仅扫描] ' if CHECK_ONLY else '[已修复] '}涉及模板数: {fixed}")
