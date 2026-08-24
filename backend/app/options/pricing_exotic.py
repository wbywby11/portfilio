"""
期权定价 —— 奇异结构化产品（P9 治理自 core.py 拆分）.

包含：雪球、凤凰、双鲨（双边障碍）、亚式、彩虹、区间累积、
可赎回固收、数字区间的参数结构体与定价器。
方法体自 app/options/core.py 逐字平移，core.py 保留兼容再导出。
"""

import numpy as np
from scipy.stats import norm
from dataclasses import dataclass
from typing import List

from app.options.pricing_vanilla import MarketParams


# ══════════════════════════════════════════════════════
#  第六部分：雪球结构定价（蒙特卡洛）
# ══════════════════════════════════════════════════════

@dataclass
class SnowballParams:
    """雪球结构参数"""
    spot_ref: float          # S0 期初参考价
    knock_out: float         # KO 敲出价（比例，如 1.0 = 100% × S0）
    knock_in: float          # KI 敲入价（比例，如 0.75 = 75% × S0）
    coupon_year: float       # 年化票息率
    tau: float               # 最长期限（年）
    obs_freq: str = "monthly"  # 观察频率: monthly / weekly / daily
    vol: float = 0.20
    r: float = 0.03
    q: float = 0.0
    recovery_coupon_rate: float = 0.0   # 敲入后恢复至期初价以上时的恢复票息率（年化）
    use_control_variate: bool = True    # 是否启用控制变量法（方差缩减）


class SnowballPricer:
    """雪球结构定价器 —— 蒙特卡洛模拟

    结构说明：
    - 每月/每周指定观察日判断是否敲出（S ≥ KO × S0）
    - 全程每日判断是否敲入（S ≤ KI × S0）
    - 未敲入 + 敲出 → 本金 + 已累积票息
    - 未敲入 + 未敲出 → 本金 + 全部票息
    - 敲入 + 未敲出 → 本金 × max(0, 1 + S_T/S0 - 1) = 本金 × S_T/S0
    - 敲入 + 敲出 → 本金 + 已累积票息（敲出优先结算）
    """

    def __init__(self, n_paths: int = 100000, seed: int = 42):
        self.n_paths = n_paths
        self._rng = np.random.default_rng(seed)

    def _get_obs_days(self, tau: float, obs_freq: str) -> np.ndarray:
        """获取观察日索引（从第0天到第N天）"""
        n_days = int(tau * 252)
        if obs_freq == "monthly":
            step = 21  # 每月约21个交易日
        elif obs_freq == "weekly":
            step = 5
        else:  # daily
            step = 1
        obs_days = np.arange(step, n_days + 1, step)  # 从第一个观察日到最后一个
        return obs_days[obs_days <= n_days]

    def price(self, params: SnowballParams, return_details: bool = False):
        """MC 定价雪球结构

        Returns:
            float or dict: 价格 / {price, ko_prob, ki_prob, expected_term, se}
        """
        S0, KO, KI, c, tau, freq = (
            params.spot_ref, params.knock_out, params.knock_in,
            params.coupon_year, params.tau, params.obs_freq,
        )
        vol, r, q = params.vol, params.r, params.q

        n_days = int(tau * 252)
        dt = 1 / 252
        sqrt_dt = np.sqrt(dt)
        n = self.n_paths // 2 * 2  # 偶数

        if n_days < 1:
            # 当天到期
            price = S0
            return {"price": price, "ko_prob": 0, "ki_prob": 0,
                    "expected_term": 0, "se": 0} if return_details else price

        # 观察日
        obs_days = self._get_obs_days(tau, freq)
        obs_days = obs_days[obs_days < n_days]  # 排除最后一天（到期日单独处理）

        KO_level = KO * S0
        KI_level = KI * S0

        # ── GBM 模拟（对偶变量法） ──
        Z = self._rng.normal(0, 1, (n_days, n))
        Z[:, n // 2:] = -Z[:, :n // 2]  # 对偶

        drift = (r - q - 0.5 * vol ** 2) * dt
        increments = drift + vol * sqrt_dt * Z
        log_returns = np.cumsum(increments, axis=0)
        paths = S0 * np.exp(log_returns)  # shape: (n_days, n)

        # ── 初始化追踪变量 ──
        ko_day = np.full(n, n_days + 1, dtype=int)  # 敲出日（默认未敲出）
        ki_flag = np.zeros(n, dtype=bool)            # 是否敲入

        # 检查敲出（观察日）
        for d in obs_days:
            ko_mask = (ko_day > d) & (paths[d - 1, :] >= KO_level) if d > 0 else (paths[0, :] >= KO_level)
            ko_day[ko_mask] = d

        # 检查敲入（全程每日）
        ki_mask = np.any(paths <= KI_level, axis=0)
        ki_flag[ki_mask] = True

        # ── Payoff 计算 ──
        ko_flag = ko_day <= n_days  # 是否敲出
        S_T = paths[-1, :]
        recovery_c = params.recovery_coupon_rate  # 恢复票息率

        payoff = np.zeros(n)

        # 向量化 payoff 计算
        # 敲出：本金 + 已累积票息
        ko_mask = ko_flag
        for i in np.where(ko_mask)[0]:
            periods = np.sum(obs_days <= ko_day[i])
            total_periods = len(obs_days) + 1
            coupon_per_period = c * tau / total_periods
            payoff[i] = S0 + S0 * coupon_per_period * periods

        # 敲入但未敲出
        ki_no_ko = (~ko_flag) & ki_flag
        ki_recovered = ki_no_ko & (S_T >= S0)  # 敲入但恢复到期初价以上
        ki_loss = ki_no_ko & (S_T < S0)         # 敲入且到期亏损

        if recovery_c > 0:
            # 恢复票息变体：敲入后恢复至期初价以上时，支付部分恢复票息
            payoff[ki_recovered] = S0 + S0 * recovery_c * tau
        else:
            # 经典雪球：敲入后恢复收益 = 0（仅返回本金）
            payoff[ki_recovered] = S0

        payoff[ki_loss] = np.maximum(S_T[ki_loss], 0)  # 承担下跌

        # 未敲入未敲出：本金 + 全部票息
        no_ki_no_ko = (~ko_flag) & (~ki_flag)
        payoff[no_ki_no_ko] = S0 + S0 * c * tau

        # 折现
        disc = np.exp(-r * tau)
        pv = disc * payoff

        # ── 控制变量法（方差缩减） ──
        if params.use_control_variate and n > 10:
            # 使用 S_T 作为控制变量：E[e^{-rT} S_T] = S0 * e^{-qT}
            E_ST = S0 * np.exp((r - q) * tau) * disc  # 折现后的期望终端价
            ST_disc = disc * S_T  # 每条路径的折现终端价
            # 最优 beta = Cov(pv, ST_disc) / Var(ST_disc)
            cov_matrix = np.cov(pv, ST_disc)
            var_ST = cov_matrix[1, 1]
            if var_ST > 1e-20:
                beta = cov_matrix[0, 1] / var_ST
                pv = pv - beta * (ST_disc - E_ST)  # 控制变量修正

        price = np.mean(pv)
        se = np.std(pv) / np.sqrt(n)
        ko_prob = np.mean(ko_flag)
        ki_prob = np.mean(ki_flag)  # 整体敲入概率
        expected_term = np.mean(ko_day[ko_flag]) / 252 if np.any(ko_flag) else tau

        # 加权平均期限：敲出的按敲出日，未敲出的按完整期限
        expected_term = (np.sum(ko_day[ko_flag]) + (n - np.sum(ko_flag)) * n_days) / (n * 252)

        if return_details:
            return {
                "price": price,
                "se": se,
                "ko_prob": ko_prob,
                "ki_prob": ki_prob,
                "expected_term": expected_term,
                "method": "snowball_mc",
            }
        return price

    def greeks(self, params: SnowballParams) -> dict:
        """Bump & Reprice 计算 Greeks
        
        MC Greeks 需要较大的 bump（1%），否则信号会被 MC 噪声淹没。
        """
        base = self.price(params, return_details=True)
        base_price = base["price"]
        S0, vol, r = params.spot_ref, params.vol, params.r
        eps = 0.01  # 1% bump for MC (太小会被噪声淹没)

        def bumped(**kw):
            p = SnowballParams(**{**{
                "spot_ref": params.spot_ref, "knock_out": params.knock_out,
                "knock_in": params.knock_in, "coupon_year": params.coupon_year,
                "tau": params.tau, "obs_freq": params.obs_freq,
                "vol": params.vol, "r": params.r, "q": params.q,
            }, **kw})
            return self.price(p, return_details=True)["price"]

        # Delta: bump spot
        p_up = bumped(spot_ref=S0 * (1 + eps))
        p_dn = bumped(spot_ref=S0 * (1 - eps))
        delta = (p_up - p_dn) / (2 * S0 * eps)

        # Vega: bump vol
        p_up = bumped(vol=vol * (1 + eps))
        p_dn = bumped(vol=vol * (1 - eps))
        vega = (p_up - p_dn) / (2 * vol * eps * 100)  # per 1% vol

        # Rho: bump rate
        p_up = bumped(r=r + eps)
        p_dn = bumped(r=r - eps)
        rho = (p_up - p_dn) / (2 * eps * 100)

        # Theta: bump time (1 day = 1/365 year)
        dt = 1 / 365
        p_later = bumped(tau=params.tau - dt)
        theta = (p_later - base_price) / dt  # 每天的时间衰减

        return {
            "price": base_price,
            "delta": delta,
            "vega": vega,
            "rho": rho,
            "theta": theta,
            "ko_prob": base["ko_prob"],
            "ki_prob": base["ki_prob"],
            "expected_term": base["expected_term"],
            "method": "snowball_mc",
        }


# ══════════════════════════════════════════════════════
#  第七部分：凤凰结构定价（蒙特卡洛）
# ══════════════════════════════════════════════════════

@dataclass
class PhoenixParams:
    """凤凰结构参数

    凤凰（Phoenix）是带逐月派息和记忆票息的雪球变体：
    - 月观察：S ≥ KO → 敲出终止，本金+当期票息+记忆累积票息
    - 月观察：KI < S < KO → 支付当期票息+记忆票息
    - 月观察：S ≤ KI → 不派息，记忆该期票息
    - 到期：未敲出+未敲入 → 本金+最后一期票息
    - 到期：未敲出+敲入 → 本金 × max(0, S_T/S0)
    """
    spot_ref: float          # S0 期初参考价
    knock_out: float         # KO 敲出价（比例）
    knock_in: float          # KI 敲入价（比例）
    coupon_per_period: float # 每期票息（如 0.015 = 每期 1.5%）
    tau: float               # 最长期限（年）
    obs_freq: str = "monthly"
    memory_flag: bool = True  # 是否启用记忆票息
    vol: float = 0.20
    r: float = 0.03
    q: float = 0.0
    use_control_variate: bool = True  # 是否启用控制变量法（方差缩减）


class PhoenixPricer:
    """凤凰结构定价器 —— 蒙特卡洛模拟

    与雪球的区别：
    1. 每期（月）判断是否派息，而非到期一次性结算
    2. 记忆票息：未支付的票息在后续恢复时补发
    3. 现金流分布在多个时间点，需逐笔折现
    """

    def __init__(self, n_paths: int = 50000, seed: int = 42):
        self.n_paths = n_paths
        self._rng = np.random.default_rng(seed)

    def _get_obs_days(self, tau: float, obs_freq: str) -> np.ndarray:
        """获取观察日索引（从第1个到第N个）"""
        n_days = int(tau * 252)
        if obs_freq == "monthly":
            step = 21
        elif obs_freq == "weekly":
            step = 5
        else:
            step = 1
        obs_days = np.arange(step, n_days + 1, step)
        return obs_days[obs_days <= n_days]

    def price(self, params: PhoenixParams, return_details: bool = False):
        """MC 定价凤凰结构（向量化版本）"""
        S0, KO, KI, cpp, tau, freq, memory = (
            params.spot_ref, params.knock_out, params.knock_in,
            params.coupon_per_period, params.tau, params.obs_freq,
            params.memory_flag,
        )
        vol, r, q = params.vol, params.r, params.q

        n_days = int(tau * 252)
        dt = 1 / 252
        sqrt_dt = np.sqrt(dt)
        n = self.n_paths // 2 * 2

        if n_days < 1:
            return {"price": S0, "se": 0, "ko_prob": 0,
                    "ki_prob": 0, "method": "phoenix_mc"} if return_details else S0

        obs_days = self._get_obs_days(tau, freq)
        n_obs = len(obs_days)
        if n_obs == 0:
            price = S0 * np.exp(-r * tau)
            return {"price": price, "se": 0, "ko_prob": 0,
                    "ki_prob": 0, "method": "phoenix_mc"} if return_details else price

        KO_level = KO * S0
        KI_level = KI * S0

        # ── GBM 模拟（对偶变量法） ──
        Z = self._rng.normal(0, 1, (n_days, n))
        Z[:, n // 2:] = -Z[:, :n // 2]

        drift = (r - q - 0.5 * vol ** 2) * dt
        increments = drift + vol * sqrt_dt * Z
        log_returns = np.cumsum(increments, axis=0)
        paths = S0 * np.exp(log_returns)  # shape: (n_days, n)

        # ── 向量化现金流计算 ──
        cf_total = np.zeros(n)
        ko_flag = np.zeros(n, dtype=bool)  # 是否敲出
        ki_flag = np.zeros(n, dtype=bool)  # 是否敲入
        active = np.ones(n, dtype=bool)     # 路径是否还存续
        remembered = np.zeros(n, dtype=int)  # 记忆累积未派息次数

        for j in range(n_obs):
            d = obs_days[j]
            S_t = paths[d - 1, :]  # shape: (n,)
            t_years = d / 252
            disc = np.exp(-r * t_years)

            # 敲出：S >= KO
            ko_mask = active & (S_t >= KO_level)
            payoff_ko = S0 + S0 * cpp * (1 + remembered)
            cf_total += np.where(ko_mask, payoff_ko * disc, 0)
            ko_flag |= ko_mask
            active &= ~ko_mask

            # 未敲出：检查是否派息
            pay_mask = active & (S_t > KI_level)
            payoff_coupon = S0 * cpp * (1 + remembered)
            cf_total += np.where(pay_mask, payoff_coupon * disc, 0)
            remembered = np.where(pay_mask, 0, remembered)  # 派息后清空记忆

            # 敲入标记
            ki_mask = active & (S_t <= KI_level)
            ki_flag |= ki_mask
            if memory:
                remembered = np.where(ki_mask, remembered + 1, remembered)

        # 到期结算（未敲出的路径）
        S_T = paths[-1, :]
        disc_T = np.exp(-r * tau)
        # 未敲入：本金 + 最后一期票息
        cf_total += np.where(active & ~ki_flag, (S0 + S0 * cpp) * disc_T, 0)
        # 已敲入：承担下跌
        cf_total += np.where(active & ki_flag, S0 * np.maximum(S_T / S0, 0) * disc_T, 0)

        # ── 统计 ──
        # 控制变量法（方差缩减）
        if params.use_control_variate and n > 10:
            E_ST = S0 * np.exp((r - q) * tau) * disc_T
            ST_disc = disc_T * S_T
            cov_matrix = np.cov(cf_total, ST_disc)
            var_ST = cov_matrix[1, 1]
            if var_ST > 1e-20:
                beta = cov_matrix[0, 1] / var_ST
                cf_total = cf_total - beta * (ST_disc - E_ST)

        price = np.mean(cf_total)
        se = np.std(cf_total) / np.sqrt(n)
        ko_prob = np.mean(ko_flag)
        ki_prob = np.mean(ki_flag)

        if return_details:
            return {
                "price": price,
                "se": se,
                "ko_prob": ko_prob,
                "ki_prob": ki_prob,
                "method": "phoenix_mc",
            }
        return price


# ══════════════════════════════════════════════════════
#  第八部分：双鲨（双边障碍期权）定价
# ══════════════════════════════════════════════════════

class DoubleBarrierPricer:
    """双鲨期权（双边敲出）定价 —— 蒙特卡洛模拟

    纯 numpy 实现，无外部依赖。

    双鲨结构（Double Knock-Out）：
    - 标的价格在 [L, H] 区间内时，期权存续
    - 触碰 L（下界）或 H（上界）时，敲出
    - 两个障碍使期权比单障更便宜（风险更大）
    """

    def __init__(self, n_paths: int = 100000, seed: int = 42):
        self.n_paths = n_paths
        self._rng = np.random.default_rng(seed)

    def price(self, params: MarketParams, barrier_low: float,
              barrier_high: float, rebate: float = 0.0) -> float:
        """双鲨看涨（双边敲出）定价

        Args:
            params: MarketParams (spot, strike, tau, vol, r, q)
            barrier_low: 下界障碍价
            barrier_high: 上界障碍价
            rebate: 敲出补偿（到期支付）

        Returns:
            float: 期权价格
        """
        S, K, tau, vol, r, q = params.spot, params.strike, params.tau, params.vol, params.r, params.q

        if tau <= 1e-10:
            if barrier_low < S < barrier_high:
                return max(S - K, 0)
            return rebate

        # 如果当前已在障碍外
        if S <= barrier_low or S >= barrier_high:
            return rebate * np.exp(-r * tau)

        n_days = int(tau * 252)
        dt = 1 / 252
        sqrt_dt = np.sqrt(dt)
        n = self.n_paths // 2 * 2  # 偶数（对偶变量）

        # GBM 模拟（对偶变量法）
        Z = self._rng.normal(0, 1, (n_days, n))
        Z[:, n // 2:] = -Z[:, :n // 2]

        drift = (r - q - 0.5 * vol ** 2) * dt
        increments = drift + vol * sqrt_dt * Z
        log_returns = np.cumsum(increments, axis=0)
        paths = S * np.exp(log_returns)  # shape: (n_days, n)

        # 检查是否触碰障碍（全程每日检查）
        hit_low = np.any(paths <= barrier_low, axis=0)    # shape: (n,)
        hit_high = np.any(paths >= barrier_high, axis=0)  # shape: (n,)
        knocked_out = hit_low | hit_high

        # 未敲出：看涨 payoff
        S_T = paths[-1, :]
        payoff_no_ko = np.maximum(S_T - K, 0)

        # 敲出：补偿（近似用到期折现）
        payoff_ko = np.full(n, rebate)

        # 组合
        payoff = np.where(knocked_out, payoff_ko, payoff_no_ko)

        # 折现
        disc = np.exp(-r * tau)
        price = disc * np.mean(payoff)
        return price

    def price_call(self, spot: float, strike: float, tau: float,
                   vol: float, r: float, q: float,
                   barrier_low: float, barrier_high: float,
                   rebate: float = 0.0) -> float:
        """便捷接口：双鲨看涨"""
        p = MarketParams(spot, strike, tau, vol, r, q)
        return self.price(p, barrier_low, barrier_high, rebate)

    def price_put(self, spot: float, strike: float, tau: float,
                  vol: float, r: float, q: float,
                  barrier_low: float, barrier_high: float,
                  rebate: float = 0.0) -> float:
        """便捷接口：双鲨看跌"""
        p = MarketParams(spot, strike, tau, vol, r, q)
        # 复用 price 方法的框架，改为看跌 payoff
        S, K, tau_, vol_, r_, q_ = p.spot, p.strike, p.tau, p.vol, p.r, p.q

        if tau_ <= 1e-10:
            if barrier_low < S < barrier_high:
                return max(K - S, 0)
            return rebate

        if S <= barrier_low or S >= barrier_high:
            return rebate * np.exp(-r_ * tau_)

        n_days = int(tau_ * 252)
        dt = 1 / 252
        sqrt_dt = np.sqrt(dt)
        n = self.n_paths // 2 * 2

        Z = self._rng.normal(0, 1, (n_days, n))
        Z[:, n // 2:] = -Z[:, :n // 2]

        drift = (r_ - q_ - 0.5 * vol_ ** 2) * dt
        increments = drift + vol_ * sqrt_dt * Z
        log_returns = np.cumsum(increments, axis=0)
        paths = S * np.exp(log_returns)

        hit_low = np.any(paths <= barrier_low, axis=0)
        hit_high = np.any(paths >= barrier_high, axis=0)
        knocked_out = hit_low | hit_high

        S_T = paths[-1, :]
        payoff_no_ko = np.maximum(K - S_T, 0)
        payoff_ko = np.full(n, rebate)
        payoff = np.where(knocked_out, payoff_ko, payoff_no_ko)

        disc = np.exp(-r_ * tau_)
        return disc * np.mean(payoff)

    # ── Greeks（Bump & Reprice）──────────────────────

    def greeks(self, params: MarketParams, barrier_low: float,
               barrier_high: float, rebate: float = 0.0) -> dict:
        """Bump & Reprice 计算双鲨期权 Greeks

        MC Greeks 需要较大的 bump（1%），否则信号被噪声淹没。

        Args:
            params: 市场参数
            barrier_low: 下界障碍价
            barrier_high: 上界障碍价
            rebate: 敲出补偿

        Returns:
            dict: {price, delta, gamma, vega, theta, rho}
        """
        S, K, tau, vol, r, q = params.spot, params.strike, params.tau, params.vol, params.r, params.q

        def _price(S_=S, K_=K, tau_=tau, vol_=vol, r_=r, q_=q):
            p = MarketParams(S_, K_, tau_, vol_, r_, q_)
            return self.price(p, barrier_low, barrier_high, rebate)

        base = _price()
        eps = 0.01  # 1% bump for MC

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
#  第九部分：亚式期权定价（算术/几何平均）
# ══════════════════════════════════════════════════════

@dataclass
class AsianParams:
    """亚式期权参数"""
    spot_ref: float          # S0 参考价
    strike: float            # K 行权价
    tau: float               # 期限（年）
    obs_freq: str = "daily"  # 观察频率: daily / weekly / monthly
    avg_type: str = "arithmetic"  # 平均类型: arithmetic / geometric
    vol: float = 0.20
    r: float = 0.03
    q: float = 0.0


class AsianOptionPricer:
    """亚式期权定价器

    支持算术平均和几何平均两种类型：
    - 几何平均: Turnbull-Wakeman 解析近似
    - 算术平均: 蒙特卡洛模拟
    """

    def __init__(self, n_paths: int = 50000, seed: int = 42):
        self.n_paths = n_paths
        self._rng = np.random.default_rng(seed)

    def price(self, params: AsianParams, return_details: bool = False):
        """定价亚式期权"""
        S0, K, tau = params.spot_ref, params.strike, params.tau
        vol, r, q = params.vol, params.r, params.q

        if tau <= 1e-10:
            payoff = max(S0 - K, 0)
            price = payoff * np.exp(-r * tau)
            return {"price": price, "method": "asian_intrinsic"} if return_details else price

        if params.avg_type == "geometric":
            price = self._geometric_asian(S0, K, tau, vol, r, q)
            method = "asian_geometric_analytic"
        else:
            price, method = self._arithmetic_asian_mc(params)

        if return_details:
            return {"price": price, "method": method}
        return price

    def _geometric_asian(self, S0, K, tau, vol, r, q):
        """Turnbull-Wakeman 几何平均亚式期权近似"""
        sigma_g = vol / np.sqrt(3)
        mu_g = (r - q - 0.5 * vol ** 2) / 2
        d1 = (np.log(S0 / K) + (mu_g + 0.5 * sigma_g ** 2) * tau) / (sigma_g * np.sqrt(tau))
        d2 = d1 - sigma_g * np.sqrt(tau)
        Dr = np.exp(-r * tau)
        F_g = S0 * np.exp(mu_g * tau)
        price = Dr * (F_g * norm.cdf(d1) - K * norm.cdf(d2))
        return max(price, 0)

    def _arithmetic_asian_mc(self, params):
        """蒙特卡洛模拟算术平均亚式期权"""
        S0, K, tau = params.spot_ref, params.strike, params.tau
        vol, r, q = params.vol, params.r, params.q
        n_days = max(int(tau * 252), 1)
        dt = 1 / 252
        sqrt_dt = np.sqrt(dt)
        n = self.n_paths // 2 * 2

        if params.obs_freq == "monthly":
            obs_step = 21
        elif params.obs_freq == "weekly":
            obs_step = 5
        else:
            obs_step = 1
        obs_days = np.arange(obs_step, n_days + 1, obs_step)
        obs_days = obs_days[obs_days <= n_days]
        if len(obs_days) == 0:
            obs_days = np.array([n_days])

        Z = self._rng.normal(0, 1, (n_days, n))
        Z[:, n // 2:] = -Z[:, :n // 2]
        drift = (r - q - 0.5 * vol ** 2) * dt
        increments = drift + vol * sqrt_dt * Z
        log_returns = np.cumsum(increments, axis=0)
        paths = S0 * np.exp(log_returns)

        avg_prices = np.mean(paths[obs_days - 1, :], axis=0)
        payoff = np.maximum(avg_prices - K, 0)
        disc = np.exp(-r * tau)
        price = float(disc * np.mean(payoff))
        return max(price, 0), "asian_arithmetic_mc"

    def greeks(self, params: AsianParams) -> dict:
        """Bump & Reprice 计算 Greeks"""
        base = self.price(params, return_details=True)["price"]
        S0, vol, r = params.spot_ref, params.vol, params.r
        eps = 0.01

        def bumped(**kw):
            p = AsianParams(**{**vars(params), **kw})
            return self.price(p)

        delta = (bumped(spot_ref=S0 * (1 + eps)) - bumped(spot_ref=S0 * (1 - eps))) / (2 * S0 * eps)
        vega = (bumped(vol=vol * (1 + eps)) - bumped(vol=vol * (1 - eps))) / (2 * vol * eps * 100)
        dt = 1 / 365
        theta = (bumped(tau=max(params.tau - dt, 0)) - base) / dt
        rho = (bumped(r=r + eps) - bumped(r=r - eps)) / (2 * eps * 100)

        return {"price": base, "delta": delta, "vega": vega, "theta": theta, "rho": rho}


# ══════════════════════════════════════════════════════
#  第十部分：彩虹期权定价（多标的挂钩）
# ══════════════════════════════════════════════════════

@dataclass
class RainbowParams:
    """彩虹期权参数（多标的挂钩）"""
    spots: List[float]           # 各标的现价
    strikes: List[float]         # 各标的行权价
    tau: float                   # 期限（年）
    vols: List[float]            # 各标的波动率
    correlations: List[List[float]]  # 相关系数矩阵
    payoff_type: str = "best_of"  # best_of / worst_of / all_or_nothing
    r: float = 0.03
    q: float = 0.0


class RainbowPricer:
    """彩虹期权定价器（多标的挂钩）—— 蒙特卡洛模拟

    支持：
    - best_of: 取最优标的的 payoff
    - worst_of: 取最差标的的 payoff
    - all_or_nothing: 所有标的都超过行权价才有 payoff
    """

    def __init__(self, n_paths: int = 50000, seed: int = 42):
        self.n_paths = n_paths
        self._rng = np.random.default_rng(seed)

    def price(self, params: RainbowParams, return_details: bool = False):
        """定价彩虹期权"""
        n_assets = len(params.spots)
        tau = params.tau
        r, q = params.r, params.q

        if tau <= 1e-10:
            payoffs = [max(s - k, 0) for s, k in zip(params.spots, params.strikes)]
            if params.payoff_type == "best_of":
                price = max(payoffs)
            elif params.payoff_type == "worst_of":
                price = min(payoffs)
            else:
                price = min(payoffs) if all(p > 0 for p in payoffs) else 0
            price *= np.exp(-r * tau)
            return {"price": price, "method": "rainbow_intrinsic"} if return_details else price

        n = self.n_paths // 2 * 2
        n_days = max(int(tau * 252), 1)
        dt = 1 / 252
        sqrt_dt = np.sqrt(dt)

        corr = np.array(params.correlations)
        if corr.shape != (n_assets, n_assets):
            corr = np.eye(n_assets)
        L = np.linalg.cholesky(corr)

        Z_indep = self._rng.normal(0, 1, (n_assets, n_days, n))
        Z_corr = np.zeros_like(Z_indep)
        for t in range(n_days):
            for p in range(n):
                z = Z_indep[:, t, p]
                Z_corr[:, t, p] = L @ z

        terminal_prices = np.zeros((n_assets, n))
        for i in range(n_assets):
            drift = (r - q - 0.5 * params.vols[i] ** 2) * dt * n_days
            vol_term = params.vols[i] * sqrt_dt * np.sum(Z_corr[i, :, :], axis=0)
            terminal_prices[i, :] = params.spots[i] * np.exp(drift + vol_term)

        payoffs_matrix = np.maximum(terminal_prices - np.array(params.strikes)[:, None], 0)

        if params.payoff_type == "best_of":
            path_payoffs = np.max(payoffs_matrix, axis=0)
        elif params.payoff_type == "worst_of":
            path_payoffs = np.min(payoffs_matrix, axis=0)
        else:
            all_in = np.all(payoffs_matrix > 0, axis=0)
            path_payoffs = np.where(all_in, np.sum(payoffs_matrix, axis=0), 0)

        disc = np.exp(-r * tau)
        price = float(disc * np.mean(path_payoffs))
        method = f"rainbow_{params.payoff_type}_mc"

        if return_details:
            se = float(np.std(path_payoffs) / np.sqrt(n))
            return {"price": price, "se": se, "method": method}
        return price

    def greeks(self, params: RainbowParams) -> dict:
        """Bump & Reprice 计算 Greeks"""
        base = self.price(params, return_details=True)["price"]
        eps = 0.01

        deltas = []
        for i in range(len(params.spots)):
            spots_up = list(params.spots)
            spots_dn = list(params.spots)
            spots_up[i] *= (1 + eps)
            spots_dn[i] *= (1 - eps)
            p_up = RainbowParams(**{**vars(params), "spots": spots_up})
            p_dn = RainbowParams(**{**vars(params), "spots": spots_dn})
            d = (self.price(p_up) - self.price(p_dn)) / (2 * params.spots[i] * eps)
            deltas.append(d)

        return {"price": base, "deltas": deltas}


# ══════════════════════════════════════════════════════
#  第十一部分：区间累积期权定价
# ══════════════════════════════════════════════════════

@dataclass
class RangeAccrualParams:
    """区间累积期权参数"""
    spot_ref: float          # S0 参考价
    lower_barrier: float     # 区间下界
    upper_barrier: float     # 区间上界
    coupon_rate: float       # 年化票息率
    tau: float               # 期限（年）
    obs_freq: str = "daily"  # 观察频率
    vol: float = 0.20
    r: float = 0.03
    q: float = 0.0


class RangeAccrualPricer:
    """区间累积期权定价器 —— 蒙特卡洛模拟

    当标的价格在 [lower, upper] 区间内时，每日累积票息。
    到期支付 = 本金 × 票息率 × (区间内天数 / 总天数) × 期限
    """

    def __init__(self, n_paths: int = 50000, seed: int = 42):
        self.n_paths = n_paths
        self._rng = np.random.default_rng(seed)

    def price(self, params: RangeAccrualParams, return_details: bool = False):
        """定价区间累积期权"""
        S0 = params.spot_ref
        tau = params.tau
        vol, r, q = params.vol, params.r, params.q

        if tau <= 1e-10:
            price = S0 * np.exp(-r * tau)
            return {"price": price, "method": "range_accrual_intrinsic"} if return_details else price

        n_days = max(int(tau * 252), 1)
        dt = 1 / 252
        sqrt_dt = np.sqrt(dt)
        n = self.n_paths // 2 * 2

        if params.obs_freq == "monthly":
            obs_step = 21
        elif params.obs_freq == "weekly":
            obs_step = 5
        else:
            obs_step = 1
        obs_days = np.arange(obs_step, n_days + 1, obs_step)
        obs_days = obs_days[obs_days <= n_days]
        n_obs = len(obs_days)
        if n_obs == 0:
            n_obs = 1
            obs_days = np.array([n_days])

        Z = self._rng.normal(0, 1, (n_days, n))
        Z[:, n // 2:] = -Z[:, :n // 2]
        drift = (r - q - 0.5 * vol ** 2) * dt
        increments = drift + vol * sqrt_dt * Z
        log_returns = np.cumsum(increments, axis=0)
        paths = S0 * np.exp(log_returns)

        lower = params.lower_barrier
        upper = params.upper_barrier
        in_range_count = np.zeros(n)
        for d in obs_days:
            prices = paths[d - 1, :]
            in_range_count += ((prices >= lower) & (prices <= upper)).astype(float)

        accrual_ratio = in_range_count / n_obs
        # 每条路径的票息（取均值作为期望票息）
        coupon_per_path = S0 * params.coupon_rate * tau * accrual_ratio

        fixed_part = float(S0 * np.exp(-r * tau))
        option_part = float(np.mean(coupon_per_path) * np.exp(-r * tau))
        price = fixed_part + option_part

        if return_details:
            avg_ratio = float(np.mean(accrual_ratio))
            return {
                "price": price,
                "fixed_part": float(fixed_part),
                "option_part": float(option_part),
                "avg_accrual_ratio": avg_ratio,
                "method": "range_accrual_mc",
            }
        return price

    def greeks(self, params: RangeAccrualParams) -> dict:
        """Bump & Reprice 计算 Greeks"""
        base = self.price(params, return_details=True)["price"]
        S0, vol = params.spot_ref, params.vol
        eps = 0.01

        def bumped(**kw):
            p = RangeAccrualParams(**{**vars(params), **kw})
            return self.price(p)

        delta = (bumped(spot_ref=S0 * (1 + eps)) - bumped(spot_ref=S0 * (1 - eps))) / (2 * S0 * eps)
        vega = (bumped(vol=vol * (1 + eps)) - bumped(vol=vol * (1 - eps))) / (2 * vol * eps * 100)
        dt = 1 / 365
        theta = (bumped(tau=max(params.tau - dt, 0)) - base) / dt

        return {"price": base, "delta": delta, "vega": vega, "theta": theta}


# ══════════════════════════════════════════════════════
#  第十二部分：可赎回固收定价（二叉树）
# ══════════════════════════════════════════════════════

@dataclass
class CallableFixedParams:
    """可赎回固收参数"""
    principal: float          # 本金
    coupon_rate: float        # 年化票息率
    tau: float                # 期限（年）
    call_date: float          # 可赎回起始日（年）
    call_price: float         # 赎回价格
    r: float = 0.03           # 无风险利率
    rate_vol: float = 0.01    # 利率波动率
    n_steps: int = 100        # 二叉树步数


class CallableFixedPricer:
    """可赎回固收定价器 —— 二叉树模型

    发行人有权在 call_date 后以 call_price 提前赎回。
    对投资者而言，这相当于持有固收 - 发行人看涨期权。
    """

    def price(self, params: CallableFixedParams, return_details: bool = False):
        """定价可赎回固收"""
        P = params.principal
        c = params.coupon_rate
        tau = params.tau
        r = params.r
        n = params.n_steps

        if tau <= 1e-10:
            price = P
            return {"price": price, "method": "callable_fixed_matured"} if return_details else price

        dt = tau / n
        call_step = int(params.call_date / dt) if params.call_date < tau else n + 1
        coupon_per_step = P * c * dt

        values = np.zeros(n + 1)
        for j in range(n + 1):
            values[j] = P + coupon_per_step

        for i in range(n - 1, -1, -1):
            rate_i = r
            disc = np.exp(-rate_i * dt)
            for j in range(i + 1):
                p_up = 0.5
                val = disc * (p_up * values[j] + (1 - p_up) * values[j + 1])
                if i >= call_step:
                    val = min(val, params.call_price + coupon_per_step)
                values[j] = val + coupon_per_step

        price = float(values[0] - coupon_per_step)

        if return_details:
            straight_price = P * (1 + c * tau) * np.exp(-r * tau)
            call_option_value = straight_price - price
            return {
                "price": price,
                "straight_bond_price": straight_price,
                "call_option_value": call_option_value,
                "method": "callable_fixed_binomial",
            }
        return price

    def greeks(self, params: CallableFixedParams) -> dict:
        """利率敏感性（DV01）"""
        base = self.price(params, return_details=True)["price"]
        dr = 0.0001
        p_up = self.price(CallableFixedParams(**{**vars(params), "r": params.r + dr}))
        p_dn = self.price(CallableFixedParams(**{**vars(params), "r": params.r - dr}))
        dv01 = -(p_up - p_dn) / (2 * dr * 10000)
        return {"price": base, "dv01": dv01}


# ══════════════════════════════════════════════════════
#  第十三部分：数字区间期权定价（解析解）
# ══════════════════════════════════════════════════════

@dataclass
class DigitalRangeParams:
    """数字区间期权参数"""
    spot: float               # 现价
    lower: float              # 区间下界
    upper: float              # 区间上界
    payoff: float             # 区间内固定收益
    tau: float                # 期限（年）
    r: float = 0.03
    q: float = 0.0
    vol: float = 0.20


class DigitalRangePricer:
    """数字区间期权定价器 —— 解析解

    如果到期时标的价格在 [lower, upper] 区间内，支付固定收益 payoff。
    否则支付 0。
    价格 = payoff × D(t,T) × [N(d2_lower) - N(d2_upper)]
    """

    def price(self, params: DigitalRangeParams, return_details: bool = False):
        """定价数字区间期权"""
        S, L, U = params.spot, params.lower, params.upper
        tau = params.tau
        vol, r, q = params.vol, params.r, params.q

        if tau <= 1e-10:
            in_range = (S >= L) and (S <= U)
            price = params.payoff * np.exp(-r * tau) if in_range else 0
            return {"price": price, "method": "digital_range_intrinsic"} if return_details else price

        sqrt_tau = np.sqrt(tau)
        Dr = np.exp(-r * tau)
        F = S * np.exp((r - q) * tau)

        d2_L = (np.log(F / L) - 0.5 * vol ** 2 * tau) / (vol * sqrt_tau)
        d2_U = (np.log(F / U) - 0.5 * vol ** 2 * tau) / (vol * sqrt_tau)

        prob = norm.cdf(d2_L) - norm.cdf(d2_U)
        price = float(params.payoff * Dr * prob)

        if return_details:
            return {
                "price": price,
                "probability": float(prob),
                "discount_factor": float(Dr),
                "method": "digital_range_analytic",
            }
        return price

    def greeks(self, params: DigitalRangeParams) -> dict:
        """解析 + 数值 Greeks"""
        S = params.spot
        base = self.price(params, return_details=True)
        base_price = base["price"]

        eps = 0.01
        p_up = self.price(DigitalRangeParams(**{**vars(params), "spot": S * (1 + eps)}))
        p_dn = self.price(DigitalRangeParams(**{**vars(params), "spot": S * (1 - eps)}))
        delta = (p_up - p_dn) / (2 * S * eps)

        dt = 1 / 365
        p_later = self.price(DigitalRangeParams(**{**vars(params), "tau": max(params.tau - dt, 0)}))
        theta = (p_later - base_price) / dt

        return {
            "price": base_price,
            "probability": base.get("probability", 0),
            "delta": delta,
            "theta": theta,
        }
