"""净值计算公式.

包含基础净值计算和指数净值分段累加法。
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd


def calculate_nav_from_prices(prices: pd.Series) -> pd.Series:
    """从价格序列计算归一化净值序列.
    
    将价格序列转换为净值序列（初始值=1）.
    
    公式: NAV_t = Price_t / Price_0
    
    参数:
        prices: 价格序列
    
    返回:
        净值序列（归一化，初始=1）
    """
    if prices.empty:
        return pd.Series(dtype=float)
    
    # 归一化：第一个价格=1
    nav = prices / float(prices.iloc[0])
    
    return nav


def calculate_nav_from_returns(
    returns: pd.Series,
    initial_nav: float = 1.0
) -> pd.Series:
    """从收益率序列计算净值序列.
    
    公式: NAV_t = NAV_0 * ∏(1 + r_i)
    
    参数:
        returns: 收益率序列
        initial_nav: 初始净值（默认1.0）
    
    返回:
        净值序列
    """
    if returns.empty:
        return pd.Series(dtype=float)
    
    nav = initial_nav * (1 + returns).cumprod()
    
    return nav


def calculate_index_nav(
    tr_series: Dict[str, pd.Series],
    weights: Dict[str, float],
    initial_index: float = 1000.0,
    fx_series: Optional[Dict[str, pd.Series]] = None,
    replication_cost_rates: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """计算指数净值序列（单一权重区间）.
    
    基于《净值计算.md》的分段累加公式：
    Index_{s+t} = Index_s + Σ_c APL_CNY_{s+t}^c
    
    其中:
    APL_{s+t}^c = APL_{s+t-1}^c + PV_{s+t-1}^c * (TR_{s+t}^c / TR_{s+t-1}^c - 1) - RC_{s+t}^c
    APL_CNY_{s+t}^c = APL_{s+t}^c * FX_{s+t}^c
    
    注意：本版本为单一权重区间（无调仓），不包含交易费用（TC=0）。
    
    参数:
        tr_series: 资产TR序列字典 {thscode: TR_t^c (pd.Series)}
        weights: 起始目标权重 {thscode: weight}
        initial_index: 起始净值（默认1000）
        fx_series: 汇率序列 {thscode: FX_t^c}，默认为1
        replication_cost_rates: 复制费用率 {thscode: rc^c}，年化费率
    
    返回:
        指数净值序列 Index_t
    """
    if not tr_series:
        raise ValueError("tr_series 不能为空")
    
    # 统一时间索引：取所有资产TR序列的交集
    common_index = None
    for s in tr_series.values():
        if common_index is None:
            common_index = s.index
        else:
            common_index = common_index.intersection(s.index)
    
    if common_index is None or len(common_index) == 0:
        raise ValueError("所有资产的TR序列没有共同的时间索引")
    
    # 按共同索引截取并排序
    tr_aligned: Dict[str, pd.Series] = {}
    for code, s in tr_series.items():
        tr_aligned[code] = s.loc[common_index].sort_index()
    
    # 准备汇率序列（默认为1）
    fx_aligned: Dict[str, pd.Series] = {}
    for code in tr_aligned.keys():
        if fx_series and code in fx_series:
            fx_aligned[code] = fx_series[code].reindex(common_index).fillna(method="ffill").fillna(1.0)
        else:
            fx_aligned[code] = pd.Series(1.0, index=common_index)
    
    # 准备复制费用率（年化），默认为0
    rc_rates: Dict[str, float] = {}
    for code in tr_aligned.keys():
        if replication_cost_rates and code in replication_cost_rates:
            rc_rates[code] = float(replication_cost_rates[code])
        else:
            rc_rates[code] = 0.0
    
    # 初始化容器
    dates = common_index.sort_values()
    index_nav = pd.Series(index=dates, dtype=float)
    
    # 资产持仓价值 PV_t^c、本币累计损益 APL_t^c
    pv: Dict[str, float] = {}
    apl: Dict[str, float] = {}
    
    # 起始日 s
    s_date = dates[0]
    index_nav.loc[s_date] = initial_index
    
    # 起始日的TR和FX
    tr_s = {code: float(series.loc[s_date]) for code, series in tr_aligned.items()}
    fx_s = {code: float(fx_aligned[code].loc[s_date]) for code in tr_aligned.keys()}
    
    # 初始化 PV_s^c 和 APL_s^c = 0
    for code, w in weights.items():
        if code not in tr_aligned:
            continue
        fx_val = fx_s.get(code, 1.0)
        pv[code] = initial_index * float(w) / fx_val
        apl[code] = 0.0
    
    # 逐日迭代计算
    prev_date = s_date
    for current_date in dates[1:]:
        apl_cny_sum = 0.0
        
        for code, series in tr_aligned.items():
            if code not in pv:
                continue
            
            tr_prev = float(series.loc[prev_date])
            tr_curr = float(series.loc[current_date])
            
            if tr_prev == 0:
                daily_return = 0.0
            else:
                daily_return = tr_curr / tr_prev - 1.0
            
            pv_prev = pv[code]
            
            # 复制费用：按年化费率/365 计提
            rc_rate = rc_rates.get(code, 0.0)
            rc = pv_prev * rc_rate / 365.0 if rc_rate > 0 else 0.0
            
            # 本币累计损益
            apl_prev = apl[code]
            apl_curr = apl_prev + pv_prev * daily_return - rc
            apl[code] = apl_curr
            
            # 更新持仓价值
            pv_curr = pv_prev * (1.0 + daily_return)
            pv[code] = pv_curr
            
            # 转换为人民币
            fx_curr = float(fx_aligned[code].loc[current_date])
            apl_cny = apl_curr * fx_curr
            apl_cny_sum += apl_cny
        
        # 指数净值
        index_nav.loc[current_date] = initial_index + apl_cny_sum
        prev_date = current_date
    
    return index_nav
