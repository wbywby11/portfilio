"""滚动窗口波动率计算公式."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_rolling_volatility(
    returns: pd.Series,
    windows: list[int],
    annualization_factor: int = 260
) -> float:
    """计算多窗口最大波动率（年化）.
    
    根据文档公式：
    σ_n = sqrt((260/(n-1)) * Σ(r_i - mean(r))^2)
    σ_realized = max{σ_22, σ_65, σ_130}
    
    Args:
        returns: 收益率序列
        windows: 窗口列表（如[22, 65, 130]）
        annualization_factor: 年化因子（默认260交易日）
    
    Returns:
        float: 最大年化波动率
    """
    if returns.empty:
        return 0.0
    
    vols = []
    
    for window in windows:
        if len(returns) < window:
            continue
        
        # 取最近window个交易日
        returns_window = returns.tail(window)
        
        # 计算均值
        mean_ret = returns_window.mean()
        
        # 计算方差（年化）
        deviations = returns_window - mean_ret
        variance = (deviations ** 2).sum() / (window - 1)
        # 年化波动率 = sqrt(年化因子 × 方差)
        vol_annual = np.sqrt(variance * annualization_factor)
        
        vols.append(vol_annual)
    
    # 返回最大波动率
    return max(vols) if vols else 0.0


def compute_asset_rolling_volatility(
    prices: pd.DataFrame,
    windows: list[int] = [22, 65, 130],
    annualization_factor: int = 260
) -> pd.Series:
    """计算每个资产的滚动窗口波动率.
    
    Args:
        prices: 价格矩阵（index: 日期，columns: 资产代码）
        windows: 窗口列表
        annualization_factor: 年化因子
    
    Returns:
        pd.Series: 每个资产的已实现波动率（index: 资产代码）
    """
    from app.formula.returns import compute_simple_returns
    
    # 计算收益率
    returns = compute_simple_returns(prices)
    
    # 计算每个资产的波动率
    vols = {}
    for asset in returns.columns:
        asset_returns = returns[asset].dropna()
        vols[asset] = compute_rolling_volatility(
            asset_returns, 
            windows, 
            annualization_factor
        )
    
    return pd.Series(vols)


def compute_portfolio_volatility(
    returns: pd.DataFrame,
    weights: pd.Series,
    windows: list[int] = [22, 65, 130],
    annualization_factor: int = 260,
    fillna_zero: bool = False,
) -> float:
    """计算组合的滚动窗口波动率.
    
    步骤：
    1. 计算组合收益率序列：IR_s = Σ(w_c * r_c)
    2. 计算组合的多窗口波动率
    
    编制规则 B.4.1：fillna_zero=True 时对缺失收益率用 0 填充（假设无变动），与 step2/外部系统一致。
    
    Args:
        returns: 资产收益率矩阵
        weights: 资产权重
        windows: 窗口列表
        annualization_factor: 年化因子
        fillna_zero: 是否对缺失收益率填充 0（risk_budget_target_vol 混合动量策略使用）
    
    Returns:
        float: 组合已实现波动率
    """
    # 对齐资产
    common_assets = returns.columns.intersection(weights.index)
    if len(common_assets) == 0:
        return 0.0
    
    aligned_returns = returns[common_assets].fillna(0) if fillna_zero else returns[common_assets]
    aligned_weights = weights[common_assets]
    
    # 计算组合收益率序列
    portfolio_returns = (aligned_returns * aligned_weights).sum(axis=1)
    
    # 计算组合波动率
    return compute_rolling_volatility(
        portfolio_returns,
        windows,
        annualization_factor
    )
