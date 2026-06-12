"""
从 daily_px.xlsx 生成可直接导入 MongoDB 的 JSON 文件:
  - daily_px_assets.json        → 导入到 assets 集合
  - daily_px_asset_prices.json  → 导入到 asset_prices 集合

支持两种文件格式:
  格式A（旧）: 第1行直接为资产名称列头，第1列为日期，无代码行
  格式B（新）: 第1行为资产中文名，第2行为资产代码（首列值为"Date"），第3行起为数据

数据格式与 generate_import_json.py 完全一致:
  - assets: {code, name, asset_type, exchange, description, is_active, created_at, updated_at}
  - asset_prices: {asset_code, date, open, high, low, close, volume, amount, scale}
    (仅 close 有值，其余 OHLCVA+Scale 字段显式设为 null)

用法:
  python scripts/generate_daily_px_json.py
"""

import json
import openpyxl
import pandas as pd
from pymongo import MongoClient
from pathlib import Path
from datetime import datetime
import sys

# ── 配置 ─────────────────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"
ASSETS_COL = "assets"

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_FILE = SCRIPT_DIR / "daily_px.xlsx"
OUTPUT_ASSETS = SCRIPT_DIR / "daily_px_assets.json"
OUTPUT_PRICES = SCRIPT_DIR / "daily_px_asset_prices.json"


def detect_format(ws) -> str:
    """检测文件格式: 'B' = 第2行含代码行(首列为Date), 'A' = 旧格式"""
    cell_b2 = ws.cell(2, 1).value
    if cell_b2 and str(cell_b2).strip().lower() == "date":
        return "B"
    return "A"


def load_format_b(ws):
    """
    格式B: 第1行=中文名, 第2行=代码(首列'Date'), 第3行起=数据
    返回 (names, codes, rows) rows = [(date_str, [val,...])]
    """
    max_col = ws.max_column
    names = [ws.cell(1, c).value for c in range(2, max_col + 1)]
    codes = [ws.cell(2, c).value for c in range(2, max_col + 1)]

    rows = []
    for r in range(3, ws.max_row + 1):
        date_val = ws.cell(r, 1).value
        if date_val is None:
            continue
        vals = [ws.cell(r, c).value for c in range(2, max_col + 1)]
        rows.append((date_val, vals))
    return names, codes, rows


def get_code_to_info(db) -> dict:
    """从 MongoDB assets 集合获取 code -> doc 映射"""
    mapping = {}
    for doc in db[ASSETS_COL].find({}):
        doc.pop("_id", None)
        mapping[doc["code"]] = doc
    return mapping


def get_asset_full_info(db) -> dict:
    """从 MongoDB assets 集合获取 name -> doc 映射（格式A用）"""
    mapping = {}
    for doc in db[ASSETS_COL].find({}):
        doc.pop("_id", None)
        mapping[doc["name"]] = doc
    return mapping


def fuzzy_match(col_name: str, name_to_info: dict) -> tuple:
    """模糊匹配资产名称，返回 (matched_name, info_doc) 或 (None, None)"""
    if col_name in name_to_info:
        return col_name, name_to_info[col_name]
    col_stripped = col_name.strip()
    for sys_name, info in name_to_info.items():
        if col_stripped in sys_name or sys_name in col_stripped:
            return sys_name, info
    return None, None


def main():
    # 1. 读取文件，检测格式
    if not INPUT_FILE.exists():
        print(f"错误：找不到输入文件 {INPUT_FILE}")
        sys.exit(1)

    print(f"读取输入文件: {INPUT_FILE}")
    wb = openpyxl.load_workbook(INPUT_FILE, data_only=True)
    ws = wb.active
    fmt = detect_format(ws)
    print(f"  检测到文件格式: {'B (第1行名称+第2行代码)' if fmt == 'B' else 'A (标准日期索引格式)'}")

    # 2. 连接 MongoDB
    print(f"\n连接 MongoDB: {MONGO_URI}/{DB_NAME}")
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
        db = client[DB_NAME]
        print("  连接成功 ✓")
    except Exception as e:
        print(f"  连接失败: {e}")
        sys.exit(1)

    # 3. 按格式处理
    if fmt == "B":
        # ── 格式B：代码直接从文件读取 ──
        names, codes, rows = load_format_b(ws)
        code_to_info = get_code_to_info(db)
        print(f"  资产数: {len(codes)}, 数据行: {len(rows)}")

        matched = []  # [(name, code, info_or_None)]
        for name, code in zip(names, codes):
            info = code_to_info.get(code)
            if info:
                print(f"  代码匹配: {code} ({name})")
            else:
                print(f"  系统中无此代码: {code} ({name})，将使用文件中的名称")
                info = {"code": code, "name": name, "asset_type": "指数",
                        "exchange": None, "description": None}
            matched.append((name, code, info))

        codes_list = [code for _, code, _ in matched]

        # 生成 assets.json
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        assets_list = []
        for name, code, info in matched:
            assets_list.append({
                "code": info["code"],
                "name": info["name"],
                "asset_type": info.get("asset_type", "指数"),
                "exchange": info.get("exchange"),
                "description": info.get("description"),
                "is_active": True,
                "created_at": {"$date": now_iso},
                "updated_at": {"$date": now_iso},
            })

        # 生成 asset_prices.json
        prices_list = []
        for date_val, vals in rows:
            if isinstance(date_val, datetime):
                date_str = date_val.strftime("%Y-%m-%d")
            else:
                date_str = str(date_val).strip()[:10]
            for i, (name, code, info) in enumerate(matched):
                val = vals[i]
                if val is None:
                    continue
                prices_list.append({
                    "asset_code": code,
                    "date": date_str,
                    "open": None, "high": None, "low": None,
                    "close": round(float(val), 6),
                    "volume": None, "amount": None, "scale": None,
                })

    else:
        # ── 格式A：从 MongoDB 匹配名称 ──
        df = pd.read_excel(INPUT_FILE, sheet_name="Sheet1", index_col=0)
        df.index = pd.to_datetime(df.index)
        dup_count = df.index.duplicated().sum()
        if dup_count > 0:
            print(f"  发现 {dup_count} 行重复日期，已去重（保留最后一条）")
            df = df[~df.index.duplicated(keep='last')]
        print(f"  列数（资产）: {len(df.columns)}, 行数（日期）: {len(df)}")

        name_to_info = get_asset_full_info(db)
        matched_a = []
        for col_name in df.columns:
            sys_name, info = fuzzy_match(col_name, name_to_info)
            if info:
                matched_a.append((col_name, info))
                if sys_name != col_name:
                    print(f"  模糊匹配: '{col_name}' -> '{sys_name}' ({info['code']})")
                else:
                    print(f"  精确匹配: '{col_name}' -> {info['code']}")
            else:
                print(f"  未匹配: '{col_name}'")

        codes_list = [info["code"] for _, info in matched_a]
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        assets_list = []
        for _, info in matched_a:
            assets_list.append({
                "code": info["code"], "name": info["name"],
                "asset_type": info.get("asset_type", "指数"),
                "exchange": info.get("exchange"),
                "description": info.get("description"),
                "is_active": True,
                "created_at": {"$date": now_iso},
                "updated_at": {"$date": now_iso},
            })
        prices_list = []
        for col_name, info in matched_a:
            code = info["code"]
            for date_val, close_val in df[col_name].dropna().items():
                prices_list.append({
                    "asset_code": code,
                    "date": date_val.strftime("%Y-%m-%d"),
                    "open": None, "high": None, "low": None,
                    "close": round(float(close_val), 6),
                    "volume": None, "amount": None, "scale": None,
                })
        codes = codes_list  # alias for stats print

    # 4. 保存 JSON
    with open(OUTPUT_ASSETS, "w", encoding="utf-8") as f:
        json.dump(assets_list, f, ensure_ascii=False, indent=2)
    print(f"\n✓ {OUTPUT_ASSETS.name} ({len(assets_list)} 条)")

    total_records = len(prices_list)
    with open(OUTPUT_PRICES, "w", encoding="utf-8") as f:
        json.dump(prices_list, f, ensure_ascii=False, indent=2)
    print(f"✓ {OUTPUT_PRICES.name} ({total_records} 条)")

    client.close()

    # 5. 输出导入命令
    codes_js = json.dumps(codes_list)
    print(f"\n{'='*60}")
    print(f"导入命令（先删后导）:")
    print(f"{'='*60}")
    print(f"\n── Step 1: 删除这批资产的旧数据 ──")
    print(f'mongosh "mongodb://localhost:27017/{DB_NAME}" --eval "')
    print(f"var codes = {codes_js};")
    print(f"var r1 = db.assets.deleteMany({{code: {{\\$in: codes}}}});")
    print(f"print('assets 删除: ' + r1.deletedCount + ' 条');")
    print(f"var r2 = db.asset_prices.deleteMany({{asset_code: {{\\$in: codes}}}});")
    print(f"print('asset_prices 删除: ' + r2.deletedCount + ' 条');")
    print(f'"')

    print(f"\n── Step 2: 导入 assets ──")
    print(f'mongoimport --uri "mongodb://localhost:27017/{DB_NAME}" --collection assets --file "{OUTPUT_ASSETS}" --jsonArray')

    print(f"\n── Step 3: 导入 asset_prices ──")
    print(f'mongoimport --uri "mongodb://localhost:27017/{DB_NAME}" --collection asset_prices --file "{OUTPUT_PRICES}" --jsonArray')

    print(f"\n── 或一键执行（PowerShell）──")
    print(f'mongosh "mongodb://localhost:27017/{DB_NAME}" --eval "var codes={codes_js}; db.assets.deleteMany({{code:{{\\$in:codes}}}}); db.asset_prices.deleteMany({{asset_code:{{\\$in:codes}}}});"')
    print(f'mongoimport --uri "mongodb://localhost:27017/{DB_NAME}" --collection assets --file "{OUTPUT_ASSETS}" --jsonArray')
    print(f'mongoimport --uri "mongodb://localhost:27017/{DB_NAME}" --collection asset_prices --file "{OUTPUT_PRICES}" --jsonArray')

    # 统计
    print(f"\n{'─'*60}")
    print(f"资产统计:")
    print(f"  资产数: {len(assets_list)}")
    print(f"  行情数据总条数: {total_records}")
    print(f"  资产代码: {codes_list}")


if __name__ == "__main__":
    main()

