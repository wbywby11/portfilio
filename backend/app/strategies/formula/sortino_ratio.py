"""Sortino ratio calculation - downside risk adjusted return metric."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_sortino_ratio(
    portfolio_returns: pd.Series,
    risk_free_rate: float = 0.0,
    freq_factor: int = 252
) -> float:
    """计算索提诺比率(Sortino Ratio).
    
    索提诺比率类似于夏普比率,但只考虑下行风险(负收益的波动性),
    更适合衡量对下行风险敏感的投资策略表现。
    
    Args:
        portfolio_returns: 投资组合收益率序列
        risk_free_rate: 无风险利率(年化)
        freq_factor: 年化因子,默认252(交易日)
    
    Returns:
        float: 年化索提诺比率
    """
    # 转换为日度无风险利率
    rf_daily = risk_free_rate / freq_factor
    
    # 计算超额收益
    excess = portfolio_returns - rf_daily
    mean_excess = excess.mean()
    
    # 计算下行偏差(Downside Deviation)
    # 只考虑低于无风险利率的收益
    downside_returns = excess[excess < 0]
    
    if len(downside_returns) == 0:
        # 没有负收益,下行风险为0
        downside_std = 0.0
    else:
        # 下行标准差
        downside_std = downside_returns.std()
    
    # 避免除零
    if downside_std == 0 or np.isnan(downside_std):
        return 0.0
    
    # 计算年化索提诺比率
    sortino = mean_excess / downside_std
    return float(sortino * np.sqrt(freq_factor))
