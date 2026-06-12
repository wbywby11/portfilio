# -*- coding: utf-8 -*-
"""
从 Excel 导入测试资产与数据到数据库

用法：python -m scripts.import_test_data

数据源：
- daily_px.xlsx: 第一列为日期，后续列为资产（名称或代码）
- fx.xlsx: 第一列为日期，后续列为 EUR/USD/CNH/HKD
- trade_dates.xlsx: 交易日历

规则：同名资产（与库中已有资产）取名为 XXX-测试，代码为 XXX_TEST，避免与原数据重合。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import pandas as pd
import numpy as np

# 资产名称 -> 代码（用于 daily_px 列名为中文时）
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


def _normalize_col(col: str) -> str:
    """标准化列名，去除空白"""
    return str(col).strip() if col is not None else ""


def _resolve_asset_code_and_name(header: str) -> tuple[str, str]:
    """
    根据列名解析资产代码和名称。
    返回 (code, name)。若列名为中文则 name=列名，code 从 NAME_TO_CODE 取；否则 code=列名，name=列名。
    """
    h = _normalize_col(header)
    if not h:
        return "", ""
    h = h.replace(" ", "")
    if h in NAME_TO_CODE:
        return NAME_TO_CODE[h], h
    if h in {v for v in NAME_TO_CODE.values()}:
        rev = {v: k for k, v in NAME_TO_CODE.items()}
        return h, rev.get(h, h)
    return h, h


async def main():
    from app.config.database import Database
    from app.models.asset import Asset, AssetType
    from app.services.asset_service import AssetService
    from app.services.fx_service import FxService

    # 文件路径：优先项目 data/，其次旧版 raw_data（可改 LEGACY_DATA_DIR）
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "data"
    legacy = Path(
        os.environ.get(
            "PORTFOLIO_LEGACY_DATA_DIR",
            r"d:\project\portfilio-end\monitor_vs\raw_data",
        )
    )

    def pick(name: str) -> Path:
        p = data_dir / name
        if p.exists():
            return p
        return legacy / name

    daily_px_path = pick("daily_px.xlsx")
    fx_path = pick("fx.xlsx")
    trade_dates_path = pick("trade_dates.xlsx")

    if not daily_px_path.exists():
        print(f"错误: 找不到 daily_px.xlsx（已查 {data_dir} 与 {legacy}）")
        return

    # 初始化数据库
    Database.connect()

    asset_service = AssetService()
    fx_service = FxService()

    # 获取已有资产（code 和 name 集合，用于判断是否重名）
    existing_codes = set()
    existing_names = set()
    cursor = asset_service.collection.find({"is_active": True})
    async for doc in cursor:
        c = doc.get("code", "")
        n = doc.get("name", "")
        if c:
            existing_codes.add(c)
        if n:
            existing_names.add(n)

    print("=" * 60)
    print("1. 导入 daily_px.xlsx -> 资产 + 行情")
    print("=" * 60)

    df_px = pd.read_excel(daily_px_path)
    df_px.columns = [_normalize_col(c) for c in df_px.columns]

    date_col = df_px.columns[0]
    if "Unnamed" in str(date_col):
        df_px = df_px.rename(columns={date_col: "date"})
        date_col = "date"
    if date_col not in df_px.columns:
        date_col = df_px.columns[0]
    df_px[date_col] = pd.to_datetime(df_px[date_col])
    df_px = df_px.dropna(subset=[date_col])

    asset_columns = [c for c in df_px.columns if c != date_col and _normalize_col(c)]
    print(f"  日期列: {date_col}, 资产列数: {len(asset_columns)}")

    for col in asset_columns:
        code, name = _resolve_asset_code_and_name(col)
        if not code:
            code = col.replace(" ", "_")
            name = col

        is_duplicate = (code in existing_codes) or (name in existing_names)
        if is_duplicate:
            final_code = f"{code}_TEST"
            final_name = f"{name}-测试"
        else:
            final_code = code
            final_name = name

        print(f"  处理: {col} -> code={final_code}, name={final_name} (duplicate={is_duplicate})")

        # 创建或跳过资产
        existing_asset = await asset_service.get_asset_by_code(final_code)
        if not existing_asset:
            asset = Asset(
                code=final_code,
                name=final_name,
                asset_type=AssetType.INDEX,
            )
            await asset_service.create_asset(asset)
            print(f"    创建资产: {final_code}")

        # 导入行情
        prices = df_px[[date_col, col]].copy()
        prices = prices.dropna(subset=[col])
        prices.columns = ["date", "close"]
        prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")
        price_list = [{"date": r["date"], "close": float(r["close"])} for _, r in prices.iterrows()]
        if price_list:
            result = await asset_service.import_price_data(
                asset_code=final_code,
                price_data_list=price_list,
                replace_existing=True,
            )
            print(f"    行情: {result['inserted_count']} 插入, {result['updated_count']} 更新")

    print()
    print("=" * 60)
    print("2. 导入 fx.xlsx -> 汇率")
    print("=" * 60)

    if fx_path.exists():
        df_fx = pd.read_excel(fx_path, index_col=0, parse_dates=True)
        df_fx.columns = df_fx.columns.astype(str).str.strip().str.upper()
        if not df_fx.empty:
            stats = await fx_service.import_from_dataframe(df_fx, mode="replace")
            count = stats["inserted"] + stats["updated"]
            print(f"  导入 {count} 条汇率记录")
        else:
            print("  fx 文件为空")
    else:
        print(f"  跳过: {fx_path} 不存在")

    print()
    print("=" * 60)
    print("3. 复制 trade_dates.xlsx -> data/")
    print("=" * 60)

    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    dest_path = data_dir / "trade_dates.xlsx"
    if trade_dates_path.exists():
        shutil.copy2(trade_dates_path, dest_path)
        print(f"  已复制到 {dest_path}")
    else:
        print(f"  跳过: {trade_dates_path} 不存在")

    print()
    print("=" * 60)
    print("导入完成，前台可查询")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
