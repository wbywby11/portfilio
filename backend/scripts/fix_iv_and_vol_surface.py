# -*- coding: utf-8 -*-
"""修复隐含波动率 moneyness 计算（使用 ETF 价格而非指数价格）"""
import sys, os, time, math
from datetime import datetime, timedelta

import numpy as np
import tushare as ts
from pymongo import MongoClient, UpdateOne

TOKEN = "286fd29627e9ce67299c961761cc79b1aad18937fc58373f87793775"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "asset_allocation"

BATCH_SIZE = 1000


def calc_implied_vol(option_price, S, K, T, r, q, option_type="C"):
    """Newton-Raphson 计算隐含波动率"""
    from scipy.stats import norm
    if option_price <= 0 or T <= 0 or K <= 0 or S <= 0:
        return None
    intrinsic = max(S - K, 0) if option_type == "C" else max(K - S, 0)
    if option_price < intrinsic * 0.95:
        return None

    vol = 0.25
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


def fmt_date(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def build_vol_surface(iv_records, spot):
    """从IV数据构建波动率曲面"""
    if not iv_records:
        return None

    moneyness_grid = [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]
    tenor_grid = [1/12, 2/12, 3/12, 6/12, 1.0]

    buckets = {}
    for rec in iv_records:
        t = rec["tenor"]
        mn = rec["moneyness"]
        iv = rec["iv"]
        if iv is None or iv < 0.05 or iv > 2.0:
            continue
        if mn < 0.7 or mn > 1.4:
            continue
        best_t = min(tenor_grid, key=lambda bt: abs(bt - t))
        if abs(best_t - t) > 0.12:
            continue
        buckets.setdefault(best_t, []).append((mn, iv))

    if len(buckets) < 2:
        return None

    vol_grid = []
    used_tenors = []
    for t in tenor_grid:
        if t not in buckets or not buckets[t]:
            continue
        used_tenors.append(t)
        points = sorted(buckets[t], key=lambda p: p[0])
        row = []
        for m in moneyness_grid:
            best = min(points, key=lambda p: abs(p[0] - m))
            if abs(best[0] - m) < 0.06:
                row.append(round(best[1], 4))
            else:
                # 插值
                if m <= points[0][0]:
                    row.append(round(points[0][1], 4))
                elif m >= points[-1][0]:
                    row.append(round(points[-1][1], 4))
                else:
                    for i in range(len(points) - 1):
                        if points[i][0] <= m <= points[i+1][0]:
                            w = (m - points[i][0]) / (points[i+1][0] - points[i][0])
                            val = points[i][1] + w * (points[i+1][1] - points[i][1])
                            row.append(round(val, 4))
                            break
                    else:
                        row.append(round(points[-1][1], 4))
        vol_grid.append(row)

    if not vol_grid or len(used_tenors) < 2:
        return None

    return {
        "moneyness_grid": moneyness_grid,
        "tenor_grid": used_tenors,
        "vol_grid": vol_grid,
    }


def main():
    pro = ts.pro_api(TOKEN)
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    end_str = datetime.now().strftime("%Y%m%d")
    start_str = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")

    # 1. 下载 ETF 日线 (510300, 510050)
    print("[1] 下载 ETF 日线...")
    etf_prices = {}  # date → {etf_code: close}
    for etf_code in ["510300.SH", "510050.SH"]:
        time.sleep(0.3)
        df = pro.fund_daily(ts_code=etf_code, start_date=start_str, end_date=end_str)
        if df is not None and not df.empty:
            df = df.sort_values("trade_date")
            for _, row in df.iterrows():
                d = fmt_date(row["trade_date"])
                etf_prices.setdefault(d, {})[etf_code] = float(row["close"])
            print(f"  {etf_code}: {len(df)} days, latest close={df.iloc[-1]['close']:.4f}")

    # 2. 下载 SHIBOR
    print("\n[2] 下载 SHIBOR...")
    df_shibor = pro.shibor(start_date=start_str, end_date=end_str)
    shibor_by_date = {}
    if df_shibor is not None and not df_shibor.empty:
        for _, row in df_shibor.iterrows():
            shibor_by_date[row["date"]] = {
                "1m": float(row["1m"]) / 100,
                "3m": float(row["3m"]) / 100,
                "6m": float(row["6m"]) / 100,
                "1y": float(row["1y"]) / 100,
            }
        print(f"  {len(df_shibor)} days")

    # 3. 获取活跃合约
    print("\n[3] 获取期权合约...")
    df_basic = pro.opt_basic(exchange="SSE",
                             fields="ts_code,name,call_put,list_date,delist_date,exercise_price,s_month")
    active = df_basic[df_basic["delist_date"] >= end_str]
    # 筛选 300ETF 相关 (1000xxxx)
    contracts_300 = active[active["ts_code"].str.startswith("1000")].sort_values("delist_date").head(30)
    print(f"  活跃 300ETF 合约: {len(contracts_300)}")

    # 4. 重新计算 IV (使用 ETF 价格)
    print("\n[4] 重新计算隐含波动率...")
    iv_by_date = {}
    iv_ops = []

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

                # 使用 ETF 价格
                etf_price = etf_prices.get(d, {}).get("510300.SH")
                if not etf_price or etf_price <= 0:
                    continue

                delist_date = datetime.strptime(delist, "%Y%m%d")
                trade_date = datetime.strptime(row["trade_date"], "%Y%m%d")
                T = (delist_date - trade_date).days / 365.0
                if T <= 0.005 or T > 2.0:
                    continue

                rate = shibor_by_date.get(row["trade_date"], {}).get("1y", 0.02)

                iv = calc_implied_vol(settle, etf_price, K, T, rate, 0.02, call_put)
                if iv and 0.05 < iv < 2.0:
                    moneyness = round(K / etf_price, 4)
                    record = {
                        "ts_code": ts_code, "date": d,
                        "call_put": call_put, "strike": K,
                        "settle": settle, "spot": etf_price,
                        "moneyness": moneyness, "tenor": round(T, 4),
                        "iv": round(iv, 4), "rate": rate,
                    }
                    iv_ops.append(UpdateOne(
                        {"ts_code": ts_code, "date": d},
                        {"$set": record}, upsert=True,
                    ))
                    iv_by_date.setdefault(d, []).append(record)
        except Exception as e:
            print(f"    {ts_code}: ERROR: {e}")

    if iv_ops:
        for i in range(0, len(iv_ops), BATCH_SIZE):
            db["option_iv_data"].bulk_write(iv_ops[i:i + BATCH_SIZE], ordered=False)
    print(f"  写入 {len(iv_ops)} 条 IV 记录, 覆盖 {len(iv_by_date)} 个交易日")

    # 5. 更新 option_market_data 的波动率
    print("\n[5] 更新 option_market_data 波动率...")
    market_ops = []
    for d, iv_recs in iv_by_date.items():
        # 按 tenor 分桶
        tenor_buckets = {0.083: [], 0.25: [], 0.5: [], 1.0: []}
        for rec in iv_recs:
            t = rec["tenor"]
            best_t = min(tenor_buckets.keys(), key=lambda bt: abs(bt - t))
            if abs(best_t - t) < 0.15:
                tenor_buckets[best_t].append(rec["iv"])

        vol_1m = float(np.median(tenor_buckets[0.083])) if tenor_buckets[0.083] else None
        vol_3m = float(np.median(tenor_buckets[0.25])) if tenor_buckets[0.25] else None
        vol_6m = float(np.median(tenor_buckets[0.5])) if tenor_buckets[0.5] else None
        vol_12m = float(np.median(tenor_buckets[1.0])) if tenor_buckets[1.0] else None

        if vol_1m:
            # 更新 SH000300 的市场数据
            update = {"data_source": "tushare_iv"}
            if vol_1m: update["vol_1m"] = round(vol_1m, 4)
            if vol_3m: update["vol_3m"] = round(vol_3m, 4)
            if vol_6m: update["vol_6m"] = round(vol_6m, 4)
            if vol_12m: update["vol_12m"] = round(vol_12m, 4)
            market_ops.append(UpdateOne(
                {"date": d, "underlying": "SH000300"},
                {"$set": update}, upsert=True,
            ))

    if market_ops:
        db["option_market_data"].bulk_write(market_ops, ordered=False)
    print(f"  更新 {len(market_ops)} 条市场数据的波动率")

    # 6. 构建波动率曲面
    print("\n[6] 构建波动率曲面...")
    sorted_dates = sorted(iv_by_date.keys(), reverse=True)
    surface_count = 0
    for d in sorted_dates[:15]:  # 最近15个交易日
        iv_recs = iv_by_date[d]
        spot = iv_recs[0]["spot"] if iv_recs else 0
        surface = build_vol_surface(iv_recs, spot)
        if surface:
            db["option_vol_surfaces"].update_one(
                {"underlying": "SH000300", "date": d},
                {"$set": {
                    "underlying": "SH000300",
                    "date": d,
                    "spot": spot,
                    **surface,
                    "updated_at": datetime.now(),
                }},
                upsert=True,
            )
            surface_count += 1
            if surface_count == 1:
                print(f"  最新曲面 {d}: spot={spot:.4f}")
                print(f"    Moneyness: {surface['moneyness_grid']}")
                print(f"    Tenor(年): {[round(t, 3) for t in surface['tenor_grid']]}")
                for i, t in enumerate(surface["tenor_grid"]):
                    vols = [f"{v*100:.1f}%" for v in surface["vol_grid"][i]]
                    print(f"    T={t:.3f}y: {vols}")

    print(f"  共构建 {surface_count} 个曲面快照")

    # 7. 验证最终结果
    print("\n=== 最终数据验证 ===")
    latest = db["option_market_data"].find_one(
        {"underlying": "SH000300"}, sort=[("date", -1)])
    if latest:
        print(f"\nSH000300 最新市场数据 ({latest['date']}):")
        print(f"  spot={latest['spot']:.2f}")
        print(f"  vol_1m={latest['vol_1m']*100:.1f}%  vol_3m={latest['vol_3m']*100:.1f}%"
              f"  vol_6m={latest['vol_6m']*100:.1f}%  vol_12m={latest['vol_12m']*100:.1f}%")
        print(f"  rate_1y={latest['rate_1y']*100:.2f}%")

    vs = db["option_vol_surfaces"].find_one(
        {"underlying": "SH000300"}, sort=[("date", -1)])
    if vs:
        print(f"\nSH000300 最新波动率曲面 ({vs['date']}):")
        print(f"  Moneyness: {vs['moneyness_grid']}")
        print(f"  Tenor: {[round(t, 3) for t in vs['tenor_grid']]}")
        for i, t in enumerate(vs["tenor_grid"]):
            vols = [f"{v*100:.1f}%" for v in vs["vol_grid"][i]]
            print(f"  T={t:.3f}y: {vols}")

    # 集合统计
    print(f"\n集合总览:")
    for col in ["asset_prices", "option_market_data", "option_contracts",
                 "option_iv_data", "option_vol_surfaces", "option_products"]:
        cnt = db[col].count_documents({})
        print(f"  {col:30s}: {cnt:>8,}")

    client.close()
    print("\n=== 修复完成 ===")


if __name__ == "__main__":
    main()
