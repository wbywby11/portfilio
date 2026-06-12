"""夏普比率计算公式."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    freq_factor: int = 252
) -> float:
    """计算夏普比率（Sharpe Ratio）.
    
    公式: SR = E[r - r_f] / σ[r - r_f] * sqrt(252)
    其中:
        - r: 资产收益率
        - r_f: 无风险利率（日度）
        - E: 期望值（均值）
        - σ: 标准差
    
    参数:
        returns: 收益率序列（日度）
        risk_free_rate: 无风险利率（年化）
        freq_factor: 年化因子（默认252个交易日）
    
    返回:
        夏普比率（年化）
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
