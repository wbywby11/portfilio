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
from typing import Dict, List, Optional, Sequence, Tuple
from loguru import logger

from app.monitor import config


def _resolve_windows(vol_windows: Optional[Sequence[int]]) -> List[int]:
    """解析波动率窗口：调用方传值优先，非法/空回退全局配置（升序去重）.

    调用方应传 signal_detector 判定时使用的同一组窗口（策略参数
    ``vol_windows``）；缺省才回退 ``config.VOL_WINDOWS``。
    """
    try:
        windows = sorted({int(w) for w in (vol_windows or []) if int(w) > 1})
    except (TypeError, ValueError):
        windows = []
    return windows or list(config.VOL_WINDOWS)


class VolatilityCalculator:
    """波动率计算器"""
    
    def __init__(self):
        self.annualize_factor = np.sqrt(config.ANNUALIZE_FACTOR)  # √260
        self.threshold = config.VOL_TRIGGER_THRESHOLD * 100  # 百分比形式

    @staticmethod
    def _common_price_as_of(
        prices_df: pd.DataFrame,
        assets: Sequence[str],
        until: pd.Timestamp,
    ) -> Optional[pd.Timestamp]:
        """所有给定资产都有有效行情的最后一个交易日（≤ until）。

        停更资产若继续参与统计，``pct_change`` 会把它当成零收益，窗口内只剩
        仍在更新的资产在动，波动率被系统性低估。任一资产在 ``until`` 之前
        完全没有行情时返回 None——组合无法代表真实持仓，不产出数值。
        """
        last_dates = []
        for asset in assets:
            if asset not in prices_df.columns:
                return None
            series = prices_df[asset].loc[:until].dropna()
            if series.empty:
                return None
            last_dates.append(series.index[-1])
        return min(last_dates) if last_dates else None
    
    def calc_current_volatility(self, prices_df: pd.DataFrame,
                                 positions_local: Dict[str, float],
                                 last_rebalance_fx: Dict[str, float],
                                 nav: float,
                                 current_date: str,
                                 asset_list: Optional[List[str]] = None,
                                 w_cny: Optional[Dict[str, float]] = None,
                                 vol_windows: Optional[Sequence[int]] = None,
                                 annualize_factor: Optional[float] = None) -> Tuple[Optional[float], Dict[str, float], Optional[str]]:
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
            vol_windows: 波动率窗口（交易日）。调用方应传 signal_detector 判定
                   时使用的同一组窗口（策略参数 ``vol_windows``），缺省回退
                   ``config.VOL_WINDOWS``。展示与触发必须同源，否则信号页
                   显示的波动率会和实际判定用的窗口不同。
            annualize_factor: 年化因子，缺省用 ``sqrt(config.ANNUALIZE_FACTOR)``。
                   与 vol_windows 同源传入（signal_detector._vol_params 的返回值）。
        
        Returns:
            (current_volatility, vol_window_values, price_as_of)
            current_volatility: 百分比形式的最大窗口波动率，如 5.50
            vol_window_values: {'22天': x, '65天': x, '130天': x}（键随窗口参数变化）
            price_as_of: 本次计算实际用到的最后行情日（YYYY-MM-DD）；
                   持仓资产行情不完整时为 None（此时不产出数值）
        """
        vol_window_values = {}
        current_volatility = None
        windows = _resolve_windows(vol_windows)
        annualize = (
            float(annualize_factor)
            if annualize_factor is not None and float(annualize_factor) > 0
            else self.annualize_factor
        )
        
        if prices_df is None or prices_df.empty or nav <= 0:
            return current_volatility, vol_window_values, None
        
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
                return current_volatility, vol_window_values, None
            
            use_cols = [a for a in assets if a in prices_df.columns]
            if not use_cols:
                return current_volatility, vol_window_values, None

            # 窗口截止日 = 所有持仓资产都有行情的最后一天。
            # 停更资产若按 pct_change().fillna(0) 参与统计，会被当成「日收益恒为 0」，
            # 窗口越短、仍在更新的资产权重越小，波动率被压得越低（22 天窗口尤其明显）。
            current_date_ts = pd.Timestamp(current_date)
            as_of = self._common_price_as_of(prices_df, assets_with_position, current_date_ts)
            if as_of is None:
                logger.warning(
                    "当前波动率跳过：持仓资产行情不完整，无法定位共同截止日: %s",
                    ",".join(assets_with_position),
                )
                return current_volatility, vol_window_values, None

            # 先按交易日历前向填充再算收益：跨市场休市日收益为 0 是正确的，
            # 但填充到共同截止日就停，不会把「停更」伪装成「零收益」。
            window_prices = prices_df[use_cols].loc[:as_of].ffill()
            daily_ret_df = window_prices.pct_change(fill_method=None).fillna(0)
            ytd_ret = daily_ret_df[assets_with_position]
            
            if len(ytd_ret) < min(windows):
                return current_volatility, vol_window_values, as_of.strftime('%Y-%m-%d')
            
            w_series = pd.Series({a: w_cny.get(a, 0.0) for a in assets_with_position})
            weighted_returns = (ytd_ret * w_series).sum(axis=1)
            
            vol_values = []
            for window in windows:
                if len(weighted_returns) >= window:
                    ret_window = weighted_returns.iloc[-window:]
                    vol = float(ret_window.std() * annualize) * 100
                    vol_window_values[f'{window}天'] = round(vol, 2)
                    if not np.isnan(vol):
                        vol_values.append(vol)
            
            if vol_values:
                current_volatility = round(max(vol_values), 2)
        
        except Exception as e:
            logger.warning(f"计算当前波动率失败: {e}")
            return current_volatility, vol_window_values, None
        
        return current_volatility, vol_window_values, as_of.strftime('%Y-%m-%d')
    
    def calc_volatility_history(self, prices_df: pd.DataFrame,
                                 event_log: List[dict],
                                 current_date: str,
                                 lookback_days: int = None,
                                 asset_list: Optional[List[str]] = None,
                                 vol_windows: Optional[Sequence[int]] = None,
                                 annualize_factor: Optional[float] = None,
                                 as_of: Optional[str] = None,
                                 current_weights: Optional[Dict[str, float]] = None) -> List[dict]:
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
            asset_list: 资产列表
            vol_windows: 波动率窗口，应与当前值/触发判定同源；缺省回退
                   ``config.VOL_WINDOWS``（趋势图与顶部数值必须同窗口）
            annualize_factor: 年化因子，与当前值同源传入；缺省用
                   ``sqrt(config.ANNUALIZE_FACTOR)``
            as_of: 与当前值同源的行情截止日（YYYY-MM-DD）。传入时趋势终点
                   与当前值对齐；缺省由全部资产共同行情日推导
            current_weights: 当前持仓权重。趋势最后一个点用它计算，
                   保证图表最右点与卡片「当前组合波动率」完全一致
            
        Returns:
            [{'date': 'YYYY-MM-DD', 'volatility': float}, ...]
        """
        if prices_df is None or prices_df.empty:
            return []
        
        lookback = lookback_days or config.VOL_LOOKBACK_DAYS
        windows = _resolve_windows(vol_windows)
        annualize = (
            float(annualize_factor)
            if annualize_factor is not None and float(annualize_factor) > 0
            else self.annualize_factor
        )
        
        try:
            # 1. 重建权重变化历史
            weight_timeline = self._build_weight_timeline(event_log)
            
            if not weight_timeline:
                return []
            
            assets = asset_list if asset_list is not None else list(config.ASSET_LIST)
            use_cols = [a for a in assets if a in prices_df.columns]
            if not use_cols:
                return []

            # 2. 计算日收益率：与当前值同口径——截止到「所有持仓资产都有行情的
            #    最后一天」，先前向填充再算收益（跨市场休市日收益为 0）。
            #    停更资产不会被填充到未来，避免「缺价」被当成「零收益」。
            current_date_ts = pd.Timestamp(current_date)
            as_of_ts = (
                pd.Timestamp(as_of)
                if as_of
                else self._common_price_as_of(prices_df, use_cols, current_date_ts)
            )
            if as_of_ts is None:
                return []
            daily_ret_df = (
                prices_df[use_cols]
                .loc[:min(as_of_ts, current_date_ts)]
                .ffill()
                .pct_change(fill_method=None)
                .fillna(0)
            )
            
            if len(daily_ret_df) < max(windows):
                return []
            
            # 3. 确定趋势展示的日期范围（最近 lookback 个交易日）
            max_window = max(windows)
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
            last_date_str = trend_dates[-1].strftime('%Y-%m-%d') if len(trend_dates) else ''
            
            for date_ts in trend_dates:
                date_str = date_ts.strftime('%Y-%m-%d')
                
                # 找到该日期生效的权重；最后一个点代表「当前组合在最新完整
                # 行情上的波动率」，直接用当前持仓权重（event_log 的生效权重
                # 可能停在最后一次调仓前，与卡片主指标不同源会差一个调仓）
                if date_str == last_date_str and current_weights:
                    effective_weights = {
                        k: float(v) for k, v in current_weights.items()
                        if float(v or 0.0) > 1e-8
                    }
                else:
                    effective_weights = self._get_effective_weights(weight_timeline, date_str)
                
                if not effective_weights:
                    continue
                
                # 找出有权重的资产
                assets_with_weight = [a for a in assets 
                                      if effective_weights.get(a, 0.0) > 1e-8]
                
                if not assets_with_weight:
                    continue
                
                # 获取截止到该日期的收益率；窗口截止到「该日权重下所有资产
                # 都有行情」的最后一天，避免个别资产停更后被前向填充成零收益。
                day_as_of = self._common_price_as_of(prices_df, assets_with_weight, date_ts)
                if day_as_of is None:
                    continue
                ret_up_to_date = daily_ret_df.loc[:day_as_of, assets_with_weight]
                
                if len(ret_up_to_date) < min(windows):
                    continue
                
                # 构建权重 Series
                w_series = pd.Series({a: effective_weights.get(a, 0.0) for a in assets_with_weight})
                
                # 计算加权组合收益率
                weighted_returns = (ret_up_to_date * w_series).sum(axis=1)
                
                # 计算各窗口波动率，取最大值
                vol_values = []
                for window in windows:
                    if len(weighted_returns) >= window:
                        window_ret = weighted_returns.iloc[-window:]
                        vol = float(window_ret.std() * annualize) * 100
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
