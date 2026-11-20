# -*- coding: utf-8 -*-
"""策略配置版本模型 —— 每次「发布/刷新发布」追加一条，永不改写.

为什么正文要整份复制：
    ``strategy_models.published_snapshot`` 只保留最新一版，回看 v1 时它已经被
    v2 覆盖（H7）。版本表存 ``snapshot_body``（完整正文副本），才能回答
    「三个月前那次回测按的是哪份配置」。

版本链口径：
    - 唯一键是 ``(model_id, version_no)``，``version_no`` 直接复用
      ``publish_model`` / ``republish_model`` 内已有的 ``version`` 变量
      （即 ``published_version``），不另行计算；
    - ``parent_version_id`` 指向上一条版本（按 ``version_no`` 降序取），
      用于血缘回溯；首版为 None；
    - ``live_publish`` 只冻结「已在发布的配置」，不产生新版本号，因此不写本表
      （实盘版本号记在 ``strategy_models.live_version`` 与变更日志里）；
    - ``live_config_update`` 是实盘中修改阈值/调仓模式：推进 ``live_version``
      并重算 ``config_fingerprint``，同样追加一条正文副本，供监控运行记录核对。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

__all__ = ["SOURCE_ACTIONS", "StrategyVersion"]

# publish=首次发布 / republish=已发布后刷新快照 / live_publish=预留（本期不新增版本）
# live_config_update=实盘中修改阈值或调仓模式（递增 live_version、重算指纹、追加版本）
SOURCE_ACTIONS = ("publish", "republish", "live_publish", "live_config_update")


class StrategyVersion(BaseModel):
    """策略配置版本文档（append-only）"""

    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")

    # ── 身份 ──
    version_id: str = Field(..., description="版本稳定标识（UUID4 字符串）")
    strategy_id: Optional[str] = Field(
        None, description="策略本体标识（按 template_code 反查 strategy_registry；查不到为 None）"
    )
    model_id: str = Field(..., description="strategy_models._id")
    template_code: Optional[str] = Field(None, description="策略模板码")

    # ── 版本序 ──
    version_no: int = Field(..., description="版本序号，等于 published_version")
    source_action: str = Field(
        "publish", description="触发动作：publish / republish / live_publish（预留）/ live_config_update"
    )
    parent_version_id: Optional[str] = Field(
        None, description="上一条版本的 version_id；首版为 None"
    )

    # ── 正文（可复现维度）──
    snapshot_body: Dict[str, Any] = Field(
        default_factory=dict, description="发布快照完整正文副本（含 frozen_at）"
    )
    config_fingerprint: Optional[str] = Field(
        None, description="compute_config_fingerprint(snapshot_body) 的结果，由调用方传入"
    )
    asset_pool_hash: Optional[str] = Field(None, description="资产池指纹（排序去重后 sha256）")
    contract_hash: Optional[str] = Field(
        None, description="数据契约指纹（静态反射 get_data_contract 后 sha256）"
    )

    # ── 审计 ──
    operator: Optional[str] = Field(None, description="操作人")
    created_at: datetime = Field(default_factory=datetime.now, description="写入时间（datetime，非字符串）")
    schema_version: int = Field(1, description="版本文档 schema 版本，便于将来迁移")

    class Config:
        populate_by_name = True
        protected_namespaces = ()
