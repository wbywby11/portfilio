# -*- coding: utf-8 -*-
"""零漂移基线：固定种子价格矩阵 × 5 组 config × 4 条消费路径的输入构造与输出归一化.

本模块只做三件事——构造输入、驱动**现有**代码、把结果归一化为 JSON 可精确
round-trip 的结构。不含任何断言（断言在 ``tests/test_execution_parity.py``），
不含任何比对逻辑（比对在 ``compare.py``）。

设计约束
--------
1. 全内存：四条路径都不读 MongoDB、不写任何集合。监控路径直接驱动
   ``PortfolioTracker``（不经 ``MonitorService``），符合 S1「监控侧首次建基线」
   且不触碰数据库写操作的约束。
2. 确定性：价格矩阵由 ``np.random.default_rng(PRICE_SEED)`` 生成；策略目标权重
   只由 ``as_of`` 的年月决定（与价格、与调用次序无关），不存在随机性残留。
3. 无损序列化：归一化只用 ``float()`` / ``str`` / ``bool`` / ``dict`` / ``list``，
   ``json.dumps`` 对 float 走 ``repr``，Python float 往返无损，因此 ``abs=0``
   断言不会被夹具序列化削弱。

四条路径覆盖的改动面
--------------------
- ``single``      : ``runner.run_unified`` → ``BacktestEngine.run`` →
                    ``ExecutionEngine.rebalance_to_target``（S2/S3/S5 的正面改动面），
                    5 组 config 分别覆盖零成本 / 统一费率 / 分资产费率净额配平 /
                    期初建仓含遗留资产 / 空 target。
- ``composite``   : ``portfolio.composite_runner.run_composite_unified``（合成资产 +
                    ``PortfolioWeightAllocator`` + 同一个 ``run_unified``），零成本与
                    含成本两档；另提供 ``composite_direct_inputs`` 供跨路径同一性检验。
- ``sensitivity`` : 参数网格 × ``run_unified`` × 不同 ``RiskConfig``，覆盖
                    ``RiskManager.apply_risk_checks`` 的杠杆归一 / 单资产上限缩放
                    链路（``backtest_analysis_service.sensitivity_analysis`` 的数值内核）。
- ``monitor``     : ``PortfolioTracker(traditional_mode=True)`` 逐日 ``process_day``
                    + 月度 ``execute_rebalance``，覆盖 ``_update_daily_pnl_traditional``
                    与 ``_execute_rebalance_traditional``（S6 的改动面，本批次只冻结不改）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.risk import RiskConfig
from app.backtesting.runner import RunSpec, run_unified
from app.backtesting.signal import TargetWeightSignal
from app.backtesting.strategy_api import IStrategy

# ======================================================================
#  固定种子常量（改动即视为换基线，必须重新 rebase 并说明理由）
# ======================================================================

PRICE_SEED = 20261106
N_DAYS = 300
N_ASSETS = 5
START_DATE = "2022-01-03"
WARMUP = 60  # 回测起点前的历史缓冲行数（策略信号窗口用）
INITIAL_CASH = 10_000_000.0

CODES: List[str] = [f"ASSET{i}.TEST" for i in range(N_ASSETS)]
#: 参与目标权重的资产
TRADABLE: List[str] = CODES[:4]
#: 遗留资产：只出现在 ``initial_weights``、永不出现在目标权重。
#: 回测侧 ``execution.py:98`` 只遍历 ``target_weights.keys()`` → 不清仓；
#: 监控侧 ``portfolio_tracker.py:413-415`` → 强制清零。两侧行为差异（C1-3）
#: 由本基线如实冻结，不在 S1–S5 内收敛。
LEGACY_CODE: str = CODES[4]

# 目标权重轮动表：权重和刻意不恒为 1，以覆盖杠杆（>1）与留现金（<1）两档，
# 使敏感性路径的 max_total_leverage 缩放真正生效；含 0 权重项以覆盖清仓分支。
_WEIGHT_ROTATION: List[Dict[str, float]] = [
    {TRADABLE[0]: 0.40, TRADABLE[1]: 0.30, TRADABLE[2]: 0.20, TRADABLE[3]: 0.10},
    {TRADABLE[0]: 0.25, TRADABLE[1]: 0.25, TRADABLE[2]: 0.25, TRADABLE[3]: 0.25},
    {TRADABLE[0]: 0.10, TRADABLE[1]: 0.20, TRADABLE[2]: 0.30, TRADABLE[3]: 0.40},
    {TRADABLE[0]: 0.55, TRADABLE[1]: 0.05, TRADABLE[2]: 0.25, TRADABLE[3]: 0.15},
    {TRADABLE[0]: 0.00, TRADABLE[1]: 0.50, TRADABLE[2]: 0.00, TRADABLE[3]: 0.50},
    {TRADABLE[0]: 0.50, TRADABLE[1]: 0.40, TRADABLE[2]: 0.20, TRADABLE[3]: 0.10},
    {TRADABLE[0]: 0.30, TRADABLE[1]: 0.20, TRADABLE[2]: 0.20, TRADABLE[3]: 0.10},
]

#: 5 组 config 的键（顺序即基线 JSON 中的键顺序，勿改）
CONFIG_KEYS: Tuple[str, ...] = (
    "zero_cost",
    "flat_rate",
    "by_code",
    "initial_weights",
    "empty_target",
)


# ======================================================================
#  输入构造
# ======================================================================

def make_prices(
    n_days: int = N_DAYS,
    seed: int = PRICE_SEED,
    start: str = START_DATE,
) -> pd.DataFrame:
    """固定种子价格矩阵（对数正态随机游走，全资产正价、无缺日、无 NaN）."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n_days)
    rets = rng.normal(0.0004, 0.010, size=(n_days, N_ASSETS))
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=dates, columns=list(CODES))


def weight_set_for(as_of: pd.Timestamp) -> Dict[str, float]:
    """按 ``as_of`` 的年月确定性取一组目标权重（与价格无关）."""
    ts = pd.Timestamp(as_of)
    key = ts.year * 12 + (ts.month - 1)
    return dict(_WEIGHT_ROTATION[key % len(_WEIGHT_ROTATION)])


class RotatingWeightStrategy(IStrategy):
    """确定性轮动权重策略：目标权重只由 ``as_of`` 年月决定.

    不声明 ``get_execution_schedule`` → 调度完全由 ``config.rebalance_freq`` /
    ``config.execution_delay`` 决定（``schedule.resolve_execution_schedule:381-385``），
    使 5 组 config 的差异只落在执行层，便于归因。
    """

    def generate_target_weights(
        self,
        history_prices: pd.DataFrame,
        as_of: pd.Timestamp,
    ) -> TargetWeightSignal:
        return TargetWeightSignal(
            time=pd.Timestamp(as_of),
            target_weights=weight_set_for(as_of),
        )


class EmptyTargetStrategy(IStrategy):
    """恒返回空目标权重：覆盖 ``execution.py:98`` 循环体零次执行的分支."""

    def generate_target_weights(
        self,
        history_prices: pd.DataFrame,
        as_of: pd.Timestamp,
    ) -> TargetWeightSignal:
        return TargetWeightSignal(time=pd.Timestamp(as_of), target_weights={})


def _base_config(name: str, prices: pd.DataFrame, **kwargs: Any) -> BacktestConfig:
    return BacktestConfig(
        name=name,
        thscodes=list(prices.columns),
        start_date=prices.index[WARMUP].strftime("%Y%m%d"),
        end_date=prices.index[-1].strftime("%Y%m%d"),
        rebalance_freq="monthly",
        initial_cash=INITIAL_CASH,
        **kwargs,
    )


def make_configs(prices: pd.DataFrame) -> Dict[str, BacktestConfig]:
    """5 组 config：零成本 / 统一费率 / 分资产费率 / 期初建仓 / 空 target."""
    return {
        # 1) 零成本 + T+0：execution.py:75 净额分支不触发，成本项全 0
        "zero_cost": _base_config(
            "parity_zero_cost", prices,
            commission_rate=0.0, slippage=0.0, execution_delay=0,
        ),
        # 2) 统一费率 + T+1：走毛额分配 + cash 扣费主路径
        "flat_rate": _base_config(
            "parity_flat_rate", prices,
            commission_rate=0.0003, slippage=0.0005, execution_delay=1,
        ),
        # 3) 分资产费率：commission_by_code 非空 → 触发 execution.py:75-84
        #    净额配平分支（invest_value = total_value × (1 - cost_rate)）
        "by_code": _base_config(
            "parity_by_code", prices,
            commission_rate=0.0001, slippage=0.0004, execution_delay=1,
            commission_by_code={
                TRADABLE[0]: 0.0002,
                TRADABLE[1]: 0.0003,
                TRADABLE[2]: 0.0004,
                TRADABLE[3]: 0.0005,
            },
        ),
        # 4) 期初建仓 + 遗留资产：LEGACY_CODE 建仓后永不在 target 中
        "initial_weights": _base_config(
            "parity_initial_weights", prices,
            commission_rate=0.0003, slippage=0.0, execution_delay=1,
            initial_weights={
                TRADABLE[0]: 0.30, TRADABLE[1]: 0.30, TRADABLE[2]: 0.20,
                TRADABLE[3]: 0.10, LEGACY_CODE: 0.10,
            },
        ),
        # 5) 空 target：期初建仓后每次调仓 target_weights={} → 零成交、持仓不动
        "empty_target": _base_config(
            "parity_empty_target", prices,
            commission_rate=0.0003, slippage=0.0005, execution_delay=0,
            initial_weights={TRADABLE[0]: 0.50, TRADABLE[1]: 0.50},
        ),
    }


def make_strategy(config_key: str) -> IStrategy:
    """按 config 键选策略：``empty_target`` 用空权重策略，其余用轮动策略."""
    return EmptyTargetStrategy() if config_key == "empty_target" else RotatingWeightStrategy()


# ======================================================================
#  归一化
# ======================================================================

def _f(v: Any) -> float:
    """统一转 float（None → 0.0），保证 JSON 可序列化且比对可算 abs 差."""
    return float(v) if v is not None else 0.0


def _d(v: Any) -> str:
    return pd.Timestamp(v).strftime("%Y-%m-%d")


def _sorted_floats(d: Optional[Dict[str, Any]]) -> Dict[str, float]:
    return {str(k): _f(v) for k, v in sorted((d or {}).items(), key=lambda kv: str(kv[0]))}


def normalize_backtest_result(result: Any) -> Dict[str, Any]:
    """``BacktestResult`` → 冻结结构（快照全字段 + 成交全字段）."""
    snapshots = [
        {
            "time": _d(s.time),
            "total_value": _f(s.total_value),
            "cash": _f(s.cash),
            "holdings_value": _f(s.holdings_value),
            "weights": _sorted_floats(s.weights),
            "is_rebalance_day": bool(s.is_rebalance_day),
            "rebalance_type": s.rebalance_type,
            "signal_date": _d(s.signal_date) if s.signal_date is not None else None,
            "execution_delay_days": int(s.execution_delay_days or 0),
        }
        for s in result.snapshots
    ]
    trades = [
        {
            "time": _d(t.time),
            "thscode": str(t.thscode),
            "side": str(t.side),
            "quantity": _f(t.quantity),
            "price": _f(t.price),
            "commission": _f(t.commission),
            "slippage_cost": _f(t.slippage_cost),
            "pnl": _f(t.pnl),
        }
        for t in result.trades
    ]
    return {
        "n_snapshots": len(snapshots),
        "n_trades": len(trades),
        "snapshots": snapshots,
        "trades": trades,
        "metrics": metrics_of(result),
    }


def metrics_of(result: Any) -> Dict[str, float]:
    """绩效摘要（与 ``backtest_analysis_service.compute_metrics_from_result`` 同口径）.

    直接用 ``app.backtesting.analytics.PerformanceAnalyzer``——它正是
    ``compute_metrics_from_result`` 内部委托的同一内核，避免为取指标而
    导入 ``app.services``（该包模块级导入耗时约 36–94s）。
    """
    from app.backtesting.analytics import PerformanceAnalyzer

    if not getattr(result, "snapshots", None):
        return {}
    s = PerformanceAnalyzer(risk_free_rate=0.02).from_results(result.snapshots, result.trades)
    return {
        "annual_return": _f(s.annual_return),
        "annual_vol": _f(s.annual_volatility),
        "sharpe": _f(s.sharpe_ratio),
        "max_drawdown": _f(s.max_drawdown),
        "calmar": _f(s.calmar_ratio),
        "total_return": _f(s.total_return),
        "n_trades": int(s.n_trades),
        "total_commission": _f(s.total_commission),
        "total_slippage": _f(s.total_slippage),
        "turnover": _f(s.turnover),
    }


def _normalize_series(ser: pd.Series) -> List[List[Any]]:
    return [[_d(t), _f(v)] for t, v in ser.items()]


def _normalize_frame(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        return {"columns": [], "rows": []}
    return {
        "columns": [str(c) for c in df.columns],
        "rows": [
            [_d(t)] + [_f(v) for v in row]
            for t, row in zip(df.index, df.to_numpy().tolist())
        ],
    }


def normalize_composite_result(r: Any) -> Dict[str, Any]:
    """``PortfolioBacktestResult`` → 冻结结构（NAV / 权重历史 / 母层成交 / 绩效）."""
    perf = r.performance
    return {
        "portfolio_nav": _normalize_series(r.portfolio_nav),
        "portfolio_returns": _normalize_series(r.portfolio_returns),
        "weight_history": _normalize_frame(r.weight_history),
        "sub_contributions": _normalize_frame(r.sub_contributions),
        "rebalance_dates": [_d(d) for d in r.rebalance_dates],
        "portfolio_trades": [
            {
                "time": _d(t.time), "thscode": str(t.thscode), "side": str(t.side),
                "quantity": _f(t.quantity), "price": _f(t.price),
                "commission": _f(t.commission), "slippage_cost": _f(t.slippage_cost),
                "pnl": _f(t.pnl),
            }
            for t in (r.portfolio_trades or [])
        ],
        "performance": {} if perf is None else {
            "total_return": _f(perf.total_return),
            "annual_return": _f(perf.annual_return),
            "annual_volatility": _f(perf.annual_volatility),
            "max_drawdown": _f(perf.max_drawdown),
            "sharpe_ratio": _f(perf.sharpe_ratio),
            "calmar_ratio": _f(perf.calmar_ratio),
            "win_rate": _f(perf.win_rate),
        },
    }


# ======================================================================
#  路径 1：单策略 run_unified
# ======================================================================

def run_single_path(prices: pd.DataFrame) -> Dict[str, Any]:
    configs = make_configs(prices)
    out: Dict[str, Any] = {}
    for key in CONFIG_KEYS:
        config = configs[key]
        result = run_unified(RunSpec(
            config=config,
            data_feed=DataFeed(prices=prices.copy(), config=config),
            strategy=make_strategy(key),
            risk_config=RiskConfig(),
        ))
        out[key] = normalize_backtest_result(result)
    return out


# ======================================================================
#  路径 2：组合 composite_runner
# ======================================================================

def make_sub_navs(prices: pd.DataFrame) -> Dict[str, pd.Series]:
    """由同一固定种子矩阵派生两条子策略 NAV（保证与其余路径同源、可复现）."""
    base = 1000.0
    a = prices[TRADABLE[0]]
    b = prices[TRADABLE[1]]
    return {
        "sub_a": a / a.iloc[0] * base,
        "sub_b": b / b.iloc[0] * base,
    }


COMPOSITE_VARIANTS: Dict[str, Dict[str, float]] = {
    "zero_cost": {"commission_rate": 0.0, "slippage": 0.0},
    "with_cost": {"commission_rate": 0.0003, "slippage": 0.0005},
}


def composite_inputs(prices: pd.DataFrame) -> Dict[str, Any]:
    """``run_composite_unified`` 的固定入参（两处驱动共用，确保同一性检验可比）."""
    from app.backtesting.schedule import ExecutionSchedule

    return {
        "sub_nav_series": make_sub_navs(prices),
        "sub_weights": {"sub_a": 0.6, "sub_b": 0.4},
        "initial_nav": 1000.0,
        "execution_schedule": ExecutionSchedule(rebalance_freq="monthly", execution_delay=1),
        "weight_drift": True,
    }


def run_composite_path(prices: pd.DataFrame) -> Dict[str, Any]:
    from app.portfolio.composite_runner import run_composite_unified

    base = composite_inputs(prices)
    out: Dict[str, Any] = {}
    for tag, cost in COMPOSITE_VARIANTS.items():
        r = run_composite_unified(**base, **cost)
        out[tag] = normalize_composite_result(r)
    return out


def run_composite_direct(prices: pd.DataFrame, variant: str) -> Any:
    """跨路径同一性检验用：复刻 ``run_composite_unified`` 步骤 1–8 直驱 ``run_unified``.

    只复刻到「调用 run_unified 之前」，不复刻 ``_aggregate_result``；返回原始
    ``BacktestResult``，由测试侧与 ``run_composite_unified`` 的
    ``portfolio_nav`` / ``portfolio_trades`` 做 abs=0 比对
    （``composite_runner.py:276-278`` 与 ``:316`` 表明二者是原样透传）。
    """
    from app.backtesting.synthetic_feed import build_synthetic_prices
    from app.backtesting.schedule import ScheduleResolver
    from app.portfolio.weight_models import FixedWeightModel, PortfolioWeightAllocator

    base = composite_inputs(prices)
    cost = COMPOSITE_VARIANTS[variant]
    sub_nav_series = base["sub_nav_series"]
    sub_weights = base["sub_weights"]
    initial_nav = float(base["initial_nav"])
    raw_sched = base["execution_schedule"]

    total_w = sum(sub_weights.values())
    norm_weights = {k: v / total_w for k, v in sub_weights.items()}
    keys = list(sub_weights.keys())

    prices_synth = build_synthetic_prices(sub_nav_series, base=initial_nav)
    dates = prices_synth.index
    exec_delay = int(raw_sched.execution_delay)
    weight_model = FixedWeightModel(norm_weights)

    resolver0 = ScheduleResolver(raw_sched, list(dates))
    rebal_day0 = dates[0] in set(resolver0.resolve_signal_dates(dates[0], dates[-1]))
    if rebal_day0:
        target_w0 = weight_model.compute_weights(sub_nav_series, dates[0])
        initial_weights = {k: float(target_w0.get(k, norm_weights.get(k, 0.0))) for k in keys}
    else:
        initial_weights = dict(norm_weights)

    config = BacktestConfig(
        name="composite_unified",
        thscodes=keys,
        start_date=dates[0].strftime("%Y%m%d"),
        end_date=dates[-1].strftime("%Y%m%d"),
        rebalance_freq="monthly",
        initial_cash=initial_nav,
        initial_nav=initial_nav,
        commission_rate=float(cost["commission_rate"]),
        slippage=float(cost["slippage"]),
        initial_weights=initial_weights,
    )
    allocator = PortfolioWeightAllocator(
        weight_model=weight_model,
        sub_keys=keys,
        prices_matrix=prices_synth,
        rebalance_freq=raw_sched.rebalance_freq,
        execution_delay=exec_delay,
        event_signal=None,
        weight_drift=bool(base["weight_drift"]),
        initial_weights=initial_weights,
    )
    feed = DataFeed(prices=prices_synth, config=config, strategy_prices=prices_synth)
    return run_unified(RunSpec(
        config=config,
        data_feed=feed,
        allocator=allocator,
        composition={"selector": None, "allocator": "portfolio_weight", "controller": None},
        strategy_params={},
        thscodes=keys,
    ))


# ======================================================================
#  路径 3：敏感性网格
# ======================================================================

#: 网格点：RiskConfig 三字段组合。grid_4 的上限与杠杆均不咬合，
#: 数值上应与 grid_0 完全相同——测试侧把它当作网格自洽性自检。
SENSITIVITY_GRID: List[Dict[str, Any]] = [
    {"label": "no_constraint", "max_total_leverage": None, "max_weight_dict": None},
    {"label": "leverage_1.0", "max_total_leverage": 1.0, "max_weight_dict": None},
    {"label": "leverage_0.8", "max_total_leverage": 0.8, "max_weight_dict": None},
    {"label": "cap_A_0.35", "max_total_leverage": None,
     "max_weight_dict": {TRADABLE[0]: 0.35}},
    {"label": "loose_both", "max_total_leverage": 1.5,
     "max_weight_dict": {c: 0.60 for c in TRADABLE}},
]


def run_sensitivity_path(prices: pd.DataFrame) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for i, g in enumerate(SENSITIVITY_GRID):
        config = _base_config(
            "parity_sensitivity", prices,
            commission_rate=0.0003, slippage=0.0005, execution_delay=1,
        )
        risk_config = RiskConfig(
            max_total_leverage=g["max_total_leverage"],
            max_weight_dict=(dict(g["max_weight_dict"]) if g["max_weight_dict"] else None),
        )
        result = run_unified(RunSpec(
            config=config,
            data_feed=DataFeed(prices=prices.copy(), config=config),
            strategy=RotatingWeightStrategy(),
            risk_config=risk_config,
        ))
        out[f"grid_{i}_{g['label']}"] = normalize_backtest_result(result)
    return out


# ======================================================================
#  路径 4：监控 PortfolioTracker（traditional_mode，全内存）
# ======================================================================

MONITOR_TRADING_COST = 0.0003
MONITOR_INITIAL_WEIGHTS: Dict[str, float] = {
    TRADABLE[0]: 0.30, TRADABLE[1]: 0.30, TRADABLE[2]: 0.20,
    TRADABLE[3]: 0.10, LEGACY_CODE: 0.10,
}

#: 监控路径的两个费率口径，两组都必须冻结：
#:
#: ``monitor``       —— 分支覆盖探针（``trading_cost = 0.0003``）。
#:                      目的是让 ``portfolio_tracker.py:391-400`` 的「按权重差 × 费率
#:                      估算 trade_cost → nav_after_cost = current_nav - trade_cost」
#:                      这段扣费算术真的被执行。S4 的 ``RebalanceFill`` 要逐行照搬
#:                      这段算术；若基线是零成本，这段就是死代码，重构改错也不会
#:                      被任何断言发现。
#: ``monitor_gross`` —— 生产口径（``trading_cost = {}``，即 gross NAV）。
#:                      已核实生产上 ``PortfolioTracker.trading_cost`` 恒为空字典：
#:                      ``portfolio_tracker.py:43``（构造默认，注释「留作将来按资产
#:                      配置费率的入口」）、``:59``（``rt is None`` 分支）、
#:                      ``:69``（有 runtime 配置分支，注释「费率留空：通用监控按
#:                      gross NAV 计算，不再回退到 config 兜底表」），且
#:                      ``_resolve_trading_cost``（:92-94）注释「未配置时恒为 0
#:                      （gross NAV 口径）」。故 ``monitor`` 口径**不代表生产行为**，
#:                      必须由 ``monitor_gross`` 承担代表性。
MONITOR_VARIANTS: Tuple[str, ...] = ("monitor", "monitor_gross")


def _month_first_business_days(idx: pd.DatetimeIndex) -> set:
    """区间内每个月的第一个交易日（监控月度调仓日）."""
    out = set()
    for key, group in pd.Series(idx, index=idx).groupby([idx.year, idx.month]):
        out.add(pd.Timestamp(group.index[0]))
    return out


def _monitor_row(date_str: str, state: Any, kind: str, daily: Any) -> Dict[str, Any]:
    row = {
        "date": date_str,
        "kind": kind,
        "nav": _f(state.nav),
        "nav_base": _f(state.nav_base),
        "cash": _f(state.cash),
        "quantities": _sorted_floats(state.quantities),
        "total_trading_cost": _f(state.total_trading_cost),
        "day_count": int(state.day_count),
        "positions_cny": _sorted_floats(state.positions_cny),
    }
    if daily is not None:
        row["daily_nav"] = _f(daily.nav)
        row["daily_nav_change_pct"] = _f(daily.nav_change_pct)
        row["daily_total_leverage"] = _f(daily.total_leverage)
        row["daily_asset_weights"] = _sorted_floats(daily.asset_weights)
        row["daily_replication_cost"] = _f(daily.replication_cost)
    return row


def run_monitor_path(
    prices: pd.DataFrame,
    trading_cost: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """直接驱动 ``PortfolioTracker`` 的传统持仓路径，不经 MonitorService / Mongo.

    顺序对齐 ``daily_stepper._process_single_day`` 的 B → D：先 ``process_day``
    （内部 ``update_daily_pnl`` 用旧持仓计当日市场收益），再在月度调仓日
    ``execute_rebalance``（traditional_mode 下委托 ``_execute_rebalance_traditional``）。

    Args:
        prices: 价格矩阵。
        trading_cost: 按资产费率表。``None`` → 用 ``MONITOR_TRADING_COST`` 对全部
            资产配费（分支覆盖探针）；``{}`` → 生产 gross NAV 口径（费率恒 0）。
    """
    from app.monitor.portfolio_tracker import PortfolioTracker
    from app.monitor.types import PortfolioState

    codes = list(prices.columns)
    idx = prices.index[WARMUP:]
    trade_dates = [str(pd.Timestamp(d).date()) for d in idx]
    fx_df = pd.DataFrame()

    if trading_cost is None:
        trading_cost = {c: MONITOR_TRADING_COST for c in codes}

    tracker = PortfolioTracker()
    tracker.asset_list = list(codes)
    # 全部按 CNH 计价 + 空汇率表 → get_fx_rate 恒返回 1.0（portfolio_tracker.py:460-468），
    # 隔离汇率维度，使基线只反映传统持仓记账本身。
    tracker.asset_currency = {c: "CNH" for c in codes}
    # 生产上此字典恒为空（见 MONITOR_VARIANTS 注释）→ _resolve_trading_cost 恒 0，
    # portfolio_tracker.py:391-400 的扣费分支不会被执行。两个口径分别由
    # monitor（显式配费，覆盖扣费算术）与 monitor_gross（空表，生产口径）承担。
    tracker.trading_cost = dict(trading_cost)
    tracker.replication_cost = {}
    tracker.traditional_mode = True

    state = PortfolioState(
        date=trade_dates[0],
        nav=0.0,
        nav_base=0.0,
        positions_cny={},
        positions_local={},
        apl_local={},
        target_weights={},
        last_rebalance_date="",
        last_rebalance_fx={},
    )

    first_day = idx[0]
    prices_today = {c: float(prices.loc[first_day, c]) for c in codes}
    # 步骤 A：初始化（内部立即调仓到期初权重，同回测期初建仓）
    tracker._initialize_positions_traditional(
        state, dict(MONITOR_INITIAL_WEIGHTS), prices_today,
    )
    state.date = trade_dates[0]
    rows: List[Dict[str, Any]] = [_monitor_row(trade_dates[0], state, "init", None)]

    rebalance_days = _month_first_business_days(idx)
    prev_prices = prices_today
    prev_nav = state.nav

    for i in range(1, len(idx)):
        day = idx[i]
        date_str = trade_dates[i]
        prices_today = {c: float(prices.loc[day, c]) for c in codes}

        # 步骤 B：每日损益（traditional 路径 = cash + Σ qty×close）
        daily = tracker.process_day(
            state, date_str, prices_today, prev_prices, fx_df, trade_dates,
        )

        is_rebal = pd.Timestamp(day) in rebalance_days
        if is_rebal:
            # 步骤 D：月度调仓（traditional_mode 委托 _execute_rebalance_traditional）
            tracker.execute_rebalance(
                state,
                weight_set_for(day),
                tracker.get_all_fx_rates(date_str, fx_df),
                rebalance_type="monthly",
                prev_nav=prev_nav,
                prices_today=prices_today,
            )
            state.last_rebalance_date = date_str

        rows.append(_monitor_row(date_str, state, "rebalance" if is_rebal else "daily", daily))
        prev_prices = prices_today
        prev_nav = state.nav

    return {
        "n_days": len(rows),
        "n_rebalance_days": sum(1 for r in rows if r["kind"] == "rebalance"),
        "final_nav": _f(state.nav),
        "final_cash": _f(state.cash),
        "final_quantities": _sorted_floats(state.quantities),
        "final_total_trading_cost": _f(state.total_trading_cost),
        "nav_history_len": len(state.nav_history),
        "rows": rows,
    }


# ======================================================================
#  汇总入口
# ======================================================================

def build_baseline() -> Dict[str, Any]:
    """跑全部四条路径，返回完整基线结构（rebase 与 check 共用）.

    监控路径产出两个费率口径（见 ``MONITOR_VARIANTS``）：``monitor`` 是分支覆盖
    探针，``monitor_gross`` 是生产 gross NAV 口径。两者除费率外完全同构，
    差异就是「扣费算术是否被执行」。
    """
    prices = make_prices()
    return {
        "meta": {
            "price_seed": PRICE_SEED,
            "n_days": N_DAYS,
            "n_assets": N_ASSETS,
            "start_date": START_DATE,
            "warmup": WARMUP,
            "initial_cash": INITIAL_CASH,
            "codes": list(CODES),
            "legacy_code": LEGACY_CODE,
            "config_keys": list(CONFIG_KEYS),
            "composite_variants": sorted(COMPOSITE_VARIANTS.keys()),
            "sensitivity_grid": [g["label"] for g in SENSITIVITY_GRID],
            "monitor_variants": list(MONITOR_VARIANTS),
            "monitor_trading_cost": MONITOR_TRADING_COST,
            #: monitor_gross 对应生产口径：trading_cost 恒为空字典（gross NAV）。
            "monitor_gross_trading_cost": 0.0,
        },
        "single": run_single_path(prices),
        "composite": run_composite_path(prices),
        "sensitivity": run_sensitivity_path(prices),
        "monitor": run_monitor_path(prices),
        "monitor_gross": run_monitor_path(prices, trading_cost={}),
    }
