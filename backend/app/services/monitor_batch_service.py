# -*- coding: utf-8 -*-
"""监控运行批次服务 —— 批次生命周期与批次解析的唯一入口.

设计要点（计算与展示分离）：
    - **批次是一次运行的边界**：``batch_id`` 串联该次运行的状态文档、净值曲线
      （``backtest_records`` 中 ``run_kind=monitor``）、日报、操作指令、风险预警、
      绩效缓存。所有落库点都必须带 ``batch_id``，禁止写"无主"产物。
    - **展示只认 completed**：:func:`resolve_batch` 不传 ``batch_id`` 时取最新
      ``completed`` 批次；跑批进行中/失败/中断对展示不可见，页面自动回落上一个
      completed 批次，既不空窗也不会读到半成品。
    - **配置在创建时固化**：``config_snapshot`` 一次性写入参数/版本/成交口径/资产池，
      运行期间不回读策略库，因此事后可完整重现本次跑批的输入。
    - **主观指令继承（方案 A）**：:func:`inherit_pending_overrides` 把父批次
      ``pending`` 的主观调仓单复制到新批次，已执行的随旧批次封存归档。

本模块只读写 ``monitor_batches`` 与 ``subjective_overrides``（继承用），
不做任何净值/绩效计算 —— 计算侧在 :mod:`app.services.monitor_service`。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.config.collections import (
    COL_MONITOR_BATCHES,
    COL_MONITOR_STATES,
    COL_SUBJECTIVE_OVERRIDES,
)
from app.config.database import Database
from app.models.monitor import (
    LEGACY_BATCH_ID,
    BatchKind,
    BatchRunMode,
    BatchStatus,
    MonitorBatch,
    OverrideStatus,
)

__all__ = [
    "new_batch_id",
    "create_batch",
    "attach_task",
    "mark_running",
    "mark_completed",
    "mark_paused",
    "mark_failed",
    "mark_interrupted",
    "get_batch",
    "resolve_batch",
    "resolve_batch_id",
    "detect_source",
    "list_batches",
    "soft_delete_batch",
    "build_metrics",
    "inherit_pending_overrides",
    "ensure_legacy_batches",
    "mark_stale_running_interrupted",
    "normalize_batch_id",
    "batch_summary",
    "compare_view",
]

# 失败信息里的 traceback 截尾长度，与 monitor_task_service 保持一致
TRACEBACK_LIMIT = 4000

_index_lock = asyncio.Lock()
_index_ready = False

# 计入"调仓次数"的事件类型（event_log 里的 type / event_type 取值）
_REBALANCE_EVENT_TYPES = frozenset({
    "monthly", "monthly_rebalance", "vol_reset", "subjective",
})


def _collection():
    db = Database.get_database()
    if db is None:
        raise RuntimeError("数据库未连接，无法读写监控批次")
    return db[COL_MONITOR_BATCHES]


async def _ensure_indexes() -> None:
    """惰性补索引：保证 (实例, 批次号) 唯一约束在脚本/测试环境同样生效.

    启动引导（``index_bootstrap.ensure_all_indexes``）已按 ``index_specs`` 建齐，
    这里只兜住"不经过 lifespan 直接调服务"的场景，重复调用是 no-op。

    唯一键必须是 ``{monitor_id, batch_id}`` 而非 ``{batch_id}``：存量兼容的
    legacy 哨兵批次按实例各一条、``batch_id`` 同为 ``legacy``，单键唯一会
    让第二个实例的补录全部 E11000 失败。
    """
    global _index_ready
    if _index_ready:
        return
    async with _index_lock:
        if _index_ready:
            return
        coll = _collection()
        await coll.create_index(
            [("monitor_id", 1), ("batch_id", 1)],
            unique=True,
            name="monitor_batch_unique",
            background=True,
        )
        await coll.create_index(
            [("monitor_id", 1), ("status", 1), ("created_at", -1)],
            name="monitor_status_created",
            background=True,
        )
        await coll.create_index(
            [("monitor_id", 1), ("created_at", -1)], name="monitor_created", background=True
        )
        _index_ready = True


def normalize_batch_id(batch_id: Optional[str]) -> str:
    """批次号归一：None/空串一律落到 ``legacy``（存量文档的批次号）."""
    text = str(batch_id or "").strip()
    return text or LEGACY_BATCH_ID


def new_batch_id() -> str:
    """生成全局唯一批次号（与 data_hub_service 的批次号同形）."""
    return uuid.uuid4().hex


def _doc_out(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """出参归一：ObjectId 转 str，批次号缺失补 legacy."""
    if not doc:
        return None
    out = dict(doc)
    if out.get("_id") is not None:
        out["_id"] = str(out["_id"])
    out["batch_id"] = normalize_batch_id(out.get("batch_id"))
    return out


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------

async def create_batch(
    monitor_id: str,
    kind: str = BatchKind.STRATEGY.value,
    run_mode: str = BatchRunMode.INIT.value,
    *,
    task_id: Optional[str] = None,
    source_model_id: Optional[str] = None,
    researcher_code: Optional[str] = None,
    parent_batch_id: Optional[str] = None,
    start_date: Optional[str] = None,
    data_date: Optional[str] = None,
    config_snapshot: Optional[Dict[str, Any]] = None,
    status: str = BatchStatus.PENDING.value,
) -> Dict[str, Any]:
    """创建一个新批次并落库，返回批次文档（含 ``batch_id``）.

    ``config_snapshot`` 必须在此刻传全：批次创建后运行期间不再回读策略库，
    快照缺项就意味着这次跑批的输入不可重现。
    """
    await _ensure_indexes()
    batch = MonitorBatch(
        batch_id=new_batch_id(),
        monitor_id=monitor_id,
        kind=kind,
        run_mode=run_mode,
        status=status,
        task_id=task_id,
        source_model_id=source_model_id,
        researcher_code=researcher_code,
        parent_batch_id=parent_batch_id,
        start_date=start_date,
        data_date=data_date,
        config_snapshot=dict(config_snapshot or {}),
        created_at=datetime.now(),
        started_at=datetime.now() if status == BatchStatus.RUNNING.value else None,
    )
    doc = batch.to_dict()
    await _collection().insert_one(doc)
    logger.info(
        "[监控批次] 创建 batch_id={} monitor_id={} kind={} run_mode={} status={} parent={}",
        batch.batch_id, monitor_id, kind, run_mode, status, parent_batch_id or "-",
    )
    return _doc_out(doc) or {}


async def attach_task(batch_id: str, task_id: str) -> None:
    """把后台任务号挂到批次上（先建批次再建任务时用）."""
    await _collection().update_one(
        {"batch_id": batch_id}, {"$set": {"task_id": task_id}}
    )


async def _set_status(batch_id: str, payload: Dict[str, Any]) -> None:
    await _collection().update_one({"batch_id": batch_id}, {"$set": payload})


async def mark_running(batch_id: str, *, started_at: Optional[datetime] = None) -> None:
    """置为计算中."""
    await _set_status(batch_id, {
        "status": BatchStatus.RUNNING.value,
        "started_at": started_at or datetime.now(),
    })


async def mark_completed(
    batch_id: str,
    *,
    end_date: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    backtest_record_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    data_date: Optional[str] = None,
    config_snapshot: Optional[Dict[str, Any]] = None,
) -> None:
    """置为完成 —— 只有这一步之后，批次才对展示端点可见."""
    payload: Dict[str, Any] = {
        "status": BatchStatus.COMPLETED.value,
        "finished_at": datetime.now(),
    }
    if end_date is not None:
        payload["end_date"] = end_date
    if metrics is not None:
        payload["metrics"] = metrics
    if backtest_record_id is not None:
        payload["backtest_record_id"] = str(backtest_record_id)
    if duration_ms is not None:
        payload["duration_ms"] = int(duration_ms)
    if data_date is not None:
        payload["data_date"] = data_date
    if config_snapshot is not None:
        payload["config_snapshot"] = config_snapshot
    await _set_status(batch_id, payload)
    logger.info("[监控批次] 完成 batch_id={} end_date={} 耗时={}ms",
                batch_id, end_date or "-", duration_ms)


async def mark_paused(
    batch_id: str,
    *,
    end_date: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    next_date: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """置为暂停（主观预设步进：跑完某调仓日后停住，仍有更晚交易日待推演）.

    暂停批次对展示不可见（未 completed），页面回落到上一个 completed 批次；
    续跑时以本批次为 ``parent_batch_id`` 开新批次。
    """
    merged: Dict[str, Any] = dict(metrics or {})
    if next_date is not None:
        merged["next_preset_date"] = next_date
    payload: Dict[str, Any] = {
        "status": BatchStatus.PAUSED.value,
        "finished_at": datetime.now(),
    }
    if end_date is not None:
        payload["end_date"] = end_date
    if merged:
        payload["metrics"] = merged
    if duration_ms is not None:
        payload["duration_ms"] = int(duration_ms)
    await _set_status(batch_id, payload)


async def mark_failed(batch_id: str, error: Any) -> None:
    """置为失败并记录错误（traceback 截尾，避免超长文档）."""
    await _set_status(batch_id, {
        "status": BatchStatus.FAILED.value,
        "finished_at": datetime.now(),
        "error": _error_payload(error),
    })
    logger.warning("[监控批次] 失败 batch_id={} error={}", batch_id, _error_message(error))


async def mark_interrupted(batch_id: str, *, reason: str = "进程重启导致中断") -> None:
    """置为中断（启动时清理上一次未收尾的批次）."""
    await _set_status(batch_id, {
        "status": BatchStatus.INTERRUPTED.value,
        "finished_at": datetime.now(),
        "error": {"message": reason, "traceback": ""},
    })


def _error_message(error: Any) -> str:
    if isinstance(error, dict):
        return str(error.get("message") or "")
    return str(error)


def _error_payload(error: Any) -> Dict[str, Any]:
    """把异常/字符串/字典统一成 ``{message, traceback}``."""
    if isinstance(error, dict):
        return {
            "message": str(error.get("message") or ""),
            "traceback": str(error.get("traceback") or "")[:TRACEBACK_LIMIT],
        }
    if isinstance(error, BaseException):
        import traceback as _tb
        return {
            "message": f"{type(error).__name__}: {error}",
            "traceback": _tb.format_exc()[:TRACEBACK_LIMIT],
        }
    return {"message": str(error), "traceback": ""}


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

async def get_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    """按批次号直查（不过滤状态，批次详情/删除端点用）."""
    if not batch_id:
        return None
    return _doc_out(await _collection().find_one({"batch_id": batch_id}))


async def resolve_batch(
    monitor_id: str, batch_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """解析展示应读的批次.

    规则（展示接口唯一入口，不得在别处另写查询）：
        - ``batch_id`` 为空 → 取该实例最新 ``completed`` 且未软删的批次；
        - ``batch_id`` 指定 → 命中该批次，但同样要求 ``completed``；
          非 completed 的批次对展示不可见（半成品数据不得渲染）；
        - 无可用批次 → 返回 None，展示端点据此回 404 提示"请先运行初始化"。

    ``running``/``failed``/``interrupted``/``paused`` 的批次不会让页面空窗：
    不传 ``batch_id`` 时自动落到上一个 completed 批次。
    """
    coll = _collection()
    query: Dict[str, Any] = {
        "monitor_id": monitor_id,
        "status": BatchStatus.COMPLETED.value,
        "deleted": {"$ne": True},
    }
    if batch_id:
        query["batch_id"] = batch_id
        return _doc_out(await coll.find_one(query))
    doc = await coll.find_one(query, sort=[("created_at", -1)])
    return _doc_out(doc)


async def resolve_batch_id(monitor_id: str, batch_id: Optional[str] = None) -> Optional[str]:
    """:func:`resolve_batch` 的轻量版，只要批次号."""
    doc = await resolve_batch(monitor_id, batch_id)
    return (doc or {}).get("batch_id")


async def detect_source(monitor_id: str) -> Dict[str, Optional[str]]:
    """判定监控对象的类型与来源标识（建批次前的唯一口径）.

    Returns:
        ``{"kind": ..., "source_model_id": ..., "researcher_code": ...}``

    映射口径与 :func:`_resolve_kinds` 一致（``monitored_strategies.source_type``）：
        - ``researcher``      → kind=researcher，researcher_code=source_ref
        - ``portfolio``       → kind=portfolio，source_model_id=source_ref
        - ``system_strategy`` → kind=strategy，source_model_id=source_ref

    未登记（或 ``monitor_id`` 非 ObjectId 形态，如早期 ``default``）时按 strategy
    处理；``monitor_id`` 本身就是模型 ID 时直接当作 ``source_model_id``。
    查询异常不抛出，降级为 strategy（建批次不得因为台账缺失而失败）。
    """
    from bson import ObjectId

    out: Dict[str, Optional[str]] = {
        "kind": BatchKind.STRATEGY.value,
        "source_model_id": monitor_id if ObjectId.is_valid(str(monitor_id)) else None,
        "researcher_code": None,
    }
    if not ObjectId.is_valid(str(monitor_id)):
        return out
    try:
        from app.config.collections import COL_MONITORED_STRATEGIES

        db = Database.get_database()
        if db is None:
            return out
        doc = await db[COL_MONITORED_STRATEGIES].find_one(
            {"_id": ObjectId(str(monitor_id))},
            projection={"source_type": 1, "source_ref": 1},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[监控批次] 监控对象类型判定失败，按 strategy 处理: {}", exc)
        return out
    if not doc:
        return out

    source_type = str(doc.get("source_type") or "")
    source_ref = str(doc.get("source_ref") or "") or None
    if source_type == "researcher":
        out["kind"] = BatchKind.RESEARCHER.value
        out["source_model_id"] = None
        out["researcher_code"] = source_ref
    elif source_type == "portfolio":
        out["kind"] = BatchKind.PORTFOLIO.value
        out["source_model_id"] = source_ref
    else:
        out["kind"] = BatchKind.STRATEGY.value
        out["source_model_id"] = source_ref or out["source_model_id"]
    return out


async def list_batches(
    monitor_id: str,
    limit: int = 20,
    skip: int = 0,
    *,
    status: Optional[str] = None,
    include_deleted: bool = False,
) -> List[Dict[str, Any]]:
    """列出某实例的批次（按创建时间倒序），供批次历史页使用."""
    query: Dict[str, Any] = {"monitor_id": monitor_id}
    if status:
        query["status"] = status
    if not include_deleted:
        query["deleted"] = {"$ne": True}
    cursor = (
        _collection().find(query).sort("created_at", -1).skip(max(0, skip)).limit(max(1, limit))
    )
    return [item for item in (_doc_out(doc) for doc in await cursor.to_list(length=None)) if item]


async def soft_delete_batch(batch_id: str) -> bool:
    """软删除批次：只置 ``deleted=True``，产物文档全部保留（审计可回溯）."""
    res = await _collection().update_one(
        {"batch_id": batch_id, "deleted": {"$ne": True}},
        {"$set": {"deleted": True, "finished_at": datetime.now()}},
    )
    return bool(res.modified_count)


# ---------------------------------------------------------------------------
# 批次摘要指标
# ---------------------------------------------------------------------------

def build_metrics(
    state_doc: Optional[Dict[str, Any]],
    performance: Optional[Dict[str, Any]] = None,
    *,
    rebalance_count: Optional[int] = None,
    subjective_override_count: Optional[int] = None,
) -> Dict[str, Any]:
    """从状态文档 + 绩效结果组装批次摘要指标（只搬运，不重算）.

    Args:
        state_doc: ``monitor_states`` 文档（或其 dict 形式）。
        performance: 计算侧已有的绩效结果（reporter / 组合管线 performance）。
        rebalance_count: 调仓次数；不传时按 ``event_log`` 里的调仓类事件推算。
        subjective_override_count: 本批次纳入实际轨的主观指令条数。
    """
    state_doc = state_doc or {}
    performance = performance or {}

    def _num(key: str, src: Dict[str, Any]) -> Optional[float]:
        value = src.get(key)
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    if rebalance_count is None:
        rebalance_count = _count_rebalance_events(state_doc.get("event_log") or [])

    metrics: Dict[str, Any] = {
        "nav": _num("nav", state_doc),
        "day_count": int(state_doc.get("day_count") or 0),
        "rebalance_count": int(rebalance_count),
        "vol_reset_count": int(state_doc.get("vol_reset_count") or 0),
        "total_trading_cost": _num("total_trading_cost", state_doc),
        "total_return": _num("total_return", performance),
        "annual_return": _num("annual_return", performance),
        "annual_volatility": _num("annual_volatility", performance),
        "sharpe_ratio": _num("sharpe_ratio", performance),
        "max_drawdown": _num("max_drawdown", performance),
    }
    if subjective_override_count is not None:
        metrics["subjective_override_count"] = int(subjective_override_count)
    return {k: v for k, v in metrics.items() if v is not None}


def _count_rebalance_events(event_log: Any) -> int:
    """按事件日志推算调仓次数（口径：调仓类事件的 execute 阶段）."""
    if not isinstance(event_log, list):
        return 0
    count = 0
    for event in event_log:
        if not isinstance(event, dict):
            continue
        etype = str(event.get("type") or event.get("event_type") or "")
        if etype not in _REBALANCE_EVENT_TYPES:
            continue
        stage = str(event.get("stage") or "execute")
        if stage == "execute":
            count += 1
    return count


# ---------------------------------------------------------------------------
# 主观指令继承（方案 A）
# ---------------------------------------------------------------------------

async def inherit_pending_overrides(
    monitor_id: str, source_batch_id: Optional[str], target_batch_id: str
) -> int:
    """把父批次 ``pending`` 的主观调仓单复制到新批次，返回复制条数.

    方案 A 语义：
        - **只继承 pending**：``executed``/``cancelled`` 的指令留在源批次，
          随旧批次封存归档，历史视图保持完整；
        - **复制而非移动**：源批次文档不改写，回看旧批次时当时的挂单状态原样可见；
        - **换新 override_id**：``cancel_subjective_override`` / ``_mark_override_executed``
          都按 ``override_id`` 单条更新，两批次共用同一 ID 会互相误伤，
          因此新文档重新发号并用 ``inherited_from_override_id`` 保留血缘；
        - **清空 linked_operation_id**：被挂接的原指令属于源批次，新批次的操作指令
          会重新生成，保留旧 ID 会指向不存在的文档；实际轨按 ``execute_date``
          对齐生效（见 ``portfolio_dual_track._collect_effective_overrides``），
          不依赖该字段；
        - **保留 created_at**：同一执行日多条指令时按 created_at 取最新，
          保留原值才能让继承后的优先级与继承前一致。

    幂等：目标批次已存在同 ``inherited_from_override_id`` 的文档时跳过，
    重跑不会复制出两份。
    """
    if not source_batch_id or not target_batch_id:
        return 0
    if normalize_batch_id(source_batch_id) == normalize_batch_id(target_batch_id):
        return 0

    db = Database.get_database()
    if db is None:
        raise RuntimeError("数据库未连接，无法继承主观调仓指令")
    coll = db[COL_SUBJECTIVE_OVERRIDES]

    source_docs = await coll.find({
        "monitor_id": monitor_id,
        "batch_id": normalize_batch_id(source_batch_id),
        "status": OverrideStatus.PENDING.value,
    }).to_list(length=None)
    if not source_docs:
        return 0

    existed = await coll.find({
        "monitor_id": monitor_id,
        "batch_id": target_batch_id,
        "inherited_from_override_id": {
            "$in": [str(d.get("override_id")) for d in source_docs if d.get("override_id")]
        },
    }).to_list(length=None)
    existed_refs = {str(d.get("inherited_from_override_id")) for d in existed}

    copied = 0
    ref_map: Dict[str, str] = {}
    for doc in source_docs:
        source_id = str(doc.get("override_id") or "")
        if not source_id or source_id in existed_refs:
            continue
        execute_date = str(doc.get("execute_date") or "")[:10]
        new_id = f"sub_{execute_date.replace('-', '')}_{uuid.uuid4().hex[:8]}"
        new_doc = {
            "override_id": new_id,
            "monitor_id": monitor_id,
            "batch_id": target_batch_id,
            "inherited_from_batch_id": normalize_batch_id(source_batch_id),
            "inherited_from_override_id": source_id,
            "weights": dict(doc.get("weights") or {}),
            "execute_date": execute_date,
            "status": OverrideStatus.PENDING.value,
            "description": doc.get("description"),
            "linked_operation_id": None,
            "created_at": doc.get("created_at") or datetime.now(),
            "inherited_at": datetime.now(),
            "executed_at": None,
        }
        await coll.insert_one(new_doc)
        ref_map[source_id] = new_id
        copied += 1

    if copied:
        logger.info(
            "[监控批次] 继承 pending 主观指令 {} 条: monitor_id={} {} → {}",
            copied, monitor_id, source_batch_id, target_batch_id,
        )

    # 操作面板同步继承：指令重新发号后，对应的 monitor_operations 也要跟到新批次，
    # 否则新批次执行主观调仓时 mark_override_executed 找不到文档。失败不阻断跑批。
    if ref_map:
        try:
            from app.services.monitor_operation_service import MonitorOperationService
            await MonitorOperationService().copy_subjective_for_batch(
                monitor_id, normalize_batch_id(source_batch_id), target_batch_id, ref_map
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[监控批次] 主观操作指令继承失败（不影响跑批）: {exc}")
    return copied


# ---------------------------------------------------------------------------
# 存量兼容（替代独立迁移脚本）
# ---------------------------------------------------------------------------

async def ensure_legacy_batches() -> Dict[str, Any]:
    """为存量 ``monitor_states`` 文档补一条 ``batch_id="legacy"`` 的 completed 批次.

    ``index_bootstrap`` 已把存量文档的 ``batch_id`` 补成 ``legacy``，但没有批次记录
    的话 :func:`resolve_batch` 会返回 None，存量监控页会全部 404。这里在启动时补齐，
    幂等且不重写已有批次（只插缺失的），因此每次启动都可以安全调用。

    Returns:
        ``{"scanned": n, "created": n, "skipped": n}``。
    """
    db = Database.get_database()
    if db is None:
        return {"scanned": 0, "created": 0, "skipped": 0}

    await _ensure_indexes()
    states = await db[COL_MONITOR_STATES].find(
        {"batch_id": LEGACY_BATCH_ID},
        projection={
            "monitor_id": 1, "batch_id": 1, "date": 1, "nav": 1, "day_count": 1,
            "nav_history": 1, "strategy_model_id": 1, "sub_strategy_performance": 1,
            "vol_reset_count": 1, "total_trading_cost": 1, "event_log": 1,
            "created_at": 1, "updated_at": 1, "execution_policy": 1,
            "config_versions": 1,
        },
    ).to_list(length=None)
    if not states:
        return {"scanned": 0, "created": 0, "skipped": 0}

    monitor_ids = [str(s.get("monitor_id")) for s in states if s.get("monitor_id")]
    existed = await _collection().find(
        {"monitor_id": {"$in": monitor_ids}, "batch_id": LEGACY_BATCH_ID},
        projection={"monitor_id": 1},
    ).to_list(length=None)
    existed_ids = {str(d.get("monitor_id")) for d in existed}

    kinds = await _resolve_kinds(monitor_ids)
    created = 0
    for state in states:
        monitor_id = str(state.get("monitor_id") or "")
        if not monitor_id or monitor_id in existed_ids:
            continue
        kind = kinds.get(monitor_id) or (
            BatchKind.PORTFOLIO.value if state.get("sub_strategy_performance")
            else BatchKind.STRATEGY.value
        )
        nav_history = state.get("nav_history") or []
        start_date = str(nav_history[0].get("date"))[:10] if nav_history else None
        batch = MonitorBatch(
            batch_id=LEGACY_BATCH_ID,
            monitor_id=monitor_id,
            kind=kind,
            run_mode=BatchRunMode.INIT.value,
            status=BatchStatus.COMPLETED.value,
            start_date=start_date,
            end_date=str(state.get("date") or "")[:10] or None,
            config_snapshot={
                "config_versions": state.get("config_versions"),
                "execution_policy": state.get("execution_policy"),
                "origin": "legacy_backfill",
            },
            metrics=build_metrics(state, rebalance_count=None),
            created_at=state.get("created_at") or datetime.now(),
            started_at=state.get("created_at"),
            finished_at=state.get("updated_at") or state.get("created_at"),
        )
        try:
            await _collection().insert_one(batch.to_dict())
            created += 1
        except Exception as exc:  # 并发启动/重复插入：已存在即视为成功
            logger.warning("[监控批次] legacy 批次补录失败 monitor_id={}: {}", monitor_id, exc)
    logger.info(
        "[监控批次] 存量 legacy 批次核对完成: 状态文档={} 新建={}", len(states), created
    )
    return {"scanned": len(states), "created": created, "skipped": len(existed_ids)}


async def _resolve_kinds(monitor_ids: List[str]) -> Dict[str, str]:
    """按 ``monitored_strategies.source_type`` 判定存量实例的监控对象类型.

    ``monitored_strategies`` 以 ``_id``(ObjectId) 为主键，monitor_id 就是它的字符串形式；
    非 ObjectId 形态的 monitor_id（如早期 'default'）查不到，归为 strategy。
    """
    kinds: Dict[str, str] = {}
    if not monitor_ids:
        return kinds
    try:
        from bson import ObjectId

        from app.config.collections import COL_MONITORED_STRATEGIES
        db = Database.get_database()
        if db is None:
            return kinds
        oid_map: Dict[str, str] = {}
        for mid in monitor_ids:
            if ObjectId.is_valid(mid):
                oid_map[str(ObjectId(mid))] = mid
        if not oid_map:
            return kinds
        docs = await db[COL_MONITORED_STRATEGIES].find(
            {"_id": {"$in": [ObjectId(k) for k in oid_map]}},
            projection={"source_type": 1},
        ).to_list(length=None)
        mapping = {
            "researcher": BatchKind.RESEARCHER.value,
            "portfolio": BatchKind.PORTFOLIO.value,
            "system_strategy": BatchKind.STRATEGY.value,
        }
        for doc in docs:
            key = oid_map.get(str(doc.get("_id")))
            if key:
                kinds[key] = mapping.get(str(doc.get("source_type")), BatchKind.STRATEGY.value)
    except Exception as exc:
        logger.warning("[监控批次] 存量实例类型判定失败，按 strategy 处理: {}", exc)
    return kinds


# ---------------------------------------------------------------------------
# 中断批次清理
# ---------------------------------------------------------------------------

async def mark_stale_running_interrupted(*, before: Optional[datetime] = None) -> List[str]:
    """把仍处于 pending/running 的历史批次置为 interrupted（进程重启后调用）.

    与 ``monitor_task_service.mark_stale_interrupted`` 配套：任务表标中断的同时，
    批次表也必须离开 running，否则批次永远停在"计算中"且对展示不可见。
    """
    query: Dict[str, Any] = {
        "status": {"$in": [BatchStatus.PENDING.value, BatchStatus.RUNNING.value]}
    }
    if before is not None:
        query["created_at"] = {"$lt": before}
    coll = _collection()
    docs = await coll.find(query, projection={"batch_id": 1}).to_list(length=None)
    batch_ids = [str(d.get("batch_id")) for d in docs if d.get("batch_id")]
    if not batch_ids:
        return []
    await coll.update_many(
        {"batch_id": {"$in": batch_ids}},
        {"$set": {
            "status": BatchStatus.INTERRUPTED.value,
            "finished_at": datetime.now(),
            "error": {"message": "进程重启导致中断，请重新运行", "traceback": ""},
        }},
    )
    logger.warning("[监控批次] {} 个未完成批次已置为 interrupted: {}",
                   len(batch_ids), ", ".join(batch_ids[:10]))
    return batch_ids


def batch_summary(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """批次列表/详情的对外视图：去掉内部字段，时间统一 ISO 字符串."""
    if not doc:
        return {}
    out: Dict[str, Any] = {}
    for key in (
        "batch_id", "monitor_id", "kind", "run_mode", "status", "task_id",
        "source_model_id", "researcher_code", "parent_batch_id", "backtest_record_id",
        "start_date", "end_date", "data_date", "metrics", "deleted", "error",
    ):
        if key in doc:
            out[key] = doc.get(key)
    for key in ("created_at", "started_at", "finished_at"):
        value = doc.get(key)
        out[key] = value.isoformat() if isinstance(value, datetime) else value
    out["duration_ms"] = doc.get("duration_ms")
    snapshot = doc.get("config_snapshot") or {}
    out["config_snapshot"] = {
        k: snapshot.get(k)
        for k in ("template_code", "config_versions", "execution_policy", "asset_codes", "sub_strategies")
        if snapshot.get(k) is not None
    }
    return out


def compare_view(docs: Tuple[Optional[Dict[str, Any]], ...]) -> List[Dict[str, Any]]:
    """批次对比视图：只出摘要与净值曲线所需字段，曲线由调用方按批次号另取."""
    return [batch_summary(doc) for doc in docs if doc]
