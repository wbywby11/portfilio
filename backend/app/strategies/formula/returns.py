"""Simple and log returns computation."""

from __future__ import annotations

import pandas as pd


def compute_simple_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute simple returns from price data.

    prices: DataFrame indexed by datetime, columns are asset identifiers.
    Returns a DataFrame of the same shape with simple returns, first row dropped.
    """
    returns = prices.pct_change()
    return returns.dropna(how="all")


def compute_log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute log returns from price data."""
    log_prices = prices.astype(float).apply(lambda s: s.apply(lambda x: None if pd.isna(x) else pd.np.log(x)))
    returns = log_prices.diff()
    return returns.dropna(how="all")
