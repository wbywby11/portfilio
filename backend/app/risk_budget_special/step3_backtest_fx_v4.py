# -*- coding: utf-8 -*-
"""
大类资产配置指数策略 - 第三步：净值计算与回测（V5版本 - 时间线重构）

V5版本特点：
- 按时间线视角重构，逻辑清晰可读
- 模块化设计：每个操作独立为 handle_xxx() 函数
- 集中状态管理：BacktestState 数据类
- 统一调仓队列：PendingRebalance 数据类

时间线概览：
  2014-01-31 [权重计算日] → step2输出首个权重
         ↓ T+2
  2014-02-10 [指数起始日] → 净值=1000，按初始权重配置持仓
         ↓
  2014-02-11 [净值计算日] → 计算收益，更新净值
         ↓
    ...每日循环...
         ↓
  某月末 [权重计算日] → step2输出新权重
         ↓ T+2
  某日 [调仓执行日] → 按新权重重置持仓
         ↓
  某日 [波动率触发] → 计算VW权重，T+2后执行

主循环步骤：
  A. 指数起始日处理
  B. 每日损益更新
  C. 调仓执行（优先级最高）
  D. 月度调仓检查
  E. 波动率监测
  F. 记录当日状态
"""

import pandas as pd
import numpy as np
import os
import matplotlib.pyplot as plt
from dataclasses import dataclass, field
from typing import Dict, Optional, List

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


# =============================================================================
# 第一部分：配置参数
# =============================================================================

BASE_DATE = pd.Timestamp('2014-02-10')  # 指数起始日
BASE_VALUE = 1000.0  # 基点
RISK_FREE_RATE = 0.02  # 无风险利率

# 波动率监控参数
VOL_TRIGGER_THRESHOLD = 0.06  # 触发阈值 6%
VOL_TARGET = 0.05  # 目标波动率 5%
VOL_WINDOWS = [22, 65, 130]  # 波动率计算窗口
MONITOR_START_DAYS = 60  # 波动率监控起始日（前60个净值日不监控）

# 编制规则：排除日
SKIP_EXCLUDED_DATES = {
    pd.Timestamp("2015-01-01"),
    pd.Timestamp("2015-01-02"),
    pd.Timestamp("2015-01-05"),
}

# 费率配置
TRADING_COST = {
    '沪深300': 0.0003, '创业板指': 0.0003, '红利低波': 0.0003, '恒生科技': 0.0005,
    '标普500': 0.0002, '德国DAX': 0.0002, '中国10年国债': 0.0003, '中国2年国债': 0.0003,
    '布伦特原油': 0.0001, '黄金': 0.0003, '铁矿石': 0.0003, '中国有色金属': 0.0003,
}

REPLICATION_COST = {
    '沪深300': 0.004, '创业板指': 0.030, '红利低波': 0.030, '恒生科技': 0.020,
    '标普500': 0.006, '德国DAX': 0.007, '中国10年国债': 0.003, '中国2年国债': 0.003,
    '布伦特原油': 0.006, '黄金': 0.006, '铁矿石': 0.006, '中国有色金属': 0.006,
}

# 资产计价货币映射
ASSET_CURRENCY = {
    '沪深300': 'CNH', '创业板指': 'CNH', '红利低波': 'CNH', '恒生科技': 'HKD',
    '标普500': 'USD', '德国DAX': 'EUR', '中国10年国债': 'CNH', '中国2年国债': 'CNH',
    '布伦特原油': 'USD', '黄金': 'CNH', '铁矿石': 'CNH', '中国有色金属': 'CNH',
}


# =============================================================================
# 第二部分：数据结构
# =============================================================================

@dataclass
class PendingRebalance:
    """待执行的调仓信息"""
    signal_date: pd.Timestamp       # 信号日（权重计算日）
    execute_date: pd.Timestamp      # 执行日（T+2）
    weights: Dict[str, float]       # 目标权重（重置后权重）
    rebalance_type: str             # 'monthly' 或 'vol_reset'
    signal_weights: Dict[str, float] = None  # 信号日的实际权重 w_cny（仅vol_reset）
    vol_trigger: float = None       # 触发时的波动率（仅vol_reset）
    scale_factor: float = None      # 缩放因子（仅vol_reset）


@dataclass
class BacktestState:
    """回测状态 - 集中管理所有状态变量"""
    assets: List[str]               # 资产列表
    
    # 净值相关
    nav: float = BASE_VALUE         # 当日净值
    nav_base: float = BASE_VALUE    # 上次调仓日净值（用于线性累加）
    
    # 持仓相关（初始化为空字典，在 __post_init__ 中填充）
    positions_cny: Dict[str, float] = field(default_factory=dict)      # 人民币持仓（复利更新）
    positions_local: Dict[str, float] = field(default_factory=dict)    # 本币持仓（复利更新）
    apl_local: Dict[str, float] = field(default_factory=dict)          # 本币累计损益（用于净值计算）
    
    # 权重相关
    target_weights: Dict[str, float] = field(default_factory=dict)     # 当前目标权重
    
    # 调仓队列
    pending_rebalance: Optional[PendingRebalance] = None
    
    # 日期记录
    last_rebalance_date: Optional[pd.Timestamp] = None
    last_rebalance_fx: Dict[str, float] = field(default_factory=dict)  # 上次调仓日的汇率（用于权重计算）
    
    # 费用累计
    total_trading_cost: float = 0.0
    total_replication_cost: float = 0.0
    
    def __post_init__(self):
        """初始化各资产的持仓字典"""
        for asset in self.assets:
            if asset not in self.positions_cny:
                self.positions_cny[asset] = 0.0
            if asset not in self.positions_local:
                self.positions_local[asset] = 0.0
            if asset not in self.apl_local:
                self.apl_local[asset] = 0.0
            if asset not in self.target_weights:
                self.target_weights[asset] = 0.0
            if asset not in self.last_rebalance_fx:
                self.last_rebalance_fx[asset] = 1.0


# =============================================================================
# 第三部分：数据加载模块
# =============================================================================

def load_data(script_dir: str):
    """加载所有数据文件"""
    # 交易日历
    trade_dates_df = pd.read_excel(os.path.join(script_dir, 'trade_dates.xlsx'))
    trade_dates_df['trade_dates'] = pd.to_datetime(trade_dates_df['trade_dates'])
    trade_dates_list = sorted(trade_dates_df['trade_dates'].tolist())
    
    # 价格数据
    prices = pd.read_excel(os.path.join(script_dir, 'daily_px.xlsx'), 
                           index_col=0, parse_dates=True)
    
    # 汇率数据
    fx_df = pd.read_excel(os.path.join(script_dir, 'fx.xlsx'), 
                          index_col=0, parse_dates=True)
    
    # 权重数据
    weights_df = pd.read_excel(os.path.join(script_dir, '权重计算结果.xlsx'), 
                               sheet_name='权重矩阵')
    weights_df['计算日期'] = pd.to_datetime(weights_df['计算日期'])
    
    return prices, trade_dates_list, fx_df, weights_df


def get_fx_rate(fx_df: pd.DataFrame, date: pd.Timestamp, currency: str) -> float:
    """获取指定日期和货币的汇率"""
    if currency == 'CNH':
        return 1.0
    if currency not in fx_df.columns:
        return 1.0
    if date in fx_df.index:
        rate = fx_df.loc[date, currency]
        if not np.isnan(rate):
            return rate
    # 向前查找最近的有效汇率
    valid_dates = fx_df.index[fx_df.index <= date]
    for d in reversed(valid_dates):
        rate = fx_df.loc[d, currency]
        if not np.isnan(rate):
            return rate
    return 1.0


def get_fx_rates(fx_df: pd.DataFrame, date: pd.Timestamp, assets: List[str]) -> Dict[str, float]:
    """获取所有资产在指定日期的汇率"""
    fx_rates = {}
    for asset in assets:
        currency = ASSET_CURRENCY.get(asset, 'CNH')
        fx_rates[asset] = get_fx_rate(fx_df, date, currency)
    return fx_rates


def build_monthly_rebalance_map(weights_df: pd.DataFrame, trade_dates_list: List[pd.Timestamp], 
                                 assets: List[str]) -> Dict[pd.Timestamp, Dict[str, float]]:
    """
    构建月度调仓日期映射（T+2执行逻辑）
    
    返回：{执行日期: 目标权重字典}
    """
    rebalance_map = {}
    
    for i, row in weights_df.iterrows():
        calc_date = row['计算日期']
        
        # T+2: 计算日之后的第二个交易日
        future_dates = [d for d in trade_dates_list if d > calc_date]
        if len(future_dates) >= 2:
            execute_date = future_dates[1]
        elif len(future_dates) == 1:
            execute_date = future_dates[0]
        else:
            continue
        
        # 跳过排除日
        while execute_date in SKIP_EXCLUDED_DATES:
            idx = trade_dates_list.index(execute_date)
            if idx + 1 < len(trade_dates_list):
                execute_date = trade_dates_list[idx + 1]
            else:
                break
        
        weight_dict = {asset: row.get(asset, 0.0) for asset in assets}
        rebalance_map[execute_date] = weight_dict
    
    return rebalance_map


# =============================================================================
# 第四部分：辅助计算模块
# =============================================================================

def calc_realized_vol(weights: Dict[str, float], daily_ret_df: pd.DataFrame, 
                      windows: List[int] = VOL_WINDOWS) -> float:
    """
    计算已实现波动率
    
    公式：vol = (daily_ret[-n:] * w).sum(axis=1).std() * sqrt(260)
    取 max{σ_22, σ_65, σ_130}
    """
    vol_values = []
    w = pd.Series(weights)
    
    for n in windows:
        if len(daily_ret_df) >= n:
            ret_window = daily_ret_df.iloc[-n:]
            weighted_ret = (ret_window * w).sum(axis=1)
            vol = weighted_ret.std() * np.sqrt(260)
            vol_values.append(vol)
    
    return max(vol_values) if vol_values else 0.0


def calc_asset_returns(prices: pd.DataFrame, fx_df: pd.DataFrame, 
                       date: pd.Timestamp, prev_date: pd.Timestamp,
                       assets: List[str]) -> tuple:
    """
    计算资产收益率（本币和人民币）
    
    返回：(本币收益率字典, 人民币收益率字典)
    """
    ret_local = {}
    ret_cny = {}
    
    for asset in assets:
        p1 = prices.loc[date, asset]
        p0 = prices.loc[prev_date, asset]
        
        # 本币收益率
        if not np.isnan(p1) and not np.isnan(p0) and p0 > 0:
            ret_local[asset] = p1 / p0 - 1
        else:
            ret_local[asset] = 0.0
        
        # 人民币收益率（含汇率变动）
        currency = ASSET_CURRENCY.get(asset, 'CNH')
        fx_curr = get_fx_rate(fx_df, date, currency)
        fx_prev = get_fx_rate(fx_df, prev_date, currency)
        
        p1_cny = p1 * fx_curr
        p0_cny = p0 * fx_prev
        
        if not np.isnan(p1_cny) and not np.isnan(p0_cny) and p0_cny > 0:
            ret_cny[asset] = p1_cny / p0_cny - 1
        else:
            ret_cny[asset] = 0.0
    
    return ret_local, ret_cny


# =============================================================================
# 第五部分：每日操作模块
# =============================================================================

def handle_index_start(state: BacktestState, date: pd.Timestamp, 
                       initial_weights: Dict[str, float], fx_rates: Dict[str, float]) -> None:
    """
    处理指数起始日（2014-02-10）
    
    操作：
    - 设置净值为1000
    - 按初始权重配置持仓
    - 初始化所有状态变量
    """
    state.nav = BASE_VALUE
    state.nav_base = BASE_VALUE
    
    for asset in state.assets:
        weight = initial_weights.get(asset, 0.0)
        state.positions_cny[asset] = state.nav * weight
        state.positions_local[asset] = state.positions_cny[asset] / fx_rates[asset]
        state.apl_local[asset] = 0.0
        state.target_weights[asset] = weight
    
    state.last_rebalance_date = date
    state.last_rebalance_fx = fx_rates.copy()  # 记录调仓日汇率


def handle_daily_pnl_update(state: BacktestState, date: pd.Timestamp, prev_date: pd.Timestamp,
                            ret_local: Dict[str, float], ret_cny: Dict[str, float],
                            fx_rates: Dict[str, float], enable_costs: bool) -> float:
    """
    处理每日损益更新（与V4逻辑一致）
    
    操作：
    - 计算本币损益 pnl_local，累加到 apl_local
    - 更新本币持仓（复利模式）
    - 更新人民币持仓（复利模式，与V4一致）
    - 计算新净值：nav = nav_base + sum(apl_local × 当日汇率)
    
    返回：当日复制费用
    """
    daily_replication_cost = 0.0
    days_between = (date - prev_date).days
    
    for asset in state.assets:
        if state.positions_cny[asset] == 0:
            continue
        
        r_local = ret_local.get(asset, 0.0)
        r_cny = ret_cny.get(asset, 0.0)
        
        # 本币损益（用于净值计算）
        pnl_local = state.positions_local[asset] * r_local
        
        # 复制费用（本币）
        rc_cost_local = 0.0
        if enable_costs:
            rc = REPLICATION_COST.get(asset, 0.005)
            rc_cost_local = state.positions_local[asset] * (rc / 365.0) * days_between
            daily_replication_cost += rc_cost_local * fx_rates[asset]
        
        # 本币累计损益（扣除复制费用）
        state.apl_local[asset] += pnl_local - rc_cost_local
        
        # 本币持仓更新（复利）
        state.positions_local[asset] *= (1 + r_local)
        
        # 人民币持仓更新（复利，与V4一致）
        state.positions_cny[asset] *= (1 + r_cny)
    
    # 净值 = nav_base + sum(本币累计损益 × 当日汇率)
    total_apl_cny = sum(state.apl_local[asset] * fx_rates[asset] for asset in state.assets)
    state.nav = state.nav_base + total_apl_cny
    
    # 累计复制费用
    state.total_replication_cost += daily_replication_cost
    
    return daily_replication_cost


def handle_rebalance_execute(state: BacktestState, date: pd.Timestamp,
                             prev_nav: float, fx_rates: Dict[str, float], enable_costs: bool) -> float:
    """
    处理调仓执行日（月度调仓或波动率重置）- 与V4一致
    
    操作：
    - 计算交易费用（基于前一日净值）
    - 按目标权重重置持仓（基于前一日净值）
    - 重置累计损益
    - 更新净值基准
    
    返回：交易费用
    """
    pending = state.pending_rebalance
    new_weights = pending.weights
    trading_cost = 0.0
    
    # 1. 计算交易费用（与V4一致：基于前一日净值计算目标持仓）
    if enable_costs:
        for asset in state.assets:
            target_pos_local = prev_nav * new_weights.get(asset, 0) / fx_rates[asset]
            current_pos_local = state.positions_local[asset]
            trade_amount_local = abs(target_pos_local - current_pos_local)
            tc = TRADING_COST.get(asset, 0.001)
            trading_cost += trade_amount_local * tc * fx_rates[asset]
        
        state.nav -= trading_cost
    
    # 2. 按新权重重置持仓（与V4一致：基于前一日净值）
    for asset in state.assets:
        weight = new_weights.get(asset, 0.0)
        state.positions_cny[asset] = prev_nav * weight
        state.positions_local[asset] = state.positions_cny[asset] / fx_rates[asset]
        state.apl_local[asset] = 0.0
        state.target_weights[asset] = weight
    
    # 3. 更新状态
    state.nav_base = state.nav
    state.last_rebalance_date = date
    state.last_rebalance_fx = fx_rates.copy()  # 记录调仓日汇率（用于权重计算）
    state.pending_rebalance = None
    
    # 4. 累计交易费用
    state.total_trading_cost += trading_cost
    
    return trading_cost


def handle_volatility_monitor(state: BacktestState, date: pd.Timestamp, date_idx: int,
                              daily_ret_df: pd.DataFrame, trade_dates_list: List[pd.Timestamp],
                              rebalance_dates_set: set, vol_reset_dates_set: set) -> Optional[PendingRebalance]:
    """
    处理波动率监测（与V4逻辑一致）
    
    操作：
    - 计算当前实际权重（使用调仓日汇率，与V4一致）
    - 计算已实现波动率
    - 如果触发阈值，生成待执行的VW调仓
    
    返回：如果触发则返回 PendingRebalance，否则返回 None
    """
    # 前60个净值日不监控
    if date_idx < MONITOR_START_DAYS:
        return None
    
    # 1. 计算实际权重（使用调仓日汇率，与外部系统一致）
    # w_cny = (本币持仓 × 调仓日汇率) / 净值
    if state.nav <= 0:
        return None
    w_cny = {asset: state.positions_local[asset] * state.last_rebalance_fx[asset] / state.nav 
             for asset in state.assets}
    
    # 2. 计算已实现波动率
    ytd_ret = daily_ret_df.loc[:date, state.assets]
    vol_trigger = calc_realized_vol(w_cny, ytd_ret)
    
    # 3. 判断是否触发
    if vol_trigger <= VOL_TRIGGER_THRESHOLD:
        return None
    
    # 4. 确定执行日（T+2）
    future_dates = [d for d in trade_dates_list if d > date]
    if len(future_dates) < 2:
        return None
    execute_date = future_dates[1]
    
    # 跳过排除日
    while execute_date in SKIP_EXCLUDED_DATES:
        idx = trade_dates_list.index(execute_date)
        if idx + 1 < len(trade_dates_list):
            execute_date = trade_dates_list[idx + 1]
        else:
            return None
    
    # 5. 冲突检查（按文档：检查[t, T+1, T+2]整个区间）
    # 文档："从信号日t日（含）起到t日之后的第2个指数交易日（含）为止，
    #        这段时间区间内，不存在任何已安排的指数权重调整日或波动率重置调整日"
    # 检查信号日t、T+1、T+2执行日这三天
    t_plus_1 = future_dates[0] if len(future_dates) >= 1 else None
    t_plus_2 = execute_date
        
    has_conflict = False
    # 检查信号日t
    if date in rebalance_dates_set or date in vol_reset_dates_set:
        has_conflict = True
    # 检查T+1
    if t_plus_1 and (t_plus_1 in rebalance_dates_set or t_plus_1 in vol_reset_dates_set):
        has_conflict = True
    # 检查T+2执行日
    if t_plus_2 in rebalance_dates_set or t_plus_2 in vol_reset_dates_set:
        has_conflict = True
        
    if has_conflict:
        return None
    
    # 6. 计算VW权重
    scale_factor = VOL_TARGET / vol_trigger
    vw_weights = {asset: w * scale_factor for asset, w in w_cny.items()}
    
    # 7. 权重截断（小数点后三位，消除计算摩擦）
    vw_weights = {asset: np.trunc(w * 1000) / 1000 for asset, w in vw_weights.items()}
    
    return PendingRebalance(
        signal_date=date,
        execute_date=execute_date,
        weights=vw_weights,
        rebalance_type='vol_reset',
        signal_weights=w_cny.copy(),  # 保存信号日的实际权重
        vol_trigger=vol_trigger,
        scale_factor=scale_factor
    )


def record_state(state: BacktestState, date: pd.Timestamp, 
                 fx_rates: Dict[str, float], enable_fx: bool) -> dict:
    """记录当日状态"""
    record = {
        '日期': date,
        '净值': state.nav,
        '总杠杆': sum(state.positions_cny.values()) / state.nav if state.nav > 0 else 0,
    }
    
    # 各资产权重
    for asset in state.assets:
        record[asset] = state.positions_cny[asset] / state.nav if state.nav > 0 else 0
    
    # 汇率记录
    if enable_fx:
        for asset in ['恒生科技', '标普500', '德国DAX', '布伦特原油']:
            if asset in state.assets:
                record[f'{asset}_FX'] = fx_rates.get(asset, 1.0)
    
    return record


# =============================================================================
# 第六部分：主回测循环
# =============================================================================

def run_backtest(enable_vol_control=True, enable_costs=True, enable_fx=True):
    """
    主回测循环 - 按时间线逐日执行
    
    步骤：
    A. 指数起始日处理
    B. 每日损益更新
    C. 调仓执行（优先级最高）
    D. 月度调仓检查
    E. 波动率监测
    F. 记录当日状态
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("=" * 70)
    print("大类资产配置指数策略 - 完整回测（V5版本 - 时间线重构）")
    print(f"  波动率监控: {'启用' if enable_vol_control else '禁用'}")
    print(f"  费用计算: {'启用' if enable_costs else '禁用'}")
    print(f"  汇率转换: {'启用' if enable_fx else '禁用'}")
    print("=" * 70)
    
    # ========== 1. 数据加载 ==========
    print("\n1. 数据加载...")
    prices, trade_dates_list, fx_df, weights_df = load_data(script_dir)
    assets = prices.columns.tolist()
    trade_dates_set = set(trade_dates_list)
    
    print(f"   交易日历: {len(trade_dates_list)}个交易日")
    print(f"   净值日历: {prices.shape[0]}天")
    print(f"   资产列表: {assets}")
    print(f"   权重数据: {len(weights_df)}个调仓日")
    
    # ========== 2. 构建日期映射 ==========
    print("\n2. 构建日期映射...")
    monthly_rebalance_map = build_monthly_rebalance_map(weights_df, trade_dates_list, assets)
    rebalance_dates_set = set(monthly_rebalance_map.keys())
    backtest_dates = prices.index[prices.index >= BASE_DATE].tolist()
    
    # 预计算收益率DataFrame（用于波动率计算）
    daily_ret_df = prices[assets].pct_change().fillna(0)
    
    # 获取初始权重（第一行）
    initial_weights = {asset: weights_df.iloc[0].get(asset, 0.0) for asset in assets}
    
    print(f"   回测区间: {backtest_dates[0].date()} ~ {backtest_dates[-1].date()}")
    print(f"   月度调仓日: {len(monthly_rebalance_map)}个")
    print(f"   初始权重: 总杠杆 {sum(initial_weights.values()):.2f}x")
    
    # ========== 3. 初始化状态 ==========
    print("\n3. 初始化状态...")
    state = BacktestState(assets=assets)
    nav_history = []
    vol_events = []
    vol_reset_dates_set = set()
    
    # ========== 4. 时间线主循环 ==========
    print("\n4. 开始回测...")
    prev_date = None
    prev_nav = None  # 前一日净值（用于调仓计算）
    
    for date_idx, date in enumerate(backtest_dates):
        if date not in prices.index:
            continue
        
        # 获取当日汇率
        fx_rates = get_fx_rates(fx_df, date, assets) if enable_fx else {a: 1.0 for a in assets}
        
        # ------------------------------------------------------------------
        # 步骤A: 指数起始日处理
        # ------------------------------------------------------------------
        if date == BASE_DATE:
            handle_index_start(state, date, initial_weights, fx_rates)
            nav_history.append(record_state(state, date, fx_rates, enable_fx))
            prev_date = date
            prev_nav = state.nav
            continue
        
        # ------------------------------------------------------------------
        # 步骤B: 每日损益更新
        # ------------------------------------------------------------------
        ret_local, ret_cny = calc_asset_returns(prices, fx_df, date, prev_date, assets)
        handle_daily_pnl_update(state, date, prev_date, ret_local, ret_cny, fx_rates, enable_costs)
        
        # ------------------------------------------------------------------
        # 步骤C: 调仓执行（优先级最高 - 波动率重置）
        # ------------------------------------------------------------------
        is_rebalance_day = False
        
        if state.pending_rebalance is not None and date == state.pending_rebalance.execute_date:
            pending = state.pending_rebalance
            handle_rebalance_execute(state, date, prev_nav, fx_rates, enable_costs)
            is_rebalance_day = True
            
            # 记录波动率重置事件
            if pending.rebalance_type == 'vol_reset':
                vol_events.append({
                    '信号日期': pending.signal_date,
                    '执行日期': date,
                    'VolTrigger': pending.vol_trigger,
                    '触发阈值': VOL_TRIGGER_THRESHOLD,
                    '目标波动率': VOL_TARGET,
                    '缩放因子': pending.scale_factor,
                    '信号日权重(w_cny)': pending.signal_weights.copy(),  # 触发时的权重
                    '重置后权重': pending.weights.copy(),
                })
        
        # ------------------------------------------------------------------
        # 步骤D: 月度调仓检查
        # ------------------------------------------------------------------
        if date in rebalance_dates_set and not is_rebalance_day:
            # 创建月度调仓任务并立即执行
            state.pending_rebalance = PendingRebalance(
                signal_date=date,  # 月度调仓的信号日就是执行日
                execute_date=date,
                weights=monthly_rebalance_map[date],
                rebalance_type='monthly'
            )
            handle_rebalance_execute(state, date, prev_nav, fx_rates, enable_costs)
            is_rebalance_day = True
            # 月度调仓后清除待执行的波动率重置
            state.pending_rebalance = None
        
        # ------------------------------------------------------------------
        # 步骤E: 波动率监测（与V4一致：调仓日跳过波动率检测）
        # ------------------------------------------------------------------
        skip_vol_check = is_rebalance_day  # 调仓日跳过波动率检测
        if (enable_vol_control 
            and state.pending_rebalance is None 
            and not skip_vol_check):
            
            pending = handle_volatility_monitor(
                state, date, date_idx, daily_ret_df, 
                trade_dates_list, rebalance_dates_set, vol_reset_dates_set
            )
            if pending is not None:
                state.pending_rebalance = pending
                vol_reset_dates_set.add(pending.execute_date)
        
        # ------------------------------------------------------------------
        # 步骤F: 记录当日状态
        # ------------------------------------------------------------------
        nav_history.append(record_state(state, date, fx_rates, enable_fx))
        prev_date = date
        prev_nav = state.nav
    
    # ========== 5. 创建结果 ==========
    nav_df = pd.DataFrame(nav_history)
    nav_df.set_index('日期', inplace=True)
    
    cost_summary = {
        'trading_cost': state.total_trading_cost,
        'replication_cost': state.total_replication_cost,
        'total_cost': state.total_trading_cost + state.total_replication_cost,
    }
    
    print(f"\n   回测完成！净值日数: {len(nav_df)}, 波动率重置次数: {len(vol_events)}")
    
    return nav_df, vol_events, cost_summary


# =============================================================================
# 第七部分：绩效指标计算
# =============================================================================

def calc_annual_return(nav_series):
    """计算年化收益率"""
    total_return = nav_series.iloc[-1] / nav_series.iloc[0] - 1
    days = (nav_series.index[-1] - nav_series.index[0]).days
    years = days / 365.0
    return (1 + total_return) ** (1 / years) - 1


def calc_annual_volatility(nav_series):
    """计算年化波动率（260个交易日）"""
    daily_returns = nav_series.pct_change().dropna()
    return daily_returns.std() * np.sqrt(260)


def calc_max_drawdown(nav_series):
    """计算最大回撤"""
    cummax = nav_series.cummax()
    drawdown = (nav_series - cummax) / cummax
    max_dd = drawdown.min()
    max_dd_date = drawdown.idxmin()
    return max_dd, max_dd_date


def calc_sharpe_ratio(nav_series, risk_free_rate=RISK_FREE_RATE):
    """计算夏普比率"""
    annual_return = calc_annual_return(nav_series)
    annual_vol = calc_annual_volatility(nav_series)
    return (annual_return - risk_free_rate) / annual_vol if annual_vol > 0 else 0.0


def calc_period_metrics(nav_series, start_date=None, end_date=None, period_name='全局'):
    """计算指定时间段的绩效指标"""
    if start_date is not None:
        start_date = pd.Timestamp(start_date)
        nav_period = nav_series[nav_series.index >= start_date]
    else:
        nav_period = nav_series
    
    if end_date is not None:
        end_date = pd.Timestamp(end_date)
        nav_period = nav_period[nav_period.index <= end_date]
    
    if len(nav_period) < 2:
        return None
    
    return {
        '时间段': period_name,
        '起始日期': nav_period.index[0],
        '结束日期': nav_period.index[-1],
        '起始净值': nav_period.iloc[0],
        '结束净值': nav_period.iloc[-1],
        '累计收益率': nav_period.iloc[-1] / nav_period.iloc[0] - 1,
        '年化收益率': calc_annual_return(nav_period),
        '年化波动率': calc_annual_volatility(nav_period),
        '最大回撤': calc_max_drawdown(nav_period)[0],
        '最大回撤日期': calc_max_drawdown(nav_period)[1],
        '夏普比率': calc_sharpe_ratio(nav_period),
    }


# 分周期配置
PERIOD_CONFIG = [
    {'name': '全局', 'start': '2014-02-10', 'end': None},
    {'name': '2016年至今', 'start': '2016-01-01', 'end': None},
    {'name': '2019年至今', 'start': '2019-01-01', 'end': None},
    {'name': '2021年至今', 'start': '2021-01-01', 'end': None},
]


# =============================================================================
# 第八部分：结果输出
# =============================================================================

def run_full_analysis():
    """运行完整分析"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 运行回测
    nav_df, vol_events, costs = run_backtest(
        enable_vol_control=True, 
        enable_costs=True,
        enable_fx=True
    )
    nav_series = nav_df['净值']
    
    # 计算绩效指标
    annual_return = calc_annual_return(nav_series)
    annual_vol = calc_annual_volatility(nav_series)
    max_dd, max_dd_date = calc_max_drawdown(nav_series)
    sharpe = calc_sharpe_ratio(nav_series)
    
    period_metrics_list = []
    for period in PERIOD_CONFIG:
        metrics = calc_period_metrics(nav_series, period['start'], period['end'], period['name'])
        if metrics:
            period_metrics_list.append(metrics)
    
    # 打印结果
    print("\n" + "=" * 70)
    print("绩效指标（V5版本）")
    print("=" * 70)
    print(f"  起始日期: {nav_series.index[0].date()}")
    print(f"  结束日期: {nav_series.index[-1].date()}")
    print(f"  起始净值: {nav_series.iloc[0]:.2f}")
    print(f"  结束净值: {nav_series.iloc[-1]:.2f}")
    print(f"  累计收益率: {(nav_series.iloc[-1] / nav_series.iloc[0] - 1) * 100:.2f}%")
    print(f"  年化收益率: {annual_return * 100:.2f}%")
    print(f"  年化波动率: {annual_vol * 100:.2f}%")
    print(f"  最大回撤: {max_dd * 100:.2f}% ({max_dd_date.date()})")
    print(f"  夏普比率: {sharpe:.2f}")
    print("-" * 70)
    print(f"  累计交易费用: {costs['trading_cost']:.2f}")
    print(f"  累计复制费用: {costs['replication_cost']:.2f}")
    print(f"  费用合计: {costs['total_cost']:.2f}")
    print("-" * 70)
    print(f"  波动率重置次数: {len(vol_events)}")
    print("=" * 70)
    
    # 分周期指标
    print("\n" + "=" * 90)
    print("分周期绩效指标")
    print("=" * 90)
    print(f"{'时间段':<12} {'起始日期':<12} {'截止日期':<12} {'年化收益':>10} {'年化波动':>10} {'最大回撤':>10} {'夏普比率':>10}")
    print("-" * 90)
    for m in period_metrics_list:
        print(f"{m['时间段']:<12} {str(m['起始日期'].date()):<12} {str(m['结束日期'].date()):<12} "
              f"{m['年化收益率']*100:>9.2f}% {m['年化波动率']*100:>9.2f}% {m['最大回撤']*100:>9.2f}% {m['夏普比率']:>10.2f}")
    print("=" * 90)
    
    # 波动率重置事件
    if vol_events:
        print(f"\n波动率重置事件:")
        print(f"{'信号日期':<12} {'执行日期':<12} {'VolTrigger':>12} {'缩放因子':>10}")
        print("-" * 50)
        for event in vol_events:
            print(f"{str(event['信号日期'].date()):<12} {str(event['执行日期'].date()):<12} "
                  f"{event['VolTrigger']*100:>11.2f}% {event['缩放因子']:>10.2f}")
    
    # 保存结果
    print("\n保存结果...")
    output_path = os.path.join(script_dir, '回测结果_汇率版_v5.xlsx')
    
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        nav_df.to_excel(writer, sheet_name='每日净值')
        
        if vol_events:
            # 波动率重置事件
            events_df = pd.DataFrame([{
                '信号日期': e['信号日期'],
                '执行日期': e['执行日期'],
                'VolTrigger': e['VolTrigger'],
                '触发阈值': e['触发阈值'],
                '目标波动率': e['目标波动率'],
                '缩放因子': e['缩放因子'],
            } for e in vol_events])
            events_df.to_excel(writer, sheet_name='波动率重置事件', index=False)
            
            # VW权重矩阵（重置后权重）
            asset_list = list(ASSET_CURRENCY.keys())
            vw_matrix = []
            for event in vol_events:
                row = {'信号日期': event['信号日期']}
                for asset in asset_list:
                    row[asset] = event['重置后权重'].get(asset, 0)
                vw_matrix.append(row)
            vw_df = pd.DataFrame(vw_matrix)
            vw_df.set_index('信号日期', inplace=True)
            vw_df.to_excel(writer, sheet_name='VW权重矩阵')
            
            # 触发权重矩阵（信号日的实际权重 w_cny）
            trigger_matrix = []
            for event in vol_events:
                row = {'信号日期': event['信号日期']}
                trigger_weights = event.get('信号日权重(w_cny)', {})
                for asset in asset_list:
                    row[asset] = trigger_weights.get(asset, 0)
                trigger_matrix.append(row)
            trigger_df = pd.DataFrame(trigger_matrix)
            trigger_df.set_index('信号日期', inplace=True)
            trigger_df.to_excel(writer, sheet_name='触发权重矩阵')
            
            # 详细权重对比（触发时 + 重置后）
            weight_details = []
            for i, event in enumerate(vol_events):
                row = {
                    '序号': i + 1,
                    '信号日期': event['信号日期'],
                    '执行日期': event['执行日期'],
                }
                trigger_weights = event.get('信号日权重(w_cny)', {})
                reset_weights = event.get('重置后权重', {})
                for asset in asset_list:
                    row[f'{asset}_触发时'] = trigger_weights.get(asset, 0)
                    row[f'{asset}_重置后'] = reset_weights.get(asset, 0)
                weight_details.append(row)
            weight_df = pd.DataFrame(weight_details)
            weight_df.to_excel(writer, sheet_name='波动率触发权重详情', index=False)
        
        # 绩效指标
        metrics_df = pd.DataFrame({
            '指标': ['起始日期', '结束日期', '起始净值', '结束净值', 
                    '累计收益率', '年化收益率', '年化波动率', '最大回撤', '夏普比率',
                    '累计交易费用', '累计复制费用', '波动率重置次数'],
            '值': [str(nav_series.index[0].date()), str(nav_series.index[-1].date()),
                  f'{nav_series.iloc[0]:.2f}', f'{nav_series.iloc[-1]:.2f}',
                  f'{(nav_series.iloc[-1] / nav_series.iloc[0] - 1) * 100:.2f}%',
                  f'{annual_return * 100:.2f}%', f'{annual_vol * 100:.2f}%',
                  f'{max_dd * 100:.2f}%', f'{sharpe:.2f}',
                  f'{costs["trading_cost"]:.2f}', f'{costs["replication_cost"]:.2f}',
                  f'{len(vol_events)}']
        })
        metrics_df.to_excel(writer, sheet_name='绩效指标', index=False)
        
        # 分周期指标
        period_df = pd.DataFrame([{
            '时间段': m['时间段'],
            '起始日期': str(m['起始日期'].date()),
            '截止日期': str(m['结束日期'].date()),
            '累计收益率': f"{m['累计收益率']*100:.2f}%",
            '年化收益率': f"{m['年化收益率']*100:.2f}%",
            '年化波动率': f"{m['年化波动率']*100:.2f}%",
            '最大回撤': f"{m['最大回撤']*100:.2f}%",
            '夏普比率': f"{m['夏普比率']:.2f}",
        } for m in period_metrics_list])
        period_df.to_excel(writer, sheet_name='分周期指标', index=False)
        
        # 资产货币映射
        fx_info = pd.DataFrame({
            '资产': list(ASSET_CURRENCY.keys()),
            '计价货币': list(ASSET_CURRENCY.values()),
        })
        fx_info.to_excel(writer, sheet_name='资产货币映射', index=False)
    
    print(f"   结果已保存至: {output_path}")
    
    # 绘制净值曲线
    print("\n绘制净值曲线...")
    fig, ax = plt.subplots(figsize=(14, 7))
    
    ax.plot(nav_series.index, nav_series.values, 'b-', linewidth=1)
    
    for event in vol_events:
        ax.axvline(x=event['执行日期'], color='red', linestyle='--', alpha=0.5, linewidth=0.8)
    
    ax.set_title('大类资产配置指数净值曲线（V5版本）', fontsize=14)
    ax.set_xlabel('日期', fontsize=12)
    ax.set_ylabel('净值（人民币）', fontsize=12)
    ax.grid(True, alpha=0.3)
    
    text_str = (f'年化收益率: {annual_return*100:.2f}%\n'
                f'年化波动率: {annual_vol*100:.2f}%\n'
                f'最大回撤: {max_dd*100:.2f}%\n'
                f'夏普比率: {sharpe:.2f}\n'
                f'重置次数: {len(vol_events)}\n'
                f'费用合计: {costs["total_cost"]:.1f}')
    ax.text(0.02, 0.98, text_str, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    fig_path = os.path.join(script_dir, '净值曲线_汇率版_v5.png')
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    print(f"   图表已保存至: {fig_path}")
    
    plt.close()
    
    print("\n回测完成！")
    
    return nav_df, vol_events, costs


if __name__ == '__main__':
    run_full_analysis()
