# -*- coding: utf-8 -*-
"""
从本地 JSON 备份文件恢复 MongoDB asset_allocation 数据库的
assets 与 asset_prices 集合。

数据源：
  - scripts/assets.json (22 条) + scripts/daily_px_assets.json (12 条)
  - scripts/asset_prices.json (17,820 条) + scripts/daily_px_asset_prices.json (55,960 条)

字段标准：
  - assets:        code, name, asset_type, exchange, description, is_active, created_at, updated_at
  - asset_prices:  asset_code, date, open, high, low, close, volume, amount, [scale]
"""
import json
import os
import sys
from typing import Any, Dict, List

from pymongo import MongoClient, UpdateOne


MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_FILES = [
    os.path.join(SCRIPT_DIR, "assets.json"),          # 优先
    os.path.join(SCRIPT_DIR, "daily_px_assets.json"),
]
PRICES_FILES = [
    os.path.join(SCRIPT_DIR, "asset_prices.json"),
    os.path.join(SCRIPT_DIR, "daily_px_asset_prices.json"),
]


def load_json_array(path: str) -> List[Dict[str, Any]]:
    """加载 JSON 数组文件；不存在或为空时返回空列表并给出警告。"""
    if not os.path.exists(path):
        print(f"[WARN] 文件不存在，跳过: {path}")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"[WARN] 文件解析失败，跳过: {path} ({exc})")
        return []
    if not isinstance(data, list) or len(data) == 0:
        print(f"[WARN] 文件为空或非列表结构，跳过: {path}")
        return []
    return data


def normalize_extended_date(value: Any) -> Any:
    """将 MongoDB 扩展 JSON 形如 {'$date': '...'} 转为纯字符串；其他类型原样返回。"""
    if isinstance(value, dict) and "$date" in value and len(value) == 1:
        return value["$date"]
    return value


def normalize_asset(record: Dict[str, Any]) -> Dict[str, Any]:
    """将一条 asset 记录规范化为项目标准字段格式。"""
    code = record.get("code") or record.get("asset_code")
    name = record.get("name") or record.get("asset_name")
    doc = {
        "code": code,
        "name": name,
        "asset_type": record.get("asset_type"),
        "exchange": record.get("exchange"),
        "description": record.get("description"),
        "is_active": record.get("is_active", True),
        "created_at": normalize_extended_date(record.get("created_at")),
        "updated_at": normalize_extended_date(record.get("updated_at")),
    }
    return doc


def normalize_price(record: Dict[str, Any]) -> Dict[str, Any]:
    """将一条 asset_price 记录规范化为项目标准字段格式。"""
    doc = {
        "asset_code": record.get("asset_code") or record.get("code"),
        "date": record.get("date"),
        "open": record.get("open"),
        "high": record.get("high"),
        "low": record.get("low"),
        "close": record.get("close"),
        "volume": record.get("volume"),
        "amount": record.get("amount"),
    }
    if "scale" in record:
        doc["scale"] = record.get("scale")
    return doc


def merge_assets(file_paths: List[str]) -> List[Dict[str, Any]]:
    """按 code 去重合并 assets；先出现的文件优先（assets.json 优先于 daily_px_assets.json）。"""
    merged: Dict[str, Dict[str, Any]] = {}
    total_loaded = 0
    for path in file_paths:
        records = load_json_array(path)
        total_loaded += len(records)
        added = 0
        skipped = 0
        for raw in records:
            doc = normalize_asset(raw)
            code = doc.get("code")
            if not code:
                continue
            if code in merged:
                skipped += 1  # 已存在，保留已合并文件中的记录（优先级更高）
                continue
            merged[code] = doc
            added += 1
        print(f"  - {os.path.basename(path)}: 读取 {len(records)} 条, 新增 {added} 条, 重复跳过 {skipped} 条")
    print(f"  合计读取 {total_loaded} 条, 去重后 {len(merged)} 条")
    return list(merged.values())


def merge_prices(file_paths: List[str]) -> List[Dict[str, Any]]:
    """按 (asset_code, date) 去重合并 asset_prices；先出现的文件优先。"""
    merged: Dict[tuple, Dict[str, Any]] = {}
    total_loaded = 0
    for path in file_paths:
        records = load_json_array(path)
        total_loaded += len(records)
        added = 0
        skipped = 0
        for raw in records:
            doc = normalize_price(raw)
            key = (doc.get("asset_code"), doc.get("date"))
            if not key[0] or not key[1]:
                continue
            if key in merged:
                skipped += 1
                continue
            merged[key] = doc
            added += 1
        print(f"  - {os.path.basename(path)}: 读取 {len(records)} 条, 新增 {added} 条, 重复跳过 {skipped} 条")
    print(f"  合计读取 {total_loaded} 条, 去重后 {len(merged)} 条")
    return list(merged.values())


def bulk_insert(collection, docs: List[Dict[str, Any]], batch_size: int = 2000) -> int:
    """分批插入 docs，返回实际插入条数。"""
    inserted = 0
    for i in range(0, len(docs), batch_size):
        batch = docs[i:i + batch_size]
        if not batch:
            continue
        result = collection.insert_many(batch, ordered=False)
        inserted += len(result.inserted_ids)
    return inserted


def main() -> int:
    print(f"[INFO] 连接 MongoDB: {MONGO_URI}, 数据库: {DB_NAME}")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        print(f"[ERROR] 无法连接 MongoDB: {exc}")
        return 1

    db = client[DB_NAME]
    assets_col = db["assets"]
    prices_col = db["asset_prices"]

    # 1) 清空旧数据
    print("\n[STEP 1] 清空旧数据 ...")
    deleted_assets = assets_col.delete_many({}).deleted_count
    deleted_prices = prices_col.delete_many({}).deleted_count
    print(f"  - assets 删除 {deleted_assets} 条")
    print(f"  - asset_prices 删除 {deleted_prices} 条")

    # 2) 合并 assets
    print("\n[STEP 2] 加载并合并 assets ...")
    assets_docs = merge_assets(ASSETS_FILES)

    # 3) 合并 asset_prices
    print("\n[STEP 3] 加载并合并 asset_prices ...")
    prices_docs = merge_prices(PRICES_FILES)

    # 4) 写入 assets
    print("\n[STEP 4] 写入 assets ...")
    assets_inserted = 0
    if assets_docs:
        assets_inserted = bulk_insert(assets_col, assets_docs)
        try:
            assets_col.create_index("code", unique=True)
        except Exception as exc:
            print(f"  [WARN] 创建 code 唯一索引失败: {exc}")
    print(f"  - assets 实际插入 {assets_inserted} 条")

    # 5) 写入 asset_prices
    print("\n[STEP 5] 写入 asset_prices ...")
    prices_inserted = 0
    if prices_docs:
        prices_inserted = bulk_insert(prices_col, prices_docs)
        try:
            prices_col.create_index([("asset_code", 1), ("date", 1)], unique=True)
        except Exception as exc:
            print(f"  [WARN] 创建 (asset_code,date) 唯一索引失败: {exc}")
    print(f"  - asset_prices 实际插入 {prices_inserted} 条")

    # 6) 统计
    print("\n[STEP 6] 导入统计")
    print(f"  - assets       : {assets_col.count_documents({})}")
    print(f"  - asset_prices : {prices_col.count_documents({})}")

    print("\n[DONE] 数据恢复完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
