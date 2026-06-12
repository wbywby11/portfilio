# -*- coding: utf-8 -*-
"""
大类资产配置指数策略 - 第二步：权重计算 (V2版本 - 对齐外部系统)
严格按照《大类资产指数编制规则》实现

V2版本修改说明：
- 组合波动率计算时，对缺失的收益率数据使用fillna(0)处理
- 假设该资产在数据缺失日无变动
- 与外部系统asset_weight.xlsx计算逻辑完全一致

数据依赖（原始数据）：
- daily_px.xlsx: 底层资产每日价格

数据依赖（前置步骤输出）：
- 资产选择结果.xlsx: step1 输出的入选矩阵

输出文件：
- 权重计算结果.xlsx: 包含权重矩阵、权重详情

本脚本实现：
1. 读取资产选择结果
2. 分配风险预算（动量1/8，反转1/8，两者2/8）
3. 计算资产波动率（22/65/130日最大值）
4. 计算初始权重：w_init = b × (5% / σ)
5. 组合波动率与杠杆约束
6. 应用单资产权重上限
7. 输出每个调仓日的完整仓位
"""

import pandas as pd
import numpy as np
import os

# =============================================================================
# 第一部分：配置参数
# =============================================================================

# 目标波动率
TARGET_VOL = 0.05  # 5%

# 杠杆上限
MAX_LEVERAGE = 4.0

# 单资产权重上限
WEIGHT_CAPS = {
    '沪深300': 0.10,
    '创业板指': 0.10,
    '红利低波': 0.10,
    '恒生科技': 0.10,
    '标普500': 0.15,  # 特殊配置
    '德国DAX': 0.10,
    '中国10年国债': 0.60,
    '中国2年国债': 0.90,
    '布伦特原油': 0.10,
    '黄金': 0.10,
    '铁矿石': 0.10,
    '中国有色金属': 0.10,
}

# 波动率计算窗口
VOL_WINDOWS = [22, 65, 130]

# 年化因子（文档要求使用260个交易日/年）
ANNUALIZE_FACTOR = np.sqrt(260)


# =============================================================================
# 第二部分：波动率计算函数
# =============================================================================

def calc_asset_volatility(prices, date_idx, windows=VOL_WINDOWS):
    """
    计算资产波动率
    取22、65、130日年化波动率的最大值
    """
    returns = prices.pct_change()
    vols = {}
    
    for asset in prices.columns:
        asset_vols = []
        for w in windows:
            if date_idx >= w:
                ret_window = returns[asset].iloc[date_idx-w+1:date_idx+1]
                vol = ret_window.std() * ANNUALIZE_FACTOR
                if not np.isnan(vol):
                    asset_vols.append(vol)
        
        if asset_vols:
            vols[asset] = max(asset_vols)
        else:
            vols[asset] = np.nan
    
    return pd.Series(vols)


def calc_portfolio_volatility(prices, weights, date_idx, windows=VOL_WINDOWS):
    """
    计算组合波动率
    使用权重加权的组合收益率，取22、65、130日年化波动率的最大值
    
    V2修改：对缺失的收益率数据使用fillna(0)处理
    与外部系统asset_weight.xlsx保持一致
    """
    returns = prices.pct_change()
    
    # 只计算有权重的资产
    valid_assets = [a for a in weights.index if weights[a] > 0 and a in returns.columns]
    if not valid_assets:
        return 0.0
    
    port_vols = []
    for w in windows:
        if date_idx >= w:
            # 计算组合收益率
            # V2修改：对缺失的收益率使用fillna(0)，假设该资产当天无变动
            port_returns = pd.Series(0.0, index=returns.index)
            for asset in valid_assets:
                port_returns += weights[asset] * returns[asset].fillna(0)
            
            ret_window = port_returns.iloc[date_idx-w+1:date_idx+1]
            vol = ret_window.std() * ANNUALIZE_FACTOR
            if not np.isnan(vol):
                port_vols.append(vol)
    
    return max(port_vols) if port_vols else 0.0


# =============================================================================
# 第三部分：权重计算函数
# =============================================================================

def calc_risk_budget(selection_matrix_row, assets):
    """
    根据入选情况分配风险预算
    - 仅动量入选：1/8
    - 仅反转入选：1/8
    - 两者都入选：2/8
    - 未入选：0
    """
    budgets = {}
    for asset in assets:
        status = selection_matrix_row.get(asset, 0)
        if status == 2:  # 动量+反转
            budgets[asset] = 2/8
        elif status == 1:  # 动量或反转
            budgets[asset] = 1/8
        else:  # 未入选
            budgets[asset] = 0
    return pd.Series(budgets)


def calc_initial_weights(risk_budgets, asset_vols, target_vol=TARGET_VOL):
    """
    计算初始权重
    w_init = b × (target_vol / σ)
    """
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
    """
    应用组合波动率与杠杆约束
    scale = min(target_vol / σ_port, max_leverage / Σw)
    """
    total_weight = weights.sum()
    
    if total_weight <= 0:
        return weights, 1.0
    
    # 计算缩放系数
    scale_vol = target_vol / port_vol if port_vol > 0 else 1.0
    scale_leverage = max_leverage / total_weight
    scale = min(scale_vol, scale_leverage)
    
    # 缩放后权重
    scaled_weights = weights * scale
    
    return scaled_weights, scale


def apply_weight_caps_and_rebalance(weights, weight_caps=WEIGHT_CAPS):
    """
    只截断超限权重，不做再分配
    与 asset_weight.xlsx 保持一致
    
    逻辑：
    1. 超过上限的资产设为上限
    2. 不做再分配，总权重可能减少
    """
    if weights.sum() <= 0:
        return weights
    
    # 应用硬上限截断
    capped_weights = weights.copy()
    for asset in capped_weights.index:
        cap = weight_caps.get(asset, 1.0)
        if capped_weights[asset] > cap:
            capped_weights[asset] = cap
    
    return capped_weights


def calc_weights_for_date(nav, date_idx, selection_row, all_assets,
                         target_vol=None, max_leverage=None, weight_caps=None):
    """
    计算单个调仓日的权重

    target_vol, max_leverage, weight_caps 为可选覆盖参数
    """
    _target_vol = target_vol if target_vol is not None else TARGET_VOL
    _max_leverage = max_leverage if max_leverage is not None else MAX_LEVERAGE
    _weight_caps = dict(WEIGHT_CAPS)
    if weight_caps:
        _weight_caps.update(weight_caps)

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

    # 1. 计算风险预算
    risk_budgets = calc_risk_budget(selection_row, all_assets)
    result['风险预算'] = risk_budgets.to_dict()
    
    # 2. 计算资产波动率
    asset_vols = calc_asset_volatility(nav, date_idx)
    result['资产波动率'] = asset_vols.to_dict()
    
    # 3. 计算初始权重
    initial_weights = calc_initial_weights(risk_budgets, asset_vols, _target_vol)
    result['初始权重'] = initial_weights.to_dict()

    # 4. 计算组合波动率（使用初始权重）
    port_vol = calc_portfolio_volatility(nav, initial_weights, date_idx)
    result['组合波动率'] = port_vol

    # 5. 应用缩放约束
    scaled_weights, scale = apply_scale_constraint(
        initial_weights, port_vol, target_vol=_target_vol, max_leverage=_max_leverage
    )
    result['缩放后权重'] = scaled_weights.to_dict()
    result['缩放系数'] = scale

    # 6. 应用权重上限并再平衡
    final_weights = apply_weight_caps_and_rebalance(scaled_weights, weight_caps=_weight_caps)
    result['最终权重'] = final_weights.to_dict()
    result['总杠杆'] = final_weights.sum()
    
    return result


# =============================================================================
# 第四部分：主程序
# =============================================================================

def main():
    print("=" * 70)
    print("大类资产配置指数策略 - 第二步：权重计算 (V2版本)")
    print("V2修改：组合波动率计算对缺失数据fillna(0)，与外部系统一致")
    print("=" * 70)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 读取净值数据
    nav_path = os.path.join(script_dir, 'daily_px.xlsx')
    nav = pd.read_excel(nav_path, index_col=0, parse_dates=True)
    print(f"\n净值数据: {nav.shape[0]}行 × {nav.shape[1]}列")
    
    # 读取资产选择结果
    selection_path = os.path.join(script_dir, '资产选择结果.xlsx')
    selection_summary = pd.read_excel(selection_path, sheet_name='选择汇总')
    selection_matrix = pd.read_excel(selection_path, sheet_name='入选矩阵')
    
    print(f"调仓日数量: {len(selection_summary)}")
    
    all_assets = nav.columns.tolist()
    print(f"资产列表: {all_assets}")
    
    # 存储所有调仓日的权重结果
    weight_results = []
    weight_details = []
    
    print("\n" + "=" * 70)
    print("开始计算权重...")
    print("=" * 70)
    
    for i, row in selection_summary.iterrows():
        calc_date = pd.Timestamp(row['计算日期'])
        
        # 找到该日期在净值数据中的索引
        if calc_date not in nav.index:
            # 找最近的日期
            valid_dates = nav.index[nav.index <= calc_date]
            if len(valid_dates) == 0:
                continue
            calc_date = valid_dates[-1]
        
        date_idx = nav.index.get_loc(calc_date)
        
        # 获取该日期的入选矩阵
        selection_row = selection_matrix.iloc[i].to_dict()
        
        # 计算权重
        result = calc_weights_for_date(nav, date_idx, selection_row, all_assets)
        
        # 构建权重记录（包含所有资产）
        weight_record = {'计算日期': calc_date}
        for asset in all_assets:
            weight_record[asset] = result['最终权重'].get(asset, 0.0)
        weight_record['总杠杆'] = result['总杠杆']
        weight_record['组合波动率'] = result['组合波动率']
        weight_record['缩放系数'] = result['缩放系数']
        weight_results.append(weight_record)
        
        # 构建详细记录
        for asset in all_assets:
            detail_record = {
                '计算日期': calc_date,
                '资产': asset,
                '入选状态': selection_row.get(asset, 0),
                '风险预算': result['风险预算'].get(asset, 0),
                '资产波动率': result['资产波动率'].get(asset, np.nan),
                '初始权重': result['初始权重'].get(asset, 0),
                '缩放后权重': result['缩放后权重'].get(asset, 0),
                '最终权重': result['最终权重'].get(asset, 0),
            }
            weight_details.append(detail_record)
        
        # 打印进度
        if (i + 1) % 12 == 0 or i == 0:
            print(f"  {calc_date.date()}: 总杠杆 {result['总杠杆']:.2f}x, "
                  f"组合波动率 {result['组合波动率']*100:.2f}%")
    
    # 创建DataFrame
    weight_df = pd.DataFrame(weight_results)
    detail_df = pd.DataFrame(weight_details)
    
    # 保存到Excel
    output_path = os.path.join(script_dir, '权重计算结果.xlsx')
    
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        # Sheet1: 权重矩阵（每行一个调仓日，每列一个资产）
        weight_df.to_excel(writer, sheet_name='权重矩阵', index=False)
        
        # Sheet2: 权重详情（长格式，包含中间计算过程）
        detail_df.to_excel(writer, sheet_name='权重详情', index=False)
    
    print("\n" + "=" * 70)
    print(f"结果已保存至: {output_path}")
    print("=" * 70)
    
    # 统计信息
    print("\n权重计算统计：")
    print(f"  总调仓次数: {len(weight_df)}")
    print(f"  平均总杠杆: {weight_df['总杠杆'].mean():.2f}x")
    print(f"  平均组合波动率: {weight_df['组合波动率'].mean()*100:.2f}%")
    
    print("\n各资产平均权重：")
    for asset in all_assets:
        avg_weight = weight_df[asset].mean()
        max_weight = weight_df[asset].max()
        print(f"  {asset}: 平均 {avg_weight*100:.1f}%, 最大 {max_weight*100:.1f}%")
    
    print("\n第二步完成！结果已保存至 '权重计算结果.xlsx'。")
    print("下一步：运行 step3_backtest_fx_v1.py 进行净值回测。")


if __name__ == '__main__':
    main()
