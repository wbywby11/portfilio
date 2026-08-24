# -*- coding: utf-8 -*-
"""诊断IV数据分布并修复波动率曲面构建"""
from pymongo import MongoClient
import numpy as np
from datetime import datetime

c = MongoClient("mongodb://localhost:27017")
db = c["asset_allocation"]

# 1. 查看最近一天的IV数据分布
latest_date = db["option_iv_data"].find_one(sort=[("date", -1)])["date"]
print(f"Latest IV date: {latest_date}")

recs = list(db["option_iv_data"].find({"date": latest_date}))
print(f"Records: {len(recs)}")

if recs:
    moneyness = [r["moneyness"] for r in recs]
    tenors = [r["tenor"] for r in recs]
    ivs = [r["iv"] for r in recs]

    print(f"\nMoneyness distribution:")
    print(f"  min={min(moneyness):.4f} max={max(moneyness):.4f} median={np.median(moneyness):.4f}")
    # Histogram
    bins = [0.7, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5]
    for i in range(len(bins)-1):
        cnt = sum(1 for m in moneyness if bins[i] <= m < bins[i+1])
        if cnt > 0:
            print(f"  [{bins[i]:.2f}, {bins[i+1]:.2f}): {cnt}")

    print(f"\nTenor distribution:")
    t_bins = [0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0]
    for i in range(len(t_bins)-1):
        cnt = sum(1 for t in tenors if t_bins[i] <= t < t_bins[i+1])
        if cnt > 0:
            print(f"  [{t_bins[i]:.3f}, {t_bins[i+1]:.3f}): {cnt}")

    print(f"\nIV range: {min(ivs)*100:.1f}% ~ {max(ivs)*100:.1f}%, median={np.median(ivs)*100:.1f}%")

    # Show sample records
    print(f"\nSample records:")
    for r in recs[:5]:
        print(f"  strike={r['strike']:.2f} spot={r['spot']:.4f} "
              f"moneyness={r['moneyness']:.4f} tenor={r['tenor']:.4f}y "
              f"iv={r['iv']*100:.1f}% cp={r['call_put']}")

# 2. Check all dates with IV data
all_dates = sorted(db["option_iv_data"].distinct("date"))
print(f"\nIV data dates: {len(all_dates)} days, from {all_dates[0]} to {all_dates[-1]}")

# Count records per date
for d in all_dates[-5:]:
    cnt = db["option_iv_data"].count_documents({"date": d})
    print(f"  {d}: {cnt} records")

# 3. Now build surface with relaxed grid
print("\n" + "="*60)
print("Building volatility surface with relaxed grid...")

def build_surface_relaxed(iv_records, spot):
    """更宽松的曲面构建"""
    if not iv_records:
        return None

    # 先看数据分布
    moneyness_vals = [r["moneyness"] for r in iv_records]
    tenor_vals = [r["tenor"] for r in iv_records]
    iv_vals = [r["iv"] for r in iv_records]

    # 过滤异常值
    clean = [(r["moneyness"], r["tenor"], r["iv"]) for r in iv_records
             if 0.05 < r["iv"] < 1.5 and 0.7 < r["moneyness"] < 1.4]
    if len(clean) < 10:
        return None

    # 自适应网格
    mn_min, mn_max = np.percentile([c[0] for c in clean], [10, 90])
    t_min, t_max = np.percentile([c[1] for c in clean], [10, 90])

    m_grid = [round(x, 2) for x in np.linspace(max(0.80, mn_min), min(1.20, mn_max), 7)]
    t_grid = [round(x, 3) for x in np.linspace(max(0.03, t_min), min(1.5, t_max), 5)]

    # 分桶
    buckets = {}
    for mn, t, iv in clean:
        best_t = min(t_grid, key=lambda bt: abs(bt - t))
        if abs(best_t - t) > 0.2:
            continue
        buckets.setdefault(best_t, []).append((mn, iv))

    if len(buckets) < 2:
        print(f"  Only {len(buckets)} tenor buckets, need >= 2")
        return None

    vol_grid = []
    used_t = []
    for t in t_grid:
        if t not in buckets:
            continue
        pts = sorted(buckets[t], key=lambda p: p[0])
        if len(pts) < 3:
            continue
        used_t.append(t)
        row = []
        for m in m_grid:
            # 找最近的点
            dists = [(abs(p[0]-m), p[1]) for p in pts]
            dists.sort()
            if dists[0][0] < 0.08:
                row.append(round(dists[0][1], 4))
            elif len(dists) >= 2:
                # 线性插值
                p1, p2 = sorted(pts, key=lambda p: p[0])[:2]
                if p1[0] != p2[0]:
                    w = (m - p1[0]) / (p2[0] - p1[0])
                    w = max(0, min(1, w))
                    row.append(round(p1[1] + w*(p2[1]-p1[1]), 4))
                else:
                    row.append(round(p1[1], 4))
            else:
                row.append(round(pts[0][1], 4))
        vol_grid.append(row)

    if len(used_t) < 2 or not vol_grid:
        return None

    return {"moneyness_grid": m_grid, "tenor_grid": used_t, "vol_grid": vol_grid}

# Try building for last 5 dates
surface_count = 0
for d in all_dates[-10:]:
    recs = list(db["option_iv_data"].find({"date": d}))
    spot = recs[0]["spot"] if recs else 0
    surf = build_surface_relaxed(recs, spot)
    if surf:
        db["option_vol_surfaces"].update_one(
            {"underlying": "SH000300", "date": d},
            {"$set": {"underlying": "SH000300", "date": d,
                       "spot": spot, **surf, "updated_at": datetime.now()}},
            upsert=True)
        surface_count += 1
        if surface_count <= 2:
            print(f"\n  Surface for {d} (spot={spot:.4f}):")
            print(f"    Moneyness: {surf['moneyness_grid']}")
            print(f"    Tenor(yr): {[round(t,3) for t in surf['tenor_grid']]}")
            for i, t in enumerate(surf["tenor_grid"]):
                vols = [f"{v*100:.1f}%" for v in surf["vol_grid"][i]]
                print(f"    T={t:.3f}y: {vols}")

print(f"\n  Total surfaces built: {surface_count}")

# Final check
vs_count = db["option_vol_surfaces"].count_documents({"underlying": "SH000300"})
print(f"\n  SH000300 vol surfaces in DB: {vs_count}")

# Show latest
vs = db["option_vol_surfaces"].find_one({"underlying": "SH000300"}, sort=[("date", -1)])
if vs and "tenor_grid" in vs:
    print(f"\n  Latest surface ({vs['date']}):")
    print(f"    Grid: {len(vs['moneyness_grid'])}x{len(vs['tenor_grid'])}")
    for i, t in enumerate(vs["tenor_grid"]):
        vols = [f"{v*100:.1f}%" for v in vs["vol_grid"][i]]
        print(f"    T={t:.3f}y: {vols}")

c.close()
print("\nDone!")
