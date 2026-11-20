# -*- coding: utf-8 -*-
"""策略档案模型 —— 一个 manifest_key 一条，strategy_id 稳定不变.

两级身份：
    - ``strategy_id``：策略本体（STRATEGY_MANIFEST 的一个 key）的稳定标识，
      由采集器生成 UUID 后永不变更；**不**从 key / 文件名 / 类名派生
      （``cso`` 的策略码、文件名、类名三者互不相同，任何派生都会在改名时漂移）；
    - ``model_id``：``strategy_models._id``，实例级外键；同一 template_code
      在建多个模型时是一对多关系，档案只记本体，不记实例。

研究员手填字段（``trial_count`` / ``owner`` / ``tags`` / ``lifecycle_stage``）
在采集器 upsert 时不被覆盖，是档案里唯一允许人工维护的部分。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

__all__ = ["LIFECYCLE_STAGES", "DEFAULT_LIFECYCLE_STAGE", "StrategyRegistryEntry"]

# 研发成熟度口径，与 ModelStatus（草稿/已发布/已归档）并存不映射：
# 「已发布」是配置冻结状态，「live」是研发成熟度，二者不是同一维度
LIFECYCLE_STAGES = ("research", "shadow", "paper", "live", "retired")
DEFAULT_LIFECYCLE_STAGE = "research"


class StrategyRegistryEntry(BaseModel):
    """策略档案文档"""

    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    # ── 身份 ──
    strategy_id: str = Field(..., description="策略本体稳定标识（UUID4 字符串）")
    manifest_key: str = Field(..., description="STRATEGY_MANIFEST 的键，唯一")
    name: str = Field(..., description="中文展示名称")
    description: Optional[str] = Field(None, description="策略说明（取自 manifest）")
    class_path: str = Field(..., description="策略类完整路径")
    strategy_form: str = Field(
        "composite", description="策略形态：composite=三层组合 / standalone=打包独立"
    )

    # ── 分类（可发现维度）──
    pillar: str = Field(
        "allocation", description="支柱：allocation / selection / control（本期只覆盖 allocation）"
    )
    family_id: Optional[str] = Field(None, description="策略族标识（同族共享择时/风控骨架）")
    signal_family: Optional[str] = Field(None, description="信号族（动量/夏普/因子打分…）")
    aliases: List[str] = Field(
        default_factory=list, description="历史别名（LEGACY_ALIASES 的键），不单独建文档"
    )
    tags: List[str] = Field(default_factory=list, description="人工标签（采集器不覆盖）")
    owner: Optional[str] = Field(None, description="负责人（采集器不覆盖）")

    # ── 组件声明与实际解析（可复用维度）──
    component_set_declared: Dict[str, Any] = Field(
        default_factory=dict,
        description="manifest 静态声明的 composition（selector/allocator/controller）",
    )
    component_set_resolved: Dict[str, Any] = Field(
        default_factory=dict,
        description="运行时实际解析结果（服务层回填；空字典表示尚未回填）",
    )
    pending_scope: List[str] = Field(
        default_factory=list,
        description="本期未纳入档案的层（如 selection / control 模板不建独立档案）",
    )

    # ── 数据契约快照（可复现维度）──
    data_contract_snapshot: Optional[Dict[str, Any]] = Field(
        None, description="静态反射 get_data_contract() 的结果；反射失败记 None"
    )
    panel_datasets_snapshot: Optional[Dict[str, str]] = Field(
        None, description="静态反射 get_extra_panels()/get_panel_datasets() 的结果"
    )

    # ── 治理（可治理维度）──
    lifecycle_stage: str = Field(
        DEFAULT_LIFECYCLE_STAGE,
        description="研发成熟度：research / shadow / paper / live / retired",
    )
    trial_count: int = Field(0, description="参数试错次数（按参数快照去重后计数）")
    parameter_search_space: Dict[str, List[Any]] = Field(
        default_factory=dict, description="参数搜索空间（取自 schema 声明了搜索范围的参数）"
    )

    # ── 时间 ──
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        populate_by_name = True
        protected_namespaces = ()
