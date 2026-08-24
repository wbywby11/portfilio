# -*- coding: utf-8 -*-
"""
监控服务 Mixin：单日推演引擎（步骤 A-F）

自 monitor_service.py 平移而来，方法体保持不变，仅按职责归组。
严格按以下顺序执行：
步骤A: 初始日处理（如果是基日）
步骤B: 每日损益更新 (portfolio_tracker.process_day)
步骤B2: 主观调仓检查（优先级最高）
步骤C: 执行 Pending 波动率重置调仓
步骤D: 月度调仓检查（T+2 执行）
步骤E: 波动率重置监测
步骤F: 生成日报数据
"""

import pandas as pd
from typing import Dict, List, Optional
from loguru import logger

from app.monitor import config
from app.monitor.types import PortfolioState
from app.monitor.engine_adapter import MonitorEngineAdapter
from app.monitor.monitor_runtime import resolve_asset_currency_for_monitor
from app.monitor.time_norm import normalize_calendar_timestamp

# 跳过波动率重置监测的策略模板集合
_SKIP_VOL_RESET_TEMPLATES = {
    "manual_allocation", "manual_allocation_strategy",
    "etf_cycle_rotation", "risk_parity",
}


class DailyStepperMixin:
    """单日推演方法群。

    依赖宿主（MonitorService）属性：tracker、detector、_merged_monitor_params、
    以及 ManualPresetMixin 的观察指标方法与 RebalancePlanningMixin 的适配器方法。
    """

    def _process_single_day(self, state: PortfolioState, date_str: str,
                            prices_df: pd.DataFrame, fx_df: pd.DataFrame,
                            trade_dates: List, monthly_rebalance_map: dict,
                            monthly_rebalance_dates: set,
                            vol_reset_execute_dates: set,
                            subjective_overrides: List[dict],
                            prev_nav: float,
                            base_date: str = None,
                            rt=None,
                            monthly_signal_dates: set = None,
                            vol_signal_dates: set = None) -> dict:
        """
        处理单个交易日（对应 run_monitor.py 的步骤 A-F）
        
        Args:
            base_date: 基日，用于判断是否是初始化第一天，默认使用 config.BASE_DATE
        """
        date = normalize_calendar_timestamp(pd.Timestamp(date_str))
        actual_base_ts = normalize_calendar_timestamp(
            base_date or config.BASE_DATE
        )
        al = list(self.tracker.asset_list)
        merged_params = getattr(self, "_merged_monitor_params", None) or {}
        
        # 获取价格
        prices_today = self._get_prices_for_date(prices_df, date)
        prev_dates = prices_df.index[prices_df.index < date]
        if len(prev_dates) > 0:
            prev_date = prev_dates[-1]
            prices_yesterday = self._get_prices_for_date(prices_df, prev_date)
        else:
            prices_yesterday = prices_today.copy()
        
        # 获取汇率
        fx_rates = self.tracker.get_all_fx_rates(date, fx_df)
        fx_rates_asset = self.tracker.get_all_asset_fx_rates(date, fx_df)
        
        is_rebalance_day = False
        rebalance_signal = None
        vol_reset_signal = None
        rebalance_type = None
        trading_cost = 0.0
        vol_reset_triggered = False
        vol_reset_execute_date = None
        executed_override_id = None  # 已执行的主观调仓指令ID
        
        # ================================================================
        # 步骤A: 初始日处理
        # ================================================================
        if date == actual_base_ts:
            if date in monthly_rebalance_map:
                initial_weights = monthly_rebalance_map[date]['weights']
            elif rt is not None and getattr(rt, "manual_allocation_mode", False):
                initial_weights = self._initial_manual_weights_from_params(al, merged_params)
            else:
                try:
                    adapter = self._get_engine_adapter(rt)
                    if adapter is None and rt is not None:
                        adapter = MonitorEngineAdapter.from_runtime_config(rt)
                    if adapter is not None:
                        initial_weights = adapter.compute_weights(prices_df, date)
                    else:
                        initial_weights = {a: 1.0 / len(al) for a in al} if al else {}
                except Exception as e:
                    logger.warning(f"基日权重计算失败: {e}，使用等权重")
                    initial_weights = {a: 1.0 / len(al) for a in al} if al else {}
            
            self.tracker.initialize_positions(
                state, initial_weights, fx_rates, prices_today=prices_today
            )
            state.target_weights = initial_weights.copy()
            state.last_rebalance_date = date_str
            state.last_rebalance_fx = fx_rates_asset.copy()
            state.day_count = 1
            state.date = date_str
            # 初始日 trade_day_count（与原型 trade_day_idx 对齐）
            trade_dates_ts_init = {normalize_calendar_timestamp(d) for d in trade_dates} if trade_dates else set()
            state.trade_day_count = 1 if date in trade_dates_ts_init else 0
            
            zero_weights = {a: 0.0 for a in al}
            state.event_log.append({
                'date': date_str,
                'type': 'init',
                'description': f'策略初始化，初始净值 {state.nav:.2f}',
                'trading_cost': 0.0,
                'old_weights': dict(zero_weights),
                'new_weights': dict(initial_weights),
            })
            state.nav_history.append({'date': date_str, 'nav': state.nav, 'daily_return': 0.0})  # 初始日无涨跌
            
            init_result = self._build_daily_result(state, date_str, 0.0, True, 'init', 0.0, 0.0)
            self._attach_manual_rebalance_observation(
                state, date_str, prices_df, rt, True, init_result
            )
            return init_result
        
        # ================================================================
        # 步骤B: 每日损益更新
        # ================================================================
        if prev_nav is None:
            prev_nav = state.nav
        
        daily_result = self.tracker.process_day(
            state, date_str, prices_today, prices_yesterday, fx_df, trade_dates
        )
        
        # 递增 trade_day_count（仅当日期在 trade_dates 中时，与原型 trade_day_idx 对齐）
        trade_dates_ts = {normalize_calendar_timestamp(d) for d in trade_dates} if trade_dates else set()
        if date in trade_dates_ts:
            state.trade_day_count = getattr(state, 'trade_day_count', 0) + 1
        
        # ================================================================
        # 步骤B2: 主观调仓检查
        # ================================================================
        override = self._get_override_for_date(subjective_overrides, date_str)
        if override is not None:
            old_weights = {}
            if state.nav > 0:
                for asset in al:
                    old_weights[asset] = state.positions_cny.get(asset, 0) / state.nav
            
            new_weights = override['weights']
            trading_cost = self.tracker.execute_rebalance(
                state, new_weights, fx_rates, 'subjective', prev_nav,
                prices_today=prices_today,
            )
            
            state.last_rebalance_date = date_str
            state.last_rebalance_fx = {
                asset: fx_rates.get(resolve_asset_currency_for_monitor(asset), 1.0)
                for asset in al
            }
            state.target_weights = new_weights.copy()
            
            state.event_log.append({
                'date': date_str,
                'type': 'subjective',  # 统一事件类型名称
                'description': f"执行主观调仓，交易费用 {trading_cost:.2f}",
                'trading_cost': trading_cost,
                'old_weights': old_weights,
                'new_weights': dict(new_weights),
                'override_id': override.get('override_id'),
            })
                    
            is_rebalance_day = True
            rebalance_type = 'subjective'
            # 记录已执行的 override_id，供调用方标记状态
            executed_override_id = override.get('override_id')
        
        # ================================================================
        # 步骤C: 执行 Pending 波动率重置调仓
        # 与原型一致：月度调仓优先于波动率重置（同日冲突时跳过vol_reset）
        # 额外检查：触发日到执行日之间是否存在其他调仓信号（与原型 L689-706 对齐）
        # ================================================================
        if not is_rebalance_day and state.pending_rebalance is not None:
            pending_exec_date = normalize_calendar_timestamp(
                state.pending_rebalance.get('execute_date')
            )
            pending_type = state.pending_rebalance.get('rebalance_type', '')
            # 原型规则1：vol_reset 与月度调仓同日冲突时，月度优先，跳过 vol_reset
            skip_vol_due_to_monthly = (
                pending_type == 'vol_reset'
                and date in monthly_rebalance_dates
            )
            # 原型规则2：触发日到执行日之间存在月度调仓信号或波动率触发信号时，跳过执行
            skip_vol_due_to_interval_signal = False
            skip_reason = ''
            if (
                pending_type == 'vol_reset'
                and not skip_vol_due_to_monthly
                and date == pending_exec_date
            ):
                pending_signal_date = normalize_calendar_timestamp(
                    state.pending_rebalance.get('signal_date')
                )
                # 检查月度调仓信号
                _monthly_sig_dates = monthly_signal_dates or set()
                for sig_d in _monthly_sig_dates:
                    sig_d_ts = normalize_calendar_timestamp(sig_d)
                    if pending_signal_date < sig_d_ts < pending_exec_date:
                        skip_vol_due_to_interval_signal = True
                        skip_reason = (
                            f'触发日({pending_signal_date.date()})至执行日'
                            f'({pending_exec_date.date()})间存在月度调仓'
                            f'信号({sig_d_ts.date()})'
                        )
                        break
                # 检查波动率触发信号
                if not skip_vol_due_to_interval_signal:
                    _vol_sig_dates = vol_signal_dates or set()
                    for sig_d in _vol_sig_dates:
                        sig_d_ts = normalize_calendar_timestamp(sig_d)
                        if pending_signal_date < sig_d_ts < pending_exec_date:
                            skip_vol_due_to_interval_signal = True
                            skip_reason = (
                                f'触发日({pending_signal_date.date()})至执行日'
                                f'({pending_exec_date.date()})间存在波动率触发'
                                f'信号({sig_d_ts.date()})'
                            )
                            break

            if date == pending_exec_date and not skip_vol_due_to_monthly and not skip_vol_due_to_interval_signal:
                pending_weights = state.pending_rebalance.get('weights', {})
                old_weights = dict(state.target_weights)
                trading_cost = self.tracker.execute_rebalance(
                    state, pending_weights, fx_rates, 'vol_reset', prev_nav,
                    prices_today=prices_today,
                )
                new_weights = dict(state.target_weights)
                state.last_rebalance_date = date_str
                
                state.event_log.append({
                    'date': date_str,
                    'type': 'vol_reset',  # 统一事件类型名称
                    'stage': 'execute',   # 通过 stage 区分触发/执行
                    'description': f'执行波动率重置调仓，交易费用 {trading_cost:.2f}',
                    'trading_cost': trading_cost,
                    'old_weights': old_weights,
                    'new_weights': new_weights,
                })
                
                is_rebalance_day = True
                rebalance_type = 'vol_reset'
            elif (skip_vol_due_to_monthly or skip_vol_due_to_interval_signal) and date == pending_exec_date:
                # 跳过 vol_reset
                desc = (
                    '波动率重置执行日被月度调仓覆盖（月度优先）'
                    if skip_vol_due_to_monthly
                    else f'波动率重置跳过: {skip_reason}'
                )
                state.event_log.append({
                    'date': date_str,
                    'type': 'vol_reset',
                    'stage': 'skipped',
                    'description': desc,
                })
                state.pending_rebalance = None
        
        # ================================================================
        # 步骤D: 月度调仓检查
        # ================================================================
        if not is_rebalance_day:
            rebalance_signal = self.detector.check_monthly_rebalance_execute(
                date, prices_df, trade_dates, monthly_rebalance_map
            )
            if rebalance_signal:
                old_weights = dict(state.target_weights)
                trading_cost = self.tracker.execute_rebalance(
                    state, rebalance_signal.new_weights, fx_rates, 'monthly', prev_nav,
                    prices_today=prices_today,
                )
                new_weights = dict(state.target_weights)
                state.last_rebalance_date = date_str
                state.pending_rebalance = None
                
                calc_date = rebalance_signal.signal_date
                state.event_log.append({
                    'date': date_str,
                    'type': 'monthly',  # 统一事件类型名称
                    'description': f'执行月度调仓（计算日 {calc_date}），交易费用 {trading_cost:.2f}',
                    'calc_date': calc_date,
                    'trading_cost': trading_cost,
                    'old_weights': old_weights,
                    'new_weights': new_weights,
                })
                
                is_rebalance_day = True
                rebalance_type = 'monthly'
        
        # ================================================================
        # 步骤E: 波动率监测
        # ================================================================
        if (
            not is_rebalance_day
            and state.pending_rebalance is None
            and not (rt is not None and (
                getattr(rt, "manual_allocation_mode", False)
                or getattr(rt, "template_code", "") in _SKIP_VOL_RESET_TEMPLATES
            ))
        ):
            vol_reset_signal = self.detector.check_volatility_reset(
                state, state.nav_history, trade_dates, date,
                monthly_rebalance_dates, prices_df, vol_reset_execute_dates,
                rt=rt,
                fx_df=fx_df,
            )
            if vol_reset_signal:
                state.pending_rebalance = {
                    'signal_date': vol_reset_signal.signal_date,
                    'execute_date': vol_reset_signal.execute_date,
                    'weights': vol_reset_signal.new_weights,
                    'rebalance_type': 'vol_reset',
                    'vol_trigger': vol_reset_signal.vol_trigger,
                    'scale_factor': vol_reset_signal.scale_factor,
                }
                state.vol_reset_count += 1
                vol_reset_triggered = True
                vol_reset_execute_date = vol_reset_signal.execute_date
                
                state.event_log.append({
                    'date': date_str,
                    'type': 'vol_reset',  # 统一事件类型名称
                    'stage': 'trigger',   # 通过 stage 区分触发/执行
                    'description': f'波动率触发重置，realized_vol={vol_reset_signal.vol_trigger:.4f}，'
                                   f'scale_factor={vol_reset_signal.scale_factor:.4f}，'
                                   f'执行日 {vol_reset_signal.execute_date}',
                    'vol_trigger': vol_reset_signal.vol_trigger,
                    'scale_factor': vol_reset_signal.scale_factor,
                    'execute_date': vol_reset_signal.execute_date,
                })
        
        # ================================================================
        # 步骤F: 构建结果
        # ================================================================
        # 调仓日：用扣费后的 state.nav 重新计算当日涨跌幅，与回测调仓日快照口径一致
        nav_change_pct_final = daily_result.nav_change_pct
        if is_rebalance_day and prev_nav is not None and prev_nav > 0:
            nav_change_pct_final = (state.nav / prev_nav - 1) * 100
        
        result = self._build_daily_result(
            state, date_str, nav_change_pct_final,
            is_rebalance_day, rebalance_type, trading_cost,
            daily_result.replication_cost
        )
        result['vol_reset_triggered'] = vol_reset_triggered
        result['vol_reset_execute_date'] = vol_reset_execute_date
        result['executed_override_id'] = executed_override_id  # 返回已执行的主观调仓指令ID
        result['asset_returns_local'] = daily_result.asset_returns_local
        result['asset_returns_cny'] = daily_result.asset_returns_cny

        self._attach_manual_rebalance_observation(
            state, date_str, prices_df, rt, is_rebalance_day, result
        )

        return result
    
    def _build_daily_result(self, state: PortfolioState, date_str: str,
                            nav_change_pct: float, rebalance_executed: bool,
                            rebalance_type: Optional[str], trading_cost: float,
                            replication_cost: float) -> dict:
        """构建每日处理结果字典"""
        asset_weights = self.tracker.calc_current_weights(state)
        total_leverage = sum(asset_weights.values())
        
        return {
            'date': date_str,
            'nav': state.nav,
            'nav_change_pct': nav_change_pct,
            'total_leverage': total_leverage,
            'asset_weights': asset_weights,
            'rebalance_executed': rebalance_executed,
            'rebalance_type': rebalance_type,
            'trading_cost': trading_cost,
            'replication_cost': replication_cost,
            'day_count': state.day_count,
        }

    def _get_prices_for_date(self, prices_df: pd.DataFrame, date: pd.Timestamp) -> dict:
        """获取指定日期的价格数据"""
        if date in prices_df.index:
            return prices_df.loc[date].to_dict()
        return {}
    
    def _get_override_for_date(self, overrides: List[dict], date_str: str) -> Optional[dict]:
        """获取指定日期的 pending 主观调仓指令"""
        pending = [o for o in overrides if o.get('status') == 'pending' and o.get('execute_date') == date_str]
        if not pending:
            return None
        pending.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return pending[0]
