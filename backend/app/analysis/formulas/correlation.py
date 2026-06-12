"""相关性计算公式."""

from __future__ import annotations

from typing import Literal

import pandas as pd


def calculate_correlation_matrix(
    returns: pd.DataFrame,
    method: Literal["pearson", "spearman", "kendall"] = "pearson"
) -> pd.DataFrame:
    """计算相关性矩阵.
    
    支持三种相关性方法：
    - pearson: 线性相关性（默认）
    - spearman: 秩相关性（适合非线性单调关系）
    - kendall: 秩相关性（适合小样本）
    
    参数:
        returns: 收益率矩阵（index=时间, columns=资产代码）
        method: 相关性方法
    
    返回:
        相关性矩阵（DataFrame，index和columns为资产代码）
    """
    if returns.empty:
        return pd.DataFrame()
    
    corr_matrix = returns.corr(method=method)
    
    return corr_matrix
