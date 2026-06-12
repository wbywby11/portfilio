"""Correlation calculation formulas."""

from __future__ import annotations

from typing import Literal

import pandas as pd


def calculate_correlation_matrix(
    returns: pd.DataFrame,
    method: Literal["pearson", "spearman", "kendall"] = "pearson"
) -> pd.DataFrame:
    """计算相关性矩阵.
    
    参数:
        returns: 收益率矩阵（index=时间, columns=资产代码）
        method: 相关性方法
    
    返回:
        相关性矩阵
    """
    if returns.empty:
        return pd.DataFrame()
    
    corr_matrix = returns.corr(method=method)
    
    return corr_matrix
