# -*- coding: utf-8 -*-
"""组合监控：策略维度指令提取 + 双轨净值（模型/实际）构建。

- 模型口径：直接复用组合回测管线输出（纯系统信号自动执行，与回测一致）。
- 实际口径：在模型口径基础上叠加用户主观调整。组合层主观调整作用于
  **穿透后底层资产权重**：自主观指令执行日起、至下一个系统再平衡日为止，
  组合日收益按主观权重与底层资产收益计算；系统再平衡日后恢复系统权重续算。
  组合引擎在子策略合成资产层运行，资产级主观权重无法回投为引擎预设调仓，
  故采用与穿透权重同源的逐日重加权口径（无主观调整时实际轨与模型轨完全重合）。
- 策略维度指令：组合层（四象限再平衡，strategy_key=portfolio）+
  各子策略自身调仓（strategy_key=子策略 model_id），均来自管线回测输出。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from loguru import logger


def _build_strategy_weight_maps(
    pipeline: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, Dict[str, float]]]]:
    """构建策略级权重查找表：{日期: {子策略key: 组合比重}} 与 {子策略key: {日期: 策略内资产权重}}。"""
    strat_w_by_date: Dict[str, Dict[str, float]] = {}
    weight_hist = pipeline.get("strategy_weight_history")
    if weight_hist is not None and len(weight_hist):
        for ts, row in weight_hist.iterrows():
            strat_w_by_date[str(ts)[:10]] = {
                str(k): float(v) for k, v in row.items() if v
            }

    sub_date_weights: Dict[str, Dict[str, Dict[str, float]]] = {}
    for key, snapshots in (pipeline.get("sub_snapshots_by_key") or {}).items():
        m: Dict[str, Dict[str, float]] = {}
        for snap in snapshots or []:
            w = {
                str(k): float(v)
                for k, v in (getattr(snap, "weights", None) or {}).items()
            }
            if w:
                m[str(getattr(snap, "time", ""))[:10]] = w
        sub_date_weights[str(key)] = m
    return strat_w_by_date, sub_date_weights


def _sub_weights_at(
    sub_date_weights: Dict[str, Dict[str, Dict[str, float]]],
    key: str, date_str: str,
) -> Dict[str, float]:
    """取子策略某日策略内资产权重（与穿透口径一致：最多回溯 5 个自然日）。"""
    m = sub_date_weights.get(key) or {}
    if date_str in m:
        return m[date_str]
    base = datetime.strptime(date_str, "%Y-%m-%d")
    for offset in range(1, 6):
        lookup = (base - timedelta(days=offset)).strftime("%Y-%m-%d")
        if lookup in m:
            return m[lookup]
    return {}


def extract_portfolio_operations(pipeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从组合管线输出提取策略维度调仓指令（管线全量重跑，均为已执行状态）。

    Args:
        pipeline: run_portfolio_monitor_pipeline 输出，需含
            equity_curve（带 is_rebalance_day/weights）、sub_snapshots_by_key、
            sub_names_by_key、strategy_weight_history（策略级权重时间线）

    Returns:
        指令字典列表，字段与 MonitorOperationService.bulk_upsert_executed_operations 对齐；
        组合层指令额外携带 strategy_weights（当日子策略组合比重）与
        strategy_breakdown（穿透拆解：策略权重 × 策略内资产权重）。
        组合层还带 prev_strategy_breakdown（上一调仓日的同级拆解）：
        资产行变动必须按策略归属，仅凭穿透后的 prev_weights 无法拆回各子策略。
    """
    ops: List[Dict[str, Any]] = []
    strat_w_by_date, sub_date_weights = _build_strategy_weight_maps(pipeline)
    sub_names_by_key: Dict[str, str] = pipeline.get("sub_names_by_key") or {}

    # ── 组合层：四象限再平衡日（equity_curve.is_rebalance_day + 穿透后资产权重）──
    prev_weights: Dict[str, float] = {}
    prev_strategy_weights: Dict[str, float] = {}
    prev_breakdown: List[Dict[str, Any]] = []
    for pt in pipeline.get("equity_curve") or []:
        if not pt.get("is_rebalance_day"):
            continue
        weights = {str(k): float(v) for k, v in (pt.get("weights") or {}).items()}
        if not weights:
            continue
        date_str = str(pt.get("date") or "")[:10]
        strategy_weights = strat_w_by_date.get(date_str, {})
        breakdown = sorted(
            (
                {
                    "strategy_key": str(k),
                    "strategy_name": sub_names_by_key.get(str(k), ""),
                    "weight": float(w),
                    "asset_weights": _sub_weights_at(sub_date_weights, str(k), date_str),
                }
                for k, w in strategy_weights.items()
                if w > 0
            ),
            key=lambda b: -b["weight"],
        )
        ops.append({
            "strategy_key": "portfolio",
            "strategy_name": "组合层（四象限动态调权）",
            "op_type": "monthly_rebalance",
            "signal_date": date_str,
            "execute_date": date_str,
            "target_weights": weights,
            "prev_weights": dict(prev_weights),
            "strategy_weights": dict(strategy_weights),
            "prev_strategy_weights": dict(prev_strategy_weights),
            "strategy_breakdown": breakdown,
            "prev_strategy_breakdown": prev_breakdown,
        })
        prev_weights = weights
        prev_strategy_weights = strategy_weights
        prev_breakdown = breakdown

    # ── 子策略层：策略内调仓日（回测快照 is_rebalance_day，含延迟执行的原始信号日）──
    sub_snapshots_by_key: Dict[str, list] = pipeline.get("sub_snapshots_by_key") or {}
    for key, snapshots in sub_snapshots_by_key.items():
        prev_w: Dict[str, float] = {}
        for snap in snapshots or []:
            if not getattr(snap, "is_rebalance_day", False):
                continue
            w = {
                str(k): float(v)
                for k, v in (getattr(snap, "weights", None) or {}).items()
            }
            if not w:
                continue
            date_str = str(getattr(snap, "time", ""))[:10]
            signal_date = date_str
            sig_ts = getattr(snap, "signal_date", None)
            if sig_ts is not None:
                signal_date = str(sig_ts)[:10]
            ops.append({
                "strategy_key": str(key),
                "strategy_name": sub_names_by_key.get(str(key), ""),
                "op_type": "monthly_rebalance",
                "signal_date": signal_date,
                "execute_date": date_str,
                "target_weights": w,
                "prev_weights": dict(prev_w),
            })
            prev_w = w
    return ops


def _collect_effective_overrides(
    overrides: List[Dict[str, Any]],
    dates: List[str],
) -> Dict[str, Dict[str, Any]]:
    """筛选区间内有效的主观指令，执行日对齐到首个不早于它的交易日。

    Returns:
        {对齐后的执行日: override 文档}（同日多条取最新创建）
    """
    if not overrides or not dates:
        return {}
    first, last = dates[0], dates[-1]
    out: Dict[str, Dict[str, Any]] = {}
    for doc in overrides:
        status = str(doc.get("status") or "")
        if status == "cancelled":
            continue
        exec_d = str(doc.get("execute_date") or "")[:10]
        if not exec_d or exec_d < first or exec_d > last:
            continue
        # 非交易日执行日顺延到首个不早于它的交易日
        aligned = exec_d if exec_d in dates else next(
            (d for d in dates if d >= exec_d), None
        )
        if aligned is None:
            continue
        existed = out.get(aligned)
        if existed is None or str(doc.get("created_at") or "") >= str(
            existed.get("created_at") or ""
        ):
            out[aligned] = doc
    return out


def align_overrides_to_trade_days(
    overrides: List[Dict[str, Any]],
    dates: List[str],
) -> List[Dict[str, Any]]:
    """把指令执行日对齐到交易日并按日去重，返回带 ``aligned_date`` 的列表。

    单策略逐日推演按日期精确匹配指令；补录允许选择非交易日，不对齐就会
    静默丢掉这笔调仓。``dates`` 传本次推演的交易日序列，区间外指令丢弃。
    """
    aligned = _collect_effective_overrides(overrides, dates)
    return [{**doc, "aligned_date": day} for day, doc in sorted(aligned.items())]


async def build_portfolio_actual_nav(
    pipeline: Dict[str, Any],
    overrides: List[Dict[str, Any]],
    initial_nav: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """在模型口径上叠加主观调整，构建实际口径净值序列。

    Args:
        pipeline: 组合回测管线输出（需含带穿透权重的 equity_curve）
        overrides: subjective_overrides 文档列表（含 weights/execute_date/status）
        initial_nav: 起始净值

    Returns:
        (actual_nav_history, applied_overrides)
        - 无有效主观调整时返回模型口径序列（双轨重合），applied 为空
        - applied_overrides 为区间内被纳入实际轨的主观指令文档
    """
    equity_curve: List[Dict[str, Any]] = pipeline.get("equity_curve") or []
    if not equity_curve:
        return [], []

    dates = [str(pt["date"])[:10] for pt in equity_curve]
    model_nav = [float(pt["value"]) for pt in equity_curve]
    model_history = [
        {"date": d, "nav": v} for d, v in zip(dates, model_nav)
    ]

    override_map = _collect_effective_overrides(overrides, dates)
    if not override_map:
        return model_history, []

    if pipeline.get("product_layer"):
        # 产品层（控波/现金垫）会改写组合净值，主观重加权口径暂不适用
        logger.warning(
            "[组合监控] 产品层已启用，主观调整暂无法纳入实际口径，实际轨沿用模型口径"
        )
        return model_history, []

    # ── 模型权重时间线（再平衡日穿透权重，区间内前向填充）──
    model_w_by_date: Dict[str, Dict[str, float]] = {}
    for pt in equity_curve:
        if pt.get("weights"):
            model_w_by_date[str(pt["date"])[:10]] = {
                str(k): float(v) for k, v in pt["weights"].items()
            }
    model_timeline: Dict[str, Dict[str, float]] = {}
    cur_w: Dict[str, float] = {}
    for d in dates:
        if d in model_w_by_date:
            cur_w = model_w_by_date[d]
        model_timeline[d] = cur_w

    # ── 实际权重时间线：主观执行日起用主观权重，下一系统再平衡日恢复系统权重 ──
    actual_timeline: Dict[str, Dict[str, float]] = {}
    overridden_active = False
    for d in dates:
        if d in override_map:
            # 调仓日比例优化：主观权重覆盖当日系统权重
            cur_w = {
                str(k): float(v)
                for k, v in (override_map[d].get("weights") or {}).items()
            }
            overridden_active = True
        elif overridden_active and d in model_w_by_date:
            cur_w = model_w_by_date[d]
            overridden_active = False
        actual_timeline[d] = cur_w

    returns_df = await _load_asset_returns(pipeline, override_map, dates)
    if returns_df is None or returns_df.empty:
        logger.warning("[组合监控] 底层资产行情缺失，实际轨沿用模型口径")
        return model_history, []

    nav = float(initial_nav)
    actual_history: List[Dict[str, Any]] = []
    for i, d in enumerate(dates):
        if i == 0:
            actual_history.append({"date": d, "nav": round(nav, 4)})
            continue
        # 当日收益使用前一日收盘持仓权重（调仓在收盘执行）
        held_w = actual_timeline[dates[i - 1]]
        day_ret = 0.0
        row = returns_df.loc[d] if d in returns_df.index else None
        if row is not None:
            for asset, w in held_w.items():
                r = row.get(asset)
                if r is not None and pd.notna(r):
                    day_ret += w * float(r)
        nav *= (1.0 + day_ret)
        actual_history.append({"date": d, "nav": round(nav, 4)})

    applied = sorted(override_map.values(), key=lambda x: str(x.get("execute_date")))
    logger.info(
        "[组合监控] 实际口径已纳入 {} 条主观调整（{} ~ {}）",
        len(applied), dates[0], dates[-1],
    )
    return actual_history, applied


async def _load_asset_returns(
    pipeline: Dict[str, Any],
    override_map: Dict[str, Dict[str, Any]],
    dates: List[str],
) -> Optional[pd.DataFrame]:
    """加载穿透资产 + 主观权重资产的日收益率矩阵（行=日期字符串，列=资产代码）。"""
    from app.services.market_service import MarketService

    codes: set = set()
    for pt in pipeline.get("equity_curve") or []:
        codes.update(str(k) for k in (pt.get("weights") or {}).keys())
    for doc in override_map.values():
        codes.update(str(k) for k in (doc.get("weights") or {}).keys())
    codes.discard("")
    if not codes:
        return None

    start_yyyymmdd = dates[0].replace("-", "")
    end_yyyymmdd = dates[-1].replace("-", "")
    svc = MarketService()
    prices = await svc.get_price_matrix(sorted(codes), start_yyyymmdd, end_yyyymmdd)
    if prices is None or prices.empty:
        return None

    missing = sorted(c for c in codes if c not in prices.columns)
    if missing:
        logger.warning("[组合监控] 实际口径行情缺失资产（收益按 0 处理）: {}", missing)

    returns = prices.pct_change(fill_method=None)
    returns.index = pd.DatetimeIndex(returns.index).strftime("%Y-%m-%d")
    return returns
