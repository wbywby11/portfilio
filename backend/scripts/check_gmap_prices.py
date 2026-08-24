# -*- coding: utf-8 -*-
"""检查 GMAP 10 品种在系统 DB 中的价格与原型 gmap_adj 数据是否一致。

GCMI 46 商品此前已验证一致（来自 gcmi_adj），但 GMAP 含 IC/IF/IM/T/TF
（股指/国债期货），原型从 gmap_adj 目录加载——需确认导入时用的是同源数据。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.database import Database  # noqa: E402

PROTO_ROOT = Path("d:/project/portfilio/gmsi2_replication")
GMAP_ASSETS = ["AU", "CU", "FG", "I", "IC", "IF", "IM", "M", "T", "TF"]


async def main() -> None:
    Database.connect()
    db = Database.db

    # 找到行情集合名
    cols = await db.list_collection_names()
    cand = [c for c in cols if any(k in c for k in ("price", "market", "daily", "quote"))]
    print("候选集合:", cand)

    # 探测文档结构
    sample = await db["asset_prices"].find_one()
    if sample:
        print("asset_prices 文档字段:", {k: repr(v)[:60] for k, v in sample.items() if k != "_id"})

    for code in GMAP_ASSETS:
        f = PROTO_ROOT / "data" / "gmap_adj" / f"{code}.csv"
        if not f.exists():
            f2 = list((PROTO_ROOT / "data" / "gmap_adj").glob(f"{code}*.csv"))
            f = f2[0] if f2 else None
        if f is None or not f.exists():
            print(f"{code}: 原型 gmap_adj 无文件")
            continue
        proto = pd.read_csv(f)
        proto = proto.set_index(pd.to_datetime(proto["trade_date"]))["settle"].sort_index()

        # 系统 DB：尝试几个可能的集合与字段
        sys_ser = None
        for cname in cand:
            doc = await db[cname].find_one({"code": code}) \
                or await db[cname].find_one({"thscode": code}) \
                or await db[cname].find_one({"asset_code": code}) \
                or await db[cname].find_one({"symbol": code})
            if doc is None:
                continue
            key = next(k for k in ("code", "thscode", "asset_code", "symbol") if k in doc)
            rows = db[cname].find({key: code})
            recs = []
            async for r in rows:
                d = r.get("trade_date") or r.get("date") or r.get("dt")
                px = r.get("close") or r.get("settle") or r.get("price") or r.get("settle_price")
                if d is not None and px is not None:
                    recs.append((pd.Timestamp(d), float(px)))
            if recs:
                sys_ser = pd.Series(dict(recs)).sort_index()
                print(f"{code}: 系统集合={cname}, 行数={len(sys_ser)}, 键={key}")
                break
        if sys_ser is None:
            print(f"{code}: 系统 DB 未找到行情")
            continue

        common = proto.index.intersection(sys_ser.index)
        diff = (proto.loc[common] - sys_ser.loc[common]).abs()
        rel = (diff / proto.loc[common].abs()).max()
        print(f"  公共日期={len(common)}  max|Δ|={diff.max():.6f}  max相对差={rel:.2%}"
              f"  原型范围={proto.index.min().date()}~{proto.index.max().date()}"
              f"  系统范围={sys_ser.index.min().date()}~{sys_ser.index.max().date()}")
        if diff.max() > 1e-6:
            bad = diff[diff > 1e-6].sort_values(ascending=False).head(5)
            for dt in bad.index:
                print(f"    {dt.date()}: proto={proto[dt]:.4f} sys={sys_ser[dt]:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
