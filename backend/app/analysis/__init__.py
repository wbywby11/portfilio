"""数据分析模块.

专注于单资产的统计分析和多资产的对比分析，不涉及资产组合后的绩效分析。

模块分层：
- formulas/: 基础计算公式（TR、净值、收益率、波动率等）
- metrics/: 单资产指标计算（组合 formulas 公式）
- analyzers/: 分析器（单资产、多资产对比、相关性、时间序列）
- service.py: 统一服务接口
"""

from app.analysis.config import AnalysisConfig
from app.analysis.types import AssetMetrics, CorrelationMatrix, TimeSeriesData, DashboardData
from app.analysis.analyzers import (
    AssetAnalyzer,
    ComparativeAnalyzer,
    ComparativeMetrics,
    CorrelationAnalyzer,
    TimeSeriesAnalyzer,
)
from app.analysis.service import AnalysisService

__all__ = [
    "AnalysisConfig",
    "AssetMetrics",
    "CorrelationMatrix",
    "TimeSeriesData",
    "DashboardData",
    "AssetAnalyzer",
    "ComparativeAnalyzer",
    "ComparativeMetrics",
    "CorrelationAnalyzer",
    "TimeSeriesAnalyzer",
    "AnalysisService",
]
