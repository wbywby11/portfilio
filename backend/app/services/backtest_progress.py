"""回测端点的旁路进度上报（不改变端点的同步返回语义）.

前端发起回测时生成一个 ``progress_key`` 随请求带来，端点据此在 ``monitor_tasks``
建一条「纯进度」任务文档，执行过程中把引擎逐日进度写进去；前端并行轮询
``GET /monitor/tasks/{task_id}`` 渲染进度条，与日常监控的进度对话框同一套口径。

三条硬约束：
    - 进度是旁路设施：任何异常只告警，绝不影响回测本身；
    - 不传 ``progress_key`` 时不建文档、不写进度，端点行为与接入前完全一致；
    - 端点仍同步返回回测结果（调用方众多：agent 工具、基线脚本、回归链），
      因此引擎必须跑在工作线程里，否则事件循环被冻结、轮询请求根本进不来。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from loguru import logger

from app.services import monitor_task_service as task_service

#: 单个阶段的进度刻度数：阶段内逐日进度按此粒度折算，避免百分比长时间不动
STAGE_SCALE = 100

#: 任务类型别名（调用方不必再 import monitor_task_service）
KIND_SINGLE = task_service.TASK_KIND_BACKTEST_SINGLE
KIND_PORTFOLIO = task_service.TASK_KIND_BACKTEST_PORTFOLIO

#: 进度上下文在 sink 字典里的键（与 ``digest_sink`` 同一套输出参数写法）
SINK_KEY = "progress"

#: 进度文案：组合回测按子策略分阶段，单策略只有一段
LABEL_BY_KIND = {
    KIND_SINGLE: "回测",
    KIND_PORTFOLIO: "组合回测",
}


class BacktestProgress:
    """一次回测的进度上下文；``task_id`` 为空时所有方法退化为 no-op.

    进度模型与组合监控一致：把整次回测切成 ``total_steps`` 个阶段，每阶段
    折算 ``STAGE_SCALE`` 个刻度，``total = total_steps * STAGE_SCALE``，
    阶段内的逐日进度按完成比例填充本阶段刻度。
    """

    def __init__(
        self,
        task_id: Optional[str] = None,
        *,
        kind: str = "",
        subject: str = "",
        total_steps: int = 1,
    ):
        self.task_id = task_id
        self.kind = kind
        self.subject = subject
        self.label = LABEL_BY_KIND.get(kind, "回测")
        self.total_steps = max(int(total_steps), 1)
        self.total_units = self.total_steps * STAGE_SCALE
        self._done_steps = 0

    @property
    def enabled(self) -> bool:
        """是否真的在上报（未传 progress_key 或建文档失败时为 False）."""
        return bool(self.task_id)

    async def _safe(self, coro) -> None:
        """吞掉进度写入异常：进度永远不能成为回测失败的原因."""
        if not self.enabled:
            return
        try:
            await coro
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[backtest-progress] 进度写入失败: {exc}")

    async def emit(
        self, units: int, message: str, current_date: Optional[str] = None
    ) -> None:
        """按刻度写一次进度（``total`` 固定为总刻度数，前端据此算百分比）.

        ``phase`` 固定为 ``engine``：``total`` 是「阶段 × 刻度」的放大值而非交易日数，
        前端据此隐去「X / Y 个交易日」（与组合监控同一口径），明细看 message。
        """
        await self._safe(
            task_service.update_progress(
                self.task_id,
                phase="engine",
                current=max(0, min(int(units), self.total_units)),
                total=self.total_units,
                current_date=current_date,
                message=message,
            )
        )

    async def start(self, message: str) -> None:
        """置 running 并立即报一次起点，让前端拿到 total 而不是干等第一个刻度."""
        if not self.enabled:
            return
        await self._safe(
            task_service.mark_running(
                self.task_id, phase="engine", message=message
            )
        )
        await self.emit(0, message)

    async def step(self, message: str, *, index: Optional[int] = None) -> None:
        """完成一个阶段；``index`` 为阶段序号（1 起），缺省按调用次数递增."""
        self._done_steps = (
            min(int(index), self.total_steps)
            if index is not None
            else min(self._done_steps + 1, self.total_steps)
        )
        await self.emit(self._done_steps * STAGE_SCALE, message)

    def day_bridge(
        self, step_index: int = 1, stage_name: str = ""
    ) -> Optional[Callable[[int, int, Any], None]]:
        """构造某阶段的同步逐日回调（引擎在 ``asyncio.to_thread`` 工作线程里调用）.

        Args:
            step_index: 该阶段在 ``1..total_steps`` 中的序号（1 起）。
            stage_name: 阶段名，写进 message 供前端直接展示。

        Returns:
            同步回调 ``(done, total, bar_time)``；未启用进度时返回 None。
        """
        if not self.enabled:
            return None
        base = (max(int(step_index), 1) - 1) * STAGE_SCALE
        head = stage_name or self.label
        task_id = self.task_id
        total_units = self.total_units

        async def _dispatch(done: int, total: int, pct: int, date_str) -> None:
            units = base + min(int(round(STAGE_SCALE * done / total)), STAGE_SCALE)
            await task_service.update_progress(
                task_id,
                phase="engine",
                current=min(units, total_units),
                total=total_units,
                current_date=date_str,
                message=f"{head} {pct}%（{done}/{total}）",
            )

        return task_service.make_thread_bridge(_dispatch)

    async def finish(self, message: Optional[str] = None) -> None:
        """回测成功收尾：写终态并释放「单实例单活跃任务」名额."""
        await self._safe(
            task_service.finish_task(
                self.task_id,
                task_service.STATUS_COMPLETED,
                message=message
                or task_service.DONE_MESSAGE_BY_KIND.get(self.kind, "回测完成"),
            )
        )

    async def fail(self, error: BaseException) -> None:
        """回测失败收尾：错误信息进任务表，前端轮询到终态即可停止."""
        await self._safe(
            task_service.finish_task(
                self.task_id,
                task_service.STATUS_FAILED,
                error={"message": str(error), "type": type(error).__name__},
                message=f"{self.label}失败：{error}",
            )
        )


async def open_progress(
    progress_key: Optional[str],
    *,
    kind: str,
    subject_id: str,
    subject_name: str = "",
    total_steps: int = 1,
    params: Optional[Dict[str, Any]] = None,
) -> BacktestProgress:
    """按前端传来的 ``progress_key`` 开一条进度任务.

    Args:
        progress_key: 前端生成的任务号（同时作为轮询用的 task_id）；为空则不上报
        kind: ``backtest_single`` / ``backtest_portfolio``
        subject_id: 回测主体（模型 ID / 组合 ID），落库时加 ``backtest::`` 前缀，
            避免与真实监控实例抢「单实例单活跃任务」唯一索引
        subject_name: 主体展示名，仅存 params 供排查
        total_steps: 阶段数（单策略 1；组合 = 子策略数 + 合成 1 段）
        params: 回测区间等上下文，原样存下供排查

    Returns:
        可用的进度上下文；未传 key 或建文档失败时返回 no-op 空壳（回测照常执行）。
    """
    ctx = BacktestProgress(
        None, kind=kind, subject=subject_id, total_steps=total_steps
    )
    key = (progress_key or "").strip()
    if not key:
        return ctx
    payload = dict(params or {})
    if subject_name:
        payload["subject_name"] = subject_name
    try:
        task = await task_service.create_task(
            f"{task_service.BACKTEST_SUBJECT_PREFIX}{subject_id}",
            kind,
            task_id=key,
            params=payload,
        )
    except Exception as exc:  # noqa: BLE001 —— 进度建不了不影响回测
        logger.warning(f"[backtest-progress] 进度任务创建失败（回测照常执行）: {exc}")
        return ctx
    ctx.task_id = task["task_id"]
    logger.info(
        f"[backtest-progress] 已开启进度上报: task_id={ctx.task_id}, kind={kind}, "
        f"subject={subject_id}, steps={ctx.total_steps}"
    )
    return ctx


async def close_progress(
    sink: Optional[Dict[str, Any]], error: Optional[BaseException] = None
) -> None:
    """收尾 sink 里的进度上下文（端点在成功返回前与各 except 分支各调一次）.

    回测编排函数有多个 return / except 出口，进度上下文改由输出参数 ``sink``
    带出（与 ``digest_sink`` 同一套写法），由持有 ``progress_key`` 的端点统一收尾，
    避免任务文档停在 running 直到下次重启被标为中断。
    """
    ctx = sink.get(SINK_KEY) if sink else None
    if not isinstance(ctx, BacktestProgress) or not ctx.enabled:
        return
    if error is None:
        await ctx.finish()
    else:
        await ctx.fail(error)
