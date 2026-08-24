# -*- coding: utf-8 -*-
"""
清理并重新导入行情数据（asset_prices / fx_rates / trade_dates）

数据源：d:\project\portfilio\ 下的 daily_px.xlsx / fx.xlsx / trade_dates.xlsx
映射：与 xlsx_to_json.py COLUMN_TO_CODE 一致（新标准码）

用法：
  python scripts/reimport_all_prices.py
  python scripts/reimport_all_prices.py --dry-run
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from pymongo import MongoClient, UpdateOne

# ---------------------------------------------------------------------------
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"
DATA_DIR = Path("D:/project/portfilio")
BATCH_SIZE = 5000

# daily_px.xlsx 列名 → asset_code（与 sharpe_18.py 一致）
COLUMN_TO_CODE: Dict[str, str] = {
    "中国10年国债": "ZQGZ10",
    "中国5年国债":  "ZQGZ5",
    "中国2年国债":  "ZQGZ2",
    "美国10年国债": "UST10",
    "美国2年国债":  "UST2",
    "可转债":       "CVTBND",
    "沪深300":      "000300.SH",
    "中证500":      "ZZ000905",
    "创业板指":     "SZ399006",
    "标普500":      "SPX",
    "纳斯达克100":  "NDX",
    "日经225":      "N225",
    "沪铜":         "SHCU",
    "沪铝":         "SHAL",
    "沪锡":         "SHSN",
    "黄金":         "GLD",
    "布伦特原油":   "B00Y",
    "豆粕":         "DM",
}


def fmt_date(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d")
    if isinstance(dt, str):
        for f in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(dt, f).strftime("%Y-%m-%d")
            except ValueError:
                continue
    # pandas Timestamp
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d")
    return str(dt)[:10]


def main():
    dry_run = "--dry-run" in sys.argv

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    print("=" * 60)
    print("清理并重新导入行情数据")
    print(f"数据库: {DB_NAME}")
    print(f"数据源: {DATA_DIR}")
    print(f"模式: {'预览(dry-run)' if dry_run else '写入'}")
    print("=" * 60)

    # ─── 1. 清理 ───────────────────────────────────────────────
    if not dry_run:
        for coll_name in ["asset_prices", "fx_rates", "trade_dates"]:
            n = db[coll_name].count_documents({})
            db[coll_name].delete_many({})
            print(f"  [清理] {coll_name}: 删除 {n} 条")
    else:
        for coll_name in ["asset_prices", "fx_rates", "trade_dates"]:
            n = db[coll_name].count_documents({})
            print(f"  [预览] {coll_name}: 将删除 {n} 条")

    # ─── 2. trade_dates.xlsx ──────────────────────────────────
    td_path = DATA_DIR / "trade_dates.xlsx"
    print(f"\n{'=' * 60}")
    print(f"导入 trade_dates.xlsx")
    df_td = pd.read_excel(td_path)
    dates = set()
    for val in df_td.iloc[:, 0]:
        d = fmt_date(val)
        if d:
            dates.add(d)
    td_records = [{"date": d} for d in sorted(dates)]
    print(f"  交易日数: {len(td_records)}")
    if td_records:
        print(f"  范围: {td_records[0]['date']} ~ {td_records[-1]['date']}")
    if not dry_run:
        db["trade_dates"].insert_many(td_records)
        print(f"  已写入 {len(td_records)} 条")

    # ─── 3. fx.xlsx ───────────────────────────────────────────
    fx_path = DATA_DIR / "fx.xlsx"
    print(f"\n{'=' * 60}")
    print(f"导入 fx.xlsx")
    df_fx = pd.read_excel(fx_path)
    # 第一列为日期，其余列为汇率
    date_col = df_fx.columns[0]
    fx_cols = [c for c in df_fx.columns[1:] if str(c).strip()]
    print(f"  汇率列: {fx_cols}")

    fx_ops = []
    for _, row in df_fx.iterrows():
        d = fmt_date(row[date_col])
        if not d:
            continue
        doc = {"date": d}
        for c in fx_cols:
            v = row[c]
            if pd.notna(v):
                doc[str(c).strip().upper()] = float(v)
        fx_ops.append(UpdateOne({"date": d}, {"$set": doc}, upsert=True))

    print(f"  汇率记录数: {len(fx_ops)}")
    if not dry_run and fx_ops:
        db["fx_rates"].bulk_write(fx_ops, ordered=False)
        print(f"  已写入 {len(fx_ops)} 条")

    # ─── 4. daily_px.xlsx ─────────────────────────────────────
    px_path = DATA_DIR / "daily_px.xlsx"
    print(f"\n{'=' * 60}")
    print(f"导入 daily_px.xlsx")
    df_px = pd.read_excel(px_path)
    date_col_px = df_px.columns[0]

    # 建立列映射
    col_map: Dict[str, str] = {}
    unmapped = []
    for c in df_px.columns[1:]:
        c_str = str(c).strip()
        code = COLUMN_TO_CODE.get(c_str)
        if code:
            col_map[c] = code
        else:
            unmapped.append(c_str)

    if unmapped:
        print(f"  [警告] 未映射列: {unmapped}")
    print(f"  已映射资产 ({len(col_map)}): {list(col_map.values())}")

    # 构建文档
    price_docs: List[Dict[str, Any]] = []
    for _, row in df_px.iterrows():
        d = fmt_date(row[date_col_px])
        if not d:
            continue
        for col, code in col_map.items():
            v = row[col]
            if pd.notna(v):
                price_docs.append({
                    "date": d,
                    "asset_code": code,
                    "close": float(v),
                    "open": None,
                    "high": None,
                    "low": None,
                    "volume": None,
                    "amount": None,
                })

    print(f"  行情记录数: {len(price_docs)}")
    codes_set = set(doc["asset_code"] for doc in price_docs)
    dates_set = set(doc["date"] for doc in price_docs)
    print(f"  资产数: {len(codes_set)}")
    print(f"  资产代码: {sorted(codes_set)}")
    if dates_set:
        print(f"  日期范围: {min(dates_set)} ~ {max(dates_set)}")

    if not dry_run and price_docs:
        for i in range(0, len(price_docs), BATCH_SIZE):
            batch = price_docs[i:i + BATCH_SIZE]
            db["asset_prices"].insert_many(batch)
            print(f"  写入 {min(i + BATCH_SIZE, len(price_docs))}/{len(price_docs)}")
        print(f"  完成！共写入 {len(price_docs)} 条行情")

    # ─── 汇总 ─────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("导入完成汇总:")
    print(f"  trade_dates: {db['trade_dates'].count_documents({})} 条")
    print(f"  fx_rates:    {db['fx_rates'].count_documents({})} 条")
    print(f"  asset_prices:{db['asset_prices'].count_documents({})} 条")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
