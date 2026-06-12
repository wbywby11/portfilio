# -*- coding: utf-8 -*-
"""
从宽表净值 Excel 生成 mongoimport 用 assets / asset_prices JSON（不写库）。

自动识别 Sheet：第 5 行为「Date + *.OF」（新模板）则从第 6 行起为数据；
第 5 列为 unit_nv（旧模板）则从第 7 行起为数据。名称取自第 4 行、代码取自第 5 行。

用法（项目根目录）:
  python -m scripts.export_fund_excel_to_mongo_json

环境变量 FUND_XLSX 可覆盖源文件路径。
输出 data/fund_assets.import.json、data/fund_asset_prices.import.json（JSON 数组）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_XLSX = Path(
    r"c:\Users\wangb\xwechat_files\wxid_l7trc60uwzre22_b8b1\msg\file\2026-05\量化基金净值数据0509.xlsx"
)


def _mongo_date(dt: datetime) -> dict:
    return {"$date": dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"}


def _first_data_row_index(df: pd.DataFrame) -> int:
    """第 6 行为单位净值表头时为旧版；新版第 6 行为首行日期。"""
    c0 = df.iloc[4, 0]
    if isinstance(c0, str) and c0.strip().lower() == "unit_nv":
        return 6
    return 5


def _guess_nav_sheet(xlsx_path: Path) -> tuple[str, pd.DataFrame]:
    xl = pd.ExcelFile(xlsx_path)
    best: tuple[str, pd.DataFrame] | None = None
    best_cols = 0
    for name in xl.sheet_names:
        df = pd.read_excel(xlsx_path, sheet_name=name, header=None)
        if df.shape[0] < 8 or df.shape[1] < 3:
            continue
        c1 = df.iloc[4, 1]
        if pd.isna(c1):
            continue
        sc = str(c1).strip()
        if sc.endswith(".OF"):
            ncol = df.shape[1]
            if ncol > best_cols:
                best_cols = ncol
                best = (name, df)
    if best is None:
        raise ValueError(f"无法在 {xlsx_path} 中识别净值宽表 Sheet（需在行 5 列 2 起为 *.OF 代码）")
    return best


def _pair_name_code(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    names: list[str] = []
    codes: list[str] = []
    for j in range(1, df.shape[1]):
        cell = df.iloc[4, j]
        if pd.isna(cell):
            continue
        code = str(cell).strip()
        if not code.endswith(".OF"):
            continue
        nc = df.iloc[3, j]
        name = str(nc).strip() if pd.notna(nc) else code
        names.append(name)
        codes.append(code)
    if not codes:
        raise ValueError("未解析到任何基金代码（*.OF）")
    return names, codes


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    xlsx = Path(os.environ.get("FUND_XLSX", str(DEFAULT_XLSX)))
    if not xlsx.exists():
        raise FileNotFoundError(xlsx)

    sheet_name, df = _guess_nav_sheet(xlsx)
    names, codes = _pair_name_code(df)
    data_start = _first_data_row_index(df)

    body = df.iloc[data_start:, :].copy()
    body = body.dropna(subset=[0])
    body.iloc[:, 0] = pd.to_datetime(body.iloc[:, 0], errors="coerce")
    body = body.dropna(subset=[0])

    now = _mongo_date(datetime.now(timezone.utc))

    asset_docs = []
    for name, code in zip(names, codes):
        asset_docs.append(
            {
                "code": code,
                "name": name,
                "asset_type": "基金",
                "exchange": None,
                "description": None,
                "is_active": True,
                "rollover_days": None,
                "rollover_threshold": None,
                "rollover_window_p": None,
                "rollover_window_q": None,
                "substitute_code": None,
                "switch_date": None,
                "currency": None,
                "trading_cost_rate": None,
                "replication_cost_rate": None,
                "created_at": now,
                "updated_at": now,
            }
        )

    price_docs: list[dict] = []
    for ci, code in enumerate(codes, start=1):
        for _, row in body.iterrows():
            d_raw = row[0]
            if pd.isna(d_raw):
                continue
            nv = row[ci]
            if pd.isna(nv):
                continue
            try:
                close = float(nv)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            d_str = pd.Timestamp(d_raw).strftime("%Y-%m-%d")
            price_docs.append(
                {
                    "asset_code": code,
                    "date": d_str,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": close,
                    "volume": None,
                    "amount": None,
                    "scale": None,
                }
            )

    assets_path = out_dir / "fund_assets.import.json"
    prices_path = out_dir / "fund_asset_prices.import.json"

    for path, docs in [(assets_path, asset_docs), (prices_path, price_docs)]:
        with path.open("w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)

    print(f"源: {xlsx} 工作表 `{sheet_name}` 数据起始行(0-based)={data_start}")
    print(f"资产条数: {len(asset_docs)} -> {assets_path}")
    print(f"行情条数: {len(price_docs)} -> {prices_path}")


if __name__ == "__main__":
    main()
