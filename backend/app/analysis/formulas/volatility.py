"""波动率计算公式.

包含滚动波动率等 analysis 独有公式。
基础波动率已统一由 app.formula.volatility 提供，
通过 __init__.py 中的薄包装保持 calculate_* 命名兼容。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_rolling_volatility(
    returns: pd.Series,
    window: int = 20,
    annualize: bool = False,
    freq_factor: int = 260
) -> pd.Series:
    """计算滚动波动率.
    
    参数:
        returns: 收益率序列
        window: 滚动窗口（交易日数）
        annualize: 是否年化
        freq_factor: 年化因子
    
    返回:
        滚动波动率序列
    """
    if returns.empty:
        return pd.Series(dtype=float)
    
    rolling_vol = returns.rolling(window=window).std()
    
    if annualize:
        rolling_vol = rolling_vol * np.sqrt(freq_factor)
    
    return rolling_vol
