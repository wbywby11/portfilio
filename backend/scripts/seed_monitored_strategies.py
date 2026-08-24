# -*- coding: utf-8 -*-
"""
种子脚本：注册研究员策略到 monitored_strategies 集合

将 researcher_strategies 模块中定义的两个研究员策略写入 MongoDB，
作为监测策略注册表的初始数据。幂等执行（upsert by source_ref）。

用法:
  python scripts/seed_monitored_strategies.py [--dry-run]
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from pymongo import MongoClient, UpdateOne
from loguru import logger

from app.config.settings import settings
from app.monitor.researcher_strategies import RESEARCHER_STRATEGY_REGISTRY


COLLECTION = "monitored_strategies"


def seed(dry_run: bool = False):
    """将研究员策略注册到 monitored_strategies 集合。"""
    client = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
    db = client[settings.DATABASE_NAME]
    col = db[COLLECTION]

    ops = []
    for code, strategy in RESEARCHER_STRATEGY_REGISTRY.items():
        doc = strategy.to_monitored_strategy_doc()
        now = datetime.now()
        doc["updated_at"] = now

        # upsert by source_type + source_ref（幂等）
        filter_key = {"source_type": "researcher", "source_ref": code}

        # 首次插入时设置 created_at
        update = {
            "$set": doc,
            "$setOnInsert": {"created_at": now},
        }
        ops.append(UpdateOne(filter_key, update, upsert=True))
        logger.info(f"准备注册: {code} → {doc['display_name']}")

    if dry_run:
        logger.info(f"[dry-run] 共 {len(ops)} 条待写入，未实际执行")
        return

    if ops:
        result = col.bulk_write(ops, ordered=False)
        logger.info(
            f"注册完成: upserted={result.upserted_count}, "
            f"modified={result.modified_count}"
        )

    # 确保索引
    col.create_index([("source_type", 1), ("source_ref", 1)], unique=True)
    col.create_index([("status", 1)])
    logger.info("索引已创建")

    client.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    seed(dry_run=dry_run)
