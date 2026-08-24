# -*- coding: utf-8 -*-
"""
大类资产配置监测系统 - 数据类型定义

本模块集中定义所有数据类型，包括：
- PortfolioState: 组合状态
- AssetSelectionResult: 资产选择结果
- WeightResult: 权重计算结果
- RebalanceSignal: 月度调仓信号
- VolResetSignal: 波动率重置信号
- DailyResult: 每日处理结果
- DeviationInfo: 权重偏离度信息
- ReportData: 报告数据
- TradeOrder: 交易指令
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# =============================================================================
# 组合状态
# =============================================================================

@dataclass
class PortfolioState:
    """组合状态数据类"""
    
    date: str                                       # 当前日期 (YYYY-MM-DD)
    nav: float                                      # 当前净值
    nav_base: float                                 # 基准净值（上次调仓日的净值）
    positions_cny: Dict[str, float]                 # 人民币持仓金额 {资产名: 金额}
    positions_local: Dict[str, float]               # 本币持仓金额 {资产名: 金额}
    apl_local: Dict[str, float]                     # 本币累计损益 {资产名: 累计PnL}
    target_weights: Dict[str, float]                # 当前目标权重 {资产名: 权重}
    last_rebalance_date: str                        # 上次调仓日 (YYYY-MM-DD)
    last_rebalance_fx: Dict[str, float]             # 上次调仓日汇率 {资产名: 汇率}
    pending_rebalance: Optional[Dict] = None        # 待执行调仓信息
    positions_cny_base: Dict[str, float] = field(default_factory=dict)  # 调仓日基准CNY持仓 = nav × weight（与原型 BacktestState 对齐）
    nav_history: List[Dict] = field(default_factory=list)  # 近期净值历史
    total_trading_cost: float = 0.0                 # 累计交易费用
    total_replication_cost: float = 0.0             # 累计复制费用
    vol_reset_count: int = 0                        # 波动率重置次数
    day_count: int = 0                              # 净值运行天数（从基日起，包含所有处理日）
    trade_day_count: int = 0                         # 交易日计数（仅计入 trade_dates 中的日期，与原型 trade_day_idx 对齐）
    event_log: List[Dict] = field(default_factory=list)   # 事件日志
    # ---- 传统持仓模型字段（与回测 engine.py Position 对齐：NAV = cash + Σ(qty × close)）----
    # 仅在 PortfolioTracker.traditional_mode=True 时启用（典型为主观/手动配置策略）
    cash: float = 0.0                                       # 现金余额（与回测 Position.cash 对齐）
    quantities: Dict[str, float] = field(default_factory=dict)  # 资产持仓数量 {asset_code: qty}
    # 节假日/停牌价格回退：保存每个资产上一次出现的有效收盘价，
    # 当 prices_today 缺失时用于估值，避免 NAV 在非交易日归零（任务#12）。
    last_prices: Dict[str, float] = field(default_factory=dict)


# =============================================================================
# 资产选择结果
# =============================================================================

@dataclass
class AssetSelectionResult:
    """资产选择结果"""
    calc_date: str                          # 计算日期
    momentum_selected: List[str]            # 动量入选资产
    reversal_selected: List[str]            # 反转入选资产
    final_selected: List[str]               # 最终入选（并集）
    selection_status: Dict[str, str]        # 各资产入选状态：'动量'/'反转'/'动量+反转'/'未入选'
    momentum_scores: Dict[str, int]         # 各资产动量得分
    reversal_scores: Dict[str, float]       # 各资产反转得分


# =============================================================================
# 权重计算结果
# =============================================================================

@dataclass
class WeightResult:
    """权重计算结果"""
    calc_date: str                          # 计算日期
    weights: Dict[str, float]               # 最终权重 {资产: 权重}
    risk_budgets: Dict[str, float]          # 风险预算
    asset_vols: Dict[str, float]            # 资产波动率
    initial_weights: Dict[str, float]       # 初始权重
    scaled_weights: Dict[str, float]        # 缩放后权重
    portfolio_vol: float                    # 组合波动率
    scale_factor: float                     # 缩放系数
    total_leverage: float                   # 总杠杆


# =============================================================================
# 调仓信号
# =============================================================================

@dataclass
class RebalanceSignal:
    """月度调仓信号"""
    signal_type: str              # 'monthly'
    signal_date: str              # 信号日期（月末计算日）
    execute_date: str             # 执行日期（月度调仓是立即执行）
    new_weights: Dict[str, float] # 新目标权重
    selection_result: Optional[AssetSelectionResult]  # 资产选择结果
    weight_result: Optional[WeightResult]   # 权重计算结果


@dataclass
class VolResetSignal:
    """波动率重置信号"""
    signal_type: str              # 'vol_reset'
    signal_date: str              # 触发日期
    execute_date: str             # 执行日期（T+2）
    vol_trigger: float            # 触发波动率
    scale_factor: float           # 缩放因子 = TARGET_VOL / vol_trigger
    current_weights: Dict[str, float]  # 触发时实际权重(w_cny)
    new_weights: Dict[str, float]      # VW重置权重


# =============================================================================
# 每日处理结果
# =============================================================================

@dataclass
class DailyResult:
    """每日处理结果"""
    date: str                               # 日期
    nav: float                              # 当日净值
    nav_change_pct: float                   # 日涨跌幅 %
    total_leverage: float                   # 总杠杆
    asset_weights: Dict[str, float]         # 各资产实际权重 (positions_cny / nav)
    asset_returns_local: Dict[str, float]   # 各资产本币收益率
    asset_returns_cny: Dict[str, float]     # 各资产人民币收益率
    rebalance_executed: bool                # 是否执行了调仓
    rebalance_type: Optional[str]           # 调仓类型: 'monthly' / 'vol_reset' / None
    trading_cost: float                     # 当日交易费用
    replication_cost: float                 # 当日复制费用


# =============================================================================
# 权重偏离度信息
# =============================================================================

@dataclass
class DeviationInfo:
    """权重偏离度信息"""
    asset: str
    target_weight: float
    actual_weight: float
    deviation: float              # actual - target
    deviation_pct: float          # deviation / target * 100


# =============================================================================
# 交易指令
# =============================================================================

@dataclass
class TradeOrder:
    """交易指令"""
    asset: str
    direction: str                # 'buy' / 'sell'
    target_weight: float
    current_weight: float
    weight_change: float          # 权重变动量
    estimated_amount_cny: float   # 估算交易金额（人民币）


# =============================================================================
# 报告数据
# =============================================================================

@dataclass
class ReportData:
    """日报数据汇总"""
    date: str                                    # 日期
    state: PortfolioState                        # 当前状态
    daily_result: DailyResult                    # 当日结果
    deviations: List[DeviationInfo]              # 权重偏离度
    rebalance_signal: Optional[RebalanceSignal]  # 月度调仓信号
    vol_reset_signal: Optional[VolResetSignal]   # 波动率重置信号
    trade_orders: List[TradeOrder]               # 交易指令
    next_rebalance_date: str                     # 下次调仓日
    realized_vol: Optional[float]                # 当前已实现波动率


# =============================================================================
# 绩效指标
# =============================================================================

@dataclass
class PerformanceMetrics:
    """绩效指标"""
    cumulative_return: float      # 累计收益 (%)
    annual_return: float          # 年化收益 (%)
    annual_vol: float             # 年化波动率 (%)
    max_drawdown: float           # 最大回撤 (%)
    sharpe_ratio: float           # 夏普比率
