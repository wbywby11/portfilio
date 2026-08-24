# -*- coding: utf-8 -*-
"""
组合管理 API Schema

包含组合管理和模拟交易的所有输入/输出模型定义。
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from app.portfolio.models import PortfolioSource, PortfolioStatus, RebalanceAction


# ============================================================
# 组合相关输入模型
# ============================================================

class PositionIn(BaseModel):
    """持仓输入"""
    asset_code: str = Field(..., description="资产代码")
    asset_name: str = Field(..., description="资产名称")
    weight: Optional[float] = Field(None, description="权重（0-1之间）")
    shares: Optional[float] = Field(None, description="持有份额")

    @model_validator(mode='after')
    def validate_position(self):
        if self.weight is None and self.shares is None:
            raise ValueError("必须提供 weight（权重）或 shares（份额）中的至少一个")
        if self.weight is not None and (self.weight < 0 or self.weight > 1):
            raise ValueError(f"权重必须在0-1之间，当前值: {self.weight}")
        if self.shares is not None and self.shares <= 0:
            raise ValueError(f"持有份额必须大于0，当前值: {self.shares}")
        return self


class SubStrategyIn(BaseModel):
    """子策略配置输入"""
    model_id: str = Field(..., description="子策略模型ID")
    weight: float = Field(..., description="配置权重（0-1之间）")


class PortfolioCreate(BaseModel):
    """手工创建组合请求"""
    name: str = Field(..., description="组合名称")
    description: Optional[str] = Field(None, description="组合描述")
    initial_capital: float = Field(10_000_000, description="初始资金")
    inception_date: Optional[datetime] = Field(None, description="建仓日期")
    created_by: Optional[str] = Field(None, description="创建人")
    positions: List[PositionIn] = Field(default_factory=list, description="初始持仓")

    model_config = {"protected_namespaces": ()}

    @field_validator('inception_date', mode='before')
    @classmethod
    def parse_date(cls, v):
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v


class PortfolioFromSingleModelCreate(BaseModel):
    """从单策略模型创建组合请求"""
    model_id: str = Field(..., description="策略模型ID")
    name: str = Field(..., description="组合名称")
    inception_date: Optional[datetime] = Field(None, description="建仓日期，留空则不设置")
    initial_capital: float = Field(10_000_000, description="初始资金")

    model_config = {"protected_namespaces": ()}

    @field_validator('inception_date', mode='before')
    @classmethod
    def parse_date(cls, v):
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v


class PortfolioFromPortfolioModelCreate(BaseModel):
    """从组合模型（多策略）创建组合请求"""
    portfolio_model_id: str = Field(..., description="组合模型ID（is_portfolio=True 的策略模型）")
    name: str = Field(..., description="组合名称")
    inception_date: Optional[datetime] = Field(None, description="建仓日期，留空则不设置")
    initial_capital: float = Field(10_000_000, description="初始资金")

    # 权重构建方法
    weight_method: str = Field(
        "custom",
        description="权重构建方法: custom(用户自定义) / equal_weight / risk_parity / min_variance"
    )
    # 自定义权重时的子策略权重配置
    sub_strategy_weights: Optional[List[SubStrategyIn]] = Field(
        None, description="自定义权重时的子策略权重列表，仅 weight_method=custom 时使用"
    )

    # 波动率控制参数
    vol_target: Optional[float] = Field(
        None, description="母层目标年化波动率（如0.08表示8%），None不启用"
    )
    vol_lookback_short: int = Field(20, description="短期波动率窗口（交易日）")
    vol_lookback_long: int = Field(60, description="长期波动率窗口（交易日）")
    vol_method: Optional[str] = Field(
        None, description="母层波动率估计方法: rolling/ewma，None 默认 rolling"
    )
    vol_annualize_factor: Optional[int] = Field(
        None, description="母层波动率年化因子（默认 252，期货口径可配 260）"
    )
    vol_leverage_min: Optional[float] = Field(
        None, description="母层定标杠杆下界，None 默认 0.1"
    )
    vol_leverage_max: Optional[float] = Field(
        None, description="母层定标杠杆上界，None 默认 5.0"
    )

    # 再平衡频率（可选，留空表示不平衡）
    rebalance_frequency: Optional[str] = Field(None, description="再平衡频率: monthly/quarterly/yearly，None表示不平衡")

    model_config = {"protected_namespaces": ()}

    @field_validator('inception_date', mode='before')
    @classmethod
    def parse_date(cls, v):
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v


class PortfolioFromStrategiesCreate(BaseModel):
    """从多个已发布策略直接组合创建（仅建记录，不执行回测）"""
    strategy_ids: List[str] = Field(..., description="选中的策略模型ID列表")
    name: str = Field(..., description="组合名称")
    initial_capital: float = Field(10_000_000, description="初始资金")

    weight_method: str = Field(
        "custom",
        description="权重构建方法: custom(用户自定义) / equal_weight / risk_parity / min_variance / quadrant(四象限调权)"
    )
    weight_model_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="权重模型参数（quadrant 时使用：rebalance_mode/signal_code/boost_factor/vol_window/quadrant_strategy_map 等）"
    )
    sub_strategy_weights: List[SubStrategyIn] = Field(
        default_factory=list, description="各策略权重配置"
    )

    # 母层波动率定标参数（可选，启用后组合回测/监控按目标波动率缩放）
    vol_target: Optional[float] = Field(
        None, description="母层目标年化波动率（如0.03表示3%），None不启用"
    )
    vol_lookback_short: int = Field(20, description="短期波动率窗口（交易日）")
    vol_lookback_long: int = Field(60, description="长期波动率窗口（交易日）")
    vol_method: Optional[str] = Field(
        None, description="母层波动率估计方法: rolling/ewma，None 默认 rolling"
    )
    vol_annualize_factor: Optional[int] = Field(
        None, description="母层波动率年化因子（默认 252，期货口径可配 260）"
    )
    vol_leverage_min: Optional[float] = Field(
        None, description="母层定标杠杆下界，None 默认 0.1"
    )
    vol_leverage_max: Optional[float] = Field(
        None, description="母层定标杠杆上界，None 默认 5.0"
    )

    model_config = {"protected_namespaces": ()}


class WeightAdjustRequest(BaseModel):
    """手动调整子策略权重请求"""
    sub_strategies: List[SubStrategyIn] = Field(..., description="新的子策略权重配置")
    reason: Optional[str] = Field(None, description="调整原因")

    @model_validator(mode='after')
    def validate_weights(self):
        total = sum(s.weight for s in self.sub_strategies)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"子策略权重总和必须为1，当前总和: {total:.4f}")
        return self


# ============================================================
# 组合相关输出模型
# ============================================================

class SubStrategyOut(BaseModel):
    """子策略摘要输出"""
    model_id: str = Field(..., description="子策略模型ID")
    name: str = Field(..., description="子策略名称")
    weight: float = Field(..., description="配置权重")
    template_code: Optional[str] = Field(None, description="策略模板代码")
    latest_nav: Optional[float] = Field(None, description="最新NAV")
    latest_return: Optional[float] = Field(None, description="最新收益率")


class PortfolioOut(BaseModel):
    """组合列表输出"""
    id: str = Field(..., description="组合ID")
    name: str = Field(..., description="组合名称")
    source: PortfolioSource = Field(..., description="来源类型")
    description: Optional[str] = Field(None, description="组合描述")
    status: PortfolioStatus = Field(..., description="状态")

    # 关联
    model_id: Optional[str] = Field(None, description="关联策略模型ID")
    portfolio_model_id: Optional[str] = Field(None, description="关联组合模型ID")
    sub_strategies: List[SubStrategyOut] = Field(default_factory=list, description="子策略配置")
    rebalance_frequency: Optional[str] = Field(None, description="再平衡频率")

    # 权重与波动率控制
    weight_method: Optional[str] = Field(None, description="权重构建方法")
    weight_model_params: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="权重模型参数（编辑回显）：quadrant 四象限参数 + product_layer 产品层配置"
    )
    vol_target: Optional[float] = Field(None, description="目标波动率")
    vol_lookback_short: Optional[int] = Field(None, description="短期波动率窗口")
    vol_lookback_long: Optional[int] = Field(None, description="长期波动率窗口")
    vol_method: Optional[str] = Field(None, description="母层波动率估计方法: rolling/ewma")
    vol_annualize_factor: Optional[int] = Field(None, description="母层波动率年化因子")
    vol_leverage_min: Optional[float] = Field(None, description="母层定标杠杆下界")
    vol_leverage_max: Optional[float] = Field(None, description="母层定标杠杆上界")

    # 资金
    initial_capital: float = Field(..., description="初始资金")
    current_capital: float = Field(..., description="当前市值")

    # 扁平化绩效指标（列表页快速展示）
    total_return: Optional[float] = Field(None, description="累计收益率")
    annual_return: Optional[float] = Field(None, description="年化收益率")
    annual_volatility: Optional[float] = Field(None, description="年化波动率")
    max_drawdown: Optional[float] = Field(None, description="最大回撤")
    sharpe_ratio: Optional[float] = Field(None, description="夏普比率")
    latest_unit_value: Optional[float] = Field(None, description="最新单位净值")

    # 最近回测快照（列表页展示回测区间+指标）
    latest_backtest_summary: Optional[Dict[str, Any]] = Field(
        None,
        description="最近一次回测绩效快照 {annual_return, annual_vol, sharpe, max_drawdown, total_return, start_date, end_date}"
    )

    # 实盘状态（来自关联策略模型）
    live_publish_enabled: bool = Field(False, description="关联模型是否已实盘发布")

    # 时间
    inception_date: datetime = Field(..., description="建仓日期")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = {"protected_namespaces": ()}


class SubStrategyPerformanceOut(BaseModel):
    """子策略绩效输出（详情页使用）"""
    model_id: str = Field(..., description="子策略模型ID")
    name: str = Field(..., description="子策略名称")
    weight: float = Field(..., description="配置权重")
    annual_return: Optional[float] = Field(None, description="年化收益率")
    annual_vol: Optional[float] = Field(None, description="年化波动率")
    sharpe: Optional[float] = Field(None, description="夏普比率")
    max_drawdown: Optional[float] = Field(None, description="最大回撤")
    contribution: Optional[float] = Field(None, description="对组合收益的贡献")
    contribution_pct: Optional[float] = Field(None, description="贡献占比")
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list, description="子策略净值曲线")


class CorrelationAnalysisOut(BaseModel):
    """相关性分析输出"""
    avg_correlation: float = Field(0.0, description="平均相关系数")
    diversification_ratio: float = Field(1.0, description="分散化比率")
    correlation_drag: float = Field(0.0, description="相关性拖累")
    correlation_matrix: Optional[Dict[str, Dict[str, float]]] = Field(None, description="相关系数矩阵")


from app.schemas.strategy_model import BacktestResultOut, AssetPositionOut


class PortfolioDetailOut(BaseModel):
    """组合详情输出"""
    id: str = Field(..., description="组合ID")
    name: str = Field(..., description="组合名称")
    source: PortfolioSource = Field(..., description="来源类型")
    description: Optional[str] = Field(None, description="组合描述")
    status: PortfolioStatus = Field(..., description="状态")

    # 关联
    model_id: Optional[str] = Field(None, description="关联策略模型ID")
    portfolio_model_id: Optional[str] = Field(None, description="关联组合模型ID")
    sub_strategies: List[SubStrategyOut] = Field(default_factory=list, description="子策略配置")

    # 资金
    inception_date: datetime = Field(..., description="建仓日期")
    initial_capital: float = Field(..., description="初始资金")
    current_capital: float = Field(..., description="当前市值")

    # 核心绩效（组合级）
    metrics: Optional[BacktestResultOut] = Field(None, description="组合业绩分析")

    # 子策略绩效分解（仅 PORTFOLIO_MODEL）
    sub_strategy_performance: List[SubStrategyPerformanceOut] = Field(
        default_factory=list, description="子策略绩效分解"
    )

    # 相关性分析（仅 PORTFOLIO_MODEL）
    correlation_analysis: Optional[CorrelationAnalysisOut] = Field(None, description="相关性分析")

    # 当前持仓
    current_holdings: List[AssetPositionOut] = Field(default_factory=list, description="当前资产权重占比")

    # 分析笔记
    note: Optional[str] = Field(None, description="分析笔记")

    model_config = {"protected_namespaces": ()}


class RebalanceRecordOut(BaseModel):
    """调仓记录输出"""
    id: Optional[str] = Field(None, description="记录ID")
    rebalance_date: datetime = Field(..., description="调仓日期")
    action: RebalanceAction = Field(..., description="调仓动作")
    reason: Optional[str] = Field(None, description="调仓原因")
    positions_before: List[PositionIn] = Field(default_factory=list, description="调仓前持仓")
    positions_after: List[PositionIn] = Field(default_factory=list, description="调仓后持仓")
    weights_before: Optional[Dict[str, float]] = Field(None, description="调仓前子策略权重")
    weights_after: Optional[Dict[str, float]] = Field(None, description="调仓后子策略权重")


# ============================================================
# 模拟交易相关 Schema
# ============================================================

class SimAdvanceRequest(BaseModel):
    """手动推进请求"""
    target_date: Optional[str] = Field(
        None, description="推进目标日期 (YYYY-MM-DD)，不提供则推进到今天"
    )


class BatchAdvanceRequest(BaseModel):
    """批量推进请求"""
    target_date: Optional[str] = Field(
        None, description="推进目标日期 (YYYY-MM-DD)，不提供则推进到今天"
    )
    portfolio_ids: Optional[List[str]] = Field(
        None, description="指定组合 ID 列表，不提供则推进所有模型驱动组合"
    )


class SimPositionSnapshotOut(BaseModel):
    """持仓快照输出"""
    asset_code: str
    asset_name: str
    weight: float
    quantity: float
    market_value: float
    price: float


class SimTradeOut(BaseModel):
    """成交记录输出"""
    id: str
    portfolio_id: str
    trade_date: str
    asset_code: str
    asset_name: str
    side: str
    quantity: float
    price: float
    commission: float
    slippage_cost: float
    gross_amount: float
    net_amount: float
    signal_source: str
    trigger_reason: str
    created_at: str


class SimDailySnapshotOut(BaseModel):
    """逐日快照输出"""
    id: str
    portfolio_id: str
    date: str
    nav: float
    total_value: float
    cash: float
    holdings_value: float
    daily_return: float
    cumulative_return: float
    positions: List[SimPositionSnapshotOut] = Field(default_factory=list)
    is_rebalance_day: bool = False
    backtest_nav: Optional[float] = None
    tracking_error: Optional[float] = None


class TrackingErrorStats(BaseModel):
    """跟踪误差统计"""
    annual_tracking_error: float = Field(0.0, description="年化跟踪误差")
    information_ratio: float = Field(0.0, description="信息比率")
    max_deviation: float = Field(0.0, description="最大偏离（绝对值）")
    mean_daily_error: float = Field(0.0, description="日均跟踪误差")
    total_days: int = Field(0, description="对比天数")
    days_with_data: int = Field(0, description="有回测净值对比的天数")


class NavComparisonPoint(BaseModel):
    """NAV 对比数据点"""
    date: str
    sim_nav: float
    backtest_nav: Optional[float] = None
    tracking_error: Optional[float] = None


class TrackingReport(BaseModel):
    """跟踪误差报告"""
    portfolio_id: str
    portfolio_name: str
    stats: TrackingErrorStats
    nav_comparison: List[NavComparisonPoint] = Field(default_factory=list)


class AttributionEffect(BaseModel):
    """单个资产的归因效应"""
    asset_code: str
    asset_name: str
    allocation_effect: float = Field(0.0, description="配置效应")
    selection_effect: float = Field(0.0, description="选择效应")
    interaction_effect: float = Field(0.0, description="交互效应")
    total_effect: float = Field(0.0, description="总效应")


class AttributionReport(BaseModel):
    """Brinson 绩效归因报告"""
    portfolio_id: str
    portfolio_name: str
    total_allocation: float = Field(0.0, description="总配置效应")
    total_selection: float = Field(0.0, description="总选择效应")
    total_interaction: float = Field(0.0, description="总交互效应")
    total_active_return: float = Field(0.0, description="总主动收益")
    effects: List[AttributionEffect] = Field(default_factory=list)
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class AdvanceResult(BaseModel):
    """推进结果"""
    portfolio_id: str
    portfolio_name: str
    days_advanced: int = Field(0, description="推进天数")
    trades_generated: int = Field(0, description="生成成交单数")
    target_date: str
    final_nav: Optional[float] = None
    final_total_value: Optional[float] = None
    message: str = ""
