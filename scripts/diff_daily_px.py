"""
对比 daily_px.xlsx 与 MongoDB asset_prices 集合中的现有数据，
输出仅包含系统中缺失条目的增量 Excel 文件（格式与原文件一致）。

用法:
  python scripts/diff_daily_px.py

输出:
  scripts/daily_px_incremental.xlsx  — 仅包含系统中没有的数据
"""

import pandas as pd
from pymongo import MongoClient
from pathlib import Path
import sys

# ── 配置 ─────────────────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"
ASSETS_COL = "assets"
PRICES_COL = "asset_prices"

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_FILE = SCRIPT_DIR / "daily_px.xlsx"
OUTPUT_FILE = SCRIPT_DIR / "daily_px_incremental.xlsx"

# ── 主逻辑 ─────────────────────────────────────────────────────────


def load_daily_px(path: Path) -> pd.DataFrame:
    """读取 daily_px.xlsx，返回以日期为索引、资产名称为列名的 DataFrame"""
    df = pd.read_excel(path, sheet_name="Sheet1", index_col=0)
    # 确保索引是日期类型
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    return df


def get_asset_name_to_code(db) -> dict:
    """从 MongoDB assets 集合获取 name -> code 映射"""
    mapping = {}
    for doc in db[ASSETS_COL].find({}, {"code": 1, "name": 1}):
        mapping[doc["name"]] = doc["code"]
    return mapping


def get_existing_dates_by_code(db, asset_code: str) -> set:
    """查询某资产在 asset_prices 中已有的所有日期"""
    dates = set()
    cursor = db[PRICES_COL].find(
        {"asset_code": asset_code},
        {"date": 1, "_id": 0}
    )
    for doc in cursor:
        d = doc.get("date")
        if d:
            # date 可能是字符串 "YYYY-MM-DD" 或 datetime
            if isinstance(d, str):
                dates.add(pd.Timestamp(d))
            else:
                dates.add(pd.Timestamp(d).normalize())
    return dates


def main():
    # 1. 读取 Excel
    if not INPUT_FILE.exists():
        print(f"错误：找不到输入文件 {INPUT_FILE}")
        sys.exit(1)

    print(f"读取输入文件: {INPUT_FILE}")
    df = load_daily_px(INPUT_FILE)
    print(f"  列数（资产）: {len(df.columns)}")
    print(f"  行数（日期）: {len(df)}")
    print(f"  日期范围: {df.index.min().date()} ~ {df.index.max().date()}")
    print(f"  资产列: {list(df.columns)}")

    # 2. 连接 MongoDB
    print(f"\n连接 MongoDB: {MONGO_URI}/{DB_NAME}")
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()  # 测试连接
        db = client[DB_NAME]
        print("  连接成功 ✓")
    except Exception as e:
        print(f"  连接失败: {e}")
        print("  将输出全部数据作为增量（假设系统中没有任何数据）")
        df.to_excel(OUTPUT_FILE)
        print(f"\n输出文件: {OUTPUT_FILE}")
        return

    # 3. 获取资产名称到代码的映射
    name_to_code = get_asset_name_to_code(db)
    print(f"\n系统中已有资产数: {len(name_to_code)}")

    # 4. 对比每个资产，标记已有数据为 NaN
    incremental_df = df.copy()
    stats = []

    for col_name in df.columns:
        # 尝试匹配资产代码
        asset_code = name_to_code.get(col_name)

        if asset_code is None:
            # 尝试模糊匹配（去空格、部分匹配）
            for sys_name, sys_code in name_to_code.items():
                if col_name.strip() in sys_name or sys_name in col_name.strip():
                    asset_code = sys_code
                    print(f"  模糊匹配: '{col_name}' -> '{sys_name}' ({sys_code})")
                    break

        if asset_code is None:
            # 系统中不存在该资产，保留所有数据
            non_null_count = df[col_name].notna().sum()
            stats.append({
                "asset": col_name,
                "code": "（未匹配）",
                "total": non_null_count,
                "existing": 0,
                "incremental": non_null_count
            })
            print(f"  {col_name}: 系统中无此资产，保留全部 {non_null_count} 条")
            continue

        # 查询已有日期
        existing_dates = get_existing_dates_by_code(db, asset_code)
        total_in_file = df[col_name].notna().sum()

        # 将已有日期的数据标记为 NaN（即排除掉）
        removed_count = 0
        for date_idx in df.index:
            if pd.notna(df.at[date_idx, col_name]):
                normalized_date = pd.Timestamp(date_idx).normalize()
                if normalized_date in existing_dates:
                    incremental_df.at[date_idx, col_name] = None
                    removed_count += 1

        incremental_count = total_in_file - removed_count
        stats.append({
            "asset": col_name,
            "code": asset_code,
            "total": total_in_file,
            "existing": removed_count,
            "incremental": incremental_count
        })
        print(f"  {col_name} ({asset_code}): 文件 {total_in_file} 条, "
              f"系统已有 {removed_count} 条, 增量 {incremental_count} 条")

    # 5. 删除全部为 NaN 的列和行
    # 先去掉完全没有增量数据的列
    incremental_df = incremental_df.dropna(axis=1, how="all")
    # 再去掉全部为 NaN 的行（所有资产在该日期都已存在）
    incremental_df = incremental_df.dropna(how="all")

    # 6. 输出结果
    print(f"\n{'='*60}")
    print(f"增量数据统计:")
    print(f"  原始日期数: {len(df)}")
    print(f"  增量日期数: {len(incremental_df)}")

    total_cells = sum(s["incremental"] for s in stats)
    print(f"  增量数据条目: {total_cells}")

    if len(incremental_df) == 0:
        print("\n系统中已包含所有数据，无需增量导入。")
    else:
        incremental_df.to_excel(OUTPUT_FILE)
        print(f"\n输出文件: {OUTPUT_FILE}")
        print(f"  格式：与原 daily_px.xlsx 相同（日期为行索引，资产名为列名）")
        print(f"  可直接通过前端「多资产行情导入」功能上传此文件")

    # 打印详细统计表
    print(f"\n{'─'*60}")
    print(f"{'资产':<12} {'代码':<14} {'文件':>6} {'系统已有':>8} {'增量':>6}")
    print(f"{'─'*60}")
    for s in stats:
        print(f"{s['asset']:<10} {s['code']:<14} {s['total']:>6} "
              f"{s['existing']:>8} {s['incremental']:>6}")
    print(f"{'─'*60}")

    client.close()


if __name__ == "__main__":
    main()
