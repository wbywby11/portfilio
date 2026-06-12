"""业绩基准数据模型"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum


class BenchmarkType(str, Enum):
    """业绩基准类型"""
    SINGLE = "单一基准"
    COMPOSITE = "复合基准"
    ABSOLUTE = "绝对基准"


class BenchmarkComponent(BaseModel):
    """复合基准成分"""
    asset_code: str = Field(..., description="资产代码")
    weight: float = Field(..., ge=0, le=1, description="权重(0-1之间)")


class PerformanceBenchmark(BaseModel):
    """业绩基准"""
    id: Optional[str] = Field(None, alias="_id", description="基准ID")
    code: str = Field(..., description="基准代码，如B001")
    name: str = Field(..., description="基准名称")
    benchmark_type: BenchmarkType = Field(..., description="基准类型")
    description: str = Field(..., description="基准描述")
    components: List[BenchmarkComponent] = Field(
        default_factory=list, 
        description="基准成分列表(仅适用于复合基准)"
    )
    fixed_return: Optional[float] = Field(None, description="固定收益率(仅适用于绝对基准，0.05表示5%)")
    is_active: bool = Field(True, description="是否启用")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}