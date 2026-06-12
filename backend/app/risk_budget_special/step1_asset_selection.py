# -*- coding: utf-8 -*-
"""
大类资产配置指数策略 - 第一步：资产选择
严格按照《大类资产指数编制规则》实现

数据依赖（原始数据）：
- daily_px.xlsx: 底层资产每日价格

输出文件：
- 资产选择结果.xlsx: 包含选择汇总、入选矩阵、动量排名等详细信息

本脚本实现：
1. 动量因子计算（4因子×4窗口：MOM/MACD/POSI/SMOM，满分16分）
   - 动量因子最短观察期：260天
2. 反转因子计算（双窗口偏度：10天+22天）
   - 反转因子最短观察期：22天
   - 偏度从低到高排序（负偏度优先）
   - 打分规则：排名第k → 得 N-k+1 分（N为有效资产数）
   - 综合得分 = 10天得分 + 22天得分，最高2N分
3. 资产选择（动量选7个 + 反转选1个，取并集）
4. 输出每次调仓的详细排序和入围情况到Excel

指数基日：2014年2月10日
动量资产入选条件：历史数据满260个净值计算日
反转资产入选条件：历史数据满22个净值计算日
"""

import pandas as pd
import numpy as np
import os

# =============================================================================
# 第一部分：动量因子计算函数
# =============================================================================

def calc_mom(prices, n):
    """
    简单时序动量 MOM
    公式：MOM_t(n) = TR_t / TR_{t-n} - 1
    """
    return prices / prices.shift(n) - 1


def calc_macd(prices, win_short, win_long=250):
    """
    双均线动量 MACD
    公式：MACD = k_short - k_long（短期均线 - 长期均线）
    窗口：40, 80, 120, 160
    """
    k_short = prices.rolling(win_short).mean()
    k_long = prices.rolling(win_long).mean()
    macd = k_short - k_long
    return macd


def calc_posi(prices, n):
    """
    收益正负差因子 POSI
    公式：POSI = rpos + rneg（过去n日正收益之和 + 负收益之和）
    """
    returns = prices.pct_change()
    pos_ret = returns.where(returns > 0, 0)
    neg_ret = returns.where(returns < 0, 0)
    return pos_ret.rolling(window=n).sum() + neg_ret.rolling(window=n).sum()


def calc_smom(prices, win, vol_target=0.045, n_annual=260):
    """
    缩放动量因子 SMOM
    公式：SMOM = MOM × (vol_target / (vol × sqrt(n_annual)))
    文档要求使用260个交易日/年
    """
    vol = prices.pct_change().rolling(win).std() * np.sqrt(n_annual)
    mom = prices / prices.shift(win) - 1
    smom = mom * (vol_target / (vol * np.sqrt(n_annual)))
    return smom.replace([np.inf, -np.inf], np.nan)


# =============================================================================
# 第二部分：反转因子计算函数
# =============================================================================

def calc_skew(daily_px, win=10):
    """
    计算反转因子（偏度）
    公式：skewness = daily_px.rolling(win).skew().rank(ascending=True, axis=1)
    返回：偏度排名，ascending=True表示偏度最小的排名第1
    """
    skewness = daily_px.rolling(win).skew().rank(ascending=True, axis=1)
    return skewness


def calc_10day_skewness(prices, date_idx):
    """
    计算截止到date_idx的10日价格偏度
    按照图片逻辑：直接对价格计算偏度，不是收益率
    返回各资产的偏度值
    """
    # 直接对价格计算10日滚动偏度
    skew_series = prices.rolling(10).skew()
    if date_idx < len(skew_series):
        return skew_series.iloc[date_idx]
    else:
        return pd.Series(np.nan, index=prices.columns)


def calc_reversal_scores(prices, date_idx, windows=[10, 22]):
    """
    计算反转因子综合打分（双窗口偏度）
    
    规则：
    - 窗口：10天、22天
    - 偏度从低到高排序（负偏度优先，ascending=True）
    - 打分：排名第k → 得 N-k+1 分（N为有效资产数）
      例如：12个资产，排名第1得12分，排名第2得11分...
    - 综合得分 = 10天得分 + 22天得分
    - 最高可能得分：2N分（每个窗口最高N分）
    
    并列处理：使用平均排名（method='average'）
    
    返回：各资产的综合得分和详细信息DataFrame
    """
    price_data = prices.iloc[:date_idx + 1]
    
    details = {}
    total_scores = pd.Series(0.0, index=prices.columns)
    
    for win in windows:
        if len(price_data) > win:
            # 计算偏度
            skew = price_data.rolling(win).skew().iloc[-1]
            
            # 排名（升序，偏度小的排前面，使用平均排名处理并列）
            rank = skew.rank(ascending=True, method='average')
            
            # 打分：排名第k → 得 N-k+1 分
            # 有效资产数（非NaN的数量）
            valid_count = skew.notna().sum()
            score = (valid_count - rank + 1).fillna(0)
            
            total_scores += score
            
            details[f'Skew_{win}'] = skew
            details[f'Skew_{win}_rank'] = rank
            details[f'Skew_{win}_score'] = score
    
    details['反转综合得分'] = total_scores
    return total_scores, pd.DataFrame(details)


# =============================================================================
# 第三部分：动量综合打分
# =============================================================================

def calc_momentum_scores(prices, date_idx):
    """
    计算动量因子综合打分
    
    规则：
    - 4个因子类型：MOM、MACD、POSI、SMOM
    - MOM/POSI/SMOM窗口：20, 60, 120, 250
    - MACD窗口：40, 80, 120, 160（需要250日数据作为长期基准）
    - 阈值：> -2% 得1分，否则得0分
    - 最高总分：16分（4因子 × 4窗口）
    
    返回：各资产的得分和各因子详细值
    """
    threshold = -0.02
    price_data = prices.iloc[:date_idx + 1]
    
    # 存储详细结果
    details = {}
    scores = pd.Series(0.0, index=prices.columns)
    
    # MOM因子，窗口：20, 60, 120, 250
    mom_windows = [20, 60, 120, 250]
    for n in mom_windows:
        if len(price_data) > n:
            factor = calc_mom(price_data, n).iloc[-1]
            signal = (factor > threshold).astype(int)
            scores += signal.fillna(0)
            details[f'MOM_{n}'] = factor
            details[f'MOM_{n}_signal'] = signal
    
    # MACD因子，窗口：40, 80, 120, 160
    macd_windows = [40, 80, 120, 160]
    if len(price_data) > 250:
        for n in macd_windows:
            factor = calc_macd(price_data, n).iloc[-1]
            signal = (factor > threshold).astype(int)
            scores += signal.fillna(0)
            details[f'MACD_{n}'] = factor
            details[f'MACD_{n}_signal'] = signal
    
    # POSI因子，窗口：20, 60, 120, 250
    posi_windows = [20, 60, 120, 250]
    for n in posi_windows:
        if len(price_data) > n:
            factor = calc_posi(price_data, n).iloc[-1]
            signal = (factor > threshold).astype(int)
            scores += signal.fillna(0)
            details[f'POSI_{n}'] = factor
            details[f'POSI_{n}_signal'] = signal
    
    # SMOM因子，窗口：20, 60, 120, 250
    smom_windows = [20, 60, 120, 250]
    for n in smom_windows:
        if len(price_data) > n:
            factor = calc_smom(price_data, n).iloc[-1]
            signal = (factor > threshold).astype(int)
            scores += signal.fillna(0)
            details[f'SMOM_{n}'] = factor
            details[f'SMOM_{n}_signal'] = signal
    
    details['总分'] = scores
    return scores, pd.DataFrame(details)


# =============================================================================
# 第四部分：资产选择主逻辑
# =============================================================================

def select_assets_for_date(nav, date_idx, calc_date, min_history_momentum=260, min_history_reversal=22, top_momentum=7):
    """
    单次调仓的资产选择
    
    Parameters:
    -----------
    nav : pd.DataFrame - 净值数据
    date_idx : int - 计算日在数据中的索引
    calc_date : datetime - 计算日期
    min_history_momentum : int - 动量因子最小历史数据要求（260天）
    min_history_reversal : int - 反转因子最小历史数据要求（22天）
    top_momentum : int - 动量选择数量（7个）
    
    Returns:
    --------
    result_dict : dict - 包含选择结果和详细信息
    """
    result = {
        '计算日期': calc_date,
        '有效资产': [],
        '动量有效资产': [],
        '反转有效资产': [],
        '动量详情': None,
        '动量排名': None,
        '动量入选': [],
        '反转详情': None,
        '反转排名': None,
        '反转入选': [],
        '最终入选': []
    }
    
    # 第一步：分别确定动量和反转的有效候选池
    momentum_valid_assets = []  # 动量有效资产（需260天历史数据）
    reversal_valid_assets = []  # 反转有效资产（需22天历史数据）
    asset_history_info = {}
    
    for col in nav.columns:
        # 计算该资产到计算日为止的有效数据天数
        asset_data = nav[col].iloc[:date_idx + 1]
        valid_count = asset_data.notna().sum()
        asset_history_info[col] = valid_count
        
        # 动量有效资产：需要260天历史数据
        if valid_count >= min_history_momentum:
            momentum_valid_assets.append(col)
        
        # 反转有效资产：需要22天历史数据
        if valid_count >= min_history_reversal:
            reversal_valid_assets.append(col)
    
    # 有效资产取并集（用于输出和权重计算）
    all_valid_assets = list(set(momentum_valid_assets + reversal_valid_assets))
    
    result['有效资产'] = all_valid_assets
    result['动量有效资产'] = momentum_valid_assets
    result['反转有效资产'] = reversal_valid_assets
    result['资产历史天数'] = asset_history_info
    
    # 第二步：动量模型打分（仅对动量有效资产）
    momentum_selected = []
    mom_ranking_df = pd.DataFrame()
    mom_details = pd.DataFrame()
    
    if len(momentum_valid_assets) > 0:
        price_data_momentum = nav[momentum_valid_assets].iloc[:date_idx + 1]
        mom_scores, mom_details = calc_momentum_scores(price_data_momentum, len(price_data_momentum) - 1)
    
    # 动量排名（降序，分数高的排前面）
    mom_ranking = mom_scores.sort_values(ascending=False)
    mom_ranking_df = pd.DataFrame({
        '资产': mom_ranking.index,
        '动量得分': mom_ranking.values,
        '动量排名': range(1, len(mom_ranking) + 1)
    })
    
    # 动量选前7个，处理并列情况
    # 规则：并列资产的平均排名 <= 7 则都入选，> 7 则都不入选
    # 例如：排名7和8平分，平均排名(7+8)/2=7.5>7，都不入选
    # 例如：排名6、7、8平分，平均排名(6+7+8)/3=7，都入选
    momentum_selected = []
    current_rank = 0  # 当前已处理到的排名
    
    # 按分数分组
    score_groups = mom_ranking.groupby(mom_ranking).groups
    unique_scores = sorted(score_groups.keys(), reverse=True)  # 降序
    
    for score in unique_scores:
        assets_with_score = list(score_groups[score])
        n_assets = len(assets_with_score)
        
        # 计算这组并列资产的排名范围
        start_rank = current_rank + 1
        end_rank = current_rank + n_assets
        
        # 计算平均排名
        avg_rank = (start_rank + end_rank) / 2
        
        if avg_rank <= top_momentum:
            # 平均排名 <= 7，都入选
            momentum_selected.extend(assets_with_score)
        else:
            # 平均排名 > 7，都不入选，结束
            break
        
        current_rank = end_rank
    
    mom_ranking_df['动量入选'] = mom_ranking_df['资产'].isin(momentum_selected)
    
    result['动量详情'] = mom_details
    result['动量排名'] = mom_ranking_df
    result['动量入选'] = momentum_selected
    
    # 第三步：反转模型（双窗口偏度：10天+22天）
    # 使用反转有效资产池（仅需22天历史数据）
    reversal_selected = []
    skew_ranking_df = pd.DataFrame()
    rev_details = pd.DataFrame()
    
    if len(reversal_valid_assets) > 0:
        price_data_reversal = nav[reversal_valid_assets].iloc[:date_idx + 1]
        rev_scores, rev_details = calc_reversal_scores(price_data_reversal, len(price_data_reversal) - 1, windows=[10, 22])
        
        # 按综合得分排名（降序，得分高的排前面）
        rev_ranking = rev_scores.sort_values(ascending=False)
        
        # 构建反转排名详情DataFrame
        skew_ranking_df = pd.DataFrame({
            '资产': rev_ranking.index,
            '反转综合得分': rev_ranking.values,
            '反转排名': range(1, len(rev_ranking) + 1)
        })
        
        # 添加各窗口详细信息
        for asset in skew_ranking_df['资产']:
            idx = rev_details.index[rev_details.index == asset]
            if len(idx) > 0:
                skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '10日偏度'] = rev_details.loc[asset, 'Skew_10'] if 'Skew_10' in rev_details.columns else np.nan
                skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '10日排名'] = rev_details.loc[asset, 'Skew_10_rank'] if 'Skew_10_rank' in rev_details.columns else np.nan
                skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '10日得分'] = rev_details.loc[asset, 'Skew_10_score'] if 'Skew_10_score' in rev_details.columns else 0
                skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '22日偏度'] = rev_details.loc[asset, 'Skew_22'] if 'Skew_22' in rev_details.columns else np.nan
                skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '22日排名'] = rev_details.loc[asset, 'Skew_22_rank'] if 'Skew_22_rank' in rev_details.columns else np.nan
                skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '22日得分'] = rev_details.loc[asset, 'Skew_22_score'] if 'Skew_22_score' in rev_details.columns else 0
        
        # 反转选1个（综合得分最高的）
        # 处理并列情况：如果最高分有多个并列，则都不入选
        max_score = rev_ranking.max()
        top_assets = rev_ranking[rev_ranking == max_score].index.tolist()
        
        if len(top_assets) == 1:
            # 唯一最高分，入选
            reversal_selected = top_assets
        else:
            # 并列最高分，都不入选
            reversal_selected = []
        
        skew_ranking_df['反转入选'] = skew_ranking_df['资产'].isin(reversal_selected)
    
    result['反转详情'] = rev_details
    result['反转排名'] = skew_ranking_df
    result['反转入选'] = reversal_selected
    
    # 第四步：取并集（动量7 + 反转1）
    final_selected = list(set(momentum_selected + reversal_selected))
    result['最终入选'] = final_selected

    # 入选矩阵行 {asset: 0|1|2}，供 step2 calc_weights_for_date 使用
    selection_row = {}
    for asset in nav.columns:
        if asset not in all_valid_assets:
            selection_row[asset] = 0
        elif asset in momentum_selected and asset in reversal_selected:
            selection_row[asset] = 2
        elif asset in momentum_selected or asset in reversal_selected:
            selection_row[asset] = 1
        else:
            selection_row[asset] = 0
    result['入选矩阵_row'] = selection_row

    return result


# =============================================================================
# 第五部分：主程序
# =============================================================================

def main():
    print("=" * 70)
    print("大类资产配置指数策略 - 第一步：资产选择")
    print("=" * 70)
    
    # 加载数据
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(script_dir, 'daily_px.xlsx')
    
    nav = pd.read_excel(data_path)
    date_col = nav.columns[0]
    nav[date_col] = pd.to_datetime(nav[date_col])
    nav.set_index(date_col, inplace=True)
    nav.index.name = '日期'
    
    print(f"\n数据期间: {nav.index[0].date()} 至 {nav.index[-1].date()}")
    print(f"资产数量: {len(nav.columns)}")
    print(f"资产列表: {nav.columns.tolist()}")
    
    # 检查各资产的数据起始日期
    print("\n" + "=" * 70)
    print("各资产数据起始日期：")
    print("=" * 70)
    for col in nav.columns:
        first_valid = nav[col].first_valid_index()
        valid_count = nav[col].notna().sum()
        print(f"  {col}: 起始于 {first_valid.date()}, 共 {valid_count} 天数据")
    
    # 确定月末调仓日
    # 月末的最后一个交易日
    nav['year_month'] = nav.index.to_period('M')
    month_end_dates = nav.groupby('year_month').apply(lambda x: x.index[-1], include_groups=False).tolist()
    nav = nav.drop(columns=['year_month'])
    
    # 指数基日：2014年2月10日
    base_date = pd.Timestamp('2014-02-10')
    
    # 资产选择起始日：2014年1月31日（比基日早一个月，这样基日时已有组合）
    selection_start_date = pd.Timestamp('2014-01-31')
    
    # 筛选资产选择起始日之后的月末日期
    valid_month_ends = [d for d in month_end_dates if d >= selection_start_date]
    
    print(f"\n指数基日: {base_date.date()}")
    print(f"调仓计算日数量: {len(valid_month_ends)}")
    print(f"首个调仓计算日: {valid_month_ends[0].date() if valid_month_ends else 'N/A'}")
    print(f"最后调仓计算日: {valid_month_ends[-1].date() if valid_month_ends else 'N/A'}")
    
    # 存储所有调仓结果
    all_results = []
    momentum_details_list = []
    reversal_details_list = []
    
    # 新增：存储每个调仓日各资产的入选情况矩阵
    asset_selection_matrix = []  # 每行是一个调仓日，每列是一个资产
    
    print("\n" + "=" * 70)
    print("开始逐月计算资产选择...")
    print("=" * 70)
    
    for i, calc_date in enumerate(valid_month_ends):
        date_idx = nav.index.get_loc(calc_date)
        
        # 执行资产选择
        result = select_assets_for_date(nav, date_idx, calc_date)
        
        # 汇总结果
        summary = {
            '序号': i + 1,
            '计算日期': calc_date,
            '有效资产数': len(result['有效资产']),
            '有效资产': ', '.join(result['有效资产']) if result['有效资产'] else '',
            '动量入选': ', '.join(result['动量入选']) if result['动量入选'] else '',
            '反转入选': ', '.join(result['反转入选']) if result['反转入选'] else '',
            '最终入选': ', '.join(result['最终入选']) if result['最终入选'] else '',
            '入选数量': len(result['最终入选'])
        }
        all_results.append(summary)
        
        # 保存动量排名详情
        if result['动量排名'] is not None:
            mom_rank = result['动量排名'].copy()
            mom_rank['计算日期'] = calc_date
            momentum_details_list.append(mom_rank)
        
        # 保存反转排名详情
        if result['反转排名'] is not None:
            rev_rank = result['反转排名'].copy()
            rev_rank['计算日期'] = calc_date
            reversal_details_list.append(rev_rank)
        
        # 新增：构建该调仓日的资产入选矩阵行
        selection_row = {'计算日期': calc_date}
        for asset in nav.columns:
            # 判断资产是否有效（历史数据满260天）
            is_valid = asset in result['有效资产']
            # 判断是否被动量选中
            is_momentum = asset in result['动量入选']
            # 判断是否被反转选中
            is_reversal = asset in result['反转入选']
            
            # 记录详细状态
            if not is_valid:
                selection_row[f'{asset}_状态'] = '无效'
                selection_row[f'{asset}_入选'] = 0
            elif is_momentum and is_reversal:
                selection_row[f'{asset}_状态'] = '动量+反转'
                selection_row[f'{asset}_入选'] = 2  # 两者都入选标记为2
            elif is_momentum:
                selection_row[f'{asset}_状态'] = '动量'
                selection_row[f'{asset}_入选'] = 1
            elif is_reversal:
                selection_row[f'{asset}_状态'] = '反转'
                selection_row[f'{asset}_入选'] = 1
            else:
                selection_row[f'{asset}_状态'] = '未入选'
                selection_row[f'{asset}_入选'] = 0
        
        asset_selection_matrix.append(selection_row)
        
        # 打印进度
        if (i + 1) % 12 == 0 or i == 0:
            print(f"  {calc_date.date()}: 有效资产{len(result['有效资产'])}个, "
                  f"动量选{len(result['动量入选'])}个, "
                  f"反转选{len(result['反转入选'])}个, "
                  f"最终{len(result['最终入选'])}个")
    
    # 创建汇总DataFrame
    summary_df = pd.DataFrame(all_results)
    
    # 创建动量排名详情DataFrame
    if momentum_details_list:
        momentum_all_df = pd.concat(momentum_details_list, ignore_index=True)
        # 重排列顺序
        momentum_all_df = momentum_all_df[['计算日期', '资产', '动量得分', '动量排名', '动量入选']]
    else:
        momentum_all_df = pd.DataFrame()
    
    # 创建反转排名详情DataFrame
    if reversal_details_list:
        reversal_all_df = pd.concat(reversal_details_list, ignore_index=True)
        # 重排列顺序，包含双窗口详情
        cols_order = ['计算日期', '资产', '反转综合得分', '反转排名', 
                      '10日偏度', '10日排名', '10日得分',
                      '22日偏度', '22日排名', '22日得分', '反转入选']
        # 只保留存在的列
        cols_exist = [c for c in cols_order if c in reversal_all_df.columns]
        reversal_all_df = reversal_all_df[cols_exist]
    else:
        reversal_all_df = pd.DataFrame()
    
    # 新增：创建资产入选矩阵DataFrame
    selection_matrix_df = pd.DataFrame(asset_selection_matrix)
    
    # 创建简洁的入选矩阵（只显示0/1）
    simple_matrix = selection_matrix_df[['计算日期']].copy()
    for asset in nav.columns:
        simple_matrix[asset] = selection_matrix_df[f'{asset}_入选']
    
    # 创建状态矩阵（显示入选类型）
    status_matrix = selection_matrix_df[['计算日期']].copy()
    for asset in nav.columns:
        status_matrix[asset] = selection_matrix_df[f'{asset}_状态']
    
    # 保存到Excel
    output_path = os.path.join(script_dir, '资产选择结果.xlsx')
    
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        # Sheet1: 汇总
        summary_df.to_excel(writer, sheet_name='选择汇总', index=False)
        
        # Sheet2: 入选矩阵（0/1）
        simple_matrix.to_excel(writer, sheet_name='入选矩阵', index=False)
        
        # Sheet3: 状态矩阵（显示入选类型）
        status_matrix.to_excel(writer, sheet_name='入选状态矩阵', index=False)
        
        # Sheet4: 动量排名详情
        if not momentum_all_df.empty:
            momentum_all_df.to_excel(writer, sheet_name='动量排名详情', index=False)
        
        # Sheet5: 反转排名详情
        if not reversal_all_df.empty:
            reversal_all_df.to_excel(writer, sheet_name='反转排名详情', index=False)
    
    print("\n" + "=" * 70)
    print(f"结果已保存至: {output_path}")
    print("=" * 70)
    
    # 打印统计信息
    print("\n资产选择统计：")
    print(f"  总调仓次数: {len(all_results)}")
    print(f"  平均入选资产数: {summary_df['入选数量'].mean():.1f}")
    
    # 统计各资产被选中次数
    asset_counts = {}
    for result in all_results:
        for asset in result['最终入选'].split(', '):
            if asset:
                asset_counts[asset] = asset_counts.get(asset, 0) + 1
    
    print("\n各资产被选中次数：")
    for asset, count in sorted(asset_counts.items(), key=lambda x: -x[1]):
        pct = count / len(all_results) * 100
        print(f"  {asset}: {count}次 ({pct:.1f}%)")
    
    print("\n第一步完成！结果已保存至 '资产选择结果.xlsx'。")
    print("下一步：运行 step2_weight_calculation.py 进行权重计算。")


if __name__ == "__main__":
    main()
