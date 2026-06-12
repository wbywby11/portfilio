"""Calmar比率计算公式."""

from __future__ import annotations


def calculate_calmar_ratio(
    annualized_return: float,
    max_drawdown: float
) -> float:
    """计算Calmar比率.
    
    公式: Calmar = 年化收益率 / |最大回撤|
    
    参数:
        annualized_return: 年化收益率
        max_drawdown: 最大回撤（通常为负值）
    
    返回:
        Calmar比率
    """
    if max_drawdown == 0.0:
        return 0.0
    
    return annualized_return / abs(max_drawdown)
