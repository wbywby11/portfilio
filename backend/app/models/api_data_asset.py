"""
API 数据资产模型

定义数据资产注册表的 Pydantic 模型，用于数据资产全生命周期管理。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ─── 枚举类型 ───────────────────────────────────────────────────────────────────

class DataAssetType(str, Enum):
    """数据资产来源类型"""
    api_upstream = "api_upstream"
    local_import = "local_import"
    computed = "computed"


class SyncStrategy(str, Enum):
    """同步策略"""
    manual = "manual"
    scheduled = "scheduled"
    realtime = "realtime"


class SyncStatus(str, Enum):
    """最近一次同步状态"""
    success = "success"
    failed = "failed"
    partial = "partial"
    never = "never"


class AssetStatus(str, Enum):
    """资产生命周期状态"""
    active = "active"
    deprecated = "deprecated"


class AuthType(str, Enum):
    """认证方式"""
    none = "none"
    api_key = "api_key"
    token = "token"


# ─── 核心模型 ───────────────────────────────────────────────────────────────────

class ApiDataAsset(BaseModel):
    """API 数据资产"""

    asset_id: str = Field(..., description="唯一标识")
    name: str = Field(..., description="资产名称")
    asset_type: DataAssetType = Field(..., description="资产来源类型")
    description: str = Field("", description="业务描述")

    # 数据源信息
    source_url: Optional[str] = Field(None, description="上游API地址")
    source_resource: Optional[str] = Field(None, description="上游资源标识")
    source_params: dict = Field(default_factory=dict, description="请求参数模板")
    auth_type: AuthType = Field(AuthType.none, description="认证方式")

    # 存储信息
    target_collection: str = Field(..., description="目标MongoDB集合名")
    primary_key: List[str] = Field(default_factory=list, description="主键字段列表")
    schema_fields: List[dict] = Field(default_factory=list, description="字段定义")

    # 同步策略
    sync_strategy: SyncStrategy = Field(SyncStrategy.manual, description="同步策略")
    sync_cron: Optional[str] = Field(None, description="定时同步cron表达式")
    last_sync_at: Optional[datetime] = Field(None, description="最近同步时间")
    last_sync_status: SyncStatus = Field(SyncStatus.never, description="最近同步状态")
    last_sync_count: int = Field(0, description="最近同步记录数")

    # 数据质量
    total_records: int = Field(0, description="总记录数")
    date_range_start: Optional[str] = Field(None, description="数据起始日期（ISO格式）")
    date_range_end: Optional[str] = Field(None, description="数据结束日期（ISO格式）")

    # 关联信息
    connector_id: Optional[str] = Field(None, description="关联连接器ID")
    tags: List[str] = Field(default_factory=list, description="标签")
    owner: str = Field("", description="负责人")

    # 生命周期
    status: AssetStatus = Field(AssetStatus.active, description="资产状态")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
        }


# ─── 请求/响应模型 ──────────────────────────────────────────────────────────────

class ApiDataAssetCreate(BaseModel):
    """创建数据资产 — 请求体"""

    name: str = Field(..., description="资产名称")
    asset_type: DataAssetType = Field(..., description="资产来源类型")
    description: str = Field("", description="业务描述")

    # 数据源信息
    source_url: Optional[str] = Field(None, description="上游API地址")
    source_resource: Optional[str] = Field(None, description="上游资源标识")
    source_params: dict = Field(default_factory=dict, description="请求参数模板")
    auth_type: AuthType = Field(AuthType.none, description="认证方式")

    # 存储信息
    target_collection: str = Field(..., description="目标MongoDB集合名")
    primary_key: List[str] = Field(default_factory=list, description="主键字段列表")
    schema_fields: List[dict] = Field(default_factory=list, description="字段定义")

    # 同步策略
    sync_strategy: SyncStrategy = Field(SyncStrategy.manual, description="同步策略")
    sync_cron: Optional[str] = Field(None, description="定时同步cron表达式")

    # 数据质量
    total_records: int = Field(0, description="总记录数")
    date_range_start: Optional[str] = Field(None, description="数据起始日期（ISO格式）")
    date_range_end: Optional[str] = Field(None, description="数据结束日期（ISO格式）")

    # 关联信息
    connector_id: Optional[str] = Field(None, description="关联连接器ID")
    tags: List[str] = Field(default_factory=list, description="标签")
    owner: str = Field("", description="负责人")

    # 生命周期
    status: AssetStatus = Field(AssetStatus.active, description="资产状态")


class ApiDataAssetUpdate(BaseModel):
    """更新数据资产 — 请求体（所有字段可选）"""

    name: Optional[str] = Field(None, description="资产名称")
    asset_type: Optional[DataAssetType] = Field(None, description="资产来源类型")
    description: Optional[str] = Field(None, description="业务描述")

    source_url: Optional[str] = Field(None, description="上游API地址")
    source_resource: Optional[str] = Field(None, description="上游资源标识")
    source_params: Optional[dict] = Field(None, description="请求参数模板")
    auth_type: Optional[AuthType] = Field(None, description="认证方式")

    target_collection: Optional[str] = Field(None, description="目标MongoDB集合名")
    primary_key: Optional[List[str]] = Field(None, description="主键字段列表")
    schema_fields: Optional[List[dict]] = Field(None, description="字段定义")

    sync_strategy: Optional[SyncStrategy] = Field(None, description="同步策略")
    sync_cron: Optional[str] = Field(None, description="定时同步cron表达式")

    total_records: Optional[int] = Field(None, description="总记录数")
    date_range_start: Optional[str] = Field(None, description="数据起始日期（ISO格式）")
    date_range_end: Optional[str] = Field(None, description="数据结束日期（ISO格式）")

    connector_id: Optional[str] = Field(None, description="关联连接器ID")
    tags: Optional[List[str]] = Field(None, description="标签")
    owner: Optional[str] = Field(None, description="负责人")

    status: Optional[AssetStatus] = Field(None, description="资产状态")


class ApiDataAssetListResponse(BaseModel):
    """数据资产列表 — 分页响应"""

    items: List[ApiDataAsset] = Field(default_factory=list, description="资产列表")
    total: int = Field(0, description="总数")
    page: int = Field(1, description="当前页")
    page_size: int = Field(20, description="每页数量")


class ApiDataAssetSummary(BaseModel):
    """数据资产汇总统计"""

    total_assets: int = Field(0, description="资产总数")
    active_count: int = Field(0, description="活跃资产数")
    deprecated_count: int = Field(0, description="已废弃资产数")
    total_records: int = Field(0, description="总记录数（所有资产）")
    sync_success_count: int = Field(0, description="同步成功资产数")
    sync_failed_count: int = Field(0, description="同步失败资产数")
    by_type: dict = Field(default_factory=dict, description="按类型分组统计")
