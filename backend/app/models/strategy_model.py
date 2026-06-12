"""
策略模型数据模型
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
import pandas as pd
import numpy as np
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class RebalanceFrequency(str, Enum):
    """调仓频率"""
    DAILY = "日"
    WEEKLY = "周"
    MONTHLY = "月"
    QUARTERLY = "季"
    YEARLY = "年"
    CUSTOM = "自定义"


class ModelStatus(str, Enum):
    """模型状态"""
    DRAFT = "草稿"
    PUBLISHED = "已发布"
    ARCHIVED = "已归档"


class LiveRebalanceMode(str, Enum):
    """实盘调仓模式"""
    AUTO = "auto"
    MANUAL = "manual"


class AssetPosition(BaseModel):
    """资产持仓"""
    asset_code: str = Field(..., description="资产代码")
    asset_name: Optional[str] = Field(None, description="资产名称")
    weight: float = Field(..., description="权重（0-1）")
    shares: Optional[float] = Field(None, description="持有份额")
    market_value: Optional[float] = Field(None, description="市值")
    price: Optional[float] = Field(None, description="当前价格")


class PositionRecord(BaseModel):
    """持仓记录"""
    date: datetime = Field(..., description="调仓日期")
    portfolio_value: Optional[float] = Field(None, description="组合总市值")
    positions: List[AssetPosition] = Field(default_factory=list, description="各资产持仓")
    cash: Optional[float] = Field(None, description="现金余额")
    
    # 调仓原因
    rebalance_reason: Optional[str] = Field(None, description="调仓原因（周期性调仓/条件触发调仓等）")
    
    # 兼容旧数据格式
    weights: Optional[Dict[str, float]] = Field(None, description="权重字典（旧格式兼容）")
    
    @field_validator('date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持字符串日期格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.strftime('%Y-%m-%d') if v else None
        }


class EquityPoint(BaseModel):
    """净值点"""
    date: datetime = Field(..., description="日期")
    value: float = Field(..., description="组合市值")
    unit_value: Optional[float] = Field(None, description="单位净值（从1开始）")
    cumulative_return: Optional[float] = Field(None, description="累计收益率")
    portfolio_volatility: Optional[float] = Field(None, description="当日组合波动率（监控指标）")
    drawdown: Optional[float] = Field(None, description="当日回撤（相对历史最高点）")
    rebalance_type: Optional[str] = Field(None, description="调仓类型：regular/vol_reset，用于波动率重置标注")
    
    @field_validator('date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持字符串日期格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.strftime('%Y-%m-%d') if v else None
        }


class ReturnPoint(BaseModel):
    """收益率点"""
    date: datetime = Field(..., description="日期")
    daily_return: float = Field(..., description="日收益率")
    cumulative_return: float = Field(..., description="累计收益率")
    
    @field_validator('date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持字符串日期格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.strftime('%Y-%m-%d') if v else None
        }


class BenchmarkReturnPoint(BaseModel):
    """业绩基准收益率点"""
    date: datetime = Field(..., description="日期")
    daily_return: float = Field(..., description="基准日收益率")
    cumulative_return: float = Field(..., description="基准累计收益率")
    
    @field_validator('date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持字符串日期格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.strftime('%Y-%m-%d') if v else None
        }


class WeightChangePoint(BaseModel):
    """权重变化点"""
    date: str = Field(..., description="日期")
    weights: Dict[str, float] = Field(..., description="各资产权重字典")


class TodayNav(BaseModel):
    """当日净值"""
    date: str = Field(..., description="日期")
    unit_value: float = Field(..., description="单位净值")
    total_value: float = Field(..., description="组合总市值")


class TodayPlannedRebalance(BaseModel):
    """当日计划调仓"""
    date: str = Field(..., description="日期")
    is_rebalance_day: bool = Field(..., description="是否为调仓日")
    current_weights: Dict[str, float] = Field(default_factory=dict, description="当前权重（调仓前）")
    target_weights: Dict[str, float] = Field(default_factory=dict, description="目标权重（调仓后）")
    weight_deltas: Dict[str, float] = Field(default_factory=dict, description="权重变化 delta")


class BacktestResult(BaseModel):
    """回测结果"""
    total_return: float = Field(..., description="总收益率")
    annual_return: float = Field(..., description="年化收益率")
    annual_volatility: float = Field(..., description="年化波动率")
    sharpe_ratio: float = Field(..., description="夏普比率")
    max_drawdown: float = Field(..., description="最大回撤")
    calmar_ratio: Optional[float] = Field(None, description="卡玛比率")
    latest_unit_value: float = Field(1.0, description="最新单位净值")
    win_rate: Optional[float] = Field(None, description="胜率")
    equity_curve: List[EquityPoint] = Field(default_factory=list, description="净值曲线")
    return_curve: List[ReturnPoint] = Field(default_factory=list, description="收益率曲线")
    positions: List[PositionRecord] = Field(default_factory=list, description="持仓记录")
    weight_changes: List[WeightChangePoint] = Field(
        default_factory=list,
        description="权重变化记录列表，每项包含date(日期)和weights(各资产权重字典)字段"
    )
    asset_names: Optional[Dict[str, str]] = Field(None, description="资产名称字典")
    today_nav: Optional[TodayNav] = Field(None, description="当日净值")
    today_weights: Optional[Dict[str, float]] = Field(None, description="当日权重")
    today_planned_rebalance: Optional[TodayPlannedRebalance] = Field(None, description="当日计划调仓（若为调仓日）")
    
    def dict(self, **kwargs):
        d = super().dict(**kwargs)
        # 将所有 NaN 和 inf 值替换为 None 或 0
        for key, value in d.items():
            if isinstance(value, float):
                if pd.isna(value) or np.isinf(value):
                    d[key] = None  # 或者设为 0.0
            elif value is not None and str(value) in ['nan', 'inf', '-inf']:
                d[key] = None
        return d


class BacktestRecord(BaseModel):
    """回测记录"""
    id: Optional[str] = Field(None, alias="_id", description="记录ID")
    model_id: str = Field(..., description="模型ID")
    start_date: datetime = Field(..., description="回测开始日期")
    end_date: datetime = Field(..., description="回测结束日期")
    initial_capital: float = Field(..., description="初始资金")
    benchmark_code: Optional[str] = Field(None, description="业绩基准代码")  # 新增字段
    result: BacktestResult = Field(..., description="回测结果")
    remark: Optional[str] = Field(None, description="备注信息")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    
    @field_validator('start_date', 'end_date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持字符串日期格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v
    
    def dict(self, **kwargs):
        d = super().dict(**kwargs)
        # start_date 和 end_date 只返回年月日
        if 'start_date' in d and isinstance(d['start_date'], datetime):
            d['start_date'] = d['start_date'].strftime('%Y-%m-%d')
        if 'end_date' in d and isinstance(d['end_date'], datetime):
            d['end_date'] = d['end_date'].strftime('%Y-%m-%d')
        return d
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        protected_namespaces = ()  # 允许使用 model_ 前缀的字段名


class StrategyModel(BaseModel):
    """策略模型"""
    id: Optional[str] = Field(None, alias="_id")
    name: str = Field(..., description="模型名称")
    template_code: str = Field(..., description="模板代码")
    description: Optional[str] = Field(None, description="模型描述")
    
    # 资产配置
    asset_codes: List[str] = Field(..., description="关联的资产代码列表")
    
    # 参数配置
    parameters: Dict[str, Any] = Field(default_factory=dict, description="模型参数")
    rebalance_frequency: str = Field(..., description="调仓频率")
    
    # 策略建仓日（用于策略监控的起始日期）
    inception_date: Optional[datetime] = Field(None, description="策略建仓日")
    
    # 资产选择相关配置（可选）
    enable_momentum_selection: Optional[bool] = Field(None, description="是否启用动量资产选择")
    selector_type: Optional[str] = Field(None, description="选择器类型（如momentum）")
    asset_selection_count: Optional[int] = Field(None, description="选择资产数量")
    min_history_days: Optional[int] = Field(None, description="最小历史数据要求")
    momentum_windows: Optional[str] = Field(None, description="动量窗口（如'22,65,260'），兼容旧数据：未单独配置时作 MOM/POSI/SMOM 默认")
    mom_windows: Optional[str] = Field(None, description="MOM 因子窗口，逗号分隔四档")
    posi_windows: Optional[str] = Field(None, description="POSI 因子窗口")
    smom_windows: Optional[str] = Field(None, description="SMOM 因子窗口")
    macd_windows: Optional[str] = Field(None, description="MACD 短期均线窗口（四档）")
    macd_long_window: Optional[int] = Field(None, description="MACD 长期均线窗口（默认250）")
    reversal_windows: Optional[str] = Field(None, description="反转偏度双窗口，逗号分隔两个整数")
    tie_break_window: Optional[int] = Field(None, description="并列决胜窗口")
    
    # 状态管理
    status: ModelStatus = Field(ModelStatus.DRAFT, description="模型状态")
    published_at: Optional[datetime] = Field(None, description="发布时间")

    # 实盘发布管理（与 status 独立，不冲突）
    live_publish_enabled: bool = Field(False, description="是否已实盘发布")
    live_published_at: Optional[datetime] = Field(None, description="实盘发布时间")
    live_effective_date: Optional[datetime] = Field(None, description="实盘生效日期（T+1 交易日）")
    live_rebalance_mode: LiveRebalanceMode = Field(
        LiveRebalanceMode.AUTO,
        description="实盘调仓模式：auto 自动调仓 / manual 手动确认"
    )
    live_volatility_threshold: Optional[float] = Field(None, description="实盘波动率阈值")
    live_version: int = Field(0, description="实盘发布版本号")
    live_snapshot: Dict[str, Any] = Field(default_factory=dict, description="实盘配置快照")
    live_snapshot_outdated: bool = Field(False, description="实盘快照是否落后于当前策略配置")
    
    # 创建信息
    created_by: Optional[str] = Field(None, description="创建人")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}
        protected_namespaces = ()  # 允许使用 model_ 前缀的字段名
