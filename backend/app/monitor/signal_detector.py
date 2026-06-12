# -*- coding: utf-8 -*-
"""
大类资产配置监测系统 - 信号检测器

本模块实现三类信号检测和交易指令生成：
1. 月度调仓信号 (RebalanceSignal)
2. 波动率重置信号 (VolResetSignal)
3. 权重偏离度计算 (DeviationInfo)
4. 交易指令生成 (TradeOrder)

注意：核心计算逻辑与 monitor_vs 完全一致，不做任何算法修改
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Union, TYPE_CHECKING

from app.monitor import config

if TYPE_CHECKING:
    from app.monitor.monitor_runtime import MonitorRuntimeConfig
from app.monitor.time_norm import normalize_calendar_timestamp
from app.monitor.strategy_engine import StrategyEngine
from app.monitor.types import (
    PortfolioState, AssetSelectionResult, WeightResult,
    RebalanceSignal, VolResetSignal, DeviationInfo, TradeOrder
)

logger = logging.getLogger(__name__)

# 纯权重分配型策略的 template_code 集合
_ALLOCATION_ONLY_TEMPLATES = frozenset({"etf_cycle_rotation", "risk_parity"})


class SignalDetector:
    """信号检测器 - 检测调仓信号并生成交易指令"""
    
    def __init__(self):
        """初始化信号检测器"""
        self.engine = StrategyEngine()  # 用于月度调仓时的资产选择和权重计算
        self._annualize_factor = np.sqrt(config.ANNUALIZE_FACTOR)
    
    # =========================================================================
    # 月度调仓检测
    # =========================================================================
    
    def check_monthly_rebalance_execute(self, date, prices_df: pd.DataFrame, 
                                         trade_dates: List,
                                         monthly_rebalance_map: dict) -> Optional[RebalanceSignal]:
        """
        检查是否为月度调仓执行日（T+2）
        
        判定逻辑：
        1. 检查当前日期是否在 monthly_rebalance_map 的执行日中
        2. 如果是，返回 RebalanceSignal 以执行调仓
        3. 月度调仓是"立即执行"的，但执行日是 T+2
        
        Args:
            date: 当前日期（字符串或 Timestamp）
            prices_df: 价格数据 DataFrame
            trade_dates: 交易日列表
            monthly_rebalance_map: {执行日期: {'weights': 权重字典, 'calc_date': 计算日期}}
            
        Returns:
            RebalanceSignal 如果是调仓执行日，否则 None
        """
        date_ts = normalize_calendar_timestamp(date)
        date_str = date_ts.strftime('%Y-%m-%d')
        
        # 检查是否是调仓执行日
        if date_ts not in monthly_rebalance_map:
            return None
        
        rebalance_info = monthly_rebalance_map[date_ts]
        weights = rebalance_info['weights']
        calc_date = rebalance_info['calc_date']
        
        return RebalanceSignal(
            signal_type='monthly',
            signal_date=calc_date,  # 原始计算日
            execute_date=date_str,  # 执行日（T+2）
            new_weights=weights,
            selection_result=None,  # 已预计算，不需要再次选择
            weight_result=None,  # 已预计算
        )
    
    def check_monthly_rebalance(self, date, prices_df: pd.DataFrame, 
                                 trade_dates: List,
                                 rt: Optional["MonitorRuntimeConfig"] = None) -> Optional[RebalanceSignal]:
        """
        检查是否为调仓日（旧接口，保留兼容性）
        
        根据 rt.template_code 路由到不同执行路径：
        - risk_budget_target_vol / 默认: 资产选择 + 权重计算（月度调仓）
        - etf_cycle_rotation / risk_parity: 纯权重分配（支持周频/月频）
        - manual_allocation: 不在此方法处理
        """
        date_ts = normalize_calendar_timestamp(date)
        template_code = getattr(rt, 'template_code', 'risk_budget_target_vol') if rt else 'risk_budget_target_vol'
        rebalance_frequency = (rt.strategy_params or {}).get('rebalance_frequency', 'monthly') if rt else 'monthly'
        if not rebalance_frequency:
            rebalance_frequency = 'monthly'

        # ---------- 纯权重分配型策略分支 ----------
        if template_code in _ALLOCATION_ONLY_TEMPLATES:
            # 判断是否到达调仓日
            if rebalance_frequency == 'weekly':
                if not self._is_week_end_trade_date(date_ts, trade_dates):
                    return None
            else:  # monthly 或其他
                if not self._is_month_end_trade_date(date_ts, trade_dates):
                    return None

            weight_result = self.engine.run_weight_calculation_for_allocation_strategy(
                prices_df, date_ts, rt
            )
            date_str = date_ts.strftime('%Y-%m-%d')
            signal_type = 'weekly' if rebalance_frequency == 'weekly' else 'monthly'
            return RebalanceSignal(
                signal_type=signal_type,
                signal_date=date_str,
                execute_date=date_str,
                new_weights=weight_result.weights,
                selection_result=None,
                weight_result=weight_result,
            )

        # ---------- 默认路径：risk_budget_target_vol ----------
        # 检查是否是月末交易日
        if not self._is_month_end_trade_date(date_ts, trade_dates):
            return None
        
        # 执行资产选择
        selection_result = self.engine.run_asset_selection(prices_df, date_ts, rt=rt)
        
        # 执行权重计算
        weight_result = self.engine.run_weight_calculation(
            prices_df, selection_result, date_ts, rt=rt
        )
        
        date_str = date_ts.strftime('%Y-%m-%d')
        
        return RebalanceSignal(
            signal_type='monthly',
            signal_date=date_str,
            execute_date=date_str,
            new_weights=weight_result.weights,
            selection_result=selection_result,
            weight_result=weight_result,
        )
    
    def _is_week_end_trade_date(self, date, trade_dates: List) -> bool:
        """
        判断是否是周末交易日
        
        方法：下一个交易日的 ISO 周序号 != 当前交易日的 ISO 周序号，
        或当前交易日是最后一个交易日。
        """
        date_ts = normalize_calendar_timestamp(date)
        trade_dates_ts = [normalize_calendar_timestamp(d) for d in trade_dates]

        if date_ts not in trade_dates_ts:
            return False

        idx = trade_dates_ts.index(date_ts)
        if idx + 1 >= len(trade_dates_ts):
            return True

        next_date = trade_dates_ts[idx + 1]
        # ISO 周序号不同即跨周
        return date_ts.isocalendar()[1] != next_date.isocalendar()[1]

    def _is_month_end_trade_date(self, date, trade_dates: List) -> bool:
        """
        判断是否是月末交易日
        
        方法：下一个交易日的月份 != 当前交易日的月份
        """
        date_ts = normalize_calendar_timestamp(date)
        
        # 将交易日列表转为 Timestamp
        trade_dates_ts = [normalize_calendar_timestamp(d) for d in trade_dates]
        
        # 检查 date 是否在交易日列表中
        if date_ts not in trade_dates_ts:
            return False
        
        # 找到下一个交易日
        idx = trade_dates_ts.index(date_ts)
        if idx + 1 >= len(trade_dates_ts):
            # 最后一个交易日，视为月末
            return True
        
        next_date = trade_dates_ts[idx + 1]
        
        # 比较月份
        return date_ts.month != next_date.month
    
    # =========================================================================
    # 波动率重置检测
    # =========================================================================
    
    def check_volatility_reset(self, state: PortfolioState, 
                                nav_history: List[Dict],
                                trade_dates: List,
                                date,
                                monthly_rebalance_dates: set = None,
                                prices_df: pd.DataFrame = None,
                                vol_reset_execute_dates: set = None,
                                rt: Optional["MonitorRuntimeConfig"] = None) -> Optional[VolResetSignal]:
        """
        检查是否触发波动率重置
        
        前提条件（全部满足才检查）：
        1. state.day_count > config.MONITOR_START_DAYS (60天)
        2. 当天没有月度调仓（月度调仓优先级更高）
        3. 没有已经 pending 的调仓
        
        计算逻辑：
        1. 计算当前实际权重 w_cny（使用调仓日汇率）
        2. 使用 prices_df 计算各资产日收益率
        3. 用 w_cny 加权计算组合日收益率
        4. 计算三个窗口的年化波动率，取 max
        5. 如果 realized_vol > VOL_TRIGGER_THRESHOLD (0.06)：
           a. scale_factor = TARGET_VOL / realized_vol
           b. VW权重 = w_cny * scale_factor（小数点后三位截断）
           c. 计算执行日 = T+2
           d. 冲突检查（包括月度调仓日和之前的波动率重置执行日）
           e. 返回 VolResetSignal
        
        Args:
            state: 组合状态
            nav_history: 净值历史列表 [{'date': date, 'nav': nav}, ...]
            trade_dates: 交易日列表
            date: 当前日期
            monthly_rebalance_dates: 月度调仓日期集合（用于冲突检查）
            prices_df: 价格数据 DataFrame（用于计算波动率）
            vol_reset_execute_dates: 之前波动率重置的执行日期集合（用于冲突检查）
            
        Returns:
            VolResetSignal 如果触发，否则 None
        """
        date_ts = pd.Timestamp(date)
        date_str = date_ts.strftime('%Y-%m-%d')

        asset_list = list(rt.asset_list) if rt else list(config.ASSET_LIST)
        target_vol = float(rt.target_vol) if rt else float(config.TARGET_VOL)
        vol_trigger_threshold = (
            float(rt.vol_trigger_threshold) if rt else float(config.VOL_TRIGGER_THRESHOLD)
        )
        
        # 前提条件1：day_count > MONITOR_START_DAYS
        if state.day_count <= config.MONITOR_START_DAYS:
            return None
        
        # 前提条件3：没有已经 pending 的调仓
        if state.pending_rebalance is not None:
            return None
        
        # 前提条件2：当天没有月度调仓
        if monthly_rebalance_dates and date_ts in monthly_rebalance_dates:
            return None
        
        # 1. 计算当前实际权重 w_cny（使用调仓日汇率）
        if state.nav <= 0:
            return None
        
        # 使用本币持仓 × 调仓日汇率 / 净值 计算权重
        # 注意：last_rebalance_fx 键是资产名
        w_cny = {}
        for asset in asset_list:
            pos_local = state.positions_local.get(asset, 0.0)
            # 获取调仓日汇率（last_rebalance_fx 键是资产名）
            fx_rate = state.last_rebalance_fx.get(asset, 1.0)
            w_cny[asset] = pos_local * fx_rate / state.nav
        
        # 2. 使用 prices_df 计算波动率
        if prices_df is None or prices_df.empty:
            return None
        
        # 找出有持仓的资产
        assets_with_position = [a for a in asset_list if w_cny.get(a, 0.0) > 1e-8]
        if not assets_with_position:
            return None
        
        use_cols = [a for a in asset_list if a in prices_df.columns]
        if not use_cols:
            return None
        # 仅取最长波动窗口所需价格子集再 pct_change，避免每日对全历史 O(行×列) 重算
        max_w = max(config.VOL_WINDOWS)
        need_rows = max_w + 2  # 130 日波动需约 131 个价位得到 130 个收益
        loc = prices_df.index.get_loc(date_ts)
        if isinstance(loc, slice):
            idx = loc.stop - 1 if loc.stop is not None else loc.start
        elif isinstance(loc, np.ndarray):
            nz = np.flatnonzero(loc)
            if nz.size == 0:
                return None
            idx = int(nz[-1])
        else:
            idx = int(loc)
        start_i = max(0, idx - need_rows + 1)
        sub_px = prices_df.iloc[start_i : idx + 1][use_cols]
        daily_ret_df = sub_px.pct_change(fill_method=None).fillna(0)
        ytd_ret = daily_ret_df[assets_with_position]
        
        if len(ytd_ret) < config.VOL_WINDOWS[0]:  # 至少需要22天数据
            return None
        
        # 3. 计算加权组合波动率
        vol_values = []
        w_series = pd.Series({a: w_cny.get(a, 0.0) for a in assets_with_position})
        windows = config.VOL_WINDOWS  # [22, 65, 130]
        
        for n in windows:
            if len(ytd_ret) >= n:
                ret_window = ytd_ret.iloc[-n:]
                weighted_ret = (ret_window * w_series).sum(axis=1)
                vol = weighted_ret.std() * self._annualize_factor
                if not np.isnan(vol):
                    vol_values.append(vol)
        
        if not vol_values:
            return None
        
        # 4. realized_vol = max(vol_22, vol_65, vol_130)
        realized_vol = max(vol_values)
        
        # 5. 判断是否触发
        if realized_vol <= vol_trigger_threshold:
            return None
        
        # 6. 计算缩放因子和 VW 权重
        scale_factor = target_vol / realized_vol
        vw_weights = {asset: w * scale_factor for asset, w in w_cny.items()}
        
        # 7. 权重截断（小数点后三位，消除计算摩擦）
        vw_weights = {asset: np.trunc(w * 1000) / 1000 for asset, w in vw_weights.items()}
        
        # 8. 计算执行日 T+2
        execute_date = self.calc_t_plus_2(date_str, trade_dates)
        if execute_date is None:
            return None
        
        # 9. 冲突检查：检查 [t, T+1, T+2] 区间（同时检查月度调仓日和波动率重置执行日）
        if self._has_conflict(date_ts, execute_date, trade_dates, 
                              monthly_rebalance_dates, vol_reset_execute_dates):
            return None
        
        return VolResetSignal(
            signal_type='vol_reset',
            signal_date=date_str,
            execute_date=execute_date,
            vol_trigger=realized_vol,
            scale_factor=scale_factor,
            current_weights=w_cny.copy(),
            new_weights=vw_weights,
        )
    
    def _has_conflict(self, signal_date, execute_date: str, 
                      trade_dates: List, monthly_rebalance_dates: set = None,
                      vol_reset_execute_dates: set = None) -> bool:
        """
        检查 [signal_date, T+1, T+2] 区间内是否有调仓冲突
        
        同时检查 rebalance_dates_set 和 vol_reset_dates_set
        
        Args:
            signal_date: 信号日（Timestamp）
            execute_date: 执行日（字符串）
            trade_dates: 交易日列表
            monthly_rebalance_dates: 月度调仓日期集合
            vol_reset_execute_dates: 之前波动率重置的执行日期集合
            
        Returns:
            True 如果有冲突，False 否则
        """
        signal_ts = normalize_calendar_timestamp(signal_date)
        execute_ts = normalize_calendar_timestamp(execute_date)
        
        trade_dates_ts = [normalize_calendar_timestamp(d) for d in trade_dates]
        
        # 合并检查集合：月度调仓日 + 波动率重置执行日
        conflict_dates = set()
        if monthly_rebalance_dates:
            conflict_dates.update(
                normalize_calendar_timestamp(d) for d in monthly_rebalance_dates
            )
        if vol_reset_execute_dates:
            conflict_dates.update(
                normalize_calendar_timestamp(d) for d in vol_reset_execute_dates
            )
        
        # 找到 T+1
        future_dates = [d for d in trade_dates_ts if d > signal_ts]
        t_plus_1 = future_dates[0] if len(future_dates) >= 1 else None
        
        # 检查信号日 t
        if signal_ts in conflict_dates:
            return True
        
        # 检查 T+1
        if t_plus_1 and t_plus_1 in conflict_dates:
            return True
        
        # 检查 T+2 执行日
        if execute_ts in conflict_dates:
            return True
        
        return False
    
    # =========================================================================
    # 权重偏离度计算
    # =========================================================================
    
    def check_weight_deviation(self, state: PortfolioState, 
                                fx_rates: Dict[str, float] = None,
                                asset_list: Optional[List[str]] = None) -> List[DeviationInfo]:
        """
        计算各资产的权重偏离度
        
        对每个有持仓的资产：
        - actual_weight = positions_cny[asset] / nav
        - target_weight = target_weights[asset]
        - deviation = actual - target
        - deviation_pct = deviation / target * 100 (target为0时设为0)
        
        Args:
            state: 组合状态
            fx_rates: 汇率字典（可选，用于更精确的权重计算）
            
        Returns:
            偏离度列表，按偏离绝对值降序排列
        """
        if state.nav <= 0:
            return []
        
        deviations = []
        assets = asset_list if asset_list is not None else list(config.ASSET_LIST)
        
        for asset in assets:
            target_weight = state.target_weights.get(asset, 0.0)
            actual_weight = state.positions_cny.get(asset, 0.0) / state.nav
            
            deviation = actual_weight - target_weight
            
            if target_weight != 0:
                deviation_pct = deviation / target_weight * 100
            else:
                deviation_pct = 0.0
            
            deviations.append(DeviationInfo(
                asset=asset,
                target_weight=target_weight,
                actual_weight=actual_weight,
                deviation=deviation,
                deviation_pct=deviation_pct,
            ))
        
        # 按偏离绝对值降序排列
        deviations.sort(key=lambda x: abs(x.deviation), reverse=True)
        
        return deviations
    
    # =========================================================================
    # 交易指令生成
    # =========================================================================
    
    def generate_trade_orders(self, signal: Union[RebalanceSignal, VolResetSignal], 
                               state: PortfolioState,
                               asset_list: Optional[List[str]] = None) -> List[TradeOrder]:
        """
        根据信号生成交易指令
        
        对 RebalanceSignal 或 VolResetSignal：
        - 比较 new_weights 与当前 positions_cny/nav
        - 计算每个资产的权重变动
        - 估算交易金额（基于当前 NAV）
        - 返回 TradeOrder 列表，按交易金额绝对值降序
        
        Args:
            signal: 调仓信号（RebalanceSignal 或 VolResetSignal）
            state: 组合状态
            
        Returns:
            TradeOrder 列表
        """
        if state.nav <= 0:
            return []
        
        new_weights = signal.new_weights
        orders = []
        assets = asset_list if asset_list is not None else list(config.ASSET_LIST)
        
        for asset in assets:
            target_weight = new_weights.get(asset, 0.0)
            current_weight = state.positions_cny.get(asset, 0.0) / state.nav
            
            weight_change = target_weight - current_weight
            estimated_amount = abs(weight_change) * state.nav
            
            # 只生成有变动的交易指令
            if abs(weight_change) > 1e-6:  # 忽略极小变动
                direction = 'buy' if weight_change > 0 else 'sell'
                
                orders.append(TradeOrder(
                    asset=asset,
                    direction=direction,
                    target_weight=target_weight,
                    current_weight=current_weight,
                    weight_change=weight_change,
                    estimated_amount_cny=estimated_amount,
                ))
        
        # 按交易金额绝对值降序
        orders.sort(key=lambda x: abs(x.estimated_amount_cny), reverse=True)
        
        return orders
    
    # =========================================================================
    # 日期计算辅助方法
    # =========================================================================
    
    def get_next_rebalance_date(self, current_date, trade_dates: List) -> Optional[str]:
        """
        获取下一个月末调仓日
        
        Args:
            current_date: 当前日期
            trade_dates: 交易日列表
            
        Returns:
            下一个月末调仓日的字符串，如果没有则返回 None
        """
        current_ts = normalize_calendar_timestamp(current_date)
        trade_dates_ts = [normalize_calendar_timestamp(d) for d in trade_dates]
        
        # 找到当前日期之后的所有交易日
        future_dates = [d for d in trade_dates_ts if d > current_ts]
        
        if not future_dates:
            return None
        
        # 遍历寻找月末交易日
        for i, date in enumerate(future_dates):
            if self._is_month_end_trade_date(date, trade_dates_ts):
                return date.strftime('%Y-%m-%d')
        
        return None
    
    def calc_t_plus_2(self, signal_date, trade_dates: List) -> Optional[str]:
        """
        计算 T+2 执行日期
        
        从信号日的下一个交易日开始计数，找到第2个有效交易日
        排除 SKIP_EXCLUDED_DATES 中的日期
        
        Args:
            signal_date: 信号日期（字符串）
            trade_dates: 交易日列表
            
        Returns:
            执行日期字符串，如果交易日不足则返回 None
        """
        excluded = {
            normalize_calendar_timestamp(d) for d in config.SKIP_EXCLUDED_DATES
        }
        signal_ts = normalize_calendar_timestamp(signal_date)
        
        trade_dates_ts = [normalize_calendar_timestamp(d) for d in trade_dates]
        
        # 找到信号日之后的交易日
        future_dates = [d for d in trade_dates_ts if d > signal_ts]
        
        if len(future_dates) < 2:
            return None
        
        # T+2: 第2个交易日（索引 [1]）
        execute_date = future_dates[1]
        
        # 跳过排除日：在完整的 trade_dates_ts 中查索引
        while execute_date in excluded:
            idx = trade_dates_ts.index(execute_date)  # 在完整列表中查
            if idx + 1 < len(trade_dates_ts):
                execute_date = trade_dates_ts[idx + 1]
            else:
                return None
        
        return execute_date.strftime('%Y-%m-%d')
    
    def get_month_end_dates(self, trade_dates: List) -> List[str]:
        """
        获取所有月末交易日
        
        Args:
            trade_dates: 交易日列表
            
        Returns:
            月末交易日列表
        """
        trade_dates_ts = [normalize_calendar_timestamp(d) for d in trade_dates]
        month_ends = []
        
        for i, date in enumerate(trade_dates_ts):
            if self._is_month_end_trade_date(date, trade_dates_ts):
                month_ends.append(date.strftime('%Y-%m-%d'))
        
        return month_ends
