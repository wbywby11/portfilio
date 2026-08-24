"""
期权定价 —— 数值方法与波动率模型（P9 治理自 core.py 拆分）.

包含：二叉树（美式）、有限差分（PDE）、SABR 波动率曲面、
Dupire 局部波动率。
方法体自 app/options/core.py 逐字平移，core.py 保留兼容再导出。
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Optional

from app.options.pricing_vanilla import MarketParams, OptionPricer


# ══════════════════════════════════════════════════════
#  第十四部分：二叉树定价器（美式期权）
# ══════════════════════════════════════════════════════

@dataclass
class BinomialTreeParams:
    """二叉树定价参数"""
    spot: float              # 现价
    strike: float            # 行权价
    tau: float               # 期限（年）
    vol: float               # 波动率
    r: float = 0.03          # 无风险利率
    q: float = 0.0           # 分红率
    n_steps: int = 200       # 步数
    option_type: str = "call"  # call / put
    exercise_style: str = "american"  # american / european


class BinomialTreePricer:
    """CRR 二叉树定价器 —— 支持美式/欧式期权

    采用 Cox-Ross-Rubinstein 参数化：
        u = exp(vol * sqrt(dt))
        d = 1 / u
        p = (exp((r-q)*dt) - d) / (u - d)
    """

    def price(self, params: BinomialTreeParams, return_details: bool = False):
        """二叉树定价"""
        S, K, tau, vol = params.spot, params.strike, params.tau, params.vol
        r, q = params.r, params.q
        n = params.n_steps

        if tau <= 1e-10:
            if params.option_type == "call":
                payoff = max(S - K, 0)
            else:
                payoff = max(K - S, 0)
            price = payoff * np.exp(-r * tau)
            return {"price": price, "method": "binomial_intrinsic"} if return_details else price

        dt = tau / n
        u = np.exp(vol * np.sqrt(dt))
        d = 1.0 / u
        disc = np.exp(-r * dt)
        p = (np.exp((r - q) * dt) - d) / (u - d)

        # 构建终端节点价格
        S_nodes = S * u ** np.arange(n, -1, -1) * d ** np.arange(0, n + 1)

        # 终端期权价值
        if params.option_type == "call":
            V = np.maximum(S_nodes - K, 0)
        else:
            V = np.maximum(K - S_nodes, 0)

        # 回推
        for i in range(n - 1, -1, -1):
            # 期望折现
            V = disc * (p * V[:-1] + (1 - p) * V[1:])
            S_nodes = S_nodes[:-1] / u  # 缩减一层

            # 美式提前行权检查
            if params.exercise_style == "american":
                if params.option_type == "call":
                    intrinsic = np.maximum(S_nodes - K, 0)
                else:
                    intrinsic = np.maximum(K - S_nodes, 0)
                V = np.maximum(V, intrinsic)

        price = float(V[0])
        method = f"binomial_{params.exercise_style}_{params.option_type}"

        if return_details:
            return {"price": price, "method": method}
        return price

    def greeks(self, params: BinomialTreeParams) -> dict:
        """Bump & Reprice Greeks"""
        base = self.price(params, return_details=True)["price"]
        S, vol, r = params.spot, params.vol, params.r
        eps = 0.01

        def bumped(**kw):
            p = BinomialTreeParams(**{**vars(params), **kw})
            return self.price(p)

        delta = (bumped(spot=S*(1+eps)) - bumped(spot=S*(1-eps))) / (2*S*eps)
        gamma = (bumped(spot=S*(1+eps)) - 2*base + bumped(spot=S*(1-eps))) / (S*eps)**2
        vega = (bumped(vol=vol*(1+eps)) - bumped(vol=vol*(1-eps))) / (2*vol*eps*100)
        dt = 1 / 365
        theta = (bumped(tau=max(params.tau-dt, 0)) - base) / dt
        rho = (bumped(r=r+eps) - bumped(r=r-eps)) / (2*eps*100)

        return {"price": base, "delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


# ══════════════════════════════════════════════════════
#  第十五部分：有限差分法定价器（PDE 求解）
# ══════════════════════════════════════════════════════

@dataclass
class FiniteDifferenceParams:
    """有限差分法参数"""
    spot: float              # 现价
    strike: float            # 行权价
    tau: float               # 期限（年）
    vol: float               # 波动率
    r: float = 0.03          # 无风险利率
    q: float = 0.0           # 分红率
    n_space: int = 200       # 空间网格点数
    n_time: int = 500        # 时间网格点数
    option_type: str = "call"  # call / put
    exercise_style: str = "european"  # european / american
    s_max_factor: float = 5.0  # S_max = s_max_factor * S0


class FiniteDifferencePricer:
    """有限差分法定价器 —— Crank-Nicolson 隐式-显式混合方案

    求解 Black-Scholes PDE：
        ∂V/∂t + (1/2)σ²S²∂²V/∂S² + (r-q)S∂V/∂S - rV = 0

    采用 Crank-Nicolson 时间离散（无条件稳定，二阶精度）。
    """

    def price(self, params: FiniteDifferenceParams, return_details: bool = False):
        """有限差分法定价"""
        S0, K, tau, vol = params.spot, params.strike, params.tau, params.vol
        r, q = params.r, params.q
        M = params.n_space  # 空间点数
        N = params.n_time   # 时间点数

        if tau <= 1e-10:
            if params.option_type == "call":
                price = max(S0 - K, 0) * np.exp(-r * tau)
            else:
                price = max(K - S0, 0) * np.exp(-r * tau)
            return {"price": price, "method": "fd_intrinsic"} if return_details else price

        S_max = params.s_max_factor * S0
        dS = S_max / M
        dt = tau / N

        # 空间网格
        S_grid = np.linspace(0, S_max, M + 1)

        # 终端条件
        if params.option_type == "call":
            V = np.maximum(S_grid - K, 0)
        else:
            V = np.maximum(K - S_grid, 0)

        # Crank-Nicolson 系数
        alpha = 0.5 * dt * ((r - q) * np.arange(M + 1) - vol**2 * np.arange(M + 1)**2)
        beta = dt * (vol**2 * np.arange(M + 1)**2 + r)
        gamma_coeff = 0.5 * dt * (-(r - q) * np.arange(M + 1) - vol**2 * np.arange(M + 1)**2)

        # 时间回推
        for n in range(N):
            V_new = np.zeros(M + 1)
            for i in range(1, M):
                V_new[i] = (alpha[i] * V[i-1] + (1 - beta[i]) * V[i] + gamma_coeff[i] * V[i+1]) / (1 + beta[i])

            # 边界条件
            if params.option_type == "call":
                V_new[0] = 0
                V_new[M] = (S_max - K * np.exp(-r * (tau - (n + 1) * dt)))
            else:
                V_new[0] = K * np.exp(-r * (tau - (n + 1) * dt))
                V_new[M] = 0

            # 美式提前行权
            if params.exercise_style == "american":
                if params.option_type == "call":
                    V_new = np.maximum(V_new, np.maximum(S_grid - K, 0))
                else:
                    V_new = np.maximum(V_new, np.maximum(K - S_grid, 0))

            V = V_new

        # 插值得到 S0 处的价格
        idx = int(S0 / dS)
        if idx >= M:
            idx = M - 1
        w = (S0 - S_grid[idx]) / dS
        price = float(V[idx] * (1 - w) + V[idx + 1] * w)
        method = f"fd_crank_nicolson_{params.exercise_style}_{params.option_type}"

        if return_details:
            return {"price": price, "method": method}
        return price

    def greeks(self, params: FiniteDifferenceParams) -> dict:
        """Bump & Reprice Greeks"""
        base = self.price(params, return_details=True)["price"]
        S, vol, r = params.spot, params.vol, params.r
        eps = 0.01

        def bumped(**kw):
            p = FiniteDifferenceParams(**{**vars(params), **kw})
            return self.price(p)

        delta = (bumped(spot=S*(1+eps)) - bumped(spot=S*(1-eps))) / (2*S*eps)
        vega = (bumped(vol=vol*(1+eps)) - bumped(vol=vol*(1-eps))) / (2*vol*eps*100)
        dt_day = 1 / 365
        theta = (bumped(tau=max(params.tau-dt_day, 0)) - base) / dt_day

        return {"price": base, "delta": delta, "vega": vega, "theta": theta}


# ══════════════════════════════════════════════════════
#  第十六部分：SABR/SVI 波动率曲面拟合
# ══════════════════════════════════════════════════════

@dataclass
class SABRParams:
    """SABR 模型参数

    SABR 模型: dF = α F^β dW₁, dα = ν α dW₂, dW₁dW₂ = ρ dt
    """
    alpha: float     # 初始波动率 α
    beta: float      # CEV 指数 β (0 ≤ β ≤ 1)
    rho: float       # 相关系数 ρ (-1 < ρ < 1)
    nu: float        # 波动率的波动率 ν
    forward: float   # 远期价格 F


class SABRVolSurface:
    """SABR 波动率曲面 —— Hagan et al. (2002) 渐近展开

    从市场期权价格中拟合参数化波动率曲面。
    支持：
    - 给定参数 → 计算隐含波动率曲面
    - 给定市场数据 → 最小二乘拟合 SABR 参数
    """

    @staticmethod
    def implied_vol(params: SABRParams, strike: float, tau: float) -> float:
        """Hagan 渐近公式计算 SABR 隐含波动率

        Args:
            params: SABR 参数
            strike: 行权价
            tau: 期限（年）

        Returns:
            float: 隐含波动率
        """
        F, alpha, beta, rho, nu = params.forward, params.alpha, params.beta, params.rho, params.nu
        K = strike

        if abs(F - K) < 1e-10:
            # ATM 公式
            Fmid = F
            A = alpha / (Fmid ** (1 - beta))
            B = 1 + ((1 - beta)**2 / 24 * alpha**2 / Fmid**(2*(1-beta))
                     + rho * beta * nu * alpha / (4 * Fmid**(1-beta))
                     + (2 - 3*rho**2) * nu**2 / 24) * tau
            return float(A * B)

        Fmid = np.sqrt(F * K) * ((F / K) ** ((1 - beta) / 2))
        logFK = np.log(F / K)

        # z 和 x(z)
        z = nu / alpha * (F * K) ** ((1 - beta) / 2) * logFK
        x_z = np.log((np.sqrt(1 - 2*rho*z + z**2) + z - rho) / (1 - rho))

        if abs(x_z) < 1e-10:
            x_z = 1.0

        # Hagan 公式
        prefix = alpha / ((F * K) ** ((1 - beta) / 2) * (1 + (1-beta)**2/24 * logFK**2
                          + (1-beta)**4/1920 * logFK**4))

        correction = 1 + ((1-beta)**2/24 * alpha**2/(F*K)**(1-beta)
                        + rho*beta*nu*alpha/(4*(F*K)**((1-beta)/2))
                        + (2-3*rho**2)*nu**2/24) * tau

        vol = float(prefix * (z / x_z) * correction)
        return max(vol, 1e-6)

    def calibrate(self, market_vols: List[dict], tau: float, forward: float) -> dict:
        """从市场数据拟合 SABR 参数

        Args:
            market_vols: [{"strike": K, "vol": iv}, ...]
            tau: 期限
            forward: 远期价格

        Returns:
            dict: {"params": SABRParams, "error": float}
        """
        from scipy.optimize import minimize

        strikes = np.array([m["strike"] for m in market_vols])
        target_vols = np.array([m["vol"] for m in market_vols])

        def objective(x):
            alpha, beta, rho, nu = x
            if alpha <= 0 or beta < 0 or beta > 1 or rho <= -1 or rho >= 1 or nu <= 0:
                return 1e10
            sp = SABRParams(alpha=alpha, beta=beta, rho=rho, nu=nu, forward=forward)
            model_vols = np.array([self.implied_vol(sp, k, tau) for k in strikes])
            return float(np.sum((model_vols - target_vols) ** 2))

        # 初始猜测
        x0 = [0.2, 0.5, -0.1, 0.3]
        result = minimize(objective, x0, method='Nelder-Mead',
                          options={'maxiter': 1000, 'xatol': 1e-6})

        alpha, beta, rho, nu = result.x
        params = SABRParams(alpha=alpha, beta=beta, rho=rho, nu=nu, forward=forward)

        model_vols = np.array([self.implied_vol(params, k, tau) for k in strikes])
        error = float(np.sqrt(np.mean((model_vols - target_vols) ** 2)))

        return {"params": params, "error": error, "model_vols": model_vols.tolist()}

    def surface(self, params: SABRParams, strikes: List[float], taus: List[float]) -> dict:
        """生成完整波动率曲面

        Args:
            params: SABR 参数
            strikes: 行权价网格
            taus: 期限网格（年）

        Returns:
            dict: {"strikes": [...], "taus": [...], "vols": [[...], ...]}
        """
        vols = []
        for t in taus:
            row = [self.implied_vol(params, k, t) for k in strikes]
            vols.append(row)
        return {"strikes": strikes, "taus": taus, "vols": vols}


# ══════════════════════════════════════════════════════
#  第十七部分：Dupire 局部波动率模型
# ══════════════════════════════════════════════════════

@dataclass
class LocalVolParams:
    """局部波动率参数"""
    spot: float              # 现价
    strike: float            # 行权价
    tau: float               # 期限（年）
    r: float = 0.03          # 无风险利率
    q: float = 0.0           # 分红率
    n_space: int = 100       # 空间网格点数
    n_time: int = 200        # 时间网格点数
    option_type: str = "call"


class LocalVolPricer:
    """Dupire 局部波动率模型定价器

    从隐含波动率曲面通过 Dupire 公式提取局部波动率：
        σ_local²(K,T) = (∂C/∂T + (r-q)K∂C/∂K + qC) / ((1/2)K²∂²C/∂K²)

    然后用局部波动率通过有限差分法求解 PDE 定价。
    """

    def __init__(self, implied_vol_surface: Optional[dict] = None):
        """
        Args:
            implied_vol_surface: {"strikes": [...], "taus": [...], "vols": [[...], ...]}
        """
        self.iv_surface = implied_vol_surface

    @staticmethod
    def dupire_local_vol(strikes: List[float], taus: List[float],
                         iv_matrix: List[List[float]],
                         r: float, q: float, forward: float) -> dict:
        """从隐含波动率曲面提取局部波动率

        Args:
            strikes: 行权价网格
            taus: 期限网格（年）
            iv_matrix: 隐含波动率矩阵 shape=(len(taus), len(strikes))
            r: 无风险利率
            q: 分红率
            forward: 远期价格

        Returns:
            dict: {"strikes": [...], "taus": [...], "local_vols": [[...], ...]}
        """
        K_arr = np.array(strikes)
        T_arr = np.array(taus)
        iv_arr = np.array(iv_matrix)
        n_T = len(T_arr)
        n_K = len(K_arr)
        local_vols = np.zeros_like(iv_arr)

        dS = K_arr[1] - K_arr[0] if len(K_arr) > 1 else 1.0
        dT = T_arr[1] - T_arr[0] if len(T_arr) > 1 else 0.1

        for j in range(n_T):
            T = max(T_arr[j], 1e-6)
            for i in range(1, n_K - 1):
                K = K_arr[i]
                iv = iv_arr[j, i]

                # 数值导数
                if i > 0 and i < n_K - 1:
                    dC_dK = (iv_arr[j, i+1] - iv_arr[j, i-1]) / (2 * dS)
                    d2C_dK2 = (iv_arr[j, i+1] - 2*iv + iv_arr[j, i-1]) / (dS**2)
                else:
                    dC_dK = 0
                    d2C_dK2 = 0

                if j > 0 and j < n_T - 1:
                    dC_dT = (iv_arr[j+1, i] - iv_arr[j-1, i]) / (2 * dT)
                elif j == 0:
                    dC_dT = (iv_arr[min(1, n_T-1), i] - iv) / max(dT, 1e-6)
                else:
                    dC_dT = 0

                # Dupire 公式
                numerator = dC_dT + (r - q) * K * dC_dK + q * iv
                denominator = 0.5 * K**2 * d2C_dK2

                if denominator > 1e-10:
                    local_var = numerator / denominator
                    local_vols[j, i] = np.sqrt(max(local_var, 0.01))
                else:
                    local_vols[j, i] = iv  # 退化为隐含波动率

        # 边界填充
        local_vols[:, 0] = local_vols[:, 1]
        local_vols[:, -1] = local_vols[:, -2]

        return {
            "strikes": strikes,
            "taus": taus,
            "local_vols": local_vols.tolist(),
        }

    def price(self, params: LocalVolParams, return_details: bool = False):
        """局部波动率定价（使用有限差分法）"""
        S0, K, tau, r, q = params.spot, params.strike, params.tau, params.r, params.q

        if tau <= 1e-10:
            if params.option_type == "call":
                price = max(S0 - K, 0) * np.exp(-r * tau)
            else:
                price = max(K - S0, 0) * np.exp(-r * tau)
            return {"price": price, "method": "local_vol_intrinsic"} if return_details else price

        # 如果没有局部波动率曲面，退化为常数波动率 BS 定价
        if self.iv_surface is None:
            pricer = OptionPricer()
            mp = MarketParams(spot=S0, strike=K, tau=tau, vol=0.20, r=r, q=q)
            if params.option_type == "call":
                result = pricer.call(mp)
            else:
                result = pricer.put(mp)
            price = result.price
            method = "local_vol_fallback_bs"
        else:
            # 使用有限差分法 + 局部波动率
            M = params.n_space
            N = params.n_time
            S_max = 5.0 * S0
            dS = S_max / M
            dt = tau / N

            S_grid = np.linspace(0, S_max, M + 1)

            if params.option_type == "call":
                V = np.maximum(S_grid - K, 0)
            else:
                V = np.maximum(K - S_grid, 0)

            # 简单局部波动率：从曲面插值
            local_vol_grid = np.ones(M + 1) * 0.20  # 默认值

            for n in range(N):
                V_new = np.zeros(M + 1)
                for i in range(1, M):
                    Si = S_grid[i]
                    sigma_i = local_vol_grid[i]
                    ai = 0.5 * dt * ((r-q)*Si - sigma_i**2 * Si**2)
                    bi = dt * (sigma_i**2 * Si**2 + r)
                    gi = 0.5 * dt * (-(r-q)*Si - sigma_i**2 * Si**2)
                    V_new[i] = (ai*V[i-1] + (1-bi)*V[i] + gi*V[i+1]) / (1+bi)

                if params.option_type == "call":
                    V_new[0] = 0
                    V_new[M] = S_max - K * np.exp(-r*(tau-(n+1)*dt))
                else:
                    V_new[0] = K * np.exp(-r*(tau-(n+1)*dt))
                    V_new[M] = 0

                V = V_new

            idx = int(S0 / dS)
            if idx >= M:
                idx = M - 1
            w = (S0 - S_grid[idx]) / dS
            price = float(V[idx] * (1-w) + V[idx+1] * w)
            method = "local_vol_fd"

        if return_details:
            return {"price": price, "method": method}
        return price

    def greeks(self, params: LocalVolParams) -> dict:
        """Bump & Reprice Greeks"""
        base = self.price(params, return_details=True)["price"]
        S, r = params.spot, params.r
        eps = 0.01

        def bumped(**kw):
            p = LocalVolParams(**{**vars(params), **kw})
            return self.price(p)

        delta = (bumped(spot=S*(1+eps)) - bumped(spot=S*(1-eps))) / (2*S*eps)
        dt_day = 1 / 365
        theta = (bumped(tau=max(params.tau-dt_day, 0)) - base) / dt_day

        return {"price": base, "delta": delta, "theta": theta}
