# -*- coding: utf-8 -*-
"""资产费率字段名迁移（幂等）.

背景：早期导入脚本把费率写成 ``trading_cost`` / ``replication_cost``，
而 ``Asset`` 模型声明的字段名是 ``trading_cost_rate`` / ``replication_cost_rate``，
导致库内费率对模型不可见（读出来永远是 None）。

本脚本把旧字段名改为模型声明的字段名。新旧字段同时存在时不自动覆盖，
而是列出冲突文档由人工裁决 —— 静默覆盖可能丢掉后来手工维护的正确值。

用法（在 portfilio-end 目录下运行）：
  py scripts/migrate_asset_cost_field_names.py --dry-run
  py scripts/migrate_asset_cost_field_names.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.collections import COL_ASSETS  # noqa: E402
from app.config.database import Database  # noqa: E402

# 旧字段名 → 模型声明字段名
RENAMES = {
    "trading_cost": "trading_cost_rate",
    "replication_cost": "replication_cost_rate",
}


async def migrate(dry_run: bool) -> int:
    Database.connect()
    col = Database.db[COL_ASSETS]

    conflicts: list[str] = []
    total_renamed = 0

    for old, new in RENAMES.items():
        n_old = await col.count_documents({old: {"$exists": True}})
        n_both = await col.count_documents(
            {old: {"$exists": True}, new: {"$exists": True}}
        )
        n_new = await col.count_documents(
            {old: {"$exists": False}, new: {"$exists": True}}
        )
        print(f"[探查] {old:20s} 待迁移={n_old - n_both:4d} "
              f"冲突(新旧共存)={n_both:4d} 已是新名={n_new:4d}")

        if n_both:
            cursor = col.find(
                {old: {"$exists": True}, new: {"$exists": True}},
                {"code": 1, old: 1, new: 1},
            )
            async for doc in cursor:
                conflicts.append(
                    f"  {doc.get('code')}: {old}={doc.get(old)} {new}={doc.get(new)}"
                )
            continue

        if dry_run or n_old == 0:
            continue
        res = await col.update_many(
            {old: {"$exists": True}}, {"$rename": {old: new}}
        )
        total_renamed += res.modified_count
        print(f"[迁移] {old} → {new}: {res.modified_count} 个文档")

    if conflicts:
        print("\n[冲突] 以下文档新旧字段共存，未自动处理，请人工裁决：")
        print("\n".join(conflicts))
        return 1

    print(f"\n[完成] {'dry-run，未写库' if dry_run else f'共迁移 {total_renamed} 个文档'}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="资产费率字段名迁移（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只探查不写库")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(migrate(args.dry_run)))


if __name__ == "__main__":
    main()
