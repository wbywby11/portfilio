"""收益率计算公式.

包含简单收益率、对数收益率、累计收益率、年化收益率等。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_simple_returns(prices: pd.Series) -> pd.Series:
    """计算简单收益率（百分比收益率）.
    
    公式: r_t = (P_t / P_{t-1}) - 1
    
    参数:
        prices: 价格序列（index=时间）
    
    返回:
        收益率序列（去除第一个NaN）
    """
    returns = prices.pct_change()
    return returns.dropna()


def calculate_log_returns(prices: pd.Series) -> pd.Series:
    """计算对数收益率.
    
    公式: r_t = ln(P_t / P_{t-1})
    
    参数:
        prices: 价格序列（index=时间）
    
    返回:
        对数收益率序列（去除第一个NaN）
    """
    log_returns = np.log(prices / prices.shift(1))
    return log_returns.dropna()


def calculate_cumulative_return(prices: pd.Series) -> float:
    """计算累计收益率.
    
    公式: (price_end / price_start) - 1
    
    参数:
        prices: 价格序列
    
    返回:
        累计收益率
    """
    if prices.empty or len(prices) < 2:
        return 0.0
    
    price_start = float(prices.iloc[0])
    price_end = float(prices.iloc[-1])
    
    if price_start == 0 or pd.isna(price_start) or pd.isna(price_end):
        return 0.0
    
    return (price_end / price_start) - 1.0


def calculate_annualized_return(
    prices: pd.Series,
    freq_factor: int = 252
) -> float:
    """计算年化收益率（几何平均）.
    
    公式: (1 + cum_return) ^ (252 / n_days) - 1
    
    参数:
        prices: 价格序列
        freq_factor: 年化因子（默认252个交易日）
    
    返回:
        年化收益率
    """
    if prices.empty or len(prices) < 2:
        return 0.0
    
    cum_return = calculate_cumulative_return(prices)
    n_days = len(prices) - 1
    
    if n_days == 0:
        return 0.0
    
    annualized = (1.0 + cum_return) ** (freq_factor / n_days) - 1.0
    return float(annualized)
