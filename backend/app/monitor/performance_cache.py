# -*- coding: utf-8 -*-
"""监控绩效缓存（monitor_performance_cache）

职责
----
初始化 / 日常运行结束时，一次性把「绩效页」要用的底层数据算好，并按 monitor_id
（实盘策略即策略模型 ID）统一落库；页面按区间直接读取，不再每次请求重复计算。

缓存内容
--------
- nav_series        实际口径净值序列（日收益、累计收益、回撤、调仓标记）
- nav_series_model  模型口径净值序列（双轨虚线）
- positions_history 调仓日持仓快照（权重 + 当日净值；独立引擎无操作指令时由事件日志回退）
- asset_returns     底层资产日收益率（人民币口径，含汇率折算；相关性 / 波动率 / 归因由此派生）
- meta              资产展示名、类别、币种

过期判定：缓存 end_date 与 monitor_states.date 不一致，或 schema_version 升版。
存量实例无缓存时由读取侧按需重建（幂等），无需重新初始化。

批次维度（``batch_id``）
------------------------
- 缓存文档按 ``{monitor_id, batch_id}`` 唯一，一个批次一份快照；重跑不会覆盖
  旧批次的绩效页数据，批次切换器可以直接读到历史批次的完整视图。
- 批次号跟随 ``monitor_states`` 文档：``rebuild`` / ``ensure`` 都以当前状态文档的
  ``batch_id`` 为准（显式传参优先），避免「状态取新批次、缓存写旧批次」的错配。
- 新批次首日会从父批次缓存继承历史持仓快照（仅 ``end_date <= 本次状态日`` 的），
  否则归因链路会在批次边界断档。
- 展示端点**只读不重建**：批次缓存缺失直接 404，重建只发生在跑批写入侧。
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from app.analysis.performance import compute_performance
from app.analysis.formulas.correlation import calculate_correlation_matrix
from app.analysis.metrics.asset_metrics import calculate_asset_metrics
from app.config.collections import COL_ASSETS, COL_MONITOR_PERFORMANCE_CACHE
from app.models.monitor import LEGACY_BATCH_ID
from app.monitor import config
from app.monitor.mongo_asset_codes import canonical_price_code
from app.monitor.monitor_runtime import (
    resolve_asset_class_for_monitor,
    resolve_asset_currency_for_monitor,
    resolve_monitor_asset_display_label,
)
from app.monitor.rebalance_marks import rebalance_dates_from_event_log

#: 缓存结构版本：字段口径变化时 +1，读取侧会自动重建
#: v3：绩效指标新增 365 自然日口径（读取侧现算，重建保证同一份缓存口径一致）
#: v4：归因口径修复——持仓快照支持事件日志回退；资产收益折算人民币（含汇率）；
#:     归因按 NAV 链接因子加总（Σ贡献 + 其他 = 区间收益），残差项改为「费用、汇率及其他」
#: v5：365 自然日口径修正——分母改为日历天数（原实现沿用交易日区间数，
#:     年化收益被放大 365/260 倍、波动率被放大 √(365/260) 倍）
SCHEMA_VERSION = 5

#: 资产日收益的年化因子（与全系统统一口径一致）
PERIODS_PER_YEAR = 260

#: 同一 monitor 的并发重建保护
_BUILD_LOCKS: Dict[str, asyncio.Lock] = {}


# ============================================================
# 基础工具
# ============================================================

def _num(value: Any, digits: Optional[int] = None) -> Optional[float]:
    """安全转 float：None/NaN/inf 一律返回 None（避免写出非法 JSON）。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, digits) if digits is not None else f


def _day(value: Any) -> str:
    return str(value or "").strip()[:10]


def _collection(service) -> Any:
    return service.db[COL_MONITOR_PERFORMANCE_CACHE]


def _batch_key(service, batch_id: Optional[str], state: Any = None) -> str:
    """缓存文档的批次键：显式传入 > 状态文档 > 宿主运行上下文 > ``legacy``。

    以状态文档为权威来源，保证「读的是哪个批次的状态，就写/读哪个批次的缓存」。
    """
    text = str(batch_id or "").strip()
    if not text:
        text = str(getattr(state, "batch_id", "") or "").strip()
    if not text:
        getter = getattr(service, "_current_batch_id", None)
        if callable(getter):
            try:
                text = str(getter() or "").strip()
            except Exception:  # noqa: BLE001
                text = ""
    return text or LEGACY_BATCH_ID


def _derive_nav_series(
    nav_history: List[Dict[str, Any]],
    rebalance_dates: set,
) -> List[Dict[str, Any]]:
    """净值历史 → 绩效页净值序列（补齐日收益、累计收益、回撤、调仓标记）。"""
    rows: List[Dict[str, Any]] = []
    first_nav: Optional[float] = None
    prev_nav: Optional[float] = None
    peak: Optional[float] = None

    for item in nav_history or []:
        date = _day(item.get("date"))
        nav = _num(item.get("nav"))
        if not date or nav is None:
            continue

        if first_nav is None:
            first_nav = nav
        peak = nav if peak is None else max(peak, nav)

        daily_return = _num(item.get("daily_return"))
        if daily_return is None and prev_nav is not None and prev_nav > 0:
            daily_return = nav / prev_nav - 1

        rows.append({
            "date": date,
            "nav": _num(nav, 4),
            "daily_return": _num(daily_return, 8),
            "cumulative_return": _num(nav / first_nav - 1, 8) if first_nav else None,
            "drawdown": _num(nav / peak - 1, 8) if peak else None,
            "is_rebalance": date in rebalance_dates,
        })
        prev_nav = nav

    return rows


def _model_nav_series(nav_history_model: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in nav_history_model or []:
        date = _day(item.get("date"))
        nav = _num(item.get("nav"))
        if date and nav is not None:
            rows.append({"date": date, "nav": _num(nav, 4)})
    return rows


def _normalize_weights(weights: Any) -> Dict[str, float]:
    """权重字典清洗：键统一为 str，值统一为小数（fraction）。"""
    out: Dict[str, float] = {}
    if not isinstance(weights, dict):
        return out
    for key, value in weights.items():
        w = _num(value)
        if w is None or key is None:
            continue
        code = str(key).strip()
        if code:
            out[code] = round(w, 8)
    return out


def _state_weights(state) -> Dict[str, float]:
    """状态的最新持仓权重（小数）：实际持仓市值/nav 优先，缺失时回退目标权重。"""
    nav = _num(state.nav)
    pc = _normalize_weights(state.positions_cny)
    if nav and nav > 0 and any(abs(v) > 1e-9 for v in pc.values()):
        return {k: v / nav for k, v in pc.items()}
    return _normalize_weights(state.target_weights)


def _positions_from_daily_rows(rows: List[dict]) -> List[Dict[str, Any]]:
    """单日推演结果 → 持仓快照（仅保留调仓日与最后一日，控制缓存体积）。"""
    snapshots: List[Dict[str, Any]] = []
    last_index = len(rows) - 1
    for i, row in enumerate(rows):
        weights = _normalize_weights(row.get("asset_weights"))
        if not weights:
            continue
        is_rebalance = bool(row.get("rebalance_executed") or row.get("is_rebalance"))
        if not is_rebalance and i != last_index:
            continue
        date = _day(row.get("date"))
        if not date:
            continue
        snapshots.append({
            "date": date,
            "nav": _num(row.get("nav"), 4),
            "weights": weights,
        })
    return snapshots


def _positions_from_weight_history(weight_history: List[dict]) -> List[Dict[str, Any]]:
    """组合穿透后权重历史（{date, 资产: 权重}）→ 持仓快照。"""
    snapshots: List[Dict[str, Any]] = []
    for item in weight_history or []:
        date = _day(item.get("date"))
        if not date:
            continue
        weights = _normalize_weights({k: v for k, v in item.items() if k != "date"})
        if weights:
            snapshots.append({"date": date, "nav": None, "weights": weights})
    return snapshots


def _positions_from_event_log(event_log: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """事件日志 → 持仓快照（独立引擎无操作指令时的权威来源）。

    只取实际执行的调仓事件（init / monthly / subjective / vol_reset execute）；
    trigger / skipped / pending 等阶段不构成持仓变更，不纳入。
    """
    snapshots: List[Dict[str, Any]] = []
    for ev in event_log or []:
        if not isinstance(ev, dict):
            continue
        etype = str(ev.get("type") or ev.get("event_type") or "").strip()
        stage = str(ev.get("stage") or "").strip()
        executed = etype in (
            "init", "monthly", "monthly_rebalance",
            "subjective", "subjective_rebalance", "vol_reset_execute",
        ) or (etype == "vol_reset" and stage in ("", "execute"))
        if not executed:
            continue
        date = _day(ev.get("date"))
        weights = _normalize_weights(ev.get("new_weights"))
        if date and weights:
            snapshots.append({"date": date, "nav": None, "weights": weights})
    return snapshots


def _positions_from_operations(
    ops: List[Dict[str, Any]],
    monitor_id: str,
    state_nav: Optional[float],
    state_weights: Dict[str, Any],
    state_date: str,
) -> List[Dict[str, Any]]:
    """已执行指令的目标权重 → 持仓快照（存量实例无逐日权重时的兜底）。

    组合监控只取组合层（strategy_key=portfolio）的穿透权重，避免子策略权重混入。
    """
    by_date: Dict[str, Dict[str, float]] = {}
    for op in sorted(ops or [], key=lambda o: _day(o.get("execute_date"))):
        if op.get("status") != "executed":
            continue
        key = str(op.get("strategy_key") or "")
        if key not in ("portfolio", monitor_id):
            continue
        weights = _normalize_weights(op.get("target_weights"))
        if not weights:
            continue
        date = _day(op.get("execute_date"))
        if date:
            by_date[date] = weights

    snapshots = [
        {"date": date, "nav": None, "weights": weights}
        for date, weights in sorted(by_date.items())
    ]

    latest = _normalize_weights(state_weights)
    if latest and state_date:
        snapshots.append({"date": state_date, "nav": state_nav, "weights": latest})
    return snapshots


def _merge_snapshots(
    existing: List[Dict[str, Any]],
    fresh: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """按日期合并持仓快照（新数据覆盖旧数据）。"""
    merged: Dict[str, Dict[str, Any]] = {}
    for item in (existing or []) + (fresh or []):
        date = _day(item.get("date"))
        weights = _normalize_weights(item.get("weights"))
        if not date or not weights:
            continue
        merged[date] = {
            "date": date,
            "nav": _num(item.get("nav"), 4),
            "weights": weights,
        }
    return [merged[d] for d in sorted(merged)]


def _build_asset_returns(
    prices_df: pd.DataFrame,
    fx_df: Optional[pd.DataFrame] = None,
    currency_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """价格面板 → 资产日收益率（百分数）序列。

    监控组合以人民币计价，非 CNH 资产先把汇率收益折算进资产日收益：
    ``r_cny = (1 + r_local) × (1 + r_fx) − 1``。
    汇率缺失时保留本币收益，不阻断缓存构建。
    """
    if prices_df is None or prices_df.empty:
        return []

    returns = prices_df.pct_change(fill_method=None)
    if fx_df is not None and not fx_df.empty and currency_map:
        fx = fx_df.copy()
        fx.index = [str(idx)[:10] for idx in fx.index]
        fx = fx[~fx.index.duplicated(keep="last")]
        fx = fx.reindex([str(idx)[:10] for idx in returns.index]).ffill()
        fx_ret = fx.pct_change(fill_method=None)
        for col in list(returns.columns):
            code = str(col)
            ccy = str(
                currency_map.get(code) or currency_map.get(canonical_price_code(code)) or "CNH"
            ).strip().upper()
            if ccy in ("CNH", "CNY") or ccy not in fx_ret.columns:
                continue
            local = returns[col]
            # 汇率缺失按 0 处理（视为汇率不变），保留本币收益，避免整段资产收益被吞
            fx_ret_col = fx_ret[ccy].reindex(local.index).fillna(0.0)
            returns[col] = (1.0 + local) * (1.0 + fx_ret_col) - 1.0

    rows: List[Dict[str, Any]] = []
    for ts, row in returns.iterrows():
        date = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else _day(ts)
        values: Dict[str, float] = {}
        for code, value in row.items():
            pct = _num(value)
            if pct is not None:
                values[str(code)] = round(pct * 100, 6)
        if values:
            rows.append({"date": date, "returns": values})
    return rows


def _asset_meta(
    names_lookup: Dict[str, str],
    master_info: Dict[str, Dict[str, str]],
    asset_keys: List[str],
) -> List[Dict[str, str]]:
    meta: List[Dict[str, str]] = []
    for code in asset_keys:
        info = master_info.get(code) or master_info.get(canonical_price_code(code)) or {}
        name = resolve_monitor_asset_display_label(code, names_lookup)
        if (not name or name == code) and info.get("name"):
            name = info["name"]
        meta.append({
            "code": code,
            "name": name,
            "asset_class": (
                resolve_asset_class_for_monitor(code)
                or info.get("asset_class")
                or "未分类"
            ),
            "currency": info.get("currency") or resolve_asset_currency_for_monitor(code),
        })
    return meta


#: 资产主数据大类 → 监控页展示口径
_ASSET_CLASS_LABEL = {
    "权益": "权益",
    "固收": "固定收益",
    "商品": "大宗商品",
    "货币": "货币",
    "另类": "另类",
}


async def _load_asset_master_info(
    service, asset_keys: List[str]
) -> Dict[str, Dict[str, str]]:
    """一次查询资产主数据：code → {name, asset_class, currency}，用于展示兜底。"""
    codes: set = set()
    for key in asset_keys or []:
        s = str(key or "").strip()
        if s:
            codes.add(s)
            codes.add(canonical_price_code(s))
    if not codes:
        return {}

    info: Dict[str, Dict[str, str]] = {}
    try:
        cursor = service.db[COL_ASSETS].find({"code": {"$in": list(codes)}})
        async for doc in cursor:
            code = str(doc.get("code") or "").strip()
            if not code:
                continue
            asset_class = str(doc.get("asset_class") or "").strip()
            info[code] = {
                "name": str(doc.get("name") or "").strip(),
                "asset_class": _ASSET_CLASS_LABEL.get(asset_class, asset_class),
                "currency": str(doc.get("currency") or "").strip(),
            }
    except Exception as exc:  # pragma: no cover - 主数据缺失不阻断绩效页
        logger.warning(f"绩效缓存读取资产主数据失败: {exc}")
    return info


def _asset_keys_from_state(
    state,
    extra_weight_maps: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    keys: List[str] = []
    seen = set()
    sources: List[Dict[str, Any]] = [state.positions_cny or {}, state.target_weights or {}]
    for wmap in extra_weight_maps or []:
        sources.append(wmap or {})
    for source in sources:
        for key in source.keys():
            code = str(key).strip()
            if code and code not in seen:
                seen.add(code)
                keys.append(code)
    return keys


async def _load_prices_for_assets(service, asset_keys: List[str]) -> pd.DataFrame:
    """按资产列表从行情库加载价格面板（缓存重建兜底路径）。"""
    try:
        prices_df = await service.async_provider.load_prices(asset_columns=list(asset_keys))
    except Exception as exc:  # pragma: no cover - 行情缺失不应阻断绩效页
        logger.warning(f"绩效缓存加载行情失败: assets={len(asset_keys)}, error={exc}")
        return pd.DataFrame()

    if prices_df is None or prices_df.empty:
        return pd.DataFrame()

    keep = [c for c in prices_df.columns if str(c) in set(asset_keys)]
    if keep and len(keep) != len(prices_df.columns):
        prices_df = prices_df[keep]
    return prices_df


# ============================================================
# 缓存构建
# ============================================================

async def rebuild_performance_cache(
    service,
    monitor_id: str,
    daily_rows: Optional[List[dict]] = None,
    weight_history: Optional[List[dict]] = None,
    prices_df: Optional[pd.DataFrame] = None,
    force_prices: bool = False,
    batch_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """重建并落库某个监控实例当前批次的绩效缓存（幂等）。

    Args:
        service: MonitorService 实例
        monitor_id: 监控实例 ID（实盘策略即策略模型 ID）
        daily_rows: 本次推演逐日结果（初始化/日常运行传入，用于精确持仓快照）
        weight_history: 组合穿透后权重历史（组合监控传入）
        prices_df: 已加载的价格面板（避免重复从 Mongo 读取）
        force_prices: 无缓存且未传 prices_df 时，是否从行情库加载价格
        batch_id: 目标批次号；缺省跟随状态文档/宿主运行上下文（写入侧必为本次批次）
    """
    state = await service.get_state(monitor_id)
    batch = _batch_key(service, batch_id, state)
    if not state:
        await _collection(service).delete_one({"monitor_id": monitor_id, "batch_id": batch})
        return None

    state_date = _day(state.date)
    collection = _collection(service)
    existing = await collection.find_one({"monitor_id": monitor_id, "batch_id": batch})
    if not existing:
        # 新批次首日：继承历史批次的持仓快照，避免归因在批次边界断档。
        # 只取 end_date <= 本次状态日的缓存，不会把更晚批次的数据拉进来。
        existing = await collection.find_one(
            {
                "monitor_id": monitor_id,
                "batch_id": {"$ne": batch},
                "end_date": {"$lte": state_date},
            },
            sort=[("updated_at", -1)],
        )
    # 旧版本缓存的快照/收益口径与当前不一致（如 v3 本币收益、操作指令兜底快照），不跨版本复用
    existing = existing if (existing or {}).get("schema_version") == SCHEMA_VERSION else None

    # 1) 资产键：状态持仓/权重 ∪ 各类快照里出现的键
    extra_maps: List[Dict[str, Any]] = []
    for row in daily_rows or []:
        extra_maps.append(row.get("asset_weights") or {})
    for item in weight_history or []:
        extra_maps.append({k: v for k, v in item.items() if k != "date"})
    for item in (existing or {}).get("positions_history") or []:
        extra_maps.append(item.get("weights") or {})
    # 事件日志里出现过的历史权重（独立引擎无操作指令时，快照由此重建）
    for item in _positions_from_event_log(state.event_log):
        extra_maps.append(item.get("weights") or {})

    asset_keys = _asset_keys_from_state(state, extra_maps)
    if not asset_keys:
        rt = await service._runtime_for_reads(monitor_id)
        asset_keys = list(rt.asset_list) if rt else list(config.ASSET_LIST)

    # 2) 展示名/类别/币种（主数据兜底策略自定义资产）
    model = None
    if service._is_strategy_model_monitor_id(monitor_id):
        from app.services.strategy_model_service import StrategyModelService
        model = await StrategyModelService().get_model(monitor_id)
    names_lookup = await service._asset_master_names_by_code(model, asset_keys)
    master_info = await _load_asset_master_info(service, asset_keys)

    # 3) 调仓日集合（净值图标记 + 持仓快照）
    # 故意不限定批次：调仓日与历史权重快照需要完整时间轴，而指令幂等键已含
    # batch_id，跨批次读取只会拿到同一次调仓在不同批次里的重复记录，_merge_snapshots 按日期去重。
    ops = await service.operation_service.list_by_monitor(monitor_id, limit=5000)
    rebalance_dates = {
        _day(op.get("execute_date"))
        for op in ops
        if op.get("status") == "executed" and _day(op.get("execute_date"))
    }
    if not rebalance_dates:
        # 存量实例没有操作指令记录：回退事件日志口径，与 /monitor/performance 一致
        rebalance_dates = set(rebalance_dates_from_event_log(state.event_log))

    # 4) 持仓快照：逐日（精确）→ 组合权重历史 → 事件日志/已执行指令兜底
    fresh_snapshots: List[Dict[str, Any]] = []
    if daily_rows:
        fresh_snapshots = _positions_from_daily_rows(daily_rows)
    elif weight_history:
        fresh_snapshots = _positions_from_weight_history(weight_history)

    latest_weights = _state_weights(state)
    if not fresh_snapshots:
        # 独立引擎无步进指令事件：事件日志是唯一完整的调仓权重来源；
        # 操作指令（含主观调仓）覆盖同日权重。缺失时归因会退回「覆盖不足」提示，
        # 不把区间收益当作单一「现金」贡献展示。
        fresh_snapshots = _merge_snapshots(
            _positions_from_event_log(state.event_log),
            _positions_from_operations(
                ops,
                monitor_id,
                _num(state.nav, 4),
                latest_weights,
                state_date,
            ),
        )
    # 保证最新一日有快照（持仓展示以「区间末最近快照」为准）
    if latest_weights and state_date and not any(s["date"] == state_date for s in fresh_snapshots):
        fresh_snapshots.append({"date": state_date, "nav": _num(state.nav, 4), "weights": latest_weights})

    positions_history = _merge_snapshots(
        (existing or {}).get("positions_history"), fresh_snapshots
    )

    # 5) 资产日收益：人民币口径（非 CNH 资产先折算汇率收益）
    currency_map: Dict[str, str] = {}
    for code in asset_keys:
        info = master_info.get(code) or master_info.get(canonical_price_code(code)) or {}
        ccy = info.get("currency") or resolve_asset_currency_for_monitor(code) or "CNH"
        ccy = str(ccy).strip().upper()
        currency_map[code] = ccy
        # 行情面板列名可能是交易码规范形式，与资产键不同名时同样能命中币种
        currency_map.setdefault(canonical_price_code(code), ccy)

    fx_df: Optional[pd.DataFrame] = None
    provider = getattr(service, "async_provider", None)
    if provider is not None:
        try:
            fx_df = await provider.load_fx()
        except Exception as exc:  # pragma: no cover - 汇率缺失保留本币口径
            logger.warning(f"绩效缓存加载汇率失败（资产收益保留本币口径）: {exc}")

    asset_returns: List[Dict[str, Any]] = []
    if prices_df is not None and not prices_df.empty:
        asset_returns = _build_asset_returns(prices_df, fx_df, currency_map)
    else:
        cached_returns = (existing or {}).get("asset_returns") or []
        cached_end = _day((cached_returns[-1] if cached_returns else {}).get("date"))
        cached_codes = set((cached_returns[-1].get("returns") or {}).keys()) if cached_returns else set()
        if cached_returns and cached_end == state_date and cached_codes.issuperset(set(asset_keys)):
            asset_returns = cached_returns
        elif force_prices or not cached_returns:
            prices = await _load_prices_for_assets(service, asset_keys)
            asset_returns = _build_asset_returns(prices, fx_df, currency_map)
        else:
            asset_returns = cached_returns

    # 6) 落库
    doc = {
        "monitor_id": monitor_id,
        "batch_id": batch,
        "schema_version": SCHEMA_VERSION,
        "strategy_model_id": str(state.strategy_model_id or "") or None,
        "start_date": _day((state.nav_history[0] if state.nav_history else {}).get("date")),
        "end_date": state_date,
        "updated_at": datetime.now(),
        "meta": {"assets": _asset_meta(names_lookup, master_info, asset_keys)},
        "nav_series": _derive_nav_series(state.nav_history, rebalance_dates),
        "nav_series_model": _model_nav_series(state.nav_history_model),
        "positions_history": positions_history,
        "asset_returns": asset_returns,
    }
    await collection.replace_one(
        {"monitor_id": monitor_id, "batch_id": batch}, doc, upsert=True
    )

    logger.info(
        "绩效缓存已重建: monitor=%s, batch=%s, %s~%s, nav=%d, snapshots=%d, returns=%d, assets=%d",
        monitor_id, batch, doc["start_date"], doc["end_date"],
        len(doc["nav_series"]), len(positions_history), len(asset_returns), len(asset_keys),
    )
    return doc


async def ensure_performance_cache(
    service,
    monitor_id: str,
    force_rebuild: bool = False,
    batch_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """读取缓存；缺失/过期时重建（同一 monitor+批次串行，避免并发重复计算）。

    ``batch_id`` 缺省时跟随状态文档解析出的展示批次（最新 completed）。
    """
    state = await service.get_state(monitor_id, batch_id=batch_id)
    if not state:
        return None

    batch = _batch_key(service, batch_id, state)
    state_date = _day(state.date)
    collection = _collection(service)

    def _fresh(doc: Optional[dict]) -> bool:
        return bool(
            doc
            and doc.get("schema_version") == SCHEMA_VERSION
            and _day(doc.get("end_date")) == state_date
        )

    query = {"monitor_id": monitor_id, "batch_id": batch}
    doc = await collection.find_one(query)
    if not force_rebuild and _fresh(doc):
        return doc

    lock = _BUILD_LOCKS.setdefault(f"{monitor_id}::{batch}", asyncio.Lock())
    async with lock:
        doc = await collection.find_one(query)
        if not force_rebuild and _fresh(doc):
            return doc
        return await rebuild_performance_cache(
            service, monitor_id, force_prices=True, batch_id=batch
        )


# ============================================================
# 区间读取（绩效页统一数据）
# ============================================================

def _period_metrics(nav_rows: List[Dict[str, Any]],
                    rebalance_dates: Optional[List[str]] = None) -> Dict[str, Any]:
    """区间绩效指标（与监控绩效接口同口径：年化因子 260、CAGR、几何夏普）。

    Args:
        nav_rows: 区间内的净值序列（带 is_rebalance 标记）
        rebalance_dates: 区间内的调仓执行日，作为胜率的周期边界；
            传空列表时胜率按 0 返回
    """
    empty = {
        "period_return": None,
        "annual_return": None,
        "annual_volatility": None,
        "max_drawdown": None,
        "sharpe_ratio": None,
        "calmar_ratio": None,
        "annual_return_365": None,
        "annual_volatility_365": None,
        "sharpe_ratio_365": None,
        "calmar_ratio_365": None,
        "win_rate": None,
        "trading_days": 0,
        "start_nav": None,
        "end_nav": None,
    }
    if len(nav_rows) < 2:
        if len(nav_rows) == 1:
            empty["start_nav"] = empty["end_nav"] = nav_rows[0]["nav"]
            empty["trading_days"] = 1
        return empty

    series = pd.Series(
        [r["nav"] for r in nav_rows],
        index=pd.to_datetime([r["date"] for r in nav_rows]),
        dtype="float64",
    )
    perf = compute_performance(
        series,
        risk_free_rate=config.RISK_FREE_RATE,
        rebalance_dates=rebalance_dates,
    )
    return {
        "period_return": _round(perf.total_return, 8),
        "annual_return": _round(perf.annual_return, 8),
        "annual_volatility": _round(perf.annual_volatility, 8),
        "max_drawdown": _round(perf.max_drawdown, 8),
        "sharpe_ratio": _round(perf.sharpe_ratio, 6),
        "calmar_ratio": _round(perf.calmar_ratio, 6),
        "annual_return_365": _round(perf.annual_return_365, 8),
        "annual_volatility_365": _round(perf.annual_volatility_365, 8),
        "sharpe_ratio_365": _round(perf.sharpe_ratio_365, 6),
        "calmar_ratio_365": _round(perf.calmar_ratio_365, 6),
        "win_rate": _round(perf.win_rate, 6),
        "trading_days": len(nav_rows),
        "start_nav": nav_rows[0]["nav"],
        "end_nav": nav_rows[-1]["nav"],
    }


def _round(value: Any, digits: int) -> Optional[float]:
    return _num(value, digits)


def _pick_snapshot(
    positions_history: List[Dict[str, Any]],
    target_date: str,
) -> Optional[Dict[str, Any]]:
    """取不晚于目标日期的最近持仓快照；若区间早于全部快照，则取最早一条。"""
    chosen: Optional[Dict[str, Any]] = None
    for item in positions_history or []:
        if _day(item.get("date")) <= target_date:
            chosen = item
        else:
            break
    if chosen is None and positions_history:
        chosen = positions_history[0]
    return chosen


def _returns_on(asset_returns: List[Dict[str, Any]], date: str) -> Dict[str, float]:
    """取指定日期的资产日收益；缺失时向前找最近一个有效日。"""
    fallback: Dict[str, float] = {}
    for row in asset_returns or []:
        row_date = _day(row.get("date"))
        if row_date > date:
            break
        if row.get("returns"):
            fallback = row["returns"]
            if row_date == date:
                return fallback
    return fallback


def _positions_payload(
    snapshot: Optional[Dict[str, Any]],
    meta_assets: List[Dict[str, str]],
    asset_returns: List[Dict[str, Any]],
    nav_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """持仓快照 → 绩效页持仓表（权重为百分数、当日涨跌为百分数）。"""
    if not snapshot:
        return {"date": None, "nav": None, "count": 0, "items": [], "by_class": [], "total_leverage": 0}

    snap_date = _day(snapshot.get("date"))
    weights = _normalize_weights(snapshot.get("weights"))
    nav_value = _num(snapshot.get("nav"))
    if nav_value is None and nav_rows:
        for row in nav_rows:
            if row["date"] <= snap_date:
                nav_value = row["nav"]
    if nav_value is None and nav_rows:
        nav_value = nav_rows[-1]["nav"]

    daily_changes = _returns_on(asset_returns, snap_date)
    meta_map = {item["code"]: item for item in meta_assets or []}

    items: List[Dict[str, Any]] = []
    by_class: Dict[str, float] = {}
    for code, weight in weights.items():
        if abs(weight) <= 1e-9:
            continue  # 空仓资产不入表
        meta = meta_map.get(code) or {}
        weight_pct = weight * 100
        asset_class = meta.get("asset_class") or resolve_asset_class_for_monitor(code) or "未分类"
        by_class[asset_class] = by_class.get(asset_class, 0.0) + weight_pct
        items.append({
            "code": code,
            "name": meta.get("name") or resolve_monitor_asset_display_label(code, {}),
            "asset_class": asset_class,
            "currency": meta.get("currency") or resolve_asset_currency_for_monitor(code),
            "current_weight": _num(weight_pct, 4),
            "value_cnh": _num((nav_value or 0.0) * weight, 2),
            "daily_change": _num(daily_changes.get(code), 4),
        })
    items.sort(key=lambda x: abs(x["current_weight"] or 0), reverse=True)

    total_leverage = sum(abs(v) for v in weights.values())
    return {
        "date": snap_date,
        "nav": nav_value,
        "total_leverage": _num(total_leverage, 4),
        # 持仓资产数：非零权重计数（与总览页 /monitor/performance 的 position_count 同口径）
        "count": len(items),
        "items": items,
        "by_class": [
            {"category": key, "weight": _num(value, 4)}
            for key, value in sorted(by_class.items(), key=lambda kv: -abs(kv[1]))
        ],
    }


def _attribution_payload(
    positions_history: List[Dict[str, Any]],
    positions: Dict[str, Any],
    meta_assets: List[Dict[str, str]],
    asset_returns: List[Dict[str, Any]],
    nav_rows: List[Dict[str, Any]],
    range_start: str,
    range_end: str,
) -> Dict[str, Any]:
    """区间收益归因（NAV 链接多期归因，人民币口径），单位为百分点。

    口径
    ----
    - 日贡献 ``c(i,t) = w(i,t-1) × r(i,t)``：权重取「早于当日」的最近调仓快照，
      即调仓次日生效，与独立引擎「当日损益用旧持仓、收盘后调仓」的执行顺序一致；
    - 链接因子 ``λ(t) = NAV(t-1) / NAV(0)``，满足 ``Σ λ(t)·r(t) ≡ NAV(T)/NAV(0) − 1``，
      故各资产贡献与残差项相加精确等于区间收益（多期归因行业规范）；
    - 行项覆盖缓存内全部候选资产：区间内从未入围（权重恒 0）的资产同样出行，
      平均权重与收益贡献显示 0，区间涨跌按全区间日收益复利计算；
    - 资产收益已折算人民币（含汇率），残差项由费用、杠杆资金成本与执行/数据偏差构成。

    持仓快照覆盖不足一半交易日时不输出资产贡献，只返回 warning，
    避免把未归因的区间收益误标为某一类资产的贡献。
    """
    empty = {
        "date": range_end,
        "start_date": range_start,
        "end_date": range_end,
        "trading_days": 0,
        "covered_days": 0,
        "total_return": None,
        "start_nav": None,
        "end_nav": None,
        "items": [],
        "other_note": None,
        "warning": "区间内净值不足两个交易日，无法计算收益归因",
    }
    if not nav_rows or len(nav_rows) < 2:
        return empty

    start_nav = _num(nav_rows[0].get("nav"))
    end_nav = _num(nav_rows[-1].get("nav"))
    if start_nav is None or end_nav is None or start_nav <= 0:
        return {**empty, "warning": "净值序列缺失，无法计算收益归因"}

    total_return = end_nav / start_nav - 1.0

    # 资产日收益：date -> {code: 小数收益}
    returns_map: Dict[str, Dict[str, float]] = {}
    for row in asset_returns or []:
        rets = row.get("returns")
        if rets:
            returns_map[_day(row.get("date"))] = rets

    # 持仓权重时间线（升序）；调仓次日生效 → 严格早于当日才切换权重
    snapshots = sorted(
        [item for item in positions_history or [] if item.get("date")],
        key=lambda item: _day(item["date"]),
    )
    snap_dates = [_day(item["date"]) for item in snapshots]
    snap_index = -1
    weights: Dict[str, float] = {}

    contributions: Dict[str, float] = {}
    weight_sum: Dict[str, float] = {}
    weight_days: Dict[str, int] = {}
    compounded: Dict[str, float] = {}
    expected_days = 0
    covered_days = 0
    prev_nav = start_nav

    for i in range(1, len(nav_rows)):
        day = _day(nav_rows[i]["date"])
        nav = _num(nav_rows[i].get("nav"))
        if nav is None or prev_nav <= 0:
            continue
        nav_ret = nav / prev_nav - 1.0
        link = prev_nav / start_nav  # NAV 链接因子：使日贡献可跨期相加
        expected_days += 1

        while snap_index + 1 < len(snap_dates) and snap_dates[snap_index + 1] < day:
            snap_index += 1
            weights = _normalize_weights(snapshots[snap_index].get("weights"))

        day_returns = returns_map.get(day) or {}
        day_changes: Dict[str, float] = {}
        if weights and day_returns:
            for code, weight in weights.items():
                change_pct = day_returns.get(code)
                if change_pct is None:
                    continue
                change = change_pct / 100.0  # 缓存内收益率为百分数
                day_changes[code] = change
                contributions[code] = contributions.get(code, 0.0) + weight * change * link
                weight_sum[code] = weight_sum.get(code, 0.0) + weight
                weight_days[code] = weight_days.get(code, 0) + 1
                compounded[code] = compounded.get(code, 1.0) * (1.0 + change)
        if day_changes:
            covered_days += 1

        # 权重随净值漂移，下一调仓日由快照重置；用实际净值收益归一化以贴合引擎持仓口径
        if day_changes and weights and nav_ret > -1.0:
            base = 1.0 + nav_ret
            weights = {
                code: (weight * (1.0 + day_changes[code]) / base if code in day_changes else weight)
                for code, weight in weights.items()
            }
        prev_nav = nav

    coverage = covered_days / expected_days if expected_days else 0.0
    warning: Optional[str] = None
    if expected_days == 0:
        warning = "区间内净值不足两个有效交易日，无法计算收益归因"
    elif covered_days == 0:
        warning = "区间内无可用持仓快照，无法计算收益归因"
    elif coverage < 0.5:
        warning = f"持仓快照仅覆盖 {covered_days}/{expected_days} 个交易日（{coverage:.0%}），不足以支撑区间归因"
    elif coverage < 0.999:
        warning = f"持仓快照覆盖 {covered_days}/{expected_days} 个交易日，未覆盖部分计入「费用、汇率及其他」"

    meta_map = {item["code"]: item for item in meta_assets or []}
    holding_map = {item["code"]: item for item in positions.get("items") or []}
    items: List[Dict[str, Any]] = []
    if coverage >= 0.5:
        # 候选全集：缓存资产全表 ∪ 实际产生过贡献的代码。
        # 未入围（区间内权重恒 0）的资产同样出行，权重/贡献显示 0，保证底层资产清单完整。
        universe: List[str] = []
        seen_codes: set = set()
        for item in meta_assets or []:
            code = str(item.get("code") or "").strip()
            if code and code not in seen_codes:
                seen_codes.add(code)
                universe.append(code)
        for code in contributions:
            if code not in seen_codes:
                seen_codes.add(code)
                universe.append(code)

        zero_rows: List[Dict[str, Any]] = []
        for code in universe:
            holding = holding_map.get(code) or {}
            meta = meta_map.get(code) or {}
            name = holding.get("name") or meta.get("name") \
                or resolve_monitor_asset_display_label(code, {})
            asset_class = holding.get("asset_class") or meta.get("asset_class") \
                or resolve_asset_class_for_monitor(code) or "未分类"
            currency = holding.get("currency") or meta.get("currency") \
                or resolve_asset_currency_for_monitor(code)
            pnl = contributions.get(code)
            shown_contrib = _num(pnl * 100.0, 4) if pnl is not None else None
            if shown_contrib:
                days = weight_days.get(code) or 0
                items.append({
                    "code": code,
                    "name": name,
                    "asset_class": asset_class,
                    "currency": currency,
                    "weight": _num(weight_sum.get(code, 0.0) / days * 100, 4) if days else None,
                    "period_return": _num(compounded.get(code, 1.0) - 1.0, 4),
                    "contribution": shown_contrib,
                })
            else:
                # 贡献显示值为 0（含未入围、权重恒 0）的资产：置底展示；
                # 区间涨跌按资产自身口径：曾持有取持仓期复利，从未持有取全区间复利
                days = weight_days.get(code) or 0
                if days:
                    weight = _num(weight_sum.get(code, 0.0) / days * 100, 4)
                    period_return = _num(compounded.get(code, 1.0) - 1.0, 4)
                else:
                    acc = 1.0
                    has_data = False
                    for rets in returns_map.values():
                        pct = rets.get(code)
                        if pct is None:
                            continue
                        acc *= 1.0 + pct / 100.0
                        has_data = True
                    weight = 0.0
                    period_return = _num(acc - 1.0, 4) if has_data else None
                zero_rows.append({
                    "code": code,
                    "name": name,
                    "asset_class": asset_class,
                    "currency": currency,
                    "weight": weight,
                    "period_return": period_return,
                    "contribution": 0.0,
                })

        items.sort(key=lambda x: x["contribution"] or 0, reverse=True)
        # 未入围资产（贡献 0）统一排在负贡献之后、残差之前
        zero_rows.sort(key=lambda x: str(x["name"] or x["code"]))
        items.extend(zero_rows)

        # 残差用「展示值」倒推，保证表格上各贡献与残差相加 = 区间收益
        shown_sum = sum(item["contribution"] or 0.0 for item in items)
        residual = total_return * 100.0 - shown_sum
        if abs(residual) >= 0.01:
            # 配平项固定放在末尾：= 区间收益 − 各资产贡献
            items.append({
                "code": "__other__",
                "name": "费用、汇率及其他",
                "asset_class": "其他",
                "currency": None,
                "weight": None,
                "period_return": None,
                "contribution": _num(residual, 4),
            })

    return {
        "date": range_end,
        "start_date": range_start,
        "end_date": range_end,
        "trading_days": len(nav_rows),
        "covered_days": covered_days,
        "total_return": _num(total_return * 100.0, 4),
        "start_nav": _num(start_nav, 4),
        "end_nav": _num(end_nav, 4),
        "items": items,
        "other_note": "区间收益 − 各资产贡献；含交易与复制费用、杠杆资金成本、汇率折算、未投资现金及执行/数据偏差",
        "warning": warning,
    }


def _asset_analysis_payload(
    asset_returns: List[Dict[str, Any]],
    meta_assets: List[Dict[str, str]],
    start: str,
    end: str,
    focus_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """区间内底层资产相关性矩阵 + 年化波动率（年化因子 260）。

    focus_codes: 当前持仓资产；资产数 ≥3 时仅分析持仓，避免大策略热力图过密。
    """
    empty = {
        "start_date": start,
        "end_date": end,
        "trading_days": 0,
        "correlation": {"matrix": {}, "asset_info": [], "method": "pearson",
                        "start_date": start, "end_date": end},
        "metrics": [],
    }
    rows = [r for r in asset_returns or [] if start <= _day(r.get("date")) <= end and r.get("returns")]
    if len(rows) < 2:
        return empty

    dates = [_day(r["date"]) for r in rows]
    # 索引必须是 DatetimeIndex：calculate_asset_metrics 的 365 自然日口径
    # （calendar_span_days）要求可换算日历天数，字符串索引会抛 TypeError。
    frame = pd.DataFrame([r["returns"] for r in rows], index=pd.to_datetime(dates))
    # 与 /analysis 接口口径一致：区间内收益率序列（首日无前收，不参与统计）
    frame = frame.iloc[1:]
    if frame.empty:
        return empty

    valid_codes = [c for c in frame.columns if frame[c].notna().sum() >= 2]
    focus = [c for c in (focus_codes or []) if c in valid_codes]
    if len(focus) >= 3:
        valid_codes = focus
    frame = frame[valid_codes]
    if frame.empty:
        return empty

    name_map = {item["code"]: item["name"] for item in meta_assets or []}

    corr = calculate_correlation_matrix(frame, method="pearson")
    matrix: Dict[str, Dict[str, float]] = {}
    for row_code in corr.index:
        matrix[str(row_code)] = {
            str(col): (_num(corr.loc[row_code, col], 6) or 0.0) for col in corr.columns
        }

    metrics: List[Dict[str, Any]] = []
    for code in valid_codes:
        series = frame[code].dropna()
        if len(series) < 2:
            continue
        nav = (1 + series / 100).cumprod()
        try:
            m = calculate_asset_metrics(nav, code, freq_factor=PERIODS_PER_YEAR)
        except ValueError:
            continue
        metrics.append({
            "thscode": code,
            "name": name_map.get(code, code),
            "annual_return": _num(m.annualized_return, 6),
            "annual_volatility": _num(m.annualized_volatility, 6),
            "max_drawdown": _num(m.max_drawdown, 6),
            "sharpe_ratio": _num(m.sharpe_ratio, 6),
            "total_return": _num(m.cumulative_return, 6),
            "annual_return_365": _num(m.annualized_return_365, 6),
            "annual_volatility_365": _num(m.annualized_volatility_365, 6),
            "sharpe_ratio_365": _num(m.sharpe_ratio_365, 6),
        })
    metrics.sort(key=lambda x: x["annual_volatility"] or 0, reverse=True)

    return {
        "start_date": start,
        "end_date": end,
        "trading_days": len(frame),
        "correlation": {
            "matrix": matrix,
            "asset_info": [
                {"thscode": str(code), "name": name_map.get(str(code), str(code))}
                for code in corr.columns
            ],
            "method": "pearson",
            "start_date": start,
            "end_date": end,
        },
        "metrics": metrics,
    }


def _filter_rows(
    rows: List[Dict[str, Any]],
    start: str,
    end: str,
) -> List[Dict[str, Any]]:
    return [r for r in rows or [] if start <= _day(r.get("date")) <= end]


def _rebase_nav_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按所选区间重算累计收益与回撤；区间首日无前收，日收益置空。"""
    out: List[Dict[str, Any]] = []
    first_nav: Optional[float] = None
    peak: Optional[float] = None
    prev_nav: Optional[float] = None
    for item in rows or []:
        nav = _num(item.get("nav"))
        if nav is None:
            continue
        if first_nav is None:
            first_nav = nav
        peak = nav if peak is None else max(peak, nav)
        daily = None
        if prev_nav is not None and prev_nav > 0:
            daily = _num(nav / prev_nav - 1, 8)
        out.append({
            "date": item["date"],
            "nav": nav,
            "daily_return": daily,
            "cumulative_return": _num(nav / first_nav - 1, 8) if first_nav else None,
            "drawdown": _num(nav / peak - 1, 8) if peak else None,
            "is_rebalance": bool(item.get("is_rebalance")),
        })
        prev_nav = nav
    return out


# ============================================================
# 纯读表投影（展示侧唯一入口）
# ============================================================
# 以下三个 ``project_*`` 函数只吃「已落库的缓存文档」，不碰行情库、不触发重建，
# 因此可以被 app/services/monitor_query_service.py（纯读表服务）直接复用。
# 缓存缺失时返回 None，由展示端点直接 404 —— 重建只发生在跑批写入侧。

_TRACK_FIELDS = {"actual": "nav_series", "model": "nav_series_model"}


def project_track_rows(
    cache: Dict[str, Any],
    track: str = "actual",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """按区间截取某一条轨的净值序列（``actual`` 重算累计收益/回撤，``model`` 原样）。"""
    field = _TRACK_FIELDS.get(track, "nav_series")
    full_start = _day(cache.get("start_date"))
    full_end = _day(cache.get("end_date"))
    range_start, range_end = _clamp_range(cache, start, end, full_start, full_end)
    rows = _filter_rows(cache.get(field), range_start, range_end)
    return _rebase_nav_rows(rows) if track == "actual" else rows


def project_track_metrics(
    cache: Dict[str, Any],
    track: str = "actual",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, Any]:
    """区间绩效指标（小数形式）。

    实际轨用 ``is_rebalance`` 标记作为胜率周期边界；模型轨无逐日指令记录，
    显式传空列表（胜率 0），与 ``get_dual_performance`` 的口径一致。
    """
    rows = project_track_rows(cache, track, start, end)
    marks = [r["date"] for r in rows if r.get("is_rebalance")] if track == "actual" else []
    return _period_metrics(rows, marks)


def _clamp_range(
    cache: Dict[str, Any],
    start: Optional[str],
    end: Optional[str],
    full_start: str,
    full_end: str,
) -> tuple:
    """把请求区间夹到缓存数据范围内，防止越界导致空图。"""
    req_start = _day(start) or full_start
    req_end = _day(end) or full_end
    range_start = max(req_start, full_start) if full_start else req_start
    range_end = min(req_end, full_end) if full_end else req_end
    if range_start > range_end:
        range_start, range_end = range_end, range_start
    return range_start, range_end


def project_panel_from_cache(
    cache: Dict[str, Any],
    monitor_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """缓存文档 → 绩效页统一数据（净值 + 指标 + 持仓 + 归因 + 资产分析）。"""
    if not cache:
        return None

    full_start = _day(cache.get("start_date"))
    full_end = _day(cache.get("end_date"))
    req_start = _day(start) or full_start
    req_end = _day(end) or full_end
    range_start, range_end = _clamp_range(cache, start, end, full_start, full_end)

    nav_rows = _rebase_nav_rows(_filter_rows(cache.get("nav_series"), range_start, range_end))
    model_rows = _filter_rows(cache.get("nav_series_model"), range_start, range_end)
    meta_assets = (cache.get("meta") or {}).get("assets") or []
    # 区间内已执行调仓日：由缓存写入的 is_rebalance 标记提取，作为胜率周期边界
    range_rebalance_dates = [r["date"] for r in nav_rows if r.get("is_rebalance")]

    snapshot = _pick_snapshot(cache.get("positions_history") or [], range_end)
    positions = _positions_payload(
        snapshot, meta_assets, cache.get("asset_returns") or [], nav_rows
    )
    attribution = _attribution_payload(
        cache.get("positions_history") or [], positions, meta_assets,
        cache.get("asset_returns") or [], nav_rows, range_start, range_end,
    )
    analysis = _asset_analysis_payload(
        cache.get("asset_returns") or [], meta_assets, range_start, range_end,
        focus_codes=[item["code"] for item in positions.get("items") or []],
    )

    updated_at = cache.get("updated_at")
    return {
        "monitor_id": monitor_id,
        "batch_id": str(cache.get("batch_id") or LEGACY_BATCH_ID),
        "range": {
            "start": range_start,
            "end": range_end,
            "full_start": full_start,
            "full_end": full_end,
            "clamped": (range_start != req_start or range_end != req_end),
        },
        "nav_history": nav_rows,
        "nav_history_model": model_rows,
        "has_model_track": bool(model_rows),
        "metrics": _period_metrics(nav_rows, range_rebalance_dates),
        "positions": positions,
        "attribution": attribution,
        "asset_analysis": analysis,
        "cache_updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
    }


def project_positions_from_cache(
    cache: Dict[str, Any],
    end: Optional[str] = None,
) -> Dict[str, Any]:
    """缓存文档 → 总览页持仓明细（与 ``get_positions`` 同字段名）。

    ``end`` 为空时取缓存 ``end_date``，即「区间末最近一次持仓快照」。
    """
    if not cache:
        return {"positions": [], "total_leverage": 0, "nav": None, "date": None}
    target = _day(end) or _day(cache.get("end_date"))
    meta_assets = (cache.get("meta") or {}).get("assets") or []
    nav_rows = cache.get("nav_series") or []
    snapshot = _pick_snapshot(cache.get("positions_history") or [], target)
    payload = _positions_payload(snapshot, meta_assets, cache.get("asset_returns") or [], nav_rows)
    leverage = _num((payload.get("total_leverage") or 0) / 100.0, 4)
    return {
        "positions": payload.get("items") or [],
        "total_leverage": leverage,
        "nav": payload.get("nav"),
        "date": payload.get("date"),
        "by_class": payload.get("by_class") or [],
    }


def project_daily_attribution_from_cache(
    cache: Dict[str, Any],
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """缓存文档 → 单日损益归因（与 ``get_daily_attribution`` 同字段名）。

    口径：``contribution = w(i, t-1) × r(i, t) × NAV(t-1)``，权重取「严格早于当日」
    的最近持仓快照（调仓次日生效），与区间归因 ``_attribution_payload`` 一致。
    """
    empty = {
        "date": None, "attributions": [], "total_pnl": 0.0,
        "prev_nav": 0.0, "current_nav": 0.0,
    }
    if not cache:
        return empty

    nav_rows = cache.get("nav_series") or []
    if len(nav_rows) < 2:
        return empty

    target = _day(date) or _day(cache.get("end_date")) or _day(nav_rows[-1].get("date"))
    index = next(
        (i for i, row in enumerate(nav_rows) if _day(row.get("date")) == target), None
    )
    if index is None or index == 0:
        # 目标日不在缓存序列内（或就是首日）：回落到最后一个有前收的交易日
        index = len(nav_rows) - 1
    prev_row, cur_row = nav_rows[index - 1], nav_rows[index]
    target = _day(cur_row.get("date"))
    prev_nav = _num(prev_row.get("nav")) or 0.0
    current_nav = _num(cur_row.get("nav")) or prev_nav
    if prev_nav <= 0:
        return {**empty, "date": target, "current_nav": current_nav}

    meta_assets = (cache.get("meta") or {}).get("assets") or []
    meta_map = {item["code"]: item for item in meta_assets}
    snapshot = _pick_snapshot(cache.get("positions_history") or [], target)
    # 严格早于当日才切换权重：快照日 == 当日时说明当日收盘后才调仓，仍用旧持仓归因
    if snapshot and _day(snapshot.get("date")) >= target:
        earlier = [
            item for item in (cache.get("positions_history") or [])
            if _day(item.get("date")) < target
        ]
        snapshot = earlier[-1] if earlier else None
    weights = _normalize_weights((snapshot or {}).get("weights"))
    day_returns = _returns_on(cache.get("asset_returns") or [], target)

    attributions: List[Dict[str, Any]] = []
    total_pnl = 0.0
    for code, weight in weights.items():
        change_pct = day_returns.get(code)
        if change_pct is None or abs(weight) <= 1e-9:
            continue
        market_value = prev_nav * weight
        change = change_pct / 100.0  # 缓存内收益率为百分数
        contribution = market_value * change
        total_pnl += contribution
        meta = meta_map.get(code) or {}
        attributions.append({
            "name": meta.get("name") or resolve_monitor_asset_display_label(code, {}),
            "code": code,
            "asset_class": meta.get("asset_class")
            or resolve_asset_class_for_monitor(code) or "未分类",
            "weight": _num(weight * 100, 4),
            "daily_change": _num(change_pct, 4),
            "contribution": _num(contribution, 4),
            "currency": meta.get("currency") or resolve_asset_currency_for_monitor(code),
        })
    attributions.sort(key=lambda x: abs(x["contribution"] or 0), reverse=True)

    return {
        "date": target,
        "attributions": attributions,
        "total_pnl": _num(total_pnl, 4),
        "prev_nav": _num(prev_nav, 4),
        "current_nav": _num(current_nav, 4),
    }


async def get_performance_panel(
    service,
    monitor_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    batch_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """绩效页统一数据：净值序列 + 区间指标 + 持仓快照 + 归因 + 资产分析。

    **仅供计算侧/脚本使用**：缓存缺失或过期时会触发重建（读行情库）。
    展示端点走 :func:`project_panel_from_cache`，不得调用本函数。
    """
    cache = await ensure_performance_cache(service, monitor_id, batch_id=batch_id)
    return project_panel_from_cache(cache, monitor_id, start, end)
