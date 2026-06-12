"""Volatility calculation formulas."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_volatility(
    returns: pd.Series,
    annualize: bool = False,
    freq_factor: int = 252
) -> float:
    """计算波动率（标准差）.
    
    参数:
        returns: 收益率序列
        annualize: 是否年化
        freq_factor: 年化因子
    
    返回:
        波动率
    """
    if returns.empty:
        return 0.0
    
    vol = float(returns.std())
    
    if annualize:
        vol = vol * np.sqrt(freq_factor)
    
    return vol
