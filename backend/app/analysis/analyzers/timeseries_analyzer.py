"""Time series analyzer for NAV and drawdown calculation."""

from __future__ import annotations

from typing import Dict

import pandas as pd

from app.analysis.config import AnalysisConfig
from app.analysis.types import TimeSeriesData
from app.analysis.metrics import (
    calculate_simple_returns,
    calculate_nav_series,
    calculate_drawdown_series,
)


class TimeSeriesAnalyzer:
    """时间序列分析器."""
    
    def __init__(self, config: AnalysisConfig | None = None) -> None:
        """初始化分析器.
        
        参数:
            config: 分析配置（可选）
        """
        self._config = config or AnalysisConfig()
    
    def analyze(
        self,
        prices: pd.Series,
        thscode: str,
    ) -> TimeSeriesData:
        """分析单个资产的时间序列.
        
        参数:
            prices: 价格序列（index=时间）
            thscode: 资产代码
        
        返回:
            TimeSeriesData 对象
        """
        if prices.empty or len(prices) < 2:
            raise ValueError(f"价格序列为空或数据点不足: {thscode}")
        
        # 1. 计算收益率序列
        returns = calculate_simple_returns(prices)
        
        # 2. 计算归一化净值序列
        nav = calculate_nav_series(prices)
        
        # 3. 计算回撤序列
        drawdown = calculate_drawdown_series(prices)
        
        return TimeSeriesData(
            thscode=thscode,
            nav=nav,
            drawdown=drawdown,
            returns=returns,
        )
    
    def analyze_batch(
        self,
        prices: pd.DataFrame,
    ) -> Dict[str, TimeSeriesData]:
        """批量分析多个资产的时间序列.
        
        参数:
            prices: 价格矩阵（index=时间, columns=资产代码）
        
        返回:
            {thscode: TimeSeriesData} 字典
        """
        if prices.empty:
            return {}
        
        results = {}
        for thscode in prices.columns:
            asset_prices = prices[thscode].dropna()
            if len(asset_prices) >= 2:
                try:
                    results[thscode] = self.analyze(asset_prices, thscode)
                except Exception as e:
                    # 跳过无法分析的资产
                    continue
        
        return results
