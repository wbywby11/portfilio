"""回测 API 请求/响应模型（自 app/api/backtests.py 平移，P8 治理）.

行为契约：模型字段、校验器与原实现逐字一致；app/api/backtests.py
通过再导出保持旧导入面兼容（main.py / monitor / regression chains）。
"""
from typing import List, Dict, Any, Optional
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, Field, field_validator


class ManualWeightAdjustmentItem(BaseModel):
    """单次交互式权重调整（权重可选，不设则到该日由用户选择）"""
    date: str = Field(..., description="调整日期，格式 YYYYMMDD")
    weights: Optional[Dict[str, float]] = Field(None, description="资产代码到权重的映射，可留空")
    auto_normalize: bool = Field(True, description="是否自动归一化权重")


class BacktestRequest(BaseModel):
    """回测请求"""
    name: str = Field(..., description="回测名称")
    strategy_type: str = Field(..., description="策略类型")
    strategy_params: Dict[str, Any] = Field(default_factory=dict, description="策略参数")
    thscodes: List[str] = Field(..., description="资产代码列表")
    start_date: str = Field(..., description="回测开始日期（格式：YYYY-MM-DD）")
    end_date: str = Field(..., description="回测结束日期（格式：YYYY-MM-DD）")
    initial_cash: float = Field(10_000_000.0, description="初始资金")
    rebalance_freq: str = Field("monthly", description="调仓频率（daily/weekly/monthly/month_end/quarterly/yearly，vol_scaled_budget混合动量时自动用month_end）")
    commission_rate: float = Field(0.0, description="手续费率（默认 0：不计成本，可按需设置）")
    slippage: float = Field(0.0, description="滑点率（默认 0：不计成本，可按需设置）")
    lookback_days: int = Field(500, description="历史数据预加载天数")
    manual_weight_adjustments: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="交互式权重调整（仅 manual_allocation 策略）：[{date, weights, auto_normalize}, ...]"
    )
    execution_delay: Optional[int] = Field(
        None,
        description="执行延迟（交易日）：None=使用策略默认值，0=T+0, 1=T+1, 2=T+2, ..."
    )

    @field_validator('start_date', 'end_date', mode='before')
    @classmethod
    def validate_date(cls, v: Any) -> str:
        """验证并规范化日期格式为 YYYYMMDD"""
        if not v:
            return v
        try:
            # 使用 pandas 灵活解析日期
            dt = pd.to_datetime(v)
            return dt.strftime('%Y%m%d')
        except Exception:
            return v  # 如果解析失败，保持原样，让后续逻辑处理


class SnapshotOut(BaseModel):
    """组合快照输出"""
    time: datetime = Field(..., description="时间")
    total_value: float = Field(..., description="组合总市值")
    cash: float = Field(..., description="现金")
    holdings_value: float = Field(..., description="持仓市值")
    weights: Dict[str, float] = Field(..., description="持仓权重")
    is_rebalance_day: bool = Field(False, description="是否为调仓日")
    rebalance_type: Optional[str] = Field(None, description="调仓类型：regular/vol_reset")
    rebalance_reason: Optional[str] = Field(None, description="调仓原因（周期性调仓/条件触发调仓等）")
    portfolio_volatility: Optional[float] = Field(None, description="当日组合波动率")
    drawdown: Optional[float] = Field(None, description="当日回撤")
    monitoring_metrics: Dict[str, Any] = Field(default_factory=dict, description="所有监控指标")


class TradeOut(BaseModel):
    """交易记录输出"""
    time: datetime = Field(..., description="交易时间")
    thscode: str = Field(..., description="资产代码")
    side: str = Field(..., description="交易方向（buy/sell）")
    quantity: float = Field(..., description="交易数量")
    price: float = Field(..., description="交易价格")
    commission: float = Field(..., description="手续费")
    slippage_cost: float = Field(..., description="滑点成本")
    rebalance_label: Optional[str] = Field(None, description="调仓类型：初始化仓位/主观调仓/周期性调仓/波动率重置")


class BacktestResultOut(BaseModel):
    """回测结果输出"""
    snapshots: List[SnapshotOut] = Field(..., description="组合快照列表")
    trades: List[TradeOut] = Field(..., description="交易记录列表")
    total_return: float = Field(..., description="总收益率")
    annual_return: float = Field(..., description="年化收益率")
    volatility: float = Field(..., description="波动率")
    sharpe_ratio: float = Field(..., description="夏普比率")
    max_drawdown: float = Field(..., description="最大回撤")
    calmar_ratio: float = Field(..., description="卡玛比率")
    # 365 口径（自然日/年）：与 260 口径并列返回，累计收益/回撤/胜率只给一份
    annual_return_365: Optional[float] = Field(None, description="年化收益率（365 自然日口径）")
    volatility_365: Optional[float] = Field(None, description="年化波动率（365 自然日口径）")
    sharpe_ratio_365: Optional[float] = Field(None, description="夏普比率（365 自然日口径）")
    calmar_ratio_365: Optional[float] = Field(None, description="卡玛比率（365 自然日口径）")
    win_rate: Optional[float] = Field(None, description="胜率（卖出交易中盈利的比例）")
    n_trades: int = Field(0, description="成交笔数")
    total_commission: float = Field(0.0, description="累计手续费")
    total_slippage: float = Field(0.0, description="累计滑点成本")
    turnover: float = Field(0.0, description="累计换手额 / 期初净值（单边）")
    warnings: List[str] = Field(default_factory=list, description="数据质量告警（缺失值、异常跳变、样本不足等，指标未做任何钳制）")
    asset_names: Optional[Dict[str, str]] = Field(None, description="资产名称字典")
    selected_asset_count: Optional[int] = Field(None, description="动量选择器「选择资产数量」，与持仓权重资产类别数一致")


class ComputeMetricsFromSnapshotsRequest(BaseModel):
    """基于快照切片计算绩效指标（用于多策略步进对比，保证与净值曲线数据源一致）"""
    snapshots: List[Dict[str, Any]] = Field(..., description="组合快照列表，含 time/total_value/is_rebalance_day 等")
    cutoff_date: str = Field(..., description="截止日期 YYYYMMDD，只使用 time<=cutoff_date 的快照")


class BacktestByModelRequest(BaseModel):
    """根据策略模型回测的请求参数"""
    start_date: str = Field(..., description="回测开始日期（格式：YYYYMMDD）")
    end_date: str = Field(..., description="回测结束日期（格式：YYYYMMDD）")
    initial_cash: float = Field(10_000_000.0, description="初始资金")
    initial_nav: float = Field(1000.0, description="回测起始净值（NAV），默认1000")
    rebalance_freq: Optional[str] = Field(None, description="调仓频率（覆盖模型配置，daily/weekly/monthly/quarterly/yearly）")
    commission_rate: Optional[float] = Field(None, description="手续费率（覆盖模型配置）")
    slippage: Optional[float] = Field(None, description="滑点率（覆盖模型配置）")
    lookback_days: int = Field(500, description="历史数据预加载天数")
    
    # 手动选择资产：前端指定具体要用于回测的资产列表（优先级最高，跳过动量选择器）
    selected_asset_codes: Optional[List[str]] = Field(None, description="手动选择的资产代码列表（优先使用，跳过动量选择）")
    
    # 动量选择器参数（可选，如果策略启用了选择器，这些参数会覆盖数据库中的配置）
    enable_momentum_selection: Optional[bool] = Field(None, description="是否启用动量资产选择（覆盖模型配置）")
    selector_type: Optional[str] = Field(None, description="选择器类型（momentum/momentum_reversal，覆盖模型配置）")
    asset_selection_count: Optional[int] = Field(None, description="选择资产数量（覆盖模型配置）")
    min_history_days: Optional[int] = Field(None, description="最小历史数据要求（覆盖模型配置）")
    momentum_windows: Optional[str] = Field(None, description="动量窗口(MOM/POSI/SMOM)，格式：20,60,120,250（覆盖模型配置）")
    sharp_windows: Optional[str] = Field(None, description="夏普率窗口，格式：22,65,260（覆盖模型配置）")
    macd_windows: Optional[str] = Field(None, description="MACD窗口，格式：40,80,120,160（覆盖模型配置）")
    reversal_windows: Optional[str] = Field(None, description="反转窗口，格式：10,22（覆盖模型配置）")
    tie_break_window: Optional[int] = Field(None, description="并列决胜窗口（覆盖模型配置）")
    n_momentum: Optional[int] = Field(None, description="动量选择数量（覆盖模型配置）")
    n_reversal: Optional[int] = Field(None, description="反转选择数量（覆盖模型配置）")
    
    # 波动率阈值重置（仅对 vol_scaled_budget 生效，覆盖模型配置）
    enable_vol_reset: Optional[bool] = Field(None, description="是否启用波动率阈值重置（覆盖模型配置）")
    vol_reset_threshold: Optional[float] = Field(None, description="波动率重置阈值，如 0.06 表示 6%（覆盖模型配置）")

    # 交互式权重调整（仅 manual_allocation 策略）：指定日期使用用户预设的权重
    manual_weight_adjustments: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="[{date: YYYYMMDD, weights: {code: w}, auto_normalize: bool}, ...]"
    )
    # 默认权重（仅 manual_allocation 策略）：本次回测覆盖模型的 manual_weights，避免模型未配置时报错
    manual_weights: Optional[Dict[str, float]] = Field(
        None,
        description="资产代码到权重的映射，覆盖策略模型中的默认权重（仅主观配置策略）"
    )

    # 回测结果备注（保存到策略回测记录，可在回测记录列表中展示与编辑）
    remark: Optional[str] = Field(None, description="备注信息")

    # 杠杆倍数限制（本次回测覆盖模型配置，如 4 表示 400%，初始化/预设调仓日权重和均不得超过此值）
    max_leverage: Optional[float] = Field(None, description="杠杆倍数限制，覆盖策略模型中的最大杠杆（如 4 表示 400%）")

    @field_validator('start_date', 'end_date', mode='before')
    @classmethod
    def validate_date(cls, v: Any) -> str:
        """验证并规范化日期格式为 YYYYMMDD"""
        if not v:
            return v
        try:
            dt = pd.to_datetime(v)
            return dt.strftime('%Y%m%d')
        except Exception:
            return v


class SensitivityRequest(BaseModel):
    """参数敏感度分析请求"""
    model_id: str = Field(..., description="策略模型 ID")
    param_name: str = Field(..., description="要扫描的参数名")
    param_values: List[Any] = Field(..., description="参数值列表")
    start_date: str = Field(..., description="回测开始日期 YYYYMMDD")
    end_date: str = Field(..., description="回测结束日期 YYYYMMDD")
    initial_cash: float = Field(1000000, description="初始资金")


class ScenarioRequest(BaseModel):
    """情景推演请求"""
    model_id: str = Field(..., description="策略模型 ID")
    scenario: Dict[str, float] = Field(..., description="情景冲击 {asset_code: shock_pct}")
    start_date: str = Field(..., description="回测开始日期 YYYYMMDD")
    end_date: str = Field(..., description="回测结束日期 YYYYMMDD")
    initial_cash: float = Field(1000000, description="初始资金")


class RobustnessRequest(BaseModel):
    """鲁棒性检验请求"""
    model_id: str = Field(..., description="策略模型 ID")
    n_windows: int = Field(5, ge=2, le=20, description="子区间数量")
    start_date: Optional[str] = Field(None, description="回测开始日期")
    end_date: Optional[str] = Field(None, description="回测结束日期")
    initial_cash: float = Field(1000000, description="初始资金")


class PortfolioReportRequest(BaseModel):
    """组合评估报告请求"""
    model_id: str = Field(..., description="策略模型 ID")
    benchmark_nav: Optional[List[float]] = Field(None, description="基准净值序列（可选）")
    benchmark_dates: Optional[List[str]] = Field(None, description="基准净值对应日期序列")


class PortfolioBacktestRequest(BaseModel):
    """投资组合回测请求"""
    start_date: str = Field(..., description="回测开始日期（格式：YYYYMMDD）")
    end_date: str = Field(..., description="回测结束日期（格式：YYYYMMDD）")
    initial_nav: float = Field(1000.0, description="回测起始净值（NAV），默认1000")
    rebalance_freq: Optional[str] = Field("monthly", description="再平衡频率：monthly/quarterly/yearly")
    mother_vol_target: Optional[float] = Field(None, description="母层目标波动率（可选，None则不启用母层波动率控制）")
    mother_leverage_min: Optional[float] = Field(None, description="母层定标杠杆下界，None 默认 0.1")
    mother_leverage_max: Optional[float] = Field(None, description="母层定标杠杆上界，None 默认 5.0")
    commission_rate: Optional[float] = Field(None, description="子策略手续费率，传 0 即零手续费；None 用策略默认")
    slippage: Optional[float] = Field(None, description="子策略滑点率，传 0 即零滑点；None 用策略默认")


class SubStrategyResultOut(BaseModel):
    """子策略回测结果"""
    model_id: str = Field(..., description="子策略模型ID")
    name: str = Field(..., description="子策略名称")
    weight: float = Field(..., description="配置权重")
    annual_return: float = Field(..., description="年化收益率")
    annual_volatility: float = Field(..., description="年化波动率")
    sharpe_ratio: float = Field(..., description="夏普比率")
    max_drawdown: float = Field(..., description="最大回撤")
    # 365 口径（自然日/年）
    annual_return_365: Optional[float] = Field(None, description="年化收益率（365 自然日口径）")
    annual_volatility_365: Optional[float] = Field(None, description="年化波动率（365 自然日口径）")
    sharpe_ratio_365: Optional[float] = Field(None, description="夏普比率（365 自然日口径）")
    n_trades: int = Field(0, description="成交笔数")
    total_commission: float = Field(0.0, description="累计手续费")
    total_slippage: float = Field(0.0, description="累计滑点成本")
    turnover: float = Field(0.0, description="累计换手额 / 期初净值（单边）")
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list, description="NAV曲线 [{date, value}]")


class PortfolioBacktestResultOut(BaseModel):
    """投资组合回测结果输出"""
    total_return: float = Field(..., description="总收益率")
    annual_return: float = Field(..., description="年化收益率")
    annual_volatility: float = Field(..., description="年化波动率")
    sharpe_ratio: float = Field(..., description="夏普比率")
    max_drawdown: float = Field(..., description="最大回撤")
    calmar_ratio: float = Field(..., description="卡玛比率")
    # 365 口径（自然日/年）：与 260 口径并列返回，累计收益/回撤/胜率只给一份
    annual_return_365: Optional[float] = Field(None, description="年化收益率（365 自然日口径）")
    annual_volatility_365: Optional[float] = Field(None, description="年化波动率（365 自然日口径）")
    sharpe_ratio_365: Optional[float] = Field(None, description="夏普比率（365 自然日口径）")
    calmar_ratio_365: Optional[float] = Field(None, description="卡玛比率（365 自然日口径）")
    win_rate: Optional[float] = Field(None, description="胜率")
    n_trades: int = Field(0, description="组合层成交笔数（合成资产再平衡）")
    total_commission: float = Field(0.0, description="组合层累计手续费")
    total_slippage: float = Field(0.0, description="组合层累计滑点成本")
    turnover: float = Field(0.0, description="组合层累计换手额 / 期初净值（单边）")
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list, description="NAV曲线 [{date, value, drawdown, is_rebalance_day, weights（穿透后资产级）}]")
    sub_strategies: List[SubStrategyResultOut] = Field(default_factory=list, description="子策略回测结果列表")
    # 增强：穿透后资产级权重历史与相关性分析
    weight_history: List[Dict[str, Any]] = Field(default_factory=list, description="穿透后资产级权重历史 [{date, ...asset_weights}]")
    correlation_analysis: Optional[Dict[str, Any]] = Field(None, description="子策略相关性分析")
    attribution: Optional[Dict[str, Any]] = Field(None, description="子策略归因分析")
    warnings: List[str] = Field(default_factory=list, description="数据质量与归因口径告警（指标未做任何钳制）")
    backtest_record_id: Optional[str] = Field(None, description="保存的回测记录ID")
    trades: List[Dict[str, Any]] = Field(default_factory=list, description="模拟交易明细（含 strategy_name 字段标识来源策略）")
    product_layer: Optional[Dict[str, Any]] = Field(None, description="产品层配置与权重摘要（启用时返回）")


class PortfolioByIdBacktestRequest(BaseModel):
    """根据组合ID执行回测的请求"""
    start_date: str = Field(..., description="回测开始日期（格式：YYYYMMDD）")
    end_date: str = Field(..., description="回测结束日期（格式：YYYYMMDD）")
    initial_nav: float = Field(1000.0, description="回测起始净值（NAV），默认1000")
    rebalance_freq: Optional[str] = Field("monthly", description="再平衡频率：monthly/quarterly/yearly")
    mother_vol_target: Optional[float] = Field(None, description="母层目标波动率（可选，None则回退到组合文档配置）")
    mother_leverage_min: Optional[float] = Field(None, description="母层定标杠杆下界，None 回退到组合文档配置（默认 0.1）")
    mother_leverage_max: Optional[float] = Field(None, description="母层定标杠杆上界，None 回退到组合文档配置（默认 5.0）")
    commission_rate: Optional[float] = Field(None, description="子策略手续费率，传 0 即零手续费；None 用策略默认")
    slippage: Optional[float] = Field(None, description="子策略滑点率，传 0 即零滑点；None 用策略默认")
