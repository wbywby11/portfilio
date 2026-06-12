"""
从 '大类资产底层数据上传版本(1).xlsx' 生成可直接导入 MongoDB 的 JSON 文件:
  - assets.json          → 导入到 assets 集合
  - asset_prices.json    → 导入到 asset_prices 集合

用法:
  python scripts/generate_import_json.py

导入 MongoDB:
  mongoimport --db portfolio --collection assets --file assets.json --jsonArray
  mongoimport --db portfolio --collection asset_prices --file asset_prices.json --jsonArray
"""

import json
import openpyxl
from datetime import datetime

EXCEL_PATH = r"C:\Users\wangb\xwechat_files\wxid_l7trc60uwzre22_b8b1\msg\file\2026-05\大类资产底层数据上传版本(1).xlsx"
OUTPUT_DIR = r"d:\portfilio\scripts"

# ── 资产元数据映射 ──────────────────────────────────────────────
# code → (name, asset_type, exchange, description)
ASSET_META = {
    "CBA00101.CS": ("中债-新综合财富(总值)指数", "指数", "中证指数",  "中债综合财富指数，反映债券市场整体表现"),
    "000300.SH":   ("沪深300",                "指数", "上交所",    "沪深300指数，A股核心宽基指数"),
    "CCFI.WI":     ("Wind商品综合",            "指数", "Wind",     "Wind商品综合指数，大宗商品综合表现"),
    "NMFI.WI":     ("Wind贵金属",              "指数", "Wind",     "Wind贵金属指数"),
    "NFFI.WI":     ("Wind有色",                "指数", "Wind",     "Wind有色金属指数"),
    "CIFI.WI":     ("Wind化工",                "指数", "Wind",     "Wind化工指数"),
    "JJRI.WI":     ("Wind煤焦钢矿",            "指数", "Wind",     "Wind煤焦钢矿指数"),
    "OOFI.WI":     ("Wind油脂油料",            "指数", "Wind",     "Wind油脂油料指数"),
    "SOFI.WI":     ("Wind软商品",              "指数", "Wind",     "Wind软商品指数"),
    "ENFI.WI":     ("Wind能源",                "指数", "Wind",     "Wind能源指数"),
    "APFI.WI":     ("Wind农副产品",            "指数", "Wind",     "Wind农副产品指数"),
    "NMBM.WI":     ("Wind非金属建材",          "指数", "Wind",     "Wind非金属建材指数"),
    "CRFI.WI":     ("Wind谷物",                "指数", "Wind",     "Wind谷物指数"),
    "518880.SH":   ("黄金ETF华安",             "基金", "上交所",    "华安黄金ETF，跟踪黄金现货价格"),
    "159980.SZ":   ("有色ETF大成",             "基金", "深交所",    "大成有色金属ETF"),
    "159981.SZ":   ("能源化工ETF建信",          "基金", "深交所",    "建信能源化工ETF"),
    "159985.SZ":   ("豆粕ETF华夏",             "基金", "深交所",    "华夏豆粕ETF"),
    "501018.SH":   ("南方原油LOF",             "基金", "上交所",    "南方原油LOF，QDII跟踪原油期货"),
    "160216.SZ":   ("国泰商品LOF",             "基金", "深交所",    "国泰大宗商品LOF"),
    "164701.SZ":   ("黄金LOF",                 "基金", "深交所",    "前海开源黄金LOF"),
    "161226.SZ":   ("国投白银LOF",             "基金", "深交所",    "国投瑞银白银LOF"),
    "DR007.IB":    ("银存间质押7日",            "指数", "银行间",    "银行间7天质押回购利率DR007"),
}


def load_excel(path):
    """读取 Excel，返回 (codes, names, rows)"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Sheet1"]

    max_col = ws.max_column
    max_row = ws.max_row

    # 第1行: 中文名; 第2行: 代码
    names = [ws.cell(1, c).value for c in range(2, max_col + 1)]
    codes = [ws.cell(2, c).value for c in range(2, max_col + 1)]

    # 第3行起: 数据
    rows = []
    for r in range(3, max_row + 1):
        date_val = ws.cell(r, 1).value
        if date_val is None:
            continue
        values = [ws.cell(r, c).value for c in range(2, max_col + 1)]
        rows.append((date_val, values))

    return codes, names, rows


def build_assets(codes, names):
    """构建 assets 集合文档列表"""
    # 使用 MongoDB Extended JSON $date 格式，mongoimport 会自动转为 ISODate
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assets = []
    for code, cn_name in zip(codes, names):
        meta = ASSET_META.get(code)
        if meta:
            name, asset_type, exchange, description = meta
        else:
            name = cn_name or code
            asset_type = "指数"
            exchange = None
            description = None

        doc = {
            "code": code,
            "name": name,
            "asset_type": asset_type,
            "exchange": exchange,
            "description": description,
            "is_active": True,
            "created_at": {"$date": now_iso},
            "updated_at": {"$date": now_iso},
        }
        assets.append(doc)
    return assets


def build_prices(codes, rows):
    """构建 asset_prices 集合文档列表（完整 OHLCVA 格式）"""
    prices = []
    for date_val, values in rows:
        # 日期格式化
        if isinstance(date_val, datetime):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val).strip()

        for i, code in enumerate(codes):
            val = values[i]
            if val is None:
                continue

            close_val = round(float(val), 6)
            doc = {
                "asset_code": code,
                "date": date_str,
                "open": None,
                "high": None,
                "low": None,
                "close": close_val,
                "volume": None,
                "amount": None,
            }
            prices.append(doc)
    return prices


def main():
    print(f"读取 Excel: {EXCEL_PATH}")
    codes, names, rows = load_excel(EXCEL_PATH)
    print(f"  资产数: {len(codes)}")
    print(f"  日期行: {len(rows)}")

    # ── 生成 assets.json ──
    assets = build_assets(codes, names)
    assets_path = f"{OUTPUT_DIR}/assets.json"
    with open(assets_path, "w", encoding="utf-8") as f:
        json.dump(assets, f, ensure_ascii=False, indent=2)
    print(f"  ✓ assets.json ({len(assets)} 条)")

    # ── 生成 asset_prices.json ──
    prices = build_prices(codes, rows)
    prices_path = f"{OUTPUT_DIR}/asset_prices.json"
    with open(prices_path, "w", encoding="utf-8") as f:
        json.dump(prices, f, ensure_ascii=False, indent=2)
    print(f"  ✓ asset_prices.json ({len(prices)} 条)")

    # ── 打印导入命令 ──
    print("\n导入 MongoDB 命令:")
    print(f'  mongoimport --db portfolio --collection assets --file "{assets_path}" --jsonArray --drop')
    print(f'  mongoimport --db portfolio --collection asset_prices --file "{prices_path}" --jsonArray --drop')


if __name__ == "__main__":
    main()
