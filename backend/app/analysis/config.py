"""Analysis configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnalysisConfig:
    """数据分析配置."""
    
    risk_free_rate: float = 0.0      # 无风险利率（年化）
    freq_factor: int = 260           # 年化因子（交易日天数），全系统统一口径 260
    correlation_method: str = "pearson"  # 默认相关性方法
