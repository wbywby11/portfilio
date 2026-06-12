"""Risk contribution related formulas."""

from __future__ import annotations

import pandas as pd


def compute_risk_contribution(cov_matrix: pd.DataFrame, weights: pd.Series, normalize: bool = True) -> pd.Series:
    """Compute per-asset risk contribution given covariance matrix and weights."""
    import numpy as np
    cov = cov_matrix.values
    w = weights.values.reshape(-1, 1)
    # 修复：确保矩阵乘法的结果是标量
    portfolio_var_result = w.T @ cov @ w
    if isinstance(portfolio_var_result, (np.ndarray, list)):
        portfolio_var = float(portfolio_var_result.item() if hasattr(portfolio_var_result, 'item') else portfolio_var_result[0])
    else:
        portfolio_var = float(portfolio_var_result)
    if portfolio_var <= 0:
        return pd.Series(0.0, index=weights.index)
    marginal = cov @ w
    contribution = (w * marginal).flatten()
    rc = pd.Series(contribution, index=weights.index)
    if normalize:
        rc = rc / portfolio_var
    return rc
