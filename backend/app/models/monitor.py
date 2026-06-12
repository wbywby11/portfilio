"""
监控模块数据模型
用于日常组合监控、主观调仓和日报生成
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class OverrideStatus(str, Enum):
    """主观调仓状态"""
    PENDING = "pending"      # 待执行
    EXECUTED = "executed"    # 已执行
    CANCELLED = "cancelled"  # 已取消


class NavHistoryPoint(BaseModel):
    """净值历史点"""
    date: str = Field(..., description="日期 (YYYY-MM-DD)")
    nav: float = Field(..., description="净值")
    
    class Config:
        populate_by_name = True


class EventLogEntry(BaseModel):
    """事件日志条目"""
    date: str = Field(..., description="事件日期 (YYYY-MM-DD)")
    event_type: str = Field(..., description="事件类型（如 rebalance, vol_reset, signal 等）")
    description: str = Field(..., description="事件描述")
    details: Optional[Dict[str, Any]] = Field(None, description="事件详情")
    
    class Config:
        populate_by_name = True


class PendingRebalance(BaseModel):
    """待执行调仓信息"""
    trigger_date: str = Field(..., description="触发日期")
    reason: str = Field(..., description="调仓原因（如 monthly, vol_reset, subjective）")
    target_weights: Dict[str, float] = Field(default_factory=dict, description="目标权重")
    
    class Config:
        populate_by_name = True


class MonitorState(BaseModel):
    """
    组合监控状态
    存入 MongoDB monitor_states 集合
    对应 monitor_vs 的 PortfolioState
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    @field_validator('id', mode='before')
    @classmethod
    def convert_objectid(cls, v):
        """将 MongoDB ObjectId 自动转为 str"""
        if v is not None:
            return str(v)
        return v
    monitor_id: str = Field(..., description="监控实例 ID（如 'default'）")
    date: str = Field(..., description="当前日期 (YYYY-MM-DD)")
    
    # 净值相关
    nav: float = Field(1.0, description="当前净值（基于人民币）")
    nav_base: float = Field(1.0, description="基准净值（上次调仓日的净值）")
    day_count: int = Field(0, description="从基日起的运行天数")
    
    # 持仓信息
    positions_cny: Dict[str, float] = Field(
        default_factory=dict, 
        description="人民币持仓金额 {资产名: CNY金额}"
    )
    positions_local: Dict[str, float] = Field(
        default_factory=dict, 
        description="本币持仓金额 {资产名: 本币金额}"
    )
    apl_local: Dict[str, float] = Field(
        default_factory=dict, 
        description="本币累计损益 {资产名: PnL}"
    )

    # 传统持仓模型（主观策略：与回测 engine.py 对齐 NAV = cash + Σ(qty × close)）
    cash: float = Field(0.0, description="现金余额（传统持仓模型，与回测 Position.cash 对齐）")
    quantities: Dict[str, float] = Field(
        default_factory=dict,
        description="资产持仓数量 {asset_code: qty}（传统持仓模型）",
    )
    last_prices: Dict[str, float] = Field(
        default_factory=dict,
        description="上次有效收盘价 {asset_code: price}（任务#12：节假日/停牌价格回退）",
    )
    
    # 权重与调仓
    target_weights: Dict[str, float] = Field(
        default_factory=dict, 
        description="当前目标权重 {资产名: 权重}"
    )
    last_rebalance_date: Optional[str] = Field(
        None, 
        description="上次调仓日期 (YYYY-MM-DD)"
    )
    last_rebalance_fx: Dict[str, float] = Field(
        default_factory=dict, 
        description="上次调仓日汇率 {资产名: 汇率}"
    )
    pending_rebalance: Optional[Dict[str, Any]] = Field(
        None, 
        description="待执行调仓信息"
    )
    
    # 费用统计
    total_trading_cost: float = Field(0.0, description="累计交易费用")
    total_replication_cost: float = Field(0.0, description="累计复制费用")
    
    # 波动率重置
    vol_reset_count: int = Field(0, description="波动率重置次数")
    
    # 历史记录
    nav_history: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="净值历史 [{'date': '...', 'nav': ...}, ...]"
    )
    event_log: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="事件日志"
    )
    
    # 关联信息
    strategy_model_id: Optional[str] = Field(
        None, 
        description="关联的策略模型 ID（可选）"
    )

    # 绩效解释：完整初始化、主观步进暂停落库时写入的实盘参数快照（与准入接口同口径）；普通过监控不覆盖
    performance_basis: Optional[Dict[str, Any]] = Field(
        None,
        description="监控净值/绩效曲线对应的实盘参数摘要（初始化或主观步进暂停保存时写入）",
    )

    # 主观预设步进：尚有未推演交易日时为 True；已滚到行情末尾则为 False（供前端「继续执行」显隐）
    manual_preset_step_pending: bool = Field(
        False,
        description="主观策略预设调仓步进：完成某调仓日当日推演后暂停，若仍有更晚交易日待跑则为 True",
    )
    manual_preset_next_date: Optional[str] = Field(
        None,
        description="区间内下一档预设调仓日 YYYY-MM-DD；若后续仅有非调仓交易日则可能为空",
    )

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 MongoDB 存储）"""
        data = self.model_dump(by_alias=True, exclude_none=False)
        # replace_one/insert_one 不得带与文档不一致的 _id，否则触发 immutable _id 错误
        data.pop("_id", None)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorState":
        """从字典创建实例"""
        # 处理 _id 到 id 的映射
        if "_id" in data and "id" not in data:
            data["id"] = str(data["_id"])
        return cls(**data)


class SubjectiveOverride(BaseModel):
    """
    主观调仓指令
    存入 MongoDB subjective_overrides 集合
    用于手动指定目标权重进行调仓
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    @field_validator('id', mode='before')
    @classmethod
    def convert_objectid(cls, v):
        """将 MongoDB ObjectId 自动转为 str"""
        if v is not None:
            return str(v)
        return v
    override_id: str = Field(..., description="唯一调仓指令 ID")
    monitor_id: str = Field(..., description="关联的监控实例 ID")
    
    # 调仓配置
    weights: Dict[str, float] = Field(..., description="目标权重 {资产名: 权重}")
    execute_date: str = Field(..., description="执行日期 (YYYY-MM-DD)")
    
    # 状态
    status: OverrideStatus = Field(
        OverrideStatus.PENDING, 
        description="状态: pending/executed/cancelled"
    )
    description: Optional[str] = Field(None, description="调仓描述/备注")
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    executed_at: Optional[datetime] = Field(None, description="执行时间")
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 MongoDB 存储）"""
        data = self.model_dump(by_alias=True, exclude_none=False)
        data.pop("_id", None)
        # 枚举转为字符串值
        if "status" in data and isinstance(data["status"], OverrideStatus):
            data["status"] = data["status"].value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubjectiveOverride":
        """从字典创建实例"""
        if "_id" in data and "id" not in data:
            data["id"] = str(data["_id"])
        return cls(**data)


class PositionDetail(BaseModel):
    """持仓明细"""
    asset_name: str = Field(..., description="资产名称")
    weight: float = Field(..., description="权重")
    position_cny: float = Field(..., description="人民币持仓金额")
    position_local: float = Field(..., description="本币持仓金额")
    daily_return: Optional[float] = Field(None, description="日收益率")
    pnl_local: Optional[float] = Field(None, description="本币损益")
    
    class Config:
        populate_by_name = True


class SignalStatus(BaseModel):
    """信号状态"""
    vol_breach: bool = Field(False, description="波动率突破信号")
    drawdown_warning: bool = Field(False, description="回撤预警信号")
    rebalance_due: bool = Field(False, description="需要调仓信号")
    details: Optional[Dict[str, Any]] = Field(None, description="信号详情")
    
    class Config:
        populate_by_name = True


class PerformanceMetrics(BaseModel):
    """绩效指标"""
    cumulative_return: float = Field(0.0, description="累计收益率")
    annual_return: Optional[float] = Field(None, description="年化收益率")
    annual_volatility: Optional[float] = Field(None, description="年化波动率")
    sharpe_ratio: Optional[float] = Field(None, description="夏普比率")
    max_drawdown: float = Field(0.0, description="最大回撤")
    current_drawdown: float = Field(0.0, description="当前回撤")
    calmar_ratio: Optional[float] = Field(None, description="卡玛比率")
    
    class Config:
        populate_by_name = True


class MonitorDailyReport(BaseModel):
    """
    日报快照
    存入 MongoDB monitor_daily_reports 集合
    记录每日监控快照数据
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")
    monitor_id: str = Field(..., description="监控实例 ID")
    date: str = Field(..., description="日期 (YYYY-MM-DD)")
    
    # 净值数据
    nav: float = Field(..., description="净值")
    daily_return: float = Field(0.0, description="日收益率")
    
    # 杠杆
    total_leverage: float = Field(1.0, description="总杠杆")
    
    # 持仓明细
    positions: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="持仓明细列表"
    )
    
    # 信号状态
    signals: Dict[str, Any] = Field(
        default_factory=dict, 
        description="信号状态（波动率突破、回撤预警等）"
    )
    
    # 绩效指标
    performance: Dict[str, Any] = Field(
        default_factory=dict, 
        description="绩效指标（累计收益、年化收益、波动、夏普、回撤等）"
    )
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 MongoDB 存储）"""
        data = self.model_dump(by_alias=True, exclude_none=False)
        data.pop("_id", None)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorDailyReport":
        """从字典创建实例"""
        if "_id" in data and "id" not in data:
            data["id"] = str(data["_id"])
        return cls(**data)


# ============================================================
# 请求/响应模型（用于 API 接口）
# ============================================================

class MonitorStateCreate(BaseModel):
    """创建监控状态请求"""
    monitor_id: str = Field(..., description="监控实例 ID")
    strategy_model_id: Optional[str] = Field(None, description="关联的策略模型 ID")
    initial_nav: float = Field(1.0, description="初始净值")
    initial_date: str = Field(..., description="初始日期 (YYYY-MM-DD)")
    target_weights: Dict[str, float] = Field(
        default_factory=dict, 
        description="初始目标权重"
    )


class MonitorStateUpdate(BaseModel):
    """更新监控状态请求"""
    nav: Optional[float] = Field(None, description="净值")
    positions_cny: Optional[Dict[str, float]] = Field(None, description="人民币持仓")
    positions_local: Optional[Dict[str, float]] = Field(None, description="本币持仓")
    target_weights: Optional[Dict[str, float]] = Field(None, description="目标权重")
    pending_rebalance: Optional[Dict[str, Any]] = Field(None, description="待执行调仓")


class SubjectiveOverrideCreate(BaseModel):
    """创建主观调仓请求"""
    monitor_id: str = Field(..., description="监控实例 ID")
    weights: Dict[str, float] = Field(..., description="目标权重")
    execute_date: str = Field(..., description="执行日期 (YYYY-MM-DD)")
    description: Optional[str] = Field(None, description="调仓描述")


class MonitorDailyReportQuery(BaseModel):
    """日报查询请求"""
    monitor_id: str = Field(..., description="监控实例 ID")
    start_date: Optional[str] = Field(None, description="开始日期 (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="结束日期 (YYYY-MM-DD)")
    limit: int = Field(30, description="返回条数限制")
