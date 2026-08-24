# -*- coding: utf-8 -*-
"""端到端冒烟测试：验证估值引擎能正确加载种子数据并运行"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.config.database import Database

async def main():
    # 1. 连接数据库
    Database.connect()
    db = Database.get_database()
    print("=== Smoke Test ===")
    print(f"Connected to: {db.name}")

    # 2. 验证产品加载
    from app.services.option_pricing_service import OptionPricingService
    svc = OptionPricingService()

    products = await svc._load_product_records()
    print(f"\n[1] Products loaded: {len(products)}")
    for p in products:
        print(f"  {p.id:12s} type={p.type:16s} underlying={p.underlying:10s} principal={p.principal:,.0f}")

    # 3. 验证市场数据加载（含桥接）
    from datetime import date
    today_str = date.today().isoformat()
    market_data = await svc.get_market_data_records(today_str)
    print(f"\n[2] Market data for {today_str}: {len(market_data)} underlyings")
    for code, md in market_data.items():
        print(f"  {code}: spot={md.spot:.2f} vol_1y={md.vols.get('12M', 'N/A')}")

    # 4. 验证波动率曲面加载
    vol_surfaces = await svc._load_vol_surfaces(market_data)
    print(f"\n[3] Vol surfaces loaded: {len(vol_surfaces)}")
    for code, vs in vol_surfaces.items():
        print(f"  {code}: moneyness={len(vs.moneyness)}pts tenor={len(vs.tenors)}pts")

    # 5. 运行估值（核心测试！）
    print(f"\n[4] Running valuation for {today_str}...")
    result = await svc.run_valuation(
        date_str=today_str,
        skip_lifecycle=True,  # 跳过生命周期以加速测试
    )

    if result.get("error"):
        print(f"  ERROR: {result['error']}")
    else:
        print(f"  Version: {result.get('version', '?')}")
        print(f"  Total: {result['total_products']}, Success: {result['success_count']}, Error: {result['error_count']}")
        print(f"  Total Value: {result['total_value']:,.2f}")
        print(f"\n  Per-product results:")
        for p in result.get("products", []):
            err = f" ERR:{p['error']}" if p.get("error") else ""
            print(f"    {p['product_id']:12s} type={p['type']:16s} "
                  f"price={p['price_total']:>14,.2f} method={p['method']:25s}{err}")

    # 6. 验证版本化
    versions = await svc.get_valuation_versions(today_str)
    print(f"\n[5] Versions for {today_str}: {len(versions)}")
    for v in versions:
        print(f"  v{v['version']}: {v['snapshot']['total_products']} products, "
              f"value={v['snapshot']['total_value']:,.2f}, final={v.get('is_final', False)}")

    # 7. 验证版本确认
    if versions:
        v1 = versions[-1]["version"]
        ok = await svc.confirm_valuation_version(today_str, v1, "smoke_test")
        print(f"\n[6] Confirm v{v1}: {'OK' if ok else 'FAIL'}")

    # 8. 验证趋势查询
    if products:
        pid = products[0].id
        trend = await svc.get_valuation_trend(pid)
        print(f"\n[7] Trend for {pid}: {len(trend)} data points")

    Database.close()
    print("\n=== Smoke Test PASSED ===")

asyncio.run(main())
