# -*- coding: utf-8 -*-
"""把多资产β策略的选择器同分口径切到 strict（严格前N名，与四象限原型一致）。

编制规则的平均排名口径让动量入选数在 9 附近浮动（7~14），
tag_based 预算分母固定 10，导致槽位数与预算不符、权重和被强行归一。

用法：
    python scripts/set_multi_asset_tie_rule.py [--rule strict|index_rule]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from bson import ObjectId

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MULTI_ASSET_MODEL_ID = "6a7194f3df5c07bf2cd2dd05"


async def main(rule: str) -> None:
    from app.config.database import Database
    from app.services.strategy_model_service import StrategyModelService

    Database.connect()
    try:
        service = StrategyModelService()
        doc = await service.collection.find_one({"_id": ObjectId(MULTI_ASSET_MODEL_ID)})
        if not doc:
            print(f"模型不存在: {MULTI_ASSET_MODEL_ID}")
            return

        params = doc.get("parameters") or {}
        sel = params.get("selector_parameters")
        if not isinstance(sel, dict):
            sel = {}
        print(f"当前 selector_parameters: {sel}")

        sel["tie_rule"] = rule
        await service.collection.update_one(
            {"_id": ObjectId(MULTI_ASSET_MODEL_ID)},
            {"$set": {"parameters.selector_parameters": sel}},
        )
        after = await service.collection.find_one({"_id": ObjectId(MULTI_ASSET_MODEL_ID)})
        print(f"更新后 selector_parameters: {(after.get('parameters') or {}).get('selector_parameters')}")
    finally:
        Database.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", default="strict", choices=["strict", "index_rule"])
    args = ap.parse_args()
    asyncio.run(main(args.rule))
