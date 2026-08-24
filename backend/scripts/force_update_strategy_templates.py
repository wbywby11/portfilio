# -*- coding: utf-8 -*-
"""
一次性脚本：强制更新 momentum_risk_parity、trend_cross_sectional 和 etf_discount 内置模板的参数 schema

背景：
  代码已改造去除 gmap_tickers/gcmi_tickers/etf_codes 等冗余参数，
  但数据库中已存在的模板记录仍是旧 schema，需要强制刷新。

用法：
  & "d:\\portfilio-end\\venv\\Scripts\\python.exe" d:\\portfilio-end\\scripts\\force_update_strategy_templates.py
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main():
    from app.config.database import Database
    from app.services.model_template_service import ModelTemplateService
    from app.allocation.builtin_templates import get_builtin_templates
    from app.models.model_template import ModelParameter

    Database.connect()

    target_codes = {"momentum_risk_parity", "trend_cross_sectional", "etf_discount"}
    builtin = {t["code"]: t for t in get_builtin_templates() if t["code"] in target_codes}

    service = ModelTemplateService()
    print(f"=== 强制更新内置模板参数 schema ===")
    for code, data in builtin.items():
        existing = await service.get_template_by_code(code)
        if not existing:
            print(f"  [SKIP] [{code}] 数据库中不存在，跳过（启动时会自动创建）")
            continue

        parameters = [ModelParameter(**p) for p in data["parameters"]]
        update_data = {
            "name": data["name"],
            "description": data["description"],
            "source_code": data["source_code"],
            "parameters": [p.dict() for p in parameters],
        }
        await service.update_template(existing.id, update_data)
        print(f"  [OK]   [{code}] 已强制刷新 — {len(parameters)} 个参数")
        for p in parameters:
            print(f"           - {p.name:25s} ({p.param_type}) default={p.default_value}")
        print()

    Database.close()
    print("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
