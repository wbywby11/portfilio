# -*- coding: utf-8 -*-
"""策略运行摘要（``strategy_runs``）—— 回测 / 监控 / 信号回放的统一运行台账.

设计约束（S11）：
    - 文档只存「摘要」：8 项指标白名单 + 窗口 + 指纹引用，**不复制净值曲线**，
      单文档硬上限 8KB；正文与曲线始终以 ``backtest_records`` 为唯一来源；
    - 一个 ``backtest_record_id`` 对应且仅对应一条 ``run_kind=backtest`` 记录
      （写入方 ``StrategyRunService.append_run`` 先查后写，幂等）；
    - ``strategy_id`` / ``config_version_id`` 在 S12 身份注入链落地前可为空，
      读取侧一律按 Optional 处理。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

# 运行种类：backtest（回测）/ monitor（日常监控）/ signal_replay（信号回放）
RUN_KINDS = ("backtest", "monitor", "signal_replay")

# 运行状态：目前只有成功落库的记录会写入，failed 预留给监控失败留痕（S13）
RUN_STATUSES = ("success", "failed")

# 指标白名单（8 项）：对应 BacktestResult 上的数值字段，映射到台账的短名
METRIC_KEYS = (
    "total_return",
    "annual_return",
    "annual_vol",
    "sharpe",
    "max_drawdown",
    "calmar",
    "win_rate",
    "latest_unit_value",
)


class StrategyRun(BaseModel):
    """一条运行摘要（append-only，不做更新）"""

    run_id: str = Field(..., description="运行唯一标识（uuid4）")
    run_kind: str = Field("backtest", description="backtest / monitor / signal_replay")
    strategy_id: Optional[str] = Field(None, description="策略本体标识（strategy_registry.strategy_id）")
    model_id: str = Field(..., description="策略模型 ID")
    config_version_id: Optional[str] = Field(None, description="本次运行对应的配置版本（strategy_versions.version_id）")
    backtest_record_id: Optional[str] = Field(None, description="对应 backtest_records._id 字符串")
    pool_hash: Optional[str] = Field(None, description="资产池指纹")
    contract_hash: Optional[str] = Field(None, description="数据契约指纹")
    data_digest: Optional[str] = Field(None, description="行情矩阵摘要（data_digest_v2）")
    config_fingerprint: Optional[str] = Field(None, description="配置指纹（发布快照）")
    reproducibility_fingerprint: Optional[str] = Field(None, description="可复现性指纹")
    engine_version: Optional[str] = Field(None, description="写入时的引擎版本（settings.APP_VERSION）")
    window: Dict[str, Optional[str]] = Field(
        default_factory=lambda: {"start": None, "end": None},
        description="运行窗口 {start: YYYY-MM-DD, end: YYYY-MM-DD}",
    )
    metrics: Dict[str, Optional[float]] = Field(
        default_factory=dict, description="8 项指标白名单（缺失项不写键）"
    )
    status: str = Field("success", description="success / failed")
    created_at: datetime = Field(default_factory=datetime.now)
    schema_version: int = Field(1, description="文档 schema 版本")

    class Config:
        populate_by_name = True
        protected_namespaces = ()
