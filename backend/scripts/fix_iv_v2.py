# -*- coding: utf-8 -*-
"""修复IV计算 + 构建波动率曲面 v2
   使用 50ETF + 300ETF 全部活跃期权合约
"""
import sys, os, time, math
from datetime import datetime, timedelta
import numpy as np
import tushare as ts
from pymongo import MongoClient, UpdateOne

TOKEN = "286fd29627e9ce67299c961761cc79b1aad18937fc58373f87793775"
BATCH_SIZE = 1000


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
    return vol


def fmt_date(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def build_surface(iv_records, spot):
    if not iv_records:
        return None
    m_grid = [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]
    t_grid = [1/12, 2/12, 3/12, 6/12, 1.0]
    buckets = {}
    for rec in iv_records:
        t, mn, iv = rec["tenor"], rec["moneyness"], rec["iv"]
        if iv < 0.05 or iv > 2.0 or mn < 0.7 or mn > 1.4:
            continue
        best_t = min(t_grid, key=lambda bt: abs(bt - t))
        if abs(best_t - t) > 0.12:
            continue
        buckets.setdefault(best_t, []).append((mn, iv))
    if len(buckets) < 2:
        return None
    vol_grid, used_t = [], []
    for t in t_grid:
        if t not in buckets:
            continue
        pts = sorted(buckets[t], key=lambda p: p[0])
        used_t.append(t)
        row = []
        for m in m_grid:
            if m <= pts[0][0]:
                row.append(round(pts[0][1], 4))
            elif m >= pts[-1][0]:
                row.append(round(pts[-1][1], 4))
            else:
                for i in range(len(pts)-1):
                    if pts[i][0] <= m <= pts[i+1][0]:
                        w = (m - pts[i][0]) / (pts[i+1][0] - pts[i][0])
                        row.append(round(pts[i][1] + w*(pts[i+1][1]-pts[i][1]), 4))
                        break
                else:
                    row.append(round(pts[-1][1], 4))
        vol_grid.append(row)
    if len(used_t) < 2:
        return None
    return {"moneyness_grid": m_grid, "tenor_grid": used_t, "vol_grid": vol_grid}


def main():
    pro = ts.pro_api(TOKEN)
    client = MongoClient("mongodb://localhost:27017")
    db = client["asset_allocation"]

    end_str = datetime.now().strftime("%Y%m%d")
    start_str = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")

    # 1. ETF prices
    print("[1] Download ETF daily prices...")
    etf_prices = {}
    for etf in ["510300.SH", "510050.SH"]:
        time.sleep(0.3)
        df = pro.fund_daily(ts_code=etf, start_date=start_str, end_date=end_str)
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                d = fmt_date(r["trade_date"])
                etf_prices.setdefault(d, {})[etf] = float(r["close"])
            print(f"  {etf}: {len(df)} days, latest={df.iloc[0]['close']:.4f}")

    # 2. SHIBOR
    print("\n[2] Download SHIBOR...")
    df_shibor = pro.shibor(start_date=start_str, end_date=end_str)
    rates = {}
    if df_shibor is not None and not df_shibor.empty:
        for _, r in df_shibor.iterrows():
            rates[r["date"]] = float(r["1y"]) / 100
        print(f"  {len(df_shibor)} days")

    # 3. Get ALL active SSE option contracts (50ETF + 300ETF)
    print("\n[3] Get active option contracts...")
    df_all = pro.opt_basic(exchange="SSE",
                           fields="ts_code,name,call_put,list_date,delist_date,exercise_price,s_month")
    active = df_all[df_all["delist_date"] >= end_str].copy()
    print(f"  Total active SSE contracts: {len(active)}")

    # Show some contract code samples
    if len(active) > 0:
        sample_codes = active["ts_code"].head(5).tolist()
        print(f"  Sample codes: {sample_codes}")
        # Filter 50ETF and 300ETF options
        # 50ETF options: name contains "50ETF"
        # 300ETF options: name contains "300ETF"
        mask_50 = active["name"].str.contains("50ETF", na=False)
        mask_300 = active["name"].str.contains("300ETF", na=False)
        contracts_50 = active[mask_50].sort_values("delist_date").head(25)
        contracts_300 = active[mask_300].sort_values("delist_date").head(25)
        print(f"  50ETF contracts: {len(contracts_50)}")
        print(f"  300ETF contracts: {len(contracts_300)}")
        selected = pd.concat([contracts_50, contracts_300]).drop_duplicates("ts_code").head(40)
        print(f"  Selected for IV calc: {len(selected)}")
    else:
        selected = pd.DataFrame()

    # 4. Calculate IV for selected contracts
    print("\n[4] Calculate implied volatility...")
    iv_by_date = {}
    iv_ops = []
    etf_map = {"50ETF": "510050.SH", "300ETF": "510300.SH"}

    for _, c in selected.iterrows():
        code = c["ts_code"]
        cp = c["call_put"]
        K = float(c["exercise_price"])
        delist = c["delist_date"]
        name = c["name"]
        time.sleep(0.3)

        # Determine ETF
        etf_code = "510300.SH"  # default
        for key, val in etf_map.items():
            if key in name:
                etf_code = val
                break

        try:
            df_opt = pro.opt_daily(ts_code=code, start_date=start_str, end_date=end_str)
            if df_opt is None or df_opt.empty:
                continue

            cnt = 0
            for _, r in df_opt.iterrows():
                d = fmt_date(r["trade_date"])
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
                rate = rates.get(r["trade_date"], 0.02)
                iv = calc_iv(settle, spot, K, T, rate, 0.02, cp)
                if iv and 0.05 < iv < 2.0:
                    mn = round(K / spot, 4)
                    rec = {"ts_code": code, "date": d, "call_put": cp,
                           "strike": K, "settle": settle, "spot": spot,
                           "moneyness": mn, "tenor": round(T, 4),
                           "iv": round(iv, 4), "rate": rate, "etf": etf_code}
                    iv_ops.append(UpdateOne({"ts_code": code, "date": d},
                                            {"$set": rec}, upsert=True))
                    iv_by_date.setdefault(d, []).append(rec)
                    cnt += 1
            if cnt > 0:
                print(f"    {code} ({name[:20]}): {cnt} IV points")
        except Exception as e:
            print(f"    {code}: ERROR: {e}")

    if iv_ops:
        for i in range(0, len(iv_ops), BATCH_SIZE):
            db["option_iv_data"].bulk_write(iv_ops[i:i+BATCH_SIZE], ordered=False)
    total_iv = sum(len(v) for v in iv_by_date.values())
    print(f"\n  Total: {total_iv} IV records across {len(iv_by_date)} days")

    # 5. Update market_data volatility
    print("\n[5] Update option_market_data volatility...")
    mkt_ops = []
    for d, recs in iv_by_date.items():
        t_buckets = {0.083: [], 0.25: [], 0.5: [], 1.0: []}
        for rec in recs:
            best_t = min(t_buckets.keys(), key=lambda bt: abs(bt - rec["tenor"]))
            if abs(best_t - rec["tenor"]) < 0.15:
                t_buckets[best_t].append(rec["iv"])
        update = {"data_source": "tushare_iv"}
        if t_buckets[0.083]: update["vol_1m"] = round(float(np.median(t_buckets[0.083])), 4)
        if t_buckets[0.25]: update["vol_3m"] = round(float(np.median(t_buckets[0.25])), 4)
        if t_buckets[0.5]: update["vol_6m"] = round(float(np.median(t_buckets[0.5])), 4)
        if t_buckets[1.0]: update["vol_12m"] = round(float(np.median(t_buckets[1.0])), 4)
        # Update for both SH000300 and SH000016 (both track similar underlyings)
        for underlying in ["SH000300", "SH000016"]:
            mkt_ops.append(UpdateOne({"date": d, "underlying": underlying},
                                     {"$set": update}, upsert=True))
    if mkt_ops:
        db["option_market_data"].bulk_write(mkt_ops, ordered=False)
    print(f"  Updated {len(mkt_ops)} market data records")

    # 6. Build vol surfaces
    print("\n[6] Build volatility surfaces...")
    sorted_dates = sorted(iv_by_date.keys(), reverse=True)
    surf_count = 0
    for d in sorted_dates[:15]:
        recs = iv_by_date[d]
        spot = recs[0]["spot"] if recs else 0
        surf = build_surface(recs, spot)
        if surf:
            db["option_vol_surfaces"].update_one(
                {"underlying": "SH000300", "date": d},
                {"$set": {"underlying": "SH000300", "date": d,
                           "spot": spot, **surf, "updated_at": datetime.now()}},
                upsert=True)
            surf_count += 1
            if surf_count == 1:
                print(f"\n  Latest surface {d} (spot={spot:.4f}):")
                print(f"    Moneyness: {surf['moneyness_grid']}")
                print(f"    Tenor(yr): {[round(t,3) for t in surf['tenor_grid']]}")
                for i, t in enumerate(surf["tenor_grid"]):
                    vols = [f"{v*100:.1f}%" for v in surf["vol_grid"][i]]
                    print(f"    T={t:.3f}y: {vols}")
    print(f"\n  Built {surf_count} surface snapshots")

    # 7. Final verification
    print("\n" + "="*60)
    print("=== Final Data Summary ===")
    print("="*60)

    latest_mkt = db["option_market_data"].find_one({"underlying": "SH000300"}, sort=[("date", -1)])
    if latest_mkt:
        print(f"\nSH000300 Market Data ({latest_mkt['date']}):")
        print(f"  spot={latest_mkt['spot']:.2f}")
        print(f"  vol: 1M={latest_mkt['vol_1m']*100:.1f}% 3M={latest_mkt['vol_3m']*100:.1f}% "
              f"6M={latest_mkt['vol_6m']*100:.1f}% 12M={latest_mkt['vol_12m']*100:.1f}%")
        print(f"  rate_1y={latest_mkt['rate_1y']*100:.2f}%")

    vs = db["option_vol_surfaces"].find_one({"underlying": "SH000300"}, sort=[("date", -1)])
    if vs and "date" in vs:
        print(f"\nSH000300 Vol Surface ({vs['date']}):")
        print(f"  Grid: {len(vs['moneyness_grid'])}x{len(vs['tenor_grid'])}")
    else:
        print(f"\n  Vol surface: not yet available (insufficient IV data for grid)")

    print(f"\nCollections:")
    for col in ["asset_prices", "option_market_data", "option_contracts",
                 "option_iv_data", "option_vol_surfaces", "option_products"]:
        cnt = db[col].count_documents({})
        print(f"  {col:30s}: {cnt:>8,}")

    client.close()
    print("\nDone!")


if __name__ == "__main__":
    import pandas as pd
    main()
