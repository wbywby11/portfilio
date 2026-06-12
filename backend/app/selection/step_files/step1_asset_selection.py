# -*- coding: utf-8 -*-
"""
大类资产配置指数策略 - 第一步：资产选择（portfilio-end 副本）

与 动量策略相关资料/step1_asset_selection.py 完全一致，增加：
- reversal_tie_all_select 参数（默认 False，与参考一致：并列都不入选）
- 入选矩阵_row: 返回 {asset: 0|1|2} 供 step2 使用
"""

import pandas as pd
import numpy as np
import os

try:
    from loguru import logger as _log
except ImportError:
    import logging
    _log = logging.getLogger(__name__)

# =============================================================================
# 第一部分：动量因子计算函数
# =============================================================================

def calc_mom(prices, n):
    """MOM_t(n) = TR_t / TR_{t-n} - 1"""
    return prices / prices.shift(n) - 1


def calc_macd(prices, win_short, win_long=250):
    """MACD = k_short - k_long"""
    k_short = prices.rolling(win_short).mean()
    k_long = prices.rolling(win_long).mean()
    macd = k_short - k_long
    return macd


def calc_posi(prices, n):
    """POSI = rpos + rneg"""
    returns = prices.pct_change()
    pos_ret = returns.where(returns > 0, 0)
    neg_ret = returns.where(returns < 0, 0)
    return pos_ret.rolling(window=n).sum() + neg_ret.rolling(window=n).sum()


def calc_smom(prices, win, vol_target=0.045, n_annual=260):
    """SMOM = MOM × (vol_target / (vol × sqrt(n_annual)))"""
    vol = prices.pct_change().rolling(win).std() * np.sqrt(n_annual)
    mom = prices / prices.shift(win) - 1
    smom = mom * (vol_target / (vol * np.sqrt(n_annual)))
    return smom.replace([np.inf, -np.inf], np.nan)


# =============================================================================
# 第二部分：反转因子计算函数
# =============================================================================

def calc_skew(daily_px, win=10):
    """偏度排名，ascending=True 表示偏度最小的排名第1"""
    skewness = daily_px.rolling(win).skew().rank(ascending=True, axis=1)
    return skewness


def calc_10day_skewness(prices, date_idx):
    """计算截止到 date_idx 的10日价格偏度"""
    skew_series = prices.rolling(10).skew()
    if date_idx < len(skew_series):
        return skew_series.iloc[date_idx]
    return pd.Series(np.nan, index=prices.columns)


def calc_reversal_scores(prices, date_idx, windows=[10, 22]):
    """反转因子综合打分（双窗口偏度）"""
    price_data = prices.iloc[:date_idx + 1]
    details = {}
    total_scores = pd.Series(0.0, index=prices.columns)

    for win in windows:
        if len(price_data) > win:
            skew = price_data.rolling(win).skew().iloc[-1]
            rank = skew.rank(ascending=True, method='average')
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
    """动量因子综合打分"""
    threshold = -0.02
    price_data = prices.iloc[:date_idx + 1]
    details = {}
    scores = pd.Series(0.0, index=prices.columns)

    mom_windows = [20, 60, 120, 250]
    for n in mom_windows:
        if len(price_data) > n:
            factor = calc_mom(price_data, n).iloc[-1]
            signal = (factor > threshold).astype(int)
            scores += signal.fillna(0)
            details[f'MOM_{n}'] = factor
            details[f'MOM_{n}_signal'] = signal

    macd_windows = [40, 80, 120, 160]
    if len(price_data) > 250:
        for n in macd_windows:
            factor = calc_macd(price_data, n).iloc[-1]
            signal = (factor > threshold).astype(int)
            scores += signal.fillna(0)
            details[f'MACD_{n}'] = factor
            details[f'MACD_{n}_signal'] = signal

    posi_windows = [20, 60, 120, 250]
    for n in posi_windows:
        if len(price_data) > n:
            factor = calc_posi(price_data, n).iloc[-1]
            signal = (factor > threshold).astype(int)
            scores += signal.fillna(0)
            details[f'POSI_{n}'] = factor
            details[f'POSI_{n}_signal'] = signal

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

def select_assets_for_date(nav, date_idx, calc_date, min_history=260, top_momentum=7, reversal_tie_all_select=False):
    """
    单次调仓的资产选择（与 动量策略相关资料/step1_asset_selection.py 完全一致）

    Parameters:
    -----------
    nav : pd.DataFrame - 净值数据
    date_idx : int - 计算日在数据中的索引
    calc_date : datetime - 计算日期
    min_history : int - 最小历史数据要求（260天）
    top_momentum : int - 动量选择数量（7个）
    reversal_tie_all_select : bool - 反转平局时全部入选（默认 False，与参考一致：并列都不入选）

    Returns:
    --------
    result_dict : dict - 包含选择结果和详细信息，含 入选矩阵_row {asset: 0|1|2}
    """
    result = {
        '计算日期': calc_date,
        '有效资产': [],
        '动量详情': None,
        '动量排名': None,
        '动量入选': [],
        '反转详情': None,
        '反转排名': None,
        '反转入选': [],
        '最终入选': [],
        '入选矩阵_row': {},
    }

    # 第一步：确定有效候选池（历史数据满260天）
    valid_assets = []
    asset_history_info = {}

    for col in nav.columns:
        asset_data = nav[col].iloc[:date_idx + 1]
        valid_count = asset_data.notna().sum()
        asset_history_info[col] = valid_count
        if valid_count >= min_history:
            valid_assets.append(col)
        else:
            # 260日内缺少数据时，打印具体信息（区分：整体数据不足 vs 本资产有缺失）
            n_total = len(asset_data)
            first_valid = asset_data.dropna()
            first_valid_date = first_valid.index[0] if len(first_valid) > 0 else None
            global_start = asset_data.index[0] if n_total > 0 else None
            global_end = asset_data.index[-1] if n_total > 0 else None
            if n_total < min_history:
                first_valid_str = first_valid_date.strftime("%Y-%m-%d") if first_valid_date is not None else "无"
                global_start_str = global_start.strftime("%Y-%m-%d") if global_start is not None else "N/A"
                global_end_str = global_end.strftime("%Y-%m-%d") if global_end is not None else "N/A"
                _log.warning(
                    f"[资产选择] {col} 历史不足{min_history}天: 本资产有效{int(valid_count)}天(首有效日{first_valid_str}), "
                    f"整体数据范围 {global_start_str}~{global_end_str} 共{n_total}行 (需{min_history})。"
                    f"若沪深300等应有更早数据，请检查回测lookback_days或数据库历史覆盖"
                )
            # else: 近260日内有缺失日期的资产已排除，不输出日志

    result['有效资产'] = valid_assets
    result['资产历史天数'] = asset_history_info

    excluded = [a for a in nav.columns if a not in valid_assets]
    # 数据不足资产已排除，不输出日志

    if len(valid_assets) == 0:
        calc_str = calc_date.strftime("%Y-%m-%d") if hasattr(calc_date, "strftime") else str(calc_date)
        hist_str = ", ".join(f"{a}={asset_history_info.get(a, 0)}天" for a in nav.columns)
        _log.warning(
            f"[资产选择] 计算日 {calc_str} 无有效资产(需{min_history}天)，权重全为0。各资产历史天数: {hist_str}"
        )
        return result

    price_data = nav[valid_assets].iloc[:date_idx + 1]

    # 第二步：动量模型打分
    mom_scores, mom_details = calc_momentum_scores(price_data, len(price_data) - 1)
    mom_ranking = mom_scores.sort_values(ascending=False)
    mom_ranking_df = pd.DataFrame({
        '资产': mom_ranking.index,
        '动量得分': mom_ranking.values,
        '动量排名': range(1, len(mom_ranking) + 1)
    })

    # 动量选前7个，并列按平均排名
    momentum_selected = []
    current_rank = 0
    score_groups = mom_ranking.groupby(mom_ranking).groups
    unique_scores = sorted(score_groups.keys(), reverse=True)

    for score in unique_scores:
        assets_with_score = list(score_groups[score])
        n_assets = len(assets_with_score)
        start_rank = current_rank + 1
        end_rank = current_rank + n_assets
        avg_rank = (start_rank + end_rank) / 2
        if avg_rank <= top_momentum:
            momentum_selected.extend(assets_with_score)
        else:
            break
        current_rank = end_rank

    mom_ranking_df['动量入选'] = mom_ranking_df['资产'].isin(momentum_selected)
    result['动量详情'] = mom_details
    result['动量排名'] = mom_ranking_df
    result['动量入选'] = momentum_selected

    # 第三步：反转模型（双窗口偏度：10天+22天）
    rev_scores, rev_details = calc_reversal_scores(price_data, len(price_data) - 1, windows=[10, 22])
    rev_ranking = rev_scores.sort_values(ascending=False)
    skew_ranking_df = pd.DataFrame({
        '资产': rev_ranking.index,
        '反转综合得分': rev_ranking.values,
        '反转排名': range(1, len(rev_ranking) + 1)
    })

    for asset in skew_ranking_df['资产']:
        idx = rev_details.index[rev_details.index == asset]
        if len(idx) > 0:
            skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '10日偏度'] = rev_details.loc[asset, 'Skew_10'] if 'Skew_10' in rev_details.columns else np.nan
            skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '10日排名'] = rev_details.loc[asset, 'Skew_10_rank'] if 'Skew_10_rank' in rev_details.columns else np.nan
            skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '10日得分'] = rev_details.loc[asset, 'Skew_10_score'] if 'Skew_10_score' in rev_details.columns else 0
            skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '22日偏度'] = rev_details.loc[asset, 'Skew_22'] if 'Skew_22' in rev_details.columns else np.nan
            skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '22日排名'] = rev_details.loc[asset, 'Skew_22_rank'] if 'Skew_22_rank' in rev_details.columns else np.nan
            skew_ranking_df.loc[skew_ranking_df['资产'] == asset, '22日得分'] = rev_details.loc[asset, 'Skew_22_score'] if 'Skew_22_score' in rev_details.columns else 0

    # 反转选1个（与参考一致：并列最高分都不入选）
    max_score = rev_ranking.max()
    top_assets = rev_ranking[rev_ranking == max_score].index.tolist()
    if reversal_tie_all_select:
        reversal_selected = top_assets
    else:
        reversal_selected = top_assets if len(top_assets) == 1 else []

    skew_ranking_df['反转入选'] = skew_ranking_df['资产'].isin(reversal_selected)
    result['反转详情'] = rev_details
    result['反转排名'] = skew_ranking_df
    result['反转入选'] = reversal_selected

    # 第四步：取并集（动量7 + 反转1）
    final_selected = list(set(momentum_selected + reversal_selected))
    result['最终入选'] = final_selected

    # 入选矩阵行 {asset: 0|1|2}，供 step2 使用
    for asset in nav.columns:
        if asset not in valid_assets:
            result['入选矩阵_row'][asset] = 0
        elif asset in momentum_selected and asset in reversal_selected:
            result['入选矩阵_row'][asset] = 2
        elif asset in momentum_selected or asset in reversal_selected:
            result['入选矩阵_row'][asset] = 1
        else:
            result['入选矩阵_row'][asset] = 0

    return result


# =============================================================================
# 第五部分：主程序（独立运行用）
# =============================================================================

def main():
    print("=" * 70)
    print("大类资产配置指数策略 - 第一步：资产选择")
    print("=" * 70)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(script_dir, 'daily_px.xlsx')
    if not os.path.exists(data_path):
        print(f"数据文件不存在: {data_path}")
        return
    nav = pd.read_excel(data_path)
    date_col = nav.columns[0]
    nav[date_col] = pd.to_datetime(nav[date_col])
    nav.set_index(date_col, inplace=True)
    nav.index.name = '日期'
    print(f"\n数据期间: {nav.index[0].date()} 至 {nav.index[-1].date()}")
    print(f"资产数量: {len(nav.columns)}")
    print("\n第一步完成（独立运行需 daily_px.xlsx 在同目录）。")


if __name__ == "__main__":
    main()
