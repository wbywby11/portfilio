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
    
    def calc_performance(self, state: PortfolioState) -> PerformanceMetrics:
        """
        从 nav_history 计算绩效指标

        年化采用与回测一致的口径：基于实际交易日数 / 252 的 CAGR 公式，
        并以 nav_history 首条记录的净值与日期为起点（而非配置中的指数起始日 BASE_DATE）。

        Returns:
            PerformanceMetrics: 绩效指标（百分点形式）
        """
        nav_history = state.nav_history

        # 优先使用 nav_history 的首条记录作为组合实际起点；
        # 若 nav_history 为空，则回退到 BASE_VALUE / BASE_DATE。
        if nav_history:
            first_nav = float(nav_history[0].get('nav', config.BASE_VALUE)) or config.BASE_VALUE
            first_date_str = nav_history[0].get('date') or config.BASE_DATE
        else:
            first_nav = config.BASE_VALUE
            first_date_str = config.BASE_DATE

        # 累计收益（百分点）：last_nav / first_nav - 1
        cum_ret_decimal = (state.nav / first_nav - 1.0) if first_nav > 1e-12 else 0.0
        cumulative_return = cum_ret_decimal * 100

        # 年化收益：与回测一致，使用交易日数 / 252 的 CAGR 公式。
        # 交易日数 = 日收益率序列长度（即 nav_history 长度 - 1，去除首日）。
        periods_per_year = 252
        n_trading_days = max(len(nav_history) - 1, 0)

        if n_trading_days > 0 and cum_ret_decimal > -1.0:
            annual_return = ((1.0 + cum_ret_decimal) ** (periods_per_year / n_trading_days) - 1.0) * 100
        else:
            # 兜底：若无有效交易日序列，使用日历天数 / 365 估算
            try:
                first_date = pd.Timestamp(first_date_str)
                last_date = pd.Timestamp(state.date)
                calendar_days = (last_date - first_date).days
                years = calendar_days / 365.0
            except Exception:
                years = 0.0
            if years > 0 and cum_ret_decimal > -1.0:
                annual_return = ((1 + cum_ret_decimal) ** (1.0 / years) - 1) * 100
            else:
                annual_return = 0.0

        if len(nav_history) >= 2:
            # 计算日收益率
            nav_series = pd.Series([h['nav'] for h in nav_history])
            returns = nav_series.pct_change().dropna()

            # 年化波动率：使用 √252 年化（与回测口径保持一致）
            if len(returns) > 0:
                daily_vol = returns.std()
                annual_vol = daily_vol * np.sqrt(periods_per_year) * 100
            else:
                annual_vol = 0.0

            # 最大回撤
            max_drawdown = self._calc_max_drawdown(nav_history)
        else:
            annual_vol = 0.0
            max_drawdown = 0.0
        
        # 夏普比率
        risk_free = config.RISK_FREE_RATE * 100  # 转为百分比
        if annual_vol > 0:
            sharpe_ratio = (annual_return - risk_free) / annual_vol
        else:
            sharpe_ratio = 0.0
        
        return PerformanceMetrics(
            cumulative_return=cumulative_return,
            annual_return=annual_return,
            annual_vol=annual_vol,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
        )
    
    def _calc_max_drawdown(self, nav_history: List[Dict]) -> float:
        """
        计算最大回撤
        
        max_dd = min((nav - peak) / peak) * 100
        
        Args:
            nav_history: 净值历史列表 [{'date': date, 'nav': nav}, ...]
            
        Returns:
            最大回撤（负数百分比）
        """
        if len(nav_history) < 2:
            return 0.0
        
        navs = [h['nav'] for h in nav_history]
        
        peak = navs[0]
        max_dd = 0.0
        
        for nav in navs:
            if nav > peak:
                peak = nav
            dd = (nav - peak) / peak
            if dd < max_dd:
                max_dd = dd
        
        return max_dd * 100
    
    def calc_performance_dict(self, state: PortfolioState) -> Dict:
        """
        计算绩效指标并返回字典格式（兼容旧接口）
        
        Returns:
            包含 cumulative_return, annual_return, annual_vol, max_drawdown, sharpe_ratio 的字典
        """
        perf = self.calc_performance(state)
        return {
            'cumulative_return': perf.cumulative_return,
            'annual_return': perf.annual_return,
            'annual_vol': perf.annual_vol,
            'max_drawdown': perf.max_drawdown,
            'sharpe_ratio': perf.sharpe_ratio,
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
