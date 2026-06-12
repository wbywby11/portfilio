"""索提诺比率计算公式."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    annualize: bool = True,
    freq_factor: int = 252,
) -> float:
    """计算索提诺比率（Sortino Ratio）.

    公式: Sortino = (年化收益 - 无风险利率) / 下行标准差
    仅计算负收益的波动率作为风险度量。

    参数:
        returns: 收益率序列（日度）
        risk_free_rate: 无风险利率（年化）
        annualize: 是否年化
        freq_factor: 年化因子（默认252个交易日）

    返回:
        索提诺比率
    """
    if returns.empty or len(returns) < 2:
        return 0.0

    excess_returns = returns - risk_free_rate / freq_factor
    downside_returns = excess_returns[excess_returns < 0]

    if len(downside_returns) == 0:
        return float("inf")

    downside_std = float(np.sqrt(np.mean(downside_returns ** 2)))
    if annualize:
        downside_std *= np.sqrt(freq_factor)

    mean_excess = float(excess_returns.mean())
    if annualize:
        mean_excess *= freq_factor

    if downside_std == 0:
        return float("inf")

    return mean_excess / downside_std
