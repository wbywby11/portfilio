# -*- coding: utf-8 -*-
"""
删除此前按「量化基金净值 / 基金数据」excel 批量手动导入的一组基金：
  asset_prices 中 asset_code 命中者、assets 中 code 命中者。

与 scripts/export_fund_excel_to_mongo_json.py 配套；删库后即可用新 excel 重建 JSON 并重导。

用法（在项目根目录）:
  python -m scripts.delete_previous_quant_fund_import
"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目根
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 上一轮「基金数据.xlsx」导出的 19 支（含华泰柏瑞 021814）；新 excel 若不包含某代码，也需从库中删掉
PREVIOUS_BATCH_ASSET_CODES = frozenset(
    {
        "001974.OF",
        "001990.OF",
        "004881.OF",
        "004945.OF",
        "005109.OF",
        "005399.OF",
        "005443.OF",
        "006048.OF",
        "012350.OF",
        "014155.OF",
        "015867.OF",
        "015880.OF",
        "017953.OF",
        "018823.OF",
        "019124.OF",
        "021814.OF",
        "022485.OF",
        "022756.OF",
        "023298.OF",
    }
)


def main() -> None:
    from pymongo import MongoClient

    from app.config.settings import settings

    uri = settings.MONGODB_URL
    db_name = settings.DATABASE_NAME
    codes = sorted(PREVIOUS_BATCH_ASSET_CODES)

    client = MongoClient(uri)
    try:
        db = client[db_name]
        pr = db["asset_prices"].delete_many({"asset_code": {"$in": codes}})
        ar = db["assets"].delete_many({"code": {"$in": codes}})
        print(f"MongoDB `{db_name}`")
        print(f"  asset_prices 删除: {pr.deleted_count} 条 (codes={len(codes)})")
        print(f"  assets 删除:      {ar.deleted_count} 条")
    finally:
        client.close()


if __name__ == "__main__":
    main()
