"""策略模型API模型"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, field_serializer
from app.models.strategy_model import ModelStatus, WeightChangePoint, LiveRebalanceMode


class AssetWeight(BaseModel):
    """单个资产权重模型"""
    asset_code: str = Field(..., description="资产代码")
    asset_name: Optional[str] = Field(None, description="资产名称")
    weight: float = Field(..., ge=0, le=1, description="权重值(0-1之间)，表示该资产在组合中的占比")


class AssetPositionOut(BaseModel):
    """资产持仓输出"""
    asset_code: str = Field(..., description="资产代码")
    asset_name: Optional[str] = Field(None, description="资产名称")
    weight: float = Field(..., description="权重（0-1）")
    shares: Optional[float] = Field(None, description="持有份额")
    market_value: Optional[float] = Field(None, description="市值")
    price: Optional[float] = Field(None, description="当前价格")


class PositionRecordOut(BaseModel):
    """持仓记录输出"""
    date: datetime = Field(..., description="调仓日期")
    portfolio_value: Optional[float] = Field(None, description="组合总市值")
    positions: List[AssetPositionOut] = Field(default_factory=list, description="各资产持仓")
    cash: Optional[float] = Field(None, description="现金余额")
    rebalance_reason: Optional[str] = Field(None, description="调仓原因（周期性调仓/条件触发调仓等）")
    weights: Optional[Dict[str, float]] = Field(None, description="权重字典（旧格式兼容）")
    
    @field_validator('date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持字符串日期格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v
    
    @field_serializer('date')
    def serialize_date(self, value: datetime) -> str:
        """序列化日期为YYYY-MM-DD格式"""
        return value.strftime('%Y-%m-%d') if value else None


class EquityPointOut(BaseModel):
    """净值点输出"""
    date: datetime = Field(..., description="日期")
    value: float = Field(..., description="组合市值")
    unit_value: Optional[float] = Field(None, description="单位净值（从1开始）")
    cumulative_return: Optional[float] = Field(None, description="累计收益率")
    portfolio_volatility: Optional[float] = Field(None, description="当日组合波动率（监控指标）")
    drawdown: Optional[float] = Field(None, description="当日回撤（相对历史最高点）")
    
    @field_validator('date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持字符串日期格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v
    
    @field_serializer('date')
    def serialize_date(self, value: datetime) -> str:
        """序列化日期为YYYY-MM-DD格式"""
        return value.strftime('%Y-%m-%d') if value else None


class ReturnPointOut(BaseModel):
    """收益率点输出"""
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
    
    @field_serializer('date')
    def serialize_date(self, value: datetime) -> str:
        """序列化日期为YYYY-MM-DD格式"""
        return value.strftime('%Y-%m-%d') if value else None


class BenchmarkReturnPointOut(BaseModel):
    """业绩基准收益率点输出"""
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
    
    @field_serializer('date')
    def serialize_date(self, value: datetime) -> str:
        """序列化日期为YYYY-MM-DD格式"""
        return value.strftime('%Y-%m-%d') if value else None


class StrategyModelCreate(BaseModel):
    """创建策略模型请求"""
    name: str = Field(..., description="模型名称")
    template_code: str = Field(..., description="模板代码")
    description: Optional[str] = Field(None, description="模型描述")
    asset_codes: List[str] = Field(..., description="关联的资产代码列表")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="模型参数")
    rebalance_frequency: str = Field(..., description="调仓频率(日/周/月/季/年 或 自定义格式如 '1天', '2周', '3月' 等)")
    created_by: Optional[str] = Field(None, description="创建人")
    inception_date: Optional[datetime] = Field(None, description="策略建仓日（用于策略监控起始日期）")
    
    # 资产选择相关配置（可选）
    enable_momentum_selection: Optional[bool] = Field(None, description="是否启用动量资产选择")
    selector_type: Optional[str] = Field(None, description="选择器类型（如momentum）")
    asset_selection_count: Optional[int] = Field(None, description="选择资产数量")
    min_history_days: Optional[int] = Field(None, description="最小历史数据要求")
    momentum_windows: Optional[str] = Field(None, description="动量窗口（兼容旧数据，作 MOM/POSI/SMOM 共用默认）")
    mom_windows: Optional[str] = Field(None, description="MOM 因子四档窗口")
    posi_windows: Optional[str] = Field(None, description="POSI 因子四档窗口")
    smom_windows: Optional[str] = Field(None, description="SMOM 因子四档窗口")
    macd_windows: Optional[str] = Field(None, description="MACD 短期四档窗口")
    macd_long_window: Optional[int] = Field(None, description="MACD 长期窗口")
    reversal_windows: Optional[str] = Field(None, description="反转双窗口")
    tie_break_window: Optional[int] = Field(None, description="并列决胜窗口")

    @field_validator('parameters', mode='before')
    @classmethod
    def parse_parameters(cls, v):
        """处理参数中的JSON字符串"""
        if not isinstance(v, dict):
            return v
        
        import json
        processed = {}
        for key, value in v.items():
            if isinstance(value, str) and (value.strip().startswith('{') or value.strip().startswith('[')):
                try:
                    processed[key] = json.loads(value)
                except Exception:
                    processed[key] = value
            else:
                processed[key] = value
        return processed


class StrategyModelUpdate(BaseModel):
    """更新策略模型请求（所有字段均为可选）"""
    name: Optional[str] = Field(None, description="模型名称")
    description: Optional[str] = Field(None, description="模型描述")
    asset_codes: Optional[List[str]] = Field(None, description="关联的资产代码列表")
    parameters: Optional[Dict[str, Any]] = Field(None, description="模型参数")
    rebalance_frequency: Optional[str] = Field(None, description="调仓频率(日/周/月/季/年 或 自定义格式如 '1天', '2周', '3月' 等)")
    inception_date: Optional[datetime] = Field(None, description="策略建仓日（用于策略监控起始日期）")
    
    # 资产选择相关配置（可选）
    enable_momentum_selection: Optional[bool] = Field(None, description="是否启用动量资产选择")
    selector_type: Optional[str] = Field(None, description="选择器类型（如momentum）")
    asset_selection_count: Optional[int] = Field(None, description="选择资产数量")
    min_history_days: Optional[int] = Field(None, description="最小历史数据要求")
    momentum_windows: Optional[str] = Field(None, description="动量窗口（兼容旧数据）")
    mom_windows: Optional[str] = Field(None, description="MOM 因子四档窗口")
    posi_windows: Optional[str] = Field(None, description="POSI 因子四档窗口")
    smom_windows: Optional[str] = Field(None, description="SMOM 因子四档窗口")
    macd_windows: Optional[str] = Field(None, description="MACD 短期四档窗口")
    macd_long_window: Optional[int] = Field(None, description="MACD 长期窗口")
    reversal_windows: Optional[str] = Field(None, description="反转双窗口")
    tie_break_window: Optional[int] = Field(None, description="并列决胜窗口")

    @field_validator('parameters', mode='before')
    @classmethod
    def parse_parameters(cls, v):
        """处理参数中的JSON字符串"""
        if v is None:
            return v
        if not isinstance(v, dict):
            return v
        
        import json
        processed = {}
        for key, value in v.items():
            if isinstance(value, str) and (value.strip().startswith('{') or value.strip().startswith('[')):
                try:
                    processed[key] = json.loads(value)
                except Exception:
                    processed[key] = value
            else:
                processed[key] = value
        return processed


class StrategyModelOut(StrategyModelCreate):
    """策略模型输出模型"""
    id: str = Field(..., description="模型ID")
    status: ModelStatus = Field(..., description="模型状态")
    published_at: Optional[datetime] = Field(None, description="发布时间")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    
    # 附加的名称信息
    asset_names: Optional[Dict[str, str]] = Field(None, description="资产名称字典，键为资产代码，值为资产名称")
    template_name: Optional[str] = Field(None, description="模板名称")
    parameter_labels: Optional[Dict[str, str]] = Field(None, description="参数显示名称字典，键为参数名称，值为中文标签")
    
    # 资产选择相关字段继承自 StrategyModelCreate（含动量/反转各窗口）

    # 实盘发布（须出现在 JSON 中；不含 live_snapshot 以免列表接口体积过大）
    live_publish_enabled: bool = Field(False, description="是否已实盘发布")
    live_published_at: Optional[datetime] = Field(None, description="实盘发布时间")
    live_effective_date: Optional[datetime] = Field(None, description="实盘生效日期（T+1 交易日）")
    live_rebalance_mode: Optional[LiveRebalanceMode] = Field(None, description="实盘调仓模式")
    live_volatility_threshold: Optional[float] = Field(None, description="实盘波动率阈值")
    live_version: int = Field(0, description="实盘发布版本号")
    live_snapshot_outdated: bool = Field(False, description="实盘快照是否落后于当前策略配置")
    live_effective_summary: Optional[str] = Field(
        None,
        description="实盘生效参数摘要（目标波动、重置阈值、资产类别、底层资产等，供列表/监控展示）",
    )
    live_effective_assets: Optional[List[str]] = Field(
        None,
        description="日常监控实际参与计算的资产标识列表（与运行时 universe、行情列一致）",
    )
    live_effective_asset_labels: Optional[List[str]] = Field(
        None,
        description="与 live_effective_assets 同序的展示用资产名称（供监控页标签等）",
    )

    @field_serializer('parameters')
    def serialize_parameters(self, v: Dict[str, Any]) -> Dict[str, Any]:
        """将字典类型的参数序列化为JSON字符串返回给前端"""
        if not v:
            return v
        
        import json
        processed = {}
        for key, value in v.items():
            if isinstance(value, dict):
                processed[key] = json.dumps(value, ensure_ascii=False)
            else:
                processed[key] = value
        return processed


class WeightChangesOut(BaseModel):
    """权重变化输出模型"""
    date: str = Field(..., description="日期，格式：YYYY-MM-DD")
    weights: List[AssetWeight] = Field(
        ..., 
        description="各资产权重列表"
    )


class BacktestResultOut(BaseModel):
    """回测结果输出模型"""
    total_return: float = Field(..., description="总收益率")
    annual_return: float = Field(..., description="年化收益率")
    annual_volatility: float = Field(..., description="年化波动率")
    sharpe_ratio: float = Field(..., description="夏普比率")
    max_drawdown: float = Field(..., description="最大回撤")
    calmar_ratio: Optional[float] = Field(None, description="卡玛比率")
    latest_unit_value: float = Field(..., description="最新单位净值")
    equity_curve: List[EquityPointOut] = Field(default_factory=list, description="净值曲线")
    return_curve: List[ReturnPointOut] = Field(default_factory=list, description="收益率曲线")
    positions: List[PositionRecordOut] = Field(default_factory=list, description="持仓记录")
    weight_changes: List[WeightChangePoint] = Field(
        default_factory=list, 
        description="权重变化记录列表，每项包含date(日期)和weights(各资产权重字典)字段"
    )
    asset_names: Optional[Dict[str, str]] = Field(None, description="资产名称字典，键为资产代码，值为资产名称")


class BacktestRequest(BaseModel):
    """回测请求"""
    start_date: datetime = Field(..., description="回测开始日期")
    end_date: datetime = Field(..., description="回测结束日期")
    initial_capital: float = Field(1_000_000, description="初始资金")
    benchmark_code: Optional[str] = Field(None, description="业绩基准代码（回测时指定）")
    
    @field_validator('start_date', 'end_date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持只传入年月日格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            # 如果是字符串且只有日期部分，补充时间部分
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v


class BacktestRecordOut(BaseModel):
    """回测记录输出模型"""
    id: str = Field(..., description="记录ID")
    model_id: str = Field(..., description="模型ID")
    start_date: datetime = Field(..., description="回测开始日期")
    end_date: datetime = Field(..., description="回测结束日期")
    initial_capital: float = Field(..., description="初始资金")
    result: BacktestResultOut = Field(..., description="回测结果")
    remark: Optional[str] = Field(None, description="备注信息")
    created_at: datetime = Field(..., description="创建时间")
    
    model_config = {"protected_namespaces": ()}  # 允许使用 model_ 前缀的字段名
    
    @field_validator('start_date', 'end_date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持字符串日期格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            # 如果是字符串且只有日期部分，补充时间部分
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v
    
    @field_serializer('start_date', 'end_date')
    def serialize_date(self, value: datetime) -> str:
        """序列化日期为YYYY-MM-DD格式"""
        return value.strftime('%Y-%m-%d') if value else None


class LivePublishRequest(BaseModel):
    """实盘发布请求体（可选字段均为默认时由服务层从模型继承）"""

    source: str = Field("strategy", description="操作来源，如 strategy / live_monitoring")
    operator: Optional[str] = Field(None, description="操作人")
    rebalance_mode: Optional[LiveRebalanceMode] = Field(
        None, description="实盘调仓模式；不传则沿用模型当前值"
    )
    volatility_threshold: Optional[float] = Field(
        None, description="波动率阈值；不传则从模型或策略参数推导"
    )


class LiveConfigUpdate(BaseModel):
    """更新实盘配置请求体"""

    source: str = Field("strategy", description="操作来源")
    operator: Optional[str] = Field(None, description="操作人")
    rebalance_mode: Optional[LiveRebalanceMode] = Field(None, description="调仓模式")
    volatility_threshold: Optional[float] = Field(None, description="波动率阈值")


class ManualRebalanceDecisionRequest(BaseModel):
    """手动确认/跳过调仓"""

    decision: str = Field(..., description="confirm 确认执行 / skip 跳过")
    operator: Optional[str] = Field(None, description="操作人")
    comment: Optional[str] = Field(None, description="备注")


class LiveChangeLogOut(BaseModel):
    """实盘变更日志条目"""

    id: str = Field(..., description="MongoDB 文档 _id")
    model_id: str = Field(..., description="策略模型 ID")
    action: str = Field("", description="动作类型")
    source: str = Field("", description="来源")
    operator: Optional[str] = Field(None, description="操作人")
    live_version: Optional[int] = Field(None, description="实盘版本号")
    before: Dict[str, Any] = Field(default_factory=dict, description="变更前快照")
    after: Dict[str, Any] = Field(default_factory=dict, description="变更后快照")
    change_summary: Optional[str] = Field(None, description="摘要")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    monitor_scoped_changes: Optional[Dict[str, Any]] = Field(
        None,
        description="日常监控相关变更：实盘生效参数、底层资产、窗口等（仅变动字段，old/new）",
    )

    model_config = {"protected_namespaces": ()}

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)