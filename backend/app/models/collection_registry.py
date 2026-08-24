# -*- coding: utf-8 -*-
"""
集合元数据注册中心数据模型

对应集合: _collection_registry（系统内部集合，`_` 前缀）

写入来源: CollectionRegistryService（collection_registry.py）
- 系统启动时从 DOMAIN_METADATA 预注册
- 运行时自动发现并注册新集合
- 支持手动标注补充

被消费方: AI Agent 语义查询、数据资产探索、影响分析
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CollectionRegistryEntry(BaseModel):
    """集合元数据条目 (_collection_registry 集合)

    每个条目描述一个 MongoDB 集合的语义信息。
    """
    id: Optional[str] = Field(None, alias="_id")
    collection_name: str = Field(..., description="集合名（唯一标识）")
    display_name: str = Field("", description="显示名称（中文）")
    description: str = Field("", description="集合描述")
    domain: str = Field("", description="所属功能域: market / strategy / monitor / portfolio / option / agent / research / infra")
    is_whitelisted: bool = Field(True, description="是否白名单（AI Agent 可查询）")

    # 结构信息
    fields: List[Dict[str, Any]] = Field(default_factory=list, description="字段列表（从采样推断）")
    indexes: List[Dict[str, Any]] = Field(default_factory=list, description="索引列表")
    record_count: int = Field(0, description="实际记录数")

    # 语义信息
    primary_keys: List[str] = Field(default_factory=list, description="业务主键字段列表")
    foreign_keys: Dict[str, Any] = Field(default_factory=dict, description="外键引用关系 {字段: 目标集合.字段}")
    key_fields: List[str] = Field(default_factory=list, description="关键查询字段")
    typical_queries: List[str] = Field(default_factory=list, description="典型查询场景")
    sensitive_fields: List[str] = Field(default_factory=list, description="敏感字段列表（手动标注）")

    class Config:
        populate_by_name = True
