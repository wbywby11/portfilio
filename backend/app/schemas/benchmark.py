"""业绩基准API模型"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from app.models.benchmark import BenchmarkType


class BenchmarkComponentCreate(BaseModel):
    """基准成分创建模型"""
    asset_code: str = Field(..., description="资产代码")
    weight: float = Field(..., ge=0, le=1, description="权重(0-1之间)")


class PerformanceBenchmarkCreate(BaseModel):
    """创建业绩基准请求"""
    code: str = Field(..., description="基准代码，如B001")
    name: str = Field(..., description="基准名称")
    benchmark_type: BenchmarkType = Field(..., description="基准类型")
    description: str = Field(..., description="基准描述")
    components: List[BenchmarkComponentCreate] = Field(
        default_factory=list,
        description="基准成分列表(仅适用于复合基准)"
    )
    fixed_return: Optional[float] = Field(None, description="固定收益率(仅适用于绝对基准，0.05表示5%)")


class PerformanceBenchmarkUpdate(BaseModel):
    """更新业绩基准请求（所有字段可选）"""
    name: Optional[str] = Field(None, description="基准名称")
    benchmark_type: Optional[BenchmarkType] = Field(None, description="基准类型")
    description: Optional[str] = Field(None, description="基准描述")
    components: Optional[List[BenchmarkComponentCreate]] = Field(None, description="基准成分列表")
    fixed_return: Optional[float] = Field(None, description="固定收益率(仅适用于绝对基准，0.05表示5%)")
    is_active: Optional[bool] = Field(None, description="是否启用")


class PerformanceBenchmarkOut(PerformanceBenchmarkCreate):
    """业绩基准输出模型"""
    id: str = Field(..., description="基准ID")
    is_active: bool = Field(..., description="是否启用")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")