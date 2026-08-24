"""迁移脚本：更新 MongoDB model_templates 集合中 source_code 的 import 路径。

背景：
  DynamicStrategyLoader 会 exec 数据库里的 source_code，因此源码模块一旦搬家，
  库里存的旧 import 路径就会在动态加载时抛 ModuleNotFoundError。
  每次模块重构后在 REPLACEMENTS 追加一条规则并重跑本脚本即可。

历史重构：
  1. strategies/ -> allocation/，formula/ 与 solvers/ 提升为顶层包
  2. backtesting/factor_model.py -> allocation/factor_model.py（因子提取归属策略域）

使用方式：
  # 预览（dry-run），不写入数据库
  python scripts/migrate_strategy_imports.py --dry-run

  # 实际执行
  python scripts/migrate_strategy_imports.py

依赖：
  pymongo（同步客户端），通过 app.config.settings 读取 MONGODB_URL。
"""

import sys
import os

# 确保可以导入 app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import settings

# 替换规则（顺序重要：先长后短）
REPLACEMENTS = [
    ("app.strategies.formula.", "app.formula."),
    ("app.strategies.solvers.", "app.solvers."),
    ("app.strategies.models.", "app.allocation.models."),
    ("app.strategies.services.", "app.allocation.services."),
    ("app.strategies.dynamic_loader", "app.allocation.dynamic_loader"),
    ("app.strategies.builtin_templates", "app.allocation.builtin_templates"),
    ("app.backtesting.factor_model", "app.allocation.factor_model"),
]

COLLECTION = "model_templates"
FIELD = "source_code"


def run(dry_run: bool = False) -> None:
    from pymongo import MongoClient

    client = MongoClient(settings.MONGODB_URL)
    db = client[settings.DATABASE_NAME]
    col = db[COLLECTION]

    templates = list(col.find({FIELD: {"$exists": True, "$ne": None}}))
    print(f"Found {len(templates)} templates with source_code in '{COLLECTION}'")

    updated = 0
    for doc in templates:
        code = doc.get("code", "?")
        source = doc[FIELD]
        original = source
        for old, new in REPLACEMENTS:
            source = source.replace(old, new)
        if source != original:
            updated += 1
            # 打印差异摘要
            print(f"  [{code}] {len(original)} chars -> {len(source)} chars (needs update)")
            if not dry_run:
                col.update_one({"_id": doc["_id"]}, {"$set": {FIELD: source}})
        else:
            print(f"  [{code}] no change")

    action = "Would update" if dry_run else "Updated"
    print(f"\n{action} {updated}/{len(templates)} templates.")

    if dry_run and updated > 0:
        print("Run without --dry-run to apply changes.")

    client.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY-RUN MODE (no changes will be written) ===\n")
    run(dry_run=dry_run)
