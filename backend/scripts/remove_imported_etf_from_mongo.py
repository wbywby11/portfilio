# -*- coding: utf-8 -*-
"""
从 MongoDB 删除「六宽表 ETF 导入」产生的资产与行情，便于用 mongoimport 重测插入效果。

代码列表默认从 ``data/asset_allocation.assets.json`` 读取（与导入脚本导出一致）。

用法（项目根目录）::

  python scripts/remove_imported_etf_from_mongo.py
  python scripts/remove_imported_etf_from_mongo.py --mongo-uri mongodb://127.0.0.1:27017 --db asset_allocation
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from bson import json_util  # noqa: E402
from pymongo import MongoClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="删除 ETF 导入资产与 asset_prices")
    parser.add_argument(
        "--mongo-uri",
        default="mongodb://localhost:27017",
        help="MongoDB URI",
    )
    parser.add_argument(
        "--db",
        default="asset_allocation",
        help="数据库名",
    )
    parser.add_argument(
        "--assets-json",
        type=str,
        default=str(project_root / "data" / "asset_allocation.assets.json"),
        help="含 code 列表的 assets Extended JSON 数组文件",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行删除（未加则仅打印将删除的代码数量并退出）",
    )
    args = parser.parse_args()

    path = Path(args.assets_json)
    if not path.is_file():
        print(f"错误: 找不到 {path}")
        sys.exit(1)

    data = json_util.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("错误: JSON 根须为数组")
        sys.exit(1)
    codes = [str(d.get("code", "")).strip() for d in data if isinstance(d, dict) and d.get("code")]
    codes = [c for c in codes if c]
    if not codes:
        print("错误: 未解析到任何 code")
        sys.exit(1)

    print(f"将处理 {len(codes)} 个资产代码（来源: {path}）")
    if not args.yes:
        print("未加 --yes，未执行删除。确认请运行: python scripts/remove_imported_etf_from_mongo.py --yes")
        sys.exit(0)

    client = MongoClient(args.mongo_uri)
    db = client[args.db]
    r1 = db["asset_prices"].delete_many({"asset_code": {"$in": codes}})
    r2 = db["assets"].delete_many({"code": {"$in": codes}})
    client.close()
    print(f"asset_prices 已删除: {r1.deleted_count} 条")
    print(f"assets 已删除: {r2.deleted_count} 条")


if __name__ == "__main__":
    main()
