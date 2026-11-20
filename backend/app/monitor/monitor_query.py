# -*- coding: utf-8 -*-
"""
监控服务 Mixin：读取查询接口（净值历史、事件、绩效、日报、信号状态、持仓、归因）

自 monitor_service.py 平移而来，方法体保持不变，仅按职责归组：
1. 净值历史 / 事件日志 / 绩效指标查询
2. 日报读取与持久化
3. 信号状态（月度调仓 + 波动率）查询
4. 持仓明细与损益归因查询

批次维度（``batch_id``）：读方法一律接受可选 ``batch_id``，为空时由
``MonitorService.get_state`` 解析到最新 completed 批次。本 Mixin 仍含大量计算
（reporter / detector / vol_calculator / 行情加载），**不属于纯读表服务**；
展示端点的纯读表实现见 ``app/services/monitor_query_service.py``。
"""

from datetime import datetime
from typing import Dict, List, Optional, Any

from app.models.monitor import MonitorDailyReport
from app.monitor import config
from app.monitor.mongo_asset_codes import stored_price_code, canonical_price_code
from app.monitor.time_norm import normalize_calendar_timestamp, coerce_trade_dates
from app.monitor.monitor_runtime import (
    resolve_asset_class_for_monitor,
    resolve_asset_currency_for_monitor,
    resolve_monitor_asset_display_label,
    slice_prices_df,
)
from app.services.strategy_model_service import StrategyModelService


class MonitorQueryMixin:
    """监控查询接口方法群。

    依赖宿主（MonitorService）属性：get_state、_state_to_portfolio_state、
    _runtime_for_reads、_is_strategy_model_monitor_id、_asset_keys_for_positions_attribution、
    _asset_master_names_by_code、reporter、detector、vol_calculator、async_provider、
    reports_collection、db。
    """

    async def get_nav_history(self, monitor_id: str,
                               start_date: str = None, end_date: str = None,
                               batch_id: Optional[str] = None) -> List[dict]:
        """获取净值历史，支持日期范围筛选"""
        state = await self.get_state(monitor_id, batch_id=batch_id)
        if not state:
            return []
        
        history = state.nav_history
        
        if start_date:
            history = [h for h in history if h['date'] >= start_date]
        if end_date:
            history = [h for h in history if h['date'] <= end_date]
        
        return history
    
    async def get_events(self, monitor_id: str,
                          event_type: str = None, limit: int = 50,
                          batch_id: Optional[str] = None) -> List[dict]:
        """获取事件日志，支持类型筛选
        
        事件类型：
        - init: 初始化
        - monthly: 月度调仓
        - vol_reset: 波动率重置（通过 stage 字段区分 trigger/execute）
        - subjective: 主观调仓
        """
        state = await self.get_state(monitor_id, batch_id=batch_id)
        if not state:
            return []
        
        events = state.event_log
        
        if event_type:
            # 支持新的统一类型名和旧类型名的兼容筛选
            type_mapping = {
                'monthly_rebalance': 'monthly',
                'vol_reset_trigger': 'vol_reset',
                'vol_reset_execute': 'vol_reset',
                'subjective_rebalance': 'subjective',
            }
            # 将旧类型名转换为新类型名
            normalized_type = type_mapping.get(event_type, event_type)
            events = [e for e in events if e.get('type') == normalized_type]
        
        events = sorted(events, key=lambda x: x.get('date', ''), reverse=True)
        
        return events[:limit]
    
    async def _executed_rebalance_dates(self, monitor_id: str) -> List[str]:
        """已执行调仓的执行日（与绩效页缓存同一数据源：monitor_operations）。

        故意不限批次：调仓日标记需要完整时间轴，而指令幂等键已含 batch_id，
        同一次调仓在不同批次里的重复记录落到同一个日期集合里，不影响结果。
        """
        try:
            ops = await self.operation_service.list_by_monitor(monitor_id, limit=5000)
        except Exception:
            return []
        marks = {
            str(op.get('execute_date'))[:10]
            for op in ops
            if op.get('status') == 'executed' and op.get('execute_date')
        }
        return sorted(marks)

    async def get_performance(self, monitor_id: str,
                              start_date: str = None,
                              end_date: str = None,
                              batch_id: Optional[str] = None) -> dict:
        """计算并返回绩效指标（指标计算已下沉 report_generator）

        Args:
            start_date / end_date: 可选区间（YYYY-MM-DD），默认全区间。
                区间由后端裁剪净值序列后交给统一内核计算，前端不做二次计算。
            batch_id: 目标批次；为空时取最新 completed 批次。
        """
        state = await self.get_state(monitor_id, batch_id=batch_id)
        if not state:
            return {}

        ps = self._state_to_portfolio_state(state)
        if start_date or end_date:
            history = list(ps.nav_history)
            if start_date:
                history = [h for h in history if h.get('date', '') >= start_date]
            if end_date:
                history = [h for h in history if h.get('date', '') <= end_date]
            ps.nav_history = history
            if history:
                # 区间末对齐：避免 _build_nav_series 追加全区间最新净值
                ps.date = str(history[-1].get('date', ps.date))[:10]
                ps.nav = float(history[-1].get('nav', ps.nav))

        # 优先用已执行指令的执行日；存量实例无指令记录时传 None，由内核消费方回退事件日志
        rebalance_dates = await self._executed_rebalance_dates(monitor_id) or None
        result = self.reporter.calc_performance_api_dict(
            ps, rebalance_dates=rebalance_dates
        )
        # 持仓资产数：与绩效页持仓表同口径（实际持仓市值非零；
        # 浮点残值（如 4e-13 元）按 1e-9 剔除，避免把已清仓资产算成一个持仓）
        held = [
            v for v in (state.positions_cny or {}).values()
            if abs(float(v or 0)) > 1e-9
        ]
        position_count = len(held) if held else sum(
            1 for w in (state.target_weights or {}).values()
            if abs(float(w or 0)) > 1e-9
        )
        result.update({
            'day_count': state.day_count,
            'total_trading_cost': state.total_trading_cost,
            'total_replication_cost': state.total_replication_cost,
            'vol_reset_count': state.vol_reset_count,
            'position_count': position_count,
        })
        return result
    
    async def get_dual_performance(self, monitor_id: str,
                                   batch_id: Optional[str] = None) -> dict:
        """双轨绩效：模型口径（纯系统信号）vs 实际口径（含主观调整）。

        Returns:
            {
                'model': 模型口径指标, 'actual': 实际口径指标,
                'nav_history_model': 模型口径净值序列,
                'nav_history_actual': 实际口径净值序列,
                'divergence_events': 主观调整时点（双轨分歧事件）,
                'has_model_track': 是否存在模型轨（存量实例未重跑时为 False）,
                'sub_strategies': 组合子策略模型口径绩效（非组合监控为空列表）
            }
        """
        state = await self.get_state(monitor_id, batch_id=batch_id)
        if not state:
            return {}

        ps_actual = self._state_to_portfolio_state(state)
        rebalance_dates = await self._executed_rebalance_dates(monitor_id) or None
        actual = self.reporter.calc_performance_api_dict(
            ps_actual, rebalance_dates=rebalance_dates
        )

        has_model_track = bool(state.nav_history_model)
        if has_model_track:
            ps_model = self._state_to_portfolio_state(state)
            ps_model.nav_history = list(state.nav_history_model)
            last_pt = state.nav_history_model[-1]
            ps_model.nav = float(last_pt.get('nav', ps_model.nav))
            ps_model.date = str(last_pt.get('date', ps_model.date))[:10]
            # 模型轨无逐日操作记录，显式传空列表（胜率 0，不猜测调仓日）
            model = self.reporter.calc_performance_api_dict(
                ps_model, rebalance_dates=[]
            )
        else:
            # 存量实例未重跑无模型轨：两轨口径重合，模型轨沿用实际轨
            model = dict(actual)

        divergence_events: List[dict] = []
        # 不限批次：主观分歧时点是实例的历史事实，已执行的那部分随旧批次封存，
        # 只看当前批次会把历史上的主观调仓全部隐藏。
        ops = await self.operation_service.list_by_monitor(monitor_id, limit=500)
        for op in ops:
            if op.get('op_type') != 'subjective':
                continue
            divergence_events.append({
                'date': op.get('execute_date'),
                'status': op.get('status'),
                'description': (op.get('suggestion') or {}).get('description'),
                'linked_operation_id': op.get('linked_operation_id'),
            })
        divergence_events.sort(key=lambda x: str(x.get('date') or ''))

        return {
            'model': model,
            'actual': actual,
            'nav_history_model': state.nav_history_model,
            'nav_history_actual': state.nav_history,
            'divergence_events': divergence_events,
            'has_model_track': has_model_track,
            'sub_strategies': state.sub_strategy_performance,
        }

    async def get_operations_grouped(
        self,
        monitor_id: str,
        status: Optional[str] = None,
        strategy_key: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> dict:
        """按策略维度分组返回操作指令（组合层置顶，待执行指令组内置顶）。

        Args:
            batch_id: 目标批次；为空时**不限批次**（历史全量），
                展示端点应先经 ``monitor_batch_service.resolve_batch_id`` 解析后传入。

        Returns:
            {'groups': [{strategy_key, strategy_name, operations: [...]}], 'total': int}
        """
        ops = await self.operation_service.list_by_monitor(
            monitor_id, status=status, strategy_key=strategy_key, limit=500,
            batch_id=batch_id,
        )
        groups: Dict[str, dict] = {}
        for op in ops:
            key = str(op.get('strategy_key') or monitor_id)
            g = groups.setdefault(key, {
                'strategy_key': key,
                'strategy_name': op.get('strategy_name') or '',
                'operations': [],
            })
            if op.get('strategy_name') and not g['strategy_name']:
                g['strategy_name'] = op['strategy_name']
            g['operations'].append(op)

        _status_order = {'pending': 0, 'superseded': 1, 'executed': 2, 'cancelled': 3}
        for g in groups.values():
            # 待执行置顶，同状态内按执行日升序（最近要执行的在前）
            g['operations'].sort(key=lambda o: (
                _status_order.get(str(o.get('status')), 9),
                str(o.get('execute_date') or o.get('signal_date') or ''),
            ))

        ordered = sorted(
            groups.values(),
            key=lambda g: (g['strategy_key'] != 'portfolio', g['strategy_key']),
        )
        return {'groups': ordered, 'total': len(ops)}

    async def get_positions_overlap(
        self,
        monitor_ids: Optional[List[str]] = None,
        top: int = 10,
    ) -> dict:
        """多监控实例持仓重叠：同一资产在多个实例中的权重合计。

        口径：weight = positions_cny[code] / nav（与 DailyResult.asset_weights 一致）；
        资产代码经 canonical_price_code 归一化后合并，只统计正权重。
        monitor_ids 为空时取全部已登记且未归档的监控实例。

        Returns:
            {monitors: [...], items: [...], monitor_count, asset_count}
        """
        requested = [str(x).strip() for x in (monitor_ids or []) if str(x).strip()]
        # monitor_states.monitor_id 落地为 monitored_strategies._id，故统一以 _id 作为解析键；
        # 入参同时接受 _id / source_ref（研究员 code、portfolio_models._id 等），便于前端按需指定。
        targets = await self._monitor_targets(requested or None)

        monitors: List[dict] = []
        asset_rows: Dict[str, dict] = {}
        seen_states: set = set()
        for mid, display_name in targets:
            state_key, state = await self._overlap_state(mid)
            if state_key in seen_states:
                continue  # monitored_strategies._id 与 source_ref 指向同一实例时只计一次
            seen_states.add(state_key)
            nav = float(getattr(state, "nav", 0) or 0) if state else 0.0
            positions = dict(getattr(state, "positions_cny", None) or {}) if state else {}
            weights: Dict[str, float] = {}
            for code, pv in positions.items():
                try:
                    pv_f = float(pv)
                except (TypeError, ValueError):
                    continue
                if pv_f <= 0 or nav <= 0:
                    continue
                canon = canonical_price_code(str(code).strip())
                if not canon:
                    continue
                weights[canon] = weights.get(canon, 0.0) + pv_f / nav
            monitors.append({
                "monitor_id": mid,
                "state_key": state_key,
                "display_name": display_name,
                "date": str(getattr(state, "date", "") or "") if state else "",
                "nav": nav if state else None,
                "asset_count": len(weights),
                "total_weight": sum(weights.values()),
            })
            for code, w in weights.items():
                row = asset_rows.setdefault(code, {
                    "asset_code": code,
                    "total_weight": 0.0,
                    "monitor_count": 0,
                    "details": [],
                })
                row["total_weight"] += w
                row["details"].append({
                    "monitor_id": mid,
                    "display_name": display_name,
                    "weight": w,
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
        """解析监控实例当前状态：直接命中 monitor_states，否则回落到 source_ref。"""
        state = await self.get_state(monitor_id)
        if state is not None:
            return monitor_id, state
        from bson import ObjectId
        from app.config.collections import COL_MONITORED_STRATEGIES
        if ObjectId.is_valid(monitor_id):
            doc = await self.db[COL_MONITORED_STRATEGIES].find_one(
                {"_id": ObjectId(monitor_id)}
            )
            ref = str((doc or {}).get("source_ref") or "")
            if ref and ref != monitor_id:
                st = await self.get_state(ref)
                if st is not None:
                    return ref, st
        return monitor_id, None

    async def _monitor_targets(
        self, monitor_ids: Optional[List[str]]
    ) -> List[tuple]:
        """解析参与重叠统计的监控实例：返回 [(monitored_strategies._id, display_name)]。

        monitor_ids 为空时取全部未归档实例；非空时接受 _id 或 source_ref，未知键直接报错。
        """
        from app.config.collections import COL_MONITORED_STRATEGIES

        rows = []
        try:
            async for row in self.db[COL_MONITORED_STRATEGIES].find(
                {"status": {"$ne": "archived"}}
            ):
                rows.append(row)
        except Exception:
            rows = []

        by_id: Dict[str, dict] = {str(r["_id"]): r for r in rows if r.get("_id") is not None}
        by_ref: Dict[str, dict] = {}
        for r in rows:
            ref = str(r.get("source_ref") or "")
            if ref:
                by_ref.setdefault(ref, r)

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
    
    async def get_daily_report(self, monitor_id: str, date: str,
                               batch_id: Optional[str] = None) -> Optional[dict]:
        """获取指定日期的日报数据（``batch_id`` 为空时不限批次，取最新一份）"""
        query: Dict[str, Any] = {"monitor_id": monitor_id, "date": date}
        if batch_id:
            query["batch_id"] = str(batch_id)
        doc = await self.reports_collection.find_one(query, sort=[("created_at", -1)])
        if doc:
            doc['_id'] = str(doc['_id'])
            return doc
        return None
    
    async def get_report_list(self, monitor_id: str, skip: int = 0, limit: int = 30,
                              batch_id: Optional[str] = None) -> List[dict]:
        """获取日报列表（``batch_id`` 为空时不限批次）"""
        query: Dict[str, Any] = {"monitor_id": monitor_id}
        if batch_id:
            query["batch_id"] = str(batch_id)
        cursor = self.reports_collection.find(query).sort("date", -1).skip(skip).limit(limit)
        
        result = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            result.append(doc)
        
        return result
    
    async def get_signal_status(self, monitor_id: str,
                                batch_id: Optional[str] = None) -> dict:
        """获取当前信号状态
        
        返回数据结构：
        - monthly_rebalance: 月度调仓信息（next_date, days_until, last_date）
        - vol_reset: 波动率重置信息（threshold, current_volatility, status, distance_to_trigger, vol_windows）
        - pending_rebalance: 待执行调仓（如有）
        - volatility_history: 波动率历史（用于趋势图）
        """
        state = await self.get_state(monitor_id, batch_id=batch_id)
        if not state:
            return {}

        rt = await self._runtime_for_reads(monitor_id)
        price_cols = list(rt.asset_list) if rt else None
        prices_df = await self.async_provider.load_prices(asset_columns=price_cols)
        prices_df = slice_prices_df(prices_df, rt)
        _cal_src = getattr(rt, "calendar_source", "prices")
        _raw_td = (
            await self.async_provider.load_trade_dates()
            if _cal_src == "trade_dates" else []
        )
        trade_dates = coerce_trade_dates(_raw_td, prices_df, _cal_src)
        current_date = normalize_calendar_timestamp(state.date)
        asset_list = list(rt.asset_list) if rt else list(config.ASSET_LIST)
        
        # ===== 月度调仓信息 =====
        next_monthly = self.detector.get_next_rebalance_date(current_date, trade_dates)
        
        # 上次调仓执行日期（提取计算已下沉 signal_detector）
        last_rebalance_date = self.detector.extract_last_rebalance_date(state.event_log)
        
        # 如果有 pending_rebalance，其 execute_date 也是候选
        next_pending = None
        if state.pending_rebalance:
            next_pending = state.pending_rebalance.get('execute_date')
        
        # 取所有候选日期中最近的一个作为"下次调仓日"
        candidates = []
        if next_monthly:
            candidates.append(next_monthly)
        if next_pending:
            candidates.append(next_pending)
        next_rebal = min(candidates) if candidates else None
        
        # 计算距下次调仓天数（计算已下沉 signal_detector）
        days_until = self.detector.calc_days_until_rebalance(
            current_date, next_rebal, trade_dates
        )
        
        # ===== 波动率信息 =====
        # 开关与阈值同源读取：rt 的 vol_control_enabled 由 resolve_vol_control 单点判定。
        # 未启用时 threshold 返回 None（旧版无条件回落全局 0.06，导致所有策略都显示
        # 同一个「风控阈值 6.00%」，与策略真实配置无关）；无 rt 时按全局基准运行。
        vol_control_enabled = (
            bool(getattr(rt, "vol_control_enabled", True)) if rt else True
        )
        vol_threshold_source = (
            getattr(rt, "vol_threshold_source", None) if rt else "global_config"
        )
        vol_disabled_reason = (
            getattr(rt, "vol_control_reason", None) if rt else None
        )
        if rt is None:
            # rt 缺失有两种：①无策略上下文的全局基准会话（legacy，保持启用）；
            # ②策略监控实例但模型未实盘发布/快照缺失——后端不会执行波动率重置，
            # 不能回落全局 6% 给前端一个假阈值。
            if await self._resolve_monitored_strategy(monitor_id):
                vol_control_enabled = False
                vol_disabled_reason = "no_runtime_config"
        threshold = (
            (
                float(rt.vol_trigger_threshold) * 100
                if rt
                else float(config.VOL_TRIGGER_THRESHOLD) * 100
            )
            if vol_control_enabled
            else None
        )
        
        # 波动率窗口/年化因子与触发判定同源（signal_detector 读策略参数
        # vol_windows / annualization_factor），避免信号页显示的波动率来自
        # 另一个窗口而与实际触发口径不一致。
        vol_windows_cfg, vol_annualize = self.detector._vol_params(rt)

        # 当前持仓权重（人民币口径）：当前值与趋势终点同源，避免两处各算一份权重
        _nav_value = float(state.nav or 0.0)
        _positions_local = dict(state.positions_local)
        _last_rebalance_fx = dict(state.last_rebalance_fx)
        current_weights = (
            {
                a: float(_positions_local.get(a, 0.0))
                * float(_last_rebalance_fx.get(a, 1.0))
                / _nav_value
                for a in asset_list
            }
            if _nav_value > 0 else {}
        )

        # 1. 当前实时波动率（使用当前权重）
        current_volatility, vol_windows, price_as_of = self.vol_calculator.calc_current_volatility(
            prices_df,
            _positions_local,
            _last_rebalance_fx,
            state.nav,
            state.date,
            asset_list=asset_list,
            w_cny=current_weights,
            vol_windows=vol_windows_cfg,
            annualize_factor=vol_annualize,
        )
        
        # 2. 波动率历史趋势（与当前值同一行情截止日与当前权重，趋势终点与卡片数值对齐）
        volatility_history = self.vol_calculator.calc_volatility_history(
            prices_df,
            list(state.event_log),
            state.date,
            asset_list=asset_list,
            vol_windows=vol_windows_cfg,
            annualize_factor=vol_annualize,
            as_of=price_as_of,
            current_weights=current_weights,
        )
        
        # 3. 状态判断（未启用风控时不做阈值比较，函数视为无待处理事项）
        if vol_control_enabled:
            status, distance_to_trigger = self.vol_calculator.calc_status(
                current_volatility, threshold_pct=threshold
            )
        else:
            status, distance_to_trigger = "disabled", None
        
        # ===== 从 event_log 提取调仓历史（提取计算已下沉 signal_detector） =====
        rebalance_history = self.detector.extract_rebalance_history(state.event_log)
        
        # ===== 构建返回结果 =====
        # 优先使用 state.last_rebalance_date，若无则使用从 event_log 提取的
        final_last_rebalance_date = state.last_rebalance_date or last_rebalance_date
        
        result = {
            'monthly_rebalance': {
                # 无下次调仓日（已到行情末尾）时返回 None，由前端按空值处理；
                # 不能返回「无」等非日期文本，前端日期格式化会得到 Invalid Date。
                'next_date': next_rebal,
                'days_until': days_until,
                'last_date': final_last_rebalance_date,
            },
            'vol_reset': {
                # enabled=False 时前端整块不渲染波动率监控区（阈值/进度条/阈值线全部无意义）
                'enabled': vol_control_enabled,
                'threshold': threshold,
                'threshold_source': vol_threshold_source,
                'disabled_reason': vol_disabled_reason,
                'current_volatility': current_volatility,  # 百分比形式，未启用时仍可供只读观测
                'status': status,
                'distance_to_trigger': distance_to_trigger,
                'vol_windows': vol_windows,
                # 波动率实际用到的最后行情日；持仓资产行情停更时早于 state.date，
                # 前端用它提示「行情截至」（不遮挡，仅说明数据截断点）
                'price_as_of': price_as_of,
            },
            'pending_rebalance': None,
            'volatility_history': volatility_history,
            'rebalance_history': rebalance_history,
            'last_rebalance_date': final_last_rebalance_date,
        }
        
        if state.pending_rebalance:
            result['pending_rebalance'] = {
                'type': state.pending_rebalance.get('rebalance_type'),
                'execute_date': state.pending_rebalance.get('execute_date'),
                'description': '月度调仓' if state.pending_rebalance.get('rebalance_type') == 'monthly' else '波动率重置',
            }
        
        return result
    
    async def get_positions(self, monitor_id: str,
                            batch_id: Optional[str] = None) -> dict:
        """获取当前持仓明细
        
        返回重新设计的字段：
        - name: 资产名称
        - code: 资产代码
        - asset_class: 资产类别（权益/固定收益/大宗商品）
        - current_weight: 当前权重%（基于市值）
        - daily_change: 当日涨跌%（底层资产价格变动）
        - currency: 计价货币
        """
        state = await self.get_state(monitor_id, batch_id=batch_id)
        if not state or state.nav <= 0:
            return {'positions': [], 'total_leverage': 0}

        rt = await self._runtime_for_reads(monitor_id)
        base_al = list(rt.asset_list) if rt else list(config.ASSET_LIST)
        al = self._asset_keys_for_positions_attribution(
            base_al, state.positions_cny, state.target_weights
        )

        model = None
        if self._is_strategy_model_monitor_id(monitor_id):
            model = await StrategyModelService().get_model(monitor_id)
        names_lookup = await self._asset_master_names_by_code(model, al)
        
        # 获取所有资产的 daily_change
        daily_changes = await self._get_asset_daily_changes(state.date, asset_names=al)
        
        positions = []
        for asset in al:
            pos_cny = float(state.positions_cny.get(asset, 0.0) or 0.0)
            current_w = pos_cny / state.nav if state.nav else 0.0
            display_name = resolve_monitor_asset_display_label(asset, names_lookup)
            positions.append({
                'name': display_name,
                'code': asset,
                'asset_class': resolve_asset_class_for_monitor(asset),
                'current_weight': round(current_w * 100, 2),
                'value_cnh': round(pos_cny, 2),
                'daily_change': daily_changes.get(asset),
                'currency': resolve_asset_currency_for_monitor(asset),
            })
        
        total_leverage = sum(p['current_weight'] for p in positions) / 100
        
        return {
            'positions': positions,
            'total_leverage': round(total_leverage, 4),
            'nav': state.nav,
            'date': state.date,
        }
    
    async def get_daily_attribution(self, monitor_id: str, date: str = None,
                                    batch_id: Optional[str] = None) -> dict:
        """获取指定日期的损益归因数据
        
        每个资产贡献 = 该资产持仓权重 × 该资产当日收益率 × 前一日组合净值
        
        Args:
            monitor_id: 监控实例 ID
            date: 目标日期 YYYY-MM-DD，默认使用 state.date（最新日期）
            
        Returns:
            {
                "date": "YYYY-MM-DD",
                "attributions": [{name, code, asset_class, weight, daily_change, contribution, currency}, ...],
                "total_pnl": float,
                "prev_nav": float,
                "current_nav": float
            }
        """
        state = await self.get_state(monitor_id, batch_id=batch_id)
        if not state or not state.nav_history or len(state.nav_history) < 2:
            return {"date": None, "attributions": [], "total_pnl": 0, "prev_nav": 0, "current_nav": 0}
        
        # 确定目标日期
        target_date = date or state.date
        
        # 找到目标日期和前一日的 nav_history 记录
        history = state.nav_history
        target_record = None
        prev_record = None
        
        for i, rec in enumerate(history):
            if rec.get('date') == target_date:
                target_record = rec
                if i > 0:
                    prev_record = history[i - 1]
                break
        
        if not target_record or not prev_record:
            # 如果找不到精确日期，使用最后两条记录
            target_record = history[-1]
            prev_record = history[-2]
            target_date = target_record.get('date', state.date)
        
        prev_nav = prev_record.get('nav', 1000)
        current_nav = target_record.get('nav', prev_nav)
        
        # 获取各资产的当日权重（使用 target_weights 或 positions_cny/nav 计算）
        # 注意：target_weights 是小数形式（如 0.10 表示 10%）
        weights = state.target_weights or {}

        rt = await self._runtime_for_reads(monitor_id)
        base_al = list(rt.asset_list) if rt else list(config.ASSET_LIST)
        al = self._asset_keys_for_positions_attribution(
            base_al, state.positions_cny, state.target_weights
        )

        model = None
        if self._is_strategy_model_monitor_id(monitor_id):
            model = await StrategyModelService().get_model(monitor_id)
        names_lookup = await self._asset_master_names_by_code(model, al)
        
        # 获取各资产的日收益率
        daily_changes = await self._get_asset_daily_changes(target_date, asset_names=al)
        
        # 归因分解计算已下沉 report_generator，service 仅保留查询编排
        return self.reporter.calc_daily_attribution(
            target_date=target_date,
            prev_nav=prev_nav,
            current_nav=current_nav,
            weights=weights,
            positions_cny=state.positions_cny,
            nav_live=float(state.nav or 0.0),
            asset_list=al,
            daily_changes=daily_changes,
            names_lookup=names_lookup,
        )

    async def _get_asset_daily_changes(
        self, as_of_date: str, asset_names: Optional[List[str]] = None
    ) -> Dict[str, Optional[float]]:
        """从 asset_prices 集合查询资产的日涨跌幅。
        
        Args:
            as_of_date: 截止日期（YYYY-MM-DD）
            asset_names: 与持仓/行情一致的资产键；默认 config.ASSET_LIST（中文名，全量模式）
            
        Returns:
            {资产键: daily_change_pct}；键与 positions 中使用的标识一致
        """
        result = {}
        prices_collection = self.db[config.MONGO_COLLECTIONS['prices']]
        names = list(asset_names) if asset_names else list(config.ASSET_LIST)
        
        for aid in names:
            if aid in config.ASSET_NAME_TO_CODE:
                stored = stored_price_code(config.ASSET_NAME_TO_CODE[aid])
            else:
                stored = str(aid).strip()

            cursor = prices_collection.find(
                {
                    'asset_code': stored,
                    'date': {'$lte': as_of_date}
                },
                {'date': 1, 'close': 1}
            ).sort('date', -1).limit(2)
            
            prices = await cursor.to_list(length=2)
            
            if len(prices) >= 2:
                latest_close = prices[0].get('close')
                prev_close = prices[1].get('close')
                if latest_close and prev_close and prev_close != 0:
                    daily_change = (latest_close / prev_close - 1) * 100
                    result[aid] = round(daily_change, 2)
                else:
                    result[aid] = None
            else:
                result[aid] = None
        
        return result

    # ============================================================
    # 日报持久化
    # ============================================================
    
    async def _save_daily_report(self, monitor_id: str, report_data: dict) -> None:
        """保存日报到 MongoDB monitor_daily_reports 集合（按 ``{monitor_id, batch_id, date}`` 覆盖）"""
        perf: Dict[str, Any] = {}
        ro = report_data.get("rebalance_observation")
        if isinstance(ro, dict) and ro:
            perf["rebalance_observation"] = ro
        cm = report_data.get("custom_metrics")
        if isinstance(cm, dict) and cm:
            perf["custom_metrics"] = cm

        batch_id = self._current_batch_id()
        report = MonitorDailyReport(
            monitor_id=monitor_id,
            batch_id=batch_id,
            date=report_data['date'],
            nav=report_data['nav'],
            daily_return=report_data.get('nav_change_pct', 0.0),
            total_leverage=report_data.get('total_leverage', 1.0),
            positions=[
                {'asset': asset, 'weight': w}
                for asset, w in report_data.get('asset_weights', {}).items()
            ],
            signals={
                'rebalance_executed': report_data.get('rebalance_executed', False),
                'rebalance_type': report_data.get('rebalance_type'),
                'vol_reset_triggered': report_data.get('vol_reset_triggered', False),
            },
            performance=perf,
            created_at=datetime.now()
        )
        
        await self.reports_collection.replace_one(
            {"monitor_id": monitor_id, "batch_id": batch_id, "date": report_data['date']},
            report.to_dict(),
            upsert=True
        )
