"""Correlation analyzer for asset relationship analysis."""

from __future__ import annotations

import pandas as pd

from app.analysis.config import AnalysisConfig
from app.analysis.types import CorrelationMatrix
from app.analysis.metrics import calculate_simple_returns, calculate_correlation_matrix


class CorrelationAnalyzer:
    """资产间相关性分析器."""
    
    def __init__(self, config: AnalysisConfig | None = None) -> None:
        """初始化分析器.
        
        参数:
            config: 分析配置（可选）
        """
        self._config = config or AnalysisConfig()
    
    def analyze(
        self,
        prices: pd.DataFrame,
        method: str | None = None,
    ) -> CorrelationMatrix:
        """分析资产间相关性.
        
        参数:
            prices: 价格矩阵（index=时间, columns=资产代码）
            method: 相关性方法（默认使用config中的设置）
        
        返回:
            CorrelationMatrix 对象
        """
        if prices.empty:
            raise ValueError("价格矩阵为空")
        
        # 使用指定方法或配置中的默认方法
        corr_method = method or self._config.correlation_method
        
        # 获取时间区间
        start_date = str(prices.index[0].date()) if hasattr(prices.index[0], 'date') else str(prices.index[0])
        end_date = str(prices.index[-1].date()) if hasattr(prices.index[-1], 'date') else str(prices.index[-1])
        
        # 计算收益率矩阵
        returns_dict = {}
        for thscode in prices.columns:
            asset_prices = prices[thscode].dropna()
            if len(asset_prices) >= 2:
                returns_dict[thscode] = calculate_simple_returns(asset_prices)
        
        if not returns_dict:
            raise ValueError("无法计算收益率，所有资产数据不足")
        
        # 对齐所有收益率序列的时间索引
        returns_df = pd.DataFrame(returns_dict)
        
        # 计算相关性矩阵
        corr_matrix = calculate_correlation_matrix(returns_df, method=corr_method)
        
        return CorrelationMatrix(
            matrix=corr_matrix,
            method=corr_method,
            start_date=start_date,
            end_date=end_date,
        )
