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
from app.backtesting.events import (
    EVENT_INIT,
    EVENT_MONTHLY,
    EVENT_SUBJECTIVE,
    EVENT_VOL_RESET,
    STAGE_EXECUTE,
    STAGE_SKIPPED,
    STAGE_TRIGGER,
    make_event,
)

# 跳过波动率重置监测的策略模板集合
_SKIP_VOL_RESET_TEMPLATES = {
    "manual_allocation", "manual_allocation_strategy",
    "etf_cycle_rotation", "risk_parity",
}


def _json_safe(value):
    """递归把 numpy / 非 JSON 原生类型转成可落库形式。"""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    # ndarray / Index 等多元素容器：先 tolist 再递归，避免整块退化成字符串
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _json_safe(tolist())
        except Exception:
            pass
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            return str(value)
    return str(value)


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
                            vol_signal_dates: set = None,
                            operation_events: Optional[List[dict]] = None,
                            enable_risk_alerts: bool = False) -> dict:
        """
        处理单个交易日（对应 run_monitor.py 的步骤 A-F）
        
        Args:
            base_date: 基日，用于判断是否是初始化第一天，默认使用 config.BASE_DATE
            operation_events: 操作指令事件收集列表；双轨并行步进时由调用方传入实际轨的共享列表，
                              避免模型轨事件重复落库（None 表示新建私有列表）
            enable_risk_alerts: 是否在本日计算风险预警（步骤 E3）。预警是「当前状态」
                              语义，主循环只在本次运行的最后一个处理日置 True；模型轨
                              始终不计算，避免同一实例重复写批。
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
        if operation_events is None:
            operation_events = []  # 操作指令事件（由服务层异步落库）
        
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
            state.event_log.append(make_event(
                date_str, EVENT_INIT,
                description=f'策略初始化，初始净值 {state.nav:.2f}',
                trading_cost=0.0,
                old_weights=dict(zero_weights),
                new_weights=dict(initial_weights),
                event_log=state.event_log,
            ))
            state.nav_history.append({'date': date_str, 'nav': state.nav, 'daily_return': 0.0})  # 初始日无涨跌
            
            init_result = self._build_daily_result(state, date_str, 0.0, True, 'init', 0.0, 0.0)
            # 与步骤F的结果契约对齐：初始日同样携带双轨与操作指令键，
            # 否则 run_init 首日服务层直取 result['operation_events'] 会 KeyError
            init_result['vol_reset_triggered'] = False
            init_result['vol_reset_execute_date'] = None
            init_result['executed_override_id'] = None
            init_result['operation_events'] = operation_events
            init_result['asset_returns_local'] = {}
            init_result['asset_returns_cny'] = {}
            # 步骤E3（基日路径）：单日初始化时也产出预警，保证「只跑一天」也能落库
            init_result['risk_alerts'] = (
                self._risk_alerts_for_state(state, prices_df, date)
                if enable_risk_alerts else []
            )
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
            
            state.event_log.append(make_event(
                date_str, EVENT_SUBJECTIVE,
                description="执行主观调仓",
                trading_cost=trading_cost,
                old_weights=old_weights,
                new_weights=dict(new_weights),
                override_id=override.get('override_id'),
                event_log=state.event_log,
            ))
                    
            is_rebalance_day = True
            rebalance_type = 'subjective'
            # 记录已执行的 override_id，供调用方标记状态
            executed_override_id = override.get('override_id')
            operation_events.append({
                'kind': 'subjective_executed',
                'override_ref': executed_override_id,
            })
        
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
                # 信号日先取出：execute_rebalance 可能清空 pending_rebalance
                pending_signal_date = state.pending_rebalance.get('signal_date')
                old_weights = dict(state.target_weights)
                trading_cost = self.tracker.execute_rebalance(
                    state, pending_weights, fx_rates, 'vol_reset', prev_nav,
                    prices_today=prices_today,
                )
                new_weights = dict(state.target_weights)
                state.last_rebalance_date = date_str
                
                state.event_log.append(make_event(
                    date_str, EVENT_VOL_RESET, stage=STAGE_EXECUTE,
                    signal_date=pending_signal_date,
                    description='执行波动率重置调仓',
                    trading_cost=trading_cost,
                    old_weights=old_weights,
                    new_weights=new_weights,
                    event_log=state.event_log,
                ))
                
                is_rebalance_day = True
                rebalance_type = 'vol_reset'
                operation_events.append({
                    'kind': 'vol_executed',
                    'execute_date': date_str,
                    'prev_weights': old_weights,
                })
            elif (skip_vol_due_to_monthly or skip_vol_due_to_interval_signal) and date == pending_exec_date:
                # 跳过 vol_reset
                skip_signal_date_str = str(state.pending_rebalance.get('signal_date') or '')[:10]
                desc = (
                    '波动率重置执行日被月度调仓覆盖（月度优先）'
                    if skip_vol_due_to_monthly
                    else f'波动率重置跳过: {skip_reason}'
                )
                state.event_log.append(make_event(
                    date_str, EVENT_VOL_RESET, stage=STAGE_SKIPPED,
                    signal_date=state.pending_rebalance.get('signal_date'),
                    description=desc,
                    event_log=state.event_log,
                ))
                state.pending_rebalance = None
                if skip_signal_date_str:
                    operation_events.append({
                        'kind': 'vol_cancelled',
                        'signal_date': skip_signal_date_str,
                        'reason': desc,
                    })
        
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
                state.event_log.append(make_event(
                    date_str, EVENT_MONTHLY,
                    signal_date=calc_date,
                    description=f'执行月度调仓（计算日 {calc_date}）',
                    trading_cost=trading_cost,
                    old_weights=old_weights,
                    new_weights=new_weights,
                    event_log=state.event_log,
                ))
                
                is_rebalance_day = True
                rebalance_type = 'monthly'
                operation_events.append({
                    'kind': 'monthly_executed',
                    'execute_date': date_str,
                    'prev_weights': old_weights,
                })
        
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
                
                state.event_log.append(make_event(
                    date_str, EVENT_VOL_RESET, stage=STAGE_TRIGGER,
                    signal_date=vol_reset_signal.signal_date,
                    execute_date=vol_reset_signal.execute_date,
                    description=f'波动率触发重置，realized_vol={vol_reset_signal.vol_trigger:.4f}，'
                                f'scale_factor={vol_reset_signal.scale_factor:.4f}，'
                                f'执行日 {vol_reset_signal.execute_date}',
                    vol_trigger=vol_reset_signal.vol_trigger,
                    scale_factor=vol_reset_signal.scale_factor,
                    event_log=state.event_log,
                ))
                operation_events.append({
                    'kind': 'vol_triggered',
                    'signal_date': str(vol_reset_signal.signal_date)[:10],
                    'execute_date': str(vol_reset_signal.execute_date)[:10],
                    'target_weights': dict(vol_reset_signal.new_weights or {}),
                    'suggestion': {
                        'vol_trigger': vol_reset_signal.vol_trigger,
                        'vol_trigger_threshold': vol_reset_signal.vol_trigger_threshold,
                        'vol_windows': list(vol_reset_signal.vol_windows or []),
                        'scale_factor': vol_reset_signal.scale_factor,
                        'description': (
                            f'实时波动 {vol_reset_signal.vol_trigger:.4f} 超阈值 '
                            f'{vol_reset_signal.vol_trigger_threshold:.4f}，'
                            f'建议按 {vol_reset_signal.scale_factor:.4f} 缩放仓位'
                        ),
                    },
                })
        
        # ================================================================
        # 步骤E2: 策略自定义监控指标（通用路径，无策略特判）
        # ================================================================
        state.custom_metrics = self._compute_custom_metrics(state, prices_df, date, rt)

        # ================================================================
        # 步骤E3: 风险预警计算（波动率比较 / 相关性反转）
        # ================================================================
        # 只计算不落库：_process_single_day 是同步方法且双轨都会经过这里，
        # 写入 monitor_risk_alerts 统一由服务层在实际轨主循环里完成。
        risk_alerts: List[dict] = []
        if enable_risk_alerts:
            risk_alerts = self._risk_alerts_for_state(state, prices_df, date)

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
        result['operation_events'] = operation_events  # 操作指令事件（服务层异步落库）
        result['asset_returns_local'] = daily_result.asset_returns_local
        result['asset_returns_cny'] = daily_result.asset_returns_cny
        result['custom_metrics'] = dict(getattr(state, 'custom_metrics', {}) or {})
        result['risk_alerts'] = risk_alerts

        self._attach_manual_rebalance_observation(
            state, date_str, prices_df, rt, is_rebalance_day, result
        )

        return result
    
    def _risk_alerts_for_state(self, state: PortfolioState, prices_df: pd.DataFrame, date) -> List[dict]:
        """步骤E3 的内部实现：按当前目标权重算预警；异常不阻断推演。

        研究员通道（独立引擎）不走本方法，本期不覆盖风险预警。
        """
        try:
            return self.compute_risk_alerts(
                dict(state.target_weights or {}), prices_df, as_of=date
            )
        except Exception as e:
            logger.warning(f"风险预警计算失败（不影响推演）: date={date}, error={e}")
            return []

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

    def _compute_custom_metrics(self, state: PortfolioState, prices_df: pd.DataFrame,
                               date: pd.Timestamp, rt=None) -> dict:
        """通用：取本策略声明的自定义监控指标写入日度状态。

        适配器内部委托 CompositionPipeline → allocator.compute_monitoring_metrics，
        未实现该接口的策略返回空字典，存量策略落库内容不变。
        计算失败不阻断日度推演，记 warning 并保留为空。
        """
        try:
            adapter = self._get_engine_adapter(rt)
            if adapter is None and rt is not None:
                adapter = MonitorEngineAdapter.from_runtime_config(rt)
            if adapter is None:
                return {}
            hist = prices_df.loc[prices_df.index <= date]
            if hist is None or hist.empty:
                return {}
            raw_w = getattr(state, 'target_weights', None) or {}
            weights = pd.Series({
                str(k): float(v or 0) for k, v in raw_w.items()
                if str(k) in hist.columns
            })
            if weights.empty or float(weights.abs().sum()) <= 0:
                return {}
            metrics = adapter.compute_monitoring_metrics(
                current_weights=weights, prices_df=hist
            )
            return _json_safe(metrics) if isinstance(metrics, dict) else {}
        except Exception as exc:
            logger.warning(f"策略自定义监控指标计算失败 {str(date)[:10]}: {exc}")
            return {}

    def _get_prices_for_date(self, prices_df: pd.DataFrame, date: pd.Timestamp) -> dict:
        """获取指定日期的价格数据"""
        if date in prices_df.index:
            return prices_df.loc[date].to_dict()
        return {}
    
    def _get_override_for_date(self, overrides: List[dict], date_str: str) -> Optional[dict]:
        """取当日生效的主观指令；待执行与已执行补录同等参与，同日取最新创建。

        已执行指令只在全量重放（初始化/补录重算）时进入列表，fold 续接场景
        由调用方只传当前批次 pending，历史执行结果已在父状态里。
        """
        matched = [
            o for o in overrides
            if o.get('status') in ('pending', 'executed')
            and (o.get('aligned_date') or o.get('execute_date')) == date_str
        ]
        if not matched:
            return None
        matched.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        return matched[0]
