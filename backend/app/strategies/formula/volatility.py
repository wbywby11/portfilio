"""Volatility related formulas."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_volatility(returns: pd.DataFrame, annualize: bool = False, freq_factor: int = 252) -> pd.Series:
    """Compute per-asset volatility from returns."""
    vol = returns.std()
    if annualize:
        vol = vol * np.sqrt(freq_factor)
    return vol
