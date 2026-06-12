"""Sharpe ratio calculation formula."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    freq_factor: int = 252
) -> float:
    """计算夏普比率.
    
    公式: mean(excess_returns) / std(excess_returns) * sqrt(252)
    其中 excess_returns = returns - rf_daily
    
    参数:
        returns: 收益率序列（日度）
        risk_free_rate: 无风险利率（年化）
        freq_factor: 年化因子
    
    返回:
        夏普比率
    """
    if returns.empty or len(returns) < 2:
        return 0.0
    
    # 转换为日度无风险利率
    rf_daily = risk_free_rate / freq_factor
    
    # 超额收益
    excess_returns = returns - rf_daily
    
    mean_excess = float(excess_returns.mean())
    std_excess = float(excess_returns.std())
    
    if std_excess == 0 or pd.isna(std_excess):
        return 0.0
    
    sharpe = (mean_excess / std_excess) * np.sqrt(freq_factor)
    
    return float(sharpe)
