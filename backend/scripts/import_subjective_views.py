# -*- coding: utf-8 -*-
"""
将 data/subjective_views.xlsx 导入 MongoDB 集合 subjective_views。

工作簿为「观点矩阵 / 置信度矩阵 / 观点依据」三表结构，与主观调仓指令 subjective_overrides
（执行日 + 目标权重）不同；本脚本只落库观点矩阵数据。

用法（在项目根目录）:
  python scripts/import_subjective_views.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


async def main() -> None:
    from app.config.database import Database
    from app.data.subjective_views_loader import load_subjective_view_matrix
    from app.monitor import config

    Database.connect()
    db = Database.get_database()
    coll_name = config.MONGO_COLLECTIONS["subjective_views"]
    coll = db[coll_name]

    records = load_subjective_view_matrix()
    if not records:
        print(
            "未读取到记录：请确认存在 data/subjective_views.xlsx，"
            "且含工作表「观点矩阵」「置信度矩阵」「观点依据」及列「观点日期」。"
        )
        return

    ok = 0
    for r in records:
        doc = {
            "view_date": r["view_date"],
            "scores": r["scores"],
            "confidence": r["confidence"],
            "rationale": r["rationale"],
            "source": "subjective_views.xlsx",
        }
        await coll.update_one({"view_date": doc["view_date"]}, {"$set": doc}, upsert=True)
        ok += 1
        print(f"  已写入: view_date={doc['view_date']}")

    print(f"完成: 写入/更新 {ok} 条 -> 集合 {coll_name}")


if __name__ == "__main__":
    asyncio.run(main())
