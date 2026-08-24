"""
隐含波动率计算器 —— Newton-Raphson 方法

用法:
    from vol.iv_calculator import implied_vol
    iv = implied_vol(market_price=5.0, S=100, K=100, tau=0.5, r=0.03, q=0.0, option_type='call')
"""

import numpy as np
from scipy.stats import norm


def _bs_price(S: float, K: float, tau: float, vol: float,
              r: float, q: float, option_type: str) -> float:
    """BS 公式价格"""
    if tau <= 1e-10:
        if option_type == 'call':
            return max(S - K, 0)
        else:
            return max(K - S, 0)

    sqrt_tau = np.sqrt(tau)
    d1 = (np.log(S / K) + (r - q + 0.5 * vol ** 2) * tau) / (vol * sqrt_tau)
    d2 = d1 - vol * sqrt_tau

    Dr = np.exp(-r * tau)
    Dq = np.exp(-q * tau)
    F = S * np.exp((r - q) * tau)

    if option_type == 'call':
        return Dr * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        return Dr * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def _vega(S: float, K: float, tau: float, vol: float,
          r: float, q: float) -> float:
    """BS Vega（用于 Newton 迭代梯度）"""
    if tau <= 1e-10:
        return 0.0
    sqrt_tau = np.sqrt(tau)
    d1 = (np.log(S / K) + (r - q + 0.5 * vol ** 2) * tau) / (vol * sqrt_tau)
    return S * np.exp(-q * tau) * norm.pdf(d1) * sqrt_tau


def implied_vol(market_price: float, S: float, K: float,
                tau: float, r: float, q: float = 0.0,
                option_type: str = 'call',
                max_iter: int = 100, tol: float = 1e-8) -> float:
    """Newton-Raphson 计算隐含波动率

    Args:
        market_price: 期权市场价格
        S: 标的价格
        K: 行权价
        tau: 剩余期限（年）
        r: 无风险利率
        q: 分红率
        option_type: 'call' or 'put'
        max_iter: 最大迭代次数
        tol: 收敛精度

    Returns:
        float: 隐含波动率

    Raises:
        RuntimeError: 迭代不收敛
        ValueError: 价格超出无套利边界
    """
    # 基本边界检查
    intrinsic = max(S - K, 0) if option_type == 'call' else max(K - S, 0)
    if market_price < intrinsic:
        raise ValueError(
            f"期权价格 {market_price:.4f} 低于内在价值 {intrinsic:.4f}"
        )

    # 初始猜测（Brenner-Subrahmanyam 近似）
    # σ ≈ sqrt(2π/T) * (market_price / S)  [ATM]
    vol = np.sqrt(2 * np.pi / tau) * market_price / S
    vol = np.clip(vol, 0.01, 2.0)  # 限制在合理范围

    for i in range(max_iter):
        price = _bs_price(S, K, tau, vol, r, q, option_type)
        diff = price - market_price

        if abs(diff) < tol:
            return vol

        vega = _vega(S, K, tau, vol, r, q)
        if abs(vega) < 1e-12:
            break  # Vega 极小，期权接近到期或极度虚值

        # Newton 步
        delta_vol = diff / vega

        # 阻尼：限制单步变化
        delta_vol = np.clip(delta_vol, -0.5, 0.5)

        vol = vol - delta_vol
        vol = np.clip(vol, 0.001, 5.0)  # 安全边界

    raise RuntimeError(
        f"隐含波动率迭代不收敛 (price={market_price:.4f}, "
        f"S={S}, K={K}, tau={tau:.4f}, last_vol={vol:.4f}, diff={diff:.6f})"
    )
