"""Half-life principal component risk parity strategy.

This is a streamlined translation of HalfLifePCRPModel to the new
`strategies` architecture. It focuses on the core optimization from
returns to weights.

Entry point
-----------
    allocate(prices: DataFrame, **params) -> Series

Key params
----------
- lookback: int, rolling window length
- half_weights: list[float], half-life weights (must sum to 1)
- n_components: number of principal components
- annualization_factor: scaling for covariance (default 252)
- max_weight, min_weight: per-asset bounds
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from app.strategies.formula.returns import compute_simple_returns
from app.strategies.models.base import BaseStrategyModel
from models.utils.half_life_cov import HalfLifeCovarianceEstimator


class HalfLifePCRPStrategy(BaseStrategyModel):
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        lookback = int(params.get("lookback", 240))
        half_weights = params.get("half_weights", [1 / 3, 1 / 3, 1 / 6, 1 / 6])
        n_components = int(params.get("n_components", 3))
        annualization_factor = int(params.get("annualization_factor", 252))
        max_weight = float(params.get("max_weight", 1.0))
        min_weight = float(params.get("min_weight", 0.0))

        # 1. Compute returns and restrict to lookback
        returns_full = compute_simple_returns(prices)
        if len(returns_full) < lookback:
            raise ValueError(f"Not enough data: need {lookback} days, got {len(returns_full)}")
        returns = returns_full.iloc[-lookback:]

        symbols = list(returns.columns)
        n_assets = len(symbols)

        # 2. Half-life covariance estimation
        cov_estimator = HalfLifeCovarianceEstimator(lookback=lookback, half_weights=half_weights)
        cov_matrix = cov_estimator.estimate(returns) * annualization_factor

        # 3. Eigen decomposition and PC selection
        eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)
        idx = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[idx][:n_components]
        eigenvectors = eigenvectors[:, idx][:, :n_components]

        # 4. Set up optimization in asset space
        x0 = np.full(shape=(n_assets,), fill_value=1.0 / n_assets, dtype=float)

        constraints = ({"type": "eq", "fun": lambda w: np.sum(w) - 1.0},)
        bounds = tuple((min_weight, max_weight) for _ in range(n_assets))

        # 辅助函数：安全地将矩阵乘法结果转换为标量
        def to_scalar(value):
            if isinstance(value, (np.ndarray, list)):
                return float(value.item() if hasattr(value, 'item') else value[0])
            return float(value)
        
        def objective(w: np.ndarray) -> float:
            pc_weights = eigenvectors.T @ w  # (n_components,)
            pc_cov = np.diag(eigenvalues)
            pc_var = to_scalar(pc_weights.T @ pc_cov @ pc_weights)
            if pc_var <= 0:
                return 1e10
            pc_vol = np.sqrt(pc_var)
            pc_rc = pc_weights * (pc_cov @ pc_weights) / pc_vol
            # Minimize dispersion of PC risk contributions
            return float(np.var(pc_rc))

        result = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": int(params.get("maxiter", 1000)), "ftol": 1e-8},
        )

        # 5. 检查优化结果
        if not result.success:
            raise RuntimeError(
                f"半衰期PCRP优化失败: {result.message}\n"
                f"优化状态: {result.status}\n"
                "请检查数据质量、参数配置或增加最大迭代次数"
            )
        
        # 6. 归一化权重
        w_opt = np.maximum(result.x, 0.0)
        total = float(w_opt.sum())
        if total > 0:
            w_opt = w_opt / total

        return pd.Series(w_opt, index=symbols)
