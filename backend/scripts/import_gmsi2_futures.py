# -*- coding: utf-8 -*-
"""
GMSI 2.0 期货数据导入脚本（临时测试口径，参考原型原样导入）

数据源（默认路径）：d:/project/portfilio/gmsi2_replication/data/
  - gmap_adj/*.csv : GMAP 成分 10 品种（大写代码，列 trade_date,settle）
  - gcmi_adj/*.csv : GCMI 成分 46 品种（小写代码，列 trade_date,settle）

两个目录有大小写重复品种（au/AU, cu/CU, i/I, m/M, FG），数据完全一致，
代码统一归一为大写后去重，共 51 个品种。

目标 MongoDB 集合：
  - assets       : 51 个商品期货资产文档
  - asset_prices : {date, asset_code, close=settle} 价格文档

用法：
  python scripts/import_gmsi2_futures.py --dry-run     # 预览不写库（报告冲突）
  python scripts/import_gmsi2_futures.py               # 增量 upsert
  python scripts/import_gmsi2_futures.py --replace     # 先删后插
"""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd
from bson import ObjectId
from pymongo import MongoClient, UpdateOne

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SOURCE = Path("d:/project/portfilio/gmsi2_replication/data")
DEFAULT_MONGO_URI = "mongodb://localhost:27018"
DEFAULT_DB = "asset_allocation"
BATCH_SIZE = 5000

# ---------------------------------------------------------------------------
# 品种静态信息（代码 → (名称, 交易所)）
# ---------------------------------------------------------------------------
FUTURES_INFO: Dict[str, tuple] = {
    # 中金所（股指/国债）
    "IF": ("沪深300股指期货", "中金所"), "IC": ("中证500股指期货", "中金所"),
    "IM": ("中证1000股指期货", "中金所"),
    "T": ("10年期国债期货", "中金所"), "TF": ("5年期国债期货", "中金所"),
    # 上期所
    "AU": ("黄金", "上期所"), "CU": ("铜", "上期所"), "AG": ("白银", "上期所"),
    "AL": ("铝", "上期所"), "ZN": ("锌", "上期所"), "PB": ("铅", "上期所"),
    "NI": ("镍", "上期所"), "SN": ("锡", "上期所"), "RB": ("螺纹钢", "上期所"),
    "HC": ("热轧卷板", "上期所"), "BU": ("石油沥青", "上期所"),
    "RU": ("天然橡胶", "上期所"), "FU": ("燃料油", "上期所"),
    "SP": ("纸浆", "上期所"), "SS": ("不锈钢", "上期所"),
    # 上海国际能源交易中心
    "SC": ("原油", "上海能源"),
    # 大商所
    "M": ("豆粕", "大商所"), "B": ("豆二", "大商所"), "A": ("豆一", "大商所"),
    "Y": ("豆油", "大商所"), "P": ("棕榈油", "大商所"), "C": ("玉米", "大商所"),
    "CS": ("淀粉", "大商所"), "I": ("铁矿石", "大商所"), "JM": ("焦煤", "大商所"),
    "L": ("塑料", "大商所"), "V": ("PVC", "大商所"), "PP": ("聚丙烯", "大商所"),
    "EB": ("苯乙烯", "大商所"), "EG": ("乙二醇", "大商所"), "PG": ("LPG", "大商所"),
    # 郑商所
    "CF": ("棉花", "郑商所"), "SR": ("白糖", "郑商所"), "TA": ("PTA", "郑商所"),
    "MA": ("甲醇", "郑商所"), "OI": ("菜籽油", "郑商所"), "RM": ("菜粕", "郑商所"),
    "FG": ("玻璃", "郑商所"), "SA": ("纯碱", "郑商所"), "SF": ("硅铁", "郑商所"),
    "SM": ("锰硅", "郑商所"), "UR": ("尿素", "郑商所"), "PF": ("短纤", "郑商所"),
    "PK": ("花生", "郑商所"), "SH": ("烧碱", "郑商所"),
    # 广期所
    "SI": ("工业硅", "广期所"), "AO": ("氧化铝", "上期所"),
}

def collect_sources(source_dir: Path) -> Dict[str, Path]:
    """扫描两个目录，返回 {大写代码: csv路径}，重复时保留 gmap_adj 版本。"""
    result: Dict[str, Path] = {}
    for subdir in ("gcmi_adj", "gmap_adj"):
        folder = source_dir / subdir
        if not folder.is_dir():
            print(f"[警告] 目录不存在: {folder}")
            continue
        for f in sorted(folder.glob("*.csv")):
            code = f.stem.upper()
            if code in result:
                print(f"  [去重] {code}: {result[code].name} 与 {f.parent.name}/{f.name} 重复，保留 {result[code].parent.name}")
            else:
                result[code] = f
    return result


def build_asset_docs(db, codes: List[str]) -> List[OrderedDict]:
    now = datetime.now(timezone.utc)
    docs: List[OrderedDict] = []
    for code in codes:
        existing = None
        if db is not None:
            existing = db["assets"].find_one({"code": code})
        name, exchange = FUTURES_INFO.get(code, (f"期货{code}", "未知"))
        oid = existing["_id"] if existing else ObjectId()
        created = (existing.get("created_at") if existing else None) or now
        docs.append(OrderedDict([
            ("_id", oid),
            ("code", code),
            ("name", name),
            ("instrument_type", "期货型"),
            ("asset_class", "商品"),
            ("security_type", "期货"),
            ("asset_type", "期货"),
            ("exchange", exchange),
            ("description", "GMSI 2.0 复现 — 商品期货主力合约复权结算价（临时测试口径）"),
            ("is_active", True if not existing else existing.get("is_active", True)),
            ("currency", "CNY"),
            ("trading_cost_rate", 0.0002),
            ("replication_cost_rate", 0.001),
            ("created_at", created),
            ("updated_at", now),
        ]))
    return docs


def build_price_docs(file_map: Dict[str, Path]) -> List[OrderedDict]:
    docs: List[OrderedDict] = []
    for code in sorted(file_map):
        df = pd.read_csv(file_map[code])
        df = df.dropna(subset=["trade_date", "settle"])
        for _, row in df.iterrows():
            try:
                val = float(row["settle"])
            except (TypeError, ValueError):
                continue
            if val <= 0:
                continue
            ds = pd.Timestamp(row["trade_date"]).strftime("%Y-%m-%d")
            docs.append(OrderedDict([
                ("date", ds),
                ("asset_code", code),
                ("amount", None),
                ("close", val),
                ("high", None), ("low", None), ("open", None),
                ("volume", None), ("scale", None),
            ]))
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="GMSI 2.0 期货数据导入")
    parser.add_argument("--source", type=str, default=str(DEFAULT_SOURCE))
    parser.add_argument("--mongo-uri", type=str, default=DEFAULT_MONGO_URI)
    parser.add_argument("--db", type=str, default=DEFAULT_DB)
    parser.add_argument("--replace", action="store_true", help="替换模式：先删后插")
    parser.add_argument("--dry-run", action="store_true", help="只解析不写库")
    args = parser.parse_args()

    source_dir = Path(args.source)
    if not source_dir.is_dir():
        print(f"错误: 数据源目录不存在 {source_dir}")
        sys.exit(1)

    print("=" * 70)
    print("GMSI 2.0 期货数据导入（临时测试口径）")
    print(f"数据源: {source_dir}")
    print(f"MongoDB: {args.mongo_uri}/{args.db}")
    print(f"模式: {'替换' if args.replace else '增量'}{'（dry-run）' if args.dry_run else ''}")
    print("=" * 70)

    print("\n[1/3] 扫描数据文件")
    file_map = collect_sources(source_dir)
    codes = sorted(file_map)
    print(f"  品种数: {len(codes)}")
    print(f"  代码: {codes}")
    unknown = [c for c in codes if c not in FUTURES_INFO]
    if unknown:
        print(f"  [警告] 无名称映射的品种（将用代码占位）: {unknown}")

    # 冲突检查：数据库已有同名资产（非本次口径）
    db = None
    client = None
    if not args.dry_run:
        client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
        db = client[args.db]
        existing = db["assets"].count_documents({"code": {"$in": codes}})
        existing_prices = db["asset_prices"].count_documents({"asset_code": {"$in": codes}})
        print(f"\n数据库现有数据:")
        print(f"  assets (本次代码): {existing} 条")
        print(f"  asset_prices (本次代码): {existing_prices} 条")

    print("\n[2/3] 构建 assets 文档")
    asset_docs = build_asset_docs(db, codes)
    if args.dry_run:
        print(f"  [dry-run] 将 upsert {len(asset_docs)} 个资产文档")
    else:
        for doc in asset_docs:
            db["assets"].replace_one({"code": doc["code"]}, dict(doc), upsert=True)
        print(f"  assets: 已 upsert {len(asset_docs)} 个")

    print("\n[3/3] 导入 asset_prices")
    price_docs = build_price_docs(file_map)
    print(f"  价格文档总数: {len(price_docs)}")
    if args.dry_run:
        print(f"  [dry-run] 将写入 {len(price_docs)} 条（涉及 {len(codes)} 品种）")
    else:
        coll = db["asset_prices"]
        if args.replace:
            dr = coll.delete_many({"asset_code": {"$in": codes}})
            print(f"  [replace] 已删除 {dr.deleted_count} 条")
            ins = 0
            for i in range(0, len(price_docs), BATCH_SIZE):
                chunk = [dict(x) for x in price_docs[i:i + BATCH_SIZE]]
                coll.insert_many(chunk)
                ins += len(chunk)
            print(f"  已插入 {ins} 条")
        else:
            total_new = total_upd = 0
            for i in range(0, len(price_docs), BATCH_SIZE):
                ops = [UpdateOne(
                    {"asset_code": d["asset_code"], "date": d["date"]},
                    {"$set": {k: v for k, v in d.items() if k != "_id"}},
                    upsert=True) for d in price_docs[i:i + BATCH_SIZE]]
                r = coll.bulk_write(ops, ordered=False)
                total_new += r.upserted_count
                total_upd += r.modified_count
            print(f"  完成: 新增={total_new}, 更新={total_upd}")

    if not args.dry_run:
        print("\n导入验证:")
        final = db["asset_prices"].count_documents({"asset_code": {"$in": codes}})
        print(f"  asset_prices 总数: {final}")
        for code in codes[:5]:
            cnt = db["asset_prices"].count_documents({"asset_code": code})
            rng = db["asset_prices"].find_one({"asset_code": code}, sort=[("date", -1)])
            print(f"    {code}: {cnt} 条, 最新 {rng['date']} close={rng['close']}")
        client.close()

    print("\n" + "=" * 70)
    print("完成！")


if __name__ == "__main__":
    main()
