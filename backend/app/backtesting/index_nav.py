"""指数净值计算模块 - 基于文档《净值计算.md》实现分段累加法.

核心特点：
1. 分段累加：每次调仓视为新周期起点，损益从s日重置
2. 多币种支持：每个资产按本币计价后通过汇率转人民币
3. 成本扣除：交易费用(调仓日) + 复制费用(每日计提)
4. 持仓价值跟踪：区分调仓日/非调仓日的PV计算

主要类：
- IndexNavCalculator: 指数净值计算器（主入口）
- AssetLedger: 单资产损益账本
- IndexNavConfig: 净值计算配置（汇率、费率等）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta

import pandas as pd
import numpy as np


@dataclass
class IndexNavConfig:
    """指数净值计算配置.
    
    包含汇率数据、交易费率、复制费率等参数。
    """
    
    # 初始净值
    initial_nav: float = 1000.0
    
    # 汇率数据：{asset_code: pd.Series 或 float}
    # 支持两种格式：
    # 1. 常数汇率：{"SPY": 6.5} 表示固定USD/CNY=6.5
    # 2. 时间序列：{"SPY": pd.Series([6.5, 6.52, ...], index=dates)} 表示每日汇率
    fx_rates: Dict[str, Union[float, pd.Series]] = None
    
    # 交易费率：{asset_code: rate}，默认万3
    transaction_costs: Dict[str, float] = None
    
    # 复制费率(年化)：{asset_code: annual_rate}，默认0
    replication_costs: Dict[str, float] = None
    
    def __post_init__(self):
        """初始化默认值."""
        if self.fx_rates is None:
            self.fx_rates = {}
        if self.transaction_costs is None:
            self.transaction_costs = {}
        if self.replication_costs is None:
            self.replication_costs = {}
    
    def get_fx_rate(self, asset_code: str, date: pd.Timestamp) -> float:
        """获取指定资产在指定日期的汇率.
        
        规则：若当日无数据，则沿用最近一个净值计算日的汇率。
        
        Args:
            asset_code: 资产代码
            date: 日期
            
        Returns:
            汇率值，若无汇率数据则返回1.0(默认人民币资产)
        """
        if asset_code not in self.fx_rates:
            return 1.0
        
        fx_data = self.fx_rates[asset_code]
        
        # 判断是常数汇率还是Series
        if isinstance(fx_data, (int, float)):
            # 常数汇率，直接返回
            return float(fx_data)
        
        # Series格式，按日期查询
        if date in fx_data.index:
            return float(fx_data.loc[date])
        
        # 沿用最近历史汇率
        valid_dates = fx_data.index[fx_data.index <= date]
        if len(valid_dates) > 0:
            return float(fx_data.loc[valid_dates[-1]])
        
        return 1.0
    
    def get_transaction_cost_rate(self, asset_code: str) -> float:
        """获取资产的交易费率."""
        return self.transaction_costs.get(asset_code, 0.0003)
    
    def get_replication_cost_rate(self, asset_code: str) -> float:
        """获取资产的年化复制费率."""
        return self.replication_costs.get(asset_code, 0.0)


@dataclass
class AssetLedger:
    """单个资产的损益账本.
    
    记录从周期起点s日到当前t日的累计损益、持仓价值等。
    """
    
    asset_code: str  # 资产代码
    
    # 本币计价累计损益 APL_t^c
    apl_local: float = 0.0
    
    # 人民币计价累计损益 APL_CNY_t^c
    apl_cny: float = 0.0
    
    # 本币计价持仓价值 PV_t^c
    pv_local: float = 0.0
    
    # 人民币计价持仓价值 PV_CNY_t^c
    pv_cny: float = 0.0
    
    # 上一日样本点位 TR_{t-1}^c
    tr_prev: float = 0.0
    
    def reset(self):
        """重置账本（调仓日作为新周期起点）."""
        self.apl_local = 0.0
        self.apl_cny = 0.0


class IndexNavCalculator:
    """指数净值计算器.
    
    基于文档《净值计算.md》实现分段累加法：
    Index_{s+t} = Index_s + Σ APL_CNY_{s+t}^c
    
    使用示例：
        config = IndexNavConfig(...)
        calculator = IndexNavCalculator(config)
        
        # 每日更新
        for date, bar in backtest_snapshots:
            if is_rebalance_day:
                calculator.on_rebalance(date, target_weights, current_nav)
            nav = calculator.compute_nav(date, tr_values)
    """
    
    def __init__(self, config: IndexNavConfig):
        """初始化计算器.
        
        Args:
            config: 净值计算配置
        """
        self.config = config
        
        # 当前净值
        self.current_nav = config.initial_nav
        
        # 上一次调仓日的净值 Index_s
        self.last_rebalance_nav = config.initial_nav
        
        # 资产账本：{asset_code: AssetLedger}
        self.ledgers: Dict[str, AssetLedger] = {}
        
        # 上一个净值计算日
        self.last_calc_date: Optional[pd.Timestamp] = None
    
    def on_rebalance(
        self,
        date: pd.Timestamp,
        target_weights: Dict[str, float],
        tr_values: Dict[str, float],
    ) -> float:
        """调仓日处理（指数权重调整或波动率重置）.
        
        关键步骤：
        1. 计算交易费用（文档3.4节）
        2. 扣除交易费用后重置所有资产账本
        3. 根据新权重重新分配持仓价值
        4. 记录新周期起点净值
        
        Args:
            date: 调仓日期
            target_weights: 新目标权重 {asset_code: weight}
            tr_values: 当日样本点位 {asset_code: TR_t^c}
            
        Returns:
            调仓后净值（已扣除交易费用）
        """
        # 第一步：计算所有资产的交易费用
        total_transaction_cost_cny = 0.0
        
        for asset_code, target_weight in target_weights.items():
            fx = self.config.get_fx_rate(asset_code, date)
            tc_rate = self.config.get_transaction_cost_rate(asset_code)
            
            # 计算目标持仓价值（本币）
            target_pv_cny = self.current_nav * target_weight
            target_pv_local = target_pv_cny / fx
            
            # 计算原持仓自然增长后的价值（如果有旧持仓）
            if asset_code in self.ledgers:
                ledger = self.ledgers[asset_code]
                tr_today = tr_values.get(asset_code, ledger.tr_prev)
                tr_yesterday = ledger.tr_prev
                
                if tr_yesterday > 0:
                    # 原持仓按今日价格自然增长的价值
                    natural_pv_local = ledger.pv_local * (tr_today / tr_yesterday)
                else:
                    natural_pv_local = 0.0
            else:
                # 新增资产，原持仓为0
                natural_pv_local = 0.0
            
            # 交易费用（文档3.4节）
            # TC_t^c = |PV_t^c - PV_{t-1}^c × TR_t^c/TR_{t-1}^c| × tc^c
            trade_amount_local = abs(target_pv_local - natural_pv_local)
            transaction_cost_local = trade_amount_local * tc_rate
            transaction_cost_cny = transaction_cost_local * fx
            
            total_transaction_cost_cny += transaction_cost_cny
        
        # 第二步：扣除交易费用，更新净值
        self.current_nav -= total_transaction_cost_cny
        
        # 第三步：记录调仓后净值作为新周期基准
        self.last_rebalance_nav = self.current_nav
        
        # 第四步：重置并初始化账本
        for asset_code, weight in target_weights.items():
            if asset_code not in self.ledgers:
                self.ledgers[asset_code] = AssetLedger(asset_code=asset_code)
            
            ledger = self.ledgers[asset_code]
            ledger.reset()
            
            # 获取汇率
            fx = self.config.get_fx_rate(asset_code, date)
            
            # 调仓日持仓价值（文档3.3节）
            # PV_t^c = Index_{t-1} × TW_t^c / FX_t^c
            # 注意：这里使用扣除交易费后的净值
            ledger.pv_cny = self.current_nav * weight
            ledger.pv_local = ledger.pv_cny / fx
            
            # 记录当日样本点位
            ledger.tr_prev = tr_values.get(asset_code, 0.0)
        
        # 第五步：移除不在新权重中的资产
        assets_to_remove = [code for code in self.ledgers if code not in target_weights]
        for code in assets_to_remove:
            del self.ledgers[code]
        
        self.last_calc_date = date
        
        return self.current_nav
    
    def compute_nav(
        self,
        date: pd.Timestamp,
        tr_values: Dict[str, float],
    ) -> float:
        """计算当日指数净值（非调仓日）.
        
        流程（文档3.1-3.2节）：
        1. 对每个资产计算当日损益
        2. 更新累计损益（扣除交易费、复制费）
        3. 转换为人民币
        4. 汇总：Index_t = Index_s + Σ APL_CNY_t^c
        
        Args:
            date: 当前日期
            tr_values: 当日样本点位 {asset_code: TR_t^c}
            
        Returns:
            当日指数净值
        """
        if not self.ledgers:
            # 无持仓，净值不变
            return self.current_nav
        
        total_apl_cny = 0.0
        
        for asset_code, ledger in self.ledgers.items():
            tr_today = tr_values.get(asset_code, ledger.tr_prev)
            tr_yesterday = ledger.tr_prev
            
            if tr_yesterday == 0:
                continue
            
            # 计算当日收益率
            price_ratio = tr_today / tr_yesterday
            daily_return = price_ratio - 1.0
            
            # 当日损益（本币）
            daily_pnl_local = ledger.pv_local * daily_return
            
            # 复制费用（每日计提，文档3.5节）
            rc_rate = self.config.get_replication_cost_rate(asset_code)
            days_elapsed = self._calc_days_elapsed(self.last_calc_date, date)
            replication_cost_local = ledger.pv_local * (rc_rate / 365.0) * days_elapsed
            
            # 更新本币累计损益
            ledger.apl_local += daily_pnl_local - replication_cost_local
            
            # 获取汇率并转换为人民币
            fx = self.config.get_fx_rate(asset_code, date)
            ledger.apl_cny = ledger.apl_local * fx
            
            # 更新持仓价值（非调仓日，文档3.3节）
            ledger.pv_local = ledger.pv_local * price_ratio
            ledger.pv_cny = ledger.pv_local * fx
            
            # 更新样本点位
            ledger.tr_prev = tr_today
            
            # 累加人民币损益
            total_apl_cny += ledger.apl_cny
        
        # 计算指数净值（文档3.1节）
        self.current_nav = self.last_rebalance_nav + total_apl_cny
        self.last_calc_date = date
        
        return self.current_nav
    
    def _calc_days_elapsed(
        self,
        date_from: Optional[pd.Timestamp],
        date_to: pd.Timestamp
    ) -> int:
        """计算两个净值计算日之间的自然日天数.
        
        文档3.5节：Days(t-1, t) 为从前一净值计算日(不含)到当前日(含)的自然日天数。
        """
        if date_from is None:
            return 1
        delta = (date_to - date_from).days
        return max(delta, 1)
    
    def get_current_weights(self) -> Dict[str, float]:
        """获取当前实际权重（用于监控）.
        
        Returns:
            {asset_code: actual_weight}
        """
        total_value = sum(ledger.pv_cny for ledger in self.ledgers.values())
        if total_value == 0:
            return {}
        
        return {
            code: ledger.pv_cny / total_value
            for code, ledger in self.ledgers.items()
        }

    def get_target_weights(self) -> Dict[str, float]:
        """获取目标权重（未归一化，pv_cny / current_nav）.
        
        用于调仓日快照展示，与 on_rebalance 传入的 target_weights 一致，
        支持杠杆>1 时权重和超过 100%。
        
        Returns:
            {asset_code: target_weight}
        """
        if self.current_nav <= 0:
            return {}
        return {
            code: ledger.pv_cny / self.current_nav
            for code, ledger in self.ledgers.items()
        }
