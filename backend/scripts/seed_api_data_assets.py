"""
种子脚本：初始化 API 数据资产表
将现有连接器和本地导入型数据源注册到 api_data_assets 集合

用法（在 portfilio-end 目录）:
    python scripts/seed_api_data_assets.py

依赖 .env 中的 MONGODB_URL、DATABASE_NAME。
按 connector_id / target_collection upsert，重复执行幂等。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

from app.config.database import Database  # noqa: E402
from app.services.api_data_asset_service import ApiDataAssetService  # noqa: E402


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 建立数据库连接
    Database.connect()
    logger.info("开始初始化 API 数据资产表...")

    service = ApiDataAssetService()
    result = await service.seed_from_connectors()

    logger.info(
        "初始化完成: 新建 {} 条, 跳过 {} 条",
        result.get("created", 0),
        result.get("skipped", 0),
    )

    # 打印当前资产列表
    assets = await service.list_assets(page_size=50)
    logger.info("当前共有 {} 个数据资产:", assets.get("total", 0))
    for item in assets.get("items", []):
        logger.info(
            "  [{}] {} -> {} ({})",
            item.get("asset_type"),
            item.get("name"),
            item.get("target_collection"),
            item.get("status"),
        )

    Database.close()


if __name__ == "__main__":
    asyncio.run(main())
