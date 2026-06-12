from dataclasses import dataclass
from typing import List, Literal, Dict, Optional

import pandas as pd


@dataclass
class BacktestConfig:
    """回测配置 - 仅包含交易相关参数.
    
    注意: lookback_days已移至策略参数中,回测配置只关注交易执行层面的参数
    """

    name: str
    thscodes: List[str]
    start_date: str  # 回测开始日期, 格式: "YYYYMMDD"
    end_date: str    # 回测结束日期, 格式: "YYYYMMDD"

    # 调仓频率（month_end=月末最后一个交易日，与编制规则/交易日历一致）
    rebalance_freq: Literal["daily", "weekly", "monthly", "month_end", "quarterly", "yearly"] = "monthly"

    # 初始资金
    initial_cash: float = 10_000_000.0

    # 交易成本参数
    commission_rate: float = 0.0003  # 手续费率
    slippage: float = 0.0005         # 滑点率
    
    # 净值计算模式（新增）
    use_index_nav: bool = False  # 是否启用指数净值计算（默认使用简单的组合市值法）
    
    # 指数净值配置（仅当 use_index_nav=True 时生效）
    index_nav_initial: float = 1000.0  # 初始净值
    fx_rates: Optional[Dict[str, pd.Series]] = None  # 汇率数据 {asset_code: Series}
    transaction_costs: Optional[Dict[str, float]] = None  # 交易费率 {asset_code: rate}
    replication_costs: Optional[Dict[str, float]] = None  # 复制费率 {asset_code: annual_rate}
    tr_series: Optional[Dict[str, pd.Series]] = None  # TR样本点位序列 {asset_code: Series(TR)}

    # 交互式权重调整（仅 manual_allocation 策略）：指定日期使用用户预设的权重
    # 格式: { "YYYYMMDD": {"weights": {code: w, ...}, "auto_normalize": bool}, ... }
    manual_weight_adjustments: Optional[Dict[str, Dict]] = None

    # 主观策略仅按预设日期调仓：为 True 时不执行周期性调仓，但波动率阈值重置仍执行；预设日与波动率重置日均在 manual_weight_adjustments 或 T+2 执行
    rebalance_only_on_preset_dates: bool = False

    # 期初建仓权重：若设置则在回测首日按此权重建仓（否则期初为 100% 现金）
    initial_weights: Optional[Dict[str, float]] = None
    # 期初建仓是否将权重归一化为和 1（默认 False 不归一化；True 时归一化至和 1）
    initial_weights_auto_normalize: bool = False

    # 混合动量导出：波动率重置事件收集器（仅 risk_budget_target_vol 混合动量策略使用）
    vol_reset_events_collector: Optional[List] = None
