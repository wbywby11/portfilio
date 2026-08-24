# -*- coding: utf-8 -*-
"""诊断 Asian 定价器"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from app.options.core import AsianOptionPricer, AsianParams

pricer = AsianOptionPricer(n_paths=50000, seed=42)

S0, K = 5060.0, 5060.0
vol, r, q, tau = 0.1925, 0.02, 0.02, 0.5

ap = AsianParams(spot_ref=S0, strike=K, tau=tau, obs_freq="daily",
                 avg_type="arithmetic", vol=vol, r=r, q=q)

result = pricer.price(ap, return_details=True)
print(f"Asian ATM Call: price={result['price']:.4f}")
print(f"  S0={S0}, K={K}, vol={vol}, r={r}, q={q}, tau={tau}")

# 理论值 (Turnbull-Wakeman)
import numpy as np
from scipy.stats import norm
sigma_eff = vol / np.sqrt(3)
sT_eff = sigma_eff * np.sqrt(tau)
d1 = (r - q) * np.sqrt(tau) / sT_eff + 0.5 * sT_eff
d2 = d1 - sT_eff
F = S0 * np.exp((r - q) * tau)
Dr = np.exp(-r * tau)
theory = Dr * (F * norm.cdf(d1) - K * norm.cdf(d2))
print(f"  Turnbull-Wakeman theory: {theory:.4f}")

# 不同参数测试
for strike_pct in [0.95, 1.0, 1.05]:
    K2 = S0 * strike_pct
    ap2 = AsianParams(spot_ref=S0, strike=K2, tau=tau, obs_freq="daily",
                      avg_type="arithmetic", vol=vol, r=r, q=q)
    r2 = pricer.price(ap2, return_details=True)
    print(f"  Strike={strike_pct:.2f}*S0={K2:.0f}: MC price={r2['price']:.2f}")

# 几何平均
ap3 = AsianParams(spot_ref=S0, strike=K, tau=tau, obs_freq="daily",
                  avg_type="geometric", vol=vol, r=r, q=q)
r3 = pricer.price(ap3, return_details=True)
print(f"  Geometric ATM: price={r3['price']:.4f}")

# 测试不同路径数
for n in [10000, 50000, 100000, 200000]:
    p = AsianOptionPricer(n_paths=n, seed=42)
    r = p.price(ap, return_details=True)
    print(f"  n_paths={n:>7d}: price={r['price']:.4f}")
