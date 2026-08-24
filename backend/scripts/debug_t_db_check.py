# -*- coding: utf-8 -*-
"""临时调试：查询 DB 中 T 品种 2019-01-14 ~ 2019-01-25 的价格记录。"""
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.database import Database  # noqa: E402


async def main():
    Database.connect()
    db = Database.get_database()
    q = {"asset_code": "T", "date": {"$gte": "2019-01-14", "$lte": "2019-01-25"}}
    docs = await db["asset_prices"].find(q, {"_id": 0, "date": 1, "close": 1}).to_list(length=None)
    for d in sorted(docs, key=lambda x: x["date"]):
        print(d)
    # 统计 T 总记录数与 csv 行数对比
    n = await db["asset_prices"].count_documents({"asset_code": "T"})
    print("DB 中 T 记录数:", n)


if __name__ == "__main__":
    asyncio.run(main())
