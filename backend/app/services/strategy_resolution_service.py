# -*- coding: utf-8 -*-
"""策略解析失败观测服务（7a 影子面）.

背景：``app/monitor/engine_adapter.py`` 的工厂方法在 ``resolve_class`` 抛
``ValueError``（template_code 未注册 / 类导入失败）时静默回退到
``vol_scaled_budget``。回退本身保住了监控不断，但故障不可见：一旦某模型被
改写成未注册 code，监控会长期跑在「不是它配置的策略」上而无人察觉。

本服务只做观测，**不改回退行为**：
    - ``record()`` 写一条 ``strategy_resolution_events``，字段
      ``template_code`` / ``call_site`` / ``fallback_to`` / ``created_at``；
    - 写入是 fire-and-forget：适配器工厂方法是同步方法，调用方多为同步的
      监控步进链路，不能 await。这里在运行中的事件循环上排一个任务，
      失败只记 warning，绝不向上抛（观测面不得反向影响主流程）；
    - 无运行中的事件循环（纯脚本/单测同步调用）时直接跳过并记 warning，
      不伪造一条「已记录」的假象。

S19 的前置门槛就是本集合连续 7 天 ``count_documents({}) == 0``。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Set

from app.config.collections import COL_STRATEGY_RESOLUTION_EVENTS
from app.config.database import Database

logger = logging.getLogger(__name__)

__all__ = ["record", "count_recent", "pending_task_count"]

# 强引用持有的待执行任务：事件循环只持弱引用，任务对象被 GC 会静默不执行
_PENDING_TASKS: Set[asyncio.Task] = set()


def _build_doc(
    template_code: Optional[str], call_site: str, fallback_to: Optional[str]
) -> Dict[str, Any]:
    return {
        "template_code": str(template_code or ""),
        "call_site": str(call_site or "unknown"),
        "fallback_to": str(fallback_to or ""),
        "created_at": datetime.now(),
    }


async def _write(doc: Dict[str, Any]) -> None:
    try:
        db = Database.get_database()
        if db is None:
            logger.warning("[strategy_resolution] 数据库未连接，事件未写入: %s", doc)
            return
        await db[COL_STRATEGY_RESOLUTION_EVENTS].insert_one(dict(doc))
    except Exception as exc:  # 观测失败不得影响主流程
        logger.warning("[strategy_resolution] 事件写入失败: %s (%s)", exc, doc)


def record(
    template_code: Optional[str],
    call_site: str,
    fallback_to: Optional[str] = None,
) -> bool:
    """记录一次解析失败（同步入口，fire-and-forget）.

    Args:
        template_code: 解析失败的原始 code。
        call_site: 调用点标识，如 ``from_runtime_config``；用于区分两条回退路径。
        fallback_to: 实际回退到的 code。

    Returns:
        任务是否已排入事件循环。False 表示当前无运行中的循环（或排任务失败），
        调用方仍应继续原有回退逻辑。
    """
    doc = _build_doc(template_code, call_site, fallback_to)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "[strategy_resolution] 无运行中的事件循环，解析失败事件未落库: %s", doc
        )
        return False
    try:
        task = loop.create_task(_write(doc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[strategy_resolution] 排任务失败: %s (%s)", exc, doc)
        return False
    _PENDING_TASKS.add(task)
    task.add_done_callback(_PENDING_TASKS.discard)
    return True


def pending_task_count() -> int:
    """当前未完成的写入任务数（自检/测试用）."""
    return len(_PENDING_TASKS)


async def count_recent(since: Optional[datetime] = None) -> int:
    """统计事件条数（``since`` 为空时统计全量），供 7b 上线门槛核对."""
    db = Database.get_database()
    if db is None:
        return 0
    query: Dict[str, Any] = {}
    if since is not None:
        query["created_at"] = {"$gte": since}
    return int(await db[COL_STRATEGY_RESOLUTION_EVENTS].count_documents(query))
