"""动量因子计算公式.

基于文档中的SHARP动量计算方法：
- 计算多窗口夏普动量（22/65/260天）
- 排序打分
- 综合评分选择资产
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_sharp_momentum(
    prices: pd.Series,
    window: int,
    annualization_factor: int = 260
) -> float:
    """计算单个资产的SHARP动量因子.
    
    根据文档公式：
    SHARP_{t,n} = [累计收益率] / [年化波动率]
    
    SHARP_{t,n}^c = (TR_t/TR_{t-n} - 1) / sqrt((260/(n-1)) * Σ(偏差²))
    
    Args:
        prices: 资产价格序列
        window: 时间窗口（交易日数，如22/65/260）
        annualization_factor: 年化因子（默认260交易日）
    
    Returns:
        float: SHARP动量值
    """
    if len(prices) < window + 1:
        return 0.0
    
    # 取最近window+1个交易日（需要计算window天的收益率）
    prices_window = prices.tail(window + 1)
    
    # 1. 计算累计收益率（分子）
    # 修复：确保获取标量值，避免数组类型
    price_end = prices_window.iloc[-1]
    price_start = prices_window.iloc[0]
    
    # 如果返回的是Series或数组，取第一个值
    if isinstance(price_end, pd.Series):
        price_end = price_end.iloc[0] if len(price_end) > 0 else 0.0
    elif isinstance(price_end, (np.ndarray, list)):
        price_end = float(price_end[0]) if len(price_end) > 0 else 0.0
    else:
        price_end = float(price_end)
    
    if isinstance(price_start, pd.Series):
        price_start = price_start.iloc[0] if len(price_start) > 0 else 0.0
    elif isinstance(price_start, (np.ndarray, list)):
        price_start = float(price_start[0]) if len(price_start) > 0 else 0.0
    else:
        price_start = float(price_start)
    
    if price_start == 0:
        return 0.0
    
    period_return = (price_end / price_start) - 1
    
    # 2. 计算日收益率序列
    returns = prices_window.pct_change().dropna()
    
    if len(returns) < 2:
        return 0.0
    
    # 3. 计算平均日收益率
    mean_return = returns.mean()
    
    # 确保mean_return是标量
    if isinstance(mean_return, pd.Series):
        mean_return = mean_return.iloc[0] if len(mean_return) > 0 else 0.0
    elif isinstance(mean_return, (np.ndarray, list)):
        mean_return = float(mean_return[0]) if len(mean_return) > 0 else 0.0
    else:
        mean_return = float(mean_return)
    
    # 4. 计算收益率偏差的平方和
    deviations = returns - mean_return
    variance = (deviations ** 2).sum() / (len(returns) - 1)
    
    # 确保variance是标量
    if isinstance(variance, pd.Series):
        variance = variance.iloc[0] if len(variance) > 0 else 0.0
    elif isinstance(variance, (np.ndarray, list)):
        variance = float(variance[0]) if len(variance) > 0 else 0.0
    else:
        variance = float(variance)
    
    # 5. 年化波动率（分母）
    # sqrt((260/(n-1)) * 方差)
    annual_volatility = np.sqrt((annualization_factor / (len(returns) - 1)) * variance)
    
    # 确保annual_volatility是标量
    if isinstance(annual_volatility, (np.ndarray, list)):
        annual_volatility = float(annual_volatility[0]) if len(annual_volatility) > 0 else 0.0
    else:
        annual_volatility = float(annual_volatility)
    
    # 6. 计算SHARP动量
    if annual_volatility > 0:
        sharp = period_return / annual_volatility
    else:
        sharp = 0.0
    
    return float(sharp)


def compute_momentum_scores(
    prices: pd.DataFrame,
    windows: list[int] = [22, 65, 260],
    min_history_days: int = 260,
    annualization_factor: int = 260
) -> pd.DataFrame:
    """计算所有资产的动量得分.
    
    步骤：
    1. 筛选有效资产（历史数据≥min_history_days）
    2. 计算每个资产在各窗口的SHARP动量
    3. 对每个窗口的动量进行排序打分
    4. 计算综合得分
    
    Args:
        prices: 价格矩阵（index: 日期，columns: 资产代码）
        windows: 动量窗口列表（默认[22, 65, 260]对应1月/3月/1年）
        min_history_days: 最小历史数据要求（默认260天）
        annualization_factor: 年化因子
    
    Returns:
        pd.DataFrame: 动量得分表
            columns: [SHARP_22, SHARP_65, SHARP_260, Score_22, Score_65, Score_260, TotalScore]
            index: 资产代码
            按TotalScore降序排列
    """
    # 1. 筛选有效资产（数据不足时自动放宽要求，避免与 RiskBudgetTargetVolStrategy 等联用时报错）
    max_asset_days = 0
    for asset in prices.columns:
        n = len(prices[asset].dropna())
        if n > max_asset_days:
            max_asset_days = n
    effective_min = min_history_days
    if max_asset_days > 0 and max_asset_days < min_history_days:
        # 实际数据不足 min_history_days 时，降至至少满足最长窗口（260）或实际最大天数-10，且不少于最短窗口 22
        min_window = min(windows)   # 22
        max_window = max(windows)   # 260
        effective_min = max(min_window, max_asset_days - 10)
        effective_min = min(effective_min, max_asset_days)
    valid_assets = []
    for asset in prices.columns:
        asset_prices = prices[asset].dropna()
        if len(asset_prices) >= effective_min:
            valid_assets.append(asset)
    if not valid_assets:
        raise ValueError(
            f"没有资产满足最小历史数据要求（{effective_min}天，原始要求{min_history_days}天）"
        )
    
    # 2. 计算每个资产的SHARP动量和简单动量
    momentum_data = []
    
    for asset in valid_assets:
        asset_prices = prices[asset].dropna()
        row = {"asset": asset}
        
        # 计算各窗口的SHARP动量
        for window in windows:
            sharp = compute_sharp_momentum(
                asset_prices, 
                window, 
                annualization_factor
            )
            row[f"SHARP_{window}"] = sharp
        
        # 计算22日简单动量（用于tie-breaking和第4个因子打分）
        if len(asset_prices) >= 22:
            # 修复：确保获取标量值
            price_end = asset_prices.iloc[-1]
            price_start = asset_prices.iloc[-22]
            
            if isinstance(price_end, pd.Series):
                price_end = price_end.iloc[0] if len(price_end) > 0 else 0.0
            elif isinstance(price_end, (np.ndarray, list)):
                price_end = float(price_end[0]) if len(price_end) > 0 else 0.0
            else:
                price_end = float(price_end)
            
            if isinstance(price_start, pd.Series):
                price_start = price_start.iloc[0] if len(price_start) > 0 else 0.0
            elif isinstance(price_start, (np.ndarray, list)):
                price_start = float(price_start[0]) if len(price_start) > 0 else 0.0
            else:
                price_start = float(price_start)
            
            if price_start > 0:
                simple_mom_22 = (price_end / price_start) - 1
            else:
                simple_mom_22 = 0.0
            row["MOM_22"] = simple_mom_22
        else:
            row["MOM_22"] = 0.0
        
        momentum_data.append(row)
    
    momentum_df = pd.DataFrame(momentum_data).set_index("asset")
    
    # 3. 对每个窗口进行排序打分
    # 排名第1得分为N（资产数量），排名最后得分为1
    n_assets = len(valid_assets)
    
    for window in windows:
        col_name = f"SHARP_{window}"
        # 降序排名：动量值越高排名越靠前
        momentum_df[f"Rank_{window}"] = momentum_df[col_name].rank(
            ascending=False,
            method='min'  # 并列时取最小排名
        )
        # 转换为得分：第1名得N分，第N名得1分
        momentum_df[f"Score_{window}"] = n_assets - momentum_df[f"Rank_{window}"] + 1
    
    # 对22日简单动量也进行排序打分（第4个因子）
    if "MOM_22" in momentum_df.columns:
        momentum_df["Rank_MOM_22"] = momentum_df["MOM_22"].rank(
            ascending=False,
            method='min'
        )
        momentum_df["Score_MOM_22"] = n_assets - momentum_df["Rank_MOM_22"] + 1
    
    # 4. 计算综合得分（4个因子得分相加：3个SHARP + 1个简单动量）
    score_cols = [f"Score_{w}" for w in windows]
    if "Score_MOM_22" in momentum_df.columns:
        score_cols.append("Score_MOM_22")
    momentum_df["TotalScore"] = momentum_df[score_cols].sum(axis=1)
    
    # 5. 按综合得分降序排列
    momentum_df = momentum_df.sort_values("TotalScore", ascending=False)
    
    return momentum_df


def rank_and_select_assets(
    prices: pd.DataFrame,
    n_assets: int,
    windows: list[int] = [22, 65, 260],
    min_history_days: int = 260,
    tie_break_window: int = 22
) -> tuple[list[str], pd.DataFrame]:
    """根据动量排序选择TopN资产.
    
    Args:
        prices: 价格矩阵
        n_assets: 选择资产数量
        windows: 动量窗口列表
        min_history_days: 最小历史数据要求
        tie_break_window: 并列时的决胜窗口（默认22天）
    
    Returns:
        tuple:
            - list[str]: 选中的资产代码列表
            - pd.DataFrame: 完整排名表
    """
    # 1. 计算动量得分
    momentum_df = compute_momentum_scores(
        prices, 
        windows, 
        min_history_days
    )
    
    # 2. 处理并列情况（Tie-Breaking）
    # 如果综合得分相同，优先选择短期动量（tie_break_window）更高的资产
    if tie_break_window in windows:
        tie_break_col = f"SHARP_{tie_break_window}"
    else:
        # 如果tie_break_window不在windows中，计算它
        tie_break_scores = []
        for asset in momentum_df.index:
            asset_prices = prices[asset].dropna()
            sharp = compute_sharp_momentum(asset_prices, tie_break_window)
            tie_break_scores.append(sharp)
        momentum_df[f"SHARP_{tie_break_window}_tiebreak"] = tie_break_scores
        tie_break_col = f"SHARP_{tie_break_window}_tiebreak"
    
    # 按综合得分降序，相同时按tie_break_col降序
    momentum_df = momentum_df.sort_values(
        ["TotalScore", tie_break_col],
        ascending=[False, False]
    )
    
    # 3. 选择TopN资产（保留平分资产）
    # 如果第N名和第N+1名得分相同，则都选入
    if len(momentum_df) <= n_assets:
        # 资产总数不足N个，全选
        selected_assets = momentum_df.index.tolist()
    else:
        # 找到第N个资产的得分
        # 修复：确保获取标量值
        nth_score_value = momentum_df.iloc[n_assets - 1]['TotalScore']
        if isinstance(nth_score_value, pd.Series):
            nth_score = float(nth_score_value.iloc[0]) if len(nth_score_value) > 0 else 0.0
        elif isinstance(nth_score_value, (np.ndarray, list)):
            nth_score = float(nth_score_value[0]) if len(nth_score_value) > 0 else 0.0
        else:
            nth_score = float(nth_score_value)
        
        # 选择所有得分 >= 第N名得分的资产
        selected_assets = momentum_df[
            momentum_df['TotalScore'] >= nth_score
        ].index.tolist()
    
    return selected_assets, momentum_df
