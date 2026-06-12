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

from app.strategies.formula.returns import compute_simple_returns
from app.strategies.formula.covariance import compute_covariance
from app.strategies.formula.risk_contribution import compute_risk_contribution
from app.strategies.solvers.slsqp_solver import solve_slsqp
from app.strategies.models.base import BaseStrategyModel


class RiskParityStrategy(BaseStrategyModel):
    @classmethod
    def get_param_schema(cls):
        """返回风险平价策略的参数Schema."""
        from app.strategies.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="risk_parity",
            display_name="风险平价策略",
            description="各资产风险贡献相等的组合配置策略，适合多元化投资",
            params=[
                ParamSchema(
                    name="lookback_days",
                    label="历史数据回看期",
                    type="number",
                    default=252,
                    min_value=None,
                    max_value=None,
                    step=10,
                    description="计算协方差矩阵使用的历史数据天数（交易日），默认252天约1年"
                ),
                ParamSchema(
                    name="min_weight",
                    label="单资产最小权重",
                    type="number",
                    default=0.0,
                    min_value=0.0,
                    max_value=None,
                    step=0.01,
                    description="单个资产的最小持仓权重（建议不超过 1/资产数，否则可能无可行解）"
                ),
                ParamSchema(
                    name="max_weight",
                    label="单资产最大权重",
                    type="number",
                    default=1.0,
                    min_value=0.0,
                    max_value=None,
                    step=0.05,
                    description="单个资产的最大持仓权重"
                ),
                ParamSchema(
                    name="maxiter",
                    label="最大迭代次数",
                    type="number",
                    default=1000,
                    min_value=100,
                    max_value=5000,
                    step=100,
                    description="优化器的最大迭代次数"
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

        # 样本过少时样本协方差退化（甚至 0 行收益），SLSQP 易出现 Inequality constraints incompatible
        min_obs = max(n_assets + 1, 10)
        if returns.empty or len(returns) < min_obs:
            logger.warning(
                "RiskParityStrategy: 历史收益率样本不足 (rows={}, 需要至少 {} 条, 资产数={})，"
                "无法可靠估计协方差，本次使用等权。请确认行情起始日早于回测开始日、或拉长预热期。",
                len(returns),
                min_obs,
                n_assets,
            )
            w = np.full(shape=(n_assets,), fill_value=1.0 / n_assets, dtype=float)
            return pd.Series(w, index=assets)

        cov = compute_covariance(returns, method=params.get("cov_method", "sample"))
        if cov.isna().any().any() or not np.all(np.isfinite(cov.to_numpy(dtype=float, copy=False))):
            logger.warning(
                "RiskParityStrategy: 协方差矩阵含 NaN/Inf，使用等权。请检查价格数据是否完整。"
            )
            w = np.full(shape=(n_assets,), fill_value=1.0 / n_assets, dtype=float)
            return pd.Series(w, index=assets)

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

        # 4. Define objective: minimize variance of risk contributions
        def objective(w: np.ndarray) -> float:
            weights_series = pd.Series(w, index=assets)
            rc = compute_risk_contribution(cov, weights_series, normalize=True)
            # target equal risk: each asset should contribute 1/n
            target = np.full(shape=(n_assets,), fill_value=1.0 / n_assets)
            diff = rc.values - target
            return float(np.dot(diff, diff))

        # 5. Solve optimization
        w_opt, success, message = solve_slsqp(
            x0=x0,
            objective=objective,
            bounds=bounds,
            constraints=constraints,
            maxiter=int(params.get("maxiter", 1000)),
        )

        # 6. 检查优化结果，失败时抛出异常
        if not success:
            raise RuntimeError(
                f"风险平价优化失败: {message}\n"
                "请检查数据质量、参数配置或增加最大迭代次数"
            )
        
        # 7. 归一化权重
        w_opt = np.maximum(w_opt, 0.0)
        total = float(w_opt.sum())
        if total > 0:
            w_opt = w_opt / total

        weights = pd.Series(w_opt, index=assets)
        return weights
