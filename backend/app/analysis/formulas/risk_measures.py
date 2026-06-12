"""风险度量计算 - VaR / CVaR."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_var(
    returns: pd.Series,
    confidence_level: float = 0.95,
    method: str = "historical",
) -> float:
    """计算VaR (Value at Risk).

    历史模拟法：直接取收益率分布的分位数。
    参数法：假设正态分布，通过均值和标准差计算。

    返回值为正数，表示在置信水平下的最大损失。

    参数:
        returns: 收益率序列
        confidence_level: 置信水平（默认95%）
        method: 计算方法，"historical" 或 "parametric"

    返回:
        VaR值（正数）
    """
    clean = returns.dropna()
    if clean.empty:
        return 0.0

    if method == "historical":
        var = -float(np.percentile(clean, (1 - confidence_level) * 100))
    elif method == "parametric":
        from scipy.stats import norm

        mu = float(clean.mean())
        sigma = float(clean.std())
        var = -(mu + norm.ppf(1 - confidence_level) * sigma)
    else:
        raise ValueError(f"Unsupported method: {method}")

    return max(var, 0.0)


def calculate_cvar(
    returns: pd.Series,
    confidence_level: float = 0.95,
    method: str = "historical",
) -> float:
    """计算CVaR (Conditional VaR) / Expected Shortfall.

    VaR以下的平均损失（尾部均值）。

    参数:
        returns: 收益率序列
        confidence_level: 置信水平（默认95%）
        method: 计算方法，"historical"

    返回:
        CVaR值（正数）
    """
    clean = returns.dropna()
    if clean.empty:
        return 0.0

    if method == "historical":
        var_threshold = float(np.percentile(clean, (1 - confidence_level) * 100))
        tail_returns = clean[clean <= var_threshold]
        if len(tail_returns) == 0:
            return calculate_var(returns, confidence_level, method)
        cvar = -float(tail_returns.mean())
    else:
        raise ValueError(f"Unsupported method for CVaR: {method}")

    return max(cvar, 0.0)
