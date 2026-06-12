"""单资产分析器.

负责单个资产的完整指标计算，基于 metrics.calculate_asset_metrics。
"""

from __future__ import annotations

from typing import Dict

import pandas as pd

from app.analysis.config import AnalysisConfig
from app.analysis.metrics import AssetMetrics, calculate_asset_metrics


class AssetAnalyzer:
    """单资产统计指标分析器.
    
    使用 metrics.calculate_asset_metrics 计算单资产的完整指标集。
    """
    
    def __init__(self, config: AnalysisConfig) -> None:
        """初始化分析器.
        
        参数:
            config: 分析配置（包含无风险利率、年化因子等）
        """
        self._config = config
    
    def analyze(
        self,
        prices: pd.Series,
        thscode: str,
    ) -> AssetMetrics:
        """分析单个资产，返回完整的统计指标.
        
        参数:
            prices: 价格序列（index=时间）
            thscode: 资产代码
        
        返回:
            AssetMetrics 对象
        """
        return calculate_asset_metrics(
            prices=prices,
            thscode=thscode,
            risk_free_rate=self._config.risk_free_rate,
            freq_factor=self._config.freq_factor,
        )
    
    def analyze_batch(
        self,
        prices: pd.DataFrame,
    ) -> Dict[str, AssetMetrics]:
        """批量分析多个资产.
        
        参数:
            prices: 价格矩阵（index=时间, columns=资产代码）
        
        返回:
            {thscode: AssetMetrics} 字典
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
