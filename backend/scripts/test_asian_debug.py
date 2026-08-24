# -*- coding: utf-8 -*-
"""诊断 Asian 定价器"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.config.database import Database

async def main():
    Database.connect()
    db = Database.get_database()

    from app.services.option_pricing_service import OptionPricingService
    svc = OptionPricingService()

    # 加载 ASN_001 产品
    products = await svc._load_product_records(["ASN_001"])
    if not products:
        print("ASN_001 not found")
        return

    p = products[0]
    print(f"Product: {p.id}")
    print(f"  type={p.type}, underlying={p.underlying}")
    print(f"  principal={p.principal:,.0f}")
    print(f"  issue_date={p.issue_date}, maturity_date={p.maturity_date}")
    print(f"  params={p.params}")

    # 手动定价
    from app.options.core import AsianOptionPricer, AsianParams
    from datetime import date

    today = date(2026, 6, 22)
    tau = (p.maturity_date - today).days / 365.0
    print(f"\n  tau={tau:.4f} years ({(p.maturity_date - today).days} days)")

    market = await svc.get_market_data_records("2026-06-22")
    md = market.get(p.underlying)
    if md:
        spot = md.spot
        vol = md.vols.get("12M", 0.16)
        rate = md.rates.get("1y", 0.02)
        div = md.dividend_yield
        print(f"  spot={spot:.2f}, vol={vol:.4f}, rate={rate:.4f}, div={div:.4f}")

        spot_ref = p.params.get("spot_ref", spot)
        strike = p.params.get("strike", spot_ref)
        print(f"  spot_ref={spot_ref:.2f}, strike={strike:.2f}")

        ap = AsianParams(
            spot_ref=spot_ref, strike=strike, tau=tau,
            obs_freq=p.params.get("obs_freq", "daily"),
            avg_type=p.params.get("avg_type", "arithmetic"),
            vol=vol, r=rate, q=div,
        )
        pricer = AsianOptionPricer(n_paths=50000, seed=42)
        result = pricer.price(ap, return_details=True)
        print(f"\n  Asian MC price={result['price']:.4f} ({result['method']})")

        # 几何近似
        price_geo = pricer._geometric_asian(spot_ref, strike, tau, vol, rate, div)
        print(f"  Geometric approx={price_geo:.4f}")

        # 检查 dispatcher 逻辑
        print(f"\n  === Dispatcher 逻辑 ===")
        scale = p.principal / spot_ref if spot_ref else 1
        print(f"  scale = principal/spot_ref = {p.principal:,.0f}/{spot_ref:.2f} = {scale:.4f}")
        print(f"  price_total = price * scale = {result['price']:.4f} * {scale:.4f} = {result['price']*scale:.2f}")

    Database.close()

asyncio.run(main())
