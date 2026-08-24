"""监测策略数据模型

存入 MongoDB monitored_strategies 集合。
每条记录 = 一个"成型策略"（必选、可改名、无需发布流程）。
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class MonitoredSourceType(str, Enum):
    """监测策略来源类型"""
    RESEARCHER = "researcher"           # 研究员独立策略
    SYSTEM_STRATEGY = "system_strategy"  # 系统策略模型（来自策略库）
    PORTFOLIO = "portfolio"             # 组合模型


class MonitoredStatus(str, Enum):
    """监测策略状态"""
    ACTIVE = "active"       # 正常监测中
    PAUSED = "paused"       # 暂停（保留数据，不跑新日期）
    ARCHIVED = "archived"   # 归档（不再展示）


class MonitoredStrategy(BaseModel):
    """监测策略（monitored_strategies 集合）

    核心字段：
    - display_name: 可改名的展示名称
    - source_type + source_ref: 标识策略来源
    - composition: 三层组合配置（直接用于构建 CompositionPipeline）
    - strategy_params: 策略参数
    - asset_codes: 资产池
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    @field_validator('id', mode='before')
    @classmethod
    def convert_objectid(cls, v):
        if v is not None:
            return str(v)
        return v

    display_name: str = Field(..., description="展示名称（可改名）")
    source_type: MonitoredSourceType = Field(..., description="来源类型")
    source_ref: str = Field(..., description="来源引用（研究员策略码/策略模型ID/组合ID）")
    description: str = Field("", description="策略描述")

    # 三层引擎配置
    asset_codes: List[str] = Field(default_factory=list, description="资产池代码列表")
    composition: Dict[str, Any] = Field(default_factory=dict, description="三层组合配置")
    strategy_params: Dict[str, Any] = Field(default_factory=dict, description="策略参数")
    weight_caps: Dict[str, float] = Field(default_factory=dict, description="资产权重上限")
    asset_name_map: Dict[str, str] = Field(default_factory=dict, description="代码→名称映射")

    # 状态与元数据
    status: MonitoredStatus = Field(MonitoredStatus.ACTIVE, description="状态")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        populate_by_name = True
