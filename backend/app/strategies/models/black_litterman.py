"""Black-Litterman 资产配置模型实现.

基于 Black & Litterman (1992) 理论框架，融合市场均衡收益与投资者主观观点，
通过贝叶斯方法推导后验收益分布，并在此基础上进行均值-方差优化。

核心流程
--------
1. 逆优化推导市场隐含均衡收益率 π = δ·Σ·w_mkt
2. 构造观点矩阵 P、观点向量 Q、Idzorek 方法计算 Omega
3. 贝叶斯融合：后验均值 μ_BL 和后验协方差 Σ_BL
4. 使用后验参数进行 MVO 优化

关键参数
--------
- risk_aversion (δ): 风险厌恶系数，通常取 2-3
- tau (τ): 不确定性缩放因子，0 = 自动 (1/T)
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

from app.strategies.formula.returns import compute_simple_returns
from app.strategies.formula.covariance import compute_covariance
from app.strategies.solvers.slsqp_solver import solve_slsqp
from app.strategies.models.base import BaseStrategyModel

# ---------------------------------------------------------------------------
# 命名常量：避免魔法数字
# ---------------------------------------------------------------------------
ANNUALIZATION_FACTOR = 252          # 年化因子（交易日数）
TAU_AUTO_SENTINEL = 0.0             # tau = 0 表示自动计算模式
TAU_MIN = 0.001                     # tau 手动模式下限
TAU_MAX = 0.5                       # tau 手动模式上限
CONDITION_NUMBER_THRESHOLD = 1e10   # 矩阵条件数阈值，超过此值添加正则化
REGULARIZATION_EPSILON = 1e-8       # 正则化系数
CONFIDENCE_UPPER_CLAMP = 1.0 - 1e-10  # 置信度上限裁剪（防止除零）
CONFIDENCE_LOWER_CLAMP = 1e-10        # 置信度下限裁剪（防止无穷大）
DEFAULT_CONFIDENCE = 50.0           # 默认观点置信度 (%)
DEFAULT_RISK_AVERSION = 2.5         # 默认风险厌恶系数
DEFAULT_LOOKBACK_DAYS = 252         # 默认回看窗口
DEFAULT_RISK_FREE_RATE = 0.03       # 默认无风险利率
NUMERICAL_FLOOR = 1e-12             # 数值下限（防止 sqrt(0)）


class BlackLittermanOptimization(BaseStrategyModel):
    """Black-Litterman 贝叶斯资产配置模型.

    融合市场均衡收益与投资者主观观点，通过逆优化推导市场隐含收益率，
    再利用贝叶斯框架与主观观点进行融合，最终使用后验参数做 MVO 优化。
    """

    # ======================================================================
    # 参数 Schema
    # ======================================================================

    @classmethod
    def get_param_schema(cls):
        """返回 Black-Litterman 模型的参数 Schema."""
        from app.strategies.models.param_schema import StrategyParamSchema, ParamSchema

        return StrategyParamSchema(
            strategy_type="black_litterman",
            display_name="Black-Litterman 模型",
            description=(
                "融合市场均衡收益与投资者主观观点的贝叶斯资产配置模型。"
                "基于 Black & Litterman (1992) 理论框架，"
                "通过逆优化推导市场隐含收益率，再与主观观点进行贝叶斯融合。"
            ),
            params=[
                ParamSchema(
                    name="risk_aversion",
                    label="风险厌恶系数 (δ)",
                    type="number",
                    default=2.5,
                    min_value=0.5,
                    max_value=10.0,
                    step=0.1,
                    description="衡量投资者对风险的厌恶程度，通常取 2-3",
                ),
                ParamSchema(
                    name="tau",
                    label="不确定性缩放因子 (τ)",
                    type="number",
                    default=0.0,
                    min_value=0.0,
                    max_value=0.5,
                    step=0.001,
                    description=(
                        "0 = 自动计算 (1/样本数)。手动设置范围 0.001-0.5。"
                        "τ 过大会使结果退化为纯观点驱动"
                    ),
                ),
                ParamSchema(
                    name="lookback_days",
                    label="回看窗口 (天)",
                    type="number",
                    default=252,
                    min_value=60,
                    max_value=1260,
                    step=1,
                    description="用于估计协方差矩阵的历史数据天数",
                ),
                ParamSchema(
                    name="cov_method",
                    label="协方差估计方法",
                    type="select",
                    default="ledoit_wolf",
                    options=[
                        ("ledoit_wolf", "Ledoit-Wolf 收缩估计"),
                        ("sample", "样本协方差"),
                    ],
                    description="Ledoit-Wolf 收缩可减少估计误差，提高模型稳定性",
                ),
                ParamSchema(
                    name="optimization_mode",
                    label="优化模式",
                    type="select",
                    default="max_sharpe",
                    options=[
                        ("max_sharpe", "最大夏普比率"),
                        ("min_variance", "最小方差"),
                        ("target_return", "目标收益最小风险"),
                    ],
                    description="使用后验参数进行均值-方差优化的目标函数",
                ),
                ParamSchema(
                    name="target_return",
                    label="目标年化收益率",
                    type="number",
                    default=0.08,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                    description="仅在 '目标收益最小风险' 模式下生效",
                ),
                ParamSchema(
                    name="min_weight",
                    label="最小权重",
                    type="number",
                    default=0.0,
                    min_value=-1.0,
                    max_value=1.0,
                    step=0.01,
                    description="单个资产的最低配置比例",
                ),
                ParamSchema(
                    name="max_weight",
                    label="最大权重",
                    type="number",
                    default=1.0,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                    description="单个资产的最高配置比例",
                ),
                ParamSchema(
                    name="risk_free_rate",
                    label="无风险利率",
                    type="number",
                    default=0.03,
                    min_value=0.0,
                    max_value=0.2,
                    step=0.005,
                    description="用于计算夏普比率",
                ),
                ParamSchema(
                    name="views",
                    label="投资观点",
                    type="dict",
                    default={},
                    description=(
                        '观点定义。格式: {"v1": {"type": "absolute", "asset": "资产名", '
                        '"return": 0.08}, "v2": {"type": "relative", "long": "资产A", '
                        '"short": "资产B", "return": 0.03}}'
                    ),
                ),
                ParamSchema(
                    name="view_confidences",
                    label="观点置信度",
                    type="dict",
                    default={},
                    description='每个观点的置信度 (0-100%)。格式: {"v1": 70, "v2": 50}',
                ),
            ],
        )

    # ======================================================================
    # 核心 allocate 方法
    # ======================================================================

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """计算 Black-Litterman 模型的资产配置权重.

        核心流程：
        1. 参数解析与验证
        2. 收益率和协方差矩阵计算
        3. τ（tau）计算——控制先验不确定性的缩放因子
        4. 逆优化推导隐含均衡收益 π
        5. 解析观点 → P/Q/Omega
        6. 贝叶斯融合得到后验 μ_BL、Σ_BL
        7. 使用后验参数做 MVO 优化

        Args:
            prices: 资产价格历史数据，行为日期，列为资产标识
            **params: 策略参数（详见 get_param_schema）

        Returns:
            pd.Series: 资产配置权重，索引为资产标识，值为权重（总和为 1）

        Raises:
            ValueError: 参数不合法或数据不足时抛出
            RuntimeError: 优化求解失败时抛出
        """
        if prices.empty:
            raise ValueError("输入价格数据为空，无法进行 Black-Litterman 配置")

        # ------------------------------------------------------------------
        # 1. 参数解析
        # ------------------------------------------------------------------
        lookback_days = int(params.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
        delta = float(params.get("risk_aversion", DEFAULT_RISK_AVERSION))
        tau_param = float(params.get("tau", TAU_AUTO_SENTINEL))
        cov_method = params.get("cov_method", "ledoit_wolf")
        optimization_mode = params.get("optimization_mode", "max_sharpe")
        min_weight = float(params.get("min_weight", 0.0))
        max_weight = float(params.get("max_weight", 1.0))
        risk_free_rate = float(params.get("risk_free_rate", DEFAULT_RISK_FREE_RATE))
        views_raw = params.get("views", {}) or {}
        confidences_raw = params.get("view_confidences", {}) or {}

        logger.info(
            "Black-Litterman 配置开始 | lookback={}, δ={}, τ_param={}, "
            "cov={}, mode={}, 观点数={}",
            lookback_days, delta, tau_param, cov_method,
            optimization_mode, len(views_raw),
        )

        # ------------------------------------------------------------------
        # 2. 数据准备：取最近 lookback_days 的价格，计算收益率
        # ------------------------------------------------------------------
        prices_trimmed = prices.tail(lookback_days + 1)
        returns = compute_simple_returns(prices_trimmed)
        # 删除全部为 NaN 的列（避免后续矩阵运算问题）
        returns = returns.dropna(axis=1, how="all")
        if returns.empty or returns.shape[1] < 2:
            raise ValueError(
                f"有效资产数量不足（需 ≥ 2），当前有效资产数: {returns.shape[1]}。"
                "请检查价格数据完整性或增大回看窗口。"
            )

        assets = returns.columns.tolist()
        n = len(assets)
        logger.debug("有效资产 {} 个: {}", n, assets)

        # ------------------------------------------------------------------
        # 3. 计算协方差矩阵 Σ（Ledoit-Wolf 或样本协方差）
        # ------------------------------------------------------------------
        Sigma = compute_covariance(returns, method=cov_method).values
        Sigma_annual = Sigma * ANNUALIZATION_FACTOR  # 年化协方差

        # ------------------------------------------------------------------
        # 4. τ（tau）计算
        #    理论含义：τ 衡量对均衡收益估计的不确定性程度。
        #    τ 越大，表示对市场均衡的信心越低，观点的影响力越大。
        #    自动模式下 τ = 1/T 是常用的经验取值（He & Litterman, 1999）。
        # ------------------------------------------------------------------
        T = len(returns)  # 实际使用的样本数量
        if tau_param == TAU_AUTO_SENTINEL or tau_param is None:
            tau = 1.0 / T
            logger.info("τ 自动计算: 1/{} = {:.6f}", T, tau)
        else:
            if tau_param > TAU_MAX:
                raise ValueError(
                    f"tau = {tau_param} 超过上限 {TAU_MAX}。"
                    "tau 过大会使结果退化为纯观点驱动，请设置更小的值。"
                )
            tau = max(TAU_MIN, min(TAU_MAX, tau_param))
            logger.info("τ 手动设置: {:.6f}", tau)

        # ------------------------------------------------------------------
        # 5. 市场均衡权重（使用等权作为市场组合代理）
        # ------------------------------------------------------------------
        w_mkt = np.ones(n) / n

        # ------------------------------------------------------------------
        # 6. 逆推隐含均衡收益 π = δ·Σ_annual·w_mkt
        #    这是 CAPM 均衡下市场组合隐含的预期超额收益率向量。
        # ------------------------------------------------------------------
        pi = delta * Sigma_annual @ w_mkt
        logger.debug("隐含均衡收益 π: {}", dict(zip(assets, np.round(pi, 6))))

        # ------------------------------------------------------------------
        # 7-10. 观点处理与贝叶斯融合
        # ------------------------------------------------------------------
        if not views_raw:
            # 无观点时，直接使用隐含收益做 MVO
            logger.info("未提供观点，使用隐含均衡收益进行 MVO 优化")
            mu_BL = pi
            Sigma_BL = Sigma_annual
        else:
            # 8. 解析观点 → P 矩阵和 Q 向量
            P, Q = self._build_views(views_raw, assets)
            logger.debug("观点矩阵 P 维度: {}×{}, Q 维度: {}", P.shape[0], P.shape[1], Q.shape[0])

            # 9. Idzorek 方法构造 Omega
            Omega = self._build_omega_idzorek(P, Sigma_annual, confidences_raw, views_raw)

            # 10. 贝叶斯融合：计算后验均值和后验协方差
            mu_BL, Sigma_BL = self._posterior(pi, Sigma_annual, tau, P, Q, Omega)
            logger.debug("后验收益 μ_BL: {}", dict(zip(assets, np.round(mu_BL, 6))))

        # ------------------------------------------------------------------
        # 11. 使用 μ_BL 和 Σ_BL 做 MVO 优化
        # ------------------------------------------------------------------
        weights = self._optimize(
            mu_BL, Sigma_BL, assets, optimization_mode,
            min_weight, max_weight, risk_free_rate,
            target_return=float(params.get("target_return", 0.08)),
        )
        logger.info("Black-Litterman 配置完成 | 权重: {}", weights.to_dict())
        return weights

    # ======================================================================
    # 辅助方法
    # ======================================================================

    def _build_views(self, views_raw: dict, assets: list) -> tuple:
        """解析观点字典 → P 矩阵和 Q 向量.

        views_raw 格式示例::

            {
                "view_1": {"type": "absolute", "asset": "沪深300", "return": 0.08},
                "view_2": {"type": "relative", "long": "黄金", "short": "原油", "return": 0.03}
            }

        - absolute（绝对观点）: 认为某资产的预期收益为指定值
          → P[i, asset_idx] = 1
        - relative（相对观点）: 认为 long 资产超额收益优于 short 资产指定幅度
          → P[i, long_idx] = 1, P[i, short_idx] = -1

        Args:
            views_raw: 观点字典
            assets: 资产名称列表

        Returns:
            (P, Q): P 为 k×n 的观点矩阵，Q 为 k 维观点向量

        Raises:
            ValueError: 观点中引用了不存在的资产时抛出
        """
        n = len(assets)
        asset_index = {a: i for i, a in enumerate(assets)}
        view_keys = sorted(views_raw.keys())
        k = len(view_keys)

        if k == 0:
            raise ValueError("观点字典为空，请至少提供一个观点")

        P = np.zeros((k, n))
        Q = np.zeros(k)
        skipped_rows: list[int] = []  # 记录无法识别的观点行号

        for row, vk in enumerate(view_keys):
            view = views_raw[vk]
            view_type = view.get("type", "absolute")
            ret = float(view.get("return", 0.0))

            if view_type == "absolute":
                asset_name = view.get("asset")
                if asset_name not in asset_index:
                    logger.warning(
                        "观点 '{}' 引用了不存在的资产 '{}'，已跳过。可用资产: {}",
                        vk, asset_name, assets,
                    )
                    skipped_rows.append(row)
                    continue
                P[row, asset_index[asset_name]] = 1.0
                Q[row] = ret

            elif view_type == "relative":
                long_name = view.get("long")
                short_name = view.get("short")
                if long_name not in asset_index or short_name not in asset_index:
                    missing = []
                    if long_name not in asset_index:
                        missing.append(f"多头 '{long_name}'")
                    if short_name not in asset_index:
                        missing.append(f"空头 '{short_name}'")
                    logger.warning(
                        "观点 '{}' 引用了不存在的资产 ({})，已跳过。可用资产: {}",
                        vk, ", ".join(missing), assets,
                    )
                    skipped_rows.append(row)
                    continue
                P[row, asset_index[long_name]] = 1.0
                P[row, asset_index[short_name]] = -1.0
                Q[row] = ret

            else:
                logger.warning(
                    "观点 '{}' 的 type 不合法: '{}'，仅支持 'absolute'/'relative'，已跳过",
                    vk, view_type,
                )
                skipped_rows.append(row)
                continue

        # 移除被跳过的观点行
        if skipped_rows:
            valid_mask = np.ones(k, dtype=bool)
            valid_mask[skipped_rows] = False
            P = P[valid_mask]
            Q = Q[valid_mask]
            logger.info("跳过 {} 个无效观点，剩余 {} 个有效观点", len(skipped_rows), P.shape[0])

        if P.shape[0] == 0:
            raise ValueError("所有观点均无效（引用了不存在的资产），无法构造观点矩阵")

        return P, Q

    def _build_omega_idzorek(
        self,
        P: np.ndarray,
        Sigma: np.ndarray,
        confidences_raw: dict,
        views_raw: dict,
    ) -> np.ndarray:
        """Idzorek 方法构造观点不确定性矩阵 Ω.

        Idzorek (2005) 方法的核心思想是让 Omega 与资产的天然波动率挂钩，
        而不是任意设定。通过 confidence（置信度）参数控制每个观点的确定性程度：
        - 高置信度 → 小的 omega → 观点对后验影响大
        - 低置信度 → 大的 omega → 观点对后验影响小

        计算公式::

            omega_i = (1/c_i - 1) * (P @ Σ @ P^T)[i, i]

        其中 c_i 为置信度（0-1 之间）。

        Args:
            P: k×n 观点矩阵
            Sigma: n×n 年化协方差矩阵
            confidences_raw: 观点置信度字典，值为 0-100
            views_raw: 观点字典（用于按序遍历）

        Returns:
            np.ndarray: k×k 对角矩阵 Omega
        """
        k = P.shape[0]
        view_keys = sorted(views_raw.keys())

        # P @ Σ @ P^T 的对角元素——反映每个观点涉及资产的天然波动率
        P_Sigma_Pt = P @ Sigma @ P.T
        omega_diag = np.zeros(k)

        for i, vk in enumerate(view_keys):
            # 获取置信度（默认 50%）
            raw_confidence = float(confidences_raw.get(vk, DEFAULT_CONFIDENCE))
            # 转换到 [0, 1] 范围
            c_i = raw_confidence / 100.0

            # 裁剪置信度，防止数值问题
            # confidence = 100% 时 c_i 趋近 1 → 1/c_i - 1 趋近 0 → omega 极小（观点几乎确定）
            # confidence = 0%  时 c_i 趋近 0 → 1/c_i - 1 趋近 ∞ → omega 极大（观点几乎无效）
            c_i = np.clip(c_i, CONFIDENCE_LOWER_CLAMP, CONFIDENCE_UPPER_CLAMP)

            # Idzorek 公式：omega_i = (1/c_i - 1) * (P Σ P^T)[i,i]
            p_sigma_pt_ii = P_Sigma_Pt[i, i]
            if p_sigma_pt_ii <= 0:
                logger.warning(
                    "观点 '{}' 对应的 (PΣP^T)[{},{}] = {:.6e} ≤ 0，"
                    "使用正则化值 {:.1e}",
                    vk, i, i, p_sigma_pt_ii, REGULARIZATION_EPSILON,
                )
                p_sigma_pt_ii = REGULARIZATION_EPSILON

            omega_diag[i] = (1.0 / c_i - 1.0) * p_sigma_pt_ii

        Omega = np.diag(omega_diag)
        logger.debug("Omega 对角线: {}", np.round(omega_diag, 8))
        return Omega

    def _safe_inv(self, matrix: np.ndarray) -> np.ndarray:
        """安全矩阵求逆：检查条件数，必要时正则化，统一使用伪逆.

        所有矩阵求逆统一走此方法，保证数值稳定性：
        1. 计算条件数
        2. 若条件数 > 阈值，添加正则化项 ε·I
        3. 使用 np.linalg.pinv（Moore-Penrose 伪逆），即使矩阵接近奇异也能返回结果

        Args:
            matrix: 待求逆的方阵

        Returns:
            np.ndarray: 伪逆矩阵
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
        self,
        pi: np.ndarray,
        Sigma: np.ndarray,
        tau: float,
        P: np.ndarray,
        Q: np.ndarray,
        Omega: np.ndarray,
    ) -> tuple:
        """计算后验收益均值和后验协方差矩阵.

        贝叶斯融合公式（Black-Litterman 经典形式）::

            M       = inv(inv(τΣ) + P^T inv(Ω) P)
            μ_BL    = M @ (inv(τΣ) @ π  +  P^T @ inv(Ω) @ Q)
            Σ_BL    = Σ + M

        后验协方差 Σ_BL = Σ + M 的含义：
        引入观点后不确定性结构发生变化。M 代表后验均值的估计误差协方差，
        将其加到原始 Σ 上，才能正确反映组合的真实风险。
        如果在最终 MVO 优化中使用原始 Σ 而非 Σ_BL，会低估组合风险。

        Args:
            pi: n 维隐含均衡收益向量
            Sigma: n×n 年化协方差矩阵
            tau: 不确定性缩放因子
            P: k×n 观点矩阵
            Q: k 维观点向量
            Omega: k×k 观点不确定性矩阵

        Returns:
            (mu_BL, Sigma_BL): 后验收益向量和后验协方差矩阵
        """
        # τΣ 的逆
        tau_Sigma = tau * Sigma
        inv_tau_Sigma = self._safe_inv(tau_Sigma)

        # Ω 的逆
        inv_Omega = self._safe_inv(Omega)

        # M = inv(inv(τΣ) + P^T inv(Ω) P)
        M_inner = inv_tau_Sigma + P.T @ inv_Omega @ P
        M = self._safe_inv(M_inner)

        # 后验均值: μ_BL = M @ (inv(τΣ) @ π + P^T @ inv(Ω) @ Q)
        mu_BL = M @ (inv_tau_Sigma @ pi + P.T @ inv_Omega @ Q)

        # 后验协方差: Σ_BL = Σ + M
        # 注意：使用原始 Σ（而非 τΣ），加上 M 以反映引入观点后的不确定性
        Sigma_BL = Sigma + M

        return mu_BL, Sigma_BL

    def _optimize(
        self,
        mu_BL: np.ndarray,
        Sigma_BL: np.ndarray,
        assets: list,
        mode: str,
        min_w: float,
        max_w: float,
        rf: float,
        target_return: float = 0.08,
    ) -> pd.Series:
        """使用后验参数做 MVO 优化（max_sharpe / min_variance / target_return）.

        参考 mean_variance.py 的 SLSQP 调用方式。

        Args:
            mu_BL: n 维后验收益向量
            Sigma_BL: n×n 后验协方差矩阵
            assets: 资产名称列表
            mode: 优化模式
            min_w: 最小权重
            max_w: 最大权重
            rf: 无风险利率
            target_return: 目标收益率（仅 target_return 模式）

        Returns:
            pd.Series: 归一化后的权重

        Raises:
            ValueError: 约束不可行或模式不合法时抛出
            RuntimeError: 优化求解失败时抛出
        """
        n = len(assets)

        # 可行性检查：最小权重之和不得超过 1
        lower_bound = max(0.0, min_w)
        if lower_bound * n > 1.0:
            raise ValueError(
                f"约束不可行: min_weight={min_w}, 资产数={n}。"
                f"最小权重之和 ({lower_bound * n:.4f}) > 1.0。"
                f"建议降低 min_weight 至 {1.0 / n:.4f} 以下。"
            )

        # 保证至少存在可行解
        effective_max = max_w
        if max_w * n < 1.0:
            effective_max = 1.0 / n

        bounds = tuple((lower_bound, effective_max) for _ in range(n))
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        x0 = np.full(n, 1.0 / n, dtype=float)

        # 辅助：将矩阵乘法结果安全转换为标量
        def _to_scalar(value):
            if isinstance(value, (np.ndarray, list)):
                return float(value.item() if hasattr(value, "item") else value[0])
            return float(value)

        # 根据模式定义目标函数
        if mode == "min_variance":
            def objective(w: np.ndarray) -> float:
                return _to_scalar(w @ Sigma_BL @ w)

        elif mode == "target_return":
            if n < 2:
                raise ValueError(
                    f"目标收益模式需要至少 2 个资产，当前只有 {n} 个。"
                    "建议切换到 min_variance 或 max_sharpe 模式。"
                )
            constraints.append({
                "type": "eq",
                "fun": lambda w: float(np.dot(w, mu_BL)) - target_return,
            })

            def objective(w: np.ndarray) -> float:
                return _to_scalar(w @ Sigma_BL @ w)

        elif mode == "max_sharpe":
            def objective(w: np.ndarray) -> float:
                port_ret = float(np.dot(w, mu_BL))
                port_var = _to_scalar(w @ Sigma_BL @ w)
                port_std = np.sqrt(max(port_var, NUMERICAL_FLOOR))
                sharpe = (port_ret - rf) / port_std
                return -sharpe  # 最小化负夏普 = 最大化夏普

        else:
            raise ValueError(f"不支持的优化模式: {mode}")

        # 求解
        w_opt, success, message = solve_slsqp(
            x0=x0,
            objective=objective,
            bounds=bounds,
            constraints=constraints,
            maxiter=1000,
        )

        if not success:
            raise RuntimeError(
                f"Black-Litterman MVO 优化失败: {message} | "
                f"模式={mode}, 资产数={n}"
            )

        # 归一化
        w_opt = np.maximum(w_opt, 0.0)
        total = float(w_opt.sum())
        if total > 0:
            w_opt = w_opt / total

        return pd.Series(w_opt, index=assets)
