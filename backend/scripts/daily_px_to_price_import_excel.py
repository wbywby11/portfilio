# -*- coding: utf-8 -*-
"""
从 raw_data / data 中的 daily_px.xlsx 导出「单资产行情导入」用 Excel。

前端：资产行情页「批量导入行情」与接口下载模板列一致：
  日期*, 开盘价, 最高价, 最低价, 收盘价*, 成交量, 成交额
daily_px 仅有收盘价时，只填 日期* 与 收盘价*，其余列留空。

查找 daily_px 路径顺序与 import_canonical_prices_from_raw.py 相同
（RAW_DATA_DIR → raw_data/ → scripts/raw_data/ → data/ → PORTFOLIO_LEGACY_DATA_DIR；
同目录内优先 daily_px(n).xlsx 副本）。

用法（在 portfilio-end 根目录）:

  # 列出各列及解析到的标准代码（若有）
  python scripts/daily_px_to_price_import_excel.py --list

  # 按资产代码或中文名列名导出单个文件
  python scripts/daily_px_to_price_import_excel.py --asset SH000300
  python scripts/daily_px_to_price_import_excel.py --asset 沪深300

  # 按 Excel 列名精确导出
  python scripts/daily_px_to_price_import_excel.py --column "沪深300"

  # 为每一资产生成一个 xlsx（默认写到 daily_px 同目录，如 raw_data/）
  python scripts/daily_px_to_price_import_excel.py --all

  # 指定原始文件路径
  python scripts/daily_px_to_price_import_excel.py --input raw_data/daily_px.xlsx --asset SPX
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 与 canonical 脚本一致的路径解析、列名 -> 标准码
_SPEC = importlib.util.spec_from_file_location(
    "_canonical_prices",
    PROJECT_ROOT / "scripts" / "import_canonical_prices_from_raw.py",
)
_canonical = importlib.util.module_from_spec(_SPEC)
sys.path.insert(0, str(PROJECT_ROOT))
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_canonical)
find_daily_px_file = _canonical.find_daily_px_file
resolve_canonical = _canonical.resolve_canonical

TEMPLATE_COLUMNS = ["日期*", "开盘价", "最高价", "最低价", "收盘价*", "成交量", "成交额"]


def _norm_col(c) -> str:
    return str(c).strip() if c is not None else ""


def _safe_filename(code: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', "_", code.strip())
    return s[:120] if len(s) > 120 else s


def load_daily_px(path: Path) -> tuple[pd.DataFrame, str]:
    df = pd.read_excel(path)
    df.columns = [_norm_col(c) for c in df.columns]
    date_col = df.columns[0]
    if "Unnamed" in str(date_col):
        df = df.rename(columns={date_col: "date"})
        date_col = "date"
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])
    return df, date_col


def find_asset_column(df: pd.DataFrame, date_col: str, token: str) -> str | None:
    t = token.strip()
    if not t:
        return None
    for c in df.columns:
        if c == date_col:
            continue
        if _norm_col(c) == t:
            return c
        resolved = resolve_canonical(c)
        if resolved and (resolved[0] == t or resolved[1] == t):
            return c
    return None


def build_import_frame(df: pd.DataFrame, date_col: str, price_col: str) -> pd.DataFrame:
    sub = df[[date_col, price_col]].dropna(subset=[price_col]).copy()
    sub[date_col] = pd.to_datetime(sub[date_col])
    sub = sub.sort_values(date_col)
    dates = sub[date_col].dt.strftime("%Y-%m-%d")
    closes = pd.to_numeric(sub[price_col], errors="coerce")
    mask = closes.notna()
    dates = dates[mask]
    closes = closes[mask]
    out = pd.DataFrame(
        {
            "日期*": dates.values,
            "开盘价": "",
            "最高价": "",
            "最低价": "",
            "收盘价*": closes.values,
            "成交量": "",
            "成交额": "",
        }
    )
    return out


def default_output_basename(header: str) -> str:
    r = resolve_canonical(header)
    if r:
        return _safe_filename(r[0])
    return _safe_filename(_norm_col(header) or "asset")


def main() -> None:
    parser = argparse.ArgumentParser(description="daily_px → 单资产行情导入 Excel")
    parser.add_argument("--input", "-i", type=Path, help="daily_px.xlsx 路径（默认自动查找）")
    parser.add_argument("--asset", "-a", help="资产代码或中文名（与监控配置或列名匹配）")
    parser.add_argument("--column", "-c", help="Excel 列名（精确匹配表头）")
    parser.add_argument("--all", action="store_true", help="为每个资产列各导出一个文件")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录（默认与 daily_px.xlsx 同目录；与 --all / 单资产默认输出一致）",
    )
    parser.add_argument(
        "-O",
        "--output-file",
        type=Path,
        help="单文件输出路径（仅单资产模式；默认写到输出目录下 代码.xlsx）",
    )
    parser.add_argument("--list", action="store_true", help="仅列出列与解析结果")
    args = parser.parse_args()

    daily_path = args.input
    checked: list[Path] = []
    if daily_path is None:
        daily_path, checked = find_daily_px_file()
    else:
        daily_path = daily_path.resolve()
        if not daily_path.is_file():
            print(f"错误: 文件不存在 {daily_path}")
            sys.exit(1)

    if daily_path is None or not daily_path.is_file():
        print("错误: 找不到 daily_px.xlsx，已检查:")
        for p in checked:
            print(f"  - {p}")
        sys.exit(1)

    print(f"使用: {daily_path}")
    out_dir_default = daily_path.parent
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else out_dir_default
    )

    df, date_col = load_daily_px(daily_path)
    asset_cols = [c for c in df.columns if c != date_col and _norm_col(c)]

    if args.list:
        print(f"日期列: {date_col!r}, 共 {len(asset_cols)} 个资产列:\n")
        for col in asset_cols:
            r = resolve_canonical(col)
            extra = f" -> {r[0]} ({r[1]})" if r else " -> (未映射到监控标准码，仍可按列名导出)"
            print(f"  {col!r}{extra}")
        return

    if args.all:
        out_dir = output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for col in asset_cols:
            frame = build_import_frame(df, date_col, col)
            if frame.empty:
                print(f"  跳过（无有效收盘价）: {col}")
                continue
            base = default_output_basename(col)
            fp = out_dir / f"{base}.xlsx"
            frame.to_excel(fp, index=False, sheet_name="行情导入模板")
            print(f"  已写 {len(frame)} 行 -> {fp}")
            n += 1
        print(f"完成: 共 {n} 个文件 -> {out_dir}")
        return

    col = None
    if args.column:
        key = _norm_col(args.column)
        if key not in df.columns:
            print(f"错误: 无此列 {key!r}。使用 --list 查看列名。")
            sys.exit(1)
        col = key
    elif args.asset:
        col = find_asset_column(df, date_col, args.asset)
        if col is None:
            print(f"错误: 无法匹配资产 {args.asset!r}。使用 --list 查看列名。")
            sys.exit(1)
    else:
        parser.error("请指定 --asset / --column，或使用 --all / --list")

    frame = build_import_frame(df, date_col, col)
    if frame.empty:
        print("错误: 该列无有效收盘价行。")
        sys.exit(1)

    if args.output_file:
        fp = args.output_file.resolve()
        fp.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        fp = out_dir / f"{default_output_basename(col)}.xlsx"

    frame.to_excel(fp, index=False, sheet_name="行情导入模板")
    print(f"已导出 {len(frame)} 行 -> {fp}")
    print("下一步: 前端打开「资产行情」，选中对应资产后使用「批量导入行情」上传该文件。")


if __name__ == "__main__":
    main()
