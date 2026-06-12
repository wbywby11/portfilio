"""Calmar ratio calculation formula."""

from __future__ import annotations


def calculate_calmar_ratio(
    annualized_return: float,
    max_drawdown: float
) -> float:
    """计算Calmar比率.
    
    公式: annualized_return / abs(max_drawdown)
    
    参数:
        annualized_return: 年化收益率
        max_drawdown: 最大回撤
    
    返回:
        Calmar比率
    """
    if max_drawdown == 0.0:
        return 0.0
    
    return annualized_return / abs(max_drawdown)
