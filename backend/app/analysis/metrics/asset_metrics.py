"""单资产完整指标计算.

本模块组合 formulas/ 中的基础公式，计算单资产的完整指标集。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from app.analysis.formulas import (
    calculate_simple_returns,
    calculate_cumulative_return,
    calculate_annualized_return,
    calculate_volatility,
    calculate_max_drawdown,
    calculate_sharpe_ratio,
    calculate_calmar_ratio,
)
from app.analysis.performance import PERIODS_PER_YEAR_365, calendar_span_days


@dataclass
class AssetMetrics:
    """单资产完整指标集.
    
    包含收益指标、风险指标、风险调整收益指标。
    """
    
    thscode: str
    start_date: str
    end_date: str
    
    # 收益指标
    cumulative_return: float         # 累计收益率
    annualized_return: float         # 年化收益率（260 交易日）
    
    # 风险指标
    daily_volatility: float          # 日度波动率
    annualized_volatility: float     # 年化波动率（260 交易日）
    max_drawdown: float              # 最大回撤
    
    # 风险调整收益指标
    sharpe_ratio: float              # 夏普比率（260 交易日）
    calmar_ratio: float              # Calmar比率（260 交易日）

    # 365 口径（自然日/年）：同一组公式只换年化因子；累计收益/最大回撤不复制
    annualized_return_365: float = 0.0
    annualized_volatility_365: float = 0.0
    sharpe_ratio_365: float = 0.0
    calmar_ratio_365: float = 0.0


def calculate_asset_metrics(
    prices: pd.Series,
    thscode: str,
    risk_free_rate: float = 0.0,
    freq_factor: int = 260,
) -> AssetMetrics:
    """计算单资产的完整指标集.
    
    参数:
        prices: 价格序列（index=时间）
        thscode: 资产代码
        risk_free_rate: 无风险利率（年化）
        freq_factor: 年化因子（默认260个交易日）；365 口径固定按 365 自然日同步计算
    
    返回:
        AssetMetrics 对象
    
    异常:
        ValueError: 价格序列为空或数据点不足
    """
    if prices.empty or len(prices) < 2:
        raise ValueError(f"价格序列为空或数据点不足: {thscode}")
    
    # 获取时间区间
    start_date = str(prices.index[0].date()) if hasattr(prices.index[0], 'date') else str(prices.index[0])
    end_date = str(prices.index[-1].date()) if hasattr(prices.index[-1], 'date') else str(prices.index[-1])
    
    # 1. 计算收益率
    returns = calculate_simple_returns(prices)
    
    # 2. 计算收益指标
    cumulative_return = calculate_cumulative_return(prices)
    annualized_return = calculate_annualized_return(prices, freq_factor)
    
    # 3. 计算风险指标
    daily_volatility = calculate_volatility(returns, annualize=False, freq_factor=freq_factor)
    annualized_volatility = calculate_volatility(returns, annualize=True, freq_factor=freq_factor)
    max_drawdown = calculate_max_drawdown(prices)
    
    # 4. 计算风险调整收益指标
    sharpe_ratio = calculate_sharpe_ratio(
        returns,
        risk_free_rate=risk_free_rate,
        freq_factor=freq_factor
    )
    calmar_ratio = calculate_calmar_ratio(annualized_return, max_drawdown)

    # 5. 365 口径：分母换成日历天数，与 compute_performance 同一换算
    n_td = len(returns)
    span = calendar_span_days(prices.index)
    if span is None or n_td == 0:
        # 首末未跨日或没有有效收益样本：365 口径没有可用的分母
        annualized_return_365 = 0.0
        annualized_volatility_365 = 0.0
        sharpe_ratio_365 = 0.0
    else:
        if cumulative_return > -1.0:
            annualized_return_365 = float(
                (1.0 + cumulative_return) ** (PERIODS_PER_YEAR_365 / span) - 1.0
            )
        else:
            annualized_return_365 = -1.0
        # 日波动率 → 每日历日波动率 → 按 365 天年化，与 260 口径收敛到同一个值
        annualized_volatility_365 = float(daily_volatility) * math.sqrt(
            PERIODS_PER_YEAR_365 * n_td / span
        )
        # 算术口径夏普：每日历日收益 = 日收益 / d，标准差 = 日标准差 / √d
        d = span / n_td
        excess_mean = float(returns.mean()) / d - risk_free_rate / PERIODS_PER_YEAR_365
        excess_std = float(returns.std()) / math.sqrt(d)
        sharpe_ratio_365 = (
            float(excess_mean / excess_std * math.sqrt(PERIODS_PER_YEAR_365))
            if excess_std > 0 else 0.0
        )
    calmar_ratio_365 = calculate_calmar_ratio(annualized_return_365, max_drawdown)
    
    return AssetMetrics(
        thscode=thscode,
        start_date=start_date,
        end_date=end_date,
        cumulative_return=cumulative_return,
        annualized_return=annualized_return,
        daily_volatility=daily_volatility,
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        calmar_ratio=calmar_ratio,
        annualized_return_365=annualized_return_365,
        annualized_volatility_365=annualized_volatility_365,
        sharpe_ratio_365=sharpe_ratio_365,
        calmar_ratio_365=calmar_ratio_365,
    )
