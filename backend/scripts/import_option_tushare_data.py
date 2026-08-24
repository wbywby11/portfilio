# -*- coding: utf-8 -*-
"""
收益凭证估值模块 —— tushare 数据全量导入

数据来源: tushare pro
目标: 为期权估值模块构建完整的数据管理体系

数据覆盖:
  1. 指数日线行情 → asset_prices (底层资产价格)
  2. SHIBOR/LPR利率 → option_market_data (利率曲线)
  3. 期权合约信息 → option_contracts (合约基本信息)
  4. 期权日线行情 → option_iv_data (隐含波动率计算)
  5. 波动率曲面 → option_vol_surfaces (从期权价格反推)
  6. 综合市场数据 → option_market_data (spot + vol + rate)

用法:
  py scripts/import_option_tushare_data.py              # 全量导入
  py scripts/import_option_tushare_data.py --days 60    # 最近60天
  py scripts/import_option_tushare_data.py --dry-run    # 仅预览不写库
"""
import sys, os, time, argparse, math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import tushare as ts
from pymongo import MongoClient, UpdateOne

# ── 配置 ──────────────────────────────────────────────
TOKEN = "286fd29627e9ce67299c961761cc79b1aad18937fc58373f87793775"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"

# 标的指数映射 (tushare代码 → 系统代码)
INDEX_MAP = {
    "000300.SH": "SH000300",   # 沪深300
    "000016.SH": "SH000016",   # 上证50
    "000905.SH": "SH000905",   # 中证500
    "399006.SZ": "SZ399006",   # 创业板指
}

# ETF代码映射 (用于期权数据)
ETF_MAP = {
    "510300.SH": "SH000300",   # 沪深300ETF → 沪深300
    "510050.SH": "SH000016",   # 上证50ETF → 上证50
}

# SHIBOR 期限映射 (tushare字段 → 系统利率字段)
SHIBOR_MAP = {
    "1m": "rate_1m",
    "3m": "rate_3m",
    "6m": "rate_6m",
    "1y": "rate_1y",
}

BATCH_SIZE = 1000


def parse_args():
    parser = argparse.ArgumentParser(description="tushare期权数据导入")
    parser.add_argument("--days", type=int, default=730, help="导入最近N天数据 (默认730=2年)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写库")
    return parser.parse_args()


def ts_to_system_code(ts_code: str) -> str:
    """tushare代码转系统代码"""
    return INDEX_MAP.get(ts_code, ts_code)


def fmt_date(d: str) -> str:
    """YYYYMMDD → YYYY-MM-DD"""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def calc_implied_vol(option_price, S, K, T, r, q, option_type="C"):
    """Newton-Raphson 计算隐含波动率"""
    from scipy.stats import norm
    if option_price <= 0 or T <= 0 or K <= 0 or S <= 0:
        return None
    intrinsic = max(S - K, 0) if option_type == "C" else max(K - S, 0)
    if option_price < intrinsic * 0.99:
        return None

    vol = 0.25  # 初始猜测
    for _ in range(50):
        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r - q + 0.5 * vol ** 2) * T) / (vol * sqrt_T)
        d2 = d1 - vol * sqrt_T

        if option_type == "C":
            price = math.exp(-r * T) * (S * math.exp((r - q) * T) * norm.cdf(d1) - K * norm.cdf(d2))
        else:
            price = math.exp(-r * T) * (K * norm.cdf(-d2) - S * math.exp((r - q) * T) * norm.cdf(-d1))

        diff = price - option_price
        if abs(diff) < 1e-6:
            return vol

        vega = S * math.exp(-q * T) * norm.pdf(d1) * sqrt_T
        if vega < 1e-10:
            break
        step = diff / vega
        step = max(-0.5, min(0.5, step))
        vol -= step
        vol = max(0.01, min(5.0, vol))
    return vol


def build_vol_surface(iv_data: List[dict], spot: float, rate: float) -> Optional[dict]:
    """从期权隐含波动率构建波动率曲面

    Args:
        iv_data: [{"moneyness": K/S, "tenor": years, "iv": implied_vol}, ...]
        spot: 标的现价
        rate: 无风险利率

    Returns:
        {"moneyness_grid": [...], "tenor_grid": [...], "vol_grid": [[...], ...]}
    """
    if not iv_data:
        return None

    # 定义网格
    moneyness_grid = [0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20]
    tenor_grid = [1/12, 2/12, 3/12, 6/12, 1.0]  # 1M, 2M, 3M, 6M, 12M

    # 按 tenor 分桶
    buckets = {}
    for item in iv_data:
        tenor = item["tenor"]
        mn = item["moneyness"]
        iv = item["iv"]
        if iv is None or iv < 0.01 or iv > 3.0:
            continue
        # 找最近的 tenor
        best_t = min(tenor_grid, key=lambda t: abs(t - tenor))
        if abs(best_t - tenor) > 0.1:  # 太远就跳过
            continue
        if best_t not in buckets:
            buckets[best_t] = []
        buckets[best_t].append((mn, iv))

    if len(buckets) < 2:
        return None

    vol_grid = []
    used_tenors = []
    for t in tenor_grid:
        if t not in buckets or not buckets[t]:
            continue
        used_tenors.append(t)
        points = buckets[t]
        row = []
        for m in moneyness_grid:
            # 找最近的 moneyness 点
            best = min(points, key=lambda p: abs(p[0] - m))
            if abs(best[0] - m) < 0.08:
                row.append(round(best[1], 4))
            else:
                # 线性外推
                sorted_pts = sorted(points, key=lambda p: p[0])
                if m <= sorted_pts[0][0]:
                    row.append(round(sorted_pts[0][1], 4))
                elif m >= sorted_pts[-1][0]:
                    row.append(round(sorted_pts[-1][1], 4))
                else:
                    # 线性插值
                    for i in range(len(sorted_pts) - 1):
                        if sorted_pts[i][0] <= m <= sorted_pts[i + 1][0]:
                            w = (m - sorted_pts[i][0]) / (sorted_pts[i + 1][0] - sorted_pts[i][0])
                            val = sorted_pts[i][1] + w * (sorted_pts[i + 1][1] - sorted_pts[i][1])
                            row.append(round(val, 4))
                            break
                    else:
                        row.append(round(sorted_pts[-1][1], 4))
        vol_grid.append(row)

    if not vol_grid or len(used_tenors) < 2:
        return None

    return {
        "moneyness_grid": moneyness_grid,
        "tenor_grid": used_tenors,
        "vol_grid": vol_grid,
    }


def main():
    args = parse_args()
    dry_run = args.dry_run
    n_days = args.days

    end_date = datetime.now()
    start_date = end_date - timedelta(days=n_days)
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    print(f"=== 收益凭证估值数据导入 ===")
    print(f"日期范围: {fmt_date(start_str)} ~ {fmt_date(end_str)}")
    print(f"模式: {'DRY-RUN (不写库)' if dry_run else '写入 MongoDB'}")
    print()

    pro = ts.pro_api(TOKEN)

    # 连接 MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    col_asset_prices = db["asset_prices"]
    col_market_data = db["option_market_data"]
    col_vol_surfaces = db["option_vol_surfaces"]
    col_contracts = db["option_contracts"]
    col_iv_data = db["option_iv_data"]

    stats = {
        "index_prices": 0,
        "shibor_rates": 0,
        "market_data": 0,
        "contracts": 0,
        "iv_records": 0,
        "vol_surfaces": 0,
    }

    # ══════════════════════════════════════════════════
    #  1. 指数日线行情 → asset_prices
    # ══════════════════════════════════════════════════
    print("[1/6] 下载指数日线行情...")
    for ts_code, sys_code in INDEX_MAP.items():
        time.sleep(0.3)
        try:
            df = pro.index_daily(ts_code=ts_code, start_date=start_str, end_date=end_str)
            if df is None or df.empty:
                print(f"  {ts_code} ({sys_code}): 无数据")
                continue
            df = df.sort_values("trade_date").reset_index(drop=True)
            ops = []
            for _, row in df.iterrows():
                d = fmt_date(row["trade_date"])
                ops.append(UpdateOne(
                    {"asset_code": sys_code, "date": d},
                    {"$set": {
                        "asset_code": sys_code,
                        "date": d,
                        "close": float(row["close"]),
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "volume": float(row.get("vol", 0)),
                        "amount": float(row.get("amount", 0)),
                    }},
                    upsert=True,
                ))
            if not dry_run and ops:
                for i in range(0, len(ops), BATCH_SIZE):
                    col_asset_prices.bulk_write(ops[i:i + BATCH_SIZE], ordered=False)
            stats["index_prices"] += len(ops)
            latest = df.iloc[-1]
            print(f"  {ts_code} ({sys_code}): {len(df)} 天, "
                  f"最新 {fmt_date(latest['trade_date'])} close={latest['close']:.2f}")
        except Exception as e:
            print(f"  {ts_code}: ERROR: {e}")

    # ══════════════════════════════════════════════════
    #  2. SHIBOR 利率
    # ══════════════════════════════════════════════════
    print("\n[2/6] 下载SHIBOR利率...")
    try:
        df_shibor = pro.shibor(start_date=start_str, end_date=end_str)
        if df_shibor is not None and not df_shibor.empty:
            df_shibor = df_shibor.sort_values("date").reset_index(drop=True)
            stats["shibor_rates"] = len(df_shibor)
            latest = df_shibor.iloc[-1]
            print(f"  {len(df_shibor)} 天, 最新 {fmt_date(latest['date'])}: "
                  f"1M={latest['1m']}%, 3M={latest['3m']}%, 1Y={latest['1y']}%")
        else:
            df_shibor = pd.DataFrame()
    except Exception as e:
        print(f"  ERROR: {e}")
        df_shibor = pd.DataFrame()

    # 补充 LPR
    try:
        df_lpr = pro.shibor_lpr(start_date=start_str, end_date=end_str)
        if df_lpr is not None and not df_lpr.empty:
            latest_lpr = df_lpr.sort_values("date").iloc[-1]
            print(f"  LPR: 1Y={latest_lpr['1y']}%, 5Y={latest_lpr['5y']}%")
    except Exception:
        pass

    # ══════════════════════════════════════════════════
    #  3. 期权合约信息 → option_contracts
    # ══════════════════════════════════════════════════
    print("\n[3/6] 下载期权合约信息...")
    all_contracts = pd.DataFrame()
    for exchange in ["SSE", "SZSE"]:
        time.sleep(0.3)
        try:
            df = pro.opt_basic(
                exchange=exchange,
                fields='ts_code,name,call_put,list_date,delist_date,exercise_price,s_month,per_unit,opt_code'
            )
            if df is not None and not df.empty:
                all_contracts = pd.concat([all_contracts, df], ignore_index=True)
                print(f"  {exchange}: {len(df)} 个合约")
        except Exception as e:
            print(f"  {exchange}: ERROR: {e}")

    if not all_contracts.empty:
        # 筛选活跃合约
        active = all_contracts[all_contracts["delist_date"] >= end_str]
        print(f"  活跃合约: {len(active)} / 总计: {len(all_contracts)}")

        # 写入 option_contracts
        if not dry_run:
            ops = []
            for _, row in active.iterrows():
                ops.append(UpdateOne(
                    {"ts_code": row["ts_code"]},
                    {"$set": {
                        "ts_code": row["ts_code"],
                        "name": row["name"],
                        "call_put": row["call_put"],
                        "list_date": fmt_date(row["list_date"]),
                        "delist_date": fmt_date(row["delist_date"]),
                        "exercise_price": float(row["exercise_price"]),
                        "s_month": row["s_month"],
                        "exchange": row["ts_code"].split(".")[-1],
                        "updated_at": datetime.now(),
                    }},
                    upsert=True,
                ))
            for i in range(0, len(ops), BATCH_SIZE):
                col_contracts.bulk_write(ops[i:i + BATCH_SIZE], ordered=False)
        stats["contracts"] = len(active)

    # ══════════════════════════════════════════════════
    #  4. 期权日线 → 计算隐含波动率 → option_iv_data
    # ══════════════════════════════════════════════════
    print("\n[4/6] 下载期权日线并计算隐含波动率...")

    # 获取最近的ETF价格 (用于计算IV)
    etf_prices = {}
    for etf_code, sys_code in ETF_MAP.items():
        time.sleep(0.3)
        try:
            # 获取ETF对应指数的价格
            idx_code = sys_code.replace("SH", "").replace("SZ", "")
            if sys_code == "SH000300":
                idx_ts = "000300.SH"
            elif sys_code == "SH000016":
                idx_ts = "000016.SH"
            else:
                continue
            df_idx = pro.index_daily(ts_code=idx_ts, start_date=start_str, end_date=end_str)
            if df_idx is not None and not df_idx.empty:
                for _, row in df_idx.iterrows():
                    d = fmt_date(row["trade_date"])
                    etf_prices.setdefault(d, {})[sys_code] = float(row["close"])
        except Exception as e:
            print(f"  ETF {etf_code}: ERROR: {e}")

    # 选取活跃的300ETF期权计算IV
    if not all_contracts.empty:
        # 筛选沪深300相关合约 (1000xxxx 或 9000xxxx 开头)
        contracts_300 = all_contracts[
            (all_contracts["ts_code"].str.startswith("1000") | all_contracts["ts_code"].str.startswith("9000"))
            & (all_contracts["delist_date"] >= end_str)
        ]
        # 取最近到期的 20 个合约
        contracts_300 = contracts_300.sort_values("delist_date").head(20)
        print(f"  选取 {len(contracts_300)} 个300ETF合约计算IV")

        iv_ops = []
        iv_by_date = {}  # date → [{moneyness, tenor, iv}]

        for _, contract in contracts_300.iterrows():
            ts_code = contract["ts_code"]
            call_put = contract["call_put"]
            K = float(contract["exercise_price"])
            delist = contract["delist_date"]
            time.sleep(0.3)
            try:
                df_opt = pro.opt_daily(ts_code=ts_code, start_date=start_str, end_date=end_str)
                if df_opt is None or df_opt.empty:
                    continue

                for _, row in df_opt.iterrows():
                    d = fmt_date(row["trade_date"])
                    settle = float(row.get("settle", 0) or 0)
                    if settle <= 0:
                        continue

                    # 获取当日标的价格
                    spot_data = etf_prices.get(d, {})
                    spot = spot_data.get("SH000300", spot_data.get("SH000016"))
                    if not spot or spot <= 0:
                        continue

                    # 计算到期时间
                    delist_date = datetime.strptime(delist, "%Y%m%d")
                    trade_date = datetime.strptime(row["trade_date"], "%Y%m%d")
                    T = (delist_date - trade_date).days / 365.0
                    if T <= 0.001 or T > 2.0:
                        continue

                    # 获取利率
                    rate = 0.02  # 默认
                    if not df_shibor.empty:
                        shibor_row = df_shibor[df_shibor["date"] == row["trade_date"]]
                        if not shibor_row.empty:
                            rate = float(shibor_row.iloc[0]["1y"]) / 100.0

                    # 计算IV
                    iv = calc_implied_vol(settle, spot, K, T, rate, 0.02, call_put)
                    if iv and 0.05 < iv < 3.0:
                        moneyness = round(K / spot, 4)
                        record = {
                            "ts_code": ts_code,
                            "date": d,
                            "call_put": call_put,
                            "strike": K,
                            "settle": settle,
                            "spot": spot,
                            "moneyness": moneyness,
                            "tenor": round(T, 4),
                            "iv": round(iv, 4),
                            "rate": rate,
                        }
                        if not dry_run:
                            iv_ops.append(UpdateOne(
                                {"ts_code": ts_code, "date": d},
                                {"$set": record},
                                upsert=True,
                            ))
                        iv_by_date.setdefault(d, []).append(record)

            except Exception as e:
                print(f"    {ts_code}: ERROR: {e}")

        if not dry_run and iv_ops:
            for i in range(0, len(iv_ops), BATCH_SIZE):
                col_iv_data.bulk_write(iv_ops[i:i + BATCH_SIZE], ordered=False)
        stats["iv_records"] = len(iv_ops) if not dry_run else sum(len(v) for v in iv_by_date.values())
        print(f"  计算IV: {stats['iv_records']} 条, 覆盖 {len(iv_by_date)} 个交易日")

    # ══════════════════════════════════════════════════
    #  5. 构建波动率曲面 → option_vol_surfaces
    # ══════════════════════════════════════════════════
    print("\n[5/6] 构建波动率曲面...")

    # 取最近一个交易日的IV数据构建曲面
    if iv_by_date:
        sorted_dates = sorted(iv_by_date.keys(), reverse=True)
        latest_date = sorted_dates[0]
        iv_records = iv_by_date[latest_date]
        spot = iv_records[0]["spot"] if iv_records else 0
        rate = iv_records[0]["rate"] if iv_records else 0.02

        surface = build_vol_surface(iv_records, spot, rate)
        if surface:
            if not dry_run:
                col_vol_surfaces.update_one(
                    {"underlying": "SH000300"},
                    {"$set": {
                        "underlying": "SH000300",
                        "date": latest_date,
                        "spot": spot,
                        **surface,
                        "updated_at": datetime.now(),
                    }},
                    upsert=True,
                )
            stats["vol_surfaces"] += 1
            print(f"  SH000300 (沪深300): {len(surface['moneyness_grid'])}×{len(surface['tenor_grid'])} 网格, "
                  f"基于 {len(iv_records)} 个IV点, 日期={latest_date}")
            # 打印曲面
            print(f"    Moneyness: {surface['moneyness_grid']}")
            print(f"    Tenor(年): {[round(t, 3) for t in surface['tenor_grid']]}")
            for i, t in enumerate(surface['tenor_grid']):
                vols = [f"{v*100:.1f}%" for v in surface['vol_grid'][i]]
                print(f"    T={t:.3f}y: {vols}")
        else:
            print(f"  SH000300: IV数据不足以构建曲面 (仅 {len(iv_records)} 个点)")

        # 尝试构建多个日期的曲面
        for d in sorted_dates[1:min(10, len(sorted_dates))]:
            iv_recs = iv_by_date[d]
            sp = iv_recs[0]["spot"] if iv_recs else 0
            rt = iv_recs[0]["rate"] if iv_recs else 0.02
            sf = build_vol_surface(iv_recs, sp, rt)
            if sf and not dry_run:
                col_vol_surfaces.update_one(
                    {"underlying": f"SH000300_{d}"},
                    {"$set": {
                        "underlying": "SH000300",
                        "date": d,
                        "spot": sp,
                        **sf,
                        "updated_at": datetime.now(),
                    }},
                    upsert=True,
                )
                stats["vol_surfaces"] += 1
        if stats["vol_surfaces"] > 1:
            print(f"  共构建 {stats['vol_surfaces']} 个曲面快照")

    # ══════════════════════════════════════════════════
    #  6. 综合市场数据 → option_market_data
    # ══════════════════════════════════════════════════
    print("\n[6/6] 生成综合市场数据 (option_market_data)...")

    # 获取最近的交易日列表
    trade_dates = []
    try:
        df_cal = pro.trade_cal(exchange='SSE', start_date=start_str, end_date=end_str)
        if df_cal is not None and not df_cal.empty:
            open_days = df_cal[df_cal['is_open'] == 1].sort_values('cal_date')
            trade_dates = [row['cal_date'] for _, row in open_days.iterrows()]
    except Exception:
        pass

    # 为每个交易日 × 每个标的生成 option_market_data
    market_ops = []
    for d_raw in trade_dates[-60:]:  # 最近60个交易日
        d = fmt_date(d_raw)

        for ts_code, sys_code in INDEX_MAP.items():
            # 获取 spot
            spot_doc = col_asset_prices.find_one({"asset_code": sys_code, "date": d})
            spot = spot_doc["close"] if spot_doc else None
            if not spot:
                continue

            # 获取利率 (SHIBOR)
            rate_1m, rate_3m, rate_6m, rate_1y = 0.018, 0.019, 0.020, 0.022
            if not df_shibor.empty:
                shibor_row = df_shibor[df_shibor["date"] == d_raw]
                if not shibor_row.empty:
                    sr = shibor_row.iloc[0]
                    rate_1m = float(sr["1m"]) / 100.0
                    rate_3m = float(sr["3m"]) / 100.0
                    rate_6m = float(sr["6m"]) / 100.0
                    rate_1y = float(sr["1y"]) / 100.0

            # 获取波动率 (从IV数据)
            vol_1m, vol_3m, vol_6m, vol_12m = 0.20, 0.18, 0.17, 0.16
            iv_recs = iv_by_date.get(d, [])
            if iv_recs:
                # 按 tenor 分组取中位数IV
                tenor_buckets = {0.083: [], 0.25: [], 0.5: [], 1.0: []}
                for rec in iv_recs:
                    t = rec["tenor"]
                    iv = rec["iv"]
                    best_t = min(tenor_buckets.keys(), key=lambda bt: abs(bt - t))
                    if abs(best_t - t) < 0.15:
                        tenor_buckets[best_t].append(iv)
                if tenor_buckets[0.083]:
                    vol_1m = float(np.median(tenor_buckets[0.083]))
                if tenor_buckets[0.25]:
                    vol_3m = float(np.median(tenor_buckets[0.25]))
                if tenor_buckets[0.5]:
                    vol_6m = float(np.median(tenor_buckets[0.5]))
                if tenor_buckets[1.0]:
                    vol_12m = float(np.median(tenor_buckets[1.0]))

            # 分红率 (估算)
            div_yield = 0.02 if sys_code in ("SH000300", "SH000016") else 0.01

            record = {
                "date": d,
                "underlying": sys_code,
                "spot": spot,
                "dividend_yield": div_yield,
                "vol_1m": round(vol_1m, 4),
                "vol_3m": round(vol_3m, 4),
                "vol_6m": round(vol_6m, 4),
                "vol_12m": round(vol_12m, 4),
                "rate_1m": round(rate_1m, 4),
                "rate_3m": round(rate_3m, 4),
                "rate_6m": round(rate_6m, 4),
                "rate_1y": round(rate_1y, 4),
                "rate_2y": round(rate_1y * 1.1, 4),
                "rate_5y": round(rate_1y * 1.3, 4),
                "data_source": "tushare",
                "created_at": datetime.now(),
            }
            if not dry_run:
                market_ops.append(UpdateOne(
                    {"date": d, "underlying": sys_code},
                    {"$set": record},
                    upsert=True,
                ))

    if not dry_run and market_ops:
        for i in range(0, len(market_ops), BATCH_SIZE):
            col_market_data.bulk_write(market_ops[i:i + BATCH_SIZE], ordered=False)
    stats["market_data"] = len(market_ops)
    print(f"  写入 {stats['market_data']} 条市场数据 "
          f"({min(60, len(trade_dates))} 交易日 × {len(INDEX_MAP)} 标的)")

    # ══════════════════════════════════════════════════
    #  汇总
    # ══════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("数据导入完成!")
    for k, v in stats.items():
        print(f"  {k:20s}: {v:>8,}")
    print()

    if not dry_run:
        # 创建索引
        print("创建索引...")
        col_asset_prices.create_index([("asset_code", 1), ("date", 1)], unique=True)
        col_market_data.create_index([("date", 1), ("underlying", 1)], unique=True)
        col_contracts.create_index("ts_code", unique=True)
        col_iv_data.create_index([("ts_code", 1), ("date", 1)], unique=True)
        col_iv_data.create_index([("date", 1), ("moneyness", 1), ("tenor", 1)])
        col_vol_surfaces.create_index([("underlying", 1), ("date", 1)])
        print("索引创建完成")

    print(f"\n接下来可以：")
    print(f"  1. 启动后端: py main.py")
    print(f"  2. 打开估值工作台: http://localhost:8080/#/options/workbench")
    print(f"  3. 选择日期 → 运行估值 (数据已从真实市场获取)")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
