# -*- coding: utf-8 -*-
"""
大类资产配置指数策略 - 第三步：净值计算与回测（V1版本 - portfilio-end 副本）

【仅用于】risk_budget_target_vol 混合动量资产选择策略的全链路回测，不应用于其他策略。

从 动量策略相关资料/step3_backtest_fx_v1.py 复制，供本地调用。
独立运行需：daily_px.xlsx、权重计算结果.xlsx 同目录；trade_dates.xlsx、fx.xlsx 置于 portfilio-end/data/。
"""

import pandas as pd
import numpy as np
import os
import contextlib
import matplotlib.pyplot as plt


@contextlib.contextmanager
def suppress_stderr():
    """在 OS 层面屏蔽 C 库（如 libpng）写入 stderr 的警告"""
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    old_stderr_fd = os.dup(2)
    os.dup2(devnull_fd, 2)
    os.close(devnull_fd)
    try:
        yield
    finally:
        os.dup2(old_stderr_fd, 2)
        os.close(old_stderr_fd)

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# =============================================================================
# 配置参数
# =============================================================================

BASE_DATE = pd.Timestamp('2014-02-10')
BASE_VALUE = 1000.0
RISK_FREE_RATE = 0.02
VOL_TRIGGER_THRESHOLD = 0.06
VOL_TARGET = 0.05
VOL_WINDOWS = [22, 65, 130]
DAYS_BEFORE_REBALANCE = 2

TRADING_COST = {
    '沪深300': 0.0010, '创业板指': 0.0010, '红利低波': 0.0010, '恒生科技': 0.0010,
    '标普500': 0.0010, '德国DAX': 0.0010, '中国10年国债': 0.0005, '中国2年国债': 0.0005,
    '布伦特原油': 0.0010, '黄金': 0.0010, '铁矿石': 0.0010, '中国有色金属': 0.0010,
    # 测试资产（与上同）
    '沪深300-测试': 0.0010, '创业板指-测试': 0.0010, '红利低波-测试': 0.0010,
    '恒生科技-测试': 0.0010, '标普500-测试': 0.0010, '德国DAX-测试': 0.0010,
    '中国10年国债-测试': 0.0005, '中国2年国债-测试': 0.0005,
    '布伦特原油-测试': 0.0010, '黄金-测试': 0.0010, '铁矿石-测试': 0.0010,
    '中国有色金属-测试': 0.0010,
    'SH000300_TEST': 0.0010, 'SZ399006_TEST': 0.0010, 'ZZ000001_TEST': 0.0010,
    'HSTECH_TEST': 0.0010, 'SPX_TEST': 0.0010, 'GDAXI_TEST': 0.0010,
    'ZQGZ10_TEST': 0.0005, 'ZQGZ2_TEST': 0.0005, 'B00Y_TEST': 0.0010,
    'GLD_TEST': 0.0010, 'IRON_TEST': 0.0010, 'YSJS_TEST': 0.0010,
}

REPLICATION_COST = {
    '沪深300': 0.0050, '创业板指': 0.0050, '红利低波': 0.0050, '恒生科技': 0.0050,
    '标普500': 0.0050, '德国DAX': 0.0050, '中国10年国债': 0.0030, '中国2年国债': 0.0030,
    '布伦特原油': 0.0050, '黄金': 0.0050, '铁矿石': 0.0050, '中国有色金属': 0.0050,
    # 测试资产（与上同）
    '沪深300-测试': 0.0050, '创业板指-测试': 0.0050, '红利低波-测试': 0.0050,
    '恒生科技-测试': 0.0050, '标普500-测试': 0.0050, '德国DAX-测试': 0.0050,
    '中国10年国债-测试': 0.0030, '中国2年国债-测试': 0.0030,
    '布伦特原油-测试': 0.0050, '黄金-测试': 0.0050, '铁矿石-测试': 0.0050,
    '中国有色金属-测试': 0.0050,
    'SH000300_TEST': 0.0050, 'SZ399006_TEST': 0.0050, 'ZZ000001_TEST': 0.0050,
    'HSTECH_TEST': 0.0050, 'SPX_TEST': 0.0050, 'GDAXI_TEST': 0.0050,
    'ZQGZ10_TEST': 0.0030, 'ZQGZ2_TEST': 0.0030, 'B00Y_TEST': 0.0050,
    'GLD_TEST': 0.0050, 'IRON_TEST': 0.0050, 'YSJS_TEST': 0.0050,
}

ASSET_CURRENCY = {
    '沪深300': 'CNH', '创业板指': 'CNH', '红利低波': 'CNH', '恒生科技': 'HKD',
    '标普500': 'USD', '德国DAX': 'EUR', '中国10年国债': 'CNH', '中国2年国债': 'CNH',
    '布伦特原油': 'USD', '黄金': 'CNH', '铁矿石': 'CNH', '中国有色金属': 'CNH',
    # 测试资产（与上同）
    '沪深300-测试': 'CNH', '创业板指-测试': 'CNH', '红利低波-测试': 'CNH',
    '恒生科技-测试': 'HKD', '标普500-测试': 'USD', '德国DAX-测试': 'EUR',
    '中国10年国债-测试': 'CNH', '中国2年国债-测试': 'CNH',
    '布伦特原油-测试': 'USD', '黄金-测试': 'CNH', '铁矿石-测试': 'CNH',
    '中国有色金属-测试': 'CNH',
    'SH000300_TEST': 'CNH', 'SZ399006_TEST': 'CNH', 'ZZ000001_TEST': 'CNH',
    'HSTECH_TEST': 'HKD', 'SPX_TEST': 'USD', 'GDAXI_TEST': 'EUR',
    'ZQGZ10_TEST': 'CNH', 'ZQGZ2_TEST': 'CNH', 'B00Y_TEST': 'USD',
    'GLD_TEST': 'CNH', 'IRON_TEST': 'CNH', 'YSJS_TEST': 'CNH',
}


# =============================================================================
# 绩效指标计算函数
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
    annual_return = calc_annual_return(nav_period)
    annual_vol = calc_annual_volatility(nav_period)
    max_dd, max_dd_date = calc_max_drawdown(nav_period)
    sharpe = calc_sharpe_ratio(nav_period)
    return {
        '时间段': period_name,
        '起始日期': nav_period.index[0],
        '结束日期': nav_period.index[-1],
        '起始净值': nav_period.iloc[0],
        '结束净值': nav_period.iloc[-1],
        '累计收益率': nav_period.iloc[-1] / nav_period.iloc[0] - 1,
        '年化收益率': annual_return,
        '年化波动率': annual_vol,
        '最大回撤': max_dd,
        '最大回撤日期': max_dd_date,
        '夏普比率': sharpe,
    }


PERIOD_CONFIG = [
    {'name': '全局', 'start': '2014-02-10', 'end': None},
    {'name': '2016年至今', 'start': '2016-01-01', 'end': None},
    {'name': '2019年至今', 'start': '2019-01-01', 'end': None},
    {'name': '2021年至今', 'start': '2021-01-01', 'end': None},
]


# =============================================================================
# 波动率监控函数（V1版本）
# =============================================================================

def calc_realized_vol_v1(weights, daily_ret, windows=VOL_WINDOWS):
    """
    外部系统的波动率计算函数
    vol = (daily_ret[-n:] * w).sum(axis=1).std() * sqrt(260)
    取 max{σ_22, σ_65, σ_130}
    """
    vol_values = []
    for n in windows:
        if len(daily_ret) >= n:
            ret_window = daily_ret.iloc[-n:]
            weighted_ret = (ret_window * weights).sum(axis=1)
            vol = weighted_ret.std() * np.sqrt(260)
            vol_values.append(vol)
    return max(vol_values) if vol_values else 0.0


def calc_sample_vol(returns, n):
    """样本标准差年化波动率"""
    if len(returns) < n:
        return 0.0
    ret_window = returns[-n:]
    mean_ret = np.mean(ret_window)
    sum_sq = np.sum((ret_window - mean_ret) ** 2)
    variance = 260.0 / (n - 1) * sum_sq
    return np.sqrt(variance)


def calc_vol_trigger(sim_returns, windows=VOL_WINDOWS):
    """计算VolTrigger = max{σ_22, σ_65, σ_130}"""
    vol_values = []
    for w in windows:
        if len(sim_returns) >= w:
            vol = calc_sample_vol(sim_returns, w)
            if not np.isnan(vol):
                vol_values.append(vol)
    return max(vol_values) if vol_values else 0.0


def calc_vw_weights(current_weights, vol_trigger, target_vol=VOL_TARGET):
    """计算波动率重置后的新权重：VW = (target_vol / vol_trigger) × current_weights"""
    scale_factor = target_vol / vol_trigger
    return {asset: w * scale_factor for asset, w in current_weights.items()}, scale_factor


# =============================================================================
# 汇率处理函数
# =============================================================================

def _get_data_dir():
    """获取 portfilio-end/data 目录路径"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
    return os.path.join(project_root, "data")


def load_fx_data(script_dir=None):
    """加载汇率数据，仅引用 portfilio-end/data/fx.xlsx"""
    if script_dir is None:
        data_dir = _get_data_dir()
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(script_dir))))
        data_dir = os.path.join(project_root, "data")
    fx_path = os.path.join(data_dir, "fx.xlsx")
    if not os.path.exists(fx_path):
        raise FileNotFoundError(f"汇率文件不存在: {fx_path}，请将 fx.xlsx 放置于 portfilio-end/data/")
    fx_df = pd.read_excel(fx_path, index_col=0, parse_dates=True)
    return fx_df


def load_fx_from_data_fallback():
    """
    从 data/fx.xlsx 加载汇率，支持回退。
    若文件不存在或读取失败，返回 None（调用方应禁用汇率或使用 1.0）。
    """
    try:
        fx_path = os.path.join(_get_data_dir(), "fx.xlsx")
        if not os.path.exists(fx_path):
            return None
        return pd.read_excel(fx_path, index_col=0, parse_dates=True)
    except Exception:
        return None


def get_fx_rate(fx_df, date, currency):
    """获取指定日期和货币的汇率"""
    if currency == 'CNH':
        return 1.0
    if currency not in fx_df.columns:
        return 1.0
    if date in fx_df.index:
        rate = fx_df.loc[date, currency]
        if not np.isnan(rate):
            return rate
    valid_dates = fx_df.index[fx_df.index <= date]
    for d in reversed(valid_dates):
        rate = fx_df.loc[d, currency]
        if not np.isnan(rate):
            return rate
    return 1.0


def get_asset_fx_rate(fx_df, date, asset, asset_currency=None):
    """获取指定资产在指定日期的汇率"""
    ac = asset_currency or ASSET_CURRENCY
    currency = ac.get(asset, 'CNH')
    return get_fx_rate(fx_df, date, currency)


def _get_fx_from_rates(fx_rates_dict, asset, date):
    """从 Dict[asset, pd.Series] 获取汇率，支持向前填充"""
    if not fx_rates_dict or asset not in fx_rates_dict:
        return 1.0
    ser = fx_rates_dict[asset]
    if date in ser.index:
        v = ser.loc[date]
        return float(v) if not (isinstance(v, float) and np.isnan(v)) else 1.0
    valid = ser.index[ser.index <= date]
    if len(valid) > 0:
        v = ser.loc[valid[-1]]
        return float(v) if not (isinstance(v, float) and np.isnan(v)) else 1.0
    return 1.0


# =============================================================================
# 主回测函数（汇率版）
# =============================================================================

def _load_trade_dates(script_dir):
    """加载交易日历：优先 portfilio-end/data/trade_dates.xlsx，其次同目录"""
    # step_files 在 app/selection/step_files/，dirname=selection，../../ = project_root
    project_data = os.path.join(os.path.dirname(script_dir), "..", "..", "data", "trade_dates.xlsx")
    paths = [
        os.path.abspath(project_data),
        os.path.join(script_dir, "trade_dates.xlsx"),
    ]
    for p in paths:
        abs_p = os.path.abspath(p)
        if os.path.exists(abs_p):
            df = pd.read_excel(abs_p)
            col = df["trade_dates"] if "trade_dates" in df.columns else df.iloc[:, 0]
            trade_dates_list = sorted(pd.to_datetime(col).dropna().unique().tolist())
            return trade_dates_list, set(trade_dates_list)
    raise FileNotFoundError("未找到 trade_dates.xlsx，请放置于 portfilio-end/data/ 或 step_files 同目录")


def _skip_excluded_execute_date(execute_date, trade_dates_list, exclude_dates):
    """若执行日在排除日，顺延至下一交易日"""
    if not exclude_dates:
        return execute_date
    while execute_date in exclude_dates:
        next_dates = [d for d in trade_dates_list if d > execute_date]
        if not next_dates:
            break
        execute_date = next_dates[0]
    return execute_date


def run_backtest_fx_inmem(
    prices,
    rebalance_map,
    trade_dates_list,
    trade_dates_set,
    base_date=BASE_DATE,
    base_value=BASE_VALUE,
    enable_vol_control=True,
    enable_costs=True,
    enable_fx=True,
    fx_df=None,
    fx_rates=None,
    transaction_costs=None,
    replication_costs=None,
    asset_currency=None,
    exclude_dates=None,
    vol_trigger_threshold=VOL_TRIGGER_THRESHOLD,
    vol_target=VOL_TARGET,
):
    """
    使用内存数据运行回测。仅由 hybrid_momentum_engine 调用，用于 risk_budget_target_vol 混合动量策略。

    fx 加载优先级：fx_rates > fx_df > data/fx.xlsx（回退）
    若三者皆无且 enable_fx，则禁用汇率（全部 1.0）。

    Returns:
        nav_df, vol_reset_events, cost_summary, trades
    """
    assets = prices.columns.tolist()
    ac = asset_currency or ASSET_CURRENCY
    tc = transaction_costs or TRADING_COST
    rc = replication_costs or REPLICATION_COST

    # fx: 优先级 fx_rates > fx_df > data/fx.xlsx
    use_fx_df = None
    use_fx_rates = None
    if enable_fx:
        if fx_rates and len(fx_rates) > 0:
            use_fx_rates = fx_rates
        elif fx_df is not None and not fx_df.empty:
            use_fx_df = fx_df
        else:
            use_fx_df = load_fx_from_data_fallback()
            if use_fx_df is None:
                use_fx_df = pd.DataFrame()

    def get_fx(date, asset):
        if not enable_fx:
            return 1.0
        if use_fx_rates:
            return _get_fx_from_rates(use_fx_rates, asset, date)
        if use_fx_df is not None and not use_fx_df.empty:
            return get_asset_fx_rate(use_fx_df, date, asset, ac)
        return 1.0

    rebalance_dates_set = set(rebalance_map.keys())
    backtest_dates = prices.index[prices.index >= base_date].tolist()
    if not backtest_dates:
        empty_nav = pd.DataFrame(columns=["净值", "总杠杆"] + assets)
        return empty_nav, [], {"trading_cost": 0, "replication_cost": 0, "total_cost": 0}, []

    asset_returns = {}
    for i in range(1, len(backtest_dates)):
        date, prev_date = backtest_dates[i], backtest_dates[i - 1]
        if date in prices.index and prev_date in prices.index:
            ret_dict = {}
            for asset in assets:
                p1, p0 = prices.loc[date, asset], prices.loc[prev_date, asset]
                ret_dict[asset] = p1 / p0 - 1 if not (np.isnan(p1) or np.isnan(p0)) and p0 > 0 else 0.0
            asset_returns[date] = ret_dict

    daily_ret_df = prices[assets].pct_change(fill_method=None).fillna(0)
    first_exec = min(rebalance_map.keys()) if rebalance_map else None
    current_weights = rebalance_map[first_exec].copy() if first_exec else {a: 0.0 for a in assets}
    index_value = base_value
    positions_local = {a: 0.0 for a in assets}
    positions_cny = {a: 0.0 for a in assets}
    init_date = backtest_dates[0]
    for asset in assets:
        fx_rate = get_fx(init_date, asset)
        w = current_weights.get(asset, 0.0)
        positions_local[asset] = index_value * w / fx_rate
        positions_cny[asset] = index_value * w

    nav_history = []
    vol_reset_events = []
    trades = []
    vol_reset_dates_set = set()
    pending_vol_reset = None
    total_trading_cost = 0.0
    total_replication_cost = 0.0
    prev_date = None
    apl_local = {a: 0.0 for a in assets}
    apl_cny = {a: 0.0 for a in assets}

    for date_idx, date in enumerate(backtest_dates):
        if date not in prices.index:
            continue
        daily_trading_cost = 0.0
        daily_replication_cost = 0.0
        fx_rates_t = {a: get_fx(date, a) for a in assets}

        if enable_costs and prev_date is not None:
            days_between = (date - prev_date).days
            for asset in assets:
                if positions_local[asset] > 0:
                    r = rc.get(asset, 0.005)
                    rc_cost_local = positions_local[asset] * (r / 365.0) * days_between
                    daily_replication_cost += rc_cost_local * fx_rates_t[asset]

        daily_pnl_cny = 0.0
        if date in asset_returns:
            for asset in assets:
                if positions_local[asset] != 0:
                    ret = asset_returns[date].get(asset, 0.0)
                    pnl_local = positions_local[asset] * ret
                    pnl_cny = pnl_local * fx_rates_t[asset]
                    daily_pnl_cny += pnl_cny
                    positions_local[asset] *= (1 + ret)
                    positions_cny[asset] = positions_local[asset] * fx_rates_t[asset]
                    apl_local[asset] += pnl_local
                    apl_cny[asset] = apl_local[asset] * fx_rates_t[asset]

        index_value += daily_pnl_cny - daily_replication_cost

        is_vol_reset_day = False
        if enable_vol_control and pending_vol_reset is not None:
            if date == pending_vol_reset["执行日期"]:
                vol_trigger = pending_vol_reset["vol_trigger"]
                signal_weights = pending_vol_reset["signal_weights"]
                new_weights, scale_factor = calc_vw_weights(signal_weights, vol_trigger, vol_target)
                if enable_costs:
                    for asset in assets:
                        target_cny = index_value * new_weights.get(asset, 0)
                        curr_cny = positions_cny[asset]
                        amt = abs(target_cny - curr_cny)
                        daily_trading_cost += amt * tc.get(asset, 0.001)
                        if amt >= 1e-9:
                            trades.append({
                                "time": date, "thscode": asset, "side": "buy" if target_cny > curr_cny else "sell",
                                "quantity": amt, "price": 1.0, "commission": amt * tc.get(asset, 0.001),
                                "slippage_cost": 0.0,
                            })
                    index_value -= daily_trading_cost
                current_weights = new_weights
                for asset in assets:
                    positions_cny[asset] = index_value * current_weights.get(asset, 0)
                    positions_local[asset] = positions_cny[asset] / fx_rates_t[asset]
                apl_local = {a: 0.0 for a in assets}
                apl_cny = {a: 0.0 for a in assets}
                vol_reset_events.append({
                    "信号日期": pending_vol_reset["信号日期"],
                    "执行日期": date,
                    "VolTrigger": vol_trigger,
                    "触发阈值": vol_trigger_threshold,
                    "目标波动率": vol_target,
                    "缩放因子": scale_factor,
                    "触发时权重": signal_weights.copy(),
                    "重置后权重": new_weights.copy(),
                })
                pending_vol_reset = None
                is_vol_reset_day = True

        if date in rebalance_dates_set and not is_vol_reset_day:
            new_weights = rebalance_map[date]
            if enable_costs:
                for asset in assets:
                    target_cny = index_value * new_weights.get(asset, 0)
                    curr_cny = positions_cny[asset]
                    amt = abs(target_cny - curr_cny)
                    daily_trading_cost += amt * tc.get(asset, 0.001)
                    if amt >= 1e-9:
                        trades.append({
                            "time": date, "thscode": asset, "side": "buy" if target_cny > curr_cny else "sell",
                            "quantity": amt, "price": 1.0, "commission": amt * tc.get(asset, 0.001),
                            "slippage_cost": 0.0,
                        })
                index_value -= daily_trading_cost
            current_weights = new_weights
            for asset in assets:
                positions_cny[asset] = index_value * current_weights.get(asset, 0)
                positions_local[asset] = positions_cny[asset] / fx_rates_t[asset]
            apl_local = {a: 0.0 for a in assets}
            apl_cny = {a: 0.0 for a in assets}
            pending_vol_reset = None

        actual_weights = {a: positions_cny[a] / index_value for a in assets} if index_value > 0 else current_weights.copy()

        if enable_vol_control and pending_vol_reset is None and date_idx >= 130:
            ytd_ret = daily_ret_df.loc[:date, assets]
            w = pd.Series(actual_weights)
            vol_trigger = calc_realized_vol_v1(w, ytd_ret)
            if vol_trigger > vol_trigger_threshold:
                future_td = [d for d in trade_dates_list if d > date]
                if len(future_td) >= 2:
                    exec_date = future_td[1]
                    if exclude_dates:
                        exec_date = _skip_excluded_execute_date(exec_date, trade_dates_list, exclude_dates)
                    dates_to_check = ([date] if date in trade_dates_set else []) + future_td[:2]
                    has_conflict = any(
                        d in rebalance_dates_set or d in vol_reset_dates_set for d in dates_to_check
                    )
                    if not has_conflict and exec_date not in rebalance_dates_set and exec_date not in vol_reset_dates_set:
                        pending_vol_reset = {
                            "执行日期": exec_date,
                            "信号日期": date,
                            "vol_trigger": vol_trigger,
                            "signal_weights": actual_weights.copy(),
                        }
                        vol_reset_dates_set.add(exec_date)

        total_trading_cost += daily_trading_cost
        total_replication_cost += daily_replication_cost
        record = {"日期": date, "净值": index_value, "总杠杆": sum(positions_cny.values()) / index_value if index_value > 0 else 0}
        for asset in assets:
            record[asset] = positions_cny[asset] / index_value if index_value > 0 else 0
        nav_history.append(record)
        prev_date = date

    nav_df = pd.DataFrame(nav_history).set_index("日期") if nav_history else pd.DataFrame()
    cost_summary = {
        "trading_cost": total_trading_cost,
        "replication_cost": total_replication_cost,
        "total_cost": total_trading_cost + total_replication_cost,
    }
    return nav_df, vol_reset_events, cost_summary, trades


def run_backtest_fx(enable_vol_control=True, enable_costs=True, enable_fx=True):
    """
    运行完整回测（含汇率转换）
    依赖：daily_px.xlsx, trade_dates.xlsx（portfilio-end/data/）, fx.xlsx, 权重计算结果.xlsx
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    print("=" * 70)
    print("大类资产配置指数策略 - 完整回测（V1版本）")
    print("=" * 70)

    trade_dates_list, trade_dates_set = _load_trade_dates(script_dir)

    prices = pd.read_excel(os.path.join(script_dir, 'daily_px.xlsx'), index_col=0, parse_dates=True)
    assets = prices.columns.tolist()

    fx_df = None
    if enable_fx:
        try:
            fx_df = load_fx_data(script_dir)
        except FileNotFoundError as e:
            print(f"  警告: {e}，汇率功能已禁用")
            enable_fx = False

    weights_df = pd.read_excel(os.path.join(script_dir, '权重计算结果.xlsx'), sheet_name='权重矩阵')
    weights_df['计算日期'] = pd.to_datetime(weights_df['计算日期'])

    rebalance_map = {}
    for i, row in weights_df.iterrows():
        calc_date = row['计算日期']
        future_dates = [d for d in trade_dates_list if d > calc_date]
        if len(future_dates) >= 2:
            adjust_date = future_dates[1]
        elif len(future_dates) == 1:
            adjust_date = future_dates[0]
        else:
            continue
        weight_dict = {asset: row.get(asset, 0.0) for asset in assets}
        rebalance_map[adjust_date] = weight_dict

    rebalance_dates_set = set(rebalance_map.keys())
    backtest_dates = prices.index[prices.index >= BASE_DATE].tolist()

    asset_returns = {}
    for i in range(1, len(backtest_dates)):
        date = backtest_dates[i]
        prev_date = backtest_dates[i - 1]
        if date in prices.index and prev_date in prices.index:
            ret_dict = {}
            for asset in assets:
                p1 = prices.loc[date, asset]
                p0 = prices.loc[prev_date, asset]
                ret_dict[asset] = p1 / p0 - 1 if not np.isnan(p1) and not np.isnan(p0) and p0 > 0 else 0.0
            asset_returns[date] = ret_dict

    daily_ret_df = prices[assets].pct_change().fillna(0)
    current_weights = {asset: weights_df.iloc[0].get(asset, 0.0) for asset in assets}
    index_value = BASE_VALUE
    positions_local = {asset: 0.0 for asset in assets}
    positions_cny = {asset: 0.0 for asset in assets}
    init_date = backtest_dates[0]
    for asset in assets:
        fx_rate = get_asset_fx_rate(fx_df, init_date, asset) if enable_fx and fx_df is not None else 1.0
        positions_local[asset] = index_value * current_weights[asset] / fx_rate
        positions_cny[asset] = index_value * current_weights[asset]

    nav_history = []
    vol_reset_events = []
    vol_reset_dates_set = set()
    pending_vol_reset = None
    total_trading_cost = 0.0
    total_replication_cost = 0.0
    prev_date = None
    apl_local = {asset: 0.0 for asset in assets}
    apl_cny = {asset: 0.0 for asset in assets}

    for date_idx, date in enumerate(backtest_dates):
        if date not in prices.index:
            continue
        daily_trading_cost = 0.0
        daily_replication_cost = 0.0
        fx_rates = {}
        if enable_fx and fx_df is not None:
            for asset in assets:
                fx_rates[asset] = get_asset_fx_rate(fx_df, date, asset)
        else:
            for asset in assets:
                fx_rates[asset] = 1.0

        if enable_costs and prev_date is not None:
            days_between = (date - prev_date).days
            for asset in assets:
                if positions_local[asset] > 0:
                    rc = REPLICATION_COST.get(asset, 0.005)
                    rc_cost_local = positions_local[asset] * (rc / 365.0) * days_between
                    rc_cost_cny = rc_cost_local * fx_rates[asset]
                    daily_replication_cost += rc_cost_cny

        daily_pnl_cny = 0.0
        if date in asset_returns:
            for asset in assets:
                if positions_local[asset] != 0:
                    ret = asset_returns[date].get(asset, 0.0)
                    pnl_local = positions_local[asset] * ret
                    pnl_cny = pnl_local * fx_rates[asset]
                    daily_pnl_cny += pnl_cny
                    positions_local[asset] *= (1 + ret)
                    positions_cny[asset] = positions_local[asset] * fx_rates[asset]
                    apl_local[asset] += pnl_local
                    apl_cny[asset] = apl_local[asset] * fx_rates[asset]

        index_value += daily_pnl_cny - daily_replication_cost

        is_vol_reset_day = False
        if enable_vol_control and pending_vol_reset is not None:
            if date == pending_vol_reset['执行日期']:
                vol_trigger = pending_vol_reset['vol_trigger']
                signal_weights = pending_vol_reset['signal_weights']
                new_weights, scale_factor = calc_vw_weights(signal_weights, vol_trigger)
                if enable_costs:
                    for asset in assets:
                        target_pos_cny = index_value * new_weights[asset]
                        current_pos_cny = positions_cny[asset]
                        trade_amount_cny = abs(target_pos_cny - current_pos_cny)
                        tc = TRADING_COST.get(asset, 0.001)
                        daily_trading_cost += trade_amount_cny * tc
                    index_value -= daily_trading_cost
                current_weights = new_weights
                for asset in assets:
                    positions_cny[asset] = index_value * current_weights[asset]
                    positions_local[asset] = positions_cny[asset] / fx_rates[asset]
                apl_local = {asset: 0.0 for asset in assets}
                apl_cny = {asset: 0.0 for asset in assets}
                vol_reset_events.append({
                    '信号日期': pending_vol_reset['信号日期'],
                    '执行日期': date,
                    'VolTrigger': vol_trigger,
                    '触发阈值': VOL_TRIGGER_THRESHOLD,
                    '目标波动率': VOL_TARGET,
                    '缩放因子': scale_factor,
                    '触发时权重': signal_weights.copy(),
                    '重置后权重': new_weights.copy(),
                })
                pending_vol_reset = None
                is_vol_reset_day = True

        if date in rebalance_dates_set and not is_vol_reset_day:
            new_weights = rebalance_map[date]
            if enable_costs:
                for asset in assets:
                    target_pos_cny = index_value * new_weights[asset]
                    current_pos_cny = positions_cny[asset]
                    trade_amount_cny = abs(target_pos_cny - current_pos_cny)
                    tc = TRADING_COST.get(asset, 0.001)
                    daily_trading_cost += trade_amount_cny * tc
                index_value -= daily_trading_cost
            current_weights = new_weights
            for asset in assets:
                positions_cny[asset] = index_value * current_weights[asset]
                positions_local[asset] = positions_cny[asset] / fx_rates[asset]
            apl_local = {asset: 0.0 for asset in assets}
            apl_cny = {asset: 0.0 for asset in assets}
            pending_vol_reset = None

        actual_weights = {asset: positions_cny[asset] / index_value for asset in assets} if index_value > 0 else current_weights.copy()

        if enable_vol_control and pending_vol_reset is None and date_idx >= 130:
            ytd_ret = daily_ret_df.loc[:date, assets]
            w = pd.Series(actual_weights)
            vol_trigger = calc_realized_vol_v1(w, ytd_ret)
            if vol_trigger > VOL_TRIGGER_THRESHOLD:
                future_trade_dates = [d for d in trade_dates_list if d > date]
                if len(future_trade_dates) >= 2:
                    dates_to_check = []
                    if date in trade_dates_set:
                        dates_to_check.append(date)
                    dates_to_check.extend(future_trade_dates[:2])
                    has_conflict = False
                    for check_date in dates_to_check:
                        if check_date in rebalance_dates_set or check_date in vol_reset_dates_set:
                            has_conflict = True
                            break
                    if not has_conflict:
                        execute_date = future_trade_dates[1]
                        pending_vol_reset = {
                            '执行日期': execute_date,
                            '信号日期': date,
                            'vol_trigger': vol_trigger,
                            'signal_weights': actual_weights.copy(),
                        }
                        vol_reset_dates_set.add(execute_date)

        total_trading_cost += daily_trading_cost
        total_replication_cost += daily_replication_cost
        record = {'日期': date, '净值': index_value, '总杠杆': sum(positions_cny.values()) / index_value if index_value > 0 else 0}
        for asset in assets:
            record[asset] = positions_cny[asset] / index_value if index_value > 0 else 0
        nav_history.append(record)
        prev_date = date

    nav_df = pd.DataFrame(nav_history)
    nav_df.set_index('日期', inplace=True)
    cost_summary = {
        'trading_cost': total_trading_cost,
        'replication_cost': total_replication_cost,
        'total_cost': total_trading_cost + total_replication_cost,
    }
    return nav_df, vol_reset_events, cost_summary


def run_full_analysis():
    """运行完整分析"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    nav_df, vol_events, costs = run_backtest_fx(enable_vol_control=True, enable_costs=True, enable_fx=True)
    nav_series = nav_df['净值']
    annual_return = calc_annual_return(nav_series)
    annual_vol = calc_annual_volatility(nav_series)
    max_dd, max_dd_date = calc_max_drawdown(nav_series)
    sharpe = calc_sharpe_ratio(nav_series)
    period_metrics_list = []
    for period in PERIOD_CONFIG:
        metrics = calc_period_metrics(nav_series, period['start'], period['end'], period['name'])
        if metrics:
            period_metrics_list.append(metrics)
    print("\n" + "=" * 70)
    print("绩效指标")
    print("=" * 70)
    print(f"  年化收益率: {annual_return * 100:.2f}%")
    print(f"  年化波动率: {annual_vol * 100:.2f}%")
    print(f"  最大回撤: {max_dd * 100:.2f}%")
    print(f"  夏普比率: {sharpe:.2f}")
    output_path = os.path.join(script_dir, '回测结果_汇率版_v1.xlsx')
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        nav_df.to_excel(writer, sheet_name='每日净值')
        if vol_events:
            events_df = pd.DataFrame([{
                '信号日期': e['信号日期'], '执行日期': e['执行日期'],
                'VolTrigger': e['VolTrigger'], '缩放因子': e['缩放因子'],
            } for e in vol_events])
            events_df.to_excel(writer, sheet_name='波动率重置事件', index=False)
    print(f"结果已保存至: {output_path}")
    return nav_df, vol_events, costs


if __name__ == '__main__':
    run_full_analysis()
