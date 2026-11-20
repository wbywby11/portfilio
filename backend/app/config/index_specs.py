# -*- coding: utf-8 -*-
"""索引声明式注册表 —— 一处声明、启动时按需补齐.

与 ``collections.py`` 的分工：那里只放集合名常量，这里只放索引规格。
服务层不直接调 ``create_index``，统一由 :mod:`app.services.index_bootstrap`
在启动引导里对比 ``list_indexes()`` 后补齐缺失项，避免多 worker 并发建索引
与「每次启动都重建」的重复开销。

``unique`` 语义：
    - 唯一键（strategy_id / manifest_key / (model_id, version_no) 等）用 unique=True，
      靠数据库拒绝重复而不是靠调用方自查；
    - 查询型索引（model_id + created_at desc 等）用 unique=False。

``background`` 一律 True：大集合上建索引不得阻塞读写；超大集合仍建议走
``scripts/`` 离线执行（启动引导只补缺失，不重建）。

``LEGACY_INDEX_DROPS``：已废弃的旧索引声明。引导器只增不删，因此索引语义变更
（如唯一键从 ``{monitor_id}`` 改为 ``{monitor_id, batch_id}``）必须把旧索引显式
登记到这里，由引导器在建完新索引后删除；否则旧唯一索引会残留并拒绝新文档。

``LEGACY_BATCH_BACKFILL``：批次化改造涉及的存量集合。引导器在建索引之前，把
这些集合里 ``batch_id`` 缺失/为 null 的文档统一补 ``"legacy"``，由一次性标记位
守护，不重复扫描（见 :mod:`app.services.index_bootstrap`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Tuple

from pymongo import ASCENDING, DESCENDING

from app.config.collections import (
    COL_ASSET_UNIVERSE_VERSIONS,
    COL_BACKTEST_RECORDS,
    COL_LINEAGE_EDGES,
    COL_LINEAGE_NODES,
    COL_MONITOR_BATCHES,
    COL_MONITOR_DAILY_REPORTS,
    COL_MONITOR_OPERATIONS,
    COL_MONITOR_OPERATION_REMARKS,
    COL_MONITOR_PERFORMANCE_CACHE,
    COL_MONITOR_RISK_ALERTS,
    COL_MONITOR_STATES,
    COL_MONITOR_TASKS,
    COL_STRATEGY_LIFECYCLE_EVENTS,
    COL_STRATEGY_MODELS,
    COL_STRATEGY_PARAM_VERSIONS,
    COL_STRATEGY_REGISTRY,
    COL_STRATEGY_RESOLUTION_EVENTS,
    COL_STRATEGY_RUNS,
    COL_STRATEGY_VERSIONS,
    COL_SUBJECTIVE_OVERRIDES,
)

__all__ = [
    "IndexSpec",
    "INDEX_SPECS",
    "specs_by_collection",
    "LegacyIndexDrop",
    "LEGACY_INDEX_DROPS",
    "LEGACY_BATCH_BACKFILL",
    "LEGACY_BATCH_ID",
]


@dataclass(frozen=True)
class IndexSpec:
    """单条索引声明.

    Attributes:
        collection: 集合名（必须来自 ``app.config.collections`` 常量）。
        keys: 键与方向的有序元组，如 ``(("model_id", 1), ("created_at", -1))``。
        unique: 是否唯一索引。
        name: 显式索引名，避免驱动按默认规则生成导致同名不同键的冲突。
        partial_filter: 部分索引过滤表达式（如仅约束活跃文档）。
    """

    collection: str
    keys: Tuple[Tuple[str, int], ...]
    unique: bool = False
    name: str = ""
    partial_filter: Any = None
    _extra: dict = field(default_factory=dict, repr=False)

    @property
    def index_name(self) -> str:
        """显式名缺省时按「字段_方向」生成，与 pymongo 默认规则同形."""
        if self.name:
            return self.name
        return "_".join(f"{k}_{d}" for k, d in self.keys)


@dataclass(frozen=True)
class LegacyIndexDrop:
    """已废弃、需在启动引导时删除的旧索引声明.

    删除按 ``keys`` 签名匹配而不是按名字匹配：存量库里的索引名可能是 pymongo
    默认生成的，也可能被人工改过；只有「键形态与唯一性都对得上」才删，
    避免误删同名的其它索引。
    """

    collection: str
    keys: Tuple[Tuple[str, int], ...]
    unique: bool = False
    reason: str = ""


# 批次化前存量文档没有 batch_id，统一补这个哨兵值；
# resolve_batch(monitor_id, "legacy") 可显式命中存量数据。
LEGACY_BATCH_ID = "legacy"

# 批次化涉及的存量集合：启动引导一次性把 batch_id 补齐为 LEGACY_BATCH_ID。
# 不含 backtest_records —— 那里 run_kind 缺失即视为 backtest，不需要批次号。
LEGACY_BATCH_BACKFILL: Tuple[str, ...] = (
    COL_MONITOR_STATES,
    COL_MONITOR_DAILY_REPORTS,
    COL_MONITOR_OPERATIONS,
    COL_MONITOR_OPERATION_REMARKS,
    COL_MONITOR_PERFORMANCE_CACHE,
    COL_MONITOR_RISK_ALERTS,
    COL_SUBJECTIVE_OVERRIDES,
)

# 已废弃索引：由 index_bootstrap 在补齐新索引后删除。
LEGACY_INDEX_DROPS: List[LegacyIndexDrop] = [
    LegacyIndexDrop(
        COL_MONITOR_STATES,
        (("monitor_id", ASCENDING),),
        unique=True,
        reason="批次化后一个 monitor_id 对应多条状态文档，唯一键改为 {monitor_id, batch_id}",
    ),
    LegacyIndexDrop(
        COL_MONITOR_BATCHES,
        (("batch_id", ASCENDING),),
        unique=True,
        reason=(
            "存量兼容的 legacy 哨兵批次按 monitor_id 各一条、batch_id 同为 'legacy'，"
            "单键唯一索引会拒绝第二个实例，唯一键改为 {monitor_id, batch_id}"
        ),
    ),
]


# ---------------------------------------------------------------------------
# 声明清单
# ---------------------------------------------------------------------------
# 新增集合：先加 collections.py 常量，再在下方追加索引声明；
# 新增查询面：先在对应集合下补索引，再写查询代码（禁止先上查询后补索引）。

INDEX_SPECS: List[IndexSpec] = [
    # ── 策略档案（域 2）──
    IndexSpec(COL_STRATEGY_REGISTRY, (("strategy_id", ASCENDING),), unique=True),
    IndexSpec(COL_STRATEGY_REGISTRY, (("manifest_key", ASCENDING),), unique=True),
    IndexSpec(
        COL_STRATEGY_REGISTRY,
        (("pillar", ASCENDING), ("lifecycle_stage", ASCENDING)),
        name="pillar_lifecycle",
    ),
    IndexSpec(COL_STRATEGY_REGISTRY, (("tags", ASCENDING),), name="tags_multi"),
    # ── 发布版本链（域 2）──
    IndexSpec(
        COL_STRATEGY_VERSIONS,
        (("model_id", ASCENDING), ("version_no", DESCENDING)),
        unique=True,
        name="model_version_unique",
    ),
    IndexSpec(
        COL_STRATEGY_VERSIONS,
        (("strategy_id", ASCENDING), ("created_at", DESCENDING)),
        name="strategy_created",
    ),
    # ── 资产池版本（域 2）──
    IndexSpec(
        COL_ASSET_UNIVERSE_VERSIONS,
        (("universe_id", ASCENDING), ("version", DESCENDING)),
        unique=True,
        name="universe_version_unique",
    ),
    IndexSpec(
        COL_ASSET_UNIVERSE_VERSIONS,
        (("universe_id", ASCENDING), ("effective_from", ASCENDING)),
        name="universe_effective",
    ),
    # ── 治理事件（域 2）──
    IndexSpec(
        COL_STRATEGY_LIFECYCLE_EVENTS,
        (("strategy_id", ASCENDING), ("created_at", DESCENDING)),
        name="strategy_created",
    ),
    IndexSpec(
        COL_STRATEGY_LIFECYCLE_EVENTS,
        (("model_id", ASCENDING), ("created_at", DESCENDING)),
        name="model_created",
    ),
    # ── 运行记录（域 3）──
    IndexSpec(
        COL_STRATEGY_RUNS,
        (("strategy_id", ASCENDING), ("created_at", DESCENDING)),
        name="strategy_created",
    ),
    IndexSpec(
        COL_STRATEGY_RUNS,
        (("model_id", ASCENDING), ("run_kind", ASCENDING), ("created_at", DESCENDING)),
        name="model_kind_created",
    ),
    IndexSpec(
        COL_STRATEGY_RUNS,
        (("backtest_record_id", ASCENDING),),
        name="backtest_record",
    ),
    IndexSpec(
        COL_STRATEGY_RUNS,
        (("config_fingerprint", ASCENDING),),
        name="config_fingerprint",
    ),
    # ── 解析失败观测（域 3）──
    IndexSpec(
        COL_STRATEGY_RESOLUTION_EVENTS,
        (("created_at", DESCENDING),),
        name="created_desc",
    ),
    IndexSpec(
        COL_STRATEGY_RESOLUTION_EVENTS,
        (("template_code", ASCENDING), ("created_at", DESCENDING)),
        name="code_created",
    ),
    # ── 治理血缘（S15）：节点确定性 ID，边确定性 edge_id ──
    IndexSpec(COL_LINEAGE_NODES, (("node_id", ASCENDING),), unique=True),
    IndexSpec(COL_LINEAGE_EDGES, (("edge_id", ASCENDING),), unique=True),
    IndexSpec(
        COL_LINEAGE_EDGES,
        (("from_node", ASCENDING), ("created_at", DESCENDING)),
        name="from_created",
    ),
    # ── 存量集合补齐查询索引 ──
    IndexSpec(
        COL_BACKTEST_RECORDS,
        (("model_id", ASCENDING), ("created_at", DESCENDING)),
        name="model_created",
    ),
    # ── 回测记录被监控批次复用（run_kind=monitor）：按批次取曲线、按实例列监控历史 ──
    IndexSpec(
        COL_BACKTEST_RECORDS,
        (("run_kind", ASCENDING), ("batch_id", ASCENDING)),
        name="run_kind_batch",
    ),
    IndexSpec(
        COL_BACKTEST_RECORDS,
        (("monitor_id", ASCENDING), ("created_at", DESCENDING)),
        name="monitor_created",
    ),
    # ── 监控运行批次：一个实例内批次号唯一（真实批次为 uuid，legacy 哨兵按实例各一条）；
    #    按实例取最新 completed 批次；按任务号反查 ──
    IndexSpec(
        COL_MONITOR_BATCHES,
        (("monitor_id", ASCENDING), ("batch_id", ASCENDING)),
        unique=True,
        name="monitor_batch_unique",
    ),
    IndexSpec(
        COL_MONITOR_BATCHES,
        (("monitor_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)),
        name="monitor_status_created",
    ),
    IndexSpec(
        COL_MONITOR_BATCHES,
        (("monitor_id", ASCENDING), ("created_at", DESCENDING)),
        name="monitor_created",
    ),
    IndexSpec(COL_MONITOR_BATCHES, (("task_id", ASCENDING),), name="task_id"),
    # ── 监控状态：一个批次一条文档（旧 {monitor_id} 唯一索引见 LEGACY_INDEX_DROPS）──
    IndexSpec(
        COL_MONITOR_STATES,
        (("monitor_id", ASCENDING), ("batch_id", ASCENDING)),
        unique=True,
        name="monitor_batch_unique",
    ),
    # ── 日报：按批次取区间快照 ──
    IndexSpec(
        COL_MONITOR_DAILY_REPORTS,
        (("monitor_id", ASCENDING), ("batch_id", ASCENDING), ("date", DESCENDING)),
        name="monitor_batch_date",
    ),
    # ── 操作指令：按批次列指令 / 按批次取 pending 指令 ──
    IndexSpec(
        COL_MONITOR_OPERATIONS,
        (("monitor_id", ASCENDING), ("batch_id", ASCENDING), ("status", ASCENDING)),
        name="monitor_batch_status",
    ),
    IndexSpec(COL_MONITOR_OPERATIONS, (("batch_id", ASCENDING),), name="batch_id"),
    # ── 指令备注：业务键含 batch_id，按批次批量取回 ──
    IndexSpec(
        COL_MONITOR_OPERATION_REMARKS,
        (("monitor_id", ASCENDING), ("batch_id", ASCENDING)),
        name="monitor_batch",
    ),
    # ── 绩效缓存：一个批次一份缓存，展示侧只读 ──
    IndexSpec(
        COL_MONITOR_PERFORMANCE_CACHE,
        (("monitor_id", ASCENDING), ("batch_id", ASCENDING)),
        unique=True,
        name="monitor_batch_unique",
    ),
    # ── 主观指令：按批次取 pending（新批次创建时继承未执行指令）──
    IndexSpec(
        COL_SUBJECTIVE_OVERRIDES,
        (("monitor_id", ASCENDING), ("batch_id", ASCENDING), ("status", ASCENDING)),
        name="monitor_batch_status",
    ),
    # ── 风险预警：按监控实例取最新一批 + 按类型/级别筛选 ──
    IndexSpec(
        COL_MONITOR_RISK_ALERTS,
        (("monitor_id", ASCENDING), ("signal_date", DESCENDING)),
        name="monitor_signal_date",
    ),
    IndexSpec(
        COL_MONITOR_RISK_ALERTS,
        (("monitor_id", ASCENDING), ("signal_type", ASCENDING), ("severity", ASCENDING)),
        name="monitor_type_severity",
    ),
    IndexSpec(
        COL_MONITOR_RISK_ALERTS,
        (("monitor_id", ASCENDING), ("batch_id", ASCENDING), ("signal_date", DESCENDING)),
        name="monitor_batch_signal_date",
    ),
    # ── 监控后台任务：任务号唯一；同一实例至多一个活跃任务（partial unique）；历史按时间倒序 ──
    IndexSpec(COL_MONITOR_TASKS, (("task_id", ASCENDING),), unique=True, name="task_id_unique"),
    IndexSpec(
        COL_MONITOR_TASKS,
        (("monitor_id", ASCENDING), ("active", ASCENDING)),
        unique=True,
        name="monitor_active_unique",
        partial_filter={"active": 1},
    ),
    IndexSpec(
        COL_MONITOR_TASKS,
        (("monitor_id", ASCENDING), ("created_at", DESCENDING)),
        name="monitor_created",
    ),
    IndexSpec(
        COL_STRATEGY_MODELS,
        (("status", ASCENDING), ("updated_at", DESCENDING)),
        name="status_updated",
    ),
    IndexSpec(
        COL_STRATEGY_PARAM_VERSIONS,
        (("model_id", ASCENDING), ("version", DESCENDING)),
        name="model_version",
    ),
]


def specs_by_collection() -> "dict[str, List[IndexSpec]]":
    """按集合聚合声明，供引导器逐集合批量比对."""
    grouped: "dict[str, List[IndexSpec]]" = {}
    for spec in INDEX_SPECS:
        grouped.setdefault(spec.collection, []).append(spec)
    return grouped
