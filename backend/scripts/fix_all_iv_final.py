# -*- coding: utf-8 -*-
"""一步修复: 用ETF价格重新计算所有IV数据的moneyness + 构建波动率曲面"""
from pymongo import MongoClient, UpdateOne
import numpy as np
from datetime import datetime
import tushare as ts
import time, math

TOKEN = "286fd29627e9ce67299c961761cc79b1aad18937fc58373f87793775"
BATCH = 1000


def calc_iv(opt_price, S, K, T, r, q, cp="C"):
    from scipy.stats import norm
    if opt_price <= 0 or T <= 0 or K <= 0 or S <= 0:
        return None
    intrinsic = max(S - K, 0) if cp == "C" else max(K - S, 0)
    if opt_price < intrinsic * 0.9:
        return None
    vol = 0.25
    for _ in range(50):
        sT = math.sqrt(T)
        d1 = (math.log(S / K) + (r - q + 0.5 * vol**2) * T) / (vol * sT)
        d2 = d1 - vol * sT
        if cp == "C":
            px = math.exp(-r*T) * (S*math.exp((r-q)*T)*norm.cdf(d1) - K*norm.cdf(d2))
        else:
            px = math.exp(-r*T) * (K*norm.cdf(-d2) - S*math.exp((r-q)*T)*norm.cdf(-d1))
        diff = px - opt_price
        if abs(diff) < 1e-6:
            return vol
        vega = S * math.exp(-q*T) * norm.pdf(d1) * sT
        if vega < 1e-10:
            break
        step = max(-0.5, min(0.5, diff / vega))
        vol = max(0.01, min(5.0, vol - step))
    return None if vol <= 0.01 or vol >= 5.0 else vol


def build_surface(iv_records):
    """自适应网格构建波动率曲面"""
    clean = [(r["moneyness"], r["tenor"], r["iv"]) for r in iv_records
             if 0.05 < r["iv"] < 1.5 and 0.70 < r["moneyness"] < 1.40 and r["tenor"] > 0.01]
    if len(clean) < 15:
        return None

    # 按 tenor 分桶
    t_targets = [0.08, 0.17, 0.25, 0.50, 0.75, 1.00]
    buckets = {}
    for mn, t, iv in clean:
        best_t = min(t_targets, key=lambda bt: abs(bt - t))
        if abs(best_t - t) > 0.10:
            continue
        buckets.setdefault(best_t, []).append((mn, iv))

    if len(buckets) < 2:
        return None

    m_grid = [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]
    vol_grid, used_t = [], []

    for t in t_targets:
        if t not in buckets:
            continue
        pts = sorted(buckets[t], key=lambda p: p[0])
        if len(pts) < 3:
            continue
        used_t.append(t)
        row = []
        for m in m_grid:
            # 加权平均: 距离越近权重越大
            dists = [(abs(p[0] - m), p[1]) for p in pts]
            dists.sort()
            if dists[0][0] < 0.04:
                row.append(round(dists[0][1], 4))
            else:
                # 加权平均(距离反比)
                weights = [1.0 / max(d, 0.001) for d, _ in dists[:5]]
                total_w = sum(weights)
                val = sum(w * v for w, (_, v) in zip(weights, dists[:5])) / total_w
                row.append(round(val, 4))
        vol_grid.append(row)

    if len(used_t) < 2 or not vol_grid:
        return None
    return {"moneyness_grid": m_grid, "tenor_grid": used_t, "vol_grid": vol_grid}


def main():
    pro = ts.pro_api(TOKEN)
    client = MongoClient("mongodb://localhost:27017")
    db = client["asset_allocation"]

    end_str = datetime.now().strftime("%Y%m%d")
    start_str = "20260301"

    # 1. 获取ETF日线
    print("[1] 下载ETF日线...")
    etf_prices = {}
    for etf in ["510300.SH", "510050.SH"]:
        time.sleep(0.3)
        df = pro.fund_daily(ts_code=etf, start_date=start_str, end_date=end_str)
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                d = f"{r['trade_date'][:4]}-{r['trade_date'][4:6]}-{r['trade_date'][6:8]}"
                etf_prices.setdefault(d, {})[etf] = float(r["close"])
            print(f"  {etf}: {len(df)} days, latest={df.iloc[0]['close']:.4f}")

    # 2. SHIBOR
    print("\n[2] SHIBOR...")
    df_shibor = pro.shibor(start_date=start_str, end_date=end_str)
    rates = {}
    if df_shibor is not None and not df_shibor.empty:
        for _, r in df_shibor.iterrows():
            d = f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:8]}"
            rates[d] = float(r["1y"]) / 100

    # 3. 获取活跃合约
    print("\n[3] 期权合约...")
    df_all = pro.opt_basic(exchange="SSE",
                           fields="ts_code,name,call_put,delist_date,exercise_price")
    active = df_all[df_all["delist_date"] >= end_str]
    mask_50 = active["name"].str.contains("50ETF", na=False)
    mask_300 = active["name"].str.contains("300ETF", na=False)
    selected = active[mask_50 | mask_300].sort_values("delist_date").head(50)
    print(f"  Selected: {len(selected)} contracts")

    # 4. 重新计算IV (全部使用ETF价格)
    print("\n[4] 重新计算IV (ETF价格)...")

    # 先清除旧的错误数据
    old_bad = db["option_iv_data"].count_documents({"moneyness": {"$lt": 0.5}})
    if old_bad > 0:
        db["option_iv_data"].delete_many({"moneyness": {"$lt": 0.5}})
        print(f"  清除 {old_bad} 条 moneyness<0.5 的错误数据")

    iv_by_date = {}
    iv_ops = []
    etf_map = {"50ETF": "510050.SH", "300ETF": "510300.SH"}
    processed = 0

    for _, c in selected.iterrows():
        code = c["ts_code"]
        cp = c["call_put"]
        K = float(c["exercise_price"])
        delist = c["delist_date"]
        name = c["name"]
        time.sleep(0.3)

        etf_code = "510300.SH"
        for key, val in etf_map.items():
            if key in name:
                etf_code = val
                break

        try:
            df_opt = pro.opt_daily(ts_code=code, start_date=start_str, end_date=end_str)
            if df_opt is None or df_opt.empty:
                continue

            for _, r in df_opt.iterrows():
                d = f"{r['trade_date'][:4]}-{r['trade_date'][4:6]}-{r['trade_date'][6:8]}"
                settle = float(r.get("settle", 0) or 0)
                if settle <= 0:
                    continue
                spot = etf_prices.get(d, {}).get(etf_code)
                if not spot or spot <= 0:
                    continue

                delist_dt = datetime.strptime(delist, "%Y%m%d")
                trade_dt = datetime.strptime(r["trade_date"], "%Y%m%d")
                T = (delist_dt - trade_dt).days / 365.0
                if T <= 0.005 or T > 2.0:
                    continue
                rate = rates.get(d, 0.015)

                iv = calc_iv(settle, spot, K, T, rate, 0.02, cp)
                if iv and 0.05 < iv < 1.5:
                    mn = round(K / spot, 4)
                    rec = {"ts_code": code, "date": d, "call_put": cp,
                           "strike": K, "settle": settle, "spot": spot,
                           "moneyness": mn, "tenor": round(T, 4),
                           "iv": round(iv, 4), "rate": rate, "etf": etf_code}
                    iv_ops.append(UpdateOne({"ts_code": code, "date": d},
                                            {"$set": rec}, upsert=True))
                    iv_by_date.setdefault(d, []).append(rec)
            processed += 1
        except Exception as e:
            print(f"    {code}: ERROR: {e}")

    if iv_ops:
        for i in range(0, len(iv_ops), BATCH):
            db["option_iv_data"].bulk_write(iv_ops[i:i+BATCH], ordered=False)
    total_iv = sum(len(v) for v in iv_by_date.values())
    print(f"  Processed: {processed} contracts, {total_iv} IV records, {len(iv_by_date)} days")

    # 5. 更新市场数据波动率
    print("\n[5] 更新市场数据波动率...")
    mkt_ops = []
    for d, recs in iv_by_date.items():
        t_buckets = {0.08: [], 0.17: [], 0.25: [], 0.50: [], 0.75: [], 1.00: []}
        for rec in recs:
            best_t = min(t_buckets.keys(), key=lambda bt: abs(bt - rec["tenor"]))
            if abs(best_t - rec["tenor"]) < 0.12:
                t_buckets[best_t].append(rec["iv"])
        update = {"data_source": "tushare_iv"}
        for t_key, field in [(0.08, "vol_1m"), (0.25, "vol_3m"), (0.50, "vol_6m"), (1.00, "vol_12m")]:
            if t_buckets[t_key]:
                update[field] = round(float(np.median(t_buckets[t_key])), 4)
        for underlying in ["SH000300", "SH000016"]:
            mkt_ops.append(UpdateOne({"date": d, "underlying": underlying},
                                     {"$set": update}, upsert=True))
    if mkt_ops:
        db["option_market_data"].bulk_write(mkt_ops, ordered=False)
    print(f"  Updated {len(mkt_ops)} records")

    # 6. 构建波动率曲面
    print("\n[6] 构建波动率曲面...")
    sorted_dates = sorted(iv_by_date.keys(), reverse=True)
    surf_count = 0
    for d in sorted_dates[:20]:
        recs = iv_by_date[d]
        spot = recs[0]["spot"] if recs else 0
        surf = build_surface(recs)
        if surf:
            db["option_vol_surfaces"].update_one(
                {"underlying": "SH000300", "date": d},
                {"$set": {"underlying": "SH000300", "date": d,
                           "spot": spot, **surf, "updated_at": datetime.now()}},
                upsert=True)
            surf_count += 1
            if surf_count <= 2:
                print(f"\n  ✓ {d} (spot={spot:.4f}):")
                print(f"    Moneyness: {surf['moneyness_grid']}")
                print(f"    Tenor(yr): {[round(t,3) for t in surf['tenor_grid']]}")
                for i, t in enumerate(surf["tenor_grid"]):
                    vols = [f"{v*100:.1f}%" for v in surf["vol_grid"][i]]
                    print(f"    T={t:.3f}y: {vols}")
    print(f"\n  Built {surf_count} surfaces")

    # 7. 验证
    print("\n" + "="*60)
    print("=== 最终数据验证 ===")
    print("="*60)

    # IV数据样本
    sample = list(db["option_iv_data"].find({"date": sorted_dates[0]}).limit(5))
    print(f"\nIV数据样本 ({sorted_dates[0]}):")
    for s in sample:
        print(f"  strike={s['strike']:.2f} spot={s['spot']:.4f} "
              f"moneyness={s['moneyness']:.3f} tenor={s['tenor']:.3f}y "
              f"iv={s['iv']*100:.1f}%")

    # 市场数据
    latest_mkt = db["option_market_data"].find_one({"underlying": "SH000300"}, sort=[("date", -1)])
    if latest_mkt:
        print(f"\nSH000300 市场数据 ({latest_mkt['date']}):")
        print(f"  spot={latest_mkt['spot']:.2f}")
        print(f"  vol: 1M={latest_mkt['vol_1m']*100:.1f}% 3M={latest_mkt['vol_3m']*100:.1f}% "
              f"6M={latest_mkt['vol_6m']*100:.1f}% 12M={latest_mkt['vol_12m']*100:.1f}%")

    # 曲面
    vs = db["option_vol_surfaces"].find_one({"underlying": "SH000300", "tenor_grid": {"$exists": True}},
                                             sort=[("date", -1)])
    if vs:
        print(f"\n波动率曲面 ({vs['date']}):")
        print(f"  Grid: {len(vs['moneyness_grid'])}x{len(vs['tenor_grid'])}")
        for i, t in enumerate(vs["tenor_grid"]):
            vols = [f"{v*100:.1f}%" for v in vs["vol_grid"][i]]
            print(f"  T={t:.3f}y: {vols}")

    # 集合统计
    print(f"\n集合统计:")
    for col in ["asset_prices", "option_market_data", "option_contracts",
                 "option_iv_data", "option_vol_surfaces", "option_products"]:
        cnt = db[col].count_documents({})
        print(f"  {col:30s}: {cnt:>8,}")

    client.close()
    print("\n修复完成!")


if __name__ == "__main__":
    main()
