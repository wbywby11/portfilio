"""
将 daily_px.xlsx 转换为 '大类资产底层数据上传版本' 的格式:
  - 第1行: 资产中文名称
  - 第2行: 资产代码（从 MongoDB 匹配）
  - 第3行起: 日期 + 收盘价数据

用法:
  python scripts/convert_daily_px_format.py

输出:
  scripts/daily_px_formatted.xlsx
"""

import openpyxl
import pandas as pd
from pymongo import MongoClient
from pathlib import Path
import sys

# ── 配置 ─────────────────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"
ASSETS_COL = "assets"

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_FILE = SCRIPT_DIR / "daily_px.xlsx"
OUTPUT_FILE = SCRIPT_DIR / "daily_px_formatted.xlsx"


def get_asset_name_to_code(db) -> dict:
    """从 MongoDB assets 集合获取 name -> code 映射"""
    mapping = {}
    for doc in db[ASSETS_COL].find({}, {"code": 1, "name": 1}):
        mapping[doc["name"]] = doc["code"]
    return mapping


def fuzzy_match(col_name: str, name_to_code: dict) -> tuple:
    """模糊匹配资产名称，返回 (matched_name, code) 或 (None, None)"""
    # 精确匹配
    if col_name in name_to_code:
        return col_name, name_to_code[col_name]

    # 模糊匹配（包含关系）
    col_stripped = col_name.strip()
    for sys_name, sys_code in name_to_code.items():
        if col_stripped in sys_name or sys_name in col_stripped:
            return sys_name, sys_code

    return None, None


def main():
    # 1. 读取 daily_px.xlsx
    if not INPUT_FILE.exists():
        print(f"错误：找不到输入文件 {INPUT_FILE}")
        sys.exit(1)

    print(f"读取输入文件: {INPUT_FILE}")
    df = pd.read_excel(INPUT_FILE, sheet_name="Sheet1", index_col=0)
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    print(f"  列数（资产）: {len(df.columns)}")
    print(f"  行数（日期）: {len(df)}")
    print(f"  日期范围: {df.index.min().date()} ~ {df.index.max().date()}")
    print(f"  资产列: {list(df.columns)}")

    # 2. 连接 MongoDB 获取名称到代码的映射
    print(f"\n连接 MongoDB: {MONGO_URI}/{DB_NAME}")
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
        db = client[DB_NAME]
        print("  连接成功 ✓")
    except Exception as e:
        print(f"  连接失败: {e}")
        sys.exit(1)

    name_to_code = get_asset_name_to_code(db)
    print(f"  系统中已有资产数: {len(name_to_code)}")

    # 3. 为每一列匹配资产代码
    matched_names = []
    matched_codes = []
    matched_cols = []
    unmatched = []

    for col_name in df.columns:
        sys_name, code = fuzzy_match(col_name, name_to_code)
        if code:
            matched_names.append(col_name)
            matched_codes.append(code)
            matched_cols.append(col_name)
            if sys_name != col_name:
                print(f"  模糊匹配: '{col_name}' -> '{sys_name}' ({code})")
            else:
                print(f"  精确匹配: '{col_name}' -> {code}")
        else:
            unmatched.append(col_name)
            print(f"  未匹配: '{col_name}'")

    if unmatched:
        print(f"\n警告: {len(unmatched)} 个资产未在系统中找到匹配: {unmatched}")

    # 4. 按目标格式生成 Excel 文件
    # 格式: 第1行=资产名, 第2行=资产代码, 第3行起=日期+数据
    print(f"\n生成输出文件: {OUTPUT_FILE}")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    num_assets = len(matched_cols)

    # 第1行: 第1列空（日期列标题），后面是资产名称
    ws.cell(1, 1, "日期")
    for i, name in enumerate(matched_names):
        ws.cell(1, i + 2, name)

    # 第2行: 第1列空，后面是资产代码
    ws.cell(2, 1, "")
    for i, code in enumerate(matched_codes):
        ws.cell(2, i + 2, code)

    # 第3行起: 日期 + 数据
    for row_idx, (date_val, row_data) in enumerate(df[matched_cols].iterrows(), start=3):
        # 写入日期
        ws.cell(row_idx, 1, date_val.to_pydatetime())
        ws.cell(row_idx, 1).number_format = "YYYY-MM-DD"

        # 写入各资产数据
        for col_idx, col_name in enumerate(matched_cols):
            val = row_data[col_name]
            if pd.notna(val):
                ws.cell(row_idx, col_idx + 2, float(val))

    wb.save(OUTPUT_FILE)

    # 5. 打印统计信息
    print(f"\n{'='*60}")
    print(f"转换完成!")
    print(f"  匹配资产数: {num_assets}")
    print(f"  未匹配资产: {len(unmatched)}")
    print(f"  数据行数: {len(df)}")
    print(f"  输出文件: {OUTPUT_FILE}")
    print(f"\n格式说明:")
    print(f"  第1行: 资产中文名称")
    print(f"  第2行: 资产代码")
    print(f"  第3行起: 日期 + 收盘价数据")
    print(f"\n资产映射表:")
    print(f"  {'资产名':<16} {'代码':<14}")
    print(f"  {'─'*30}")
    for name, code in zip(matched_names, matched_codes):
        print(f"  {name:<14} {code:<14}")

    client.close()


if __name__ == "__main__":
    main()
