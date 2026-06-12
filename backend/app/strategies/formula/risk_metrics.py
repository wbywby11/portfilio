"""Risk metrics formulas: covariance, volatility, risk contribution, etc."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


CovarianceMethod = Literal["sample"]


def compute_covariance(returns: pd.DataFrame, method: CovarianceMethod = "sample") -> pd.DataFrame:
    """Compute covariance matrix of asset returns.

    Currently only sample covariance is implemented; other methods can be
    added later with the same interface.
    """
    if method != "sample":
        raise ValueError(f"Unsupported covariance method: {method}")
    return returns.cov()


def compute_volatility(returns: pd.DataFrame, annualize: bool = False, freq_factor: int = 252) -> pd.Series:
    """Compute per-asset volatility from returns."""
    vol = returns.std()
    if annualize:
        vol = vol * np.sqrt(freq_factor)
    return vol


def compute_portfolio_volatility(cov_matrix: pd.DataFrame, weights: pd.Series) -> float:
    """Compute portfolio volatility given covariance matrix and weights."""
    w = weights.values.reshape(-1, 1)
    cov = cov_matrix.values
    # 修复：确保矩阵乘法的结果是标量
    variance_result = w.T @ cov @ w
    if isinstance(variance_result, (np.ndarray, list)):
        variance = float(variance_result.item() if hasattr(variance_result, 'item') else variance_result[0])
    else:
        variance = float(variance_result)
    return float(np.sqrt(max(variance, 0.0)))


def compute_risk_contribution(cov_matrix: pd.DataFrame, weights: pd.Series, normalize: bool = True) -> pd.Series:
    """Compute per-asset risk contribution given covariance matrix and weights."""
    cov = cov_matrix.values
    w = weights.values.reshape(-1, 1)
    # 修复：确保矩阵乘法的结果是标量
    portfolio_var_result = w.T @ cov @ w
    if isinstance(portfolio_var_result, (np.ndarray, list)):
        portfolio_var = float(portfolio_var_result.item() if hasattr(portfolio_var_result, 'item') else portfolio_var_result[0])
    else:
        portfolio_var = float(portfolio_var_result)
    if portfolio_var <= 0:
        # Avoid division by zero; return zeros with same index.
        return pd.Series(0.0, index=weights.index)
    # Marginal contribution: (Sigma w)
    marginal = cov @ w
    # Total contribution per asset: w * marginal
    contribution = (w * marginal).flatten()
    rc = pd.Series(contribution, index=weights.index)
    if normalize:
        rc = rc / portfolio_var
    return rc
