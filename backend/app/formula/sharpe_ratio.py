"""Sharpe ratio and related performance metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_annualized_return(portfolio_returns: pd.Series, freq_factor: int = 260) -> float:
    """Compute annualized return from periodic portfolio returns."""
    mean_return = portfolio_returns.mean()
    return float((1 + mean_return) ** freq_factor - 1)


def compute_sharpe_ratio(portfolio_returns: pd.Series, risk_free_rate: float = 0.0, freq_factor: int = 260) -> float:
    """Compute Sharpe ratio of a portfolio return series."""
    excess = portfolio_returns - risk_free_rate / freq_factor
    mean_excess = excess.mean()
    std_excess = excess.std()
    if std_excess == 0 or np.isnan(std_excess):
        return 0.0
    sharpe = mean_excess / std_excess
    return float(sharpe * np.sqrt(freq_factor))
