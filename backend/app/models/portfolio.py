"""
模拟组合数据模型
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class PortfolioType(str, Enum):
    """组合类型"""
    MANUAL = "手工创建"
    MODEL_DRIVEN = "模型驱动"


class RebalanceAction(str, Enum):
    """调仓动作"""
    BUY = "买入"
    SELL = "卖出"
    ADJUST = "调整"


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


class RebalanceRecord(BaseModel):
    """调仓记录"""
    id: Optional[str] = Field(None, alias="_id")
    portfolio_id: str = Field(..., description="组合ID")
    rebalance_date: datetime = Field(..., description="调仓日期")
    action: RebalanceAction = Field(..., description="调仓动作")
    positions_before: List[Position] = Field(default_factory=list, description="调仓前持仓")
    positions_after: List[Position] = Field(default_factory=list, description="调仓后持仓")
    reason: Optional[str] = Field(None, description="调仓原因")
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


from app.models.strategy_model import BacktestResult as ModelBacktestResult

class Portfolio(BaseModel):
    """模拟组合"""
    id: Optional[str] = Field(None, alias="_id")
    name: str = Field(..., description="组合名称")
    portfolio_type: PortfolioType = Field(..., description="组合类型")
    description: Optional[str] = Field(None, description="组合描述")
    
    # 关联模型(模型驱动时使用)
    model_id: Optional[str] = Field(None, description="关联的模型ID")
    rebalance_frequency: Optional[str] = Field(None, description="调仓频率（从模型同步）")
    
    # 资金配置
    initial_capital: float = Field(1000000, description="初始资金")
    current_capital: float = Field(1000000, description="当前资金")
    
    # 持仓信息
    positions: List[Position] = Field(default_factory=list, description="当前持仓")
    
    # 业绩指标 (复用回测结果模型)
    performance: Optional[ModelBacktestResult] = Field(None, description="业绩指标")
    
    # 时间信息
    inception_date: datetime = Field(default_factory=datetime.now, description="建仓日期（业绩起始日）")
    created_by: Optional[str] = Field(None, description="创建人")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}
        protected_namespaces = ()  # 允许使用 model_ 前缀的字段名
