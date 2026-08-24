# -*- coding: utf-8 -*-
"""
收益凭证估值模块 —— 种子数据构建脚本

构建完整的测试数据集，包括：
1. option_products: 12 只覆盖全类型的产品
2. option_market_data: 5 个交易日市场数据
3. option_vol_surfaces: 沪深300波动率曲面
4. asset_prices: 确保标的行情存在（供桥接测试）

用法：
    py scripts/seed_option_valuation.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pymongo import MongoClient
from pymongo.operations import UpdateOne
from datetime import datetime, timedelta
import math

# ── 连接 ──────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# 集合引用
products_col = db["option_products"]
market_col = db["option_market_data"]
vol_surface_col = db["option_vol_surfaces"]
valuations_col = db["option_valuations"]
history_col = db["option_valuation_history"]
events_col = db["option_lifecycle_events"]
risk_col = db["option_risk_reports"]
accounting_col = db["option_accounting_entries"]
accounting_config_col = db["option_accounting_config"]
asset_prices_col = db["asset_prices"]

# ── 日期工具 ──────────────────────────────────────────
today = datetime.now().date()
TODAY_STR = today.isoformat()
# 往前推 5 个交易日（跳过周末）
def trading_dates_before(ref_date, n):
    dates = []
    d = ref_date - timedelta(days=1)
    while len(dates) < n:
        if d.weekday() < 5:  # 周一到周五
            dates.append(d)
        d -= timedelta(days=1)
    return list(reversed(dates))

prev_5_days = trading_dates_before(today, 5)
YESTERDAY_STR = prev_5_days[-1].isoformat()

print(f"=== 收益凭证估值种子数据 ===")
print(f"今日: {TODAY_STR}, 昨日: {YESTERDAY_STR}")
print()

# ══════════════════════════════════════════════════════
#  1. 清理旧数据（仅清理收益凭证相关集合）
# ══════════════════════════════════════════════════════
collections_to_clear = [
    products_col, market_col, vol_surface_col,
    valuations_col, history_col, events_col, risk_col,
    accounting_col, accounting_config_col,
]
for col in collections_to_clear:
    col.drop()
    print(f"  已清理: {col.name}")

# ══════════════════════════════════════════════════════
#  2. 产品数据（12只，覆盖全部13种类型中的12种常用类型）
# ══════════════════════════════════════════════════════
# 标的选择：使用系统中已有的资产代码
# SH000300 = 沪深300 (有数据), SH000016 = 上证50, SZ399006 = 创业板指

now = datetime.now()

products = [
    # ── 雪球 ×2 ──
    {
        "product_id": "SNOW_001",
        "name": "挂钩沪深300雪球A",
        "type": "snowball",
        "issuer": "中信证券",
        "issue_date": "2025-06-15",
        "maturity_date": "2027-06-15",
        "principal": 10000000,
        "underlying": "SH000300",
        "status": "active",
        "params": {
            "spot_ref": 3850.0,
            "knock_out": 1.03,
            "knock_in": 0.75,
            "coupon_year": 0.18,
            "obs_freq": "monthly",
            "recovery_coupon_rate": 0.0,
            "use_control_variate": True,
        },
    },
    {
        "product_id": "SNOW_002",
        "name": "挂钩中证500雪球B",
        "type": "snowball",
        "issuer": "中金公司",
        "issue_date": "2025-09-01",
        "maturity_date": "2027-09-01",
        "principal": 5000000,
        "underlying": "SH000905",
        "status": "active",
        "params": {
            "spot_ref": 5200.0,
            "knock_out": 1.05,
            "knock_in": 0.70,
            "coupon_year": 0.20,
            "obs_freq": "monthly",
            "recovery_coupon_rate": 0.02,
            "use_control_variate": True,
        },
    },
    # ── 凤凰 ×1 ──
    {
        "product_id": "PHX_001",
        "name": "挂钩上证50凤凰",
        "type": "phoenix",
        "issuer": "国泰君安",
        "issue_date": "2025-08-01",
        "maturity_date": "2027-08-01",
        "principal": 8000000,
        "underlying": "SH000016",
        "status": "active",
        "params": {
            "spot_ref": 2650.0,
            "knock_out": 1.03,
            "knock_in": 0.80,
            "coupon_per_period": 0.015,
            "obs_freq": "monthly",
            "memory_flag": True,
            "use_control_variate": True,
        },
    },
    # ── 鲨鱼鳍 ×1 ──
    {
        "product_id": "SHARK_001",
        "name": "挂钩沪深300鲨鱼鳍",
        "type": "sharkfin",
        "issuer": "华泰证券",
        "issue_date": "2025-12-01",
        "maturity_date": "2026-12-01",
        "principal": 3000000,
        "underlying": "SH000300",
        "status": "active",
        "params": {
            "spot_ref": 3850.0,
            "obs_freq": "daily",
            "knock_out_ratio": 1.10,
            "participation": 0.80,
            "guaranteed": 1.0,
            "strike": 3850.0,
        },
    },
    # ── 双鲨 ×1 ──
    {
        "product_id": "DBL_001",
        "name": "挂钩创业板指双鲨",
        "type": "double_barrier",
        "issuer": "招商证券",
        "issue_date": "2025-10-15",
        "maturity_date": "2026-10-15",
        "principal": 5000000,
        "underlying": "SZ399006",
        "status": "active",
        "params": {
            "spot_ref": 2100.0,
            "obs_freq": "daily",
            "barrier_low": 0.85,
            "barrier_high": 1.15,
            "guaranteed": 1.0,
            "participation": 1.0,
            "strike": 2100.0,
        },
    },
    # ── 二元 ×1 ──
    {
        "product_id": "BIN_001",
        "name": "挂钩沪深300二元看涨",
        "type": "binary",
        "issuer": "光大证券",
        "issue_date": "2026-01-15",
        "maturity_date": "2026-07-15",
        "principal": 2000000,
        "underlying": "SH000300",
        "status": "active",
        "params": {
            "strike": 3900.0,
            "high_return": 0.05,
            "low_return": 0.005,
        },
    },
    # ── 价差 ×1 ──
    {
        "product_id": "SPD_001",
        "name": "挂钩上证50看涨价差",
        "type": "spread",
        "issuer": "海通证券",
        "issue_date": "2026-02-01",
        "maturity_date": "2026-08-01",
        "principal": 3000000,
        "underlying": "SH000016",
        "status": "active",
        "params": {
            "strike_low": 2600.0,
            "strike_high": 2800.0,
            "direction": "bull",
        },
    },
    # ── 固定收益 ×1 ──
    {
        "product_id": "FIX_001",
        "name": "固定收益凭证A",
        "type": "fixed",
        "issuer": "中信建投",
        "issue_date": "2026-01-01",
        "maturity_date": "2027-01-01",
        "principal": 10000000,
        "underlying": "SH000300",
        "status": "active",
        "params": {
            "coupon_rate": 0.035,
        },
    },
    # ── 亚式 ×1 ──
    {
        "product_id": "ASN_001",
        "name": "挂钩沪深300亚式看涨",
        "type": "asian",
        "issuer": "申万宏源",
        "issue_date": "2026-03-01",
        "maturity_date": "2026-09-01",
        "principal": 4000000,
        "underlying": "SH000300",
        "status": "active",
        "params": {
            "spot_ref": 3850.0,
            "strike": 3850.0,
            "obs_freq": "daily",
            "avg_type": "arithmetic",
        },
    },
    # ── 区间累积 ×1 ──
    {
        "product_id": "RNG_001",
        "name": "挂钩沪深300区间累积",
        "type": "range_accrual",
        "issuer": "兴业证券",
        "issue_date": "2026-01-15",
        "maturity_date": "2027-01-15",
        "principal": 6000000,
        "underlying": "SH000300",
        "status": "active",
        "params": {
            "spot_ref": 3850.0,
            "lower_barrier": 3500.0,
            "upper_barrier": 4200.0,
            "coupon_rate": 0.06,
            "obs_freq": "daily",
        },
    },
    # ── 可赎回固收 ×1 ──
    {
        "product_id": "CAL_001",
        "name": "可赎回固收凭证B",
        "type": "callable_fixed",
        "issuer": "平安证券",
        "issue_date": "2025-07-01",
        "maturity_date": "2027-07-01",
        "principal": 8000000,
        "underlying": "SH000300",
        "status": "active",
        "params": {
            "coupon_rate": 0.045,
            "call_date": 1.0,
            "call_price": 8000000,
            "rate_vol": 0.01,
        },
    },
    # ── 数字区间 ×1 ──
    {
        "product_id": "DIG_001",
        "name": "挂钩沪深300数字区间",
        "type": "digital_range",
        "issuer": "长江证券",
        "issue_date": "2026-02-15",
        "maturity_date": "2026-08-15",
        "principal": 2000000,
        "underlying": "SH000300",
        "status": "active",
        "params": {
            "lower": 3600.0,
            "upper": 4100.0,
            "payoff": 200000.0,
        },
    },
]

# 批量写入
for p in products:
    p["created_at"] = now
    p["updated_at"] = now
result = products_col.insert_many(products)
print(f"\n[1/5] option_products: 写入 {len(products)} 只产品")
for p in products:
    print(f"  {p['product_id']:12s} | {p['type']:16s} | {p['name']}")

# ══════════════════════════════════════════════════════
#  3. 市场数据（option_market_data：5个交易日 × 4个标的）
# ══════════════════════════════════════════════════════
underlyings_config = {
    "SH000300": {"spot_base": 3850.0, "vol_base": 0.18, "div_yield": 0.02},
    "SH000016": {"spot_base": 2650.0, "vol_base": 0.16, "div_yield": 0.025},
    "SH000905": {"spot_base": 5200.0, "vol_base": 0.22, "div_yield": 0.015},
    "SZ399006": {"spot_base": 2100.0, "vol_base": 0.25, "div_yield": 0.01},
}

market_docs = []
all_dates = prev_5_days + [today]  # 6天数据

for i, d in enumerate(all_dates):
    ds = d.isoformat()
    for code, cfg in underlyings_config.items():
        # 模拟价格波动：基于正弦波+随机偏移
        phase = i * 0.3 + hash(code) % 10 * 0.1
        spot = cfg["spot_base"] * (1 + 0.02 * math.sin(phase) + 0.005 * (i - 2.5))
        spot = round(spot, 2)
        vol = cfg["vol_base"] * (1 + 0.05 * math.cos(phase))

        market_docs.append({
            "date": ds,
            "underlying": code,
            "spot": spot,
            "dividend_yield": cfg["div_yield"],
            "vol_1m":  round(vol * 1.10, 4),
            "vol_3m":  round(vol * 1.00, 4),
            "vol_6m":  round(vol * 0.95, 4),
            "vol_12m": round(vol * 0.90, 4),
            "rate_1m":  0.018,
            "rate_3m":  0.019,
            "rate_6m":  0.020,
            "rate_1y":  0.022,
            "rate_2y":  0.025,
            "rate_5y":  0.028,
            "created_at": now,
        })

if market_docs:
    market_col.insert_many(market_docs)
print(f"\n[2/5] option_market_data: 写入 {len(market_docs)} 条 ({len(all_dates)} 天 × {len(underlyings_config)} 标的)")

# ══════════════════════════════════════════════════════
#  4. 确保 asset_prices 中有对应标的行情（供桥接测试）
# ══════════════════════════════════════════════════════
bridge_count = 0
for code in underlyings_config:
    existing = asset_prices_col.count_documents({"asset_code": code})
    if existing == 0:
        # 写入 30 天模拟行情
        docs = []
        for i in range(30):
            d = today - timedelta(days=i)
            cfg = underlyings_config[code]
            phase = i * 0.2
            spot = cfg["spot_base"] * (1 + 0.015 * math.sin(phase))
            docs.append({
                "date": d.isoformat(),
                "asset_code": code,
                "close": round(spot, 2),
                "open": round(spot * 0.998, 2),
                "high": round(spot * 1.01, 2),
                "low": round(spot * 0.99, 2),
                "volume": 100000000,
                "amount": 5000000000,
                "scale": None,
            })
        asset_prices_col.insert_many(docs)
        bridge_count += len(docs)
        print(f"  asset_prices 补充 {code}: {len(docs)} 条")

print(f"\n[3/5] asset_prices 桥接数据: 补充 {bridge_count} 条（已有 {asset_prices_col.count_documents({})} 条）")

# ══════════════════════════════════════════════════════
#  5. 波动率曲面（沪深300 + 上证50）
# ══════════════════════════════════════════════════════
moneyness = [0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20]
tenors = [0.083, 0.25, 0.5, 1.0, 2.0]  # 1M, 3M, 6M, 12M, 24M

def build_vol_grid(base_vol, skew=0.03):
    """构建带 smile 的波动率曲面"""
    grid = []
    for t in tenors:
        row = []
        for m in moneyness:
            # ATM vol + skew * (moneyness - 1)^2 + term structure
            v = base_vol + skew * (m - 1.0) ** 2 + 0.01 * (1 - t)
            row.append(round(max(v, 0.05), 4))
        grid.append(row)
    return grid

surfaces = [
    {
        "underlying": "SH000300",
        "moneyness_grid": moneyness,
        "tenor_grid": tenors,
        "vol_grid": build_vol_grid(0.18, 0.04),
        "created_at": now,
        "updated_at": now,
    },
    {
        "underlying": "SH000016",
        "moneyness_grid": moneyness,
        "tenor_grid": tenors,
        "vol_grid": build_vol_grid(0.16, 0.03),
        "created_at": now,
        "updated_at": now,
    },
    {
        "underlying": "SH000905",
        "moneyness_grid": moneyness,
        "tenor_grid": tenors,
        "vol_grid": build_vol_grid(0.22, 0.05),
        "created_at": now,
        "updated_at": now,
    },
    {
        "underlying": "SZ399006",
        "moneyness_grid": moneyness,
        "tenor_grid": tenors,
        "vol_grid": build_vol_grid(0.25, 0.06),
        "created_at": now,
        "updated_at": now,
    },
]
vol_surface_col.insert_many(surfaces)
print(f"\n[4/5] option_vol_surfaces: 写入 {len(surfaces)} 个曲面")
for s in surfaces:
    print(f"  {s['underlying']}: {len(moneyness)}×{len(tenors)} 网格")

# ══════════════════════════════════════════════════════
#  6. 会计科目配置（默认值）
# ══════════════════════════════════════════════════════
accounting_config_col.insert_one({
    "_type": "account_map",
    "account_map": {
        "fair_value_asset": "交易性金融资产-成本",
        "accumulated_fair_value": "交易性金融资产-公允价值变动",
        "fair_value_pnl": "公允价值变动损益",
        "coupon_income": "投资收益-利息收入",
        "settlement": "银行存款",
        "receivable_coupon": "应收利息",
    },
    "updated_at": now,
})
print(f"\n[5/5] option_accounting_config: 写入默认科目映射")

# ══════════════════════════════════════════════════════
#  汇总
# ══════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("种子数据构建完成！")
print(f"  option_products:          {products_col.count_documents({})} 只")
print(f"  option_market_data:       {market_col.count_documents({})} 条")
print(f"  option_vol_surfaces:      {vol_surface_col.count_documents({})} 个")
print(f"  option_accounting_config: {accounting_config_col.count_documents({})} 套")
print(f"  asset_prices (总):        {asset_prices_col.count_documents({})} 条")
print()
print("接下来可以：")
print("  1. 启动后端: py main.py")
print("  2. 启动前端: cd portfilio && npm run dev")
print("  3. 打开 http://localhost:8080/#/options/workbench")
print("  4. 选择今日日期 → 点击「运行估值」")
print("=" * 60)

client.close()
