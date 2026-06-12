# -*- coding: utf-8 -*-
"""
大类资产配置监测系统 - 监测模块

本模块提供大类资产配置指数策略的实盘监测功能，包括：
- 组合跟踪：每日损益更新、调仓执行
- 策略引擎：资产选择（动量+反转）、权重计算（风险预算）
- 信号检测：月度调仓信号、波动率重置信号
- 报告生成：绩效计算、数据格式化
"""

# 数据类型
from app.monitor.types import (
    PortfolioState,
    AssetSelectionResult,
    WeightResult,
    RebalanceSignal,
    VolResetSignal,
    DailyResult,
    DeviationInfo,
    TradeOrder,
    ReportData,
    PerformanceMetrics,
)

# 配置
from app.monitor import config

# 数据提供者
from app.monitor.data_provider import (
    MongoDataProvider,
    SyncDataProvider,
    create_data_provider,
    get_sync_provider,
)

# 组合跟踪器
from app.monitor.portfolio_tracker import PortfolioTracker

# 策略引擎
from app.monitor.strategy_engine import StrategyEngine

# 信号检测器
from app.monitor.signal_detector import SignalDetector

# 报告生成器
from app.monitor.report_generator import ReportGenerator


__all__ = [
    # 数据类型
    'PortfolioState',
    'AssetSelectionResult',
    'WeightResult',
    'RebalanceSignal',
    'VolResetSignal',
    'DailyResult',
    'DeviationInfo',
    'TradeOrder',
    'ReportData',
    'PerformanceMetrics',
    # 配置
    'config',
    # 数据提供者
    'MongoDataProvider',
    'SyncDataProvider',
    'create_data_provider',
    'get_sync_provider',
    # 核心类
    'PortfolioTracker',
    'StrategyEngine',
    'SignalDetector',
    'ReportGenerator',
]
