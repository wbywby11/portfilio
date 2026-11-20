# -*- coding: utf-8 -*-
"""监控后台任务服务：任务落库、进度更新、启动恢复.

设计要点：
    - 任务状态落 MongoDB（``monitor_tasks``），轮询请求可打到任意 worker；
    - ``active=1`` 的 partial unique 索引保证同一监控实例同时只有一个活跃任务；
    - 任务执行体仍在进程内（``asyncio.create_task``），进程重启后由
      ``mark_stale_interrupted`` 标记为中断，前端提示重新运行；
    - 进度回调失败不得影响跑批主流程（调用方负责吞异常）。

三种跑批入口（init / run / run-range）走同一套任务机制：
    :func:`submit` 先建批次（``status=pending``）再建任务并启动协程，
    端点立即返回 ``{task_id, batch_id, status}``；真正的 ``running`` 由
    ``MonitorService._begin_run_batch`` 接管已有批次时置位，避免两侧重复建批次。

另有一类「纯进度」任务（回测）：端点保持同步返回结果，任务文档只承载进度，
    由调用方显式 :func:`create_task` → :func:`mark_running` → :func:`update_progress`
    → :func:`finish_task` 走完生命周期，不建批次、不进 ``submit``。
"""
from __future__ import annotations

import asyncio
import traceback
import uuid
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, Optional

from loguru import logger
from pymongo.errors import DuplicateKeyError

from app.config.collections import COL_MONITOR_TASKS
from app.config.database import Database
from app.models.monitor import BatchRunMode, BatchStatus

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"

ACTIVE_STATUSES = (STATUS_PENDING, STATUS_RUNNING)
TERMINAL_STATUSES = (STATUS_PAUSED, STATUS_COMPLETED, STATUS_FAILED, STATUS_INTERRUPTED)

#: 任务类型 → 批次运行模式（与 monitor_batches.run_mode 同口径）
TASK_KIND_INIT = "monitor_init"
TASK_KIND_RUN = "monitor_run"
TASK_KIND_RANGE = "monitor_range"

#: 纯进度任务类型：只借任务表上报进度，无批次、无 run_mode，不走 :func:`submit`
TASK_KIND_BACKTEST_SINGLE = "backtest_single"
TASK_KIND_BACKTEST_PORTFOLIO = "backtest_portfolio"

PROGRESS_ONLY_KINDS = frozenset(
    {TASK_KIND_BACKTEST_SINGLE, TASK_KIND_BACKTEST_PORTFOLIO}
)

#: 纯进度任务的 ``monitor_id`` 前缀：避免与真实监控实例抢「单实例单活跃任务」唯一索引
BACKTEST_SUBJECT_PREFIX = "backtest::"

RUN_MODE_BY_KIND: Dict[str, str] = {
    TASK_KIND_INIT: BatchRunMode.INIT.value,
    TASK_KIND_RUN: BatchRunMode.DAILY.value,
    TASK_KIND_RANGE: BatchRunMode.RANGE.value,
}

#: 任务完成提示文案（前端不再根据端点猜任务类型）
DONE_MESSAGE_BY_KIND: Dict[str, str] = {
    TASK_KIND_INIT: "初始化完成",
    TASK_KIND_RUN: "运行完成",
    TASK_KIND_RANGE: "补算完成",
    TASK_KIND_BACKTEST_SINGLE: "回测完成",
    TASK_KIND_BACKTEST_PORTFOLIO: "组合回测完成",
}

#: 外部传入 task_id 的长度上限（前端生成的 uuid hex 为 32 位）
TASK_ID_MAX_LEN = 64

# 任务协程引用：防止 asyncio 垃圾回收导致任务中途消失
_running_tasks: Dict[str, asyncio.Task] = {}
_index_lock = asyncio.Lock()
_index_ready = False


def _collection():
    db = Database.get_database()
    if db is None:
        raise RuntimeError("数据库未连接，无法读写监控任务")
    return db[COL_MONITOR_TASKS]


async def _ensure_indexes() -> None:
    """惰性补索引：保证「单实例单活跃任务」的约束在脚本/测试环境同样生效."""
    global _index_ready
    if _index_ready:
        return
    async with _index_lock:
        if _index_ready:
            return
        coll = _collection()
        try:
            await coll.create_index(
                [("task_id", 1)], unique=True, name="task_id_unique", background=True
            )
            await coll.create_index(
                [("monitor_id", 1), ("active", 1)],
                unique=True,
                name="monitor_active_unique",
                partialFilterExpression={"active": 1},
                background=True,
            )
            await coll.create_index(
                [("monitor_id", 1), ("created_at", -1)],
                name="monitor_created",
                background=True,
            )
        except Exception as exc:  # noqa: BLE001 —— 索引失败不让任务不可用，业务侧仍会复查
            logger.warning(f"[monitor_task] 索引补齐失败: {exc}")
        _index_ready = True


def _json_safe(value: Any) -> Any:
    """转成 BSON 可存的基本类型（numpy 标量、datetime 等）."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:  # noqa: BLE001
            pass
    return value


def _percent(current: Any, total: Any, status: str) -> Optional[float]:
    if status == STATUS_COMPLETED:
        return 100.0
    try:
        cur = int(current or 0)
        tot = int(total or 0)
    except (TypeError, ValueError):
        return None
    if tot <= 0:
        return None
    return round(min(100.0, max(0.0, cur * 100.0 / tot)), 1)


def _public(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in ("_id", "active")}
    status = out.get("status") or STATUS_PENDING
    out["percent"] = _percent(out.get("current"), out.get("total"), status)
    started = out.get("started_at") or out.get("created_at")
    end = out.get("finished_at") or datetime.now()
    try:
        out["elapsed_sec"] = max(0, int((end - started).total_seconds()))
    except (TypeError, AttributeError):
        out["elapsed_sec"] = None
    return out


async def create_task(
    monitor_id: str,
    kind: str = TASK_KIND_INIT,
    *,
    batch_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建跑批任务；同一实例已有活跃任务时抛 ValueError（API 映射 409）.

    Args:
        kind: ``monitor_init`` / ``monitor_run`` / ``monitor_range``，
            或纯进度类型 ``backtest_single`` / ``backtest_portfolio``
        batch_id: 预建的批次号（由 :func:`submit` 传入），写回任务文档供前端关联
        params: 跑批参数（start_date / target_date / from_date / to_date /
            manual_preset_step），原样存下供重启后排查
        task_id: 外部指定的任务号（回测端点用前端传来的 ``progress_key``，
            让调用方发请求前就能开始轮询）；为空则内部生成
    """
    if kind not in RUN_MODE_BY_KIND and kind not in PROGRESS_ONLY_KINDS:
        raise ValueError(f"未知的任务类型: {kind}")
    await _ensure_indexes()
    coll = _collection()
    now = datetime.now()
    payload = dict(params or {})
    doc = {
        "task_id": (task_id or "").strip()[:TASK_ID_MAX_LEN] or uuid.uuid4().hex,
        "monitor_id": monitor_id,
        "kind": kind,
        "batch_id": batch_id,
        "status": STATUS_PENDING,
        "active": 1,
        "params": _json_safe(payload),
        # 兼容旧字段：前端与存量查询仍读顶层 start_date / manual_preset_step
        "start_date": payload.get("start_date"),
        "manual_preset_step": bool(payload.get("manual_preset_step")),
        "phase": "pending",
        "current": 0,
        "total": 0,
        "current_date": None,
        "message": "任务已提交，等待执行",
        "result": None,
        "error": None,
        "created_at": now,
        "started_at": None,
        "updated_at": now,
        "finished_at": None,
    }
    try:
        await coll.insert_one(doc)
    except DuplicateKeyError:
        label = "监控实例" if kind in RUN_MODE_BY_KIND else "任务主体"
        raise ValueError(f"{label} {monitor_id} 已有任务在进行，请等待完成")
    logger.info(
        f"[monitor_task] 创建任务: task_id={doc['task_id']}, kind={kind}, "
        f"monitor_id={monitor_id}, batch_id={batch_id}"
    )
    return _public(doc)


async def create_init_task(
    monitor_id: str,
    start_date: Optional[str],
    manual_preset_step: bool,
    batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建初始化任务（:func:`create_task` 的兼容包装）."""
    return await create_task(
        monitor_id,
        TASK_KIND_INIT,
        batch_id=batch_id,
        params={"start_date": start_date, "manual_preset_step": bool(manual_preset_step)},
    )


async def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    if not task_id:
        return None
    doc = await _collection().find_one({"task_id": task_id})
    return _public(doc) if doc else None


async def get_active_task(monitor_id: str) -> Optional[Dict[str, Any]]:
    if not monitor_id:
        return None
    doc = await _collection().find_one({"monitor_id": monitor_id, "active": 1})
    return _public(doc) if doc else None


async def mark_running(
    task_id: str,
    *,
    phase: str = "preparing",
    message: Optional[str] = None,
) -> None:
    """把任务置 ``running`` 并记下开始时间（``elapsed_sec`` 由此起算）.

    每个任务只应调一次：重复调用会重置 ``started_at``，已用时从头算。
    """
    now = datetime.now()
    patch: Dict[str, Any] = {
        "status": STATUS_RUNNING,
        "started_at": now,
        "updated_at": now,
        "phase": phase,
    }
    if message is not None:
        patch["message"] = message
    await _collection().update_one({"task_id": task_id}, {"$set": patch})


async def update_progress(
    task_id: str,
    *,
    phase: Optional[str] = None,
    current: Optional[int] = None,
    total: Optional[int] = None,
    current_date: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    """写入进度；仅对 pending/running 任务生效，避免收尾回调覆盖终态."""
    patch: Dict[str, Any] = {"updated_at": datetime.now()}
    if phase is not None:
        patch["phase"] = phase
    if current is not None:
        patch["current"] = int(current)
    if total is not None:
        patch["total"] = int(total)
    if current_date is not None:
        patch["current_date"] = current_date
    if message is not None:
        patch["message"] = message
    await _collection().update_one(
        {"task_id": task_id, "status": {"$in": list(ACTIVE_STATUSES)}},
        {"$set": patch},
    )


async def _finish_task(
    task_id: str,
    status: str,
    *,
    result: Any = None,
    error: Any = None,
    message: Optional[str] = None,
) -> None:
    now = datetime.now()
    patch: Dict[str, Any] = {
        "status": status,
        "phase": status,
        "updated_at": now,
        "finished_at": now,
    }
    if result is not None:
        patch["result"] = _json_safe(result)
    if error is not None:
        patch["error"] = _json_safe(error)
    if message is not None:
        patch["message"] = message
    await _collection().update_one(
        {"task_id": task_id},
        {"$set": patch, "$unset": {"active": ""}},
    )


async def finish_task(
    task_id: str,
    status: str = STATUS_COMPLETED,
    *,
    result: Any = None,
    error: Any = None,
    message: Optional[str] = None,
) -> None:
    """任务收尾（:func:`_finish_task` 的对外入口，供纯进度任务复用）.

    写入终态的同时 ``$unset active``，释放「单实例单活跃任务」名额。
    """
    await _finish_task(
        task_id, status, result=result, error=error, message=message
    )


def make_thread_bridge(
    dispatch: Callable[[int, int, int, Optional[str]], Coroutine[Any, Any, None]],
) -> Optional[Callable[[int, int, Any], None]]:
    """构造「引擎工作线程 → 主事件循环」的同步进度桥.

    研究员引擎跑在 ``asyncio.to_thread`` 的工作线程里，不能直接 await 协程，
    因此用 ``run_coroutine_threadsafe`` 把进度调度回主循环；引擎侧已按 1%
    节流，这里再按百分比去重，避免 3000+ 次回调打满任务表。

    Args:
        dispatch: 协程工厂，签名 ``(done, total, pct, date_str)``，
            由调用方自己拼进度文案

    Returns:
        同步回调 ``(done, total, current_date=None)``；非事件循环上下文
        （脚本直调）返回 None 表示不上报。
    """
    if dispatch is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 非事件循环上下文（脚本直调）
        return None
    last = {"pct": -1}

    def _bridge(done: int, total: int, current_date=None) -> None:
        if not total:
            return
        try:
            pct = int(int(done) * 100 / int(total))
        except (TypeError, ValueError, ZeroDivisionError):
            return
        if pct <= last["pct"]:
            return
        last["pct"] = pct
        if hasattr(current_date, "strftime"):
            date_str = current_date.strftime("%Y-%m-%d")
        else:
            date_str = str(current_date) if current_date else None

        async def _safe_dispatch() -> None:
            try:
                await dispatch(int(done), int(total), pct, date_str)
            except Exception as exc:  # noqa: BLE001 —— 进度失败不影响主流程
                logger.warning(f"[task-progress] 进度写入失败: {exc}")

        try:
            asyncio.run_coroutine_threadsafe(_safe_dispatch(), loop)
        except Exception as exc:  # noqa: BLE001 —— 进度失败不影响主流程
            logger.warning(f"[task-progress] 进度调度失败: {exc}")

    return _bridge


def make_engine_progress_bridge(
    task_id: str, *, label: str = "引擎回测"
) -> Optional[Callable[[int, int, Any], None]]:
    """为指定任务构造引擎进度桥：逐日进度直接写任务表.

    回测端点（同步返回）用它把引擎工作线程的进度旁路上报到
    ``monitor_tasks``，前端轮询 ``GET /monitor/tasks/{task_id}`` 即可。
    """
    async def _dispatch(done: int, total: int, pct: int, date_str) -> None:
        await update_progress(
            task_id,
            phase="running",
            current=done,
            total=total,
            current_date=date_str,
            message=f"{label} {pct}%（{done}/{total}）",
        )

    return make_thread_bridge(_dispatch)


async def run_task(
    task_id: str,
    monitor_id: str,
    kind: str = TASK_KIND_INIT,
    params: Optional[Dict[str, Any]] = None,
    batch_id: Optional[str] = None,
) -> None:
    """后台执行跑批（init / run / run-range 共用）；异常写入任务表，不向事件循环冒出.

    ``batch_id`` 非空时直接接管已预建的批次（``_begin_run_batch`` 会把它置 running）；
    为空时由 ``MonitorService`` 自己建批次（同步模式/脚本直调场景）。
    """
    from app.services.monitor_service import MonitorService

    payload = dict(params or {})
    done_message = DONE_MESSAGE_BY_KIND.get(kind, "运行完成")

    await mark_running(
        task_id, phase="preparing", message=f"准备执行（{done_message[:2]}）"
    )
    logger.info(
        f"[monitor_task] 开始执行任务: task_id={task_id}, kind={kind}, "
        f"monitor_id={monitor_id}, batch_id={batch_id}"
    )

    async def _on_progress(**progress) -> None:
        await update_progress(task_id, **progress)

    service = MonitorService()
    common = {
        "manual_preset_step": bool(payload.get("manual_preset_step")),
        "progress_cb": _on_progress,
        "batch_id": batch_id,
        "task_id": task_id,
    }
    try:
        if kind == TASK_KIND_RUN:
            result = await service.run_daily(
                monitor_id,
                payload.get("target_date"),
                replay=bool(payload.get("replay")),
                **common,
            )
        elif kind == TASK_KIND_RANGE:
            result = await service.run_range(
                monitor_id,
                payload.get("from_date"),
                payload.get("to_date"),
                **common,
            )
        else:
            result = await service.run_init(
                monitor_id, start_date=payload.get("start_date"), **common
            )
        if isinstance(result, dict) and result.get("paused"):
            await _finish_task(
                task_id,
                STATUS_PAUSED,
                result=result,
                message=result.get("message") or "已按主观预设调仓日暂停",
            )
            logger.info(
                f"[monitor_task] 任务暂停: task_id={task_id}, date={result.get('date')}"
            )
        else:
            await _finish_task(
                task_id, STATUS_COMPLETED, result=result, message=done_message
            )
            logger.info(
                f"[monitor_task] 任务完成: task_id={task_id}, kind={kind}, result={result}"
            )
    except asyncio.CancelledError:
        await _finish_task(task_id, STATUS_INTERRUPTED, message="任务被取消（服务关闭）")
        raise
    except Exception as exc:  # noqa: BLE001 —— 任务异常必须落到任务表供前端展示
        tb = traceback.format_exc()
        logger.error(f"[monitor_task] 任务失败: task_id={task_id}, kind={kind}, error={exc}\n{tb}")
        await _finish_task(
            task_id,
            STATUS_FAILED,
            error={"message": str(exc), "traceback": tb[-4000:]},
            message=f"{done_message[:2]}失败：{exc}",
        )


async def run_init_task(
    task_id: str,
    monitor_id: str,
    start_date: Optional[str],
    manual_preset_step: bool,
    batch_id: Optional[str] = None,
) -> None:
    """后台执行初始化（:func:`run_task` 的兼容包装）."""
    await run_task(
        task_id,
        monitor_id,
        TASK_KIND_INIT,
        {"start_date": start_date, "manual_preset_step": bool(manual_preset_step)},
        batch_id,
    )


def start_task(
    task_id: str,
    monitor_id: str,
    kind: str = TASK_KIND_INIT,
    params: Optional[Dict[str, Any]] = None,
    batch_id: Optional[str] = None,
) -> None:
    """创建 asyncio 任务并保留引用（同步函数，调用方在事件循环内）."""
    task = asyncio.create_task(
        run_task(task_id, monitor_id, kind, params, batch_id),
        name=f"{kind}-{task_id}",
    )
    _running_tasks[task_id] = task
    task.add_done_callback(lambda _t: _running_tasks.pop(task_id, None))


def start_init_task(
    task_id: str,
    monitor_id: str,
    start_date: Optional[str],
    manual_preset_step: bool,
    batch_id: Optional[str] = None,
) -> None:
    """启动初始化任务（:func:`start_task` 的兼容包装）."""
    start_task(
        task_id,
        monitor_id,
        TASK_KIND_INIT,
        {"start_date": start_date, "manual_preset_step": bool(manual_preset_step)},
        batch_id,
    )


async def submit(
    monitor_id: str,
    kind: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """提交一次异步跑批：预建批次 → 建任务 → 启动协程，立即返回句柄.

    Returns:
        ``{task_id, batch_id, status, kind, monitor_id, params}``，
        ``status`` 固定为 ``pending``，进度由 ``GET /monitor/tasks/{task_id}`` 轮询。

    Raises:
        ValueError: 同一实例已有活跃任务，或批次/任务创建失败（API 映射 409）。
    """
    from app.services import monitor_batch_service

    if await get_active_task(monitor_id):
        raise ValueError(f"监控实例 {monitor_id} 已有任务在进行，请等待完成")

    payload = dict(params or {})
    run_mode = RUN_MODE_BY_KIND.get(kind)
    if run_mode is None:
        raise ValueError(f"未知的监控任务类型: {kind}")

    source = await monitor_batch_service.detect_source(monitor_id)
    parent = await monitor_batch_service.resolve_batch_id(monitor_id)
    batch_doc = await monitor_batch_service.create_batch(
        monitor_id,
        kind=str(source.get("kind") or "strategy"),
        run_mode=run_mode,
        source_model_id=source.get("source_model_id"),
        researcher_code=source.get("researcher_code"),
        parent_batch_id=parent,
        start_date=str(payload.get("start_date") or payload.get("from_date") or "")[:10] or None,
        data_date=str(payload.get("target_date") or payload.get("to_date") or "")[:10] or None,
        status=BatchStatus.PENDING.value,
    )
    batch_id = batch_doc.get("batch_id")

    try:
        task = await create_task(monitor_id, kind, batch_id=batch_id, params=payload)
    except Exception:
        # 任务建不了就把刚预建的批次标失败，不留永远的 pending 批次
        try:
            await monitor_batch_service.mark_failed(batch_id, "任务创建失败")
        except Exception:  # noqa: BLE001
            pass
        raise

    start_task(task["task_id"], monitor_id, kind, payload, batch_id)
    logger.info(
        f"[monitor_task] 任务已提交: task_id={task['task_id']}, kind={kind}, "
        f"monitor_id={monitor_id}, batch_id={batch_id}"
    )
    return {
        "task_id": task["task_id"],
        "batch_id": batch_id,
        "status": STATUS_PENDING,
        "kind": kind,
        "monitor_id": monitor_id,
        "params": _json_safe(payload),
    }


async def mark_stale_interrupted() -> int:
    """启动时把上轮进程遗留的活跃任务标记为中断.

    当前部署形态为单 worker（``main.py`` 直接 ``uvicorn.run``）；多 worker
    部署需按 owner 区分进程，否则会误伤其他 worker 正在执行的任务。
    """
    db = Database.get_database()
    if db is None:
        return 0
    now = datetime.now()
    result = await db[COL_MONITOR_TASKS].update_many(
        {"status": {"$in": list(ACTIVE_STATUSES)}},
        {
            "$set": {
                "status": STATUS_INTERRUPTED,
                "phase": "interrupted",
                "message": "服务重启，任务已中断，请重新初始化",
                "updated_at": now,
                "finished_at": now,
            },
            "$unset": {"active": ""},
        },
    )
    if result.modified_count:
        logger.warning(
            f"[monitor_task] 已将 {result.modified_count} 个遗留活跃任务标记为中断"
        )
    return int(result.modified_count or 0)
