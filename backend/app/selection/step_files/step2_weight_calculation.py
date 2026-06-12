# -*- coding: utf-8 -*-
"""
大类资产配置指数策略 - 第二步：权重计算（portfilio-end 副本）

从 动量策略相关资料/step2_weight_calculation.py 复制，增加：
- calc_weights_for_date 支持 target_vol, max_leverage, weight_caps, fillna_zero 参数
"""

import pandas as pd
import numpy as np
import os
from typing import Dict, List, Optional, Any

# =============================================================================
# 第一部分：配置参数（默认值，可被调用方覆盖）
# =============================================================================

TARGET_VOL = 0.05
MAX_LEVERAGE = 4.0
WEIGHT_CAPS = {
    '沪深300': 0.10, '创业板指': 0.10, '红利低波': 0.10, '恒生科技': 0.10,
    '标普500': 0.15, '德国DAX': 0.10, '中国10年国债': 0.60, '中国2年国债': 0.90,
    '布伦特原油': 0.10, '黄金': 0.10, '铁矿石': 0.10, '中国有色金属': 0.10,
    # 测试资产（与上同权重上限）
    'SH000300_TEST': 0.10, 'SZ399006_TEST': 0.10, 'ZZ000001_TEST': 0.10,
    'HSTECH_TEST': 0.10, 'SPX_TEST': 0.15, 'GDAXI_TEST': 0.10,
    'ZQGZ10_TEST': 0.60, 'ZQGZ2_TEST': 0.90, 'B00Y_TEST': 0.10,
    'GLD_TEST': 0.10, 'IRON_TEST': 0.10, 'YSJS_TEST': 0.10,
}
VOL_WINDOWS = [22, 65, 130]
ANNUALIZE_FACTOR = np.sqrt(260)


# =============================================================================
# 第二部分：波动率计算函数
# =============================================================================

def calc_asset_volatility(prices, date_idx, windows=VOL_WINDOWS):
    """计算资产波动率，取22、65、130日年化波动率的最大值"""
    returns = prices.pct_change()
    vols = {}
    for asset in prices.columns:
        asset_vols = []
        for w in windows:
            if date_idx >= w:
                ret_window = returns[asset].iloc[date_idx - w + 1 : date_idx + 1]
                vol = ret_window.std() * ANNUALIZE_FACTOR
                if not np.isnan(vol):
                    asset_vols.append(vol)
        vols[asset] = max(asset_vols) if asset_vols else np.nan
    return pd.Series(vols)


def calc_portfolio_volatility(prices, weights, date_idx, windows=VOL_WINDOWS, fillna_zero=False):
    """计算组合波动率（与参考一致：默认不 fillna，确保 ex-ante vol 对齐）"""
    returns = prices.pct_change()
    if fillna_zero:
        returns = returns.fillna(0)
    valid_assets = [a for a in weights.index if weights[a] > 0 and a in returns.columns]
    if not valid_assets:
        return 0.0
    port_vols = []
    for w in windows:
        if date_idx >= w:
            port_returns = pd.Series(0.0, index=returns.index)
            for asset in valid_assets:
                port_returns += weights[asset] * returns[asset]
            ret_window = port_returns.iloc[date_idx - w + 1 : date_idx + 1]
            vol = ret_window.std() * ANNUALIZE_FACTOR
            if not np.isnan(vol):
                port_vols.append(vol)
    return max(port_vols) if port_vols else 0.0


# =============================================================================
# 第三部分：权重计算函数
# =============================================================================

def calc_risk_budget(selection_matrix_row, assets):
    """根据入选情况分配风险预算（与参考完全一致：无 fallback）"""
    budgets = {}
    for asset in assets:
        status = selection_matrix_row.get(asset, 0)
        if status == 2:
            budgets[asset] = 2 / 8
        elif status == 1:
            budgets[asset] = 1 / 8
        else:
            budgets[asset] = 0
    return pd.Series(budgets)


def calc_initial_weights(risk_budgets, asset_vols, target_vol=TARGET_VOL):
    """w_init = b × (target_vol / σ)"""
    weights = {}
    for asset in risk_budgets.index:
        b = risk_budgets[asset]
        sigma = asset_vols.get(asset, np.nan)
        if b > 0 and sigma > 0 and not np.isnan(sigma):
            weights[asset] = b * (target_vol / sigma)
        else:
            weights[asset] = 0.0
    return pd.Series(weights)


def apply_scale_constraint(weights, port_vol, target_vol=TARGET_VOL, max_leverage=MAX_LEVERAGE):
    """scale = min(target_vol / σ_port, max_leverage / Σw)"""
    total_weight = weights.sum()
    if total_weight <= 0:
        return weights, 1.0
    scale_vol = target_vol / port_vol if port_vol > 0 else 1.0
    scale_leverage = max_leverage / total_weight
    scale = min(scale_vol, scale_leverage)
    return weights * scale, scale


def apply_weight_caps_and_rebalance(weights, weight_caps=None):
    """只截断超限权重，不做再分配"""
    if weights.sum() <= 0:
        return weights
    caps = weight_caps if weight_caps is not None else WEIGHT_CAPS
    capped_weights = weights.copy()
    for asset in capped_weights.index:
        cap = caps.get(asset, 1.0)
        if capped_weights[asset] > cap:
            capped_weights[asset] = cap
    return capped_weights


def calc_weights_for_date(
    nav,
    date_idx,
    selection_row,
    all_assets,
    target_vol=None,
    max_leverage=None,
    weight_caps=None,
    fillna_zero=False,
):
    """
    计算单个调仓日的权重

    Parameters:
    -----------
    nav : pd.DataFrame - 净值数据
    date_idx : int - 计算日索引
    selection_row : dict - 入选矩阵行 {asset: 0|1|2}
    all_assets : list - 全部资产列表
    target_vol : float - 目标波动率（默认 0.05）
    max_leverage : float - 杠杆上限（默认 4.0）
    weight_caps : dict - 单资产权重上限（默认使用内置 WEIGHT_CAPS）
    fillna_zero : bool - 收益率 NaN 是否填 0（默认 False，与参考一致）

    Returns:
    --------
    result : dict - 包含风险预算、波动率、权重等
    """
    target_vol = target_vol if target_vol is not None else TARGET_VOL
    max_leverage = max_leverage if max_leverage is not None else MAX_LEVERAGE
    caps = dict(WEIGHT_CAPS)
    if weight_caps:
        caps.update(weight_caps)

    result = {
        '资产波动率': {},
        '风险预算': {},
        '初始权重': {},
        '缩放后权重': {},
        '最终权重': {},
        '缩放系数': 1.0,
        '组合波动率': 0.0,
        '总杠杆': 0.0,
    }

    risk_budgets = calc_risk_budget(selection_row, all_assets)
    result['风险预算'] = risk_budgets.to_dict()

    asset_vols = calc_asset_volatility(nav, date_idx)
    result['资产波动率'] = asset_vols.to_dict()

    initial_weights = calc_initial_weights(risk_budgets, asset_vols, target_vol)
    result['初始权重'] = initial_weights.to_dict()

    port_vol = calc_portfolio_volatility(nav, initial_weights, date_idx, fillna_zero=fillna_zero)
    result['组合波动率'] = port_vol

    scaled_weights, scale = apply_scale_constraint(
        initial_weights, port_vol, target_vol=target_vol, max_leverage=max_leverage
    )
    result['缩放后权重'] = scaled_weights.to_dict()
    result['缩放系数'] = scale

    total_weight = float(initial_weights.sum())
    scale_vol = target_vol / port_vol if port_vol > 0 else 1.0
    scale_leverage = max_leverage / total_weight if total_weight > 0 else 1.0
    result['_debug_total_weight'] = total_weight
    result['_debug_scale_vol'] = scale_vol
    result['_debug_scale_leverage'] = scale_leverage
    result['_debug_scaled_sum'] = float(scaled_weights.sum())

    final_weights = apply_weight_caps_and_rebalance(scaled_weights, weight_caps=caps)
    result['最终权重'] = final_weights.to_dict()
    result['总杠杆'] = final_weights.sum()

    return result


# =============================================================================
# 第四部分：主程序（独立运行用）
# =============================================================================

def main():
    print("=" * 70)
    print("大类资产配置指数策略 - 第二步：权重计算")
    print("=" * 70)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    nav_path = os.path.join(script_dir, 'daily_px.xlsx')
    selection_path = os.path.join(script_dir, '资产选择结果.xlsx')
    if not os.path.exists(nav_path) or not os.path.exists(selection_path):
        print("数据文件不存在，需 daily_px.xlsx 和 资产选择结果.xlsx")
        return
    nav = pd.read_excel(nav_path, index_col=0, parse_dates=True)
    selection_summary = pd.read_excel(selection_path, sheet_name='选择汇总')
    selection_matrix = pd.read_excel(selection_path, sheet_name='入选矩阵')
    all_assets = nav.columns.tolist()
    print(f"\n净值数据: {nav.shape[0]}行 × {nav.shape[1]}列")
    print(f"调仓日数量: {len(selection_summary)}")
    print("\n第二步完成（独立运行需 daily_px.xlsx 和 资产选择结果.xlsx）。")


if __name__ == '__main__':
    main()
