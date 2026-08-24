# -*- coding: utf-8 -*-
"""
收益凭证估值模块 —— 数据迁移脚本

将 options_pricing/ 目录下的文件数据迁移到 MongoDB：
- products/products.yaml -> option_products
- data/market_*.csv -> option_market_data
- data/vol_surface_*.csv -> option_vol_surfaces
- valuation/events.json -> option_lifecycle_events
- valuation/snapshots/*.json -> option_valuations
- valuation/history.csv -> option_valuation_history

用法:
    cd portfilio-end
    python scripts/migrate_options_data.py

依赖: pymongo, pyyaml (pip install pyyaml)
"""
import os
import sys
import csv
import json
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("请先安装 pyyaml: pip install pyyaml")
    sys.exit(1)

# 默认 MongoDB 连接（与 .env 保持一致）
MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGODB_DB", "asset_allocation")

# options_pricing 源数据目录
OPTIONS_DIR = Path(__file__).resolve().parent.parent / "options_pricing"


def get_db():
    from pymongo import MongoClient
    client = MongoClient(MONGO_URI)
    return client[DB_NAME]


def migrate_products(db):
    """迁移产品定义: products.yaml -> option_products"""
    col = db["option_products"]
    yaml_path = OPTIONS_DIR / "products" / "products.yaml"
    if not yaml_path.exists():
        print(f"  [跳过] 未找到 {yaml_path}")
        return 0

    with open(yaml_path, "r", encoding="utf-8") as f:
        products = yaml.safe_load(f)

    count = 0
    for p in products:
        doc = {
            "product_id": p["id"],
            "name": p["name"],
            "type": p["type"],
            "issuer": p.get("issuer", ""),
            "issue_date": p["issue_date"],
            "maturity_date": p["maturity_date"],
            "principal": float(p["principal"]),
            "underlying": p["underlying"],
            "status": p.get("status", "active"),
            "params": p.get("params", {}),
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        if p.get("knock_out_date"):
            doc["knock_out_date"] = p["knock_out_date"]

        # 去重：按 product_id
        result = col.update_one(
            {"product_id": doc["product_id"]},
            {"$set": doc},
            upsert=True,
        )
        count += 1

    print(f"  [完成] 产品: {count} 条")
    return count


def migrate_market_data(db):
    """迁移市场数据: data/market_*.csv -> option_market_data"""
    col = db["option_market_data"]
    data_dir = OPTIONS_DIR / "data"
    if not data_dir.exists():
        print(f"  [跳过] 未找到 {data_dir}")
        return 0

    count = 0
    for csv_file in sorted(data_dir.glob("market_*.csv")):
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                doc = {
                    "date": row["date"],
                    "underlying": row["underlying"],
                    "spot": float(row["spot"]),
                    "dividend_yield": float(row.get("dividend_yield", 0)),
                    "vol_1m": float(row.get("vol_1m", 0.20)),
                    "vol_3m": float(row.get("vol_3m", 0.18)),
                    "vol_6m": float(row.get("vol_6m", 0.17)),
                    "vol_12m": float(row.get("vol_12m", 0.16)),
                    "rate_1m": float(row.get("rate_1m", 0.02)),
                    "rate_3m": float(row.get("rate_3m", 0.02)),
                    "rate_6m": float(row.get("rate_6m", 0.02)),
                    "rate_1y": float(row.get("rate_1y", 0.025)),
                    "rate_2y": float(row.get("rate_2y", 0.028)),
                    "rate_5y": float(row.get("rate_5y", 0.03)),
                    "created_at": datetime.now(),
                }
                col.update_one(
                    {"date": doc["date"], "underlying": doc["underlying"]},
                    {"$set": doc},
                    upsert=True,
                )
                count += 1

    print(f"  [完成] 市场数据: {count} 条")
    return count


def migrate_vol_surfaces(db):
    """迁移波动率曲面: data/vol_surface_*.csv -> option_vol_surfaces"""
    col = db["option_vol_surfaces"]
    data_dir = OPTIONS_DIR / "data"
    if not data_dir.exists():
        print(f"  [跳过] 未找到 {data_dir}")
        return 0

    # Tenor 映射: 列名 -> 年
    TENOR_MAP = {"1M": 1/12, "3M": 3/12, "6M": 6/12, "12M": 1.0}

    count = 0
    for csv_file in sorted(data_dir.glob("vol_surface_*.csv")):
        # 从文件名提取标的代码
        underlying = csv_file.stem.replace("vol_surface_", "")

        moneyness_grid = []
        vol_rows = {}  # tenor_label -> [vol values]

        with open(csv_file, "r", encoding="utf-8") as f:
            tenor_labels = []
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if not tenor_labels:
                    # 表头行: moneyness,1M,3M,6M,12M
                    parts = line.split(",")
                    tenor_labels = parts[1:]
                    for tl in tenor_labels:
                        vol_rows[tl] = []
                    continue
                parts = line.split(",")
                moneyness_grid.append(float(parts[0]))
                for i, tl in enumerate(tenor_labels):
                    vol_rows[tl].append(float(parts[i + 1]))

        if not moneyness_grid:
            continue

        # 构建 tenor_grid 和 vol_grid
        tenor_grid = [TENOR_MAP.get(tl, 0.25) for tl in tenor_labels]
        # vol_grid shape: (tenors, moneyness)
        vol_grid = [vol_rows[tl] for tl in tenor_labels]

        doc = {
            "underlying": underlying,
            "moneyness_grid": moneyness_grid,
            "tenor_grid": tenor_grid,
            "vol_grid": vol_grid,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        col.update_one(
            {"underlying": underlying},
            {"$set": doc},
            upsert=True,
        )
        count += 1

    print(f"  [完成] 波动率曲面: {count} 个标的")
    return count


def migrate_events(db):
    """迁移事件日志: valuation/events.json -> option_lifecycle_events"""
    col = db["option_lifecycle_events"]
    events_path = OPTIONS_DIR / "valuation" / "events.json"
    if not events_path.exists():
        print(f"  [跳过] 未找到 {events_path}")
        return 0

    with open(events_path, "r", encoding="utf-8") as f:
        events = json.load(f)

    count = 0
    for event in events:
        doc = {
            "product_id": event.get("product_id", ""),
            "event_type": event.get("event_type", ""),
            "event_date": event.get("event_date", ""),
            "spot": float(event.get("spot", 0)),
            "barrier_level": float(event.get("barrier_level", 0)),
            "description": event.get("description", ""),
            "created_at": datetime.now(),
        }
        col.update_one(
            {"product_id": doc["product_id"], "event_type": doc["event_type"], "event_date": doc["event_date"]},
            {"$set": doc},
            upsert=True,
        )
        count += 1

    print(f"  [完成] 事件日志: {count} 条")
    return count


def migrate_history(db):
    """迁移估值历史: valuation/history.csv -> option_valuation_history"""
    col = db["option_valuation_history"]
    history_path = OPTIONS_DIR / "valuation" / "history.csv"
    if not history_path.exists():
        print(f"  [跳过] 未找到 {history_path}")
        return 0

    count = 0
    with open(history_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            doc = {
                "date": row.get("date", ""),
                "product_id": row.get("product_id", ""),
                "name": row.get("name", ""),
                "type": row.get("type", ""),
                "principal": float(row.get("principal", 0)),
                "price_total": float(row.get("price_total", 0)),
                "method": row.get("method", ""),
                "error": row.get("error", ""),
                "created_at": datetime.now(),
            }
            col.update_one(
                {"date": doc["date"], "product_id": doc["product_id"]},
                {"$set": doc},
                upsert=True,
            )
            count += 1

    print(f"  [完成] 估值历史: {count} 条")
    return count


def main():
    print("=" * 60)
    print("收益凭证估值模块 - 数据迁移")
    print(f"  MongoDB: {MONGO_URI}")
    print(f"  数据库:  {DB_NAME}")
    print(f"  源目录:  {OPTIONS_DIR}")
    print("=" * 60)

    if not OPTIONS_DIR.exists():
        print(f"[错误] 源目录不存在: {OPTIONS_DIR}")
        sys.exit(1)

    db = get_db()
    # 测试连接
    try:
        db.client.server_info()
        print("MongoDB 连接成功\n")
    except Exception as e:
        print(f"[错误] MongoDB 连接失败: {e}")
        sys.exit(1)

    total = 0
    print("1. 迁移产品定义...")
    total += migrate_products(db)
    print("2. 迁移市场数据...")
    total += migrate_market_data(db)
    print("3. 迁移波动率曲面...")
    total += migrate_vol_surfaces(db)
    print("4. 迁移事件日志...")
    total += migrate_events(db)
    print("5. 迁移估值历史...")
    total += migrate_history(db)

    print(f"\n{'=' * 60}")
    print(f"迁移完成: 共处理 {total} 条记录")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
