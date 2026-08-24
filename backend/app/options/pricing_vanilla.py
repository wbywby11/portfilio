"""
期权定价 —— 欧式香草与基础产品（P9 治理自 core.py 拆分）.

包含：折现/远期基础工具、市场参数与定价结果结构体、欧式香草
(OptionPricer)、欧式价差、欧式二元、单障碍、固定收益定价器。
方法体自 app/options/core.py 逐字平移，core.py 保留兼容再导出。
"""

import numpy as np
from scipy.stats import norm
from dataclasses import dataclass
from datetime import date


# ── 基础工具函数 ────────────────────────────────────────

def _discount(rate: float, tau: float) -> float:
    """折现因子 D(t,T) = exp(-r * tau)"""
    return np.exp(-rate * tau)


def _forward(spot: float, r: float, q: float, tau: float) -> float:
    """远期价格 F = S * exp((r-q) * tau)"""
    return spot * np.exp((r - q) * tau)


# ── 参数结构体 ──────────────────────────────────────────

@dataclass
class MarketParams:
    """市场参数（对标文档第5-6页符号定义）"""
    spot: float        # S  标的价格
    strike: float      # K  行权价
    tau: float         # τ 距离到期时间(年)
    vol: float         # σ 波动率
    r: float           # 无风险利率
    q: float = 0.0     # 分红率/融券率

    def validate(self):
        assert self.spot > 0, "spot must be positive"
        assert self.strike > 0, "strike must be positive"
        assert self.tau >= 0, "tau must be non-negative"
        assert self.vol > 0, "vol must be positive"


@dataclass
class PricingResult:
    """定价结果（价格 + 希腊字母）"""
    price: float
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0        # 1% vol change
    theta: float = 0.0       # 1 day time decay
    rho: float = 0.0         # 1% rate change

    def __repr__(self):
        return (f"PricingResult(price={self.price:.6f}, "
                f"delta={self.delta:.6f}, gamma={self.gamma:.6f}, "
                f"vega={self.vega:.6f}, theta={self.theta:.6f}, "
                f"rho={self.rho:.6f})")


# ══════════════════════════════════════════════════════
#  第一部分：欧式香草期权（文档第8-11页）
# ══════════════════════════════════════════════════════

class OptionPricer:
    """欧式期权定价器 —— 公式(2.) - (5.)"""

    @staticmethod
    def _d1_d2(params: MarketParams) -> tuple:
        """计算辅助变量 d1, d2  —— 公式(3.)(4.)"""
        S, K, tau, vol, r, q = params.spot, params.strike, params.tau, params.vol, params.r, params.q
        F = _forward(S, r, q, tau)
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        d1 = (np.log(F / K) + 0.5 * vol ** 2 * tau) / (vol * sqrt_tau)
        d2 = d1 - vol * sqrt_tau
        return d1, d2

    # ── 看涨/看跌定价 ──────────────────────────────

    def call(self, params: MarketParams) -> PricingResult:
        """看涨期权定价 —— 公式(2.)"""
        params.validate()
        S, K, tau, vol, r, q = params.spot, params.strike, params.tau, params.vol, params.r, params.q
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        d1, d2 = self._d1_d2(params)

        Dr = _discount(r, tau)
        Dq = _discount(q, tau)
        F = _forward(S, r, q, tau)

        # 公式(2.): V = Dr * [F*N(d1) - K*N(d2)]
        price = Dr * (F * norm.cdf(d1) - K * norm.cdf(d2))

        # Greeks（解析解）
        delta = Dq * norm.cdf(d1)                           # 看涨 Delta
        gamma = Dq * norm.pdf(d1) / (S * vol * sqrt_tau)    # Gamma
        vega = Dq * S * norm.pdf(d1) * sqrt_tau / 100       # Vega (1%变动)
        theta = (-Dq * S * norm.pdf(d1) * vol / (2 * sqrt_tau)
                 - r * K * Dr * norm.cdf(d2)
                 + q * S * Dq * norm.cdf(d1)) / 365          # Theta (1天)
        rho = tau * K * Dr * norm.cdf(d2) / 100             # Rho (1%变动)

        return PricingResult(price=price, delta=delta, gamma=gamma,
                             vega=vega, theta=theta, rho=rho)

    def put(self, params: MarketParams) -> PricingResult:
        """看跌期权定价 —— 公式(5.)"""
        params.validate()
        S, K, tau, vol, r, q = params.spot, params.strike, params.tau, params.vol, params.r, params.q
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        d1, d2 = self._d1_d2(params)

        Dr = _discount(r, tau)
        Dq = _discount(q, tau)
        F = _forward(S, r, q, tau)

        # 公式(5.): V = Dr * [K*N(-d2) - F*N(-d1)]
        price = Dr * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

        # Greeks（解析解）
        delta = Dq * (norm.cdf(d1) - 1)                        # 看跌 Delta
        gamma = Dq * norm.pdf(d1) / (S * vol * sqrt_tau)       # Gamma (同看涨)
        vega = Dq * S * norm.pdf(d1) * sqrt_tau / 100          # Vega (1%变动)
        theta = (-Dq * S * norm.pdf(d1) * vol / (2 * sqrt_tau)
                 + r * K * Dr * norm.cdf(-d2)
                 - q * S * Dq * norm.cdf(-d1)) / 365           # Theta (1天)
        rho = -tau * K * Dr * norm.cdf(-d2) / 100              # Rho (1%变动)

        return PricingResult(price=price, delta=delta, gamma=gamma,
                             vega=vega, theta=theta, rho=rho)

    # ── 数值希腊字母（差分法 Bump & Reprice） ──────────

    def _call_price(self, params: MarketParams) -> float:
        """内部定价函数，仅返回价格"""
        d1, d2 = self._d1_d2(params)
        Dr = _discount(params.r, params.tau)
        F = _forward(params.spot, params.r, params.q, params.tau)
        return Dr * (F * norm.cdf(d1) - params.strike * norm.cdf(d2))

    def numerical_greeks(self, params: MarketParams) -> PricingResult:
        """Bump & Reprice 差分法计算希腊字母（文档第8-9页 + 第23页）"""
        S = params.spot
        base_price = self._call_price(params)

        # Delta & Gamma: bump spot by 0.5%
        ds = S * 0.005
        p_up = MarketParams(S + ds, params.strike, params.tau, params.vol, params.r, params.q)
        p_dn = MarketParams(S - ds, params.strike, params.tau, params.vol, params.r, params.q)
        pu = self._call_price(p_up)
        pd = self._call_price(p_dn)
        delta = (pu - pd) / (2 * ds)
        gamma = (pu - 2 * base_price + pd) / (ds ** 2)

        # Vega: bump vol by 0.1%
        dv = params.vol * 0.001
        pu = self._call_price(MarketParams(S, params.strike, params.tau, params.vol + dv, params.r, params.q))
        pd = self._call_price(MarketParams(S, params.strike, params.tau, params.vol - dv, params.r, params.q))
        vega = (pu - pd) / (2 * dv * 100)  # per 1%

        # Theta: bump t by 0.5%
        dt = params.tau * 0.005
        pu = self._call_price(MarketParams(S, params.strike, params.tau + dt, params.vol, params.r, params.q))
        pd = self._call_price(MarketParams(S, params.strike, params.tau - dt, params.vol, params.r, params.q))
        theta = (pu - pd) / (2 * dt * 365)

        # Rho: bump r by 0.5%
        dr = params.r * 0.005
        pu = self._call_price(MarketParams(S, params.strike, params.tau, params.vol, params.r + dr, params.q))
        pd = self._call_price(MarketParams(S, params.strike, params.tau, params.vol, params.r - dr, params.q))
        rho = (pu - pd) / (2 * dr * 100)

        return PricingResult(price=base_price, delta=delta, gamma=gamma,
                             vega=vega, theta=theta, rho=rho)


# ══════════════════════════════════════════════════════
#  第二部分：欧式价差期权（文档第12-14页）
# ══════════════════════════════════════════════════════

class SpreadOptionPricer:
    """欧式价差期权定价 —— 公式(6.)(7.)"""

    def __init__(self):
        self.vanilla = OptionPricer()

    def call_spread(self, p: MarketParams, k_high: float) -> PricingResult:
        """
        看涨价差 —— 公式(6.)
        V = Call(K_low) - Call(K_high)
        买入低行权价看涨 + 卖出高行权价看涨
        """
        p_low = MarketParams(p.spot, p.strike, p.tau, p.vol, p.r, p.q)
        p_high = MarketParams(p.spot, k_high, p.tau, p.vol, p.r, p.q)

        r_low = self.vanilla.call(p_low)
        r_high = self.vanilla.call(p_high)

        return PricingResult(
            price=r_low.price - r_high.price,
            delta=r_low.delta - r_high.delta,
            gamma=r_low.gamma - r_high.gamma,
            vega=r_low.vega - r_high.vega,
            theta=r_low.theta - r_high.theta,
            rho=r_low.rho - r_high.rho,
        )

    def put_spread(self, p: MarketParams, k_high: float) -> PricingResult:
        """
        看跌价差 —— 公式(7.)
        V = Put(K_high) - Put(K_low)
        买入高行权价看跌 + 卖出低行权价看跌
        """
        p_low = MarketParams(p.spot, p.strike, p.tau, p.vol, p.r, p.q)
        p_high = MarketParams(p.spot, k_high, p.tau, p.vol, p.r, p.q)

        r_low = self.vanilla.put(p_low)
        r_high = self.vanilla.put(p_high)

        return PricingResult(
            price=r_high.price - r_low.price,
            delta=r_high.delta - r_low.delta,
            gamma=r_high.gamma - r_low.gamma,
            vega=r_high.vega - r_low.vega,
            theta=r_high.theta - r_low.theta,
            rho=r_high.rho - r_low.rho,
        )


# ══════════════════════════════════════════════════════
#  第三部分：欧式二元期权（文档第15-18页）
# ══════════════════════════════════════════════════════

class BinaryOptionPricer:
    """欧式二元期权定价 —— 公式(9.)(10.)"""

    @staticmethod
    def _d2(params: MarketParams) -> float:
        S, K, tau, vol, r, q = params.spot, params.strike, params.tau, params.vol, params.r, params.q
        F = _forward(S, r, q, tau)
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        return (np.log(F / K) - 0.5 * vol ** 2 * tau) / (vol * sqrt_tau)

    def call(self, params: MarketParams) -> float:
        """二元看涨期权 —— 公式(9.): VC = D(t,T) * N(d2)"""
        d2 = self._d2(params)
        return _discount(params.r, params.tau) * norm.cdf(d2)

    def put(self, params: MarketParams) -> float:
        """二元看跌期权 —— 公式(10.): VP = D(t,T) * [1 - N(d2)]"""
        d2 = self._d2(params)
        return _discount(params.r, params.tau) * (1 - norm.cdf(d2))


# ══════════════════════════════════════════════════════
#  第四部分：障碍期权（单鲨）—— 文档第18-22页
# ══════════════════════════════════════════════════════

class BarrierOptionPricer:
    """单鲨期权（单向障碍）定价 —— Reiner-Rubinstein (1991) 解析解

    纯 numpy/scipy 实现，无外部依赖。

    支持 4 种类型：
    - Up-and-Out Call / Put   (向上敲出)
    - Down-and-Out Call / Put (向下敲出)

    辅助变量：
        μ = (r - q - σ²/2) / σ²
        λ = √(μ² + 2r/σ²)
    """

    def __init__(self):
        self.vanilla = OptionPricer()

    # ── 6 个 Reiner-Rubinstein 组件 ─────────────────

    def _A(self, S, K, tau, vol, r, q, phi):
        """A = φ[S·e^{-qT}·N(φ·x1) - K·e^{-rT}·N(φ·(x1-σ√T))]"""
        Dr = np.exp(-r * tau)
        Dq = np.exp(-q * tau)
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        x1 = np.log(S / K) / (vol * sqrt_tau) + 0.5 * (1 + 2 * (r - q) / vol ** 2) * vol * sqrt_tau
        return phi * (S * Dq * norm.cdf(phi * x1) - K * Dr * norm.cdf(phi * (x1 - vol * sqrt_tau)))

    def _B(self, S, K, H, tau, vol, r, q, phi):
        """B = φ[S·e^{-qT}·(H/S)^{2(μ+1)}·N(φ·y1) - K·e^{-rT}·(H/S)^{2μ}·N(φ·(y1-σ√T))]"""
        Dr = np.exp(-r * tau)
        Dq = np.exp(-q * tau)
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        mu = (r - q - 0.5 * vol ** 2) / vol ** 2
        y1 = np.log(H ** 2 / (S * K)) / (vol * sqrt_tau) + 0.5 * (1 + 2 * (r - q) / vol ** 2) * vol * sqrt_tau
        ratio = H / S
        return phi * (
            S * Dq * ratio ** (2 * (mu + 1)) * norm.cdf(phi * y1)
            - K * Dr * ratio ** (2 * mu) * norm.cdf(phi * (y1 - vol * sqrt_tau))
        )

    def _C(self, S, K, H, tau, vol, r, q, phi):
        """C = φ[S·e^{-qT}·N(φ·x2) - K·e^{-rT}·N(φ·(x2-σ√T))]"""
        Dr = np.exp(-r * tau)
        Dq = np.exp(-q * tau)
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        x2 = np.log(S / H) / (vol * sqrt_tau) + 0.5 * (1 + 2 * (r - q) / vol ** 2) * vol * sqrt_tau
        return phi * (S * Dq * norm.cdf(phi * x2) - K * Dr * norm.cdf(phi * (x2 - vol * sqrt_tau)))

    def _D(self, S, K, H, tau, vol, r, q, phi):
        """D = φ[S·e^{-qT}·(H/S)^{2(μ+1)}·N(φ·y2) - K·e^{-rT}·(H/S)^{2μ}·N(φ·(y2-σ√T))]"""
        Dr = np.exp(-r * tau)
        Dq = np.exp(-q * tau)
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        mu = (r - q - 0.5 * vol ** 2) / vol ** 2
        y2 = np.log(H / S) / (vol * sqrt_tau) + 0.5 * (1 + 2 * (r - q) / vol ** 2) * vol * sqrt_tau
        ratio = H / S
        return phi * (
            S * Dq * ratio ** (2 * (mu + 1)) * norm.cdf(phi * y2)
            - K * Dr * ratio ** (2 * mu) * norm.cdf(phi * (y2 - vol * sqrt_tau))
        )

    def _E(self, S, H, tau, vol, r, q, rebate):
        """E = R·e^{-rT}·[N(d4) - (H/S)^{2μ}·N(d4')]  —— 敲出补偿（下障碍）
        
        d4  = [ln(S/H) + μσ²T] / (σ√T)
        d4' = [ln(H/S) + μσ²T] / (σ√T)
        """
        if abs(rebate) < 1e-15:
            return 0.0
        Dr = np.exp(-r * tau)
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        mu = (r - q - 0.5 * vol ** 2) / vol ** 2
        d4 = (np.log(S / H) + mu * vol ** 2 * tau) / (vol * sqrt_tau)
        d4_prime = (np.log(H / S) + mu * vol ** 2 * tau) / (vol * sqrt_tau)
        return rebate * Dr * (norm.cdf(d4) - (H / S) ** (2 * mu) * norm.cdf(d4_prime))

    def _F_rebate(self, S, H, tau, vol, r, q, rebate):
        """F = R·[(H/S)^{μ+λ}·N(η·d5) + (H/S)^{μ-λ}·N(η·d6)]"""
        if abs(rebate) < 1e-15:
            return 0.0
        sqrt_tau = np.sqrt(max(tau, 1e-16))
        mu = (r - q - 0.5 * vol ** 2) / vol ** 2
        lam = np.sqrt(mu ** 2 + 2 * r / vol ** 2)
        ratio = H / S
        z1 = np.log(H / S) / (vol * sqrt_tau) + lam * vol * sqrt_tau
        z2 = np.log(H / S) / (vol * sqrt_tau) - lam * vol * sqrt_tau
        return rebate * (ratio ** (mu + lam) * norm.cdf(z1) + ratio ** (mu - lam) * norm.cdf(z2))

    # ── 4 种障碍期权定价 ──────────────────────────────

    def _price_do_call(self, S, K, H, tau, vol, r, q, rebate=0.0):
        """Down-and-Out Call（向下敲出看涨）"""
        if tau <= 1e-10:
            return max(S - K, 0) if S > H else rebate
        if S <= H:
            return rebate * np.exp(-r * tau)  # 已敲出
        if H >= K:
            return self._C(S, K, H, tau, vol, r, q, +1) - self._D(S, K, H, tau, vol, r, q, +1) \
                   + self._E(S, H, tau, vol, r, q, rebate)
        else:
            return self._A(S, K, tau, vol, r, q, +1) - self._B(S, K, H, tau, vol, r, q, +1) \
                   + self._F_rebate(S, H, tau, vol, r, q, rebate)

    def _price_uo_call(self, S, K, H, tau, vol, r, q, rebate=0.0):
        """Up-and-Out Call（向上敲出看涨）"""
        if tau <= 1e-10:
            return max(S - K, 0) if S < H else rebate
        if S >= H:
            return rebate * np.exp(-r * tau)  # 已敲出
        if H <= K:
            return 0.0  # 障碍价低于行权价，期权永远敲出
        return self._A(S, K, tau, vol, r, q, +1) - self._C(S, K, H, tau, vol, r, q, +1) \
               + self._D(S, K, H, tau, vol, r, q, +1) - self._B(S, K, H, tau, vol, r, q, +1) \
               + self._F_rebate(S, H, tau, vol, r, q, rebate)

    def _price_do_put(self, S, K, H, tau, vol, r, q, rebate=0.0):
        """Down-and-Out Put（向下敲出看跌）
        
        Reiner-Rubinstein 公式：
        - H < K: DO_put = -B + F_rebate
        - H > K: DO_put = A - C + D - E
        """
        if tau <= 1e-10:
            return max(K - S, 0) if S > H else rebate
        if S <= H:
            return rebate * np.exp(-r * tau)  # 已敲出
        if H < K:
            return -self._B(S, K, H, tau, vol, r, q, -1) \
                   + self._F_rebate(S, H, tau, vol, r, q, rebate)
        else:
            return self._A(S, K, tau, vol, r, q, -1) - self._C(S, K, H, tau, vol, r, q, -1) \
                   + self._D(S, K, H, tau, vol, r, q, -1) - self._E(S, H, tau, vol, r, q, rebate)

    def _price_uo_put(self, S, K, H, tau, vol, r, q, rebate=0.0):
        """Up-and-Out Put（向上敲出看跌）
        
        Reiner-Rubinstein 公式：
        - H < K: UO_put = C - D + F_rebate
        - H > K: UO_put = B - F_rebate
        """
        if tau <= 1e-10:
            return max(K - S, 0) if S < H else rebate
        if S >= H:
            return rebate * np.exp(-r * tau)  # 已敲出
        if H < K:
            return self._C(S, K, H, tau, vol, r, q, -1) - self._D(S, K, H, tau, vol, r, q, -1) \
                   + self._F_rebate(S, H, tau, vol, r, q, rebate)
        else:
            return self._B(S, K, H, tau, vol, r, q, -1) \
                   - self._F_rebate(S, H, tau, vol, r, q, rebate)

    # ── 公共接口 ──────────────────────────────────────

    def up_and_out_call(self, params: MarketParams, barrier: float,
                        rebate: float = 0.0) -> float:
        """向上敲出看涨期权"""
        return self._price_uo_call(params.spot, params.strike, barrier,
                                    params.tau, params.vol, params.r, params.q, rebate)

    def up_and_out_put(self, params: MarketParams, barrier: float,
                       rebate: float = 0.0) -> float:
        """向上敲出看跌期权"""
        return self._price_uo_put(params.spot, params.strike, barrier,
                                   params.tau, params.vol, params.r, params.q, rebate)

    def down_and_out_call(self, params: MarketParams, barrier: float,
                          rebate: float = 0.0) -> float:
        """向下敲出看涨期权"""
        return self._price_do_call(params.spot, params.strike, barrier,
                                    params.tau, params.vol, params.r, params.q, rebate)

    def down_and_out_put(self, params: MarketParams, barrier: float,
                         rebate: float = 0.0) -> float:
        """向下敲出看跌期权"""
        return self._price_do_put(params.spot, params.strike, barrier,
                                   params.tau, params.vol, params.r, params.q, rebate)

    # ── 离散监控修正 ──────────────────────────────────

    @staticmethod
    def discrete_monitoring_correction(barrier: float, vol: float, tau: float,
                                       monitoring_freq: int = 252,
                                       direction: str = "up") -> float:
        """Broadie-Glasserman-Kou (1997) 离散监控连续性修正

        将连续监控的障碍价调整为离散监控的等价障碍价：
        - 上障碍: H_adj = H · exp(+0.5826 · σ · √(T/m))
        - 下障碍: H_adj = H · exp(-0.5826 · σ · √(T/m))

        Args:
            barrier: 原始障碍价
            vol: 波动率
            tau: 剩余期限（年）
            monitoring_freq: 每年监控次数（252=每日, 12=每月）
            direction: "up" 或 "down"

        Returns:
            float: 修正后的障碍价
        """
        if tau <= 0 or vol <= 0 or monitoring_freq <= 0:
            return barrier
        correction = 0.5826 * vol * np.sqrt(tau / monitoring_freq)
        if direction == "up":
            return barrier * np.exp(correction)
        else:  # down
            return barrier * np.exp(-correction)

    # ── Greeks（Bump & Reprice）──────────────────────

    def greeks(self, params: MarketParams, barrier: float,
               option_type: str = "uo_call", rebate: float = 0.0) -> dict:
        """Bump & Reprice 计算障碍期权 Greeks"""
        # 选择定价函数
        price_fn = {
            "uo_call": self._price_uo_call,
            "uo_put": self._price_uo_put,
            "do_call": self._price_do_call,
            "do_put": self._price_do_put,
        }.get(option_type, self._price_uo_call)

        S, K, tau, vol, r, q = params.spot, params.strike, params.tau, params.vol, params.r, params.q

        def _price(S_=S, K_=K, tau_=tau, vol_=vol, r_=r, q_=q):
            return price_fn(S_, K_, barrier, tau_, vol_, r_, q_, rebate)

        base = _price()
        eps = 0.01  # 1% bump

        # Delta
        p_up = _price(S_=S * (1 + eps))
        p_dn = _price(S_=S * (1 - eps))
        delta = (p_up - p_dn) / (2 * S * eps)

        # Gamma
        gamma = (p_up - 2 * base + p_dn) / (S * eps) ** 2

        # Vega
        p_up = _price(vol_=vol * (1 + eps))
        p_dn = _price(vol_=vol * (1 - eps))
        vega = (p_up - p_dn) / (2 * vol * eps * 100)  # per 1%

        # Theta
        dt = 1 / 365
        p_later = _price(tau_=max(tau - dt, 0))
        theta = (p_later - base) / dt

        # Rho
        p_up = _price(r_=r + eps)
        p_dn = _price(r_=r - eps)
        rho = (p_up - p_dn) / (2 * eps * 100)

        return {
            "price": base,
            "delta": delta,
            "gamma": gamma,
            "vega": vega,
            "theta": theta,
            "rho": rho,
        }


# ══════════════════════════════════════════════════════
#  第五部分：固定收益产品定价
# ══════════════════════════════════════════════════════

class FixedIncomePricer:
    """固定收益产品定价器

    收益凭证估值的基础组件：保底收益折现。
    所有结构化产品的价值 = 固定收益部分 + 期权部分
    """

    @staticmethod
    def present_value(principal: float, coupon_rate: float,
                      issue_date: date, val_date: date,
                      maturity_date: date, discount_rate: float) -> float:
        """固定收益部分现值

        PV = Principal * (1 + coupon_rate * T_total) * exp(-r * T_remaining)
        其中 T_total = 发行日到到期日的总期限，T_remaining = 估值日到到期日的剩余期限
        """
        if val_date >= maturity_date:
            return principal  # 已到期，按面值

        tau_total = (maturity_date - issue_date).days / 365.0
        tau_remaining = (maturity_date - val_date).days / 365.0
        # 到期收益 = 本金 × (1 + 年化票息 × 总期限)
        maturity_value = principal * (1 + coupon_rate * tau_total)
        return maturity_value * _discount(discount_rate, tau_remaining)

    @staticmethod
    def accrued_interest(principal: float, coupon_rate: float,
                         issue_date: date, val_date: date) -> float:
        """应计利息（用于付息型产品）"""
        elapsed = (val_date - issue_date).days / 365.0
        return principal * coupon_rate * elapsed
