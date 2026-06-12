"""Drawdown calculation formulas."""

from __future__ import annotations

import pandas as pd

from app.analysis.metrics.nav import calculate_nav_series


def calculate_max_drawdown(prices: pd.Series) -> float:
    """计算最大回撤.
    
    公式: min((nav - nav.cummax()) / nav.cummax())
    
    参数:
        prices: 价格序列
    
    返回:
        最大回撤（负值或0）
    """
    if prices.empty or len(prices) < 2:
        return 0.0
    
    drawdown_series = calculate_drawdown_series(prices)
    
    if drawdown_series.empty:
        return 0.0
    
    return float(drawdown_series.min())


def calculate_drawdown_series(prices: pd.Series) -> pd.Series:
    """计算回撤序列.
    
    返回每个时点相对历史最高点的回撤比例（负值或0）.
    
    参数:
        prices: 价格序列
    
    返回:
        回撤序列
    """
    if prices.empty:
        return pd.Series(dtype=float)
    
    nav = calculate_nav_series(prices)
    peak = nav.cummax()
    
    drawdown = (nav - peak) / peak
    
    return drawdown
