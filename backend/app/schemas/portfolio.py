""" 模拟组合API模型"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.portfolio import PortfolioType, RebalanceAction


class PositionIn(BaseModel):
    """
    持仓输入模型
    
    支持两种配置方式：
    - 按权重：提供 weight，系统根据总资金和价格计算 shares
    - 按份额：提供 shares，系统根据价格计算 weight
    
    注意：weight 和 shares 至少提供一个
    """
    asset_code: str = Field(..., description="资产代码")
    asset_name: str = Field(..., description="资产名称")
    weight: Optional[float] = Field(None, description="权重（0-1之间，按权重配置时必填）")
    shares: Optional[float] = Field(None, description="持有份额（按份额配置时必填）")
    
    @model_validator(mode='after')
    def validate_position(self):
        """验证 weight 和 shares 至少提供一个"""
        if self.weight is None and self.shares is None:
            raise ValueError("必须提供 weight（权重）或shares（份额）中的至少一个")
        
        # 验证权重范围
        if self.weight is not None and (self.weight < 0 or self.weight > 1):
            raise ValueError(f"权重必须在0-1之间，当前值: {self.weight}")
        
        # 验证份额为正数
        if self.shares is not None and self.shares <= 0:
            raise ValueError(f"持有份额必须大于0，当前值: {self.shares}")
        
        return self


class PortfolioCreate(BaseModel):
    """创建模拟组合请求"""
    name: str = Field(..., description="组合名称")
    portfolio_type: PortfolioType = Field(..., description="组合类型")
    description: Optional[str] = Field(None, description="组合描述")
    model_id: Optional[str] = Field(None, description="关联的模型ID")
    rebalance_frequency: Optional[str] = Field(None, description="调仓频率")
    initial_capital: float = Field(1_000_000, description="初始资金")
    inception_date: Optional[datetime] = Field(None, description="建仓日期（不提供则为当前日期）")
    created_by: Optional[str] = Field(None, description="创建人")
    positions: List[PositionIn] = Field(default_factory=list, description="持仓列表")
    
    model_config = {"protected_namespaces": ()}  # 允许使用 model_ 前缀的字段名
    
    @field_validator('inception_date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """支持字符串日期格式 (YYYY-MM-DD)"""
        if isinstance(v, str):
            if len(v) == 10 and v.count('-') == 2:
                v = f"{v}T00:00:00"
        return v


from app.schemas.strategy_model import BacktestResultOut, AssetPositionOut

class PortfolioOut(PortfolioCreate):
    """模拟组合输出模型"""
    id: str = Field(..., description="组合ID")
    current_capital: float = Field(..., description="当前资金")
    inception_date: datetime = Field(..., description="建仓日期")
    performance: Optional[BacktestResultOut] = Field(None, description="业绩指标")
    
    # 冗余扁平化指标，方便列表展示
    total_return: Optional[float] = Field(None, description="累计收益率")
    annual_return: Optional[float] = Field(None, description="年化收益率")
    max_drawdown: Optional[float] = Field(None, description="最大回撤")
    sharpe_ratio: Optional[float] = Field(None, description="夏普比率")
    latest_unit_value: Optional[float] = Field(None, description="最新单位净值")
    
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class PortfolioDetailOut(BaseModel):
    """组合详情输出（包含基础信息、业绩指标、最新持仓）"""
    id: str = Field(..., description="组合ID")
    name: str = Field(..., description="组合名称")
    portfolio_type: PortfolioType = Field(..., description="组合类型")
    description: Optional[str] = Field(None, description="组合描述")
    inception_date: datetime = Field(..., description="建仓日期")
    initial_capital: float = Field(..., description="初始资金")
    current_capital: float = Field(..., description="当前市值")
    
    # 核心指标
    metrics: BacktestResultOut = Field(..., description="业绩分析指标（包含曲线、风险指标、调仓历史）")
    
    # 当前持仓简化版（用于占比图表）
    current_holdings: List[AssetPositionOut] = Field(..., description="当前资产权重占比")

    model_config = {"protected_namespaces": ()}


class RebalanceCreate(BaseModel):
    """调仓记录创建请求"""
    rebalance_date: datetime = Field(..., description="调仓日期")
    action: RebalanceAction = Field(..., description="调仓动作")
    reason: Optional[str] = Field(None, description="调仓原因")
    positions_before: List[PositionIn] = Field(default_factory=list, description="调仓前持仓")
    positions_after: List[PositionIn] = Field(default_factory=list, description="调仓后持仓")
