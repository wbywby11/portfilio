# -*- coding: utf-8 -*-
"""检查 DB 中 GCMI/GMAP 模型 parameters 是否含 signal_calendar_dates."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.database import Database  # noqa: E402


async def main() -> None:
    Database.connect()
    db = Database.db
    for name in ["GMSI2-GMAP 商品动量策略", "GMSI2-GCMI 趋势截面复合策略"]:
        doc = await db["strategy_models"].find_one({"name": name})
        if not doc:
            print(f"{name}: 不存在")
            continue
        params = doc.get("parameters", {})
        cal = params.get("signal_calendar_dates")
        print(f"{name}:")
        print(f"  signal_calendar_dates: {type(cal).__name__} "
              f"len={len(cal) if cal else 0}")
        print(f"  preserve_price_gaps: {params.get('preserve_price_gaps')}")
        print(f"  keys: {sorted(params.keys())}")
    Database.close()


if __name__ == "__main__":
    asyncio.run(main())
