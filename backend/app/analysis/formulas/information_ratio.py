"""信息比率计算公式."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_information_ratio(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    annualize: bool = True,
    freq_factor: int = 252,
) -> float:
    """计算信息比率（Information Ratio）.

    公式: IR = 超额收益均值 / 跟踪误差
    衡量相对于基准的风险调整后超额收益。

    参数:
        returns: 资产收益率序列（日度）
        benchmark_returns: 基准收益率序列（日度）
        annualize: 是否年化
        freq_factor: 年化因子（默认252个交易日）

    返回:
        信息比率
    """
    # 对齐日期
    aligned = pd.concat([returns, benchmark_returns], axis=1).dropna()
    if len(aligned) < 2:
        return 0.0

    active_returns = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    tracking_error = float(active_returns.std())

    if tracking_error == 0:
        return 0.0

    mean_active = float(active_returns.mean())

    if annualize:
        mean_active *= freq_factor
        tracking_error *= np.sqrt(freq_factor)

    return mean_active / tracking_error
