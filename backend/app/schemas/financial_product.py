"""理财产品相关API请求/响应模型"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_serializer
from app.models.financial_product import ProductType, RiskLevel, ProductStatus


class FinancialProductCreate(BaseModel):
    """创建理财产品请求"""
    product_code: str = Field(..., description="产品代码（唯一）")
    name: str = Field(..., description="产品名称")
    product_type: ProductType = Field(..., description="产品类型")
    risk_level: RiskLevel = Field(..., description="风险等级")
    duration_months: int = Field(..., description="投资期限（月）")
    min_investment: float = Field(..., description="起购金额（元）")
    expected_return_min: Optional[float] = Field(None, description="预期收益下限")
    expected_return_max: Optional[float] = Field(None, description="预期收益上限")
    strategy_type: Optional[str] = Field(None, description="关联策略类型代码")
    asset_codes: List[str] = Field(default_factory=list, description="底层资产代码列表")
    status: ProductStatus = Field(default=ProductStatus.DRAFT, description="产品状态")
    description: Optional[str] = Field(None, description="产品简介")


class FinancialProductUpdate(BaseModel):
    """更新理财产品请求"""
    product_code: Optional[str] = Field(None, description="产品代码")
    name: Optional[str] = Field(None, description="产品名称")
    product_type: Optional[ProductType] = Field(None, description="产品类型")
    risk_level: Optional[RiskLevel] = Field(None, description="风险等级")
    duration_months: Optional[int] = Field(None, description="投资期限（月）")
    min_investment: Optional[float] = Field(None, description="起购金额（元）")
    expected_return_min: Optional[float] = Field(None, description="预期收益下限")
    expected_return_max: Optional[float] = Field(None, description="预期收益上限")
    strategy_type: Optional[str] = Field(None, description="关联策略类型代码")
    asset_codes: Optional[List[str]] = Field(None, description="底层资产代码列表")
    status: Optional[ProductStatus] = Field(None, description="产品状态")
    description: Optional[str] = Field(None, description="产品简介")
    is_active: Optional[bool] = Field(None, description="是否启用")


class FinancialProductOut(BaseModel):
    """理财产品返回模型"""
    id: str = Field(..., description="产品ID")
    product_code: str = Field(..., description="产品代码")
    name: str = Field(..., description="产品名称")
    product_type: ProductType = Field(..., description="产品类型")
    risk_level: RiskLevel = Field(..., description="风险等级")
    duration_months: int = Field(..., description="投资期限（月）")
    min_investment: float = Field(..., description="起购金额（元）")
    expected_return_min: Optional[float] = Field(None, description="预期收益下限")
    expected_return_max: Optional[float] = Field(None, description="预期收益上限")
    strategy_type: Optional[str] = Field(None, description="关联策略类型代码")
    asset_codes: List[str] = Field(default_factory=list, description="底层资产代码列表")
    status: ProductStatus = Field(..., description="产品状态")
    description: Optional[str] = Field(None, description="产品简介")
    is_active: bool = Field(..., description="是否启用")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime) -> str:
        """序列化 datetime 为 YYYY-MM-DD 格式"""
        return dt.strftime('%Y-%m-%d') if dt else None
