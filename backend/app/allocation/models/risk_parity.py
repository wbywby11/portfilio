"""Risk parity strategy implementation in the new strategies module.

This class exposes a single entry point:

    allocate(prices: DataFrame, **params) -> Series

Inputs
------
- prices: cleaned price matrix (index: datetime, columns: asset identifiers)
- params (optional):
    - cov_method: covariance estimation method (default: "sample")
    - min_weight: lower bound per asset (default: 0.0)
    - max_weight: upper bound per asset (default: 1.0)

Output
------
- weights: Series of allocation weights indexed by asset identifiers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from app.formula.returns import compute_simple_returns
from app.formula.covariance import compute_covariance
from app.solvers.slsqp_solver import solve_slsqp
from app.allocation.models.base import BaseStrategyModel


class RiskParityStrategy(BaseStrategyModel):
    @classmethod
    def get_param_schema(cls):
        """返回风险平价策略的参数Schema."""
        from app.allocation.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="risk_parity",
            display_name="风险平价",
            description="基于SLSQP优化使各资产风险贡献相等，Maillard et al. (2010) 经典ERC框架",
            params=[
                ParamSchema(
                    name="lookback_days",
                    label="历史数据回看期",
                    type="number",
                    default=252,
                    min_value=20,
                    max_value=1000,
                    step=10,
                    description="计算协方差矩阵使用的历史数据天数（交易日），默认252天约1年"
                ),
                ParamSchema(
                    name="cov_method",
                    label="协方差估计方法",
                    type="select",
                    default="sample",
                    options=[("sample", "样本协方差"), ("ledoit_wolf", "Ledoit-Wolf 收缩估计")],
                    description="协方差矩阵估计方法，样本较少时自动切换为 Ledoit-Wolf",
                    group="advanced",
                ),
                ParamSchema(
                    name="maxiter",
                    label="最大迭代次数",
                    type="number",
                    default=1000,
                    min_value=100,
                    max_value=20000,
                    step=100,
                    description="优化器的最大迭代次数",
                    group="advanced",
                ),
                ParamSchema(
                    name="min_weight",
                    label="单资产最小权重",
                    type="number",
                    default=0.0,
                    min_value=0.0,
                    max_value=None,
                    step=0.01,
                    description="单个资产的最小持仓权重（建议不超过 1/资产数，否则可能无可行解）",
                    group="advanced",
                ),
                ParamSchema(
                    name="max_weight",
                    label="单资产最大权重",
                    type="number",
                    default=1.0,
                    min_value=0.0,
                    max_value=None,
                    step=0.05,
                    description="单个资产的最大持仓权重",
                    group="advanced",
                ),
            ]
        )
    
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        # 0. 处理lookback_days参数：限制使用的历史数据范围
        lookback_days = int(params.get("lookback_days", 252))  # 转换为整数类型
        if lookback_days is not None and lookback_days > 0:
            # 只使用最近lookback_days天的数据
            if len(prices) > lookback_days:
                prices = prices.iloc[-lookback_days:]

        # 1. Compute returns and covariance
        returns = compute_simple_returns(prices)
        assets = list(prices.columns)
        n_assets = len(assets)
        if n_assets == 0:
            raise ValueError("prices DataFrame has no asset columns")

        # 样本过少时使用 Ledoit-Wolf 收缩估计（比 sample cov 更稳健，适合小样本）
        min_obs = max(n_assets + 1, 10)
        cov_method = params.get("cov_method", "sample")
        if returns.empty or len(returns) < min_obs:
            logger.warning(
                "RiskParityStrategy: 历史收益率样本不足 (rows={}, 需要至少 {} 条, 资产数={})，"
                "自动切换为 Ledoit-Wolf 收缩协方差估计。请确认行情起始日早于回测开始日、或拉长预热期。",
                len(returns),
                min_obs,
                n_assets,
            )
            cov_method = "ledoit_wolf"
            # 极端情况：收益行数 < 2，Ledoit-Wolf 也无法估计
            if len(returns) < 2:
                raise ValueError(
                    f"风险平价优化失败: 历史收益数据仅 {len(returns)} 行，"
                    f"不足以估计任何协方差矩阵（至少需要 2 行）。"
                    f"请拉长回测区间或增加预热期。"
                )

        cov = compute_covariance(returns, method=cov_method)

        # 协方差矩阵质量检查：NaN/Inf 时尝试 Ledoit-Wolf 兜底
        if cov.isna().any().any() or not np.all(np.isfinite(cov.to_numpy(dtype=float, copy=False))):
            if cov_method != "ledoit_wolf":
                logger.warning(
                    "RiskParityStrategy: sample 协方差含 NaN/Inf，自动切换为 Ledoit-Wolf 收缩估计。"
                )
                cov = compute_covariance(returns, method="ledoit_wolf")
            # 再次检查
            if cov.isna().any().any() or not np.all(np.isfinite(cov.to_numpy(dtype=float, copy=False))):
                raise ValueError(
                    "风险平价优化失败: 协方差矩阵含 NaN/Inf，"
                    "即使 Ledoit-Wolf 收缩估计也无法获得有效矩阵。"
                    "请检查价格数据是否完整（是否存在常数列或全 NaN 列）。"
                )

        # 2. Initial weights (equal weight)
        x0 = np.full(shape=(n_assets,), fill_value=1.0 / n_assets, dtype=float)

        # 3. Build constraints and bounds
        min_weight = float(params.get("min_weight", 0.0))
        max_weight = float(params.get("max_weight", 1.0))
        lower_bound = max(0.0, min_weight)
        bounds = tuple((lower_bound, max_weight) for _ in range(n_assets))
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
        ]

        # 4. Define objective: minimize variance of risk contributions (pure numpy)
        cov_np = cov.to_numpy(dtype=float, copy=False)
        target_rc = 1.0 / n_assets

        def objective(w: np.ndarray) -> float:
            port_var = float(w @ cov_np @ w)
            if port_var < 1e-16:
                return 0.0
            marginal = cov_np @ w
            rc = w * marginal / port_var  # 归一化风险贡献
            diff = rc - target_rc
            return float(np.dot(diff, diff))

        # 5. Solve optimization
        w_opt, success, message = solve_slsqp(
            x0=x0,
            objective=objective,
            bounds=bounds,
            constraints=constraints,
            maxiter=int(params.get("maxiter", 1000)),
        )

        # 6. 检查优化结果
        if not success:
            raise RuntimeError(
                f"风险平价优化失败: {message}\n"
                f"资产数={n_assets}, min_weight={min_weight}, max_weight={max_weight}, "
                f"收益率行数={len(returns)}, 协方差对角最小值={float(np.min(np.diag(cov.values))):.2e}"
            )
        
        # 7. 归一化权重
        w_opt = np.maximum(w_opt, 0.0)
        total = float(w_opt.sum())
        if total > 0:
            w_opt = w_opt / total

        weights = pd.Series(w_opt, index=assets)
        return weights
