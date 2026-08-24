# -*- coding: utf-8 -*-
"""修复 assets 集合中非法的 instrument_type 枚举值

背景：scripts/import_gmsi2_futures.py 曾把 51 个商品期货资产的 instrument_type
写成 "期货"，而 InstrumentType 枚举合法值为 指数型/现货型/期货型。
Asset.backfill_legacy_dimensions 只在字段"缺失"时回填，字段存在但取值非法会直接
抛 ValidationError，导致 GET /api/v1/strategy-models/ 等接口 500。

只修复形态维度上语义唯一的历史写法（期货/期货类 → 期货型 等），其余非法取值
一律报告并以非零退出码失败，不做任何猜测性归一。

用法：
  py scripts/fix_asset_instrument_type.py            # 只体检不写库
  py scripts/fix_asset_instrument_type.py --apply    # 执行修复
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from pymongo import MongoClient, UpdateOne

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.asset import (  # noqa: E402
    Asset,
    AssetClass,
    InstrumentType,
    SecurityType,
)

DEFAULT_MONGO_URI = "mongodb://localhost:27018"
DEFAULT_DB = "asset_allocation"

# 非法 instrument_type → 合法工具形态（仅语义唯一的历史写法）
INSTRUMENT_REPAIR = {
    "期货": InstrumentType.FUTURES_LIKE.value,
    "期货类": InstrumentType.FUTURES_LIKE.value,
    "现货": InstrumentType.SPOT_LIKE.value,
    "现货类": InstrumentType.SPOT_LIKE.value,
    "指数": InstrumentType.INDEX_LIKE.value,
    "指数类": InstrumentType.INDEX_LIKE.value,
}

VALID_INSTRUMENT = {e.value for e in InstrumentType}
VALID_CLASS = {e.value for e in AssetClass}
VALID_SECURITY = {e.value for e in SecurityType}


def main() -> int:
    parser = argparse.ArgumentParser(description="修复 assets.instrument_type 非法枚举值")
    parser.add_argument("--mongo-uri", default=DEFAULT_MONGO_URI)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="真正写库（默认只体检）")
    args = parser.parse_args()

    db = MongoClient(args.mongo_uri)[args.db]
    docs = list(db["assets"].find({}))
    print(f"assets 文档总数: {len(docs)}")

    ops: list[UpdateOne] = []
    repaired = Counter()
    blocked: list[tuple[str, str, str]] = []  # (field, code, value)

    for d in docs:
        code = d.get("code", "?")

        it = d.get("instrument_type")
        if it is not None and it not in VALID_INSTRUMENT:
            target = INSTRUMENT_REPAIR.get(str(it).strip())
            if target is None:
                blocked.append(("instrument_type", code, repr(it)))
            else:
                repaired[f"{it} -> {target}"] += 1
                ops.append(UpdateOne({"_id": d["_id"]}, {"$set": {"instrument_type": target}}))

        ac = d.get("asset_class")
        if ac is not None and ac not in VALID_CLASS:
            blocked.append(("asset_class", code, repr(ac)))

        st = d.get("security_type")
        if st is not None and st not in VALID_SECURITY:
            blocked.append(("security_type", code, repr(st)))

    print("\n可修复的 instrument_type：")
    if repaired:
        for k, n in repaired.items():
            print(f"  {k}: {n} 条")
    else:
        print("  无")

    if blocked:
        print(f"\n无法自动归一的非法取值 {len(blocked)} 条（需人工确认语义，脚本不做猜测）：")
        for field, code, value in blocked[:50]:
            print(f"  {field}  {code}  {value}")
        if len(blocked) > 50:
            print(f"  ... 其余 {len(blocked) - 50} 条省略")

    if not args.apply:
        print("\n[体检模式] 未写库。确认后加 --apply 执行。")
        return 1 if blocked else 0

    if ops:
        res = db["assets"].bulk_write(ops, ordered=False)
        print(f"\n已更新 {res.modified_count} 条文档")
    else:
        print("\n无需更新")

    # 用真实 Asset 模型全量复验（_id 转字符串，与 asset_service 读取路径一致）
    failed: list[tuple[str, str]] = []
    for d in db["assets"].find({}):
        payload = dict(d)
        payload["_id"] = str(payload["_id"])
        try:
            Asset(**payload)
        except Exception as exc:  # noqa: BLE001
            failed.append((payload.get("code", "?"), " | ".join(str(exc).splitlines())))

    if failed:
        print(f"\nAsset 模型校验仍失败 {len(failed)} 条：")
        for code, msg in failed[:50]:
            print(f"  {code}: {msg}")
        return 1

    print("\nAsset 模型全量校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
