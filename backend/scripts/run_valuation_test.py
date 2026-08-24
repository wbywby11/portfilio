# -*- coding: utf-8 -*-
"""用真实市场数据运行估值验证"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.config.database import Database

async def main():
    Database.connect()
    db = Database.get_database()

    from app.services.option_pricing_service import OptionPricingService
    svc = OptionPricingService()

    # 用最新有数据的日期
    date_str = "2026-06-22"
    print(f"=== 估值验证 ({date_str}) ===\n")

    # 1. 加载
    products = await svc._load_product_records()
    print(f"[1] Products: {len(products)}")
    for p in products:
        print(f"  {p.id:12s} {p.type:16s} {p.underlying:10s} principal={p.principal:>12,.0f}")

    market = await svc.get_market_data_records(date_str)
    print(f"\n[2] Market data: {len(market)} underlyings")
    for code, md in market.items():
        print(f"  {code}: spot={md.spot:.2f} vol_1y={md.vols.get('12M',0)*100:.1f}% rate_1y={md.rates.get('1y',0)*100:.2f}%")

    vol_surfaces = await svc._load_vol_surfaces(market)
    print(f"\n[3] Vol surfaces: {len(vol_surfaces)}")

    # 2. 估值
    print(f"\n[4] Running valuation...")
    result = await svc.run_valuation(date_str=date_str, skip_lifecycle=True)

    if result.get("error"):
        print(f"  ERROR: {result['error']}")
    else:
        print(f"  Version: {result.get('version')}")
        print(f"  Total: {result['total_products']}, Success: {result['success_count']}, Error: {result['error_count']}")
        print(f"  Total Value: {result['total_value']:,.2f}")
        print(f"\n  Per-product:")
        for p in result.get("products", []):
            err = f" ERR:{p['error'][:30]}" if p.get("error") else ""
            pct = (p['price_total'] / p['principal'] - 1) * 100 if p['principal'] > 0 else 0
            print(f"    {p['product_id']:12s} {p['type']:16s} "
                  f"price={p['price_total']:>14,.2f} ({pct:+.2f}%) "
                  f"method={p['method']:25s}{err}")

    Database.close()
    print("\n=== 验证完成 ===")

asyncio.run(main())
