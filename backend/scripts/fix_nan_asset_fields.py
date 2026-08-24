# -*- coding: utf-8 -*-
"""修复 assets 集合中的 NaN / 空字符串污染字段。

背景：
    旧版资产批量导入把 pandas NaN（BSON double NaN）或空字符串直接 $set 进
    MongoDB，导致列表接口 Asset(**doc) pydantic 校验失败 → 整页 500。

用法：
    python scripts/fix_nan_asset_fields.py            # dry-run，仅列出污染文档
    python scripts/fix_nan_asset_fields.py --apply    # 实际修复（置为 null）

连接地址与 .env / 其他脚本保持一致，如需指向远端请修改 MONGO_URI。
"""
import math
import os
import sys

from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGODB_URL", "mongodb://localhost:27018")
DB_NAME = "asset_allocation"

# 可选字段：NaN / 空串 一律归一为 null
OPTIONAL_FIELDS = (
    "security_type", "exchange", "description", "asset_type",
    "substitute_code", "switch_date", "currency",
    "rollover_days", "rollover_threshold", "rollover_window_p",
    "rollover_window_q", "trading_cost_rate", "replication_cost_rate",
)


def main():
    apply = "--apply" in sys.argv
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    print("=" * 60)
    print("  assets 污染字段修复 " + ("[APPLY]" if apply else "[DRY-RUN]"))
    print("=" * 60)

    fixed = 0
    for doc in db["assets"].find({}):
        bad = {}
        for k in OPTIONAL_FIELDS:
            if k not in doc:
                continue
            v = doc[k]
            if isinstance(v, float) and math.isnan(v):
                bad[k] = "NaN"
            elif isinstance(v, str) and not v.strip():
                bad[k] = "空串"
        if not bad:
            continue
        fixed += 1
        print(f"  {doc.get('code', '?'):14s}  {doc.get('name', '?'):16s}  {bad}")
        if apply:
            db["assets"].update_one(
                {"_id": doc["_id"]},
                {"$set": {k: None for k in bad}},
            )

    print("-" * 60)
    if fixed == 0:
        print("  未发现污染文档，无需修复")
    elif apply:
        print(f"  已修复 {fixed} 个文档（污染字段置为 null）")
    else:
        print(f"  共 {fixed} 个污染文档（dry-run，加 --apply 执行修复）")
    print("=" * 60)
    client.close()


if __name__ == "__main__":
    main()
