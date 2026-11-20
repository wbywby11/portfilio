# -*- coding: utf-8 -*-
"""资产池版本模型 —— 一个 universe 一条时间轴，历史版本不可改写.

为什么资产池要版本化：
    发布快照冻结的是「配置」，不是「池子里当时有谁」。同一策略模型在不同时间
    因为换标的而发布 v1/v2 时，仅看 published_snapshot 无法回答「v1 当时用的是
    哪份资产清单」——池子本身需要一条独立的时间轴。

生效区间口径：
    ``effective_from`` / ``effective_to`` 按**日期**比较（含两端），
    ``effective_to`` 为空表示「仍然生效、无截止日」。按日期而不是按时间戳比较，
    是为了让「v1 到 6-30、v2 从 7-01」这种按自然日切分的写法不需要补 23:59:59。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

__all__ = ["UNIVERSE_SOURCES", "AssetUniverseVersion"]

# 池子来源：model=按模型当前配置冻结 / tags=按标签筛选 / preset=预置清单
UNIVERSE_SOURCES = ("model", "tags", "preset")


class AssetUniverseVersion(BaseModel):
    """资产池版本文档"""

    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    universe_id: str = Field(..., description="资产池标识（业务侧稳定键，非 _id）")
    version: int = Field(..., description="版本序号，同一 universe_id 从 1 递增")
    name: Optional[str] = Field(None, description="资产池展示名")

    asset_codes: List[str] = Field(default_factory=list, description="池内资产代码（排序去重）")
    asset_names: Dict[str, str] = Field(default_factory=dict, description="代码→名称快照")
    pool_hash: Optional[str] = Field(None, description="排序去重后 asset_codes 的 sha256")

    source: str = Field("model", description="来源：model / tags / preset")
    effective_from: datetime = Field(default_factory=datetime.now, description="生效日（含）")
    effective_to: Optional[datetime] = Field(None, description="失效日（含）；None 表示仍在生效")
    frozen_at: datetime = Field(default_factory=datetime.now, description="冻结时间（写入时间）")
    created_by: Optional[str] = Field(None, description="创建人/创建来源")

    class Config:
        populate_by_name = True
        protected_namespaces = ()
