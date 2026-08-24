# -*- coding: utf-8 -*-
"""
波动率计算模块 - 负责组合波动率的各种计算

职责：
1. 计算当前实时波动率（使用当前权重 + 资产价格）
2. 计算波动率历史趋势（使用每个日期实际生效的权重 + 资产价格）
3. 从 event_log 重建权重变化历史
"""

import warnings
warnings.filterwarnings('ignore', category=FutureWarning)

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from loguru import logger

from app.monitor import config


class VolatilityCalculator:
    """波动率计算器"""
    
    def __init__(self):
        self.annualize_factor = np.sqrt(config.ANNUALIZE_FACTOR)  # √260
        self.threshold = config.VOL_TRIGGER_THRESHOLD * 100  # 百分比形式
    
    def calc_current_volatility(self, prices_df: pd.DataFrame,
                                 positions_local: Dict[str, float],
                                 last_rebalance_fx: Dict[str, float],
                                 nav: float,
                                 current_date: str,
                                 asset_list: Optional[List[str]] = None,
                                 w_cny: Optional[Dict[str, float]] = None) -> Tuple[Optional[float], Dict[str, float]]:
        """计算当前实时波动率（使用当前权重 + 资产价格，与 signal_detector 一致）
        
        Args:
            prices_df: 资产价格 DataFrame
            positions_local: 本币持仓金额（仅在 w_cny 未传时使用，旧公式）
            last_rebalance_fx: 调仓日汇率（仅在 w_cny 未传时使用）
            nav: 组合净值
            current_date: 当前日期
            asset_list: 资产列表
            w_cny: 预计算的人民币权重 {asset: weight}。
                   传入时优先使用，跳过内部权重计算。
                   推荐使用 signal_detector 公式：
                   w = (positions_cny_base + apl_local × fx_today) / nav
        
        Returns:
            (current_volatility, vol_windows)
            current_volatility: 百分比形式的最大窗口波动率，如 5.50
            vol_windows: {'22天': x, '65天': x, '130天': x}
        """
        vol_windows = {}
        current_volatility = None
        
        if prices_df is None or prices_df.empty or nav <= 0:
            return current_volatility, vol_windows
        
        try:
            assets = asset_list if asset_list is not None else list(config.ASSET_LIST)
            
            if w_cny is None:
                # 回退：旧公式（仅用于无 positions_cny_base 的场景）
                w_cny = {}
                for asset in assets:
                    pos_local = positions_local.get(asset, 0.0)
                    fx_rate = last_rebalance_fx.get(asset, 1.0)
                    w_cny[asset] = pos_local * fx_rate / nav
            
            assets_with_position = [a for a in assets if w_cny.get(a, 0.0) > 1e-8]
            
            if not assets_with_position:
                return current_volatility, vol_windows
            
            use_cols = [a for a in assets if a in prices_df.columns]
            if not use_cols:
                return current_volatility, vol_windows
            # 计算日收益率
            daily_ret_df = prices_df[use_cols].pct_change(fill_method=None).fillna(0)
            current_date_ts = pd.Timestamp(current_date)
            ytd_ret = daily_ret_df.loc[:current_date_ts, assets_with_position]
            
            if len(ytd_ret) < config.VOL_WINDOWS[0]:
                return current_volatility, vol_windows
            
            w_series = pd.Series({a: w_cny.get(a, 0.0) for a in assets_with_position})
            weighted_returns = (ytd_ret * w_series).sum(axis=1)
            
            vol_values = []
            for window in config.VOL_WINDOWS:
                if len(weighted_returns) >= window:
                    ret_window = weighted_returns.iloc[-window:]
                    vol = float(ret_window.std() * self.annualize_factor) * 100
                    vol_windows[f'{window}天'] = round(vol, 2)
                    if not np.isnan(vol):
                        vol_values.append(vol)
            
            if vol_values:
                current_volatility = round(max(vol_values), 2)
        
        except Exception as e:
            logger.warning(f"计算当前波动率失败: {e}")
        
        return current_volatility, vol_windows
    
    def calc_volatility_history(self, prices_df: pd.DataFrame,
                                 event_log: List[dict],
                                 current_date: str,
                                 lookback_days: int = None,
                                 asset_list: Optional[List[str]] = None) -> List[dict]:
        """计算波动率历史趋势（每个日期使用该日期实际生效的权重）
        
        核心逻辑：
        1. 从 event_log 重建权重变化时间线
        2. 对趋势期间的每个交易日，查找该日生效的权重
        3. 用该权重 + 资产价格滚动窗口计算波动率
        
        Args:
            prices_df: 资产价格 DataFrame
            event_log: 事件日志列表
            current_date: 当前日期
            lookback_days: 回望天数，默认 VOL_LOOKBACK_DAYS
            
        Returns:
            [{'date': 'YYYY-MM-DD', 'volatility': float}, ...]
        """
        if prices_df is None or prices_df.empty:
            return []
        
        lookback = lookback_days or config.VOL_LOOKBACK_DAYS
        
        try:
            # 1. 重建权重变化历史
            weight_timeline = self._build_weight_timeline(event_log)
            
            if not weight_timeline:
                return []
            
            assets = asset_list if asset_list is not None else list(config.ASSET_LIST)
            use_cols = [a for a in assets if a in prices_df.columns]
            if not use_cols:
                return []
            # 2. 计算日收益率
            daily_ret_df = prices_df[use_cols].pct_change(fill_method=None).fillna(0)
            current_date_ts = pd.Timestamp(current_date)
            
            # 只取到当前日期的数据
            daily_ret_df = daily_ret_df.loc[:current_date_ts]
            
            if len(daily_ret_df) < max(config.VOL_WINDOWS):
                return []
            
            # 3. 确定趋势展示的日期范围（最近 lookback 个交易日）
            max_window = max(config.VOL_WINDOWS)  # 130
            # 需要 max_window + lookback 的数据来计算 lookback 个点
            all_dates = daily_ret_df.index
            
            if len(all_dates) <= max_window:
                return []
            
            # 从 max_window 开始，每个点都能完整计算
            computable_dates = all_dates[max_window:]
            # 只取最近 lookback 个
            trend_dates = computable_dates[-lookback:]
            
            # 4. 对每个趋势日期计算波动率
            volatility_history = []
            
            for date_ts in trend_dates:
                date_str = date_ts.strftime('%Y-%m-%d')
                
                # 找到该日期生效的权重
                effective_weights = self._get_effective_weights(weight_timeline, date_str)
                
                if not effective_weights:
                    continue
                
                # 找出有权重的资产
                assets_with_weight = [a for a in assets 
                                      if effective_weights.get(a, 0.0) > 1e-8]
                
                if not assets_with_weight:
                    continue
                
                # 获取截止到该日期的收益率
                ret_up_to_date = daily_ret_df.loc[:date_ts, assets_with_weight]
                
                if len(ret_up_to_date) < config.VOL_WINDOWS[0]:
                    continue
                
                # 构建权重 Series
                w_series = pd.Series({a: effective_weights.get(a, 0.0) for a in assets_with_weight})
                
                # 计算加权组合收益率
                weighted_returns = (ret_up_to_date * w_series).sum(axis=1)
                
                # 计算各窗口波动率，取最大值
                vol_values = []
                for window in config.VOL_WINDOWS:
                    if len(weighted_returns) >= window:
                        window_ret = weighted_returns.iloc[-window:]
                        vol = float(window_ret.std() * self.annualize_factor) * 100
                        if not np.isnan(vol):
                            vol_values.append(vol)
                
                if vol_values:
                    max_vol = max(vol_values)
                    volatility_history.append({
                        'date': date_str,
                        'volatility': round(max_vol, 2)
                    })
            
            return volatility_history
        
        except Exception as e:
            logger.warning(f"计算波动率历史失败: {e}")
            return []
    
    def _build_weight_timeline(self, event_log: List[dict]) -> List[dict]:
        """从 event_log 重建权重变化时间线
        
        提取所有调仓执行事件，按日期排序，记录每次调仓后的新权重。
        
        Returns:
            [{'date': 'YYYY-MM-DD', 'weights': {asset: weight}}, ...]
            按日期升序排列
        """
        timeline = []
        
        if not event_log:
            return timeline
        
        for event in event_log:
            event_type = event.get('type', '')
            stage = event.get('stage', '')
            new_weights = event.get('new_weights')
            
            if not new_weights:
                continue
            
            # 判断是否为调仓执行事件（排除 trigger）
            is_execute = False
            
            # 初始化事件
            if event_type == 'init':
                # init 事件可能没有 new_weights，跳过
                continue
            
            # 旧格式
            if event_type in ('monthly_rebalance', 'vol_reset_execute', 'subjective_rebalance'):
                is_execute = True
            # 新格式
            elif event_type == 'monthly':
                is_execute = True
            elif event_type == 'vol_reset' and stage == 'execute':
                is_execute = True
            elif event_type == 'subjective':
                is_execute = True
            
            if is_execute and new_weights:
                timeline.append({
                    'date': event.get('date', ''),
                    'weights': dict(new_weights)
                })
        
        # 按日期升序排列
        timeline.sort(key=lambda x: x['date'])
        
        return timeline
    
    def _get_effective_weights(self, weight_timeline: List[dict], date_str: str) -> Optional[Dict[str, float]]:
        """获取指定日期生效的权重
        
        找到 date_str 之前（含当日）最近一次调仓的权重。
        
        Args:
            weight_timeline: 权重变化时间线（升序）
            date_str: 目标日期
            
        Returns:
            {asset: weight} 或 None
        """
        effective = None
        
        for entry in weight_timeline:
            if entry['date'] <= date_str:
                effective = entry['weights']
            else:
                break  # 时间线是升序的，后面都不需要了
        
        return effective
    
    def calc_status(self, current_volatility: Optional[float],
                    threshold_pct: Optional[float] = None) -> Tuple[str, Optional[float]]:
        """计算波动率状态和距触发距离
        
        Returns:
            (status, distance_to_trigger)
        """
        status = 'normal'
        distance_to_trigger = None
        th = threshold_pct if threshold_pct is not None else self.threshold
        
        if current_volatility is not None:
            distance_to_trigger = round(th - current_volatility, 2)
            
            if current_volatility >= th:
                status = 'triggered'
            elif current_volatility >= th * 0.9:
                status = 'critical'
            elif current_volatility >= th * 0.7:
                status = 'warning'
            else:
                status = 'normal'
        
        return status, distance_to_trigger

    # ------------------------------------------------------------------
    # 工具方法：原始波动率计算（从 strategy_engine.py 迁移）
    # ------------------------------------------------------------------

    def calc_asset_volatility_raw(
        self, prices_df: pd.DataFrame, calc_date, vol_windows=None
    ) -> Dict[str, float]:
        """计算各资产波动率（原始值，非百分比）。

        取各窗口年化波动率的最大值。
        """
        windows = vol_windows or config.VOL_WINDOWS
        date_idx = prices_df.index.get_loc(calc_date)
        returns = prices_df.pct_change(fill_method=None)

        vols: Dict[str, float] = {}
        for asset in prices_df.columns:
            asset_vols = []
            for w in windows:
                if date_idx >= w:
                    ret_window = returns[asset].iloc[date_idx - w + 1:date_idx + 1]
                    vol = ret_window.std() * self.annualize_factor
                    if not np.isnan(vol):
                        asset_vols.append(vol)
            vols[asset] = max(asset_vols) if asset_vols else np.nan
        return vols

    def calc_portfolio_volatility_raw(
        self, prices_df: pd.DataFrame, weights: Dict[str, float], calc_date, vol_windows=None
    ) -> float:
        """计算组合波动率（原始值，非百分比）。

        使用权重加权的组合收益率，取各窗口年化波动率的最大值。
        """
        windows = vol_windows or config.VOL_WINDOWS
        date_idx = prices_df.index.get_loc(calc_date)
        returns = prices_df.pct_change(fill_method=None)

        valid_assets = [a for a in weights if weights[a] > 0 and a in returns.columns]
        if not valid_assets:
            return 0.0

        port_vols = []
        for w in windows:
            if date_idx >= w:
                port_returns = pd.Series(0.0, index=returns.index)
                for asset in valid_assets:
                    port_returns += weights[asset] * returns[asset].fillna(0)
                ret_window = port_returns.iloc[date_idx - w + 1:date_idx + 1]
                vol = ret_window.std() * self.annualize_factor
                if not np.isnan(vol):
                    port_vols.append(vol)

        return max(port_vols) if port_vols else 0.0
