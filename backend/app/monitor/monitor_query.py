# -*- coding: utf-8 -*-
"""
监控服务 Mixin：读取查询接口（净值历史、事件、绩效、日报、信号状态、持仓、归因）

自 monitor_service.py 平移而来，方法体保持不变，仅按职责归组：
1. 净值历史 / 事件日志 / 绩效指标查询
2. 日报读取与持久化
3. 信号状态（月度调仓 + 波动率）查询
4. 持仓明细与损益归因查询
"""

from datetime import datetime
from typing import Dict, List, Optional, Any

from app.models.monitor import MonitorDailyReport
from app.monitor import config
from app.monitor.mongo_asset_codes import stored_price_code
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
                               start_date: str = None, end_date: str = None) -> List[dict]:
        """获取净值历史，支持日期范围筛选"""
        state = await self.get_state(monitor_id)
        if not state:
            return []
        
        history = state.nav_history
        
        if start_date:
            history = [h for h in history if h['date'] >= start_date]
        if end_date:
            history = [h for h in history if h['date'] <= end_date]
        
        return history
    
    async def get_events(self, monitor_id: str,
                          event_type: str = None, limit: int = 50) -> List[dict]:
        """获取事件日志，支持类型筛选
        
        事件类型：
        - init: 初始化
        - monthly: 月度调仓
        - vol_reset: 波动率重置（通过 stage 字段区分 trigger/execute）
        - subjective: 主观调仓
        """
        state = await self.get_state(monitor_id)
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
    
    async def get_performance(self, monitor_id: str) -> dict:
        """计算并返回绩效指标（指标计算已下沉 report_generator）"""
        state = await self.get_state(monitor_id)
        if not state:
            return {}
        
        ps = self._state_to_portfolio_state(state)
        result = self.reporter.calc_performance_api_dict(ps)
        result.update({
            'day_count': state.day_count,
            'total_trading_cost': state.total_trading_cost,
            'total_replication_cost': state.total_replication_cost,
            'vol_reset_count': state.vol_reset_count,
        })
        return result
    
    async def get_daily_report(self, monitor_id: str, date: str) -> Optional[dict]:
        """获取指定日期的日报数据"""
        doc = await self.reports_collection.find_one({
            "monitor_id": monitor_id,
            "date": date
        })
        if doc:
            doc['_id'] = str(doc['_id'])
            return doc
        return None
    
    async def get_report_list(self, monitor_id: str, skip: int = 0, limit: int = 30) -> List[dict]:
        """获取日报列表"""
        cursor = self.reports_collection.find(
            {"monitor_id": monitor_id}
        ).sort("date", -1).skip(skip).limit(limit)
        
        result = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            result.append(doc)
        
        return result
    
    async def get_signal_status(self, monitor_id: str) -> dict:
        """获取当前信号状态
        
        返回数据结构：
        - monthly_rebalance: 月度调仓信息（next_date, days_until, last_date）
        - vol_reset: 波动率重置信息（threshold, current_volatility, status, distance_to_trigger, vol_windows）
        - pending_rebalance: 待执行调仓（如有）
        - volatility_history: 波动率历史（用于趋势图）
        """
        state = await self.get_state(monitor_id)
        if not state:
            return {}

        rt = await self._runtime_for_reads(monitor_id)
        price_cols = list(rt.asset_list) if rt else None
        prices_df = await self.async_provider.load_prices(asset_columns=price_cols)
        prices_df = slice_prices_df(prices_df, rt)
        trade_dates = await self.async_provider.load_trade_dates()
        trade_dates = coerce_trade_dates(trade_dates, prices_df)
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
        threshold = (
            float(rt.vol_trigger_threshold) * 100
            if rt
            else float(config.VOL_TRIGGER_THRESHOLD) * 100
        )
        
        # 1. 当前实时波动率（使用当前权重）
        current_volatility, vol_windows = self.vol_calculator.calc_current_volatility(
            prices_df,
            dict(state.positions_local),
            dict(state.last_rebalance_fx),
            state.nav,
            state.date,
            asset_list=asset_list,
        )
        
        # 2. 波动率历史趋势（使用每个日期实际生效的权重）
        volatility_history = self.vol_calculator.calc_volatility_history(
            prices_df,
            list(state.event_log),
            state.date,
            asset_list=asset_list,
        )
        
        # 3. 状态判断
        status, distance_to_trigger = self.vol_calculator.calc_status(
            current_volatility, threshold_pct=threshold
        )
        
        # ===== 从 event_log 提取调仓历史（提取计算已下沉 signal_detector） =====
        rebalance_history = self.detector.extract_rebalance_history(state.event_log)
        
        # ===== 构建返回结果 =====
        # 优先使用 state.last_rebalance_date，若无则使用从 event_log 提取的
        final_last_rebalance_date = state.last_rebalance_date or last_rebalance_date
        
        result = {
            'monthly_rebalance': {
                'next_date': next_rebal or '无',
                'days_until': days_until,
                'last_date': final_last_rebalance_date,
            },
            'vol_reset': {
                'threshold': threshold,
                'current_volatility': current_volatility,  # 百分比形式
                'status': status,
                'distance_to_trigger': distance_to_trigger,
                'vol_windows': vol_windows,
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
    
    async def get_positions(self, monitor_id: str) -> dict:
        """获取当前持仓明细
        
        返回重新设计的字段：
        - name: 资产名称
        - code: 资产代码
        - asset_class: 资产类别（权益/固定收益/大宗商品）
        - current_weight: 当前权重%（基于市值）
        - daily_change: 当日涨跌%（底层资产价格变动）
        - currency: 计价货币
        """
        state = await self.get_state(monitor_id)
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
    
    async def get_daily_attribution(self, monitor_id: str, date: str = None) -> dict:
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
        state = await self.get_state(monitor_id)
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
        """保存日报到 MongoDB monitor_daily_reports 集合"""
        perf: Dict[str, Any] = {}
        ro = report_data.get("rebalance_observation")
        if isinstance(ro, dict) and ro:
            perf["rebalance_observation"] = ro

        report = MonitorDailyReport(
            monitor_id=monitor_id,
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
            {"monitor_id": monitor_id, "date": report_data['date']},
            report.to_dict(),
            upsert=True
        )
