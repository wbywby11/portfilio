# -*- coding: utf-8 -*-
"""
xlsx → JSON 转换脚本

将 data/ 目录下的 trade_dates.xlsx、fx.xlsx、daily_px.xlsx 转换为 JSON 格式，
输出到同一目录，供 import_xlsx_data.py 导入 MongoDB 使用。

输出文件：
  - trade_dates.json   : 交易日历 [{date: "YYYY-MM-DD"}, ...]
  - fx_rates.json      : 汇率数据 [{date, USD, CNH, JPY}, ...]
  - daily_px_prices.json: 行情数据 [{asset_code, date, close}, ...]

用法：
  python scripts/xlsx_to_json.py
  python scripts/xlsx_to_json.py --source data/
  python scripts/xlsx_to_json.py --only trade_dates
  python scripts/xlsx_to_json.py --only fx
  python scripts/xlsx_to_json.py --only daily_px
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # portfilio-end/
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

# ---------------------------------------------------------------------------
# daily_px.xlsx 列名 → asset_code 映射（与 assets.json 中的 code 对应）
# ---------------------------------------------------------------------------
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
    "沪铜":         "CU",
    "沪铝":         "AL",
    "沪锡":         "SN",
    "黄金":         "AU",
    "布伦特原油":   "B00Y",
    "豆粕":         "M",
}


def fmt_date(dt: Any) -> Optional[str]:
    """将 datetime 或字符串统一格式化为 YYYY-MM-DD。"""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d")
    if isinstance(dt, str):
        # 尝试解析常见格式
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(dt, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return str(dt)


# ===========================================================================
# 1. trade_dates.xlsx → trade_dates.json
# ===========================================================================
def convert_trade_dates(xlsx_path: Path, out_path: Path) -> int:
    import openpyxl
    print(f"\n[转换] trade_dates.xlsx → trade_dates.json")
    print(f"  读取: {xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active

    records: List[Dict[str, str]] = []
    seen = set()
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        dt_val = row[0]  # 第一列是日期
        date_str = fmt_date(dt_val)
        if date_str and date_str not in seen:
            seen.add(date_str)
            records.append({"date": date_str})

    wb.close()

    # 按日期排序
    records.sort(key=lambda r: r["date"])

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"  交易日数: {len(records)}")
    if records:
        print(f"  日期范围: {records[0]['date']} ~ {records[-1]['date']}")
    print(f"  输出: {out_path}")
    return len(records)


# ===========================================================================
# 2. fx.xlsx → fx_rates.json
# ===========================================================================
def convert_fx(xlsx_path: Path, out_path: Path) -> int:
    import openpyxl
    print(f"\n[转换] fx.xlsx → fx_rates.json")
    print(f"  读取: {xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active

    # 读取表头
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    # 第一列是日期（header 为 None），后面是汇率列
    fx_columns = [h for h in headers[1:] if h is not None]
    print(f"  汇率列: {fx_columns}")

    records: List[Dict[str, Any]] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        dt_val = row[0]
        date_str = fmt_date(dt_val)
        if not date_str:
            continue

        rec: Dict[str, Any] = {"date": date_str}
        for j, col_name in enumerate(fx_columns):
            val = row[j + 1]
            rec[col_name] = val  # 保留 None
        records.append(rec)

    wb.close()

    records.sort(key=lambda r: r["date"])

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"  汇率记录数: {len(records)}")
    if records:
        print(f"  日期范围: {records[0]['date']} ~ {records[-1]['date']}")
    print(f"  输出: {out_path}")
    return len(records)


# ===========================================================================
# 3. daily_px.xlsx → daily_px_prices.json（长格式）
# ===========================================================================
def convert_daily_px(xlsx_path: Path, out_path: Path) -> int:
    import openpyxl
    print(f"\n[转换] daily_px.xlsx → daily_px_prices.json")
    print(f"  读取: {xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active

    # 读取表头并建立列索引 → asset_code 映射
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    col_map: Dict[int, str] = {}  # 列索引 → asset_code
    unmapped: List[str] = []

    for i, h in enumerate(headers):
        if i == 0 or h is None:
            continue  # 跳过日期列
        code = COLUMN_TO_CODE.get(h)
        if code:
            col_map[i] = code
        else:
            unmapped.append(h)

    if unmapped:
        print(f"  [警告] 以下列未找到映射: {unmapped}")
    print(f"  已映射列 ({len(col_map)}): {list(col_map.values())}")

    records: List[Dict[str, Any]] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        dt_val = row[0]
        date_str = fmt_date(dt_val)
        if not date_str:
            continue

        for col_idx, asset_code in col_map.items():
            val = row[col_idx] if col_idx < len(row) else None
            if val is not None:
                records.append({
                    "asset_code": asset_code,
                    "date": date_str,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": val,
                    "volume": None,
                    "amount": None,
                })

    wb.close()

    # 按 asset_code + date 排序
    records.sort(key=lambda r: (r["asset_code"], r["date"]))

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    # 统计
    codes = set(r["asset_code"] for r in records)
    dates = [r["date"] for r in records]
    print(f"  行情记录数: {len(records)}")
    print(f"  涉及资产数: {len(codes)}")
    print(f"  资产代码: {sorted(codes)}")
    if dates:
        print(f"  日期范围: {min(dates)} ~ {max(dates)}")
    print(f"  输出: {out_path}")
    return len(records)


# ===========================================================================
# 主流程
# ===========================================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="xlsx → JSON 转换（trade_dates / fx / daily_px）",
    )
    parser.add_argument("--source", type=str, default=None,
                        help=f"xlsx 文件目录（默认 {DEFAULT_DATA_DIR}）")
    parser.add_argument("--output", type=str, default=None,
                        help="JSON 输出目录（默认与 xlsx 同目录）")
    parser.add_argument("--only", type=str,
                        choices=["trade_dates", "fx", "daily_px"],
                        help="只转换指定类型")
    args = parser.parse_args()

    data_dir = Path(args.source) if args.source else DEFAULT_DATA_DIR
    out_dir = Path(args.output) if args.output else data_dir

    if not data_dir.is_dir():
        print(f"错误: 数据目录不存在 {data_dir}")
        sys.exit(1)

    print("=" * 60)
    print("xlsx → JSON 转换")
    print(f"数据源: {data_dir}")
    print(f"输出目录: {out_dir}")
    print("=" * 60)

    total = 0

    # 1. trade_dates
    if not args.only or args.only == "trade_dates":
        xlsx = data_dir / "trade_dates.xlsx"
        if xlsx.is_file():
            total += convert_trade_dates(xlsx, out_dir / "trade_dates.json")
        else:
            print(f"\n[跳过] trade_dates.xlsx 不存在: {xlsx}")

    # 2. fx
    if not args.only or args.only == "fx":
        xlsx = data_dir / "fx.xlsx"
        if xlsx.is_file():
            total += convert_fx(xlsx, out_dir / "fx_rates.json")
        else:
            print(f"\n[跳过] fx.xlsx 不存在: {xlsx}")

    # 3. daily_px
    if not args.only or args.only == "daily_px":
        xlsx = data_dir / "daily_px.xlsx"
        if xlsx.is_file():
            total += convert_daily_px(xlsx, out_dir / "daily_px_prices.json")
        else:
            print(f"\n[跳过] daily_px.xlsx 不存在: {xlsx}")

    print(f"\n{'=' * 60}")
    print(f"转换完成！共生成 {total} 条 JSON 记录")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
