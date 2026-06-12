"""Data types for analysis module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd

# 从 metrics 导入 AssetMetrics（避免重复定义）
from app.analysis.metrics import AssetMetrics


@dataclass
class CorrelationMatrix:
    """资产相关性矩阵."""
    
    matrix: pd.DataFrame             # 相关性矩阵（index/columns=thscode）
    method: str                      # 计算方法（pearson/spearman/kendall）
    start_date: str
    end_date: str


@dataclass
class TimeSeriesData:
    """时间序列分析数据."""
    
    thscode: str
    nav: pd.Series                   # 累计净值序列（归一化，初始=1）
    drawdown: pd.Series              # 回撤序列（负值）
    returns: pd.Series               # 收益率序列


@dataclass
class DashboardData:
    """看板数据（整合所有分析结果）."""
    
    asset_metrics: Dict[str, AssetMetrics]
    correlation_matrix: CorrelationMatrix
    timeseries_data: Dict[str, TimeSeriesData]
    start_date: str
    end_date: str
