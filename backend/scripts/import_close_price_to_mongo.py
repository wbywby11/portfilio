# -*- coding: utf-8 -*-
"""
收盘价.xlsx → MongoDB assets + asset_prices 导入脚本

文件格式（Wind/同花顺宽表）：
  Row 0: 基金代码 | 510300.SH | 518880.SH | ...
  Row 1: 基金名称 | 南方中证500ETF | ...
  Row 2+: 日期(datetime) | 收盘价(float) | ...

目标集合格式（与现有数据严格一致）：
  assets:        { _id, code, name, asset_type="指数类", exchange, description,
                   is_active, rollover_*, substitute_code, switch_date, created_at, updated_at }
  asset_prices:  { _id, date(str YYYY-MM-DD), asset_code, amount, close, high, low, open, volume, scale }

用法：
  # 预览（不写库）
  python scripts/import_close_price_to_mongo.py --dry-run

  # 写入MongoDB（增量模式：对已有asset_code追加新日期，不删除旧数据）
  python scripts/import_close_price_to_mongo.py

  # 写入MongoDB（替换模式：先删除这些asset_code的全部旧行情再插入）
  python scripts/import_close_price_to_mongo.py --replace
"""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
from bson import ObjectId

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
DEFAULT_EXCEL = Path.home() / "Downloads" / "收盘价.xlsx"
DEFAULT_MONGO_URI = "mongodb://localhost:27017"
DEFAULT_DB = "asset_allocation"
BATCH_SIZE = 5000


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    return False


def _norm_code(raw: Any) -> str:
    if _is_blank(raw):
        return ""
    return str(raw).strip().replace(" ", "")


def _norm_name(raw: Any) -> str:
    if _is_blank(raw):
        return ""
    return str(raw).strip()


# ---------------------------------------------------------------------------
# 读取 Excel 宽表
# ---------------------------------------------------------------------------
def parse_wide_sheet(path: Path) -> Tuple[Dict[str, str], pd.DataFrame]:
    """
    返回 (code -> 证券简称, 宽表 DataFrame)。
    索引: datetime64; 列: asset_code; 值: float or NaN。
    """
    raw = pd.read_excel(path, header=None, engine="openpyxl")
    if raw.shape[0] < 3 or raw.shape[1] < 2:
        raise ValueError(f"表过空: {path}")

    code_to_name: Dict[str, str] = {}
    codes: List[str] = []
    for j in range(1, raw.shape[1]):
        code = _norm_code(raw.iat[0, j])
        if not code:
            continue
        codes.append(code)
        nm = _norm_name(raw.iat[1, j])
        if code not in code_to_name and nm:
            code_to_name[code] = nm

    body = raw.iloc[2:].copy()
    body = body.dropna(how="all")
    dt_col = pd.to_datetime(body.iloc[:, 0], errors="coerce")
    body = body.assign(_dt=dt_col).dropna(subset=["_dt"])
    body["_dt"] = body["_dt"].dt.normalize()

    series_map: Dict[str, pd.Series] = {}
    for idx, code in enumerate(codes, start=1):
        if code in series_map:
            continue  # 去重，取第一列
        ser = pd.to_numeric(body.iloc[:, idx], errors="coerce")
        ser.index = body["_dt"].values
        series_map[code] = ser.sort_index()

    df = pd.DataFrame(series_map)
    df.index.name = "date"
    return code_to_name, df


# ---------------------------------------------------------------------------
# 构建 MongoDB 文档
# ---------------------------------------------------------------------------
def build_price_docs(
    code_to_name: Dict[str, str],
    df: pd.DataFrame,
) -> List[OrderedDict]:
    """构建 asset_prices 文档列表（仅含 close，其余 OHLCVA 为 null）。"""
    docs: List[OrderedDict] = []
    for code in df.columns:
        s = df[code].dropna()
        for dt_idx, val in s.items():
            try:
                close_val = float(val)
            except (TypeError, ValueError):
                continue
            if close_val <= 0 or pd.isna(close_val):
                continue
            ds = pd.Timestamp(dt_idx).strftime("%Y-%m-%d")
            docs.append(OrderedDict([
                ("_id", ObjectId()),
                ("date", ds),
                ("asset_code", code),
                ("amount", None),
                ("close", close_val),
                ("high", None),
                ("low", None),
                ("open", None),
                ("volume", None),
                ("scale", None),
            ]))
    return docs


def build_asset_docs(
    codes: List[str],
    code_to_name: Dict[str, str],
    db: Any = None,
) -> List[OrderedDict]:
    """构建 assets 文档列表（与现有 assets 集合字段严格一致）。"""
    now = datetime.now(timezone.utc)
    docs: List[OrderedDict] = []
    for code in sorted(codes):
        name = code_to_name.get(code, "").strip() or code

        # 如果数据库可访问，检查已有记录以保持 _id 和 created_at
        existing = None
        if db is not None:
            existing = db["assets"].find_one({"code": code})
            # 检查是否有同名不同码的资产，避免名称冲突
            other = db["assets"].find_one({"name": name, "code": {"$ne": code}})
            if other:
                name = f"{name} ({code})"

        oid = existing["_id"] if existing else ObjectId()
        created = (existing.get("created_at") if existing else None) or now

        docs.append(OrderedDict([
            ("_id", oid),
            ("code", code),
            ("name", name),
            ("asset_type", "指数类"),
            ("exchange", ""),
            ("description", ""),
            ("is_active", True if not existing else existing.get("is_active", True)),
            ("rollover_days", None),
            ("rollover_threshold", None),
            ("rollover_window_p", None),
            ("rollover_window_q", None),
            ("substitute_code", existing.get("substitute_code", "") if existing else ""),
            ("switch_date", existing.get("switch_date", "") if existing else ""),
            ("created_at", created),
            ("updated_at", now),
        ]))
    return docs


# ---------------------------------------------------------------------------
# 写入 MongoDB
# ---------------------------------------------------------------------------
def import_to_mongo(
    mongo_uri: str,
    db_name: str,
    price_docs: List[OrderedDict],
    asset_docs: List[OrderedDict],
    asset_codes: List[str],
    replace: bool = False,
) -> None:
    from pymongo import MongoClient, UpdateOne

    client = MongoClient(mongo_uri)
    db = client[db_name]
    coll_p = db["asset_prices"]
    coll_a = db["assets"]

    # ---- asset_prices ----
    if replace:
        dr = coll_p.delete_many({"asset_code": {"$in": asset_codes}})
        print(f"[replace] asset_prices 已删除: {dr.deleted_count} 条")

    # 增量模式：逐批使用 UpdateOne(upsert=True) 按 (asset_code, date) 去重
    if not replace:
        total_updated = 0
        total_inserted = 0
        for i in range(0, len(price_docs), BATCH_SIZE):
            chunk = price_docs[i:i + BATCH_SIZE]
            ops = []
            for doc in chunk:
                ops.append(UpdateOne(
                    {"asset_code": doc["asset_code"], "date": doc["date"]},
                    {"$set": dict(doc)},
                    upsert=True,
                ))
            if ops:
                result = coll_p.bulk_write(ops, ordered=False)
                total_updated += result.modified_count
                total_inserted += result.upserted_count
            done = min(i + BATCH_SIZE, len(price_docs))
            print(f"  asset_prices 进度: {done}/{len(price_docs)} "
                  f"(新增={total_inserted}, 更新={total_updated})")
        print(f"asset_prices 完成: 新增={total_inserted}, 更新={total_updated}")
    else:
        # 替换模式：直接批量插入
        ins = 0
        for i in range(0, len(price_docs), BATCH_SIZE):
            chunk = [dict(x) for x in price_docs[i:i + BATCH_SIZE]]
            if chunk:
                coll_p.insert_many(chunk)
                ins += len(chunk)
                print(f"  asset_prices 已插入: {ins}/{len(price_docs)}")
        print(f"asset_prices 完成: 共插入 {ins} 条")

    # ---- assets (upsert by code) ----
    for ad in asset_docs:
        d = dict(ad)
        coll_a.replace_one({"code": d["code"]}, d, upsert=True)
    print(f"assets 已 upsert: {len(asset_docs)} 条")

    client.close()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="收盘价.xlsx → MongoDB assets + asset_prices")
    parser.add_argument("--excel", type=str, default=str(DEFAULT_EXCEL), help="xlsx文件路径")
    parser.add_argument("--mongo-uri", type=str, default=DEFAULT_MONGO_URI, help="MongoDB URI")
    parser.add_argument("--db", type=str, default=DEFAULT_DB, help="数据库名")
    parser.add_argument("--replace", action="store_true", help="替换模式：先删后插（默认增量upsert）")
    parser.add_argument("--dry-run", action="store_true", help="只解析不写库")
    args = parser.parse_args()

    excel_path = Path(args.excel)
    if not excel_path.is_file():
        print(f"错误: 文件不存在 {excel_path}")
        sys.exit(1)

    print(f"读取 Excel: {excel_path}")
    code_to_name, df = parse_wide_sheet(excel_path)
    codes = sorted(df.columns.tolist())
    print(f"资产数: {len(codes)}")
    print(f"日期范围: {df.index.min()} ~ {df.index.max()}")
    print(f"总行数: {len(df)}")

    # 前10个资产预览
    print("\n前10个资产:")
    for c in codes[:10]:
        n = code_to_name.get(c, "?")
        non_null = df[c].dropna().shape[0]
        print(f"  {c:15s}  {n:30s}  有效数据: {non_null}")

    print("\n构建文档...")
    price_docs = build_price_docs(code_to_name, df)
    print(f"asset_prices 文档数: {len(price_docs)}")

    # 连接数据库
    db = None
    mongo_client = None
    if not args.dry_run:
        from pymongo import MongoClient
        mongo_client = MongoClient(args.mongo_uri)
        db = mongo_client[args.db]
        # 统计现有数据
        existing_prices = db["asset_prices"].count_documents({"asset_code": {"$in": codes}})
        existingAssets = db["assets"].count_documents({"code": {"$in": codes}})
        print(f"\n数据库现有数据:")
        print(f"  asset_prices (涉及本次资产): {existing_prices} 条")
        print(f"  assets (涉及本次资产): {existingAssets} 条")

    asset_docs = build_asset_docs(codes, code_to_name, db)
    print(f"assets 文档数: {len(asset_docs)}")

    if args.dry_run:
        print("\n[dry-run] 不写库，退出。")
        return

    print(f"\n开始导入 MongoDB ({args.db})...")
    if mongo_client:
        mongo_client.close()  # 关闭初始连接，import_to_mongo会开新连接
    import_to_mongo(
        args.mongo_uri, args.db,
        price_docs, asset_docs, codes,
        replace=args.replace,
    )

    # 验证
    from pymongo import MongoClient
    client = MongoClient(args.mongo_uri)
    db = client[args.db]
    final_prices = db["asset_prices"].count_documents({"asset_code": {"$in": codes}})
    final_assets = db["assets"].count_documents({"code": {"$in": codes}})
    print(f"\n导入后数据库状态:")
    print(f"  asset_prices (涉及本次资产): {final_prices} 条")
    print(f"  assets (涉及本次资产): {final_assets} 条")

    # 抽样验证
    sample_code = codes[0]
    sample_docs = list(db["asset_prices"].find({"asset_code": sample_code}).sort("date", -1).limit(3))
    print(f"\n抽样验证 ({sample_code} 最新3条):")
    for d in sample_docs:
        print(f"  date={d['date']}  close={d['close']}  open={d.get('open')}  volume={d.get('volume')}")

    sample_asset = db["assets"].find_one({"code": sample_code})
    if sample_asset:
        print(f"\nassets 抽样 ({sample_code}):")
        print(f"  name={sample_asset.get('name')}  asset_type={sample_asset.get('asset_type')}")

    client.close()
    print("\n导入完成！")


if __name__ == "__main__":
    main()

