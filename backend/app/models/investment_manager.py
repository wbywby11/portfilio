"""
投资经理数据模型
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class ManagerLevel(str, Enum):
    """投资经理职级"""
    JUNIOR = "初级投资经理"
    SENIOR = "高级投资经理"
    DIRECTOR = "投资总监"


class ExpertiseDomain(str, Enum):
    """专长领域"""
    RATES = "利率债"
    CREDIT = "信用债"
    EQUITY = "权益投资"
    QUANT = "量化策略"
    MACRO = "宏观配置"
    COMMODITY = "商品投资"
    MULTI_ASSET = "多资产配置"


class RiskAppetite(str, Enum):
    """风险偏好"""
    CONSERVATIVE = "保守型"
    MODERATE = "稳健型"
    BALANCED = "平衡型"
    AGGRESSIVE = "进取型"


class InvestmentManager(BaseModel):
    """投资经理模型"""
    id: Optional[str] = Field(None, alias="_id")
    manager_code: str = Field(..., description="经理代码（唯一）")
    name: str = Field(..., description="姓名")
    level: ManagerLevel = Field(..., description="职级")
    department: Optional[str] = Field(None, description="部门")
    expertise: List[ExpertiseDomain] = Field(default_factory=list, description="专长领域（多选）")
    risk_appetite: RiskAppetite = Field(..., description="风险偏好")
    years_experience: int = Field(..., description="从业年限")
    certifications: List[str] = Field(default_factory=list, description="资格认证")
    current_aum: float = Field(0.0, description="当前管理规模（亿）")
    max_aum: float = Field(0.0, description="最大管理容量（亿）")
    performance_score: Optional[float] = Field(None, description="历史业绩评分(0-100)")
    managed_product_ids: List[str] = Field(default_factory=list, description="当前管理的产品ID列表")
    is_active: bool = Field(True, description="是否启用")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.strftime('%Y-%m-%d %H:%M:%S') if v else None
        }
