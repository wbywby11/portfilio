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

    Returns:
        dict:
            portfolio_nav  : pd.Series（DatetimeIndex → 组合净值）
            equity_curve   : list[{date, value, drawdown, is_rebalance_day, weights}]
            weight_history : list[{date, **asset_weights}]（穿透后资产级）
            rebalance_dates: list[日期]
            performance    : PerformanceSummary
            sub_results    : list[SubStrategyResultOut]
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
    if not portfolio_model.sub_strategies:
        raise HTTPException(status_code=400, detail="投资组合未配置子策略")

    sub_pairs = await model_service.resolve_sub_strategies(portfolio_model)
    if not sub_pairs:
        raise HTTPException(status_code=400, detail="无法解析子策略，请检查配置")

    # 标准化子策略清单（与端点一致，含子策略独立回测起点 sub_start）
    sub_entries = []
    for sub_model, weight in sub_pairs:
        sub_info = next(
            (s for s in portfolio_model.sub_strategies if s.get("model_id") == sub_model.id), {}
        )
        sub_entries.append({
            "model": sub_model,
            "weight": weight,
            "name": sub_info.get("name", sub_model.name),
            "fetch_id": sub_model.id or sub_model.name,
            "sub_start": sub_info.get("backtest_start"),
        })

    # 组装成本覆盖（构造一个最小请求对象供 _collect_cost_overrides 复用）
    _req = PortfolioBacktestRequest(
        start_date=start_date,
        end_date=end_date,
        initial_nav=initial_nav,
        rebalance_freq=rebalance_freq,
        commission_rate=commission_rate,
        slippage=slippage,
    )

    (
        sub_nav_series, sub_weights, sub_results_out,
        all_trades, sub_snapshots_by_key,
    ) = await _run_sub_strategy_backtests(
        sub_entries, start_date, end_date, initial_nav, model_service,
        cost_overrides=_collect_cost_overrides(_req),
    )

    if not sub_nav_series:
        raise HTTPException(status_code=400, detail="所有子策略回测失败，无法构建投资组合")

    # 组合权重模型（四象限）与事件驱动信号
    weight_model = None
    rebalance_signal = None
    composite_exec_schedule = None
    composite_weight_drift = True
    wm_type = getattr(portfolio_model, "weight_model_type", None)
    wm_params = getattr(portfolio_model, "weight_model_params", {}) or {}
    if wm_type == "quadrant":
        weight_model, rebalance_signal, composite_exec_schedule, composite_weight_drift = (
            await _build_quadrant_weight_components(
                wm_params,
                start_date,
                end_date,
            )
        )

    portfolio_result = composite_run(
        sub_nav_series=sub_nav_series,
        sub_weights=sub_weights,
        initial_nav=initial_nav,
        rebalance_freq=rebalance_freq or "monthly",
        weight_model=weight_model,
        rebalance_signal=rebalance_signal,
        execution_schedule=composite_exec_schedule,
        weight_drift=composite_weight_drift,
    )

    # ---- 产品层（可选）：与回测端点同一入口，保证监控 == 回测 ----
    portfolio_result, product_layer_out = await _maybe_apply_product_layer(
        portfolio_result, wm_params, initial_nav,
    )

    portfolio_equity, weight_history_out = _build_portfolio_equity_outputs(
        portfolio_result, sub_snapshots_by_key
    )

    return {
        "portfolio_nav": portfolio_result.portfolio_nav,
        "equity_curve": portfolio_equity,
        "weight_history": weight_history_out,
        "rebalance_dates": list(getattr(portfolio_result, "rebalance_dates", [])),
        "performance": portfolio_result.performance,
        "sub_results": sub_results_out,
        "portfolio_model": portfolio_model,
        "product_layer": product_layer_out,
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
