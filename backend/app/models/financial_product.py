"""
理财产品数据模型
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class ProductType(str, Enum):
    """产品类型"""
    FIXED_INCOME = "固收类"
    FIXED_INCOME_PLUS = "固收+"
    BALANCED = "混合类"
    EQUITY = "权益类"
    COMMODITY = "商品类"
    CASH_MGMT = "现金管理类"


class RiskLevel(str, Enum):
    """风险等级"""
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class ProductStatus(str, Enum):
    """产品状态"""
    DRAFT = "草稿"
    VALIDATED = "已验证"
    APPROVED = "已审批"
    LAUNCHED = "已发行"
    EXPIRED = "已到期"
    ARCHIVED = "已归档"


class FinancialProduct(BaseModel):
    """理财产品模型"""
    id: Optional[str] = Field(None, alias="_id")
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
    is_active: bool = Field(True, description="是否启用")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.strftime('%Y-%m-%d') if v else None
        }
