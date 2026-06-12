# -*- coding: utf-8 -*-
"""
从 raw_data / data 中的 daily_px.xlsx 导入监控 12 类资产行情到 MongoDB，
**始终使用标准 asset_code（无 _TEST 后缀）**，与 app.monitor.config.ASSET_NAME_TO_CODE 一致。

与 import_test_data.py 的区别：
- 不因库中已存在资产而改名为 XXX_TEST / 中文名-测试
- 适合把「权威 raw」同步到生产码上

数据源查找顺序（任一目录内命中即用）：
1. 环境变量 RAW_DATA_DIR 指向的目录
2. 项目根目录 raw_data/
3. 项目根目录 scripts/raw_data/（常与脚本同级放原始表）
4. 项目根目录 data/
5. 环境变量 PORTFOLIO_LEGACY_DATA_DIR（与 import_test_data 兼容）

同一目录内：若存在 daily_px(1).xlsx 等与 daily_px.xlsx 并列的带 (n) 副本，优先选用其中修改时间最新者（通常副本为最新下载）。

可选：同目录下 fx.xlsx、trade_dates.xlsx 一并导入（见 --with-fx / --copy-trade-dates）

用法（在项目根目录）:
  python scripts/import_canonical_prices_from_raw.py
  python scripts/import_canonical_prices_from_raw.py --replace
  python scripts/import_canonical_prices_from_raw.py --with-fx --copy-trade-dates
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional, Tuple

# 同目录下 Excel 另存为副本时常见 daily_px(1).xlsx / daily_px (1).xlsx，优先于 daily_px.xlsx
_DAILY_PX_NUM_SUFFIX = re.compile(r"^(.+?)\((\d+)\)\s*$")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import pandas as pd

from app.monitor import config


def _normalize_col(col) -> str:
    return str(col).strip() if col is not None else ""


def _strip_test_markers(header: str) -> str:
    """列名可能来自测试表：去掉 -测试 或 _TEST 再解析。"""
    h = _normalize_col(header).replace(" ", "")
    suf_cn = "-测试"
    if h.endswith(suf_cn):
        h = h[: -len(suf_cn)]
    if h.endswith("_TEST"):
        h = h[: -len("_TEST")]
    return h


def resolve_canonical(header: str) -> Optional[Tuple[str, str]]:
    """
    解析为 (标准 asset_code, 标准中文名)。
    列名为中文或代码均可；无法映射到监控 12 类则返回 None。
    """
    h = _strip_test_markers(header)
    if not h:
        return None
    if h in config.ASSET_NAME_TO_CODE:
        code = config.ASSET_NAME_TO_CODE[h]
        return code, h
    if h in config.ASSET_CODE_TO_NAME:
        return h, config.ASSET_CODE_TO_NAME[h]
    return None


def _pick_daily_px_in_dir(base: Path) -> Optional[Path]:
    """目录内 daily_px*.xlsx：优先带 (n) 后缀的副本（取最新 mtime），否则 daily_px.xlsx。"""
    if not base.is_dir():
        return None
    try:
        candidates = list(base.glob("daily_px*.xlsx"))
    except OSError:
        return None
    if not candidates:
        return None
    numbered = [p for p in candidates if _DAILY_PX_NUM_SUFFIX.match(p.stem.strip())]
    if numbered:
        return max(numbered, key=lambda p: p.stat().st_mtime)
    plain = base / "daily_px.xlsx"
    if plain.exists():
        return plain
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_daily_px_file() -> Tuple[Optional[Path], list[Path]]:
    """返回 (daily_px 行情表路径, 已检查过的目录列表)。"""
    checked: list[Path] = []
    bases: list[Path] = []
    raw_env = os.environ.get("RAW_DATA_DIR", "").strip()
    if raw_env:
        bases.append(Path(raw_env))
    bases.append(project_root / "raw_data")
    bases.append(project_root / "scripts" / "raw_data")
    bases.append(project_root / "data")
    leg = os.environ.get("PORTFOLIO_LEGACY_DATA_DIR", "").strip()
    if leg:
        bases.append(Path(leg))

    for base in bases:
        checked.append(base)
        p = _pick_daily_px_in_dir(base)
        if p is not None and p.is_file():
            return p, checked
    return None, checked


async def main() -> None:
    parser = argparse.ArgumentParser(description="从 raw_data 导入标准码行情")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="每个资产导入前删除该 asset_code 下旧行情再写入（与 Excel 全量一致）",
    )
    parser.add_argument(
        "--with-fx",
        action="store_true",
        help="若 daily_px 同目录存在 fx.xlsx，则导入 Mongo fx_rates",
    )
    parser.add_argument(
        "--copy-trade-dates",
        action="store_true",
        help="若同目录存在 trade_dates.xlsx，复制到 data/trade_dates.xlsx",
    )
    args = parser.parse_args()

    daily_path, checked = find_daily_px_file()
    if not daily_path:
        print("错误: 找不到 daily_px.xlsx，已检查目录:")
        for c in checked:
            print(f"  - {c}")
        print("\n请将 daily_px.xlsx（或 daily_px(1).xlsx 等副本）放到 raw_data/、scripts/raw_data/、data/ 之一，或设置 RAW_DATA_DIR。")
        sys.exit(1)

    data_root = daily_path.parent
    print(f"使用行情文件: {daily_path}")
    print(f"数据根目录: {data_root}")

    from app.config.database import Database
    from app.models.asset import Asset, AssetType
    from app.services.asset_service import AssetService
    from app.services.fx_service import FxService

    Database.connect()
    asset_service = AssetService()
    fx_service = FxService()

    df_px = pd.read_excel(daily_path)
    df_px.columns = [_normalize_col(c) for c in df_px.columns]

    date_col = df_px.columns[0]
    if "Unnamed" in str(date_col):
        df_px = df_px.rename(columns={date_col: "date"})
        date_col = "date"
    df_px[date_col] = pd.to_datetime(df_px[date_col])
    df_px = df_px.dropna(subset=[date_col])

    asset_columns = [c for c in df_px.columns if c != date_col and _normalize_col(c)]
    print(f"日期列: {date_col}, 资产列数: {len(asset_columns)}")

    seen_codes: set[str] = set()

    for col in asset_columns:
        resolved = resolve_canonical(col)
        if not resolved:
            print(f"  跳过（非监控12类）: {col}")
            continue
        code, cn_name = resolved
        if code in seen_codes:
            print(f"  警告: 列 {col} 与已处理资产 {code} 重复，后写覆盖前写")
        seen_codes.add(code)

        print(f"  导入: 列={col} -> code={code} name={cn_name} replace={args.replace}")

        existing = await asset_service.get_asset_by_code(code)
        if not existing:
            asset = Asset(code=code, name=cn_name, asset_type=AssetType.INDEX)
            await asset_service.create_asset(asset)
            print(f"    已创建资产文档: {code}")

        prices = df_px[[date_col, col]].copy()
        prices = prices.dropna(subset=[col])
        prices.columns = ["date", "close"]
        prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")
        price_list = [{"date": r["date"], "close": float(r["close"])} for _, r in prices.iterrows()]
        if not price_list:
            print("    无有效行，跳过")
            continue

        result = await asset_service.import_price_data(
            asset_code=code,
            price_data_list=price_list,
            replace_existing=args.replace,
        )
        print(
            f"    完成: inserted={result['inserted_count']} updated={result['updated_count']} "
            f"errors={result['error_count']}"
        )

    if args.with_fx:
        fx_path = data_root / "fx.xlsx"
        print()
        print("=" * 60)
        print("导入 fx.xlsx -> fx_rates")
        print("=" * 60)
        if fx_path.exists():
            df_fx = pd.read_excel(fx_path, index_col=0, parse_dates=True)
            df_fx.columns = df_fx.columns.astype(str).str.strip().str.upper()
            if not df_fx.empty:
                stats = await fx_service.import_from_dataframe(df_fx, mode="replace")
                n = stats["inserted"] + stats["updated"]
                print(f"  已导入 {n} 条")
            else:
                print("  fx 为空")
        else:
            print(f"  跳过: 不存在 {fx_path}")

    if args.copy_trade_dates:
        src = data_root / "trade_dates.xlsx"
        print()
        print("=" * 60)
        print("复制 trade_dates.xlsx -> data/")
        print("=" * 60)
        dest_dir = project_root / "data"
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / "trade_dates.xlsx"
        if src.exists():
            shutil.copy2(src, dest)
            print(f"  已复制: {dest}")
        else:
            print(f"  跳过: 不存在 {src}")

    print()
    print("标准码行情导入流程结束。")


if __name__ == "__main__":
    asyncio.run(main())
