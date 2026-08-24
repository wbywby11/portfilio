"""监测策略 API Schema（Create/Update/Out）"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class MonitoredStrategyCreate(BaseModel):
    """新增监测策略（手动添加系统策略/组合时使用）"""
    display_name: str = Field(..., min_length=1, max_length=100, description="展示名称")
    source_type: str = Field(..., description="来源类型: researcher/system_strategy/portfolio")
    source_ref: str = Field(..., min_length=1, description="来源引用")
    description: str = Field("", max_length=500, description="策略描述")
    asset_codes: List[str] = Field(default_factory=list, description="资产池代码列表")
    composition: Dict[str, Any] = Field(default_factory=dict, description="三层组合配置")
    strategy_params: Dict[str, Any] = Field(default_factory=dict, description="策略参数")
    weight_caps: Dict[str, float] = Field(default_factory=dict, description="资产权重上限")
    asset_name_map: Dict[str, str] = Field(default_factory=dict, description="代码→名称映射")


class MonitoredStrategyUpdate(BaseModel):
    """更新监测策略（改名/暂停/归档）"""
    display_name: Optional[str] = Field(None, min_length=1, max_length=100, description="展示名称")
    status: Optional[str] = Field(None, description="状态: active/paused/archived")
    description: Optional[str] = Field(None, max_length=500, description="策略描述")


class MonitoredStrategyOut(BaseModel):
    """监测策略输出"""
    id: Optional[str] = Field(None, alias="_id")
    display_name: str
    source_type: str
    source_ref: str
    description: str = ""
    asset_codes: List[str] = Field(default_factory=list)
    composition: Dict[str, Any] = Field(default_factory=dict)
    strategy_params: Dict[str, Any] = Field(default_factory=dict)
    weight_caps: Dict[str, float] = Field(default_factory=dict)
    asset_name_map: Dict[str, str] = Field(default_factory=dict)
    status: str = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
