# -*- coding: utf-8 -*-
"""组合监控 — 复用回测管线实现。

设计目标（对齐任务 t8/t9）：
- 四象限组合（is_portfolio=True）的日常监控不再走单策略 PortfolioTracker 逐日推演，
  而是**直接复用组合回测管线**（run-portfolio 端点同一套构建块），
  从监控起始日推演到最新行情日，产出组合 NAV 序列 + 穿透后资产级权重。
- 因为监控与回测使用完全相同的引擎与口径，二者结果天然一致（monitor == backtest）。
- 雪球定价种子已改为基于日期的稳定哈希（zlib.crc32），保证回测/监控跨进程可复现。

对外提供：
- run_portfolio_monitor_pipeline: 运行组合回测管线，返回 NAV/权重/绩效/调仓日。
- build_monitor_state_from_pipeline: 将管线输出映射为 MonitorState 所需字段。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from loguru import logger


async def run_portfolio_monitor_pipeline(
    portfolio_model_id: str,
    start_date: str,
    end_date: str,
    initial_nav: float = 1000.0,
    rebalance_freq: str = "monthly",
    commission_rate: Optional[float] = 0.0,
    slippage: Optional[float] = 0.0,
    progress_cb=None,
) -> Dict[str, Any]:
    """复用组合回测管线运行组合监控。

    与 ``app.api.backtests.run_portfolio_backtest_api`` 使用完全相同的构建块：
    ``_run_sub_strategy_backtests`` + ``_build_quadrant_weight_components`` +
    ``composite_runner.run_composite_unified`` + ``_build_portfolio_equity_outputs``，
    但不保存回测记录（监控是高频运行，避免污染 backtest_records）。

    Args:
        portfolio_model_id: 组合策略模型 ID（strategy_models._id）
        start_date / end_date: YYYYMMDD
        initial_nav: 起始净值
        rebalance_freq: 再平衡频率
        commission_rate / slippage: 交易成本（与回测口径一致）
        progress_cb: async callable(phase, current, total, message) or None
            阶段进度回调。总步数 = 子策略数 + 3（权重组件 / 合成引擎 / 输出构建）。

    Returns:
        dict:
            portfolio_nav  : pd.Series（DatetimeIndex → 组合净值）
            equity_curve   : list[{date, value, drawdown, is_rebalance_day, weights}]
            weight_history : list[{date, **asset_weights}]（穿透后资产级）
            rebalance_dates: list[日期]
            performance    : PerformanceSummary
            sub_results    : list[SubStrategyResultOut]
            sub_snapshots_by_key: {子策略key: PortfolioSnapshot 列表}（策略维度指令提取）
            sub_names_by_key    : {子策略key: 展示名}
            portfolio_model: StrategyModel
    """
    from app.api.backtests import (
        get_model_service,
        _run_sub_strategy_backtests,
        _build_quadrant_weight_components,
        _build_portfolio_equity_outputs,
        _collect_cost_overrides,
        _maybe_apply_product_layer,
        PortfolioBacktestRequest,
    )
    from app.portfolio.composite_runner import run_composite_unified as composite_run
    from fastapi import HTTPException

    model_service = get_model_service()
    portfolio_model = await model_service.get_model(portfolio_model_id)
    if not portfolio_model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {portfolio_model_id}")
    if not portfolio_model.is_portfolio:
        raise HTTPException(status_code=400, detail=f"模型 {portfolio_model_id} 不是投资组合类型")
    live_snap = getattr(portfolio_model, "live_snapshot", None) or {}
    if not getattr(portfolio_model, "live_publish_enabled", False) or not live_snap:
        raise HTTPException(
            status_code=400, detail="组合未实盘发布或实盘快照缺失，无法运行日常监控"
        )
    # 成员/权重/权重模型参数只读实盘快照，子策略内容读各自发布快照
    membership = list(live_snap.get("sub_strategies") or [])
    if not membership:
        raise HTTPException(status_code=400, detail="组合实盘快照未配置子策略")

    sub_pairs = await model_service.resolve_sub_strategies(
        portfolio_model, sub_strategies=membership
    )
    if not sub_pairs:
        raise HTTPException(status_code=400, detail="无法解析子策略，请检查配置")

    # 标准化子策略清单（与端点一致，含子策略独立回测起点 sub_start）
    sub_entries = []
    for sub_model, weight in sub_pairs:
        sub_info = next(
            (s for s in membership if s.get("model_id") == sub_model.id), {}
        )
        sub_entries.append({
            "model": sub_model,
            "weight": weight,
            "name": sub_info.get("name", sub_model.name),
            "fetch_id": sub_model.id or sub_model.name,
            "sub_start": sub_info.get("backtest_start"),
        })

    # ── 起点对齐：组合监控不接受早于「最早子策略成立日」的日期 ──
    #
    # 前端「启动日期」默认值为 config.BASE_DATE（2014-02-10），但四象限子策略的
    # 成立日最早也是 2017-01-03。若真按 2014-02-10 起跑，子策略会额外获得约 3 年
    # 预热历史，而选择器 min_history_days=260 的起算相位随之改变，于是**同一个组合**
    # 从 2014-02-10 初始化与从 2017-01-03 初始化会得到两条不同的净值曲线
    # （实测 nav 1368.67/调仓51次 vs 1391.67/调仓52次）。
    #
    # 对齐规则：effective_start = max(传入起点, min(各子策略 inception_date))
    #   - 传更早的日期 → 抬到最早子策略成立日，消除预热差异；
    #   - 传更晚的日期 → 原样保留（用户显式要求更短区间时不被改写）。
    _start_raw = str(start_date)
    _start_norm = _start_raw.replace("-", "")
    _inceptions = [
        getattr(e["model"], "inception_date", None) for e in sub_entries
    ]
    _inceptions = [d for d in _inceptions if d is not None]
    effective_start = _start_raw
    _aligned_from = None
    if _inceptions:
        _floor = min(_inceptions)
        _floor_norm = (
            _floor.strftime("%Y%m%d")
            if hasattr(_floor, "strftime")
            else str(_floor).replace("-", "")[:8]
        )
        if _start_norm < _floor_norm:
            effective_start = (
                _floor.strftime("%Y-%m-%d") if "-" in _start_raw
                else _floor.strftime("%Y%m%d")
            )
            _aligned_from = _start_raw
            logger.info(
                f"[组合监控] 起点对齐：传入 {_start_raw} 早于最早子策略成立日 "
                f"{_floor_norm}，已抬升为 {effective_start}"
            )

    # 组装成本覆盖（构造一个最小请求对象供 _collect_cost_overrides 复用）
    _req = PortfolioBacktestRequest(
        start_date=effective_start,
        end_date=end_date,
        initial_nav=initial_nav,
        rebalance_freq=rebalance_freq,
        commission_rate=commission_rate,
        slippage=slippage,
    )

    # ── 进度上报：阶段骨架 × 逐日刻度 ──
    # 组合耗时集中在子策略回测与合成引擎。只报「7 个阶段」会让进度条在模拟雪球
    # （约 4 分钟）期间完全静止；因此每个阶段再放大 _scale 个刻度，由引擎逐日
    # 回调填满，前端既能看到百分比平滑推进，也能看到具体回测到哪一天。
    _total_steps = max(len(sub_entries), 1) + 3
    _scale = 100
    _total_units = _total_steps * _scale
    _step = {"done": 0}

    async def _emit(current_units: int, message: str, current_date=None) -> None:
        """写一次进度；回调异常不影响回测主流程。"""
        if progress_cb is None:
            return
        try:
            await progress_cb(
                phase="engine",
                current=int(min(current_units, _total_units)),
                total=_total_units,
                current_date=current_date,
                message=message,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[组合监控] 进度上报失败: {exc}")

    async def _tick(message: str) -> None:
        """完成一个阶段（阶段内部的逐日刻度由 _make_day_bridge 填充）。"""
        _step["done"] = min(_step["done"] + 1, _total_steps)
        await _emit(_step["done"] * _scale, message)

    _loop = asyncio.get_running_loop()

    def _make_day_bridge(step_index: int, stage_name: str):
        """构造某阶段的同步逐日回调（引擎在 asyncio.to_thread 工作线程里调用）。

        引擎不能 await 协程，所以用 ``run_coroutine_threadsafe`` 把写库调度回
        主事件循环；引擎侧已按 1% 节流，这里再按百分比去重。

        Args:
            step_index: 该阶段在 1.._total_steps 中的序号（1 起）。
            stage_name: 阶段名，写进 message 供前端直接展示。
        """
        if progress_cb is None:
            return None
        base = (max(int(step_index), 1) - 1) * _scale
        state = {"pct": -1}

        def _cb(done: int, total: int, bar_time=None) -> None:
            try:
                _d, _t = int(done), int(total)
            except (TypeError, ValueError):
                return
            if _t <= 0:
                return
            pct = int(_d * 100 / _t)
            if pct <= state["pct"]:
                return
            state["pct"] = pct
            date_str = (
                bar_time.strftime("%Y-%m-%d")
                if hasattr(bar_time, "strftime")
                else (str(bar_time) if bar_time else None)
            )
            unit = base + min(int(round(_scale * _d / _t)), _scale)
            try:
                asyncio.run_coroutine_threadsafe(
                    _emit(
                        unit,
                        f"{stage_name} · {date_str or '—'}（{_d}/{_t} 个交易日）",
                        date_str,
                    ),
                    _loop,
                )
            except Exception as exc:  # noqa: BLE001 —— 进度失败不影响回测
                logger.debug(f"[组合监控] 逐日进度调度失败: {exc}")

        return _cb

    if progress_cb is not None:
        try:
            # 先报起点，让前端立刻拿到 total（否则在第一个子策略跑完前仍显示 0%）
            _align_note = (
                f"（启动日由 {_aligned_from} 对齐为 {effective_start}）"
                if _aligned_from else ""
            )
            await progress_cb(
                phase="engine", current=0, total=_total_units,
                message=f"组合回测启动：{len(sub_entries)} 个子策略待回测{_align_note}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[组合监控] 起始进度上报失败: {exc}")

    async def _on_sub_done(done: int, total: int, message: str) -> None:
        """`_run_sub_strategy_backtests` 的完成回调：映射为统一阶段步进。"""
        await _tick(message)

    (
        sub_nav_series, sub_weights, sub_results_out,
        all_trades, sub_snapshots_by_key,
    ) = await _run_sub_strategy_backtests(
        sub_entries, effective_start, end_date, initial_nav, model_service,
        cost_overrides=_collect_cost_overrides(_req),
        progress_cb=_on_sub_done,
        engine_progress=_make_day_bridge,
    )

    if not sub_nav_series:
        raise HTTPException(status_code=400, detail="所有子策略回测失败，无法构建投资组合")

    # 组合权重模型（四象限）与事件驱动信号
    weight_model = None
    rebalance_signal = None
    composite_exec_schedule = None
    composite_weight_drift = True
    wm_type = live_snap.get("weight_model_type")
    wm_params = live_snap.get("weight_model_params") or {}
    if wm_type == "quadrant":
        weight_model, rebalance_signal, composite_exec_schedule, composite_weight_drift = (
            await _build_quadrant_weight_components(
                wm_params,
                effective_start,
                end_date,
            )
        )
        await _tick("四象限权重组件已就绪")
    else:
        # 非四象限模型：少一个阶段，补 tick 让进度仍能走到 100%
        await _tick("非四象限模型，跳过权重组件")

    # 合成引擎是同步 CPU 密集计算（逐日撮合 + 象限调权），必须放到工作线程：
    # 直接调用会冻结 asyncio 事件循环，期间任务进度轮询/其它 API 全部挂起，
    # 前端表现为进度条不动、请求超时后直接拿到终态。
    portfolio_result = await asyncio.to_thread(
        composite_run,
        sub_nav_series=sub_nav_series,
        sub_weights=sub_weights,
        initial_nav=initial_nav,
        rebalance_freq=rebalance_freq or "monthly",
        weight_model=weight_model,
        rebalance_signal=rebalance_signal,
        execution_schedule=composite_exec_schedule,
        weight_drift=composite_weight_drift,
        # 母层成本与子策略同一组参数，保证监控与回测的成本口径一致
        commission_rate=float(commission_rate or 0.0),
        slippage=float(slippage or 0.0),
        # 合成引擎同样是逐日撮合（步数 = 合成日历长度），接同一套逐日进度
        progress_cb=_make_day_bridge(len(sub_entries) + 2, "组合合成"),
    )

    # ---- 产品层（可选）：与回测端点同一入口，保证监控 == 回测 ----
    portfolio_result, product_layer_out = await _maybe_apply_product_layer(
        portfolio_result, wm_params, initial_nav,
    )
    await _tick("组合合成引擎完成")

    portfolio_equity, weight_history_out = await asyncio.to_thread(
        _build_portfolio_equity_outputs, portfolio_result, sub_snapshots_by_key
    )
    await _tick("净值与穿透权重输出已构建")

    return {
        "portfolio_nav": portfolio_result.portfolio_nav,
        "equity_curve": portfolio_equity,
        "weight_history": weight_history_out,
        # 策略级权重时间线（DatetimeIndex × 子策略key，调仓日各子策略组合比重）
        "strategy_weight_history": getattr(portfolio_result, "weight_history", None),
        "rebalance_dates": list(getattr(portfolio_result, "rebalance_dates", [])),
        "performance": portfolio_result.performance,
        "sub_results": sub_results_out,
        "sub_snapshots_by_key": sub_snapshots_by_key,
        "sub_names_by_key": {
            (e["model"].id or e["model"].name): e["name"] for e in sub_entries
        },
        "portfolio_model": portfolio_model,
        "product_layer": product_layer_out,
        "config_versions": {
            "published_version": portfolio_model.published_version,
            "live_version": portfolio_model.live_version,
            "live_published_version": portfolio_model.live_published_version,
            "config_fingerprint": portfolio_model.config_fingerprint,
            "subs": {
                (sub_model.id or sub_model.name): {
                    "published_version": sub_model.published_version,
                    "config_fingerprint": sub_model.config_fingerprint,
                }
                for sub_model, _ in sub_pairs
            },
        },
    }


def build_monitor_state_fields(
    monitor_id: str,
    strategy_model_id: str,
    pipeline: Dict[str, Any],
    initial_nav: float,
) -> Dict[str, Any]:
    """将回测管线输出映射为 MonitorState 字段（供 monitor_service 组装 MonitorState）。

    Returns:
        dict with keys: date, nav, nav_base, day_count, trade_day_count,
        positions_cny, target_weights, nav_history, event_log, last_rebalance_date
    """
    equity_curve: List[Dict[str, Any]] = pipeline.get("equity_curve") or []
    if not equity_curve:
        raise ValueError("组合监控管线未产出净值曲线（equity_curve 为空）")

    nav_history = [
        {"date": pt["date"], "nav": float(pt["value"])} for pt in equity_curve
    ]

    final_point = equity_curve[-1]
    final_date = final_point["date"]
    final_nav = float(final_point["value"])

    # 最新穿透后资产级权重（取最后一个带 weights 的点，兜底为空）
    latest_weights: Dict[str, float] = {}
    for pt in reversed(equity_curve):
        if pt.get("weights"):
            latest_weights = {k: float(v) for k, v in pt["weights"].items()}
            break

    # 持仓金额 = 净值 × 权重（与回测穿透权重口径一致）
    positions_cny = {
        code: final_nav * w for code, w in latest_weights.items()
    }

    # 调仓事件日志（来自回测 is_rebalance_day 标记）
    event_log: List[Dict[str, Any]] = [
        {
            "date": pt["date"],
            "event_type": "monthly_rebalance",
            "description": "四象限组合月度再平衡（回测管线推演）",
            "details": {"weights": pt.get("weights", {})},
        }
        for pt in equity_curve
        if pt.get("is_rebalance_day")
    ]

    last_rebalance_date = event_log[-1]["date"] if event_log else None

    return {
        "monitor_id": monitor_id,
        "strategy_model_id": strategy_model_id,
        "date": final_date,
        "nav": final_nav,
        "nav_base": initial_nav,
        "day_count": len(nav_history),
        "trade_day_count": len(nav_history),
        "positions_cny": positions_cny,
        "target_weights": latest_weights,
        "nav_history": nav_history,
        "event_log": event_log,
        "last_rebalance_date": last_rebalance_date,
    }
