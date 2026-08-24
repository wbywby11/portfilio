# -*- coding: utf-8 -*-
"""
收益凭证估值 — 种子数据生成脚本

为 MongoDB 中的 option_* 集合生成真实样例数据，覆盖：
  1. option_products (8 个产品，覆盖 7 种产品类型)
  2. option_market_data (4 个标的 × 14 天历史，让 vol/利率插值可用)
  3. option_vol_surfaces (4 个标的的波动率曲面)

跑通 valuation 的最小数据集（估值日 = 今日）。

用法：
  & "d:\\portfilio-end\\venv\\Scripts\\python.exe" d:\\portfilio-end\\scripts\\seed_options_data.py
"""
import os
import sys
from datetime import date, timedelta, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGODB_DB", "asset_allocation")
TODAY = date.today()


# ═══════════════════════════════════════════════════════════════════
#  4 个标的物 — 主流宽基股指（spot 取近期合理水平）
# ═══════════════════════════════════════════════════════════════════
UNDERLYINGS = {
    "000300.SH": {"name": "沪深300", "spot": 3850.0, "vol_base": 0.18, "div": 0.022},
    "000905.SH": {"name": "中证500", "spot": 5650.0, "vol_base": 0.22, "div": 0.018},
    "000852.SH": {"name": "中证1000", "spot": 6300.0, "vol_base": 0.25, "div": 0.015},
    "588000.SH": {"name": "科创50",   "spot": 920.0,  "vol_base": 0.30, "div": 0.005},
}


# ═══════════════════════════════════════════════════════════════════
#  8 个产品 — 覆盖全部 7 种类型（fixed 配 2 个）
# ═══════════════════════════════════════════════════════════════════
def _date_str(d): return d.isoformat()


def build_products():
    """产品定义。所有产品 issue_date 在 30~180 天前，maturity_date 在 0.5~2 年后"""
    products = [
        # ── 1. 固定收益 ───────────────────────────────
        {
            "product_id": "FIX_001",
            "name": "中信稳盈1年期固收",
            "type": "fixed",
            "issuer": "中信证券",
            "issue_date": _date_str(TODAY - timedelta(days=60)),
            "maturity_date": _date_str(TODAY + timedelta(days=305)),  # ~1Y
            "principal": 1_000_000.0,
            "underlying": "000300.SH",
            "status": "active",
            "params": {"coupon_rate": 0.040},
        },
        {
            "product_id": "FIX_002",
            "name": "国君安稳2年期固收",
            "type": "fixed",
            "issuer": "国泰君安",
            "issue_date": _date_str(TODAY - timedelta(days=30)),
            "maturity_date": _date_str(TODAY + timedelta(days=700)),  # ~2Y
            "principal": 5_000_000.0,
            "underlying": "588000.SH",
            "status": "active",
            "params": {"coupon_rate": 0.0485},
        },
        # ── 2. 二元结构 ───────────────────────────────
        {
            "product_id": "BIN_001",
            "name": "招商二元看涨6M",
            "type": "binary",
            "issuer": "招商证券",
            "issue_date": _date_str(TODAY - timedelta(days=45)),
            "maturity_date": _date_str(TODAY + timedelta(days=137)),  # ~6M
            "principal": 2_000_000.0,
            "underlying": "000300.SH",
            "status": "active",
            "params": {
                "strike": 3900.0,         # 行权价（接近 ATM 偏价外）
                "high_return": 0.06,      # 触发后年化 6%
                "low_return": 0.005,      # 未触发年化 0.5%
            },
        },
        # ── 3. 价差结构（牛市价差）─────────────────────
        {
            "product_id": "SPR_001",
            "name": "中信牛市价差1Y",
            "type": "spread",
            "issuer": "中信证券",
            "issue_date": _date_str(TODAY - timedelta(days=20)),
            "maturity_date": _date_str(TODAY + timedelta(days=345)),  # ~1Y
            "principal": 3_000_000.0,
            "underlying": "000905.SH",
            "status": "active",
            "params": {
                "strike_low": 5500.0,
                "strike_high": 6000.0,
                "direction": "bull",
            },
        },
        # ── 4. 鲨鱼鳍 ─────────────────────────────────
        {
            "product_id": "SHARK_001",
            "name": "海通向上鲨鱼鳍6M",
            "type": "sharkfin",
            "issuer": "海通证券",
            "issue_date": _date_str(TODAY - timedelta(days=30)),
            "maturity_date": _date_str(TODAY + timedelta(days=152)),  # ~6M
            "principal": 2_000_000.0,
            "underlying": "000300.SH",
            "status": "active",
            "params": {
                "spot_ref": 3800.0,
                "strike": 3800.0,
                "knock_out_ratio": 1.10,   # 110% 敲出
                "participation": 0.75,
                "guaranteed": 1.0,         # 100% 保本
            },
        },
        # ── 5. 雪球 ───────────────────────────────────
        {
            "product_id": "SNOW_001",
            "name": "广发经典雪球24M",
            "type": "snowball",
            "issuer": "广发证券",
            "issue_date": _date_str(TODAY - timedelta(days=90)),
            "maturity_date": _date_str(TODAY + timedelta(days=640)),  # ~24M
            "principal": 1_000_000.0,
            "underlying": "000905.SH",
            "status": "active",
            "params": {
                "spot_ref": 5500.0,
                "knock_out": 1.03,         # 103% 敲出
                "knock_in": 0.78,          # 78% 敲入
                "coupon_year": 0.18,       # 年化票息 18%
                "obs_freq": "monthly",
                "recovery_coupon_rate": 0.0,
                "use_control_variate": True,
            },
        },
        # ── 6. 凤凰 ───────────────────────────────────
        {
            "product_id": "PHX_001",
            "name": "中金记忆凤凰24M",
            "type": "phoenix",
            "issuer": "中金公司",
            "issue_date": _date_str(TODAY - timedelta(days=60)),
            "maturity_date": _date_str(TODAY + timedelta(days=670)),  # ~24M
            "principal": 1_500_000.0,
            "underlying": "000852.SH",
            "status": "active",
            "params": {
                "spot_ref": 6200.0,
                "knock_out": 1.03,
                "knock_in": 0.78,
                "coupon_per_period": 0.012,  # 每期 1.2%
                "obs_freq": "monthly",
                "memory_flag": True,
                "use_control_variate": True,
            },
        },
        # ── 7. 双鲨（双边敲出） ───────────────────────
        {
            "product_id": "DBL_001",
            "name": "国信双鲨结构1Y",
            "type": "double_barrier",
            "issuer": "国信证券",
            "issue_date": _date_str(TODAY - timedelta(days=15)),
            "maturity_date": _date_str(TODAY + timedelta(days=350)),  # ~1Y
            "principal": 2_500_000.0,
            "underlying": "000300.SH",
            "status": "active",
            "params": {
                "spot_ref": 3800.0,
                "strike": 3800.0,
                "barrier_low": 0.85,       # 下界 85%
                "barrier_high": 1.15,      # 上界 115%
                "guaranteed": 0.98,        # 98% 保本
                "participation": 0.6,
            },
        },
    ]
    return products


# ═══════════════════════════════════════════════════════════════════
#  市场数据 — 14 天历史 × 4 个标的（让 valuation_history 有走势）
# ═══════════════════════════════════════════════════════════════════
def build_market_data():
    """生成最近 14 天的市场数据（含今日）"""
    import random
    random.seed(42)

    records = []
    for code, info in UNDERLYINGS.items():
        spot_base = info["spot"]
        vol_base = info["vol_base"]
        div = info["div"]

        # 14 天历史 + 今日
        for offset in range(-13, 1):
            d = TODAY + timedelta(days=offset)
            # 价格小幅扰动（±2%），让历史曲线有自然波动
            jitter = 1 + random.gauss(0, 0.008)
            spot = round(spot_base * jitter, 2)

            records.append({
                "date": _date_str(d),
                "underlying": code,
                "spot": spot,
                "dividend_yield": div,
                # 期限结构：短期略高、长期略低（vol term structure）
                "vol_1m":  round(vol_base + 0.025, 4),
                "vol_3m":  round(vol_base + 0.015, 4),
                "vol_6m":  round(vol_base, 4),
                "vol_12m": round(vol_base - 0.010, 4),
                # 利率曲线（陡峭向上）
                "rate_1m": 0.0180,
                "rate_3m": 0.0195,
                "rate_6m": 0.0210,
                "rate_1y": 0.0235,
                "rate_2y": 0.0260,
                "rate_5y": 0.0285,
            })
    return records


# ═══════════════════════════════════════════════════════════════════
#  波动率曲面 — 4 个标的，反映 ATM 微笑
# ═══════════════════════════════════════════════════════════════════
def build_vol_surfaces():
    """生成波动率曲面：moneyness × tenor 网格"""
    surfaces = []
    moneyness = [0.80, 0.90, 0.95, 1.00, 1.05, 1.10, 1.20]
    tenors = [1/12, 3/12, 6/12, 1.0, 2.0]

    for code, info in UNDERLYINGS.items():
        v0 = info["vol_base"]
        # 简单的 vol smile + term structure
        # ATM 取 v0；远 OTM/ITM 上浮 +3~5%
        # 短期波动率比长期高 +2%
        vol_grid = []
        for t in tenors:
            term_adj = 0.025 if t < 0.2 else (0.012 if t < 0.7 else (0.0 if t < 1.5 else -0.010))
            row = []
            for m in moneyness:
                # smile: 偏离 1.0 越远，vol 越高
                smile_adj = 0.05 * (m - 1.0) ** 2 + 0.02 * abs(m - 1.0)
                v = v0 + term_adj + smile_adj
                row.append(round(v, 4))
            vol_grid.append(row)

        surfaces.append({
            "underlying": code,
            "moneyness_grid": moneyness,
            "tenor_grid": tenors,
            "vol_grid": vol_grid,
        })
    return surfaces


# ═══════════════════════════════════════════════════════════════════
#  导入 MongoDB
# ═══════════════════════════════════════════════════════════════════
def main():
    print(f"=== 收益凭证种子数据导入 ===")
    print(f"  MongoDB: {MONGO_URI}")
    print(f"  数据库:  {DB_NAME}")
    print(f"  估值日:  {TODAY.isoformat()}")
    print()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        client.server_info()
    except Exception as e:
        print(f"[错误] MongoDB 连接失败: {e}")
        sys.exit(1)
    db = client[DB_NAME]

    # ---- 产品 ----
    products = build_products()
    col_p = db["option_products"]
    upserted_p, updated_p = 0, 0
    for p in products:
        p["created_at"] = datetime.now()
        p["updated_at"] = datetime.now()
        r = col_p.update_one({"product_id": p["product_id"]}, {"$set": p}, upsert=True)
        if r.upserted_id:
            upserted_p += 1
        else:
            updated_p += 1
    print(f"[1/3] 产品定义: {len(products)} 条 (新增 {upserted_p}, 更新 {updated_p})")
    for p in products:
        print(f"        - {p['product_id']:10s} {p['type']:14s} {p['name']:18s}  underlying={p['underlying']}")

    # ---- 市场数据 ----
    market_records = build_market_data()
    col_m = db["option_market_data"]
    upserted_m, updated_m = 0, 0
    for rec in market_records:
        rec["created_at"] = datetime.now()
        r = col_m.update_one(
            {"date": rec["date"], "underlying": rec["underlying"]},
            {"$set": rec},
            upsert=True,
        )
        if r.upserted_id:
            upserted_m += 1
        else:
            updated_m += 1
    print(f"[2/3] 市场数据: {len(market_records)} 条 ({len(UNDERLYINGS)} 标的 × 14 天) (新增 {upserted_m}, 更新 {updated_m})")

    # ---- 波动率曲面 ----
    surfaces = build_vol_surfaces()
    col_v = db["option_vol_surfaces"]
    upserted_v, updated_v = 0, 0
    for s in surfaces:
        s["created_at"] = datetime.now()
        s["updated_at"] = datetime.now()
        r = col_v.update_one({"underlying": s["underlying"]}, {"$set": s}, upsert=True)
        if r.upserted_id:
            upserted_v += 1
        else:
            updated_v += 1
    print(f"[3/3] 波动率曲面: {len(surfaces)} 个标的 (新增 {upserted_v}, 更新 {updated_v})")
    for s in surfaces:
        v_atm_1y = s["vol_grid"][3][3]  # tenor=1Y, moneyness=1.0
        print(f"        - {s['underlying']:10s} {len(s['moneyness_grid'])}×{len(s['tenor_grid'])} grid, ATM-1Y vol={v_atm_1y:.4f}")

    print()
    print(f"=== 完成 ===")
    print(f"  集合统计:")
    print(f"    option_products:    {col_p.count_documents({})} 条")
    print(f"    option_market_data: {col_m.count_documents({})} 条")
    print(f"    option_vol_surfaces:{col_v.count_documents({})} 条")
    print()
    print(f"  下一步: POST /api/v1/options/valuation/run  body={{\"date\": \"{TODAY.isoformat()}\"}}")


if __name__ == "__main__":
    main()
