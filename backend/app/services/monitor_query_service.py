# -*- coding: utf-8 -*-
"""监控展示层只读查询服务 —— 纯读表，不含任何计算组件。

为什么要单独一个服务
--------------------
``MonitorService`` 持有 ``PortfolioTracker`` / ``MonitorEngineAdapter`` /
``SignalDetector`` / ``VolatilityCalculator`` / ``ReportGenerator`` 与行情
Provider，展示端点一旦注入它，就等于把「页面请求触发推演/重建缓存」的口子留在
生产路径上。本类只持有 MongoDB 句柄：

- **禁止**注入或 import 任何计算组件（tracker / adapter / engine / detector /
  volatility / reporter / backtesting / portfolio_* 管线）；
- **禁止**调用 ``rebuild_performance_cache`` / ``ensure_performance_cache`` /
  ``get_performance_panel`` / ``load_prices``；缓存或快照缺失一律返回 ``None``，
  由端点直接 404，重建只发生在跑批写入侧；
- 允许复用 :mod:`app.monitor.performance_cache` 里的 ``project_*`` **纯投影函数**
  （输入全部是已落库的缓存文档，做区间截取与指标聚合）。

批次口径
--------
所有方法都接受可选 ``batch_id``：为空时经
:func:`app.services.monitor_batch_service.resolve_batch` 解析到该实例最新
``completed`` 且未软删的批次；解析不到就抛 :class:`BatchNotFoundError`
（端点映射 404），绝不回落到「最近更新的一条状态文档」——那会把跑到一半的
半成品渲染到页面上。

这条边界由 ``tests/test_monitor_readonly_endpoints.py`` 的 AST 断言守住。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config.collections import (
    COL_ASSETS,
    COL_MONITOR_DAILY_REPORTS,
    COL_MONITOR_OPERATIONS,
    COL_MONITOR_PERFORMANCE_CACHE,
    COL_MONITOR_STATES,
    COL_MONITORED_STRATEGIES,
    COL_SUBJECTIVE_OVERRIDES,
)
from app.config.database import Database
from app.models.monitor import LEGACY_BATCH_ID
from app.monitor.mongo_asset_codes import canonical_price_code
from app.monitor.performance_cache import (
    SCHEMA_VERSION,
    project_daily_attribution_from_cache,
    project_panel_from_cache,
    project_positions_from_cache,
    project_track_metrics,
)
from app.services import monitor_batch_service

__all__ = ["MonitorQueryService", "BatchNotFoundError"]


class BatchNotFoundError(LookupError):
    """展示批次不可用：无 ``completed`` 批次，或指定批次未完成 / 已软删。

    端点统一映射为 404「请先运行初始化」，不回落到未完成批次。
    """


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf 不是合法 JSON
        return None
    return f


def _pct(value: Any, digits: int = 6) -> Optional[float]:
    """小数 → 百分点（与 ``report_generator.calc_performance_api_dict`` 同口径）。"""
    f = _num(value)
    return None if f is None else round(f * 100.0, digits)


def _day(value: Any) -> str:
    return str(value or "").strip()[:10]


def _doc_out(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """出参归一：ObjectId 转 str，datetime 转 ISO，批次号缺失补 legacy。"""
    if not doc:
        return None
    out: Dict[str, Any] = {}
    for key, value in doc.items():
        if key == "_id":
            out["_id"] = str(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    if "batch_id" in out:
        out["batch_id"] = str(out.get("batch_id") or LEGACY_BATCH_ID)
    return out


class MonitorQueryService:
    """监控展示端点的唯一数据入口（只读）。"""

    # ------------------------------------------------------------------
    # 句柄
    # ------------------------------------------------------------------

    @property
    def db(self):
        db = Database.get_database()
        if db is None:
            raise RuntimeError("数据库未连接，无法读取监控数据")
        return db

    @property
    def states_collection(self):
        return self.db[COL_MONITOR_STATES]

    @property
    def reports_collection(self):
        return self.db[COL_MONITOR_DAILY_REPORTS]

    @property
    def operations_collection(self):
        return self.db[COL_MONITOR_OPERATIONS]

    @property
    def overrides_collection(self):
        return self.db[COL_SUBJECTIVE_OVERRIDES]

    @property
    def cache_collection(self):
        return self.db[COL_MONITOR_PERFORMANCE_CACHE]

    # ------------------------------------------------------------------
    # 批次与文档解析
    # ------------------------------------------------------------------

    async def resolve_batch_id(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> str:
        """解析展示批次号；无可用批次抛 :class:`BatchNotFoundError`。"""
        doc = await monitor_batch_service.resolve_batch(monitor_id, batch_id)
        resolved = (doc or {}).get("batch_id")
        if not resolved:
            raise BatchNotFoundError(monitor_id)
        return str(resolved)

    async def resolve_batch(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """解析展示批次文档（批次详情端点复用同一口径）。"""
        doc = await monitor_batch_service.resolve_batch(monitor_id, batch_id)
        if not doc:
            raise BatchNotFoundError(monitor_id)
        return doc

    async def get_state_doc(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """读取展示批次的状态文档原文（dict）；批次或文档缺失返回 None。"""
        try:
            batch = await self.resolve_batch_id(monitor_id, batch_id)
        except BatchNotFoundError:
            return None
        doc = await self.states_collection.find_one(
            {"monitor_id": monitor_id, "batch_id": batch}
        )
        return _doc_out(doc)

    async def get_cache_doc(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """读取展示批次的绩效缓存文档；缺失或版本不匹配返回 None（**不重建**）。"""
        try:
            batch = await self.resolve_batch_id(monitor_id, batch_id)
        except BatchNotFoundError:
            return None
        doc = await self.cache_collection.find_one(
            {"monitor_id": monitor_id, "batch_id": batch}
        )
        if not doc:
            logger.debug(
                "绩效缓存缺失（展示侧不重建）: monitor_id={}, batch_id={}", monitor_id, batch
            )
            return None
        if doc.get("schema_version") != SCHEMA_VERSION:
            logger.debug(
                "绩效缓存版本不匹配: monitor_id={}, batch_id={}, cached={}, expect={}",
                monitor_id, batch, doc.get("schema_version"), SCHEMA_VERSION,
            )
            return None
        return doc

    async def _cache_doc_of_batch(
        self, monitor_id: str, batch_id: str
    ) -> Optional[Dict[str, Any]]:
        """按显式批次号直取缓存（批次对比/批次净值端点用，跳过展示批次解析）。"""
        doc = await self.cache_collection.find_one(
            {"monitor_id": monitor_id, "batch_id": str(batch_id)}
        )
        if not doc or doc.get("schema_version") != SCHEMA_VERSION:
            return None
        return doc

    # ------------------------------------------------------------------
    # 状态 / 净值 / 事件
    # ------------------------------------------------------------------

    async def get_state(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """完整状态文档（与 ``MonitorState.model_dump(by_alias=True)`` 同形）。"""
        return await self.get_state_doc(monitor_id, batch_id)

    async def get_nav_history(
        self,
        monitor_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """实际口径净值历史（可按区间过滤）；无批次/无状态返回 None。"""
        state = await self.get_state_doc(monitor_id, batch_id)
        if state is None:
            return None
        rows = list(state.get("nav_history") or [])
        if start_date:
            rows = [r for r in rows if _day(r.get("date")) >= _day(start_date)]
        if end_date:
            rows = [r for r in rows if _day(r.get("date")) <= _day(end_date)]
        return rows

    async def get_events(
        self,
        monitor_id: str,
        event_type: Optional[str] = None,
        limit: int = 50,
        batch_id: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """事件日志（按日期倒序）；无批次/无状态返回 None。"""
        state = await self.get_state_doc(monitor_id, batch_id)
        if state is None:
            return None
        events = list(state.get("event_log") or [])
        if event_type:
            # 兼容前端仍在用的旧类型名（与 MonitorQueryMixin.get_events 同映射）
            mapping = {
                "monthly_rebalance": "monthly",
                "vol_reset_trigger": "vol_reset",
                "vol_reset_execute": "vol_reset",
                "subjective_rebalance": "subjective",
            }
            normalized = mapping.get(event_type, event_type)
            events = [e for e in events if e.get("type") == normalized]
        events.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
        return events[: max(1, int(limit or 50))]

    # ------------------------------------------------------------------
    # 持仓 / 归因 / 绩效
    # ------------------------------------------------------------------

    async def get_positions(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """当前持仓明细（区间末最近一次快照）；缓存缺失返回 None。"""
        cache = await self.get_cache_doc(monitor_id, batch_id)
        if not cache:
            return None
        return project_positions_from_cache(cache)

    async def get_daily_attribution(
        self,
        monitor_id: str,
        date: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """单日损益归因；缓存缺失返回 None。"""
        cache = await self.get_cache_doc(monitor_id, batch_id)
        if not cache:
            return None
        return project_daily_attribution_from_cache(cache, date)

    async def get_panel(
        self,
        monitor_id: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """绩效页统一数据（缓存投影，**不触发重建**）；缓存缺失返回 None。

        故意不叫 ``get_performance_panel``：那个名字属于写入侧会重建缓存的
        :func:`app.monitor.performance_cache.get_performance_panel`，展示端点禁用。
        """
        cache = await self.get_cache_doc(monitor_id, batch_id)
        if not cache:
            return None
        return project_panel_from_cache(cache, monitor_id, start, end)

    async def get_performance(
        self,
        monitor_id: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """绩效指标（百分点口径，与旧 ``/monitor/performance`` 字段名一致）。

        指标来自缓存净值序列的区间投影，费用/次数类字段来自状态文档，
        两者都是已落库产物，不做任何重算。
        """
        cache = await self.get_cache_doc(monitor_id, batch_id)
        if not cache:
            return None
        metrics = project_track_metrics(cache, "actual", start, end)
        state = await self.get_state_doc(monitor_id, batch_id) or {}
        out = self._to_api_metrics(metrics)
        out.update({
            "batch_id": str(cache.get("batch_id") or LEGACY_BATCH_ID),
            "day_count": int(state.get("day_count") or 0),
            "total_trading_cost": _num(state.get("total_trading_cost")),
            "total_replication_cost": _num(state.get("total_replication_cost")),
            "vol_reset_count": int(state.get("vol_reset_count") or 0),
            "position_count": self._position_count(state),
        })
        return out

    async def get_dual_performance(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """双轨绩效对比（模型口径 vs 实际口径）；缓存缺失返回 None。"""
        cache = await self.get_cache_doc(monitor_id, batch_id)
        if not cache:
            return None
        state = await self.get_state_doc(monitor_id, batch_id) or {}

        actual = self._to_api_metrics(project_track_metrics(cache, "actual"))
        model_rows = cache.get("nav_series_model") or []
        has_model_track = bool(model_rows)
        model = (
            self._to_api_metrics(project_track_metrics(cache, "model"))
            if has_model_track
            else dict(actual)
        )

        # 主观分歧时点是实例的历史事实：跨批次读取，只看当前批次会把历史主观调仓全隐藏
        divergence: List[Dict[str, Any]] = []
        cursor = self.operations_collection.find(
            {"monitor_id": monitor_id, "op_type": "subjective"},
            sort=[("execute_date", 1)],
            limit=500,
        )
        async for op in cursor:
            divergence.append({
                "date": op.get("execute_date"),
                "status": op.get("status"),
                "description": (op.get("suggestion") or {}).get("description"),
                "linked_operation_id": op.get("linked_operation_id"),
            })
        divergence.sort(key=lambda x: str(x.get("date") or ""))

        return {
            "batch_id": str(cache.get("batch_id") or LEGACY_BATCH_ID),
            "model": model,
            "actual": actual,
            "nav_history_model": list(state.get("nav_history_model") or []),
            "nav_history_actual": list(state.get("nav_history") or []),
            "divergence_events": divergence,
            "has_model_track": has_model_track,
            "sub_strategies": list(state.get("sub_strategy_performance") or []),
        }

    @staticmethod
    def _to_api_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
        """缓存指标（小数）→ 接口指标（百分点），键名与旧接口保持一致。"""
        return {
            "cumulative_return": _pct(metrics.get("period_return")),
            "annual_return": _pct(metrics.get("annual_return")),
            "annual_volatility": _pct(metrics.get("annual_volatility")),
            "max_drawdown": _pct(metrics.get("max_drawdown")),
            "sharpe_ratio": _num(metrics.get("sharpe_ratio")),
            "calmar_ratio": _num(metrics.get("calmar_ratio")),
            "win_rate": _num(metrics.get("win_rate")),
            "trading_days": int(metrics.get("trading_days") or 0),
            "annual_return_365": _pct(metrics.get("annual_return_365")),
            "annual_volatility_365": _pct(metrics.get("annual_volatility_365")),
            "sharpe_ratio_365": _num(metrics.get("sharpe_ratio_365")),
            "calmar_ratio_365": _num(metrics.get("calmar_ratio_365")),
        }

    @staticmethod
    def _position_count(state_doc: Dict[str, Any]) -> int:
        """持仓资产数：实际持仓市值非零计数，缺失时回退目标权重（浮点残值按 1e-9 剔除）。"""
        positions = state_doc.get("positions_cny") or {}
        held = [v for v in positions.values() if abs(_num(v) or 0.0) > 1e-9]
        if held:
            return len(held)
        weights = state_doc.get("target_weights") or {}
        return sum(1 for w in weights.values() if abs(_num(w) or 0.0) > 1e-9)

    # ------------------------------------------------------------------
    # 操作指令 / 主观调仓 / 风险预警
    # ------------------------------------------------------------------

    async def get_operations_grouped(
        self,
        monitor_id: str,
        status: Optional[str] = None,
        strategy_key: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按策略维度分组返回操作指令（组合层置顶，待执行指令组内置顶）。

        ``batch_id`` 为空时按展示批次过滤；批次不可用则返回空分组（不抛异常，
        指令面板在实例还没跑过时应当是空表而不是 404）。

        额外返回 ``asset_meta``：资产键 → {name, price, price_date}。
        价格只作交易单的预估单价，后端不落金额（总规模由前端模拟输入）。
        """
        from app.services.monitor_operation_service import MonitorOperationService

        try:
            batch = await self.resolve_batch_id(monitor_id, batch_id)
        except BatchNotFoundError:
            batch = None
        ops = await MonitorOperationService().list_by_monitor(
            monitor_id, status=status, strategy_key=strategy_key,
            limit=500, batch_id=batch, include_subjective_history=True,
        ) if batch else []

        groups: Dict[str, Dict[str, Any]] = {}
        for op in ops:
            key = str(op.get("strategy_key") or monitor_id)
            group = groups.setdefault(key, {
                "strategy_key": key,
                "strategy_name": op.get("strategy_name") or "",
                "operations": [],
            })
            if op.get("strategy_name") and not group["strategy_name"]:
                group["strategy_name"] = op["strategy_name"]
            group["operations"].append(op)

        status_order = {"pending": 0, "superseded": 1, "executed": 2, "cancelled": 3}
        for group in groups.values():
            group["operations"].sort(key=lambda o: (
                status_order.get(str(o.get("status")), 9),
                str(o.get("execute_date") or o.get("signal_date") or ""),
            ))
        ordered = sorted(
            groups.values(),
            key=lambda g: (g["strategy_key"] != "portfolio", g["strategy_key"]),
        )
        return {
            "groups": ordered,
            "total": len(ops),
            "batch_id": batch,
            "asset_meta": await self._build_asset_meta(self._collect_operation_codes(ops)),
        }

    @staticmethod
    def _collect_operation_codes(ops: List[Dict[str, Any]]) -> List[str]:
        """收集指令里出现的全部资产键（目标/基准，以及两级拆解内的策略内资产）。"""
        codes: set = set()
        for op in ops:
            for field in ("target_weights", "prev_weights"):
                codes.update(str(k) for k in (op.get(field) or {}))
            for field in ("strategy_breakdown", "prev_strategy_breakdown"):
                for item in op.get(field) or []:
                    if isinstance(item, dict):
                        codes.update(
                            str(k) for k in (item.get("asset_weights") or {})
                        )
        return sorted(c for c in codes if c)

    async def _build_asset_meta(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """资产键 → {name, price, price_date}。

        名称取自 assets 集合，价格经 PriceRepository 取各资产最近一条收盘价。
        无行情的资产仍返回名称，``price`` 为 None：前端据此标注「无行情」，
        不用 0 兜底——价格为 0 会把估算数量算成无穷大。
        """
        if not codes:
            return {}
        from app.data.price_repository import PriceRepository
        from app.monitor.mongo_asset_codes import stored_price_code

        names: Dict[str, str] = {}
        cursor = self.db[COL_ASSETS].find(
            {"code": {"$in": codes}}, {"code": 1, "name": 1}
        )
        async for doc in cursor:
            names[str(doc.get("code"))] = str(doc.get("name") or "")

        stored_codes = [stored_price_code(c) for c in codes]
        closes = await PriceRepository().get_latest_closes(stored_codes)

        meta: Dict[str, Dict[str, Any]] = {}
        for code in codes:
            quote = closes.get(stored_price_code(code)) or {}
            meta[code] = {
                "name": names.get(code) or "",
                "price": quote.get("price"),
                "price_date": quote.get("price_date") or "",
            }
        return meta

    async def list_subjective_overrides(
        self,
        monitor_id: str,
        status: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """主观调仓指令列表。

        展示口径：
        - 显式指定 ``batch_id``：严格按该批次展示（历史回溯）；
        - 默认视图：``executed`` 跨批次 + 当前批次其余状态。补录后重算会换
          批次，已执行的历史调整挂旧批次，不跨批次读就会从页面消失。
        无可用批次返回 None（端点 404）。
        """
        try:
            batch = await self.resolve_batch_id(monitor_id, batch_id)
        except BatchNotFoundError:
            return None
        query: Dict[str, Any] = {"monitor_id": monitor_id}
        if batch_id:
            query["batch_id"] = batch
        elif status != "executed":
            query["$or"] = [
                {"batch_id": batch},
                {"status": "executed"},
            ]
        if status:
            query["status"] = status
        cursor = self.overrides_collection.find(query).sort("execute_date", 1)
        return [_doc_out(doc) for doc in await cursor.to_list(length=1000)]

    async def search_risk_alerts(
        self,
        monitor_id: Optional[str] = None,
        severity: Optional[str] = None,
        signal_type: Optional[str] = None,
        monitor_kind: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        batch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """风险预警分页查询（历史台账，默认跨批次）。"""
        from app.services.monitor_risk_alert_service import MonitorRiskAlertService

        return await MonitorRiskAlertService().search_alerts(
            monitor_id=monitor_id, severity=severity, signal_type=signal_type,
            monitor_kind=monitor_kind, start_date=start_date, end_date=end_date,
            limit=limit, offset=offset, batch_id=batch_id,
        )

    # ------------------------------------------------------------------
    # 信号状态（读跑批收尾时物化的快照）
    # ------------------------------------------------------------------

    async def get_signals(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """信号状态快照；快照缺失（存量批次未重跑）返回 None，端点 404。"""
        state = await self.get_state_doc(monitor_id, batch_id)
        if state is None:
            return None
        snapshot = state.get("signal_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return None
        out = dict(snapshot)
        out["batch_id"] = str(state.get("batch_id") or LEGACY_BATCH_ID)
        out["snapshot_at"] = state.get("signal_snapshot_at")
        return out

    # ------------------------------------------------------------------
    # 日报
    # ------------------------------------------------------------------

    async def get_daily_report(
        self, monitor_id: str, date: str, batch_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """指定日期日报；``batch_id`` 为空时按展示批次过滤。"""
        query: Dict[str, Any] = {"monitor_id": monitor_id, "date": _day(date)}
        try:
            query["batch_id"] = await self.resolve_batch_id(monitor_id, batch_id)
        except BatchNotFoundError:
            return None
        doc = await self.reports_collection.find_one(query, sort=[("created_at", -1)])
        return _doc_out(doc)

    async def get_report_list(
        self,
        monitor_id: str,
        skip: int = 0,
        limit: int = 30,
        batch_id: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """日报列表（按日期倒序）；无可用批次返回 None。"""
        try:
            batch = await self.resolve_batch_id(monitor_id, batch_id)
        except BatchNotFoundError:
            return None
        cursor = (
            self.reports_collection.find({"monitor_id": monitor_id, "batch_id": batch})
            .sort("date", -1)
            .skip(max(0, int(skip or 0)))
            .limit(max(1, int(limit or 30)))
        )
        return [_doc_out(doc) for doc in await cursor.to_list(length=None)]

    # ------------------------------------------------------------------
    # 多实例持仓重叠
    # ------------------------------------------------------------------

    async def get_positions_overlap(
        self, monitor_ids: Optional[List[str]] = None, top: int = 10
    ) -> Dict[str, Any]:
        """多监控实例持仓重叠：同一资产在多个实例中的权重合计。

        口径与 ``MonitorQueryMixin.get_positions_overlap`` 一致：
        ``weight = positions_cny[code] / nav``，资产代码经 ``canonical_price_code``
        归一化后合并，只统计正权重；每个实例取各自最新 completed 批次的状态。
        """
        requested = [str(x).strip() for x in (monitor_ids or []) if str(x).strip()]
        targets = await self._monitor_targets(requested or None)

        monitors: List[Dict[str, Any]] = []
        asset_rows: Dict[str, Dict[str, Any]] = {}
        seen_states: set = set()
        for mid, display_name in targets:
            state_key, state = await self._overlap_state(mid)
            if state_key in seen_states:
                continue  # monitored_strategies._id 与 source_ref 指向同一实例时只计一次
            seen_states.add(state_key)
            nav = _num(state.get("nav")) if state else None
            positions = dict((state or {}).get("positions_cny") or {})
            weights: Dict[str, float] = {}
            for code, market_value in positions.items():
                value = _num(market_value)
                if value is None or value <= 0 or not nav or nav <= 0:
                    continue
                canon = canonical_price_code(str(code).strip())
                if not canon:
                    continue
                weights[canon] = weights.get(canon, 0.0) + value / nav
            monitors.append({
                "monitor_id": mid,
                "state_key": state_key,
                "display_name": display_name,
                "batch_id": str((state or {}).get("batch_id") or LEGACY_BATCH_ID) if state else None,
                "date": _day((state or {}).get("date")),
                "nav": nav if state else None,
                "asset_count": len(weights),
                "total_weight": sum(weights.values()),
            })
            for code, weight in weights.items():
                row = asset_rows.setdefault(code, {
                    "asset_code": code, "total_weight": 0.0,
                    "monitor_count": 0, "details": [],
                })
                row["total_weight"] += weight
                row["details"].append({
                    "monitor_id": mid, "display_name": display_name, "weight": weight,
                })

        items = sorted(asset_rows.values(), key=lambda r: r["total_weight"], reverse=True)
        for row in items:
            row["details"].sort(key=lambda d: d["weight"], reverse=True)
            row["monitor_count"] = len(row["details"])
        return {
            "monitors": monitors,
            "items": items[: max(1, int(top))],
            "monitor_count": len(monitors),
            "asset_count": len(items),
        }

    async def _overlap_state(self, monitor_id: str):
        """解析实例当前展示状态：直接命中 monitor_states，否则回落到 source_ref。"""
        state = await self.get_state_doc(monitor_id)
        if state is not None:
            return monitor_id, state
        from bson import ObjectId

        if ObjectId.is_valid(monitor_id):
            doc = await self.db[COL_MONITORED_STRATEGIES].find_one(
                {"_id": ObjectId(monitor_id)}, projection={"source_ref": 1}
            )
            ref = str((doc or {}).get("source_ref") or "")
            if ref and ref != monitor_id:
                fallback = await self.get_state_doc(ref)
                if fallback is not None:
                    return ref, fallback
        return monitor_id, None

    async def _monitor_targets(
        self, monitor_ids: Optional[List[str]]
    ) -> List[tuple]:
        """参与重叠统计的实例：``[(monitored_strategies._id, display_name)]``。"""
        rows: List[Dict[str, Any]] = []
        try:
            cursor = self.db[COL_MONITORED_STRATEGIES].find({"status": {"$ne": "archived"}})
            rows = await cursor.to_list(length=None)
        except Exception as exc:  # noqa: BLE001 —— 台账不可用时返回空集合而非 500
            logger.warning(f"[监控只读] 监测策略台账读取失败: {exc}")
            rows = []

        by_id = {str(r["_id"]): r for r in rows if r.get("_id") is not None}
        by_ref: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            ref = str(row.get("source_ref") or "")
            if ref:
                by_ref.setdefault(ref, row)

        if not monitor_ids:
            return [
                (str(r["_id"]), str(r.get("display_name") or r["_id"]))
                for r in rows if r.get("_id") is not None
            ]

        targets: List[tuple] = []
        missing: List[str] = []
        seen: set = set()
        for mid in monitor_ids:
            row = by_id.get(mid) or by_ref.get(mid)
            if row is None or row.get("_id") is None:
                missing.append(mid)
                continue
            key = str(row["_id"])
            if key in seen:
                continue
            seen.add(key)
            targets.append((key, str(row.get("display_name") or mid)))
        if missing:
            raise ValueError(f"监控实例不存在或未登记: {', '.join(missing)}")
        return targets

    # ------------------------------------------------------------------
    # 批次视图（列表 / 详情 / 净值 / 对比 / 软删除）
    # ------------------------------------------------------------------

    async def list_batches(
        self,
        monitor_id: str,
        limit: int = 20,
        skip: int = 0,
        status: Optional[str] = None,
        include_deleted: bool = False,
    ) -> Dict[str, Any]:
        """批次历史（创建时间倒序）+ 当前展示批次号。"""
        docs = await monitor_batch_service.list_batches(
            monitor_id, limit=max(1, int(limit or 20)), skip=max(0, int(skip or 0)),
            status=status, include_deleted=include_deleted,
        )
        current: Optional[str] = None
        try:
            current = await self.resolve_batch_id(monitor_id)
        except BatchNotFoundError:
            current = None
        return {
            "monitor_id": monitor_id,
            "current_batch_id": current,
            "items": [monitor_batch_service.batch_summary(doc) for doc in docs],
            "count": len(docs),
        }

    async def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """批次详情（含配置快照与摘要指标）；不存在返回 None。"""
        doc = await monitor_batch_service.get_batch(batch_id)
        return monitor_batch_service.batch_summary(doc) if doc else None

    async def get_batch_nav_history(
        self, batch_id: str, start: Optional[str] = None, end: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """单批次双轨净值曲线（读该批次的绩效缓存，缓存缺失返回 None）。"""
        doc = await monitor_batch_service.get_batch(batch_id)
        if not doc:
            return None
        monitor_id = str(doc.get("monitor_id") or "")
        cache = await self._cache_doc_of_batch(monitor_id, batch_id)
        if not cache:
            return {
                "batch_id": str(batch_id),
                "monitor_id": monitor_id,
                "summary": monitor_batch_service.batch_summary(doc),
                "nav_history": [],
                "nav_history_model": [],
                "metrics": {},
                "cache_available": False,
            }
        panel = project_panel_from_cache(cache, monitor_id, start, end) or {}
        return {
            "batch_id": str(batch_id),
            "monitor_id": monitor_id,
            "summary": monitor_batch_service.batch_summary(doc),
            "range": panel.get("range"),
            "nav_history": panel.get("nav_history") or [],
            "nav_history_model": panel.get("nav_history_model") or [],
            "metrics": panel.get("metrics") or {},
            "cache_available": True,
        }

    async def compare_batches(
        self, monitor_id: str, batch_ids: List[str]
    ) -> Dict[str, Any]:
        """多批次对比：摘要 + 指标 + 净值曲线（最多 5 个批次）。"""
        ids = [str(b).strip() for b in (batch_ids or []) if str(b).strip()][:5]
        items: List[Dict[str, Any]] = []
        curves: Dict[str, List[Dict[str, Any]]] = {}
        for batch_id in ids:
            doc = await monitor_batch_service.get_batch(batch_id)
            if not doc or str(doc.get("monitor_id") or "") != monitor_id:
                continue
            summary = monitor_batch_service.batch_summary(doc)
            cache = await self._cache_doc_of_batch(monitor_id, batch_id)
            if cache:
                panel = project_panel_from_cache(cache, monitor_id) or {}
                summary["panel_metrics"] = panel.get("metrics") or {}
                curves[batch_id] = [
                    {"date": r.get("date"), "nav": r.get("nav")}
                    for r in (panel.get("nav_history") or [])
                ]
            else:
                summary["panel_metrics"] = {}
                curves[batch_id] = []
            items.append(summary)
        return {
            "monitor_id": monitor_id,
            "items": items,
            "curves": curves,
            "count": len(items),
        }

    async def soft_delete_batch(self, batch_id: str) -> bool:
        """软删除批次（只置 ``deleted=True``，产物文档全部保留）。"""
        return await monitor_batch_service.soft_delete_batch(batch_id)
