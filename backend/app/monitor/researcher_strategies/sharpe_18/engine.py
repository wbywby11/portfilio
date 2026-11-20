# -*- coding: utf-8 -*-
"""夏普18独立回测引擎

忠实复现策略原型 step1_asset_selection + step2_weight_calculation + step3_backtest_fx_v4 的完整计算逻辑。
本模块自包含，不依赖 CompositionPipeline / PortfolioTracker / SignalDetector 等系统组件。

输入：prices_df（列=中文资产名）、fx_df（列=币种）、trade_dates_list
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
SELECT_COUNT = 13
VOL_WINDOWS = [22, 65, 130]
ANNUALIZE_FACTOR = np.sqrt(260)
MONITOR_START_DAYS = 60
VOL_TRIGGER_THRESHOLD = 0.06

SKIP_EXCLUDED_DATES = {
    pd.Timestamp("2015-01-01"),
    pd.Timestamp("2015-01-02"),
    pd.Timestamp("2015-01-05"),
}

# 资产代码 ↔ 中文名映射（用于与监控系统对接）
CODE_TO_NAME = {
    "000300.SH": "沪深300", "ZZ000905": "中证500", "SZ399006": "创业板指",
    "SPX": "标普500", "NDX": "纳斯达克100", "N225": "日经225",
    "ZQGZ10": "中国10年国债", "ZQGZ5": "中国5年国债", "ZQGZ2": "中国2年国债",
    "UST10": "美国10年国债", "UST2": "美国2年国债",
    "CVTBND": "可转债", "GLD": "黄金", "B00Y": "布伦特原油",
    "SHCU": "沪铜", "SHAL": "沪铝", "SHSN": "沪锡", "DM": "豆粕",
}
NAME_TO_CODE = {v: k for k, v in CODE_TO_NAME.items()}

# 单资产权重上限
WEIGHT_CAPS = {
    '沪深300': 0.10, '中证500': 0.10, '创业板指': 0.10,
    '标普500': 0.15, '纳斯达克100': 0.15, '日经225': 0.10,
    '中国10年国债': 0.60, '中国5年国债': 0.60, '中国2年国债': 0.90,
    '美国10年国债': 0.60, '美国2年国债': 0.60,
    '可转债': 0.10, '黄金': 0.10, '布伦特原油': 0.10,
    '沪铜': 0.10, '沪铝': 0.10, '沪锡': 0.10, '豆粕': 0.10,
}

# 费率
TRADING_COST = {
    '沪深300': 0.0003, '中证500': 0.0003, '创业板指': 0.0003,
    '标普500': 0.0002, '纳斯达克100': 0.0002, '日经225': 0.0003,
    '中国10年国债': 0.0003, '中国5年国债': 0.0003, '中国2年国债': 0.0003,
    '美国10年国债': 0.0002, '美国2年国债': 0.0002,
    '可转债': 0.0003, '黄金': 0.0003, '布伦特原油': 0.0001,
    '沪铜': 0.0003, '沪铝': 0.0003, '沪锡': 0.0003, '豆粕': 0.0003,
}

REPLICATION_COST = {
    '沪深300': 0.004, '中证500': 0.004, '创业板指': 0.030,
    '标普500': 0.006, '纳斯达克100': 0.006, '日经225': 0.006,
    '中国10年国债': 0.003, '中国5年国债': 0.003, '中国2年国债': 0.003,
    '美国10年国债': 0.004, '美国2年国债': 0.004,
    '可转债': 0.030, '黄金': 0.006, '布伦特原油': 0.006,
    '沪铜': 0.006, '沪铝': 0.006, '沪锡': 0.006, '豆粕': 0.006,
}

# 资产计价货币
ASSET_CURRENCY = {
    '沪深300': 'CNH', '中证500': 'CNH', '创业板指': 'CNH',
    '标普500': 'USD', '纳斯达克100': 'USD', '日经225': 'JPY',
    '中国10年国债': 'CNH', '中国5年国债': 'CNH', '中国2年国债': 'CNH',
    '美国10年国债': 'USD', '美国2年国债': 'USD',
    '可转债': 'CNH', '黄金': 'CNH', '布伦特原油': 'USD',
    '沪铜': 'CNH', '沪铝': 'CNH', '沪锡': 'CNH', '豆粕': 'CNH',
}


# =============================================================================
# Step1: 夏普率因子 & 资产选择
# =============================================================================

def _calc_sharp_ratio(prices: pd.DataFrame, n: int) -> pd.DataFrame:
    """SHARP_n = pct_change(n) / rolling_std(n)"""
    cum_ret = prices / prices.shift(n) - 1
    daily_ret = prices.pct_change(fill_method=None)
    vol = daily_ret.rolling(n).std()
    sharp = cum_ret / vol
    return sharp.replace([np.inf, -np.inf], np.nan)


def _calc_sharp_scores(prices: pd.DataFrame, date_idx: int, windows=(22, 65, 260)):
    """综合打分 = 各窗口rank之和（rank ascending=True，越大越好）"""
    price_data = prices.iloc[:date_idx + 1]
    total_score = pd.Series(0.0, index=prices.columns)
    for n in windows:
        if len(price_data) > n:
            factor = _calc_sharp_ratio(price_data, n).iloc[-1]
            rank = factor.rank(ascending=True, method='average')
            total_score += rank.fillna(0)
    return total_score


def _select_assets(nav: pd.DataFrame, date_idx: int, min_history: int = 260, top_count: int = 13) -> List[str]:
    """单次调仓的资产选择：有效资产(≥260天)中按综合打分降序选top_count个"""
    valid_assets = []
    for col in nav.columns:
        valid_count = nav[col].iloc[:date_idx + 1].notna().sum()
        if valid_count >= min_history:
            valid_assets.append(col)
    if not valid_assets:
        return []
    # 在所有资产上计算SHARP和排名
    price_all = nav.iloc[:date_idx + 1]
    total_score = _calc_sharp_scores(price_all, len(price_all) - 1)
    # 22日MOM动量（tie-breaker）
    mom_22 = (price_all / price_all.shift(22) - 1).iloc[-1]
    # 仅对有效资产排序
    ranking_data = pd.DataFrame({
        '综合打分': total_score.loc[valid_assets],
        'MOM_22_tiebreak': mom_22.loc[valid_assets]
    })
    ranking_data = ranking_data.sort_values(
        by=['综合打分', 'MOM_22_tiebreak'], ascending=[False, False]
    )
    return ranking_data.index[:top_count].tolist()


# =============================================================================
# Step2: 权重计算
# =============================================================================

def _calc_asset_volatility(prices: pd.DataFrame, date_idx: int, windows=VOL_WINDOWS) -> pd.Series:
    """资产波动率：取22/65/130日年化波动率的最大值"""
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


def _calc_portfolio_volatility(prices: pd.DataFrame, weights: pd.Series, date_idx: int, windows=VOL_WINDOWS) -> float:
    """组合波动率：权重加权组合收益率，取22/65/130日年化波动率最大值"""
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


def _calc_weights_for_date(nav: pd.DataFrame, date_idx: int, selected_assets: List[str], all_assets: List[str]) -> Dict[str, float]:
    """计算单个调仓日的最终权重（风险预算→初始权重→缩放→截断）"""
    # 风险预算：选中=1/13，未选中=0
    budgets = pd.Series({a: (1.0 / SELECT_COUNT if a in selected_assets else 0.0) for a in all_assets})
    # 资产波动率
    asset_vols = _calc_asset_volatility(nav, date_idx)
    # 初始权重：w = b × (target_vol / σ)
    initial_weights = pd.Series(0.0, index=all_assets)
    for asset in all_assets:
        b = budgets[asset]
        sigma = asset_vols.get(asset, np.nan)
        if b > 0 and sigma > 0 and not np.isnan(sigma):
            initial_weights[asset] = b * (TARGET_VOL / sigma)
    # 组合波动率
    port_vol = _calc_portfolio_volatility(nav, initial_weights, date_idx)
    # 缩放约束：scale = min(target_vol/σ_port, max_leverage/Σw)
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
# Step3: 回测数据结构
# =============================================================================

@dataclass
class _PendingRebalance:
    signal_date: pd.Timestamp
    execute_date: pd.Timestamp
    weights: Dict[str, float]
    rebalance_type: str
    signal_weights: Optional[Dict[str, float]] = None
    vol_trigger: Optional[float] = None
    scale_factor: Optional[float] = None


@dataclass
class _BacktestState:
    assets: List[str]
    nav: float = BASE_VALUE
    nav_base: float = BASE_VALUE
    positions_cny: Dict[str, float] = field(default_factory=dict)
    positions_cny_base: Dict[str, float] = field(default_factory=dict)
    positions_local: Dict[str, float] = field(default_factory=dict)
    apl_local: Dict[str, float] = field(default_factory=dict)
    target_weights: Dict[str, float] = field(default_factory=dict)
    pending_rebalance: Optional[_PendingRebalance] = None
    last_rebalance_date: Optional[pd.Timestamp] = None
    last_rebalance_fx: Dict[str, float] = field(default_factory=dict)
    total_trading_cost: float = 0.0
    total_replication_cost: float = 0.0

    def __post_init__(self):
        for asset in self.assets:
            self.positions_cny.setdefault(asset, 0.0)
            self.positions_cny_base.setdefault(asset, 0.0)
            self.positions_local.setdefault(asset, 0.0)
            self.apl_local.setdefault(asset, 0.0)
            self.target_weights.setdefault(asset, 0.0)
            self.last_rebalance_fx.setdefault(asset, 1.0)


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


def _calc_realized_vol(weights: Dict[str, float], daily_ret_df: pd.DataFrame, windows=VOL_WINDOWS) -> float:
    """已实现波动率：max{σ_22, σ_65, σ_130}"""
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
    prices_df : 索引=日期, 列=中文资产名（如 '沪深300', '标普500'）
                或资产代码（如 '000300.SH'）—— 自动识别并映射为中文名
    fx_df : 索引=日期, 列=币种（'USD','JPY' 等）
    trade_dates_list : 排序后的交易日列表
    backtest_start : 回测起始日期（YYYY-MM-DD），因子计算仍用全量数据，仅净值跟踪从此日开始
    progress_cb : 可选进度回调 ``(已处理日数, 总日数, 当前日期)``。
                由监控后台任务注入，用于把逐日推演进度写回任务表；
                默认 None 时零开销，异常一律忽略，不影响回测结果。

    Returns
    -------
    dict: 回测结果
    """
    # ---- 0. 列名标准化：如果列名是代码则映射为中文名 ----
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
        date_idx = nav.index.get_loc(calc_date)
        selected = _select_assets(nav, date_idx)
        w = _calc_weights_for_date(nav, date_idx, selected, assets)
        weights_by_date[calc_date] = w

    # ---- 2. 构建月度调仓映射（T+2）----
    monthly_rebalance_map = _build_monthly_rebalance_map(weights_by_date, trade_dates_list)
    rebalance_dates_set = set(monthly_rebalance_map.keys())
    monthly_signal_dates_set = set(weights_by_date.keys())

    # ---- 3. 回测主循环 ----
    if backtest_start:
        bt_start_ts = pd.Timestamp(backtest_start)
        backtest_dates = [d for d in nav.index if d >= bt_start_ts]
    else:
        backtest_dates = list(nav.index)
    daily_ret_df = nav[assets].pct_change(fill_method=None).fillna(0)

    # 初始权重（回测起始日之前最近一次月末权重）
    initial_weights = {}
    if backtest_dates and weights_by_date:
        first_bt_date = backtest_dates[0]
        candidates = [d for d in weights_by_date.keys() if d <= first_bt_date]
        if candidates:
            initial_weights = weights_by_date[max(candidates)]
        else:
            initial_weights = weights_by_date[min(weights_by_date.keys())]

    state = _BacktestState(assets=assets)
    nav_history = []
    event_log = []
    vol_reset_dates_set = set()
    vol_signal_dates_set = set()
    vol_reset_count = 0

    prev_date = None
    prev_nav = None
    trade_day_idx = 0

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
        if date not in nav.index:
            continue
        is_trade_day = date in trade_dates_set
        fx_rates = _get_fx_rates(fx_df, date, assets)

        # ---- 步骤A: 指数起始日 ----
        if date_idx == 0:
            state.nav = BASE_VALUE
            state.nav_base = BASE_VALUE
            for asset in assets:
                weight = initial_weights.get(asset, 0.0)
                state.positions_cny[asset] = state.nav * weight
                state.positions_cny_base[asset] = state.nav * weight
                state.positions_local[asset] = state.positions_cny[asset] / fx_rates[asset]
                state.apl_local[asset] = 0.0
                state.target_weights[asset] = weight
            state.last_rebalance_date = date
            state.last_rebalance_fx = fx_rates.copy()
            nav_history.append({'date': date.strftime('%Y-%m-%d'), 'nav': state.nav, 'daily_return': 0.0})
            event_log.append({
                'date': date.strftime('%Y-%m-%d'), 'type': 'init',
                'description': f'策略初始化，初始净值 {state.nav:.2f}',
                'trading_cost': 0.0,
                'old_weights': {a: 0.0 for a in assets},
                'new_weights': dict(initial_weights),
            })
            prev_date = date
            prev_nav = state.nav
            if is_trade_day:
                trade_day_idx += 1
            continue

        # ---- 步骤B: 每日损益更新 ----
        days_between = (date - prev_date).days if prev_date else 1
        daily_replication_cost = 0.0
        for asset in assets:
            if state.positions_cny[asset] == 0:
                continue
            p1 = nav.loc[date, asset]
            p0 = nav.loc[prev_date, asset]
            # 本币收益率
            if not np.isnan(p1) and not np.isnan(p0) and p0 > 0:
                r_local = p1 / p0 - 1
            else:
                r_local = 0.0
            # 人民币收益率（含汇率变动）
            currency = ASSET_CURRENCY.get(asset, 'CNH')
            fx_curr = _get_fx_rate(fx_df, date, currency)
            fx_prev = _get_fx_rate(fx_df, prev_date, currency)
            p1_cny = p1 * fx_curr
            p0_cny = p0 * fx_prev
            if not np.isnan(p1_cny) and not np.isnan(p0_cny) and p0_cny > 0:
                r_cny = p1_cny / p0_cny - 1
            else:
                r_cny = 0.0
            # 本币损益
            pnl_local = state.positions_local[asset] * r_local
            # 复制费用
            rc = REPLICATION_COST.get(asset, 0.005)
            rc_cost_local = state.positions_local[asset] * (rc / 365.0) * days_between
            daily_replication_cost += rc_cost_local * fx_rates[asset]
            # 更新
            state.apl_local[asset] += pnl_local - rc_cost_local
            state.positions_local[asset] *= (1 + r_local)
            state.positions_cny[asset] *= (1 + r_cny)

        total_apl_cny = sum(state.apl_local[asset] * fx_rates[asset] for asset in assets)
        state.nav = state.nav_base + total_apl_cny
        state.total_replication_cost += daily_replication_cost

        # ---- 步骤C: 调仓执行（波动率重置，优先级最高）----
        is_rebalance_day = False
        if state.pending_rebalance is not None and is_trade_day and date == state.pending_rebalance.execute_date:
            pending = state.pending_rebalance
            skip_vol = False
            # 波动率重置与月度调仓同天冲突：月度调仓优先
            if pending.rebalance_type == 'vol_reset' and date in rebalance_dates_set:
                skip_vol = True
            # 检查触发日到执行日之间是否存在其他调仓信号
            if pending.rebalance_type == 'vol_reset' and not skip_vol:
                for sig_date in monthly_signal_dates_set:
                    if pending.signal_date < sig_date < pending.execute_date:
                        skip_vol = True
                        break
                if not skip_vol:
                    for sig_date in vol_signal_dates_set:
                        if pending.signal_date < sig_date < pending.execute_date:
                            skip_vol = True
                            break
            if skip_vol:
                if pending.rebalance_type == 'vol_reset':
                    event_log.append({
                        'date': date.strftime('%Y-%m-%d'), 'type': 'vol_reset', 'stage': 'skipped',
                        'description': '波动率重置跳过（冲突）',
                    })
                state.pending_rebalance = None
            else:
                # 执行调仓
                new_weights = pending.weights
                trading_cost = 0.0
                nav_for_position = prev_nav
                for asset in assets:
                    target_pos_local = nav_for_position * new_weights.get(asset, 0) / fx_rates[asset]
                    current_pos_local = state.positions_local[asset]
                    trade_amount_local = abs(target_pos_local - current_pos_local)
                    tc = TRADING_COST.get(asset, 0.001)
                    trading_cost += trade_amount_local * tc * fx_rates[asset]
                state.nav -= trading_cost
                for asset in assets:
                    weight = new_weights.get(asset, 0.0)
                    state.positions_cny[asset] = nav_for_position * weight
                    state.positions_cny_base[asset] = nav_for_position * weight
                    state.positions_local[asset] = state.positions_cny[asset] / fx_rates[asset]
                    state.apl_local[asset] = 0.0
                    state.target_weights[asset] = weight
                state.nav_base = state.nav
                state.last_rebalance_date = date
                state.last_rebalance_fx = fx_rates.copy()
                state.total_trading_cost += trading_cost
                state.pending_rebalance = None
                is_rebalance_day = True
                if pending.rebalance_type == 'vol_reset':
                    vol_reset_count += 1
                    event_log.append({
                        'date': date.strftime('%Y-%m-%d'), 'type': 'vol_reset', 'stage': 'execute',
                        'description': f'执行波动率重置调仓，交易费用 {trading_cost:.2f}',
                        'trading_cost': trading_cost,
                        'old_weights': {}, 'new_weights': dict(new_weights),
                    })

        # ---- 步骤D: 月度调仓 ----
        if is_trade_day and date in rebalance_dates_set and not is_rebalance_day:
            new_weights = monthly_rebalance_map[date]
            old_weights = dict(state.target_weights)
            trading_cost = 0.0
            nav_for_position = prev_nav
            for asset in assets:
                target_pos_local = nav_for_position * new_weights.get(asset, 0) / fx_rates[asset]
                current_pos_local = state.positions_local[asset]
                trade_amount_local = abs(target_pos_local - current_pos_local)
                tc = TRADING_COST.get(asset, 0.001)
                trading_cost += trade_amount_local * tc * fx_rates[asset]
            state.nav -= trading_cost
            for asset in assets:
                weight = new_weights.get(asset, 0.0)
                state.positions_cny[asset] = nav_for_position * weight
                state.positions_cny_base[asset] = nav_for_position * weight
                state.positions_local[asset] = state.positions_cny[asset] / fx_rates[asset]
                state.apl_local[asset] = 0.0
                state.target_weights[asset] = weight
            state.nav_base = state.nav
            state.last_rebalance_date = date
            state.last_rebalance_fx = fx_rates.copy()
            state.total_trading_cost += trading_cost
            state.pending_rebalance = None
            is_rebalance_day = True
            event_log.append({
                'date': date.strftime('%Y-%m-%d'), 'type': 'monthly',
                'description': f'执行月度调仓，交易费用 {trading_cost:.2f}',
                'trading_cost': trading_cost,
                'old_weights': old_weights, 'new_weights': dict(new_weights),
            })

        # ---- 步骤E: 波动率监测（调仓日跳过）----
        if not is_rebalance_day and state.pending_rebalance is None:
            if trade_day_idx >= MONITOR_START_DAYS:
                # 计算实际权重（线性 pv_cny）
                if state.nav > 0:
                    w_monitor = {}
                    for asset in assets:
                        pv_cny_linear = state.positions_cny_base[asset] + state.apl_local[asset] * fx_rates[asset]
                        w_monitor[asset] = pv_cny_linear / state.nav
                else:
                    w_monitor = state.target_weights.copy()
                # 已实现波动率
                ytd_ret = daily_ret_df.loc[:date, assets]
                vol_trigger = _calc_realized_vol(w_monitor, ytd_ret)
                if vol_trigger > VOL_TRIGGER_THRESHOLD:
                    future_dates = [d for d in trade_dates_list if d > date]
                    if len(future_dates) >= 2:
                        execute_date = future_dates[1]
                        while execute_date in SKIP_EXCLUDED_DATES:
                            idx = trade_dates_list.index(execute_date)
                            if idx + 1 < len(trade_dates_list):
                                execute_date = trade_dates_list[idx + 1]
                            else:
                                execute_date = None
                                break
                        if execute_date is not None:
                            # 冲突检查 [t, T+1, T+2]
                            t_plus_1 = future_dates[0]
                            has_conflict = False
                            if date in rebalance_dates_set or date in vol_reset_dates_set:
                                has_conflict = True
                            if t_plus_1 in rebalance_dates_set or t_plus_1 in vol_reset_dates_set:
                                has_conflict = True
                            if execute_date in rebalance_dates_set or execute_date in vol_reset_dates_set:
                                has_conflict = True
                            if not has_conflict:
                                scale_factor = TARGET_VOL / vol_trigger
                                vw_weights = {asset: w * scale_factor for asset, w in w_monitor.items()}
                                state.pending_rebalance = _PendingRebalance(
                                    signal_date=date,
                                    execute_date=execute_date,
                                    weights=vw_weights,
                                    rebalance_type='vol_reset',
                                    signal_weights=w_monitor.copy(),
                                    vol_trigger=vol_trigger,
                                    scale_factor=scale_factor,
                                )
                                vol_reset_dates_set.add(execute_date)
                                vol_signal_dates_set.add(date)
                                event_log.append({
                                    'date': date.strftime('%Y-%m-%d'), 'type': 'vol_reset', 'stage': 'trigger',
                                    'description': f'波动率触发 vol={vol_trigger:.4f}, scale={scale_factor:.4f}',
                                    'vol_trigger': vol_trigger,
                                    'scale_factor': scale_factor,
                                    'execute_date': execute_date.strftime('%Y-%m-%d'),
                                })

        # ---- 步骤F: 记录 ----
        daily_return = (state.nav / prev_nav - 1) * 100 if prev_nav and prev_nav > 0 else 0.0
        nav_history.append({'date': date.strftime('%Y-%m-%d'), 'nav': state.nav, 'daily_return': daily_return})
        prev_nav = state.nav
        prev_date = date
        if is_trade_day:
            trade_day_idx += 1

    # ---- 4. 构建输出 ----
    final_date = nav_history[-1]['date'] if nav_history else BASE_DATE.strftime('%Y-%m-%d')

    # 输出同时提供中文名和代码键（兼容监控系统）
    code_positions_cny = {NAME_TO_CODE.get(a, a): v for a, v in state.positions_cny.items()}
    code_positions_local = {NAME_TO_CODE.get(a, a): v for a, v in state.positions_local.items()}
    code_apl_local = {NAME_TO_CODE.get(a, a): v for a, v in state.apl_local.items()}
    code_positions_cny_base = {NAME_TO_CODE.get(a, a): v for a, v in state.positions_cny_base.items()}
    code_target_weights = {NAME_TO_CODE.get(a, a): v for a, v in state.target_weights.items()}
    code_last_rebalance_fx = {NAME_TO_CODE.get(a, a): v for a, v in state.last_rebalance_fx.items()}

    pending_dict = None
    if state.pending_rebalance:
        p = state.pending_rebalance
        pending_dict = {
            'signal_date': p.signal_date.strftime('%Y-%m-%d'),
            'execute_date': p.execute_date.strftime('%Y-%m-%d'),
            'weights': {NAME_TO_CODE.get(a, a): v for a, v in p.weights.items()},
            'rebalance_type': p.rebalance_type,
            'vol_trigger': p.vol_trigger,
            'scale_factor': p.scale_factor,
        }

    for ev in event_log:
        if 'old_weights' in ev and ev['old_weights']:
            ev['old_weights'] = {NAME_TO_CODE.get(a, a): v for a, v in ev['old_weights'].items()}
        if 'new_weights' in ev and ev['new_weights']:
            ev['new_weights'] = {NAME_TO_CODE.get(a, a): v for a, v in ev['new_weights'].items()}

    return {
        'nav_history': nav_history,
        'final_nav': state.nav,
        'final_date': final_date,
        'day_count': len(nav_history),
        'vol_reset_count': vol_reset_count,
        'total_trading_cost': state.total_trading_cost,
        'total_replication_cost': state.total_replication_cost,
        'positions_cny': code_positions_cny,
        'positions_local': code_positions_local,
        'apl_local': code_apl_local,
        'positions_cny_base': code_positions_cny_base,
        'target_weights': code_target_weights,
        'last_rebalance_date': state.last_rebalance_date.strftime('%Y-%m-%d') if state.last_rebalance_date else final_date,
        'last_rebalance_fx': code_last_rebalance_fx,
        'pending_rebalance': pending_dict,
        'event_log': event_log,
        'trade_day_count': trade_day_idx,
    }
