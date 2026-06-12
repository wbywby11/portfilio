"""波动率计算公式.

包含日度/年化波动率、滚动波动率等。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_volatility(
    returns: pd.Series,
    annualize: bool = False,
    freq_factor: int = 252
) -> float:
    """计算波动率（标准差）.
    
    公式: 
        - 日度波动率：std(returns)
        - 年化波动率：std(returns) * sqrt(252)
    
    参数:
        returns: 收益率序列
        annualize: 是否年化
        freq_factor: 年化因子（默认252个交易日）
    
    返回:
        波动率
    """
    if returns.empty:
        return 0.0
    
    vol = float(returns.std())
    
    if annualize:
        vol = vol * np.sqrt(freq_factor)
    
    return vol


def calculate_rolling_volatility(
    returns: pd.Series,
    window: int = 20,
    annualize: bool = False,
    freq_factor: int = 252
) -> pd.Series:
    """计算滚动波动率.
    
    参数:
        returns: 收益率序列
        window: 滚动窗口（交易日数）
        annualize: 是否年化
        freq_factor: 年化因子
    
    返回:
        滚动波动率序列
    """
    if returns.empty:
        return pd.Series(dtype=float)
    
    rolling_vol = returns.rolling(window=window).std()
    
    if annualize:
        rolling_vol = rolling_vol * np.sqrt(freq_factor)
    
    return rolling_vol
