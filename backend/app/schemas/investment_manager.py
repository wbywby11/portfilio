"""投资经理API模型"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from app.models.investment_manager import ManagerLevel, ExpertiseDomain, RiskAppetite


class InvestmentManagerCreate(BaseModel):
    """创建投资经理请求"""
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


class InvestmentManagerUpdate(BaseModel):
    """更新投资经理请求（所有字段可选）"""
    name: Optional[str] = Field(None, description="姓名")
    level: Optional[ManagerLevel] = Field(None, description="职级")
    department: Optional[str] = Field(None, description="部门")
    expertise: Optional[List[ExpertiseDomain]] = Field(None, description="专长领域（多选）")
    risk_appetite: Optional[RiskAppetite] = Field(None, description="风险偏好")
    years_experience: Optional[int] = Field(None, description="从业年限")
    certifications: Optional[List[str]] = Field(None, description="资格认证")
    current_aum: Optional[float] = Field(None, description="当前管理规模（亿）")
    max_aum: Optional[float] = Field(None, description="最大管理容量（亿）")
    performance_score: Optional[float] = Field(None, description="历史业绩评分(0-100)")
    managed_product_ids: Optional[List[str]] = Field(None, description="当前管理的产品ID列表")
    is_active: Optional[bool] = Field(None, description="是否启用")


class InvestmentManagerOut(InvestmentManagerCreate):
    """投资经理输出模型"""
    id: str = Field(..., description="经理ID")
    is_active: bool = Field(..., description="是否启用")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
