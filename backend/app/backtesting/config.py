"""BacktestConfig：计算引擎的执行级配置（计算内核层）.

仅包含交易相关参数（初始资金、费率、滑点等）；策略口径参数一律存于
DB 模型文档并经 build_backtest_params 组装，不在此处定义。
"""
from dataclasses import dataclass
from typing import List, Literal, Dict, Optional


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

    # 回测起始净值（NAV），用于投资组合和统一回测输出
    initial_nav: float = 1000.0

    # 交易成本参数（回测唯一的成本模型：手续费 + 滑点，均可设为 0 观察理想状态）
    commission_rate: float = 0.0003  # 手续费率
    slippage: float = 0.0005         # 滑点率

    # 交互式权重调整（仅 manual_allocation 策略）：指定日期使用用户预设的权重
    # 格式: { "YYYYMMDD": {"weights": {code: w, ...}, "auto_normalize": bool}, ... }
    manual_weight_adjustments: Optional[Dict[str, Dict]] = None

    # 主观策略仅按预设日期调仓：为 True 时不执行周期性调仓，但波动率阈值重置仍执行；预设日与波动率重置日均在 manual_weight_adjustments 或 T+2 执行
    rebalance_only_on_preset_dates: bool = False

    # 期初建仓权重：若设置则在回测首日按此权重建仓（否则期初为 100% 现金）
    initial_weights: Optional[Dict[str, float]] = None
    # 期初建仓是否将权重归一化为和 1（默认 False 不归一化；True 时归一化至和 1）
    initial_weights_auto_normalize: bool = False

    # 执行延迟（交易日）：覆盖策略声明的 execution_delay
    # None = 使用策略默认值（如 vol_scaled_budget 默认 T+2）
    # 0 = 信号日当天执行（T+0），1 = T+1，2 = T+2，...
    execution_delay: Optional[int] = None

    # 目标波动率（从 control 模块读取，用于前端展示）
    target_vol: Optional[float] = None
