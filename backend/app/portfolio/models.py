# -*- coding: utf-8 -*-
"""
组合管理数据模型

包含组合管理和模拟交易的所有领域模型：
- Portfolio: 投资组合
- Position: 持仓
- RebalanceRecord: 调仓记录
- SimTrade: 模拟成交记录
- SimDailySnapshot: 逐日持仓快照

支持三种组合来源：
- MANUAL: 手工创建组合
- SINGLE_STRATEGY: 单策略模型驱动
- PORTFOLIO_MODEL: 投资组合模型驱动（多策略复合）
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


# ============================================================
# 组合相关模型
# ============================================================

class PortfolioSource(str, Enum):
    """组合来源类型"""
    MANUAL = "manual"                       # 手工创建
    SINGLE_STRATEGY = "single_strategy"     # 单策略模型驱动
    PORTFOLIO_MODEL = "portfolio_model"     # 投资组合模型驱动（多策略）


class PortfolioStatus(str, Enum):
    """组合状态"""
    ACTIVE = "active"
    ARCHIVED = "archived"


class RebalanceAction(str, Enum):
    """调仓动作"""
    BUY = "买入"
    SELL = "卖出"
    ADJUST = "调整"
    WEIGHT_CHANGE = "权重调整"  # 组合级子策略权重变更


class Position(BaseModel):
    """
    持仓

    支持两种配置方式：
    1. 按权重配置：提供 weight，系统自动计算 shares 和 market_value
    2. 按份额配置：提供 shares，系统自动计算 weight 和 market_value
    """
    asset_code: str = Field(..., description="资产代码")
    asset_name: str = Field(..., description="资产名称")
    weight: Optional[float] = Field(None, description="权重（按权重配置时必填）")
    shares: Optional[float] = Field(None, description="持有份额（按份额配置时必填）")
    market_value: Optional[float] = Field(None, description="市值（自动计算）")
    price: Optional[float] = Field(None, description="价格（用于计算）")


class SubStrategyAllocation(BaseModel):
    """子策略配置"""
    model_id: str = Field(..., description="子策略模型ID")
    name: str = Field(..., description="子策略名称")
    weight: float = Field(..., description="配置权重（0-1之间，所有子策略权重之和=1）")
    template_code: Optional[str] = Field(None, description="子策略模板代码")
    latest_nav: Optional[float] = Field(None, description="最新子策略NAV")
    latest_return: Optional[float] = Field(None, description="最新子策略收益率")


class RebalanceRecord(BaseModel):
    """调仓记录"""
    id: Optional[str] = Field(None, alias="_id")
    portfolio_id: str = Field(..., description="组合ID")
    rebalance_date: datetime = Field(..., description="调仓日期")
    action: RebalanceAction = Field(..., description="调仓动作")
    positions_before: List[Position] = Field(default_factory=list, description="调仓前持仓")
    positions_after: List[Position] = Field(default_factory=list, description="调仓后持仓")
    # 子策略权重变更记录（仅 PORTFOLIO_MODEL 使用）
    weights_before: Optional[Dict[str, float]] = Field(None, description="调仓前子策略权重")
    weights_after: Optional[Dict[str, float]] = Field(None, description="调仓后子策略权重")
    reason: Optional[str] = Field(None, description="调仓原因")
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


from app.models.strategy_model import BacktestResult as ModelBacktestResult


class Portfolio(BaseModel):
    """投资组合"""
    id: Optional[str] = Field(None, alias="_id")
    name: str = Field(..., description="组合名称")
    source: PortfolioSource = Field(..., description="来源类型")
    description: Optional[str] = Field(None, description="组合描述")

    # 关联模型
    model_id: Optional[str] = Field(None, description="关联的策略模型ID（单策略时使用）")
    portfolio_model_id: Optional[str] = Field(None, description="关联的组合模型ID（多策略时使用）")

    # 子策略配置（仅 PORTFOLIO_MODEL 来源使用）
    sub_strategies: List[SubStrategyAllocation] = Field(
        default_factory=list,
        description="子策略配置列表，仅 PORTFOLIO_MODEL 来源时使用"
    )
    rebalance_frequency: Optional[str] = Field(None, description="再平衡频率（回测参数记录）")

    # 权重构建方法和波动率控制
    weight_method: Optional[str] = Field(None, description="权重构建方法: custom/equal_weight/risk_parity/min_variance/quadrant")
    weight_model_params: Dict[str, Any] = Field(default_factory=dict, description="权重模型参数（如 quadrant 的 signal_code/boost_factor 等）")
    vol_target: Optional[float] = Field(None, description="母层目标年化波动率（如0.08表示8%），None 表示不启用")
    vol_lookback_short: Optional[int] = Field(None, description="短期波动率窗口（交易日）")
    vol_lookback_long: Optional[int] = Field(None, description="长期波动率窗口（交易日）")
    vol_method: Optional[str] = Field(None, description="母层波动率估计方法: rolling=滚动标准差 / ewma=指数加权，None 默认 rolling")
    vol_annualize_factor: Optional[int] = Field(None, description="母层波动率年化因子（默认 252，期货口径可配 260）")
    vol_leverage_min: Optional[float] = Field(None, description="母层定标杠杆下界，None 默认 0.1")
    vol_leverage_max: Optional[float] = Field(None, description="母层定标杠杆上界，None 默认 5.0")

    # 资金与持仓
    initial_capital: float = Field(10_000_000, description="初始资金")
    current_capital: float = Field(10_000_000, description="当前市值")
    positions: List[Position] = Field(default_factory=list, description="当前持仓（底层资产展开）")

    # 绩效
    performance: Optional[ModelBacktestResult] = Field(None, description="业绩指标")
    expected_metrics: Optional[Dict[str, Any]] = Field(None, description="""
        预期绩效指标，组合创建时从关联模型的 latest_backtest_summary 自动提取。
        {annual_return, annual_vol, sharpe, max_drawdown, calmar, total_return}
    """)
    latest_backtest_summary: Optional[Dict[str, Any]] = Field(None, description="""
        最近一次回测的核心绩效快照，回测完成时自动写入。
        {annual_return, annual_vol, sharpe, max_drawdown, calmar,
         total_return, start_date, end_date, backtest_date, record_id}
    """)

    # 分析笔记
    note: Optional[str] = Field(None, description="分析笔记")

    # 状态
    status: PortfolioStatus = Field(PortfolioStatus.ACTIVE, description="组合状态")

    # 时间信息
    inception_date: datetime = Field(default_factory=datetime.now, description="建仓日期（业绩起始日）")
    created_by: Optional[str] = Field(None, description="创建人")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}
        protected_namespaces = ()


# ============================================================
# 模拟交易相关模型
# ============================================================

class SimPositionSnapshot(BaseModel):
    """快照中的单个持仓"""
    asset_code: str = Field(..., description="资产代码")
    asset_name: str = Field(..., description="资产名称")
    weight: float = Field(..., description="权重")
    quantity: float = Field(..., description="持仓数量")
    market_value: float = Field(..., description="持仓市值")
    price: float = Field(..., description="最新价格")


class SimTrade(BaseModel):
    """模拟成交单"""
    id: Optional[str] = Field(None, alias="_id")
    portfolio_id: str = Field(..., description="关联组合 ID")
    trade_date: datetime = Field(..., description="成交日期")
    asset_code: str = Field(..., description="资产代码")
    asset_name: str = Field(..., description="资产名称")
    side: str = Field(..., description="交易方向: buy / sell")
    quantity: float = Field(..., description="成交数量")
    price: float = Field(..., description="成交价格")
    commission: float = Field(0.0, description="手续费")
    slippage_cost: float = Field(0.0, description="滑点成本")
    gross_amount: float = Field(..., description="成交金额 = quantity * price")
    net_amount: float = Field(..., description="净金额（含手续费和滑点）")
    signal_source: str = Field("strategy", description="信号来源: strategy / manual")
    trigger_reason: str = Field(..., description="触发原因")
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class SimDailySnapshot(BaseModel):
    """模拟组合逐日快照"""
    id: Optional[str] = Field(None, alias="_id")
    portfolio_id: str = Field(..., description="关联组合 ID")
    date: datetime = Field(..., description="快照日期")
    nav: float = Field(..., description="当日单位净值")
    total_value: float = Field(..., description="组合总市值")
    cash: float = Field(..., description="现金余额")
    holdings_value: float = Field(..., description="持仓市值")
    daily_return: float = Field(0.0, description="日收益率")
    cumulative_return: float = Field(0.0, description="累计收益率")
    positions: List[SimPositionSnapshot] = Field(default_factory=list, description="当日持仓明细")
    is_rebalance_day: bool = Field(False, description="是否为调仓日")
    backtest_nav: Optional[float] = Field(None, description="对应日期的回测净值")
    tracking_error: Optional[float] = Field(None, description="当日跟踪误差 = sim_nav - bt_nav")
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}
