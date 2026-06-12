# -*- coding: utf-8 -*-
"""
大类资产配置指数策略 - 第三步：净值计算与回测（V4版本）

基于 step3_backtest_fx_v4.py（动量策略参考资料）重构，用于 risk_budget_target_vol 混合动量资产选择策略。

V4 特点：
- 按时间线视角，模块化设计
- BacktestState、PendingRebalance 数据类
- 净值：nav = nav_base + sum(apl_local × 当日汇率)
- 收益率：ret_local（本币）、ret_cny（含汇率的人民币）
- 波动率监控：MONITOR_START_DAYS=60，[t,T+1,T+2] 冲突检查，权重截断到小数点后三位
- 支持从 data/资产费用.xlsx 加载费率，回退到传入或内置配置
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

# =============================================================================
# 配置参数
# =============================================================================

BASE_DATE = pd.Timestamp("2014-02-10")
BASE_VALUE = 1000.0
# 波动率阈值重置：仅当 组合实现波动率 > VOL_TRIGGER_THRESHOLD 时才触发，重置后目标为 VOL_TARGET。
# 因此 目标值 < 实现波动率 <= 触发阈值 时不会触发（例如 5% < vol <= 6% 不触发）。
VOL_TRIGGER_THRESHOLD = 0.06
VOL_TARGET = 0.05
VOL_WINDOWS = [22, 65, 130]
MONITOR_START_DAYS = 60

SKIP_EXCLUDED_DATES = {
    pd.Timestamp("2015-01-01"),
    pd.Timestamp("2015-01-02"),
    pd.Timestamp("2015-01-05"),
}

# 内置费率（资产代码 key，供无 Excel 时回退，与 v4 基准一致）
_DEFAULT_TRADING_COST = {
    "SH000300": 0.0003, "SZ399006": 0.0003, "ZZ000001": 0.0003, "HSTECH": 0.0005,
    "SPX": 0.0002, "GDAXI": 0.0002, "ZQGZ10": 0.0003, "ZQGZ2": 0.0003,
    "B00Y": 0.0001, "GLD": 0.0003, "IRON": 0.0003, "YSJS": 0.0003,
    "SH000300_TEST": 0.0003, "SZ399006_TEST": 0.0003, "ZZ000001_TEST": 0.0003,
    "HSTECH_TEST": 0.0005, "SPX_TEST": 0.0002, "GDAXI_TEST": 0.0002,
    "ZQGZ10_TEST": 0.0003, "ZQGZ2_TEST": 0.0003, "B00Y_TEST": 0.0001,
    "GLD_TEST": 0.0003, "IRON_TEST": 0.0003, "YSJS_TEST": 0.0003,
}
_DEFAULT_REPLICATION_COST = {
    "SH000300": 0.004, "SZ399006": 0.030, "ZZ000001": 0.030, "HSTECH": 0.020,
    "SPX": 0.006, "GDAXI": 0.007, "ZQGZ10": 0.003, "ZQGZ2": 0.003,
    "B00Y": 0.006, "GLD": 0.006, "IRON": 0.006, "YSJS": 0.006,
    "SH000300_TEST": 0.004, "SZ399006_TEST": 0.030, "ZZ000001_TEST": 0.030,
    "HSTECH_TEST": 0.020, "SPX_TEST": 0.006, "GDAXI_TEST": 0.007,
    "ZQGZ10_TEST": 0.003, "ZQGZ2_TEST": 0.003, "B00Y_TEST": 0.006,
    "GLD_TEST": 0.006, "IRON_TEST": 0.006, "YSJS_TEST": 0.006,
}


# =============================================================================
# 资产费用加载（data/资产费用.xlsx）
# =============================================================================

def _get_data_dir() -> str:
    """获取 portfilio-end/data 目录"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
    return os.path.join(project_root, "data")


def _load_fx_from_data_fallback() -> Optional[pd.DataFrame]:
    """从 data/fx.xlsx 加载汇率，失败返回 None"""
    try:
        path = os.path.join(_get_data_dir(), "fx.xlsx")
        if not os.path.exists(path):
            return None
        return pd.read_excel(path, index_col=0, parse_dates=True)
    except Exception:
        return None


def _build_name_to_code() -> Dict[str, str]:
    """构建 名称->代码 映射"""
    try:
        from app.config.zy_document_max_weights import ZY_DOCUMENT_CODE_TO_NAME
        return {v: k for k, v in ZY_DOCUMENT_CODE_TO_NAME.items()}
    except Exception:
        return {}


def load_asset_costs_from_data(
    all_assets: Optional[List[str]] = None,
) -> Optional[Tuple[Dict[str, float], Dict[str, float]]]:
    """
    从 data/资产费用.xlsx 加载资产费率。

    预期列：资产, 交易费率, 复制费率（或 交易费率、复制费率）
    资产列支持：资产代码 或 资产名称（通过 ZY_DOCUMENT_CODE_TO_NAME 映射到代码）

    Returns:
        (tc_dict, rc_dict) 按资产代码 key；若文件不存在或解析失败则返回 None
    """
    path = os.path.join(_get_data_dir(), "资产费用.xlsx")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_excel(path)
        # 兼容多种列名
        asset_col = None
        for c in ["资产", "资产代码", "资产名称"]:
            if c in df.columns:
                asset_col = c
                break
        tc_col = None
        for c in ["交易费率", "交易成本", "trading_cost"]:
            if c in df.columns:
                tc_col = c
                break
        rc_col = None
        for c in ["复制费率", "复制成本", "replication_cost"]:
            if c in df.columns:
                rc_col = c
                break
        if asset_col is None or (tc_col is None and rc_col is None):
            return None

        name_to_code = _build_name_to_code()
        tc_dict: Dict[str, float] = {}
        rc_dict: Dict[str, float] = {}

        for _, row in df.iterrows():
            asset_raw = row.get(asset_col)
            if pd.isna(asset_raw):
                continue
            asset_str = str(asset_raw).strip()
            code = asset_str if asset_str in (all_assets or []) else name_to_code.get(asset_str, asset_str)
            if tc_col is not None:
                v = row.get(tc_col)
                if pd.notna(v):
                    try:
                        tc_dict[code] = float(v)
                    except (ValueError, TypeError):
                        pass
            if rc_col is not None:
                v = row.get(rc_col)
                if pd.notna(v):
                    try:
                        rc_dict[code] = float(v)
                    except (ValueError, TypeError):
                        pass

        if not tc_dict and not rc_dict:
            return None
        return (tc_dict, rc_dict)
    except Exception:
        return None


def get_asset_costs_with_fallback(
    all_assets: List[str],
    transaction_costs: Optional[Dict[str, float]] = None,
    replication_costs: Optional[Dict[str, float]] = None,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    获取资产费率：优先 Excel，其次传入参数，最后内置默认。
    """
    tc = dict(transaction_costs) if transaction_costs else {}
    rc = dict(replication_costs) if replication_costs else {}

    loaded = load_asset_costs_from_data(all_assets)
    if loaded:
        tc_loaded, rc_loaded = loaded
        for a in all_assets:
            if a in tc_loaded and a not in tc:
                tc[a] = tc_loaded[a]
            if a in rc_loaded and a not in rc:
                rc[a] = rc_loaded[a]

    for a in all_assets:
        if a not in tc:
            tc[a] = _DEFAULT_TRADING_COST.get(a, 0.001)
        if a not in rc:
            rc[a] = _DEFAULT_REPLICATION_COST.get(a, 0.005)

    return tc, rc


# =============================================================================
# 数据结构
# =============================================================================

@dataclass
class PendingRebalance:
    signal_date: pd.Timestamp
    execute_date: pd.Timestamp
    weights: Dict[str, float]
    rebalance_type: str  # 'monthly' | 'vol_reset'
    signal_weights: Optional[Dict[str, float]] = None
    vol_trigger: Optional[float] = None
    scale_factor: Optional[float] = None


@dataclass
class BacktestState:
    assets: List[str]
    nav: float = BASE_VALUE
    nav_base: float = BASE_VALUE
    positions_cny: Dict[str, float] = field(default_factory=dict)
    positions_local: Dict[str, float] = field(default_factory=dict)
    apl_local: Dict[str, float] = field(default_factory=dict)
    target_weights: Dict[str, float] = field(default_factory=dict)
    pending_rebalance: Optional[PendingRebalance] = None
    last_rebalance_date: Optional[pd.Timestamp] = None
    last_rebalance_fx: Dict[str, float] = field(default_factory=dict)
    total_trading_cost: float = 0.0
    total_replication_cost: float = 0.0

    def __post_init__(self):
        for a in self.assets:
            self.positions_cny.setdefault(a, 0.0)
            self.positions_local.setdefault(a, 0.0)
            self.apl_local.setdefault(a, 0.0)
            self.target_weights.setdefault(a, 0.0)
            self.last_rebalance_fx.setdefault(a, 1.0)


# =============================================================================
# 汇率与收益率
# =============================================================================

def _get_fx_from_rates(
    fx_rates: Dict[str, pd.Series],
    asset: str,
    date: pd.Timestamp,
) -> float:
    if not fx_rates or asset not in fx_rates:
        return 1.0
    ser = fx_rates[asset]
    if date in ser.index:
        v = ser.loc[date]
        return float(v) if pd.notna(v) else 1.0
    valid = ser.index[ser.index <= date]
    if len(valid) > 0:
        v = ser.loc[valid[-1]]
        return float(v) if pd.notna(v) else 1.0
    return 1.0


def _get_fx_from_df(
    fx_df: pd.DataFrame,
    date: pd.Timestamp,
    currency: str,
) -> float:
    if currency == "CNH" or currency == "CNY":
        return 1.0
    if currency not in fx_df.columns:
        return 1.0
    if date in fx_df.index:
        r = fx_df.loc[date, currency]
        return float(r) if pd.notna(r) else 1.0
    valid = fx_df.index[fx_df.index <= date]
    for d in reversed(valid.tolist()):
        r = fx_df.loc[d, currency]
        if pd.notna(r):
            return float(r)
    return 1.0


def _calc_asset_returns(
    prices: pd.DataFrame,
    date: pd.Timestamp,
    prev_date: pd.Timestamp,
    assets: List[str],
    fx_rates_t: Dict[str, float],
    fx_rates_prev: Dict[str, float],
) -> Tuple[Dict[str, float], Dict[str, float]]:
    ret_local = {}
    ret_cny = {}
    for a in assets:
        p1 = prices.loc[date, a]
        p0 = prices.loc[prev_date, a]
        if pd.notna(p1) and pd.notna(p0) and p0 > 0:
            ret_local[a] = float(p1 / p0 - 1)
        else:
            ret_local[a] = 0.0
        p1_cny = p1 * fx_rates_t.get(a, 1.0)
        p0_cny = p0 * fx_rates_prev.get(a, 1.0)
        if pd.notna(p1_cny) and pd.notna(p0_cny) and p0_cny > 0:
            ret_cny[a] = float(p1_cny / p0_cny - 1)
        else:
            ret_cny[a] = 0.0
    return ret_local, ret_cny


def _calc_realized_vol(
    weights: Dict[str, float],
    daily_ret_df: pd.DataFrame,
    date: pd.Timestamp,
    assets: List[str],
    windows: List[int] = VOL_WINDOWS,
) -> float:
    try:
        ytd = daily_ret_df.loc[:date, assets]
    except Exception:
        return 0.0
    if ytd.empty or len(ytd) < 2:
        return 0.0
    w = pd.Series(weights)
    vols = []
    for n in windows:
        if len(ytd) >= n:
            window_ret = ytd.iloc[-n:]
            wr = (window_ret * w).sum(axis=1)
            std_val = wr.std()
            if pd.notna(std_val) and std_val > 0:
                vols.append(float(std_val * np.sqrt(260)))
    return max(vols) if vols else 0.0


# =============================================================================
# 每日操作
# =============================================================================

def _handle_index_start(
    state: BacktestState,
    date: pd.Timestamp,
    initial_weights: Dict[str, float],
    fx_rates: Dict[str, float],
) -> None:
    state.nav = BASE_VALUE
    state.nav_base = BASE_VALUE
    for a in state.assets:
        w = initial_weights.get(a, 0.0)
        state.positions_cny[a] = state.nav * w
        state.positions_local[a] = state.positions_cny[a] / fx_rates.get(a, 1.0)
        state.apl_local[a] = 0.0
        state.target_weights[a] = w
    state.last_rebalance_date = date
    state.last_rebalance_fx = dict(fx_rates)


def _handle_daily_pnl_update(
    state: BacktestState,
    date: pd.Timestamp,
    prev_date: pd.Timestamp,
    ret_local: Dict[str, float],
    ret_cny: Dict[str, float],
    fx_rates: Dict[str, float],
    rc: Dict[str, float],
    enable_costs: bool,
) -> float:
    daily_rc = 0.0
    days_between = (date - prev_date).days
    for a in state.assets:
        if state.positions_cny.get(a, 0) == 0:
            continue
        rl = ret_local.get(a, 0.0)
        rcny = ret_cny.get(a, 0.0)
        pnl_local = state.positions_local[a] * rl
        rc_cost_local = 0.0
        if enable_costs:
            r = rc.get(a, 0.005)
            rc_cost_local = state.positions_local[a] * (r / 365.0) * days_between
            daily_rc += rc_cost_local * fx_rates.get(a, 1.0)
        state.apl_local[a] += pnl_local - rc_cost_local
        state.positions_local[a] *= 1 + rl
        state.positions_cny[a] *= 1 + rcny
    total_apl_cny = sum(state.apl_local[a] * fx_rates.get(a, 1.0) for a in state.assets)
    state.nav = state.nav_base + total_apl_cny
    state.total_replication_cost += daily_rc
    return daily_rc


def _handle_rebalance_execute(
    state: BacktestState,
    date: pd.Timestamp,
    prev_nav: float,
    fx_rates: Dict[str, float],
    tc: Dict[str, float],
    enable_costs: bool,
    trades: List[dict],
) -> float:
    pending = state.pending_rebalance
    if pending is None:
        return 0.0
    new_weights = pending.weights
    trading_cost = 0.0
    if enable_costs:
        for a in state.assets:
            target_local = prev_nav * new_weights.get(a, 0) / fx_rates.get(a, 1.0)
            curr_local = state.positions_local[a]
            amt = abs(target_local - curr_local)
            t = tc.get(a, 0.001)
            trading_cost += amt * t * fx_rates.get(a, 1.0)
            if amt >= 1e-9:
                trades.append({
                    "time": date,
                    "thscode": a,
                    "side": "buy" if target_local > curr_local else "sell",
                    "quantity": amt,
                    "price": 1.0,
                    "commission": amt * t,
                    "slippage_cost": 0.0,
                })
        state.nav -= trading_cost
    for a in state.assets:
        w = new_weights.get(a, 0.0)
        state.positions_cny[a] = prev_nav * w
        state.positions_local[a] = state.positions_cny[a] / fx_rates.get(a, 1.0)
        state.apl_local[a] = 0.0
        state.target_weights[a] = w
    state.nav_base = state.nav
    state.last_rebalance_date = date
    state.last_rebalance_fx = dict(fx_rates)
    state.pending_rebalance = None
    state.total_trading_cost += trading_cost
    return trading_cost


def _handle_volatility_monitor(
    state: BacktestState,
    date: pd.Timestamp,
    date_idx: int,
    daily_ret_df: pd.DataFrame,
    trade_dates_list: List[pd.Timestamp],
    rebalance_dates_set: Set[pd.Timestamp],
    vol_reset_dates_set: Set[pd.Timestamp],
    vol_trigger_threshold: float,
    vol_target: float,
    exclude_dates: Optional[Set[pd.Timestamp]],
) -> Optional[PendingRebalance]:
    """
    波动率监控：仅在以下全部满足时才下发波动率重置：
    1. 实现波动率 > vol_trigger_threshold（默认 6%，不是目标 5%）
    2. 已过 MONITOR_START_DAYS（60 日）
    3. 信号日、T+1、执行日 T+2 与月度调仓/已有波动率重置无冲突
    4. 当日无待执行调仓（pending_rebalance 为空）且非调仓执行日
    5. 未来至少有两个交易日可供 T+2 执行
    6. 执行日不在 exclude_dates 中（否则顺延到下一交易日，若无则不触发）
    因此“组合波动率超出目标值但未触发”常见原因：未超过触发阈值、[t,T+1,T+2] 冲突、已有待执行调仓。
    """
    if date_idx < MONITOR_START_DAYS:
        return None
    if state.nav <= 0:
        return None
    w_cny = {
        a: state.positions_local[a] * state.last_rebalance_fx.get(a, 1.0) / state.nav
        for a in state.assets
    }
    vol_trigger = _calc_realized_vol(w_cny, daily_ret_df, date, state.assets)
    if vol_trigger <= vol_trigger_threshold:
        return None
    future_dates = [d for d in trade_dates_list if d > date]
    if len(future_dates) < 2:
        return None
    execute_date = future_dates[1]
    if exclude_dates:
        while execute_date in exclude_dates:
            next_d = [d for d in trade_dates_list if d > execute_date]
            if not next_d:
                return None
            execute_date = next_d[0]
    t_plus_1 = future_dates[0]
    # 集合为归一化日期，比较时归一化
    date_n = pd.Timestamp(date).normalize()
    t_plus_1_n = pd.Timestamp(t_plus_1).normalize()
    exec_n = pd.Timestamp(execute_date).normalize()
    has_conflict = (
        date_n in rebalance_dates_set or date_n in vol_reset_dates_set
        or t_plus_1_n in rebalance_dates_set or t_plus_1_n in vol_reset_dates_set
        or exec_n in rebalance_dates_set or exec_n in vol_reset_dates_set
    )
    if has_conflict:
        return None
    scale_factor = vol_target / vol_trigger
    vw_weights = {a: w * scale_factor for a, w in w_cny.items()}
    vw_weights = {a: np.trunc(w * 1000) / 1000 for a, w in vw_weights.items()}
    return PendingRebalance(
        signal_date=date,
        execute_date=execute_date,
        weights=vw_weights,
        rebalance_type="vol_reset",
        signal_weights=dict(w_cny),
        vol_trigger=vol_trigger,
        scale_factor=scale_factor,
    )


def _record_state(state: BacktestState, date: pd.Timestamp) -> dict:
    record = {
        "日期": date,
        "净值": state.nav,
        "总杠杆": sum(state.positions_cny.values()) / state.nav if state.nav > 0 else 0,
    }
    for a in state.assets:
        record[a] = state.positions_cny[a] / state.nav if state.nav > 0 else 0
    return record


# =============================================================================
# 主回测函数
# =============================================================================

def run_backtest_fx_inmem(
    prices: pd.DataFrame,
    rebalance_map: Dict[pd.Timestamp, Dict[str, float]],
    trade_dates_list: List[pd.Timestamp],
    trade_dates_set: Set[pd.Timestamp],
    base_date: pd.Timestamp = BASE_DATE,
    base_value: float = BASE_VALUE,
    enable_vol_control: bool = False,
    enable_costs: bool = True,
    enable_fx: bool = True,
    fx_df: Optional[pd.DataFrame] = None,
    fx_rates: Optional[Dict[str, pd.Series]] = None,
    transaction_costs: Optional[Dict[str, float]] = None,
    replication_costs: Optional[Dict[str, float]] = None,
    asset_currency: Optional[Dict[str, str]] = None,
    exclude_dates: Optional[Set[pd.Timestamp]] = None,
    vol_trigger_threshold: float = VOL_TRIGGER_THRESHOLD,
    vol_target: float = VOL_TARGET,
):
    """
    使用内存数据运行回测（V4 逻辑）。仅由 hybrid_momentum_engine 调用。

    波动率阈值重置：仅当组合实现波动率 > vol_trigger_threshold 时触发（默认 6%），
    重置后目标为 vol_target（默认 5%）。若希望“超过目标波动率就触发”，
    可传入 vol_trigger_threshold=vol_target（例如均为 0.05）。

    Returns:
        nav_df, vol_reset_events, cost_summary, trades
    """
    assets = prices.columns.tolist()
    ac = asset_currency or {}
    tc, rc = get_asset_costs_with_fallback(
        assets, transaction_costs, replication_costs
    )

    use_fx_df = fx_df
    if enable_fx and (not fx_rates or len(fx_rates) == 0) and (use_fx_df is None or use_fx_df.empty):
        use_fx_df = _load_fx_from_data_fallback()

    def get_fx(date: pd.Timestamp, asset: str) -> float:
        if not enable_fx:
            return 1.0
        if fx_rates and asset in fx_rates:
            return _get_fx_from_rates(fx_rates, asset, date)
        if use_fx_df is not None and not use_fx_df.empty and asset in ac:
            currency = ac.get(asset, "CNH")
            return _get_fx_from_df(use_fx_df, date, currency)
        return 1.0

    # 归一化日期集合，避免 prices.index 的 datetime64 与 rebalance_map 的 Timestamp 比较失败，导致波动率重置日未执行
    rebalance_dates_set = set(pd.Timestamp(k).normalize() for k in rebalance_map.keys())
    rebalance_norm_to_key = {pd.Timestamp(k).normalize(): k for k in rebalance_map.keys()}
    backtest_dates = prices.index[prices.index >= base_date].tolist()
    if not backtest_dates:
        empty = pd.DataFrame(columns=["净值", "总杠杆"] + assets)
        return empty, [], {"trading_cost": 0, "replication_cost": 0, "total_cost": 0}, []

    daily_ret_df = prices[assets].pct_change(fill_method=None).fillna(0)
    first_exec = min(rebalance_map.keys()) if rebalance_map else None
    initial_weights = rebalance_map[first_exec].copy() if first_exec else {a: 0.0 for a in assets}

    state = BacktestState(assets=assets)
    nav_history: List[dict] = []
    vol_reset_events: List[dict] = []
    trades: List[dict] = []
    vol_reset_dates_set: Set[pd.Timestamp] = set()  # 存归一化日期，便于与 date 比较
    prev_date: Optional[pd.Timestamp] = None
    prev_nav: Optional[float] = None

    for date_idx, date in enumerate(backtest_dates):
        if date not in prices.index:
            continue
        date_norm = pd.Timestamp(date).normalize()
        fx_rates_t = {a: get_fx(date, a) for a in assets}
        fx_rates_prev = {a: get_fx(prev_date, a) for a in assets} if prev_date else fx_rates_t

        if date == base_date:
            _handle_index_start(state, date, initial_weights, fx_rates_t)
            nav_history.append(_record_state(state, date))
            prev_date = date
            prev_nav = state.nav
            continue

        ret_local, ret_cny = _calc_asset_returns(
            prices, date, prev_date, assets, fx_rates_t, fx_rates_prev
        )
        _handle_daily_pnl_update(state, date, prev_date, ret_local, ret_cny, fx_rates_t, rc, enable_costs)

        is_rebalance_day = False

        # 波动率重置执行日：按日归一化比较，避免 date(datetime64) 与 execute_date(Timestamp) 不相等
        if state.pending_rebalance is not None and date_norm == pd.Timestamp(state.pending_rebalance.execute_date).normalize():
            pending = state.pending_rebalance
            _handle_rebalance_execute(state, date, prev_nav or state.nav, fx_rates_t, tc, enable_costs, trades)
            is_rebalance_day = True
            if pending.rebalance_type == "vol_reset":
                vol_reset_events.append({
                    "信号日期": pending.signal_date,
                    "执行日期": date,
                    "VolTrigger": pending.vol_trigger,
                    "触发阈值": vol_trigger_threshold,
                    "目标波动率": vol_target,
                    "缩放因子": pending.scale_factor,
                    "触发时权重": (pending.signal_weights or {}).copy(),
                    "重置后权重": pending.weights.copy(),
                })

        if date_norm in rebalance_dates_set and not is_rebalance_day:
            key = rebalance_norm_to_key.get(date_norm)
            if key is not None:
                state.pending_rebalance = PendingRebalance(
                    signal_date=date,
                    execute_date=date,
                    weights=rebalance_map[key],
                    rebalance_type="monthly",
                )
                _handle_rebalance_execute(state, date, prev_nav or state.nav, fx_rates_t, tc, enable_costs, trades)
                is_rebalance_day = True
                state.pending_rebalance = None

        if (
            enable_vol_control
            and state.pending_rebalance is None
            and not is_rebalance_day
        ):
            pending = _handle_volatility_monitor(
                state, date, date_idx, daily_ret_df,
                trade_dates_list, rebalance_dates_set, vol_reset_dates_set,
                vol_trigger_threshold, vol_target, exclude_dates or SKIP_EXCLUDED_DATES,
            )
            if pending is not None:
                state.pending_rebalance = pending
                vol_reset_dates_set.add(pd.Timestamp(pending.execute_date).normalize())

        nav_history.append(_record_state(state, date))
        prev_date = date
        prev_nav = state.nav

    nav_df = pd.DataFrame(nav_history).set_index("日期") if nav_history else pd.DataFrame()
    cost_summary = {
        "trading_cost": state.total_trading_cost,
        "replication_cost": state.total_replication_cost,
        "total_cost": state.total_trading_cost + state.total_replication_cost,
    }
    return nav_df, vol_reset_events, cost_summary, trades
