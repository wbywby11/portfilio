"""单资产指标计算模块.

本模块专注于单资产的完整指标计算，组合 formulas/ 中的基础公式。
对于跨资产的对比分析，请使用 analyzers/ 模块。
"""

# 从 formulas 导入基础公式（向后兼容）
from app.analysis.formulas import (
    calculate_simple_returns,
    calculate_log_returns,
    calculate_cumulative_return,
    calculate_annualized_return,
    calculate_volatility,
    calculate_rolling_volatility,
    calculate_max_drawdown,
    calculate_drawdown_series,
    calculate_sharpe_ratio,
    calculate_calmar_ratio,
    calculate_correlation_matrix,
    calculate_nav_from_prices,
    calculate_nav_from_returns,
)

# 兼容性别名
calculate_nav_series = calculate_nav_from_prices  # 向后兼容

# 导出单资产指标集
from app.analysis.metrics.asset_metrics import (
    AssetMetrics,
    calculate_asset_metrics,
)

__all__ = [
    # 基础公式（向后兼容）
    "calculate_simple_returns",
    "calculate_log_returns",
    "calculate_cumulative_return",
    "calculate_annualized_return",
    "calculate_volatility",
    "calculate_rolling_volatility",
    "calculate_max_drawdown",
    "calculate_drawdown_series",
    "calculate_sharpe_ratio",
    "calculate_calmar_ratio",
    "calculate_correlation_matrix",
    "calculate_nav_from_prices",
    "calculate_nav_from_returns",
    "calculate_nav_series",  # 兼容别名
    # 单资产完整指标
    "AssetMetrics",
    "calculate_asset_metrics",
]
