"""NAV (Net Asset Value) calculation formulas."""

from __future__ import annotations

import pandas as pd


def calculate_nav_series(prices: pd.Series) -> pd.Series:
    """计算归一化净值序列.
    
    将价格序列转换为净值序列（初始值=1）.
    
    参数:
        prices: 价格序列
    
    返回:
        净值序列（归一化）
    """
    if prices.empty:
        return pd.Series(dtype=float)
    
    # 归一化：第一个价格=1
    nav = prices / float(prices.iloc[0])
    
    return nav
