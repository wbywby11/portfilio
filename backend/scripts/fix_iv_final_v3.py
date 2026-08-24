# -*- coding: utf-8 -*-
"""最终修复: 选多样化合约 + 正确ETF价格 + 构建波动率曲面"""
from pymongo import MongoClient, UpdateOne
import numpy as np
from datetime import datetime
import tushare as ts
import time, math, pandas as pd

TOKEN = "286fd29627e9ce67299c961761cc79b1aad18937fc58373f87793775"
BATCH = 1000


def calc_iv(opt_price, S, K, T, r, q, cp="C"):
    from scipy.stats import norm
    if opt_price <= 0 or T <= 0 or K <= 0 or S <= 0:
        return None
    intrinsic = max(S - K, 0) if cp == "C" else max(K - S, 0)
    if opt_price < intrinsic * 0.85:
        return None
    vol = 0.20
    for _ in range(60):
        sT = math.sqrt(T)
        d1 = (math.log(S / K) + (r - q + 0.5 * vol**2) * T) / (vol * sT)
        d2 = d1 - vol * sT
        if cp == "C":
            px = math.exp(-r*T) * (S*math.exp((r-q)*T)*norm.cdf(d1) - K*norm.cdf(d2))
        else:
            px = math.exp(-r*T) * (K*norm.cdf(-d2) - S*math.exp((r-q)*T)*norm.cdf(-d1))
        diff = px - opt_price
        if abs(diff) < 1e-6:
            return vol if 0.05 < vol < 1.5 else None
        vega = S * math.exp(-q*T) * norm.pdf(d1) * sT
        if vega < 1e-10:
            break
        step = max(-0.3, min(0.3, diff / vega))
        vol = max(0.01, min(3.0, vol - step))
    return vol if 0.05 < vol < 1.5 else None


def build_surface(iv_records):
    clean = [(r["moneyness"], r["tenor"], r["iv"]) for r in iv_records
             if 0.08 < r["iv"] < 1.2 and 0.75 < r["moneyness"] < 1.30 and r["tenor"] > 0.02]
    if len(clean) < 20:
        return None
    t_targets = [0.08, 0.17, 0.25, 0.50, 0.75, 1.00]
    buckets = {}
    for mn, t, iv in clean:
        best_t = min(t_targets, key=lambda bt: abs(bt - t))
        if abs(best_t - t) > 0.12:
            continue
        buckets.setdefault(best_t, []).append((mn, iv))
    valid_buckets = {t: pts for t, pts in buckets.items() if len(pts) >= 3}
    if len(valid_buckets) < 2:
        return None
    m_grid = [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]
    vol_grid, used_t = [], []
    for t in t_targets:
        if t not in valid_buckets:
            continue
        pts = sorted(valid_buckets[t], key=lambda p: p[0])
        used_t.append(t)
        row = []
        for m in m_grid:
            dists = [(abs(p[0]-m), p[1]) for p in pts]
            dists.sort()
            if dists[0][0] < 0.04:
                row.append(round(dists[0][1], 4))
            else:
                ws = [1.0/max(d, 0.001) for d, _ in dists[:5]]
                tw = sum(ws)
                val = sum(w*v for w, (_, v) in zip(ws, dists[:5])) / tw
                row.append(round(val, 4))
        vol_grid.append(row)
    if len(used_t) < 2:
        return None
    return {"moneyness_grid": m_grid, "tenor_grid": used_t, "vol_grid": vol_grid}


def main():
    pro = ts.pro_api(TOKEN)
    client = MongoClient("mongodb://localhost:27017")
    db = client["asset_allocation"]
    end_str = datetime.now().strftime("%Y%m%d")
    start_str = "20260401"

    # 1. ETF prices
    print("[1] ETF prices...")
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
        print(f"  {len(df_shibor)} days, latest rate={list(rates.values())[-1]*100:.2f}%")

    # 3. 合约 - 按到期月分层选取
    print("\n[3] 合约选取 (分层)...")
    df_all = pro.opt_basic(exchange="SSE",
                           fields="ts_code,name,call_put,delist_date,exercise_price")
    active = df_all[df_all["delist_date"] >= end_str].copy()
    print(f"  Active SSE contracts: {len(active)}")

    # 分50ETF和300ETF
    mask_50 = active["name"].str.contains("50ETF", na=False)
    mask_300 = active["name"].str.contains("300ETF", na=False)
    contracts_50 = active[mask_50].copy()
    contracts_300 = active[mask_300].copy()
    print(f"  50ETF: {len(contracts_50)}, 300ETF: {len(contracts_300)}")

    # 从每个到期月中选取 Call+Put 各2个 (确保tenor多样)
    selected = pd.DataFrame()
    for subset, etf_code in [(contracts_50, "510050.SH"), (contracts_300, "510300.SH")]:
        if subset.empty:
            continue
        subset = subset.copy()
        subset["s_month"] = subset["delist_date"].str[:6]
        months = sorted(subset["s_month"].unique())
        for m in months[:6]:  # 最多6个到期月
            m_contracts = subset[subset["s_month"] == m]
            for cp in ["C", "P"]:
                cp_contracts = m_contracts[m_contracts["call_put"] == cp]
                if not cp_contracts.empty:
                    # 选最接近平值的2个
                    sample = cp_contracts.head(2)
                    selected = pd.concat([selected, sample])
    selected = selected.drop_duplicates("ts_code")
    print(f"  Selected: {len(selected)} contracts (diverse tenors)")

    # Show tenor distribution
    for _, c in selected.head(10).iterrows():
        delist_dt = datetime.strptime(c["delist_date"], "%Y%m%d")
        T = (delist_dt - datetime.now()).days / 365.0
        print(f"    {c['ts_code']} {c['call_put']} K={c['exercise_price']:.2f} "
              f"delist={c['delist_date']} T={T:.3f}y")

    # 4. 计算IV
    print("\n[4] 计算IV...")
    # 清除旧数据
    db["option_iv_data"].delete_many({})
    print(f"  Cleared old IV data")

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

        etf_code = "510300.SH"
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
                if T <= 0.01 or T > 2.0:
                    continue
                rate = rates.get(d, 0.015)
                iv = calc_iv(settle, spot, K, T, rate, 0.02, cp)
                if iv:
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
                print(f"    {code} ({name[:15]}..): {cnt} pts, ETF={etf_code}")
        except Exception as e:
            print(f"    {code}: ERROR: {e}")

    if iv_ops:
        for i in range(0, len(iv_ops), BATCH):
            db["option_iv_data"].bulk_write(iv_ops[i:i+BATCH], ordered=False)
    total_iv = sum(len(v) for v in iv_by_date.values())
    print(f"\n  Total: {total_iv} IV records, {len(iv_by_date)} days")

    # 诊断: 看最近一天的数据
    if iv_by_date:
        d = sorted(iv_by_date.keys())[-1]
        recs = iv_by_date[d]
        print(f"\n  诊断 ({d}, {len(recs)} records):")
        mns = [r["moneyness"] for r in recs]
        ts_ = [r["tenor"] for r in recs]
        ivs = [r["iv"] for r in recs]
        print(f"    moneyness: {min(mns):.3f} ~ {max(mns):.3f}")
        print(f"    tenor: {min(ts_):.3f}y ~ {max(ts_):.3f}y")
        print(f"    iv: {min(ivs)*100:.1f}% ~ {max(ivs)*100:.1f}%")

    # 5. 更新市场数据
    print("\n[5] 更新市场数据波动率...")
    mkt_ops = []
    for d, recs in iv_by_date.items():
        t_buckets = {0.08: [], 0.25: [], 0.50: [], 1.00: []}
        for rec in recs:
            best_t = min(t_buckets.keys(), key=lambda bt: abs(bt - rec["tenor"]))
            if abs(best_t - rec["tenor"]) < 0.15:
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
            if surf_count <= 3:
                print(f"\n  Surface {d} (spot={spot:.4f}):")
                print(f"    Moneyness: {surf['moneyness_grid']}")
                print(f"    Tenor: {[round(t,3) for t in surf['tenor_grid']]}")
                for i, t in enumerate(surf["tenor_grid"]):
                    vols = [f"{v*100:.1f}%" for v in surf["vol_grid"][i]]
                    print(f"    T={t:.3f}y: {vols}")
    print(f"\n  Built {surf_count} surfaces total")

    # 7. 验证
    print("\n" + "="*60)
    print("=== 最终验证 ===")
    print("="*60)

    for col in ["asset_prices", "option_market_data", "option_contracts",
                 "option_iv_data", "option_vol_surfaces", "option_products"]:
        cnt = db[col].count_documents({})
        print(f"  {col:30s}: {cnt:>8,}")

    # 显示最新市场数据
    latest = db["option_market_data"].find_one({"underlying": "SH000300"}, sort=[("date", -1)])
    if latest:
        print(f"\nSH000300 ({latest['date']}):")
        print(f"  spot={latest['spot']:.2f}  vol_1m={latest['vol_1m']*100:.1f}%"
              f"  vol_3m={latest['vol_3m']*100:.1f}%  vol_12m={latest['vol_12m']*100:.1f}%")

    client.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
