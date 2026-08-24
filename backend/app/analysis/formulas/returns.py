"""收益率计算公式.

包含累计收益率、年化收益率等 analysis 独有公式。
简单收益率和对数收益率已统一由 app.formula.returns 提供，
通过 __init__.py 中的薄包装保持 calculate_* 命名兼容。
"""

from __future__ import annotations

import pandas as pd


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
    freq_factor: int = 260
) -> float:
    """计算年化收益率（几何平均）.
    
    公式: (1 + cum_return) ^ (260 / n_days) - 1
    
    参数:
        prices: 价格序列
        freq_factor: 年化因子（默认260个交易日）
    
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
