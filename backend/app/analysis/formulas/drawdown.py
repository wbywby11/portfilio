"""回撤计算公式.

包含回撤序列、最大回撤等。
数据缺失或不一致时对异常值进行处理，避免回撤、收益率等出现极端值。
"""

from __future__ import annotations

import math
import pandas as pd


def _clean_prices_series(prices: pd.Series) -> pd.Series:
    """清理价格序列：inf/nan 前向填充再后向填充，保证为有限值。"""
    if prices.empty:
        return prices
    out = pd.to_numeric(prices, errors="coerce")
    out = out.replace([float("inf"), float("-inf")], float("nan"))
    out = out.ffill().bfill()
    # 若仍存在 nan（全序列无效），置为 1.0 避免除零
    out = out.fillna(1.0)
    return out


def calculate_drawdown_series(prices: pd.Series) -> pd.Series:
    """计算回撤序列.
    
    返回每个时点相对历史最高点的回撤比例（负值或0）.
    对缺失/异常价格做清理，并将回撤限制在 [-1, 0] 内。
    
    公式: DD_t = (NAV_t - Peak_t) / Peak_t
    其中 Peak_t = max(NAV_0, ..., NAV_t)
    
    参数:
        prices: 价格序列
    
    返回:
        回撤序列（负值或0）
    """
    if prices.empty:
        return pd.Series(dtype=float)

    cleaned = _clean_prices_series(prices)
    first = float(cleaned.iloc[0])
    if first <= 0 or not math.isfinite(first):
        return pd.Series(0.0, index=prices.index)
    nav = cleaned / first

    peak = nav.cummax()
    drawdown = (nav - peak) / peak.where(peak > 0, float("nan"))
    drawdown = drawdown.fillna(0.0).replace([float("inf"), float("-inf")], 0.0)
    # 限制在 [-1, 0]，避免数据异常导致极端回撤
    drawdown = drawdown.clip(lower=-1.0, upper=0.0)
    return drawdown


def calculate_max_drawdown(prices: pd.Series) -> float:
    """计算最大回撤.
    
    公式: max_DD = min(DD_t)
    结果限制在 [-1, 0] 内。
    
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

    max_dd = float(drawdown_series.min())
    if not math.isfinite(max_dd):
        return 0.0
    return max(-1.0, min(0.0, max_dd))
