# -*- coding: utf-8 -*-
"""
从 Excel 导入测试资产与数据到数据库（独立脚本，仅需 pymongo/pandas/openpyxl）

用法：
  cd d:\portfilio-end
  pip install pymongo pandas openpyxl   # 若未安装
  python scripts/import_test_data_standalone.py

确保 MongoDB 已启动，且 BASE_PATH 指向正确的 Excel 目录。

数据源：
- daily_px.xlsx: 第一列为日期，后续列为资产（名称或代码）
- fx.xlsx: 第一列为日期，后续列为 EUR/USD/CNH/HKD
- trade_dates.xlsx: 交易日历

规则：同名资产（与库中已有）取名为 XXX-测试，代码为 XXX_TEST，避免与原数据重合。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pandas as pd
from pymongo import MongoClient

# 文件路径（请按需修改）
BASE_PATH = Path("c:/Users/wangb/xwechat_files/wxid_l7trc60uwzre22_b8b1/msg/file/2026-03")
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 资产名称 -> 代码（daily_px 列名可能为中文）
NAME_TO_CODE = {
    "沪深300": "SH000300",
    "创业板指": "SZ399006",
    "红利低波": "ZZ000001",
    "恒生科技": "HSTECH",
    "标普500": "SPX",
    "德国DAX": "GDAXI",
    "中国10年国债": "ZQGZ10",
    "中国2年国债": "ZQGZ2",
    "布伦特原油": "B00Y",
    "黄金": "GLD",
    "铁矿石": "IRON",
    "中国有色金属": "YSJS",
}

MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "asset_allocation")


def _norm(s):
    return str(s).strip() if s is not None else ""


# daily_px 列顺序（当列名无法匹配时按顺序映射）
COL_ORDER_FALLBACK = list(NAME_TO_CODE.keys())


def _resolve_code_name(header, col_index: int = -1):
    h = _norm(header).replace(" ", "")
    if h in NAME_TO_CODE:
        return NAME_TO_CODE[h], h
    rev = {v: k for k, v in NAME_TO_CODE.items()}
    if h in rev:
        return h, rev[h]
    if 0 <= col_index < len(COL_ORDER_FALLBACK):
        name = COL_ORDER_FALLBACK[col_index]
        return NAME_TO_CODE[name], name
    code = (h or "UNK").replace(" ", "_")[:50]
    return code, h or "未知"


def main():
    client = MongoClient(MONGODB_URL)
    db = client[DATABASE_NAME]
    assets_coll = db["assets"]
    prices_coll = db["asset_prices"]
    fx_coll = db["fx_rates"]

    # 数据路径：优先 portfilio-end/data/ 下最新 Excel，其次 BASE_PATH
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    daily_px_path = data_dir / "daily_px.xlsx"
    if not daily_px_path.exists():
        daily_px_path = BASE_PATH / "daily_px.xlsx"
    fx_path = data_dir / "fx.xlsx" if (data_dir / "fx.xlsx").exists() else (BASE_PATH / "fx.xlsx")
    trade_dates_path = (
        data_dir / "trade_dates.xlsx"
        if (data_dir / "trade_dates.xlsx").exists()
        else (BASE_PATH / "trade_dates.xlsx")
    )

    if not daily_px_path.exists():
        print(f"错误: 找不到 daily_px.xlsx（已查 {data_dir} 与 BASE_PATH）")
        return

    # 已有资产
    existing_codes = set()
    existing_names = set()
    for doc in assets_coll.find({"is_active": True}):
        if doc.get("code"):
            existing_codes.add(doc["code"])
        if doc.get("name"):
            existing_names.add(doc["name"])

    print("=" * 60)
    print("1. 导入 daily_px.xlsx -> 资产 + 行情")
    print("=" * 60)

    df = pd.read_excel(daily_px_path)
    df.columns = [_norm(c) for c in df.columns]
    date_col = df.columns[0]
    if "Unnamed" in str(date_col):
        df = df.rename(columns={date_col: "date"})
        date_col = "date"
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.dropna(subset=[date_col])

    asset_cols = [c for c in df.columns if c != date_col and _norm(c)]
    print(f"  日期列: {date_col}, 资产列: {len(asset_cols)}")

    for idx, col in enumerate(asset_cols):
        code, name = _resolve_code_name(col, idx)
        if not code:
            code = col.replace(" ", "_")[:50]
            name = col or "未知"
        dup = code in existing_codes or name in existing_names
        final_code = f"{code}_TEST" if dup else code
        final_name = f"{name}-测试" if dup else name
        print(f"  {col} -> {final_code} / {final_name} (重名={dup})")

        # 创建资产
        if not assets_coll.find_one({"code": final_code}):
            from datetime import datetime
            assets_coll.insert_one({
                "code": final_code,
                "name": final_name,
                "asset_type": "指数",
                "is_active": True,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            })
            existing_codes.add(final_code)
            existing_names.add(final_name)
            print(f"    创建资产")

        # 导入行情
        sub = df[[date_col, col]].dropna(subset=[col])
        ops = []
        for _, row in sub.iterrows():
            dt = row[date_col]
            dstr = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
            close = float(row[col])
            ops.append({
                "asset_code": final_code,
                "date": dstr,
                "close": close,
                "open": None, "high": None, "low": None, "volume": None, "amount": None,
            })
        if ops:
            for rec in ops:
                prices_coll.update_one(
                    {"asset_code": final_code, "date": rec["date"]},
                    {"$set": rec},
                    upsert=True,
                )
            print(f"    行情: {len(ops)} 条")

    print()
    print("=" * 60)
    print("2. 导入 fx.xlsx（优先 data/fx.xlsx，引用范围不超出 portfilio-end）")
    print("=" * 60)

    if fx_path.exists():
        df_fx = pd.read_excel(fx_path, index_col=0, parse_dates=True)
        df_fx.columns = df_fx.columns.astype(str).str.strip().str.upper()
        valid = [c for c in ["EUR", "USD", "CNH", "HKD"] if c in df_fx.columns]
        if valid and not df_fx.empty:
            fx_coll.delete_many({})
            rows = []
            for dt, r in df_fx.iterrows():
                rec = {"date": dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]}
                for c in valid:
                    v = r.get(c)
                    if v is not None and pd.notna(v):
                        rec[c] = float(v)
                rows.append(rec)
            if rows:
                fx_coll.insert_many(rows)
                print(f"  导入 {len(rows)} 条汇率")
            # 若从外部路径读取，复制到 data/ 供后续引用
            fx_dest = data_dir / "fx.xlsx"
            if fx_path != fx_dest:
                shutil.copy2(fx_path, fx_dest)
                print(f"  已复制到 {fx_dest}")
        else:
            print("  fx 无有效列")
    else:
        print(f"  跳过: {fx_path} 不存在")

    print()
    print("=" * 60)
    print("3. 复制 trade_dates.xlsx 到 data/")
    print("=" * 60)

    dest = data_dir / "trade_dates.xlsx"
    if trade_dates_path.exists():
        shutil.copy2(trade_dates_path, dest)
        print(f"  已复制到 {dest}")
    else:
        print(f"  跳过: {trade_dates_path} 不存在")

    print()
    print("=" * 60)
    print("导入完成，前台可查询")
    print("=" * 60)


if __name__ == "__main__":
    main()
