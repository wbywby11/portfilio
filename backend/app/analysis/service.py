"""Analysis service for unified data analysis interface."""

from __future__ import annotations

from typing import List, Dict

import pandas as pd

from app.services.market_service import MarketService
from app.analysis.config import AnalysisConfig
from app.analysis.types import AssetMetrics, CorrelationMatrix, TimeSeriesData, DashboardData
from app.analysis.analyzers import AssetAnalyzer, CorrelationAnalyzer, TimeSeriesAnalyzer


class AnalysisService:
    """数据分析服务（对外统一接口）.
    
    整合所有分析能力，提供一站式分析服务。
    """
    
    def __init__(
        self,
        data_service: MarketService,
        config: AnalysisConfig | None = None,
    ) -> None:
        """初始化分析服务.
        
        参数:
            data_service: 数据服务（用于获取价格数据）
            config: 分析配置（可选，默认使用默认配置）
        """
        self._data_service = data_service
        self._config = config or AnalysisConfig()
        
        # 初始化各分析器
        self._asset_analyzer = AssetAnalyzer(self._config)
        self._corr_analyzer = CorrelationAnalyzer(self._config)
        self._ts_analyzer = TimeSeriesAnalyzer(self._config)
    
    async def generate_dashboard(
        self,
        thscodes: List[str],
        start_date: str,
        end_date: str,
        correlation_method: str | None = None,
    ) -> DashboardData:
        """生成完整的看板数据（一站式接口）.
        
        参数:
            thscodes: 资产代码列表
            start_date: 开始日期
            end_date: 结束日期
            correlation_method: 相关性计算方法（可选）
        
        返回:
            DashboardData 对象
        """
        # 1. 从 MarketDataService 获取价格矩阵
        prices = await self._data_service.get_price_matrix(
            thscodes=thscodes,
            start_date=start_date,
            end_date=end_date,
        )
        
        if prices.empty:
            raise ValueError(f"未获取到价格数据: {thscodes}, {start_date} - {end_date}")
        
        # 2. 调用 AssetAnalyzer 批量计算资产指标
        asset_metrics = self._asset_analyzer.analyze_batch(prices)
        
        # 3. 调用 CorrelationAnalyzer 计算相关性矩阵
        correlation_matrix = self._corr_analyzer.analyze(prices, method=correlation_method)
        
        # 4. 调用 TimeSeriesAnalyzer 批量构建时间序列数据
        timeseries_data = self._ts_analyzer.analyze_batch(prices)
        
        # 5. 打包为 DashboardData 返回
        return DashboardData(
            asset_metrics=asset_metrics,
            correlation_matrix=correlation_matrix,
            timeseries_data=timeseries_data,
            start_date=start_date,
            end_date=end_date,
        )
    
    async def get_asset_metrics(
        self,
        thscodes: List[str],
        start_date: str,
        end_date: str,
    ) -> Dict[str, AssetMetrics]:
        """仅获取资产统计指标.
        
        参数:
            thscodes: 资产代码列表
            start_date: 开始日期
            end_date: 结束日期
        
        返回:
            {thscode: AssetMetrics} 字典
        """
        prices = await self._data_service.get_price_matrix(
            thscodes=thscodes,
            start_date=start_date,
            end_date=end_date,
        )
        
        if prices.empty:
            raise ValueError(f"未获取到价格数据: {thscodes}, {start_date} - {end_date}")
        
        return self._asset_analyzer.analyze_batch(prices)
    
    async def get_correlation_matrix(
        self,
        thscodes: List[str],
        start_date: str,
        end_date: str,
        method: str | None = None,
    ) -> CorrelationMatrix:
        """仅获取相关性矩阵.
        
        参数:
            thscodes: 资产代码列表
            start_date: 开始日期
            end_date: 结束日期
            method: 相关性计算方法（可选）
        
        返回:
            CorrelationMatrix 对象
        """
        prices = await self._data_service.get_price_matrix(
            thscodes=thscodes,
            start_date=start_date,
            end_date=end_date,
        )
        
        if prices.empty:
            raise ValueError(f"未获取到价格数据: {thscodes}, {start_date} - {end_date}")
        
        return self._corr_analyzer.analyze(prices, method=method)
    
    async def get_timeseries_data(
        self,
        thscodes: List[str],
        start_date: str,
        end_date: str,
    ) -> Dict[str, TimeSeriesData]:
        """仅获取时间序列数据.
        
        参数:
            thscodes: 资产代码列表
            start_date: 开始日期
            end_date: 结束日期
        
        返回:
            {thscode: TimeSeriesData} 字典
        """
        prices = await self._data_service.get_price_matrix(
            thscodes=thscodes,
            start_date=start_date,
            end_date=end_date,
        )
        
        if prices.empty:
            raise ValueError(f"未获取到价格数据: {thscodes}, {start_date} - {end_date}")
        
        return self._ts_analyzer.analyze_batch(prices)
