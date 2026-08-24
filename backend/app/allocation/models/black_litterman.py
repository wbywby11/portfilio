"""Black-Litterman 资产配置模型实现.

基于 Black & Litterman (1992) 理论框架，融合市场均衡与投资者主观观点，
通过贝叶斯推断得到后验收益分布，并在此基础上进行均值-方差优化。

核心流程
--------
1. 逆优化推导市场隐含收益：π = δ·Σ·w_mkt
2. 构建观点矩阵 P、观点收益 Q、Idzorek 方法构建 Omega
3. 贝叶斯融合：后验均值 μ_BL 和后验协方差 Σ_BL
4. 使用后续收益进行 MVO 优化

关键参数
--------
- risk_aversion (δ): 风险厌恶系数，通常取 2-3
- tau (τ): 不确定性标量，0 = 自动 (1/T)
- views: 投资观点（绝对/相对）
- view_confidences: 观点置信度 (0-100%)
- cov_method: 协方差估计方法 (ledoit_wolf / sample)

参考文献
--------
- Black, F. & Litterman, R. (1992). Global Portfolio Optimization.
  Financial Analysts Journal, 48(5), 28-43.
- Idzorek, T. (2005). A Step-By-Step Guide to the Black-Litterman Model.
"""

from __future__ import annotations

from typing import Dict, Any

import numpy as np
import pandas as pd
from loguru import logger

from app.formula.returns import compute_simple_returns
from app.formula.covariance import compute_covariance
from app.solvers.slsqp_solver import solve_slsqp
from app.allocation.models.base import BaseStrategyModel


# ============================================================
# 模块级常量
# ============================================================
DEFAULT_LOOKBACK_DAYS: int = 252
DEFAULT_RISK_AVERSION: float = 2.5
TAU_AUTO_SENTINEL: float = 0.0
TAU_MIN: float = 0.001
TAU_MAX: float = 0.5
ANNUALIZATION_FACTOR: int = 260
DEFAULT_RISK_FREE_RATE: float = 0.02
DEFAULT_CONFIDENCE: float = 50.0
CONFIDENCE_LOWER_CLAMP: float = 0.0
CONFIDENCE_UPPER_CLAMP: float = 0.9999999999
CONDITION_NUMBER_THRESHOLD: float = 1e10
REGULARIZATION_EPSILON: float = 1e-8
DEFAULT_TARGET_RETURN: float = 0.08


class BlackLittermanOptimization(BaseStrategyModel):
    """Black-Litterman 贝叶斯资产配置模型.

    融合市场均衡与投资者主观观点，通过逆优化推导市场隐含收益，
    利用贝叶斯公式将观点信息融入后验收益分布，最后使用后续收益 MVO 优化。
    """

    @classmethod
    def get_param_schema(cls):
        """返回 Black-Litterman 模型的参数 Schema."""
        from app.allocation.models.param_schema import StrategyParamSchema, ParamSchema

        return StrategyParamSchema(
            strategy_type="black_litterman",
            display_name="Black-Litterman 贝叶斯",
            description=(
                "融合市场均衡与投资者主观观点的贝叶斯资产配置模型。"
                "逆优化推导市场隐含收益，Idzorek方法融合主观观点，贝叶斯后验MVO优化。"
            ),
            params=[
                ParamSchema(
                    name="risk_aversion",
                    label="风险厌恶系数",
                    type="number",
                    default=2.5,
                    required=False,
                    description="衡量投资者对风险的厌恶程度，通常取 2-3",
                ),
                ParamSchema(
                    name="tau",
                    label="不确定性标量",
                    type="number",
                    default=0.0,
                    required=False,
                    min_value=0.0,
                    max_value=1.0,
                    description=(
                        "0 = 自动计算 (1/回看期)；手动设定范围 0.001-1.0，值越大表示越大不确定性"
                    ),
                    group="advanced",
                ),
                ParamSchema(
                    name="lookback_days",
                    label="回看天数",
                    type="number",
                    default=252,
                    required=False,
                    description="用于估计协方差矩阵的历史数据天数",
                ),
                ParamSchema(
                    name="cov_method",
                    label="协方差估计方法",
                    type="select",
                    default="ledoit_wolf",
                    required=False,
                    options=[
                        ("ledoit_wolf", "Ledoit-Wolf 收缩估计（推荐，更稳健）"),
                        ("sample", "样本协方差（经典，但可能不稳定）"),
                    ],
                    group="advanced",
                ),
                ParamSchema(
                    name="optimization_mode",
                    label="优化模式",
                    type="select",
                    default="max_sharpe",
                    required=False,
                    options=[
                        ("max_sharpe", "最大夏普比率"),
                        ("min_variance", "最小方差"),
                        ("target_return", "目标收益"),
                    ],
                ),
                ParamSchema(
                    name="target_return",
                    label="目标年化收益率",
                    type="number",
                    default=0.08,
                    required=False,
                    description="仅在 '目标收益（最小方差）' 模式下生效",
                    condition={"field": "optimization_mode", "value": "target_return"},
                ),
                ParamSchema(
                    name="min_weight",
                    label="单资产最小权重",
                    type="number",
                    default=0.0,
                    required=False,
                    description="每个资产的最小配置比例",
                ),
                ParamSchema(
                    name="max_weight",
                    label="单资产最大权重",
                    type="number",
                    default=1.0,
                    required=False,
                    description="每个资产的最大配置比例",
                ),
                ParamSchema(
                    name="risk_free_rate",
                    label="无风险利率",
                    type="number",
                    default=0.02,
                    required=False,
                    description="用于计算夏普比率（全系统统一口径 0.02）",
                    group="advanced",
                ),
                ParamSchema(
                    name="views",
                    label="投资观点",
                    type="dict",
                    default=None,
                    required=False,
                    description=(
                        '观点定义。格式: {"v1": {"type": "absolute", "asset": "资产名", "return": 0.08}, '
                        '"v2": {"type": "relative", "long": "资产A", "short": "资产B", "return": 0.03}}'
                    ),
                ),
                ParamSchema(
                    name="view_confidences",
                    label="观点置信度",
                    type="dict",
                    default=None,
                    required=False,
                    description=(
                        '每个观点的置信度 (0-100%)，格式: {"v1": 70, "v2": 50}'
                    ),
                ),
            ],
        )

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """计算 Black-Litterman 模型的资产配置权重.

        核心流程：
        1. 输入数据检查与验证
        2. 估计协方差矩阵（年化）
        3. 计算 tau（不确定性标量）——控制模型不确定性的关键参数
        4. 逆优化推导市场隐含收益 π
        5. 构建观点矩阵与 Omega
        6. 贝叶斯后验推断 μ_BL, Σ_BL
        7. MVO 优化得到最终权重
        """
        if prices.empty:
            raise ValueError("输入价格数据为空，无法进行 Black-Litterman 配置")

        # ---- 解析参数 ----
        lookback_days = int(params.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
        delta = float(params.get("risk_aversion", DEFAULT_RISK_AVERSION))
        tau_param = float(params.get("tau", TAU_AUTO_SENTINEL))
        cov_method = params.get("cov_method", "ledoit_wolf")
        optimization_mode = params.get("optimization_mode", "max_sharpe")
        min_weight = float(params.get("min_weight", 0.0))
        max_weight = float(params.get("max_weight", 1.0))
        risk_free_rate = float(params.get("risk_free_rate", DEFAULT_RISK_FREE_RATE))
        views_raw = params.get("views") or {}
        confidences_raw = params.get("view_confidences") or {}

        logger.info(
            "Black-Litterman 配置开始 | lookback={}, δ={}, τ_param={}, "
            "cov={}, mode={}, 观点数={}",
            lookback_days, delta, tau_param, cov_method, optimization_mode, len(views_raw),
        )

        # ---- 1. 截取回看窗口 ----
        prices_trimmed = prices.tail(lookback_days + 1)
        returns = compute_simple_returns(prices_trimmed).dropna(axis=1, how="all")

        assets = list(returns.columns)
        n = len(assets)
        T = returns.shape[0]

        if n < 2:
            logger.debug("有效资产不足（少于 2 个），退回等权配置: {}", assets)
            return pd.Series(1.0 / max(n, 1), index=prices.columns).fillna(0.0)

        logger.debug("有效资产 {} 个: {}", n, assets)

        # ---- 2. 协方差矩阵 ----
        Sigma = compute_covariance(returns, method=cov_method).values
        Sigma_annual = Sigma * ANNUALIZATION_FACTOR

        # ---- 3. Tau 计算 ----
        if tau_param <= TAU_AUTO_SENTINEL:
            tau = min(TAU_MAX, max(TAU_MIN, 1.0 / T))
            logger.debug("τ 自动计算: 1/{} = {:.6f}", T, tau)
        else:
            tau = tau_param
            logger.debug("τ 手动设定: {:.6f}", tau)

        # ---- 4. 逆优化推导市场隐含收益 π = δ·Σ·w_mkt ----
        # 假设市场均衡权重为等权（无外部市场组合输入时的合理默认）
        w_mkt = np.ones(n) / n
        pi = delta * Sigma_annual @ w_mkt
        logger.debug("市场隐含收益 π: {}", np.round(pi, 6).tolist())

        # ---- 5. 构建观点矩阵 P, Q 和 Omega ----
        if views_raw and len(views_raw) > 0:
            P, Q = self._build_views(views_raw, assets)
            Omega = self._build_omega_idzorek(P, Sigma_annual, confidences_raw, views_raw)
        else:
            logger.warning("未提供观点，使用无观点的纯市场均衡 MVO 优化")
            P = np.zeros((0, n))
            Q = np.array([])
            Omega = np.zeros((0, 0))

        if P.shape[0] > 0:
            logger.debug("观点矩阵 P 维度: {}×{}, Q 维度: {}", P.shape[0], P.shape[1], Q.shape)

        # ---- 6. 贝叶斯后验 ----
        if P.shape[0] > 0:
            mu_BL, Sigma_BL = self._posterior(pi, Sigma_annual, tau, P, Q, Omega)
        else:
            mu_BL = pi
            Sigma_BL = Sigma_annual

        logger.debug("后验均值 μ_BL: {}", np.round(mu_BL, 6).tolist())

        # ---- 7. MVO 优化 ----
        target_return = float(params.get("target_return", DEFAULT_TARGET_RETURN))
        weights = self._optimize(
            mu_BL, Sigma_BL, assets, optimization_mode,
            min_weight, max_weight, risk_free_rate, target_return,
        )

        logger.info("Black-Litterman 配置完成 | 权重: {}", weights.to_dict())
        return weights

    # ================================================================
    # 内部方法
    # ================================================================

    def _build_views(self, views_raw: dict, assets: list) -> tuple:
        """从观点字典构建 P 矩阵和 Q 向量.

        views_raw 格式示例::

            {
                "view_1": {"type": "absolute", "asset": "资产名", "return": 0.08},
                "view_2": {"type": "relative", "long": "资产A", "short": "资产B", "return": 0.03},
            }
        """
        if not views_raw:
            raise ValueError("观点字典为空，请提供至少一个观点")

        n = len(assets)
        asset_index = {a: i for i, a in enumerate(assets)}
        view_keys = sorted(views_raw.keys())

        P_rows = []
        Q_vals = []
        skipped_rows = []

        for k in view_keys:
            view = views_raw[k]
            view_type = view.get("type", "absolute")
            ret = float(view.get("return", 0.0))

            if view_type == "absolute":
                asset_name = view.get("asset", "")
                if asset_name not in asset_index:
                    logger.warning(
                        "观点 '{}' 引用了不存在的资产 '{}'，已跳过。可用资产: {}",
                        k, asset_name, list(asset_index.keys()),
                    )
                    skipped_rows.append(k)
                    continue
                row = np.zeros(n)
                row[asset_index[asset_name]] = 1.0
                P_rows.append(row)
                Q_vals.append(ret)

            elif view_type == "relative":
                long_name = view.get("long", "")
                short_name = view.get("short", "")
                missing = []
                if long_name not in asset_index:
                    missing.append(f"多头 '{long_name}'")
                if short_name not in asset_index:
                    missing.append(f"空头 '{short_name}'")
                if missing:
                    logger.warning(
                        "观点 '{}' 引用了不存在的资产 ({})，已跳过。可用资产: {}",
                        k, ", ".join(missing), list(asset_index.keys()),
                    )
                    skipped_rows.append(k)
                    continue
                row = np.zeros(n)
                row[asset_index[long_name]] = 1.0
                row[asset_index[short_name]] = -1.0
                P_rows.append(row)
                Q_vals.append(ret)
            else:
                logger.warning(
                    "观点 '{}' 的 type 不合法: '{}'，仅支持 'absolute'/'relative'，已跳过",
                    k, view_type,
                )
                skipped_rows.append(k)

        if not P_rows:
            raise ValueError("所有观点均无效（引用了不存在的资产或类型不合法），无法构建观点矩阵")

        # 过滤无效观点
        valid_mask = [i for i, k in enumerate(view_keys) if k not in skipped_rows]
        P = np.array(P_rows)
        Q = np.array(Q_vals)

        logger.info("共 {} 个有效观点，剩余 {} 个无效观点", P.shape[0], len(skipped_rows))
        return P, Q

    def _build_omega_idzorek(
        self, P: np.ndarray, Sigma: np.ndarray,
        confidences_raw: dict, views_raw: dict,
    ) -> np.ndarray:
        """使用 Idzorek 方法构建观点不确定性矩阵 Ω.

        Idzorek (2005) 提出的核心思想是：Omega 矩阵不需要人为设定，而是通过
        confidence（置信度）来反推。

        Args:
            P: K×N 观点矩阵
            Sigma: N×N 年化协方差矩阵
            confidences_raw: {view_key: confidence_percent}
            views_raw: 原始观点字典（用于排序 key）

        Returns:
            K×K 对角 Omega 矩阵
        """
        k = P.shape[0]
        view_keys = sorted(views_raw.keys())

        P_Sigma_Pt = P @ Sigma @ P.T
        omega_diag = np.zeros(k)

        for i, vk in enumerate(view_keys[:k]):
            raw_confidence = float(confidences_raw.get(vk, DEFAULT_CONFIDENCE))
            c_i = np.clip(raw_confidence / 100.0, CONFIDENCE_LOWER_CLAMP, CONFIDENCE_UPPER_CLAMP)
            p_sigma_pt_ii = P_Sigma_Pt[i, i]

            if p_sigma_pt_ii <= 0:
                logger.warning(
                    "观点 '{}' 对应的 (P·Σ·P^T)[{},{}] = {:.6e} ≤ 0，使用正则化值 {:.1e}",
                    vk, i, i, p_sigma_pt_ii, REGULARIZATION_EPSILON,
                )
                p_sigma_pt_ii = REGULARIZATION_EPSILON

            # Idzorek 公式：omega_i = (1/c_i - 1) * P_i · Σ · P_i^T
            omega_diag[i] = (1.0 / c_i - 1.0) * p_sigma_pt_ii

        Omega = np.diag(omega_diag)
        logger.debug("Omega 对角线: {}", np.round(omega_diag, 8).tolist())
        return Omega

    def _safe_inv(self, matrix: np.ndarray) -> np.ndarray:
        """安全矩阵求逆：必要时添加正则化，统一使用伪逆.

        为保证数值稳定性，统一处理流程：
        1. 检查条件数
        2. 条件数 > 阈值时添加正则化 ε·I
        3. 使用 np.linalg.pinv
        """
        n = matrix.shape[0]
        cond = np.linalg.cond(matrix)

        if cond > CONDITION_NUMBER_THRESHOLD:
            logger.warning(
                "矩阵条件数过大 ({:.2e})，超过阈值 {:.1e}，添加正则化 ε={:.1e}",
                cond, CONDITION_NUMBER_THRESHOLD, REGULARIZATION_EPSILON,
            )
            matrix = matrix + REGULARIZATION_EPSILON * np.eye(n)

        return np.linalg.pinv(matrix)

    def _posterior(
        self, pi: np.ndarray, Sigma: np.ndarray, tau: float,
        P: np.ndarray, Q: np.ndarray, Omega: np.ndarray,
    ) -> tuple:
        """计算后验收益均值和后验协方差矩阵.

        贝叶斯融合公式（Black-Litterman 经典形式）::

            M       = inv(inv(τΣ) + P^T inv(Ω) P)
            μ_BL    = M · (inv(τΣ)·π + P^T inv(Ω)·Q)
            Σ_BL    = Σ + M
        """
        tau_Sigma = tau * Sigma
        inv_tau_Sigma = self._safe_inv(tau_Sigma)
        inv_Omega = self._safe_inv(Omega)

        M_inner = inv_tau_Sigma + P.T @ inv_Omega @ P
        M = self._safe_inv(M_inner)

        mu_BL = M @ (inv_tau_Sigma @ pi + P.T @ inv_Omega @ Q)
        Sigma_BL = Sigma + M

        return mu_BL, Sigma_BL

    @staticmethod
    def _reachable_return_range(
        mu: np.ndarray, min_w: float, max_w: float
    ) -> tuple[float, float]:
        """在 sum(w)=1 与 w∈[min_w, max_w] 约束下，组合预期收益的可达上下限.

        线性目标 + 盒式约束 + 单位和约束，最优解在顶点上：
        先给所有资产垫 min_w，再按收益排序将剩余权重贪心分配到上限。
        """
        n = len(mu)

        def _extreme(descending: bool) -> float:
            order = np.argsort(-mu if descending else mu)
            w = np.full(n, min_w, dtype=float)
            remaining = 1.0 - min_w * n
            for idx in order:
                if remaining <= 0:
                    break
                add = min(max_w - min_w, remaining)
                w[idx] += add
                remaining -= add
            return float(w @ mu)

        return _extreme(descending=False), _extreme(descending=True)

    def _optimize(
        self, mu_BL: np.ndarray, Sigma_BL: np.ndarray,
        assets: list, mode: str,
        min_w: float = 0.0, max_w: float = 1.0,
        rf: float = 0.03, target_return: float = 0.08,
    ) -> pd.Series:
        """使用后续收益进行 MVO 优化 (max_sharpe / min_variance / target_return).

        参考 mean_variance.py 的 SLSQP 调用方式。
        """
        n = len(assets)
        bounds = [tuple((min_w, max_w)) for _ in range(n)]

        # 约束：权重和 = 1
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        x0 = np.full(n, 1.0 / n)

        if mode == "min_variance":
            objective = lambda w: float(w @ Sigma_BL @ w)
        elif mode == "target_return":
            if n < 2:
                raise ValueError(
                    f"目标收益模式需要至少 2 个资产，当前只有 {n} 个，请切换至 min_variance 或 max_sharpe 模式"
                )
            # 可行域预检：目标收益必须落在后验收益的可达区间内，
            # 否则 SLSQP 只会报 "Positive directional derivative" 这类无法定位的错误。
            # 可达上下限受 max_w / min_w 约束：按后验收益排序后贪心填权重。
            lo, hi = self._reachable_return_range(mu_BL, min_w, max_w)
            if not (lo - 1e-9 <= target_return <= hi + 1e-9):
                raise ValueError(
                    f"目标年化收益率 {target_return:.2%} 超出当前可达范围 "
                    f"[{lo:.2%}, {hi:.2%}]。\n"
                    f"可达范围由贝叶斯后验收益 μ_BL 与权重约束 "
                    f"[{min_w:.0%}, {max_w:.0%}] 共同决定。\n"
                    f"建议：将目标收益调入上述区间、放宽 max_weight、或通过看涨观点抬高 μ_BL"
                )
            constraints.append({
                "type": "eq",
                "fun": lambda w: float(w @ mu_BL) - target_return,
            })
            objective = lambda w: float(w @ Sigma_BL @ w)
        elif mode == "max_sharpe":
            def objective(w):
                port_ret = float(w @ mu_BL)
                port_vol = float(np.sqrt(max(w @ Sigma_BL @ w, 1e-12)))
                return -(port_ret - rf) / port_vol
        else:
            raise ValueError(f"不支持的优化模式: {mode}")

        w_opt, success, message = solve_slsqp(
            x0=x0,
            objective=objective,
            bounds=bounds,
            constraints=constraints,
        )

        # 优化失败不静默降级为等权：等权会被当成 BL 的配置结果展示，掩盖失败
        if not success:
            raise RuntimeError(
                f"Black-Litterman MVO 优化失败: {message}\n"
                f"模式={mode}, 资产数={n}, min_w={min_w}, max_w={max_w}\n"
                "请检查观点设置、协方差质量或权重约束是否可行"
            )

        w_opt = np.maximum(w_opt, 0.0)
        total = float(w_opt.sum())
        if total > 0:
            w_opt = w_opt / total
        return pd.Series(w_opt, index=assets)
