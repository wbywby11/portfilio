# -*- coding: utf-8 -*-
"""
大类资产配置监测系统 - 报告生成器

本模块实现报告数据生成功能（简化版，不含文件输出）：
- ReportGenerator 类：生成报告数据结构
- 绩效指标计算方法

注意：此模块仅负责数据生成，文件输出由 API 层处理
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from app.monitor import config
from app.monitor.monitor_runtime import (
    resolve_asset_class_for_monitor,
    resolve_asset_currency_for_monitor,
    resolve_monitor_asset_display_label,
)
from app.monitor.types import (
    PortfolioState, DailyResult, ReportData, PerformanceMetrics,
    RebalanceSignal, VolResetSignal, DeviationInfo, TradeOrder
)


class ReportGenerator:
    """报告生成器 - 生成报告数据结构"""
    
    def __init__(self):
        """初始化报告生成器"""
        pass
    
    def generate_report_data(self, 
                             date: str,
                             state: PortfolioState,
                             daily_result: DailyResult,
                             deviations: List[DeviationInfo],
                             rebalance_signal: Optional[RebalanceSignal] = None,
                             vol_reset_signal: Optional[VolResetSignal] = None,
                             trade_orders: Optional[List[TradeOrder]] = None,
                             next_rebalance_date: str = '',
                             realized_vol: Optional[float] = None) -> ReportData:
        """
        生成报告数据结构
        
        Args:
            date: 日期
            state: 当前状态
            daily_result: 当日结果
            deviations: 权重偏离度列表
            rebalance_signal: 月度调仓信号（可选）
            vol_reset_signal: 波动率重置信号（可选）
            trade_orders: 交易指令列表（可选）
            next_rebalance_date: 下次调仓日
            realized_vol: 当前已实现波动率（可选）
            
        Returns:
            ReportData: 报告数据
        """
        return ReportData(
            date=date,
            state=state,
            daily_result=daily_result,
            deviations=deviations,
            rebalance_signal=rebalance_signal,
            vol_reset_signal=vol_reset_signal,
            trade_orders=trade_orders or [],
            next_rebalance_date=next_rebalance_date,
            realized_vol=realized_vol,
        )
    
    def calc_performance(self, state: PortfolioState,
                         rebalance_dates: Optional[List] = None) -> PerformanceMetrics:
        """
        从 nav_history 计算绩效指标

        指标公式全部委托统一内核 `app.analysis.performance`（年化因子 260、CAGR、
        回撤基于净值本身、夏普为几何口径），确保监控与回测口径完全一致。
        起点取 nav_history 首条记录（而非配置中的指数起始日 BASE_DATE）。

        Args:
            state: 组合状态
            rebalance_dates: 调仓执行日列表，作为胜率的周期边界。
                None = 调用方未取到操作记录，回退到 state.event_log 推导；
                显式空列表 = 确认无调仓记录，胜率按 0 返回。

        Returns:
            PerformanceMetrics: 绩效指标（百分点形式）
        """
        from app.analysis.performance import compute_performance

        nav_history = state.nav_history or []
        nav_series = self._build_nav_series(state, nav_history)

        if len(nav_series) >= 2:
            marks = (
                rebalance_dates
                if rebalance_dates is not None
                else self._rebalance_dates_from_event_log(state)
            )
            metrics = compute_performance(
                nav_series,
                risk_free_rate=config.RISK_FREE_RATE,
                rebalance_dates=marks,
            )
            return PerformanceMetrics(
                cumulative_return=metrics.total_return * 100,
                annual_return=metrics.annual_return * 100,
                annual_vol=metrics.annual_volatility * 100,
                max_drawdown=metrics.max_drawdown * 100,
                sharpe_ratio=metrics.sharpe_ratio,
                win_rate=metrics.win_rate,
                annual_return_365=metrics.annual_return_365 * 100,
                annual_vol_365=metrics.annual_volatility_365 * 100,
                sharpe_365=metrics.sharpe_ratio_365,
                trading_days=len(nav_series),
            )

        # 净值序列不足 2 点：无法年化波动/回撤，仅给出累计收益与日历年化估算
        first_nav = float(nav_history[0].get("nav", config.BASE_VALUE)) if nav_history else config.BASE_VALUE
        first_nav = first_nav or config.BASE_VALUE
        first_date_str = (nav_history[0].get("date") if nav_history else None) or config.BASE_DATE
        cum_ret_decimal = (state.nav / first_nav - 1.0) if first_nav > 1e-12 else 0.0

        annual_return = 0.0
        try:
            calendar_days = (pd.Timestamp(state.date) - pd.Timestamp(first_date_str)).days
            years = calendar_days / 365.0
        except (TypeError, ValueError):
            years = 0.0
        if years > 0 and cum_ret_decimal > -1.0:
            annual_return = ((1 + cum_ret_decimal) ** (1.0 / years) - 1) * 100

        return PerformanceMetrics(
            cumulative_return=cum_ret_decimal * 100,
            annual_return=annual_return,
            annual_vol=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            # 不足 2 个净值点时无日收益序列，两个口径同取日历年化估算值
            annual_return_365=annual_return,
            trading_days=len(nav_history),
        )

    @staticmethod
    def _rebalance_dates_from_event_log(state: PortfolioState) -> List[str]:
        """从事件日志提取调仓执行日（与绩效页缓存共用同一判定）。"""
        from app.monitor.rebalance_marks import rebalance_dates_from_event_log

        return rebalance_dates_from_event_log(state.event_log)

    @staticmethod
    def _build_nav_series(state: PortfolioState, nav_history: List[Dict]) -> pd.Series:
        """nav_history → 净值序列（DatetimeIndex），末尾补上当前状态净值。"""
        records = []
        for h in nav_history:
            try:
                d = pd.Timestamp(h.get("date"))
                v = float(h.get("nav"))
            except (TypeError, ValueError):
                continue
            if pd.notna(d):
                records.append((d, v))
        if not records:
            return pd.Series(dtype=float)

        try:
            state_date = pd.Timestamp(state.date)
        except (TypeError, ValueError):
            state_date = None
        if state_date is not None and state_date > records[-1][0]:
            records.append((state_date, float(state.nav)))

        idx = pd.DatetimeIndex([r[0] for r in records])
        return pd.Series([r[1] for r in records], index=idx).sort_index()
    
    def calc_performance_dict(self, state: PortfolioState,
                              rebalance_dates: Optional[List] = None) -> Dict:
        """
        计算绩效指标并返回字典格式（兼容旧接口）
        
        Returns:
            包含 cumulative_return, annual_return, annual_vol, max_drawdown,
            sharpe_ratio, win_rate 的字典
        """
        perf = self.calc_performance(state, rebalance_dates=rebalance_dates)
        return {
            'cumulative_return': perf.cumulative_return,
            'annual_return': perf.annual_return,
            'annual_vol': perf.annual_vol,
            'max_drawdown': perf.max_drawdown,
            'sharpe_ratio': perf.sharpe_ratio,
            'win_rate': perf.win_rate,
            'annual_return_365': perf.annual_return_365,
            'annual_vol_365': perf.annual_vol_365,
            'sharpe_365': perf.sharpe_365,
        }
    
    def calc_performance_api_dict(self, state: PortfolioState,
                                  rebalance_dates: Optional[List] = None) -> Dict:
        """
        绩效指标 API 字典（含 calmar_ratio），监控绩效查询与暂停快照共用。
        
        Returns:
            包含 cumulative_return, annual_return, annual_volatility,
            max_drawdown, sharpe_ratio, calmar_ratio, win_rate, trading_days
            的字典（收益率/波动/回撤为百分点形式）
        """
        perf = self.calc_performance(state, rebalance_dates=rebalance_dates)
        calmar = (
            perf.annual_return / abs(perf.max_drawdown)
            if perf.max_drawdown != 0
            else 0.0
        )
        calmar_365 = (
            perf.annual_return_365 / abs(perf.max_drawdown)
            if perf.max_drawdown != 0
            else 0.0
        )
        return {
            'cumulative_return': perf.cumulative_return,
            'annual_return': perf.annual_return,
            'annual_volatility': perf.annual_vol,
            'max_drawdown': perf.max_drawdown,
            'sharpe_ratio': perf.sharpe_ratio,
            'calmar_ratio': calmar,
            'win_rate': perf.win_rate,
            'trading_days': perf.trading_days,
            'annual_return_365': perf.annual_return_365,
            'annual_volatility_365': perf.annual_vol_365,
            'sharpe_ratio_365': perf.sharpe_365,
            'calmar_ratio_365': calmar_365,
        }
    
    def calc_daily_attribution(self,
                               target_date: str,
                               prev_nav: float,
                               current_nav: float,
                               weights: Dict,
                               positions_cny: Dict,
                               nav_live: float,
                               asset_list: List[str],
                               daily_changes: Dict,
                               names_lookup: Dict) -> Dict:
        """
        资产损益归因分解（从监控服务层下沉的领域计算）
        
        每个资产贡献 = 该资产持仓权重 × 该资产当日涨跌% / 100 × 前一日组合净值
        
        Args:
            target_date: 目标日期 YYYY-MM-DD
            prev_nav: 前一日净值
            current_nav: 当日净值
            weights: 目标权重字典（小数形式）
            positions_cny: 人民币持仓市值字典（目标权重缺失时回退用）
            nav_live: 当前实时净值（回退权重计算的分母）
            asset_list: 参与归因的资产键列表
            daily_changes: {资产键: 当日涨跌幅%}
            names_lookup: 资产展示名查找表
            
        Returns:
            {date, attributions, total_pnl, prev_nav, current_nav}
        """
        total_pnl = current_nav - prev_nav
        
        attributions = []
        
        for asset_name in asset_list:
            try:
                weight = float(weights.get(asset_name, 0) or 0)
            except (TypeError, ValueError):
                weight = 0.0
            if abs(weight) < 1e-15 and nav_live > 0:
                weight = float(positions_cny.get(asset_name, 0) or 0) / nav_live
            
            daily_change = daily_changes.get(asset_name)
            if daily_change is None:
                daily_change = 0.0
            
            contribution = weight * daily_change / 100 * prev_nav
            
            ac = resolve_asset_class_for_monitor(asset_name)
            asset_class = ac if ac else '其他'
            currency = resolve_asset_currency_for_monitor(asset_name)
            display_name = resolve_monitor_asset_display_label(asset_name, names_lookup)
            
            attributions.append({
                "name": display_name,
                "code": asset_name,
                "asset_class": asset_class,
                "weight": round(weight * 100, 4),
                "daily_change": round(daily_change, 4),
                "contribution": round(contribution, 2),
                "currency": currency
            })
        
        # 按贡献绝对值降序排列
        attributions.sort(key=lambda x: abs(x['contribution']), reverse=True)
        
        return {
            "date": target_date,
            "attributions": attributions,
            "total_pnl": round(total_pnl, 2),
            "prev_nav": round(prev_nav, 2),
            "current_nav": round(current_nav, 2)
        }
    
    # =========================================================================
    # 数据格式化方法（供 API 层使用）
    # =========================================================================
    
    def format_report_summary(self, data: ReportData) -> Dict:
        """
        格式化报告摘要（用于 API 响应）
        
        Args:
            data: 报告数据
            
        Returns:
            格式化后的摘要字典
        """
        state = data.state
        result = data.daily_result
        perf = self.calc_performance(state)
        
        # 格式化涨跌幅
        nav_change = result.nav_change_pct
        nav_change_str = f"+{nav_change:.2f}%" if nav_change >= 0 else f"{nav_change:.2f}%"
        
        return {
            'date': data.date,
            'nav': round(state.nav, 2),
            'nav_change': nav_change_str,
            'nav_change_pct': round(nav_change, 4),
            'total_leverage': round(result.total_leverage, 4),
            'day_count': state.day_count,
            'performance': {
                'cumulative_return': round(perf.cumulative_return, 2),
                'annual_return': round(perf.annual_return, 2),
                'annual_vol': round(perf.annual_vol, 2),
                'max_drawdown': round(perf.max_drawdown, 2),
                'sharpe_ratio': round(perf.sharpe_ratio, 2),
                'annual_return_365': round(perf.annual_return_365, 2),
                'annual_vol_365': round(perf.annual_vol_365, 2),
                'sharpe_365': round(perf.sharpe_365, 2),
            },
            'costs': {
                'trading': round(state.total_trading_cost, 2),
                'replication': round(state.total_replication_cost, 2),
                'total': round(state.total_trading_cost + state.total_replication_cost, 2),
            },
            'vol_reset_count': state.vol_reset_count,
            'next_rebalance_date': data.next_rebalance_date,
            'realized_vol': round(data.realized_vol * 100, 2) if data.realized_vol else None,
        }
    
    def format_positions(self, data: ReportData) -> List[Dict]:
        """
        格式化持仓明细（用于 API 响应）
        
        Args:
            data: 报告数据
            
        Returns:
            持仓明细列表
        """
        positions = []
        
        for dev in data.deviations:
            asset = dev.asset
            
            # 当日收益（人民币口径）
            local_ret = data.daily_result.asset_returns_local.get(asset, 0.0)
            cny_ret = data.daily_result.asset_returns_cny.get(asset, 0.0)
            
            positions.append({
                'asset': asset,
                'target_weight': round(dev.target_weight * 100, 2),
                'actual_weight': round(dev.actual_weight * 100, 2),
                'deviation': round(dev.deviation * 100, 2),
                'deviation_pct': round(dev.deviation_pct, 2),
                'return_local': round(local_ret * 100, 4),
                'return_cny': round(cny_ret * 100, 4),
            })
        
        return positions
    
    def format_signals(self, data: ReportData) -> Dict:
        """
        格式化信号状态（用于 API 响应）
        
        Args:
            data: 报告数据
            
        Returns:
            信号状态字典
        """
        signals = {
            'monthly_rebalance': None,
            'vol_reset': None,
            'pending': None,
        }
        
        # 月度调仓
        if data.rebalance_signal:
            signals['monthly_rebalance'] = {
                'status': 'triggered',
                'signal_date': data.rebalance_signal.signal_date,
                'execute_date': data.rebalance_signal.execute_date,
            }
        
        # 波动率重置
        if data.vol_reset_signal:
            signals['vol_reset'] = {
                'status': 'triggered',
                'vol_trigger': round(data.vol_reset_signal.vol_trigger * 100, 2),
                'threshold': config.VOL_TRIGGER_THRESHOLD * 100,
                'scale_factor': round(data.vol_reset_signal.scale_factor, 4),
                'execute_date': data.vol_reset_signal.execute_date,
            }
        elif data.realized_vol is not None:
            signals['vol_reset'] = {
                'status': 'normal',
                'realized_vol': round(data.realized_vol * 100, 2),
                'threshold': config.VOL_TRIGGER_THRESHOLD * 100,
            }
        
        # 待执行调仓
        if data.state.pending_rebalance:
            signals['pending'] = {
                'rebalance_type': data.state.pending_rebalance.get('rebalance_type', 'unknown'),
                'execute_date': data.state.pending_rebalance.get('execute_date', ''),
            }
        
        return signals
    
    def format_trade_orders(self, data: ReportData) -> List[Dict]:
        """
        格式化交易指令（用于 API 响应）
        
        Args:
            data: 报告数据
            
        Returns:
            交易指令列表
        """
        orders = []
        
        for order in data.trade_orders:
            orders.append({
                'asset': order.asset,
                'direction': order.direction,
                'target_weight': round(order.target_weight * 100, 2),
                'current_weight': round(order.current_weight * 100, 2),
                'weight_change': round(order.weight_change * 100, 2),
                'estimated_amount': round(order.estimated_amount_cny, 2),
            })
        
        return orders
    
    def to_api_response(self, data: ReportData) -> Dict:
        """
        将报告数据转换为完整的 API 响应格式
        
        Args:
            data: 报告数据
            
        Returns:
            完整的 API 响应字典
        """
        return {
            'summary': self.format_report_summary(data),
            'positions': self.format_positions(data),
            'signals': self.format_signals(data),
            'trade_orders': self.format_trade_orders(data),
        }
