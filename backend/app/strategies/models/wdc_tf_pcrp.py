"""WDC-TF-PCRP strategy implementation in the new architecture.

This is a streamlined version of WdcTfPcrpModel: it focuses on the mapping
from returns to weights, using half-life covariance estimation and
principal component risk parity, with optional trend filtering.

Entry point
-----------
    allocate(prices: DataFrame, **params) -> Series

Key params
----------
- cov_method: "standard" | "decay_weighted" | "separate_estimation"
- explained_variance: float, cumulative variance threshold for PCs
- lookback: int, window length
- decay_weights: list[float], for half-life estimator
- vol_lookback: int, short-term vol window (for separate_estimation)
- corr_lookback: int, long-term corr window (for separate_estimation)
- ma_window: int, trend smoothing window (used externally when computing trend_signals)
- allow_short: bool, whether to allow shorting
- min_weight, max_weight: per-asset bounds
- annualization_factor: int, default 252
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from app.strategies.formula.returns import compute_simple_returns
from app.strategies.models.base import BaseStrategyModel
from models.utils.half_life_cov import HalfLifeCovarianceEstimator


class WdcTfPcrpStrategy(BaseStrategyModel):
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        cfg = params
        cov_method: str = cfg.get("cov_method", "separate_estimation")
        explained_variance: float = float(cfg.get("explained_variance", 0.85))
        lookback: int = int(cfg.get("lookback", 240))
        decay_weights = cfg.get("decay_weights", [0.4, 0.3, 0.2, 0.1])
        vol_lookback: int = int(cfg.get("vol_lookback", 60))
        corr_lookback: int = int(cfg.get("corr_lookback", 240))
        allow_short: bool = bool(cfg.get("allow_short", False))
        min_weight: float = float(cfg.get("min_weight", 0.0))
        max_weight: float = float(cfg.get("max_weight", 1.0))
        annualization_factor: int = int(cfg.get("annualization_factor", 252))
        opt_method: str = cfg.get("opt_method", "SLSQP")
        opt_max_iter: int = int(cfg.get("opt_max_iter", 1000))
        opt_ftol: float = float(cfg.get("opt_ftol", 1e-8))

        # 1. Returns and windowing
        returns_full = compute_simple_returns(prices)
        if len(returns_full) < lookback:
            recent_returns = returns_full.copy()
        else:
            recent_returns = returns_full.iloc[-lookback:]

        symbols = list(recent_returns.columns)
        n_assets = len(symbols)

        # 2. Covariance estimation
        if cov_method == "standard":
            cov_matrix = recent_returns.cov().values
        else:
            est = HalfLifeCovarianceEstimator(lookback=lookback, half_weights=decay_weights)
            if cov_method == "decay_weighted":
                cov_matrix = est.estimate(recent_returns)
            elif cov_method == "separate_estimation":
                cov_matrix = est.separate_estimation(returns_full, vol_lookback, corr_lookback)
            else:
                raise ValueError(f"Unsupported cov_method: {cov_method}")
        cov_matrix = cov_matrix * annualization_factor

        # 3. PCA and component selection
        evals, evecs = np.linalg.eigh(cov_matrix)
        idx = np.argsort(evals)[::-1]
        evals_sorted = evals[idx]
        evecs_sorted = evecs[:, idx]
        cum_ratio = np.cumsum(evals_sorted) / np.sum(evals_sorted)
        n_components = int(np.argmax(cum_ratio >= explained_variance) + 1)
        eigenvalues = evals_sorted[:n_components]
        eigenvectors = evecs_sorted[:, :n_components]

        # 4. Optimization in asset space
        x0 = np.full(shape=(n_assets,), fill_value=1.0 / n_assets, dtype=float)

        constraints = ({"type": "eq", "fun": lambda w: np.sum(w) - 1.0},)
        if allow_short:
            bounds = tuple((min_weight, max_weight) for _ in range(n_assets))
        else:
            bounds = tuple((max(0.0, min_weight), max_weight) for _ in range(n_assets))

        # 辅助函数：安全地将矩阵乘法结果转换为标量
        def to_scalar(value):
            if isinstance(value, (np.ndarray, list)):
                return float(value.item() if hasattr(value, 'item') else value[0])
            return float(value)
        
        def pc_risk_contributions(w: np.ndarray) -> np.ndarray:
            pc_weights = eigenvectors.T @ w
            pc_cov = np.diag(eigenvalues)
            port_var = to_scalar(pc_weights.T @ pc_cov @ pc_weights)
            if port_var <= 0:
                port_var = 1e-12
            marginal_risk = pc_cov @ pc_weights / np.sqrt(port_var)
            return pc_weights * marginal_risk

        def objective(w: np.ndarray) -> float:
            pc_rc = pc_risk_contributions(w)
            return float(np.var(pc_rc))

        result = minimize(
            objective,
            x0,
            method=opt_method,
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": opt_max_iter, "ftol": opt_ftol},
        )

        # 5. 检查优化结果
        if not result.success:
            raise RuntimeError(
                f"WDC-TF-PCRP优化失败: {result.message}\n"
                f"优化状态: {result.status}\n"
                "请检查数据质量、参数配置或增加最大迭代次数"
            )
        
        # 6. 提取权重
        weights = pd.Series(result.x, index=symbols)

        # Optional trend filter: trend_signals ∈ {0,1}, index = symbols
        trend_signals: Optional[pd.Series] = cfg.get("trend_signals")
        cash_allocation = 0.0
        if trend_signals is not None and not allow_short:
            trend_signals = trend_signals.reindex(symbols).fillna(1).astype(int)
            down_mask = trend_signals == 0
            if down_mask.any():
                weights.loc[down_mask] = 0.0
                s = float(weights.sum())
                if s > 0:
                    weights = weights / s
                cash_allocation = float(1.0 - weights.sum())

        # Ensure non-negative and normalized if not allowing short
        if not allow_short:
            weights = weights.clip(lower=0.0)
            s = float(weights.sum())
            if s > 0:
                weights = weights / s

        return weights
