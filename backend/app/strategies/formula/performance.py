"""Performance metrics formulas: portfolio returns, Sharpe ratio, etc."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_portfolio_returns(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Compute portfolio returns from asset returns and static weights."""
    # Align columns and weights index
    common_assets = returns.columns.intersection(weights.index)
    if len(common_assets) == 0:
        raise ValueError("No overlapping assets between returns and weights")
    aligned_returns = returns[common_assets]
    aligned_weights = weights[common_assets]
    return aligned_returns.dot(aligned_weights)


def compute_annualized_return(portfolio_returns: pd.Series, freq_factor: int = 252) -> float:
    """Compute annualized return from periodic portfolio returns."""
    mean_return = portfolio_returns.mean()
    return float((1 + mean_return) ** freq_factor - 1)


def compute_sharpe_ratio(portfolio_returns: pd.Series, risk_free_rate: float = 0.0, freq_factor: int = 252) -> float:
    """Compute Sharpe ratio of a portfolio return series."""
    excess = portfolio_returns - risk_free_rate / freq_factor
    mean_excess = excess.mean()
    std_excess = excess.std()
    if std_excess == 0 or np.isnan(std_excess):
        return 0.0
    sharpe = mean_excess / std_excess
    return float(sharpe * np.sqrt(freq_factor))
