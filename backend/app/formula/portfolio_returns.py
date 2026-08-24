"""Portfolio returns related formulas."""

from __future__ import annotations

import pandas as pd


def compute_portfolio_returns(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Compute portfolio returns from asset returns and static weights."""
    common_assets = returns.columns.intersection(weights.index)
    if len(common_assets) == 0:
        raise ValueError("No overlapping assets between returns and weights")
    aligned_returns = returns[common_assets]
    aligned_weights = weights[common_assets]
    return aligned_returns.dot(aligned_weights)
