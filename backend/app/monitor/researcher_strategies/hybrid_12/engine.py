# -*- coding: utf-8 -*-
"""混合动量12独立回测引擎

忠实复现策略原型 step1_asset_selection + step2_weight_calculation + step3_backtest_fx_v4 的完整计算逻辑。
本模块自包含，不依赖 CompositionPipeline / PortfolioTracker / SignalDetector 等系统组件。

输入：prices_df（列=中文资产名或资产代码）、fx_df（列=币种）、trade_dates_list
输出：回测结果字典
"""

from __future__ import annotations

import warnings
warnings.filterwarnings('ignore', category=FutureWarning)

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# =============================================================================
# 配置常量（与原型完全一致）
# =============================================================================

BASE_DATE = pd.Timestamp('2014-02-10')
BASE_VALUE = 1000.0
RISK_FREE_RATE = 0.02

TARGET_VOL = 0.05
MAX_LEVERAGE = 4.0
VOL_WINDOWS = [22, 65, 130]
ANNUALIZE_FACTOR = np.sqrt(260)
MONITOR_START_DAYS = 60
VOL_TRIGGER_THRESHOLD = 0.06

# 动量选择参数
N_MOMENTUM = 7
N_REVERSAL = 1
MOM_WINDOWS = [20, 60, 120, 250]
MACD_WINDOWS = [40, 80, 120, 160]
MOM_THRESHOLD = -0.02
MIN_HISTORY_MOMENTUM = 260
MIN_HISTORY_REVERSAL = 22
REVERSAL_WINDOWS = [10, 22]

SKIP_EXCLUDED_DATES = {
    pd.Timestamp("2015-01-01"),
    pd.Timestamp("2015-01-02"),
    pd.Timestamp("2015-01-05"),
}

# 资产代码 ↔ 中文名映射
CODE_TO_NAME = {
    "000300.SH": "沪深300", "SZ399006": "创业板指", "ZZ000001": "红利低波",
    "HSTECH": "恒生科技", "SPX": "标普500", "GDAXI": "德国DAX",
    "ZQGZ10": "中国10年国债", "ZQGZ2": "中国2年国债",
    "B00Y": "布伦特原油", "GLD": "黄金", "IRON": "铁矿石", "YSJS": "中国有色金属",
}
NAME_TO_CODE = {v: k for k, v in CODE_TO_NAME.items()}

# 单资产权重上限
WEIGHT_CAPS = {
    '沪深300': 0.10, '创业板指': 0.10, '红利低波': 0.10,
    '恒生科技': 0.10, '标普500': 0.15, '德国DAX': 0.10,
    '中国10年国债': 0.60, '中国2年国债': 0.90,
    '布伦特原油': 0.10, '黄金': 0.10, '铁矿石': 0.10, '中国有色金属': 0.10,
}

# 费率
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

# 资产计价货币
ASSET_CURRENCY = {
    '沪深300': 'CNH', '创业板指': 'CNH', '红利低波': 'CNH', '恒生科技': 'HKD',
    '标普500': 'USD', '德国DAX': 'EUR', '中国10年国债': 'CNH', '中国2年国债': 'CNH',
    '布伦特原油': 'USD', '黄金': 'CNH', '铁矿石': 'CNH', '中国有色金属': 'CNH',
}


# =============================================================================
# Step1: 动量因子计算
# =============================================================================

def _calc_mom(prices: pd.DataFrame, n: int) -> pd.DataFrame:
    """简单时序动量 MOM = P_t / P_{t-n} - 1"""
    return prices / prices.shift(n) - 1


def _calc_macd(prices: pd.DataFrame, win_short: int, win_long: int = 250) -> pd.DataFrame:
    """双均线动量 MACD = MA_short - MA_long"""
    return prices.rolling(win_short).mean() - prices.rolling(win_long).mean()


def _calc_posi(prices: pd.DataFrame, n: int) -> pd.DataFrame:
    """收益正负差因子 POSI = sum(pos_ret, n) + sum(neg_ret, n)"""
    returns = prices.pct_change(fill_method=None)
    pos_ret = returns.where(returns > 0, 0)
    neg_ret = returns.where(returns < 0, 0)
    return pos_ret.rolling(window=n).sum() + neg_ret.rolling(window=n).sum()


def _calc_smom(prices: pd.DataFrame, win: int, vol_target: float = 0.045, n_annual: int = 260) -> pd.DataFrame:
    """缩放动量因子 SMOM = MOM * (vol_target / (vol * sqrt(n_annual)))"""
    vol = prices.pct_change(fill_method=None).rolling(win).std() * np.sqrt(n_annual)
    mom = prices / prices.shift(win) - 1
    smom = mom * (vol_target / (vol * np.sqrt(n_annual)))
    return smom.replace([np.inf, -np.inf], np.nan)


def _calc_momentum_scores(prices: pd.DataFrame, date_idx: int) -> pd.Series:
    """动量因子综合打分（4因子x4窗口，满分16分），阈值 > -2% 得1分"""
    price_data = prices.iloc[:date_idx + 1]
    scores = pd.Series(0.0, index=prices.columns)

    for n in MOM_WINDOWS:
        if len(price_data) > n:
            factor = _calc_mom(price_data, n).iloc[-1]
            scores += (factor > MOM_THRESHOLD).astype(int).fillna(0)

    if len(price_data) > 250:
        for n in MACD_WINDOWS:
            factor = _calc_macd(price_data, n).iloc[-1]
            scores += (factor > MOM_THRESHOLD).astype(int).fillna(0)

    for n in MOM_WINDOWS:
        if len(price_data) > n:
            factor = _calc_posi(price_data, n).iloc[-1]
            scores += (factor > MOM_THRESHOLD).astype(int).fillna(0)

    for n in MOM_WINDOWS:
        if len(price_data) > n:
            factor = _calc_smom(price_data, n).iloc[-1]
            scores += (factor > MOM_THRESHOLD).astype(int).fillna(0)

    return scores


# =============================================================================
# Step1: 反转因子计算
# =============================================================================

def _calc_reversal_scores(prices: pd.DataFrame, date_idx: int, windows=None) -> pd.Series:
    """反转因子综合打分（双窗口偏度），负偏度优先，排名第k得N-k+1分"""
    if windows is None:
        windows = REVERSAL_WINDOWS
    price_data = prices.iloc[:date_idx + 1]
    total_scores = pd.Series(0.0, index=prices.columns)

    for win in windows:
        if len(price_data) > win:
            skew = price_data.rolling(win).skew().iloc[-1]
            rank = skew.rank(ascending=True, method='average')
            valid_count = skew.notna().sum()
            score = (valid_count - rank + 1).fillna(0)
            total_scores += score

    return total_scores


# =============================================================================
# Step1: 资产选择主逻辑
# =============================================================================

def _select_assets(nav: pd.DataFrame, date_idx: int) -> Dict[str, int]:
    """单次调仓的资产选择：动量选7 + 反转选1。返回 {资产名: 0/1/2}"""
    all_assets = nav.columns.tolist()
    selection_status = {a: 0 for a in all_assets}

    momentum_valid = []
    reversal_valid = []
    for col in all_assets:
        valid_count = nav[col].iloc[:date_idx + 1].notna().sum()
        if valid_count >= MIN_HISTORY_MOMENTUM:
            momentum_valid.append(col)
        if valid_count >= MIN_HISTORY_REVERSAL:
            reversal_valid.append(col)

    # 动量选择（选7个，并列处理）
    momentum_selected = []
    if momentum_valid:
        price_data = nav[momentum_valid].iloc[:date_idx + 1]
        mom_scores = _calc_momentum_scores(price_data, len(price_data) - 1)
        mom_ranking = mom_scores.sort_values(ascending=False)

        current_rank = 0
        score_groups = mom_ranking.groupby(mom_ranking).groups
        unique_scores = sorted(score_groups.keys(), reverse=True)

        for score in unique_scores:
            assets_with_score = list(score_groups[score])
            n_assets = len(assets_with_score)
            start_rank = current_rank + 1
            end_rank = current_rank + n_assets
            avg_rank = (start_rank + end_rank) / 2
            if avg_rank <= N_MOMENTUM:
                momentum_selected.extend(assets_with_score)
            else:
                break
            current_rank = end_rank

    # 反转选择（选1个，唯一最高分入选）
    reversal_selected = []
    if reversal_valid:
        price_data = nav[reversal_valid].iloc[:date_idx + 1]
        rev_scores = _calc_reversal_scores(price_data, len(price_data) - 1)
        rev_ranking = rev_scores.sort_values(ascending=False)
        max_score = rev_ranking.max()
        top_assets = rev_ranking[rev_ranking == max_score].index.tolist()
        if len(top_assets) == 1:
            reversal_selected = top_assets

    # 合并状态
    for a in momentum_selected:
        selection_status[a] = 1
    for a in reversal_selected:
        if selection_status[a] == 1:
            selection_status[a] = 2
        else:
            selection_status[a] = 1

    return selection_status


# =============================================================================
# Step2: 权重计算
# =============================================================================

def _calc_asset_volatility(prices: pd.DataFrame, date_idx: int, windows=None) -> pd.Series:
    """资产波动率：取22/65/130日年化波动率的最大值"""
    if windows is None:
        windows = VOL_WINDOWS
    returns = prices.pct_change(fill_method=None)
    vols = {}
    for asset in prices.columns:
        asset_vols = []
        for w in windows:
            if date_idx >= w:
                ret_window = returns[asset].iloc[date_idx - w + 1:date_idx + 1]
                vol = ret_window.std() * ANNUALIZE_FACTOR
                if not np.isnan(vol):
                    asset_vols.append(vol)
        vols[asset] = max(asset_vols) if asset_vols else np.nan
    return pd.Series(vols)


def _calc_portfolio_volatility(prices: pd.DataFrame, weights: pd.Series, date_idx: int, windows=None) -> float:
    """组合波动率：权重加权组合收益率，取22/65/130日年化波动率最大值"""
    if windows is None:
        windows = VOL_WINDOWS
    returns = prices.pct_change(fill_method=None)
    valid_assets = [a for a in weights.index if weights[a] > 0 and a in returns.columns]
    if not valid_assets:
        return 0.0
    port_vols = []
    for w in windows:
        if date_idx >= w:
            port_returns = pd.Series(0.0, index=returns.index)
            for asset in valid_assets:
                port_returns += weights[asset] * returns[asset].fillna(0)
            ret_window = port_returns.iloc[date_idx - w + 1:date_idx + 1]
            vol = ret_window.std() * ANNUALIZE_FACTOR
            if not np.isnan(vol):
                port_vols.append(vol)
    return max(port_vols) if port_vols else 0.0


def _calc_weights_for_date(
    nav: pd.DataFrame, date_idx: int, selection_status: Dict[str, int], all_assets: List[str]
) -> Dict[str, float]:
    """计算单个调仓日的最终权重（风险预算 -> 初始权重 -> 缩放 -> 截断）"""
    # 风险预算（tag_based）：动量或反转=1/8，动量+反转=2/8
    budgets = pd.Series({
        a: (2.0 / 8 if selection_status.get(a, 0) == 2 else
            1.0 / 8 if selection_status.get(a, 0) == 1 else 0.0)
        for a in all_assets
    })

    asset_vols = _calc_asset_volatility(nav, date_idx)

    # 初始权重：w = b * (target_vol / sigma)
    initial_weights = pd.Series(0.0, index=all_assets)
    for asset in all_assets:
        b = budgets[asset]
        sigma = asset_vols.get(asset, np.nan)
        if b > 0 and sigma > 0 and not np.isnan(sigma):
            initial_weights[asset] = b * (TARGET_VOL / sigma)

    port_vol = _calc_portfolio_volatility(nav, initial_weights, date_idx)

    total_weight = initial_weights.sum()
    if total_weight <= 0:
        return {a: 0.0 for a in all_assets}
    scale_vol = TARGET_VOL / port_vol if port_vol > 0 else 1.0
    scale_leverage = MAX_LEVERAGE / total_weight
    scale = min(scale_vol, scale_leverage)
    scaled_weights = initial_weights * scale

    # 权重上限截断（不做再分配）
    final_weights = scaled_weights.copy()
    for asset in final_weights.index:
        cap = WEIGHT_CAPS.get(asset, 1.0)
        if final_weights[asset] > cap:
            final_weights[asset] = cap

    return final_weights.to_dict()


# =============================================================================
# Step3: 辅助函数
# =============================================================================

def _get_fx_rate(fx_df: pd.DataFrame, date: pd.Timestamp, currency: str) -> float:
    if currency == 'CNH':
        return 1.0
    if currency not in fx_df.columns:
        return 1.0
    if date in fx_df.index:
        rate = fx_df.loc[date, currency]
        if not np.isnan(rate):
            return float(rate)
    valid_dates = fx_df.index[fx_df.index <= date]
    for d in reversed(valid_dates):
        rate = fx_df.loc[d, currency]
        if not np.isnan(rate):
            return float(rate)
    return 1.0


def _get_fx_rates(fx_df: pd.DataFrame, date: pd.Timestamp, assets: List[str]) -> Dict[str, float]:
    return {asset: _get_fx_rate(fx_df, date, ASSET_CURRENCY.get(asset, 'CNH')) for asset in assets}


def _build_monthly_rebalance_map(
    weights_by_date: Dict[pd.Timestamp, Dict[str, float]],
    trade_dates_list: List[pd.Timestamp],
) -> Dict[pd.Timestamp, Dict[str, float]]:
    """构建月度调仓日期映射（T+2执行逻辑）"""
    rebalance_map = {}
    for calc_date, weight_dict in weights_by_date.items():
        future_dates = [d for d in trade_dates_list if d > calc_date]
        if len(future_dates) >= 2:
            execute_date = future_dates[1]
        elif len(future_dates) == 1:
            execute_date = future_dates[0]
        else:
            continue
        while execute_date in SKIP_EXCLUDED_DATES:
            idx = trade_dates_list.index(execute_date)
            if idx + 1 < len(trade_dates_list):
                execute_date = trade_dates_list[idx + 1]
            else:
                break
        rebalance_map[execute_date] = weight_dict
    return rebalance_map


def _calc_realized_vol(weights: Dict[str, float], daily_ret_df: pd.DataFrame, windows=None) -> float:
    """已实现波动率：max{sigma_22, sigma_65, sigma_130}"""
    if windows is None:
        windows = VOL_WINDOWS
    vol_values = []
    w = pd.Series(weights)
    for n in windows:
        if len(daily_ret_df) >= n:
            ret_window = daily_ret_df.iloc[-n:]
            weighted_ret = (ret_window * w).sum(axis=1)
            vol = weighted_ret.std() * np.sqrt(260)
            vol_values.append(vol)
    return max(vol_values) if vol_values else 0.0


# =============================================================================
# Step3: 主回测循环
# =============================================================================

def run_backtest(
    prices_df: pd.DataFrame,
    fx_df: pd.DataFrame,
    trade_dates_list: List[pd.Timestamp],
    backtest_start: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int, pd.Timestamp], None]] = None,
) -> dict:
    """
    完整回测主入口。忠实复现原型 step1+step2+step3。

    Parameters
    ----------
    prices_df : 索引=日期, 列=中文资产名或资产代码（自动识别）
    fx_df : 索引=日期, 列=币种（'USD','EUR','HKD' 等）
    trade_dates_list : 排序后的交易日列表
    backtest_start : 回测起始日期（YYYY-MM-DD），因子计算仍用全量数据，仅净值跟踪从此日开始

    Returns
    -------
    dict: 回测结果
    """
    # ---- 0. 列名标准化 ----
    first_col = prices_df.columns[0]
    if first_col in CODE_TO_NAME:
        rename_map = {col: CODE_TO_NAME.get(col, col) for col in prices_df.columns}
        nav = prices_df.rename(columns=rename_map)
    else:
        nav = prices_df.copy()

    assets = nav.columns.tolist()
    trade_dates_set = set(trade_dates_list)

    # ---- 1. 逐月末计算资产选择 + 权重（Step1 + Step2）----
    nav_with_ym = nav.copy()
    nav_with_ym['year_month'] = nav_with_ym.index.to_period('M')
    # 月末 = 每个 year_month 的最后一个交易日；tail(1) 兼容旧版 pandas（<2.2 无 include_groups 参数）
    month_end_dates = nav_with_ym.groupby('year_month').tail(1).index.tolist()

    selection_start_date = pd.Timestamp('2014-01-31')
    valid_month_ends = [d for d in month_end_dates if d >= selection_start_date]

    weights_by_date: Dict[pd.Timestamp, Dict[str, float]] = {}
    for calc_date in valid_month_ends:
        di = nav.index.get_loc(calc_date)
        selection_status = _select_assets(nav, di)
        w = _calc_weights_for_date(nav, di, selection_status, assets)
        weights_by_date[calc_date] = w

    # ---- 2. 构建月度调仓映射（T+2）----
    monthly_rebalance_map = _build_monthly_rebalance_map(weights_by_date, trade_dates_list)
    rebalance_dates_set = set(monthly_rebalance_map.keys())

    # ---- 3. 回测主循环 ----
    if backtest_start:
        bt_start_ts = pd.Timestamp(backtest_start)
        backtest_dates = [d for d in nav.index if d >= bt_start_ts]
    else:
        backtest_dates = list(nav.index)
    daily_ret_df = nav[assets].pct_change(fill_method=None).fillna(0)

    initial_weights = {}
    if backtest_dates and weights_by_date:
        first_bt_date = backtest_dates[0]
        # 用回测起始日之前（含）最近一次月末权重
        candidates = [d for d in weights_by_date.keys() if d <= first_bt_date]
        if candidates:
            initial_weights = weights_by_date[max(candidates)]
        else:
            initial_weights = weights_by_date[min(weights_by_date.keys())]

    # 状态变量
    nav_val = BASE_VALUE
    nav_base = BASE_VALUE
    positions_cny = {a: 0.0 for a in assets}
    positions_local = {a: 0.0 for a in assets}
    apl_local = {a: 0.0 for a in assets}
    target_weights = {a: 0.0 for a in assets}
    last_rebalance_fx = {a: 1.0 for a in assets}
    pending_rebalance: Optional[dict] = None
    total_trading_cost = 0.0
    total_replication_cost = 0.0

    nav_history = []
    event_log = []
    vol_reset_dates_set = set()
    vol_reset_count = 0

    prev_date = None
    prev_nav = None

    # 进度上报：每 1% 触发一次（最多 100 次），避免逐日回调把任务表打满
    _n_dates = len(backtest_dates)
    _progress_step = max(1, _n_dates // 100) if progress_cb is not None else 0

    for date_idx, date in enumerate(backtest_dates):
        if _progress_step:
            _done = date_idx + 1
            if _done % _progress_step == 0 or _done == _n_dates:
                try:
                    progress_cb(_done, _n_dates, date)
                except Exception:  # noqa: BLE001 —— 进度失败不影响回测
                    pass
        fx_rates = _get_fx_rates(fx_df, date, assets)

        # ---- 步骤A: 指数起始日 ----
        if date_idx == 0:
            nav_val = BASE_VALUE
            nav_base = BASE_VALUE
            for asset in assets:
                w = initial_weights.get(asset, 0.0)
                positions_cny[asset] = nav_val * w
                positions_local[asset] = positions_cny[asset] / fx_rates[asset]
                apl_local[asset] = 0.0
                target_weights[asset] = w
            last_rebalance_fx = fx_rates.copy()
            nav_history.append({'date': date.strftime('%Y-%m-%d'), 'nav': nav_val, 'daily_return': 0.0})
            event_log.append({
                'date': date.strftime('%Y-%m-%d'), 'type': 'init',
                'description': f'策略初始化，初始净值 {nav_val:.2f}',
                'trading_cost': 0.0,
                'old_weights': {a: 0.0 for a in assets},
                'new_weights': dict(initial_weights),
            })
            prev_date = date
            prev_nav = nav_val
            continue

        # ---- 步骤B: 每日损益更新 ----
        days_between = (date - prev_date).days
        daily_replication_cost = 0.0
        for asset in assets:
            if positions_cny[asset] == 0:
                continue
            p1 = nav.loc[date, asset]
            p0 = nav.loc[prev_date, asset]
            if not np.isnan(p1) and not np.isnan(p0) and p0 > 0:
                r_local = p1 / p0 - 1
            else:
                r_local = 0.0
            currency = ASSET_CURRENCY.get(asset, 'CNH')
            fx_curr = _get_fx_rate(fx_df, date, currency)
            fx_prev = _get_fx_rate(fx_df, prev_date, currency)
            p1_cny = p1 * fx_curr if not np.isnan(p1) else 0
            p0_cny = p0 * fx_prev if not np.isnan(p0) else 0
            r_cny = (p1_cny / p0_cny - 1) if p0_cny > 0 else 0.0

            pnl_local = positions_local[asset] * r_local
            rc = REPLICATION_COST.get(asset, 0.005)
            rc_cost_local = positions_local[asset] * (rc / 365.0) * days_between
            daily_replication_cost += rc_cost_local * fx_rates[asset]

            apl_local[asset] += pnl_local - rc_cost_local
            positions_local[asset] *= (1 + r_local)
            positions_cny[asset] *= (1 + r_cny)

        total_apl_cny = sum(apl_local[a] * fx_rates[a] for a in assets)
        nav_val = nav_base + total_apl_cny
        total_replication_cost += daily_replication_cost

        # ---- 步骤C: 调仓执行（波动率重置优先）----
        is_rebalance_day = False
        if pending_rebalance is not None and date == pending_rebalance['execute_date']:
            pr = pending_rebalance
            new_weights = pr['weights']
            trading_cost = 0.0
            for asset in assets:
                target_pos = prev_nav * new_weights.get(asset, 0) / fx_rates[asset]
                current_pos = positions_local[asset]
                trade_amount = abs(target_pos - current_pos)
                tc = TRADING_COST.get(asset, 0.001)
                trading_cost += trade_amount * tc * fx_rates[asset]
            nav_val -= trading_cost
            total_trading_cost += trading_cost

            for asset in assets:
                w = new_weights.get(asset, 0.0)
                positions_cny[asset] = prev_nav * w
                positions_local[asset] = positions_cny[asset] / fx_rates[asset]
                apl_local[asset] = 0.0
                target_weights[asset] = w
            nav_base = nav_val
            last_rebalance_fx = fx_rates.copy()
            pending_rebalance = None
            is_rebalance_day = True

            if pr.get('type') == 'vol_reset':
                vol_reset_count += 1
                event_log.append({
                    'date': date.strftime('%Y-%m-%d'), 'type': 'vol_reset', 'stage': 'execute',
                    'description': f'执行波动率重置调仓，交易费用 {trading_cost:.2f}',
                    'trading_cost': trading_cost,
                    'new_weights': dict(new_weights),
                })

        # ---- 步骤D: 月度调仓 ----
        if date in rebalance_dates_set and not is_rebalance_day:
            new_weights = monthly_rebalance_map[date]
            old_weights = dict(target_weights)
            trading_cost = 0.0
            for asset in assets:
                target_pos = prev_nav * new_weights.get(asset, 0) / fx_rates[asset]
                current_pos = positions_local[asset]
                trade_amount = abs(target_pos - current_pos)
                tc = TRADING_COST.get(asset, 0.001)
                trading_cost += trade_amount * tc * fx_rates[asset]
            nav_val -= trading_cost
            total_trading_cost += trading_cost

            for asset in assets:
                w = new_weights.get(asset, 0.0)
                positions_cny[asset] = prev_nav * w
                positions_local[asset] = positions_cny[asset] / fx_rates[asset]
                apl_local[asset] = 0.0
                target_weights[asset] = w
            nav_base = nav_val
            last_rebalance_fx = fx_rates.copy()
            is_rebalance_day = True
            pending_rebalance = None
            event_log.append({
                'date': date.strftime('%Y-%m-%d'), 'type': 'monthly',
                'description': f'执行月度调仓，交易费用 {trading_cost:.2f}',
                'trading_cost': trading_cost,
                'old_weights': old_weights, 'new_weights': dict(new_weights),
            })

        # ---- 步骤E: 波动率监测 ----
        if not is_rebalance_day and pending_rebalance is None and date_idx >= MONITOR_START_DAYS:
            if nav_val > 0:
                w_cny = {a: positions_local[a] * last_rebalance_fx[a] / nav_val for a in assets}
                ytd_ret = daily_ret_df.loc[:date, assets]
                vol_trigger = _calc_realized_vol(w_cny, ytd_ret)

                if vol_trigger > VOL_TRIGGER_THRESHOLD:
                    future_dates = [d for d in trade_dates_list if d > date]
                    if len(future_dates) >= 2:
                        exec_date = future_dates[1]
                        while exec_date in SKIP_EXCLUDED_DATES:
                            idx_td = trade_dates_list.index(exec_date)
                            if idx_td + 1 < len(trade_dates_list):
                                exec_date = trade_dates_list[idx_td + 1]
                            else:
                                exec_date = None
                                break

                        if exec_date:
                            t_plus_1 = future_dates[0]
                            has_conflict = False
                            if date in rebalance_dates_set or date in vol_reset_dates_set:
                                has_conflict = True
                            if t_plus_1 in rebalance_dates_set or t_plus_1 in vol_reset_dates_set:
                                has_conflict = True
                            if exec_date in rebalance_dates_set or exec_date in vol_reset_dates_set:
                                has_conflict = True

                            if not has_conflict:
                                scale_factor = TARGET_VOL / vol_trigger
                                vw_weights = {
                                    a: np.trunc(w * scale_factor * 1000) / 1000
                                    for a, w in w_cny.items()
                                }
                                pending_rebalance = {
                                    'execute_date': exec_date,
                                    'weights': vw_weights,
                                    'type': 'vol_reset',
                                    'signal_date': date,
                                    'vol_trigger': vol_trigger,
                                    'scale_factor': scale_factor,
                                }
                                vol_reset_dates_set.add(exec_date)
                                event_log.append({
                                    'date': date.strftime('%Y-%m-%d'), 'type': 'vol_reset', 'stage': 'trigger',
                                    'description': f'波动率触发 vol={vol_trigger:.4f}, scale={scale_factor:.4f}',
                                    'vol_trigger': vol_trigger,
                                    'scale_factor': scale_factor,
                                    'execute_date': exec_date.strftime('%Y-%m-%d'),
                                })

        # ---- 步骤F: 记录 ----
        daily_return = (nav_val / prev_nav - 1) * 100 if prev_nav and prev_nav > 0 else 0.0
        nav_history.append({'date': date.strftime('%Y-%m-%d'), 'nav': nav_val, 'daily_return': daily_return})
        prev_date = date
        prev_nav = nav_val

    # ---- 4. 构建输出 ----
    final_date = nav_history[-1]['date'] if nav_history else BASE_DATE.strftime('%Y-%m-%d')

    code_positions_cny = {NAME_TO_CODE.get(a, a): v for a, v in positions_cny.items()}
    code_positions_local = {NAME_TO_CODE.get(a, a): v for a, v in positions_local.items()}
    code_apl_local = {NAME_TO_CODE.get(a, a): v for a, v in apl_local.items()}
    code_target_weights = {NAME_TO_CODE.get(a, a): v for a, v in target_weights.items()}
    code_last_rebalance_fx = {NAME_TO_CODE.get(a, a): v for a, v in last_rebalance_fx.items()}

    pending_dict = None
    if pending_rebalance:
        p = pending_rebalance
        pending_dict = {
            'signal_date': p['signal_date'].strftime('%Y-%m-%d'),
            'execute_date': p['execute_date'].strftime('%Y-%m-%d'),
            'weights': {NAME_TO_CODE.get(a, a): v for a, v in p['weights'].items()},
            'rebalance_type': p['type'],
            'vol_trigger': p['vol_trigger'],
            'scale_factor': p['scale_factor'],
        }

    for ev in event_log:
        if 'old_weights' in ev and ev['old_weights']:
            ev['old_weights'] = {NAME_TO_CODE.get(a, a): v for a, v in ev['old_weights'].items()}
        if 'new_weights' in ev and ev['new_weights']:
            ev['new_weights'] = {NAME_TO_CODE.get(a, a): v for a, v in ev['new_weights'].items()}

    return {
        'nav_history': nav_history,
        'final_nav': nav_val,
        'final_date': final_date,
        'day_count': len(nav_history),
        'vol_reset_count': vol_reset_count,
        'total_trading_cost': total_trading_cost,
        'total_replication_cost': total_replication_cost,
        'positions_cny': code_positions_cny,
        'positions_local': code_positions_local,
        'apl_local': code_apl_local,
        'target_weights': code_target_weights,
        'last_rebalance_fx': code_last_rebalance_fx,
        'pending_rebalance': pending_dict,
        'event_log': event_log,
    }
