"""数据资产模型 - 基于 MongoDB 实际集合的元数据注册表

每个集合自动注册为一个数据资产，记录实际统计信息。

实际集合名: _data_asset_registry
service 层 (api_data_asset_service.py) 使用 COLLECTION = "_data_asset_registry"，
本文档中的字段设计以代码实际为准。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─── 枚举 ────────────────────────────────────────────────────────────────────

class AssetStatus(str, Enum):
    """资产状态"""
    active = "active"
    deprecated = "deprecated"


# ─── 核心模型 ────────────────────────────────────────────────────────────────

class CollectionAsset(BaseModel):
    """MongoDB 集合资产（实际数据库驱动）"""

    collection_name: str = Field(..., description="集合名（唯一标识）")

    # 实际统计信息
    record_count: int = Field(0, description="实际记录数")
    storage_size_bytes: int = Field(0, description="存储大小（字节）")
    fields: List[str] = Field(default_factory=list, description="字段列表（从采样推断）")
    field_count: int = Field(0, description="字段数量")

    # 日期信息（自动探测）
    date_field: Optional[str] = Field(None, description="自动探测到的日期字段名")
    date_range: Optional[Dict[str, Any]] = Field(None, description="{min, max} 实际日期范围")

    # 人工编辑字段
    description: str = Field("", description="业务描述")
    tags: List[str] = Field(default_factory=list, description="标签")
    owner: str = Field("", description="负责人")
    status: AssetStatus = Field(AssetStatus.active, description="资产状态")

    # 元数据
    last_scanned_at: Optional[str] = Field(None, description="最近扫描时间")
    created_at: Optional[str] = Field(None, description="创建时间")
    updated_at: Optional[str] = Field(None, description="更新时间")


class CollectionAssetUpdate(BaseModel):
    """更新集合资产 — 请求体（仅人工编辑字段可更新）"""
    description: Optional[str] = Field(None, description="业务描述")
    tags: Optional[List[str]] = Field(None, description="标签")
    owner: Optional[str] = Field(None, description="负责人")
    status: Optional[AssetStatus] = Field(None, description="资产状态")


class CollectionAssetListResponse(BaseModel):
    """集合资产列表 — 分页响应"""
    items: List[CollectionAsset] = Field(default_factory=list, description="资产列表")
    total: int = Field(0, description="总数")
    total_records: int = Field(0, description="所有集合总记录数")
    total_storage_bytes: int = Field(0, description="所有集合总存储大小")
