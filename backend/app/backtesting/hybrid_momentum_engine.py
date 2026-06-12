# -*- coding: utf-8 -*-
"""
risk_budget_target_vol 混合动量策略 - 全链路回测引擎

【重要】本模块仅应用于 risk_budget_target_vol 的混合动量资产选择策略，
不应用于其他任何策略。其他策略使用通用 BacktestEngine。

流程：prices -> step1 资产选择 -> step2 权重计算 -> step3 回测（FX、波动率监控、成本）
编制规则：执行日 = 月末最后交易日后的第2个交易日（T+2）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

try:
    from loguru import logger as _loguru
except ImportError:
    _loguru = None

from app.config.asset_cost_currency import ASSET_CURRENCY_BY_CODE
from app.config.hybrid_momentum_rbtv_defaults import (
    EXECUTION_DELAY_DAYS,
    MONITOR_START_DAYS,
    TARGET_VOL,
    VOL_MONITOR_WINDOWS,
    VOL_RESET_THRESHOLD,
)
from app.config.zy_document_max_weights import ZY_DOCUMENT_CODE_TO_NAME
try:
    from app.data.trade_dates import load_trade_dates
except ModuleNotFoundError:
    from data.trade_dates import load_trade_dates
from app.selection.engine_reference import calc_weights_for_date, select_assets_for_date

from app.backtesting.types import PortfolioSnapshot, Trade

# 全链路回测优先使用 step3_backtest_fx_v4（V4 逻辑），失败回退到 v1
_USE_STEP3_BACKTEST = True
run_backtest_fx_inmem = None
try:
    from app.selection.step_files.step3_backtest_fx_v4 import run_backtest_fx_inmem
except Exception:
    try:
        from app.selection.step_files.step3_backtest_fx_v1 import run_backtest_fx_inmem
    except Exception:
        _USE_STEP3_BACKTEST = False
from app.backtesting.analytics import PerformanceAnalyzer
from app.analysis.formulas.drawdown import calculate_drawdown_series

_log = logging.getLogger(__name__)


# 编制规则：2015-01-01、01-02、01-05 为排除日，若 T+2 落于此则顺延至下一交易日
_SKIP_EXCLUDED_DATES = {
    pd.Timestamp("2015-01-01"),
    pd.Timestamp("2015-01-02"),
    pd.Timestamp("2015-01-05"),
}

# 净值诊断区间：排查 01-05 净值异常
_NAV_DIAG_START = pd.Timestamp("2014-12-31")
_NAV_DIAG_END = pd.Timestamp("2015-01-07")

# 2015-01-15 前后监控时段：打印持仓、持仓变化、交易明细、占比、总净值计算
_MONITOR_0115_START = pd.Timestamp("2015-01-10")
_MONITOR_0115_END = pd.Timestamp("2015-01-20")


def _in_nav_diag_range(d: pd.Timestamp) -> bool:
    return _NAV_DIAG_START <= pd.Timestamp(d) <= _NAV_DIAG_END


def _in_monitor_0115_range(d: pd.Timestamp) -> bool:
    return _MONITOR_0115_START <= pd.Timestamp(d) <= _MONITOR_0115_END


def _skip_excluded_execute_date(execute_date: pd.Timestamp, trade_dates_list: List[pd.Timestamp]) -> pd.Timestamp:
    """若执行日在排除日，顺延至下一交易日（循环直至非排除日）"""
    while execute_date in _SKIP_EXCLUDED_DATES:
        next_dates = [d for d in trade_dates_list if d > execute_date]
        if not next_dates:
            break
        execute_date = next_dates[0]
    return execute_date


def _get_fx_rate(
    fx_rates: Dict[str, pd.Series],
    asset_code: str,
    date: pd.Timestamp,
    asset_currency_by_code: Dict[str, str],
) -> float:
    """获取资产在指定日期的汇率（本币/CNY），CNH 返回 1.0"""
    currency = asset_currency_by_code.get(asset_code, "CNH")
    if currency == "CNH":
        return 1.0
    if not fx_rates or asset_code not in fx_rates:
        return 1.0
    ser = fx_rates[asset_code]
    if date in ser.index:
        return float(ser.loc[date])
    valid = ser.index[ser.index <= date]
    if len(valid) > 0:
        return float(ser.loc[valid[-1]])
    return 1.0


def _calc_realized_vol(
    weights: Dict[str, float],
    daily_ret_df: pd.DataFrame,
    date: pd.Timestamp,
    windows: List[int] = VOL_MONITOR_WINDOWS,
) -> float:
    """组合实现波动率：max{σ_22, σ_65, σ_130}"""
    try:
        ytd = daily_ret_df.loc[:date]
    except Exception:
        return 0.0
    if ytd.empty or len(ytd) < 2:
        return 0.0
    w = pd.Series(weights)
    common = [c for c in w.index if c in ytd.columns and w[c] > 0]
    if not common:
        return 0.0
    port_ret = (ytd[common] * w[common]).sum(axis=1)
    vols = []
    for n in windows:
        if len(port_ret) >= n:
            window_ret = port_ret.iloc[-n:]
            std_val = window_ret.std()
            if pd.notna(std_val) and std_val > 0:
                vol = float(std_val * np.sqrt(260))
                vols.append(vol)
    return max(vols) if vols else 0.0


def _calc_vw_weights(
    current_weights: Dict[str, float],
    vol_trigger: float,
    target_vol: float = TARGET_VOL,
) -> Tuple[Dict[str, float], float]:
    """波动率重置：VW = (target_vol / vol_trigger) × current_weights"""
    if vol_trigger <= 0:
        return current_weights, 1.0
    scale = target_vol / vol_trigger
    return {a: w * scale for a, w in current_weights.items()}, scale


@dataclass
class HybridMomentumConfig:
    """混合动量回测配置"""

    base_date: pd.Timestamp = field(default_factory=lambda: pd.Timestamp("2014-02-10"))
    selection_start_date: pd.Timestamp = field(default_factory=lambda: pd.Timestamp("2014-01-31"))  # 资产选择/权重计算起始日，用于初始化仓位
    base_value: float = 1000.0
    target_vol: float = TARGET_VOL
    vol_trigger_threshold: float = VOL_RESET_THRESHOLD
    max_leverage: float = 4.0
    min_history_days: int = 260
    top_momentum: int = 7
    weight_caps: Optional[Dict[str, float]] = None
    transaction_costs: Optional[Dict[str, float]] = None
    replication_costs: Optional[Dict[str, float]] = None
    fx_rates: Optional[Dict[str, pd.Series]] = None
    enable_vol_control: bool = False
    enable_costs: bool = True
    enable_fx: bool = True
    # 汇率损益公式：False=含汇率(昨日)，True=去掉汇率(昨日)仅用(汇率今日/昨日-1)，支持回退
    fx_pnl_exclude_fx_yesterday: bool = True
    risk_budget_both: Optional[float] = None    # None 时使用 engine_reference 硬编码默认值 (2/8)
    risk_budget_single: Optional[float] = None  # None 时使用 engine_reference 硬编码默认值 (1/8)


def run_hybrid_momentum_backtest(
    prices: pd.DataFrame,
    config: Optional[HybridMomentumConfig] = None,
) -> Dict[str, Any]:
    """
    运行混合动量全链路回测。

    Args:
        prices: 资产价格 DataFrame，index=日期，columns=资产代码
        config: 回测配置，None 时使用默认值

    Returns:
        {
            "snapshots": List[PortfolioSnapshot],
            "trades": List[Trade],
            "vol_reset_events": List[Dict],
            "selection_records": List[Dict],
            "weight_records": List[Dict],
            "performance": Dict,
            "nav_series": pd.Series,
            "trade_dates_set": Set[pd.Timestamp],
        }
    """
    cfg = config or HybridMomentumConfig()
    _log.info(f"[BacktestEngine] enable_vol_control={cfg.enable_vol_control}")
    all_assets = list(prices.columns)
    prices = prices[all_assets].dropna(how="all").ffill().bfill()

    # 交易日历
    loaded = load_trade_dates()
    if loaded:
        trade_dates_list, trade_dates_set = loaded
    else:
        trade_dates_list = sorted(prices.index.tolist())
        trade_dates_set = set(trade_dates_list)

    # 每月最后一个交易日（用于 T+2 计算）
    selection_start = pd.Timestamp(cfg.selection_start_date)

    month_last_trade: Dict[pd.Period, pd.Timestamp] = {}
    for d in trade_dates_list:
        if d >= selection_start:
            month_last_trade[d.to_period("M")] = d

    # 计算日：从 selection_start_date（2014-01-31）起每月末，用于初始化仓位
    prices_for_calc = prices[prices.index >= selection_start]
    if prices_for_calc.empty:
        prices_for_calc = prices
    calc_dates_raw = prices_for_calc.groupby(prices_for_calc.index.to_period("M")).apply(lambda x: x.index[-1])
    if hasattr(calc_dates_raw, "values"):
        calc_dates_list = calc_dates_raw.tolist()
    else:
        calc_dates_list = [calc_dates_raw]
    calc_dates_list = [d for d in calc_dates_list if pd.Timestamp(d) >= selection_start]

    # 回测循环从 base_date（2014-02-10）起
    prices_filtered = prices[prices.index >= cfg.base_date]
    if prices_filtered.empty:
        return _empty_result(cfg.base_value, all_assets, trade_dates_set)

    # Step1 + Step2：资产选择与权重计算
    rebalance_map: Dict[pd.Timestamp, Dict[str, float]] = {}
    selection_records: List[Dict[str, Any]] = []
    weight_records: List[Dict[str, Any]] = []
    weight_caps = cfg.weight_caps or {}
    for code in all_assets:
        if code not in weight_caps:
            weight_caps[code] = 0.10  # 默认

    for calc_date in calc_dates_list:
        try:
            date_idx = prices.index.get_loc(calc_date)
        except (KeyError, TypeError):
            continue
        if date_idx < cfg.min_history_days:
            continue

        # effective_calc: 该月最后一个交易日
        period = pd.Timestamp(calc_date).to_period("M")
        effective_calc = month_last_trade.get(period, pd.Timestamp(calc_date))

        future_dates = [d for d in trade_dates_list if d > effective_calc]
        if len(future_dates) < 2:
            continue

        execute_date = future_dates[1]  # T+2
        _exec_before_skip = execute_date
        execute_date = _skip_excluded_execute_date(execute_date, trade_dates_list)

        _log_fn = _loguru if _loguru is not None else _log
        skip_note = " (排除日顺延)" if _exec_before_skip != execute_date else ""
        msg = (
            f"[T+2执行日] {pd.Timestamp(calc_date).strftime('%Y-%m-%d')} "
            f"月末最后交易日={pd.Timestamp(effective_calc).strftime('%Y-%m-%d')} "
            f"T+1={pd.Timestamp(future_dates[0]).strftime('%Y-%m-%d')} "
            f"T+2={pd.Timestamp(future_dates[1]).strftime('%Y-%m-%d')} "
            f"最终执行日={pd.Timestamp(execute_date).strftime('%Y-%m-%d')}{skip_note}"
        )
        _log_fn.info(msg)

        # Step1: 资产选择
        nav = prices.iloc[: date_idx + 1]
        sel = select_assets_for_date(
            nav=nav,
            date_idx=date_idx,
            calc_date=pd.Timestamp(calc_date),
            min_history=cfg.min_history_days,
            top_momentum=cfg.top_momentum,
        )
        valid_assets = sel.get("有效资产", [])
        final_selected = sel.get("最终入选", [])
        selection_row = sel.get("入选矩阵_row", {})
        for a in all_assets:
            if a not in selection_row:
                selection_row[a] = 0

        selection_records.append({
            "calc_date": calc_date,
            "valid_assets": valid_assets,
            "momentum_selected": sel.get("动量入选", []),
            "reversal_selected": sel.get("反转入选", []),
            "final_selected": final_selected,
            "ranking_df": sel.get("动量排名"),
            "reversal_ranking_df": sel.get("反转排名"),
        })

        if not final_selected:
            continue

        # Step2: 权重计算
        w_res = calc_weights_for_date(
            nav=nav,
            date_idx=date_idx,
            selection_row=selection_row,
            all_assets=all_assets,
            target_vol=cfg.target_vol,
            max_leverage=cfg.max_leverage,
            weight_caps=weight_caps,
            fillna_zero=True,                              # 修复 Bug：统一为 True
            risk_budget_both=cfg.risk_budget_both,          # 新增
            risk_budget_single=cfg.risk_budget_single,      # 新增
        )
        final_weights = w_res.get("最终权重", {})
        if isinstance(final_weights, pd.Series):
            final_weights = final_weights.to_dict()

        weight_records.append({
            "calc_date": calc_date,
            "final_weights": final_weights,
            "portfolio_vol": w_res.get("组合波动率", 0),
            "scale": w_res.get("缩放系数", 1),
            "total_leverage": w_res.get("总杠杆", 0),
            "risk_budgets": w_res.get("风险预算", {}),
            "asset_vols": w_res.get("资产波动率", {}),
            "initial_weights": w_res.get("初始权重", {}),
            "scaled_weights": w_res.get("缩放后权重", {}),
            "selection_status": selection_row,
        })

        rebalance_map[execute_date] = final_weights

    # Step3: 回测循环（仅本策略使用 step3_backtest_fx_v1，fx 从 data/fx.xlsx 回退）
    loop_dates = prices_filtered.index.tolist()
    if not loop_dates:
        return _empty_result(cfg.base_value, all_assets, trade_dates_set)

    daily_ret_df = prices.pct_change(fill_method=None).fillna(0)
    tc = cfg.transaction_costs or {}
    rc = cfg.replication_costs or {}
    for code in all_assets:
        if code not in tc:
            tc[code] = 0.001
        if code not in rc:
            rc[code] = 0.005

    if _USE_STEP3_BACKTEST and run_backtest_fx_inmem is not None:
        try:
            nav_df, vol_reset_events, cost_summary, step3_trades = run_backtest_fx_inmem(
                prices=prices_filtered,
                rebalance_map=rebalance_map,
                trade_dates_list=trade_dates_list,
                trade_dates_set=trade_dates_set,
                base_date=pd.Timestamp(cfg.base_date),
                base_value=cfg.base_value,
                enable_vol_control=cfg.enable_vol_control,
                enable_costs=cfg.enable_costs,
                enable_fx=cfg.enable_fx,
                fx_rates=cfg.fx_rates or None,
                transaction_costs=tc,
                replication_costs=rc,
                asset_currency=ASSET_CURRENCY_BY_CODE,
                exclude_dates=_SKIP_EXCLUDED_DATES,
                vol_trigger_threshold=cfg.vol_trigger_threshold,
                vol_target=cfg.target_vol,
            )
            nav_series = nav_df["净值"] if "净值" in nav_df.columns else nav_df.iloc[:, 0]
            snapshots = []
            # 用日期字符串 YYYY-MM-DD 做集合与比较，避免 Timestamp/datetime64 类型或精度差异导致波动率重置被标成周期性调仓
            def _date_str(x) -> str:
                return str(pd.Timestamp(x).normalize())[:10]

            rebalance_dates_str = {_date_str(k) for k in rebalance_map.keys()} | {
                _date_str(e.get("执行日期") or e.get("execute_date")) for e in vol_reset_events
            }
            vol_reset_exec_str = {_date_str(e.get("执行日期") or e.get("execute_date")) for e in vol_reset_events}
            rebalance_map_key_str = {_date_str(k) for k in rebalance_map.keys()}
            for i, (dt, row) in enumerate(nav_df.iterrows()):
                tv = float(row.get("净值", row.iloc[0]))
                w = {a: float(row.get(a, 0)) for a in all_assets if a in row.index}
                dt_str = _date_str(dt)
                is_reb = dt_str in rebalance_dates_str
                reb_type = "vol_reset" if (dt_str in vol_reset_exec_str) else ("regular" if (dt_str in rebalance_map_key_str) else None)
                reb_reason = "波动率触发重置" if reb_type == "vol_reset" else ("周期性调仓" if is_reb else None)
                port_vol = None
                if cfg.enable_vol_control and not daily_ret_df.empty:
                    try:
                        ytd = daily_ret_df.loc[:dt]
                        if len(ytd) >= 22:
                            w_ser = pd.Series(w)
                            common = [c for c in w_ser.index if c in ytd.columns and w_ser[c] > 0]
                            if common:
                                pr = (ytd[common] * w_ser[common]).sum(axis=1)
                                for n in VOL_MONITOR_WINDOWS:
                                    if len(pr) >= n:
                                        port_vol = float(pr.iloc[-n:].std() * np.sqrt(260))
                                        break
                    except Exception:
                        pass
                snapshots.append(
                    PortfolioSnapshot(
                        time=dt,
                        total_value=tv,
                        cash=0.0,
                        holdings_value=tv,
                        weights=w,
                        is_rebalance_day=is_reb,
                        rebalance_type=reb_type,
                        rebalance_reason=reb_reason,
                        portfolio_volatility=port_vol,
                    )
                )
            trades = [
                Trade(
                    time=t["time"],
                    thscode=t["thscode"],
                    side=t["side"],
                    quantity=t["quantity"],
                    price=t["price"],
                    commission=t["commission"],
                    slippage_cost=t["slippage_cost"],
                )
                for t in step3_trades
            ]
            perf_analyzer = PerformanceAnalyzer(risk_free_rate=0.02)
            summary = perf_analyzer.from_results(snapshots, trades)
            performance = {
                "start_date": str(loop_dates[0])[:10],
                "end_date": str(loop_dates[-1])[:10],
                "initial_nav": cfg.base_value,
                "final_nav": float(nav_series.iloc[-1]) if not nav_series.empty else cfg.base_value,
                "total_return": summary.total_return,
                "annual_return": summary.annual_return,
                "volatility": summary.volatility,
                "max_drawdown": summary.max_drawdown,
                "sharpe_ratio": summary.sharpe_ratio,
                "calmar_ratio": summary.calmar_ratio,
            }
            return {
                "snapshots": snapshots,
                "trades": trades,
                "vol_reset_events": vol_reset_events,
                "selection_records": selection_records,
                "weight_records": weight_records,
                "performance": performance,
                "nav_series": nav_series,
                "trade_dates_set": trade_dates_set,
            }
        except Exception as e:
            _log.warning("[混合动量] step3 回测失败，回退至内置循环: %s", e)

    # [净值诊断] 预计算阶段：价格矩阵、asset_returns、价格链
    _log_fn = _loguru if _loguru is not None else _log
    diag_dates = [d for d in loop_dates if _in_nav_diag_range(d)]
    if diag_dates:
        _log_fn.info("[净值诊断] 预计算阶段 12-31～01-07")
        px_sub = prices.loc[prices.index.isin(diag_dates), all_assets]
        _log_fn.info("[净值诊断] 价格矩阵 12-31～01-07:\n%s" % px_sub.to_string())
        for j in range(1, len(loop_dates)):
            d = loop_dates[j]
            prev = loop_dates[j - 1]
            if not _in_nav_diag_range(d) and not _in_nav_diag_range(prev):
                continue
            if prev not in prices.index or d not in prices.index:
                continue
            rets = {}
            for a in all_assets:
                p0, p1 = prices.loc[prev, a], prices.loc[d, a]
                if p0 and not np.isnan(p0) and not np.isnan(p1):
                    r = (p1 - p0) / p0
                    if abs(r) > 1e-10:
                        rets[a] = (float(p0), float(p1), r)
            if rets:
                ret_str = {a: (f"p0={v[0]:.4f} p1={v[1]:.4f} ret={v[2]:.6f}") for a, v in rets.items()}
                _log_fn.info(
                    "[净值诊断] 价格链 %s: prev=%s ret(非零)=%s"
                    % (pd.Timestamp(d).strftime("%Y-%m-%d"), pd.Timestamp(prev).strftime("%Y-%m-%d"), ret_str)
                )

    index_value = cfg.base_value
    first_execute = min(rebalance_map.keys()) if rebalance_map else None
    if first_execute:
        current_weights = rebalance_map[first_execute].copy()
    else:
        current_weights = {a: 0.0 for a in all_assets}
    positions_local = {a: 0.0 for a in all_assets}
    positions_cny = {a: 0.0 for a in all_assets}
    init_date = loop_dates[0]
    fx_rates = cfg.fx_rates or {}
    for asset in all_assets:
        fx = _get_fx_rate(fx_rates, asset, init_date, ASSET_CURRENCY_BY_CODE) if cfg.enable_fx else 1.0
        w = current_weights.get(asset, 0)
        positions_local[asset] = index_value * w / fx
        positions_cny[asset] = index_value * w

    if _in_nav_diag_range(init_date):
        nonzero_w = {a: w for a, w in current_weights.items() if w and abs(w) > 1e-9}
        nonzero_pl = {a: v for a, v in positions_local.items() if v and abs(v) > 1e-9}
        nonzero_pc = {a: v for a, v in positions_cny.items() if v and abs(v) > 1e-9}
        _log_fn.info(
            "[净值诊断] 初始建仓 %s: index_value=%s base_value=%s current_weights(非零)=%s positions_local(非零)=%s positions_cny(非零)=%s",
            pd.Timestamp(init_date).strftime("%Y-%m-%d"),
            index_value,
            cfg.base_value,
            nonzero_w,
            nonzero_pl,
            nonzero_pc,
        )

    snapshots: List[PortfolioSnapshot] = []
    trades: List[Trade] = []
    vol_reset_events: List[Dict[str, Any]] = []
    vol_reset_dates_set: Set[pd.Timestamp] = set()
    pending_vol_reset: Optional[Dict[str, Any]] = None
    prev_date: Optional[pd.Timestamp] = None
    prev_day_positions_local: Dict[str, float] = {}
    prev_day_positions_cny: Dict[str, float] = {}

    for i, date in enumerate(loop_dates):
        if date not in prices.index:
            continue

        daily_tc_total = 0.0
        fx_rates_t = {}
        if cfg.enable_fx and fx_rates:
            for a in all_assets:
                fx_rates_t[a] = _get_fx_rate(fx_rates, a, date, ASSET_CURRENCY_BY_CODE)
        else:
            for a in all_assets:
                fx_rates_t[a] = 1.0

        fx_rates_prev: Dict[str, float] = {}
        if prev_date is not None and cfg.enable_fx and fx_rates:
            for a in all_assets:
                fx_rates_prev[a] = _get_fx_rate(fx_rates, a, prev_date, ASSET_CURRENCY_BY_CODE)
        else:
            fx_rates_prev = {a: 1.0 for a in all_assets}

        index_value_before = index_value
        daily_replication_cost = 0.0
        rc_detail: Dict[str, float] = {}
        if cfg.enable_costs and prev_date is not None:
            days_between = (date - prev_date).days
            for a in all_assets:
                if positions_local[a] > 0:
                    rc_cost = positions_local[a] * (rc.get(a, 0.005) / 365.0) * days_between
                    rc_cny = rc_cost * fx_rates_t[a]
                    daily_replication_cost += rc_cny
                    if abs(rc_cny) > 1e-9:
                        rc_detail[a] = rc_cny
        index_value -= daily_replication_cost

        daily_pnl_cny = 0.0
        pnl_detail: List[str] = []
        fx_pnl_detail: List[str] = []
        if i > 0:
            prev = loop_dates[i - 1]
            if prev in prices.index and date in prices.index:
                for a in all_assets:
                    p0 = prices.loc[prev, a]
                    p1 = prices.loc[date, a]
                    if p0 and not np.isnan(p0) and not np.isnan(p1):
                        ret = (p1 - p0) / p0
                        pnl_local = positions_local[a] * ret
                        pnl_cny_val = pnl_local * fx_rates_t[a]
                        daily_pnl_cny += pnl_cny_val
                        positions_local[a] *= 1 + ret
                        positions_cny[a] = positions_local[a] * fx_rates_t[a]
                        if _in_nav_diag_range(date) and positions_local[a] and abs(positions_local[a]) > 1e-9:
                            pos_prev = positions_local[a] / (1 + ret) if abs(1 + ret) > 1e-10 else 0
                            fx_ratio = fx_rates_t[a] / fx_rates_prev[a] - 1 if fx_rates_prev[a] and abs(fx_rates_prev[a]) > 1e-10 else 0
                            price_pnl = pos_prev * ret * fx_rates_prev[a]
                            fx_today = fx_rates_t[a]
                            fx_yest = fx_rates_prev[a]
                            if getattr(cfg, "fx_pnl_exclude_fx_yesterday", True):
                                fx_pnl = pos_prev * ret * fx_ratio
                                pnl_detail.append(
                                    f"    {a}: 前日收盘价={p0:.4f} 当日收盘价={p1:.4f} => 收益率=({p1:.4f}-{p0:.4f})/{p0:.4f}={ret:.6f}\n"
                                    f"       持仓(本币)={pos_prev:.4f} 汇率(昨日)={fx_yest:.6f} 汇率(今日)={fx_today:.6f}\n"
                                    f"       价格损益=持仓×收益率×汇率(昨日)={pos_prev:.4f}×{ret:.6f}×{fx_yest:.4f}={price_pnl:.6f}\n"
                                    f"       汇率损益=持仓×收益率×(汇率(今日)/汇率(昨日)-1)={pos_prev:.4f}×{ret:.6f}×({fx_today:.6f}/{fx_yest:.6f}-1)={fx_pnl:.6f}\n"
                                    f"       => 损益(人民币)=持仓×收益率×汇率(今日)={pnl_cny_val:.6f}"
                                )
                            else:
                                fx_pnl = pos_prev * ret * fx_rates_prev[a] * fx_ratio
                                pnl_detail.append(
                                    f"    {a}: 前日收盘价={p0:.4f} 当日收盘价={p1:.4f} => 收益率=({p1:.4f}-{p0:.4f})/{p0:.4f}={ret:.6f}\n"
                                    f"       持仓(本币)={pos_prev:.4f} 汇率(昨日)={fx_yest:.6f} 汇率(今日)={fx_today:.6f}\n"
                                    f"       价格损益=持仓×收益率×汇率(昨日)={pos_prev:.4f}×{ret:.6f}×{fx_yest:.4f}={price_pnl:.6f}\n"
                                    f"       汇率损益=持仓×收益率×汇率(昨日)×(汇率(今日)/汇率(昨日)-1)={pos_prev:.4f}×{ret:.6f}×{fx_yest:.4f}×({fx_today:.6f}/{fx_yest:.6f}-1)={fx_pnl:.6f}\n"
                                    f"       => 损益(人民币)=价格损益+汇率损益={pnl_cny_val:.6f}"
                                )
                        # 汇率损益：含汇率(昨日)时=持仓×收益率×汇率(昨日)×(汇率今日/昨日-1)；去掉时=持仓×收益率×(汇率今日/昨日-1)，支持回退
                        pos_prev = positions_local[a] / (1 + ret) if abs(1 + ret) > 1e-10 else 0
                        fx_ratio = fx_rates_t[a] / fx_rates_prev[a] - 1 if fx_rates_prev[a] and abs(fx_rates_prev[a]) > 1e-10 else 0
                        if _in_nav_diag_range(date) and positions_local[a] and abs(positions_local[a]) > 1e-9:
                            if getattr(cfg, "fx_pnl_exclude_fx_yesterday", True):
                                fx_pnl = pos_prev * ret * fx_ratio
                                fx_pnl_detail.append(
                                    f"    {a}: 收益率=(当日收盘价-前日收盘价)/前日收盘价=({p1:.4f}-{p0:.4f})/{p0:.4f}={ret:.6f}\n"
                                    f"       汇率损益=持仓×收益率×(汇率(今日)/汇率(昨日)-1) "
                                    f"= {pos_prev:.4f}×{ret:.6f}×({fx_rates_t[a]:.6f}/{fx_rates_prev[a]:.6f}-1) "
                                    f"= {pos_prev:.4f}×{ret:.6f}×{fx_ratio:.6f} = {fx_pnl:.6f}"
                                )
                            else:
                                fx_pnl = pos_prev * ret * fx_rates_prev[a] * fx_ratio
                                fx_pnl_detail.append(
                                    f"    {a}: 收益率=(当日收盘价-前日收盘价)/前日收盘价=({p1:.4f}-{p0:.4f})/{p0:.4f}={ret:.6f}\n"
                                    f"       汇率损益=持仓×收益率×汇率(昨日)×(汇率(今日)/汇率(昨日)-1) "
                                    f"= {pos_prev:.4f}×{ret:.6f}×{fx_rates_prev[a]:.6f}×({fx_rates_t[a]:.6f}/{fx_rates_prev[a]:.6f}-1) "
                                    f"= {pos_prev:.4f}×{ret:.6f}×{fx_rates_prev[a]:.6f}×{fx_ratio:.6f} = {fx_pnl:.6f}"
                                )
        index_value += daily_pnl_cny

        if _in_nav_diag_range(date):
            days_between = (date - prev_date).days if prev_date else 0
            nonzero_pl = {a: v for a, v in positions_local.items() if v and abs(v) > 1e-9}
            nonzero_w = {a: positions_cny[a] / index_value for a in all_assets if index_value and abs(positions_cny[a] / index_value) > 1e-9}
            prev_str = pd.Timestamp(prev_date).strftime("%Y-%m-%d") if prev_date else "None"
            _log_fn.info(
                "[净值诊断] 每日循环 %s: prev_date=%s days_between=%s index_value_before=%.6f daily_pnl_cny=%.6f daily_rc=%.6f index_value_after=%.6f"
                % (pd.Timestamp(date).strftime("%Y-%m-%d"), prev_str, days_between, index_value_before, daily_pnl_cny, daily_replication_cost, index_value)
            )
            _log_fn.info("[净值诊断] positions_local(非零)=%s current_weights(非零)=%s" % (nonzero_pl, nonzero_w))
            if pnl_detail:
                _log_fn.info("[净值诊断] PnL明细(价格损益+汇率损益):\n%s" % "\n".join(pnl_detail))
            if fx_pnl_detail:
                formula_note = "持仓×收益率×(汇率今日/汇率昨日-1)" if getattr(cfg, "fx_pnl_exclude_fx_yesterday", True) else "持仓×收益率×汇率(昨日)×(汇率今日/汇率昨日-1)"
                _log_fn.info("[净值诊断] 汇率损益(%s):\n%s" % (formula_note, "\n".join(fx_pnl_detail)))
            if rc_detail:
                _log_fn.info("[净值诊断] 复制费用 daily_rc=%.6f 各资产=%s" % (daily_replication_cost, rc_detail))
            is_reb = date in rebalance_map
            _log_fn.info("[净值诊断] is_rebalance=%s" % is_reb)

        # 01-05、01-06 完整公式块
        if _in_nav_diag_range(date) and date in (pd.Timestamp("2015-01-05"), pd.Timestamp("2015-01-06")):
            prev = loop_dates[i - 1] if i > 0 else None
            lines = [
                f"########## [净值诊断] 重点日期 {pd.Timestamp(date).strftime('%Y-%m-%d')} 完整公式 ##########",
                "  【完整净值公式】当日净值 = 昨日净值 + Σ(各资产: 持仓×收益率×汇率) - 复制费用",
                "  其中: 收益率 = (当日收盘价 - 前日收盘价) / 前日收盘价",
            ]
            for a in all_assets:
                if prev not in prices.index or date not in prices.index:
                    continue
                p0, p1 = prices.loc[prev, a], prices.loc[date, a]
                if not p0 or np.isnan(p0) or np.isnan(p1):
                    continue
                ret = (p1 - p0) / p0
                pos_before = positions_local[a] / (1 + ret) if abs(1 + ret) > 1e-10 else 0
                pnl_cny_val = pos_before * ret * fx_rates_t[a]
                fx_prev = fx_rates_prev.get(a, 1.0)
                fx_ratio = fx_rates_t[a] / fx_prev - 1 if fx_prev and abs(fx_prev) > 1e-10 else 0
                price_pnl = pos_before * ret * fx_prev
                if getattr(cfg, "fx_pnl_exclude_fx_yesterday", True):
                    fx_pnl = pos_before * ret * fx_ratio
                    lines.append(f"    {a}: 前日收盘价={p0:.4f} 当日收盘价={p1:.4f} => 收益率=({p1:.4f}-{p0:.4f})/{p0:.4f}={ret:.6f}")
                    lines.append(f"       价格损益=持仓{pos_before:.4f}×收益率{ret:.6f}×汇率(昨日){fx_prev:.4f}={price_pnl:.6f}")
                    lines.append(f"       汇率损益(去汇率昨日)=持仓×收益率×(汇率今日/汇率昨日-1)={pos_before:.4f}×{ret:.6f}×({fx_rates_t[a]:.6f}/{fx_prev:.6f}-1)={fx_pnl:.6f}")
                    lines.append(f"       => 损益(人民币)=持仓×收益率×汇率(今日)={pnl_cny_val:.6f} (简化公式下价格+汇率≠总损益)")
                else:
                    fx_pnl = pos_before * ret * fx_prev * fx_ratio
                    lines.append(f"    {a}: 前日收盘价={p0:.4f} 当日收盘价={p1:.4f} => 收益率=({p1:.4f}-{p0:.4f})/{p0:.4f}={ret:.6f}")
                    lines.append(f"       价格损益=持仓{pos_before:.4f}×收益率{ret:.6f}×汇率(昨日){fx_prev:.4f}={price_pnl:.6f}")
                    lines.append(f"       汇率损益=持仓×收益率×汇率(昨日)×(汇率今日/汇率昨日-1)={pos_before:.4f}×{ret:.6f}×{fx_prev:.4f}×({fx_rates_t[a]:.6f}/{fx_prev:.6f}-1)={fx_pnl:.6f}")
                    lines.append(f"       => 损益(人民币)=价格损益+汇率损益={pnl_cny_val:.6f}")
            lines.append(f"  Σ各资产损益(人民币) = {daily_pnl_cny:.6f}")
            nav_prev = index_value_before
            lines.append(f"  昨日净值={nav_prev:.6f} + 当日损益={daily_pnl_cny:.6f} - 复制费用={daily_replication_cost:.6f} => 当日净值={index_value:.6f}")
            lines.append(f"########## [净值诊断] 重点日期 {pd.Timestamp(date).strftime('%Y-%m-%d')} 结束 ##########")
            _log_fn.info("\n".join(lines))

        is_vol_reset_day = False
        if cfg.enable_vol_control and pending_vol_reset is not None:
            # 按日归一化比较，避免 date 与 执行日期 类型不一致导致波动率重置未执行
            if pd.Timestamp(date).normalize() == pd.Timestamp(pending_vol_reset.get("执行日期")).normalize():
                vol_trigger = pending_vol_reset["vol_trigger"]
                signal_weights = pending_vol_reset["signal_weights"]
                new_weights, scale_factor = _calc_vw_weights(signal_weights, vol_trigger, cfg.target_vol)
                if cfg.enable_costs:
                    tc_cost = 0.0
                    for a in all_assets:
                        target_cny = index_value * new_weights.get(a, 0)
                        curr_cny = positions_cny[a]
                        tc_cost += abs(target_cny - curr_cny) * tc.get(a, 0.001)
                    daily_tc_total = tc_cost
                    index_value -= tc_cost
                    for t in _emit_trades(date, positions_cny, new_weights, index_value, all_assets, tc):
                        trades.append(t)
                current_weights = new_weights
                for a in all_assets:
                    positions_cny[a] = index_value * current_weights.get(a, 0)
                    positions_local[a] = positions_cny[a] / fx_rates_t[a]
                vol_reset_events.append({
                    "signal_date": pending_vol_reset["信号日期"],
                    "execute_date": date,
                    "vol_trigger": vol_trigger,
                    "threshold": cfg.vol_trigger_threshold,
                    "target_vol": cfg.target_vol,
                    "scale_factor": scale_factor,
                    "trigger_weights": signal_weights,
                    "reset_weights": new_weights,
                })
                pending_vol_reset = None
                is_vol_reset_day = True

        date_norm = pd.Timestamp(date).normalize()
        rebalance_key = next((k for k in rebalance_map if pd.Timestamp(k).normalize() == date_norm), None)
        if rebalance_key is not None and not is_vol_reset_day:
            new_weights = rebalance_map[rebalance_key]
            daily_tc = 0.0
            if cfg.enable_costs:
                tc_cost = 0.0
                for a in all_assets:
                    target_cny = index_value * new_weights.get(a, 0)
                    curr_cny = positions_cny[a]
                    tc_cost += abs(target_cny - curr_cny) * tc.get(a, 0.001)
                daily_tc = tc_cost
                daily_tc_total = tc_cost
                index_value -= tc_cost
                for t in _emit_trades(date, positions_cny, new_weights, index_value, all_assets, tc):
                    trades.append(t)
            current_weights = new_weights
            for a in all_assets:
                positions_cny[a] = index_value * current_weights.get(a, 0)
                positions_local[a] = positions_cny[a] / fx_rates_t[a]
            pending_vol_reset = None
            if _in_nav_diag_range(date):
                nonzero_nw = {a: v for a, v in new_weights.items() if v and abs(v) > 1e-9}
                _log_fn.info(
                    "[净值诊断] 调仓日 %s: 调仓后 index_value=%.6f daily_tc=%.6f new_weights(非零)=%s"
                    % (pd.Timestamp(date).strftime("%Y-%m-%d"), index_value, daily_tc, nonzero_nw)
                )
        actual_weights = (
            {a: positions_cny[a] / index_value for a in all_assets}
            if index_value > 0
            else current_weights.copy()
        )
        port_vol = _calc_realized_vol(actual_weights, daily_ret_df, date) if cfg.enable_vol_control else None

        if cfg.enable_vol_control and pending_vol_reset is None and i >= MONITOR_START_DAYS:
            vol_trigger = _calc_realized_vol(actual_weights, daily_ret_df, date)
            if vol_trigger > cfg.vol_trigger_threshold:
                future_td = [d for d in trade_dates_list if d > date]
                if len(future_td) >= 2:
                    exec_date = future_td[1]
                    exec_date = _skip_excluded_execute_date(exec_date, trade_dates_list)
                    if exec_date not in rebalance_map and exec_date not in vol_reset_dates_set:
                        pending_vol_reset = {
                            "执行日期": exec_date,
                            "信号日期": date,
                            "vol_trigger": vol_trigger,
                            "signal_weights": actual_weights.copy(),
                        }
                        vol_reset_dates_set.add(exec_date)

        is_reb = (date in rebalance_map and not is_vol_reset_day) or (
            cfg.enable_vol_control and pending_vol_reset is not None and date == pending_vol_reset.get("执行日期")
        )
        if is_vol_reset_day:
            reb_type, reb_reason = "vol_reset", "波动率触发重置"
        elif date in rebalance_map:
            reb_type, reb_reason = "regular", "周期性调仓"
        else:
            reb_type, reb_reason = None, None

        # 2015-01-15 前后监控：打印持仓、持仓变化、交易明细、占比、总净值计算
        if _in_monitor_0115_range(date):
            code_to_name = ZY_DOCUMENT_CODE_TO_NAME
            pos_local_named = {code_to_name.get(a, a): v for a, v in positions_local.items() if v and abs(v) > 1e-9}
            pos_cny_named = {code_to_name.get(a, a): v for a, v in positions_cny.items() if v and abs(v) > 1e-9}
            delta_cny = {code_to_name.get(a, a): positions_cny[a] - prev_day_positions_cny.get(a, 0) for a in all_assets if abs(positions_cny[a] - prev_day_positions_cny.get(a, 0)) > 1e-9}
            try:
                trades_today = [t for t in trades if getattr(t, "time", None) is not None and pd.Timestamp(getattr(t, "time", None)).normalize() == pd.Timestamp(date).normalize()]
            except Exception:
                trades_today = []
            trades_detail = [{"资产": code_to_name.get(getattr(t, "thscode", ""), getattr(t, "thscode", "")), "方向": getattr(t, "side", ""), "数量": getattr(t, "quantity", 0), "佣金": getattr(t, "commission", 0)} for t in trades_today]
            weights_named = {code_to_name.get(a, a): actual_weights.get(a, 0) for a in all_assets if actual_weights.get(a, 0) and abs(actual_weights.get(a, 0)) > 1e-9}
            _log_fn.info(
                "[监控0115] ========== %s ==========\n"
                "  持仓(本币): %s\n  持仓(人民币): %s\n  持仓变化(人民币): %s\n"
                "  交易明细: %s\n  占比: %s\n"
                "  总净值计算: 昨日净值(含复制费后)=%.6f + 当日损益=%.6f - 复制费用=%.6f - 交易成本=%.6f => 当日净值=%.6f"
                % (
                    pd.Timestamp(date).strftime("%Y-%m-%d"),
                    pos_local_named,
                    pos_cny_named,
                    delta_cny,
                    trades_detail,
                    weights_named,
                    index_value_before,
                    daily_pnl_cny,
                    daily_replication_cost,
                    daily_tc_total,
                    index_value,
                )
            )

        prev_day_positions_local = {a: positions_local[a] for a in all_assets}
        prev_day_positions_cny = {a: positions_cny[a] for a in all_assets}
        snap = PortfolioSnapshot(
            time=date,
            total_value=index_value,
            cash=0.0,
            holdings_value=index_value,
            weights=actual_weights,
            is_rebalance_day=is_reb,
            rebalance_type=reb_type,
            rebalance_reason=reb_reason,
            portfolio_volatility=port_vol,
        )
        snapshots.append(snap)
        prev_date = date

    nav_series = pd.Series([s.total_value for s in snapshots], index=[s.time for s in snapshots])
    perf_analyzer = PerformanceAnalyzer(risk_free_rate=0.02)
    summary = perf_analyzer.from_results(snapshots, trades)
    performance = {
        "start_date": str(loop_dates[0])[:10],
        "end_date": str(loop_dates[-1])[:10],
        "initial_nav": cfg.base_value,
        "final_nav": float(nav_series.iloc[-1]) if not nav_series.empty else cfg.base_value,
        "total_return": summary.total_return,
        "annual_return": summary.annual_return,
        "volatility": summary.volatility,
        "max_drawdown": summary.max_drawdown,
        "sharpe_ratio": summary.sharpe_ratio,
        "calmar_ratio": summary.calmar_ratio,
    }

    return {
        "snapshots": snapshots,
        "trades": trades,
        "vol_reset_events": vol_reset_events,
        "selection_records": selection_records,
        "weight_records": weight_records,
        "performance": performance,
        "nav_series": nav_series,
        "trade_dates_set": trade_dates_set,
    }


def _emit_trades(
    date: pd.Timestamp,
    positions_cny: Dict[str, float],
    new_weights: Dict[str, float],
    index_value: float,
    all_assets: List[str],
    tc: Dict[str, float],
) -> List[Trade]:
    """生成调仓交易记录"""
    out: List[Trade] = []
    for a in all_assets:
        target_cny = index_value * new_weights.get(a, 0)
        curr_cny = positions_cny.get(a, 0)
        diff = target_cny - curr_cny
        if abs(diff) < 1e-9:
            continue
        side = "buy" if diff > 0 else "sell"
        qty = abs(diff)
        comm = qty * tc.get(a, 0.001)
        out.append(
            Trade(
                time=date,
                thscode=a,
                side=side,
                quantity=qty,
                price=1.0,
                commission=comm,
                slippage_cost=0.0,
            )
        )
    return out


def _empty_result(
    base_value: float,
    all_assets: List[str],
    trade_dates_set: Set[pd.Timestamp],
) -> Dict[str, Any]:
    """无数据时的空结果"""
    return {
        "snapshots": [],
        "trades": [],
        "vol_reset_events": [],
        "selection_records": [],
        "weight_records": [],
        "performance": {
            "start_date": "",
            "end_date": "",
            "initial_nav": base_value,
            "final_nav": base_value,
            "total_return": 0.0,
            "annual_return": 0.0,
            "volatility": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "calmar_ratio": 0.0,
        },
        "nav_series": pd.Series(dtype=float),
        "trade_dates_set": trade_dates_set,
    }
