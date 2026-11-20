"""回测分析服务口径守卫测试.

覆盖三件事：
1. 指标摘要必须走统一绩效内核的 from_results，并用真实成交统计成本；
2. 情景冲击在 DataFeed 价格矩阵副本上生效，基线数据不被修改；
3. 源码不得回退到不存在的 analyzer.analyze / COMPOSITION_DEFAULTS /
   无效的 _scenario_shocks 参数注入。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.types import PortfolioSnapshot, Trade
from app.services.backtest_analysis_service import compute_metrics_from_result

SERVICE_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "services" / "backtest_analysis_service.py"
)


def _make_feed() -> DataFeed:
    """四个交易日的固定价格矩阵，首日用于期初建仓。"""
    dates = pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    )
    prices = pd.DataFrame(
        {"A": [100.0, 100.0, 100.0, 100.0], "B": [50.0, 50.0, 50.0, 50.0]},
        index=dates,
    )
    config = BacktestConfig(
        name="scenario_test",
        thscodes=["A", "B"],
        start_date="20240102",
        end_date="20240105",
    )
    return DataFeed(
        prices=prices.copy(),
        config=config,
        strategy_prices=prices.copy(),
        extra_prices={"vwap": prices.copy()},
    )


def test_compute_metrics_from_result_includes_trade_costs():
    """固定快照 + 固定成交：指标非空，且手续费/滑点/换手率均来自成交记录。"""
    snapshots = [
        PortfolioSnapshot(
            time=pd.Timestamp("2024-01-02"), total_value=1000.0,
            cash=0.0, holdings_value=1000.0, weights={"A": 1.0},
        ),
        PortfolioSnapshot(
            time=pd.Timestamp("2024-01-03"), total_value=1010.0,
            cash=0.0, holdings_value=1010.0, weights={"A": 1.0},
            is_rebalance_day=True,
        ),
        PortfolioSnapshot(
            time=pd.Timestamp("2024-01-04"), total_value=990.0,
            cash=0.0, holdings_value=990.0, weights={"A": 1.0},
        ),
    ]
    trades = [
        Trade(
            time=pd.Timestamp("2024-01-03"), thscode="A", side="buy",
            quantity=100.0, price=10.0, commission=5.0, slippage_cost=1.0,
        )
    ]

    metrics = compute_metrics_from_result(
        SimpleNamespace(snapshots=snapshots, trades=trades)
    )

    assert metrics, "metrics 不应为空"
    assert metrics["n_trades"] == 1
    assert metrics["total_commission"] > 0
    assert metrics["total_slippage"] > 0
    assert metrics["turnover"] > 0
    assert set(metrics) >= {
        "annual_return", "annual_vol", "sharpe", "max_drawdown",
        "calmar", "total_return", "n_trades", "total_commission",
        "total_slippage", "turnover",
    }


def test_compute_metrics_from_result_rejects_empty_snapshots():
    """快照为空必须报错，不能返回全 0 的假指标。"""
    with pytest.raises(ValueError):
        compute_metrics_from_result(SimpleNamespace(snapshots=[], trades=[]))


def test_with_scenario_shocks_defaults_to_first_day_after_start():
    """默认冲击日为首日之后的第一个交易日，且同步调整全部价格矩阵。"""
    feed = _make_feed()
    shocked = feed.with_scenario_shocks({"A": -0.10})

    shock_day = pd.Timestamp("2024-01-03")
    before = pd.Timestamp("2024-01-02")

    # 冲击日前的价格不变（期初建仓按原价成交）
    assert shocked.prices.loc[before, "A"] == pytest.approx(100.0)
    # 冲击日及之后按冲击幅度水平位移
    assert shocked.prices.loc[shock_day, "A"] == pytest.approx(90.0)
    assert shocked.prices.loc["2024-01-05", "A"] == pytest.approx(90.0)
    # 未指定资产不受影响
    assert shocked.prices["B"].tolist() == [50.0, 50.0, 50.0, 50.0]
    # 缺日保真矩阵与附加价格同步
    assert shocked.strategy_prices.loc[shock_day, "A"] == pytest.approx(90.0)
    assert shocked.extra_prices["vwap"].loc[shock_day, "A"] == pytest.approx(90.0)
    # 原 DataFeed 不被修改
    assert feed.prices.loc[shock_day, "A"] == pytest.approx(100.0)


def test_with_scenario_shocks_accepts_explicit_date():
    """显式冲击日按给定交易日生效。"""
    feed = _make_feed()
    shocked = feed.with_scenario_shocks(
        {"A": 0.20}, shock_date=pd.Timestamp("2024-01-04")
    )

    assert shocked.prices.loc["2024-01-03", "A"] == pytest.approx(100.0)
    assert shocked.prices.loc["2024-01-04", "A"] == pytest.approx(120.0)


def test_with_scenario_shocks_rejects_invalid_input():
    """未知资产、非法幅度、区间不足两个交易日都必须报错。"""
    feed = _make_feed()

    with pytest.raises(ValueError, match="不在价格矩阵"):
        feed.with_scenario_shocks({"UNKNOWN": -0.1})
    with pytest.raises(ValueError, match="非法"):
        feed.with_scenario_shocks({"A": -1.0})

    single_day = DataFeed(
        prices=feed.prices.iloc[[0]].copy(),
        config=BacktestConfig(
            name="single_day",
            thscodes=["A"],
            start_date="20240102",
            end_date="20240102",
        ),
    )
    with pytest.raises(ValueError, match="至少两个交易日"):
        single_day.with_scenario_shocks({"A": -0.1})


def test_analysis_service_has_no_phantom_calls():
    """源码守卫：不得回退到不存在的接口或无效的情景参数注入。"""
    source = SERVICE_PATH.read_text(encoding="utf-8")

    assert "analyzer.analyze" not in source
    assert "COMPOSITION_DEFAULTS" not in source
    # 冲击只能经 DataFeed 接口进入价格矩阵，不得再作为无效策略参数注入
    assert '"_scenario_shocks"' not in source
    assert "config.use_index_nav" not in source


def test_composition_force_month_end_independent_of_selection():
    """force_month_end 由分配模型决定，不因未启用选择器而丢失。"""
    from app.backtesting.composition_builder import build_strategy_composition

    without_selection = build_strategy_composition("vol_scaled_budget", ["A"], {})
    assert without_selection.force_month_end is True

    other = build_strategy_composition("manual_allocation", ["A"], {})
    assert other.force_month_end is False


def test_composite_performance_counts_mother_trades():
    """组合层绩效必须统计母层成交成本（_performance_from_nav 传入 trades）。"""
    from app.portfolio.composite_runner import run_composite_unified

    dates = pd.bdate_range("2024-01-02", periods=90)
    navs = {
        "a": pd.Series(1000.0 * (1.0005 ** np.arange(90)), index=dates),
        "b": pd.Series(1000.0 * (1.0002 ** np.arange(90)), index=dates),
    }
    result = run_composite_unified(
        sub_nav_series=navs,
        sub_weights={"a": 0.6, "b": 0.4},
        initial_nav=1000.0,
        rebalance_freq="monthly",
        commission_rate=0.001,
        slippage=0.0005,
    )

    perf = result.performance
    assert perf is not None
    assert perf.n_trades > 0
    assert perf.total_commission > 0
    assert perf.total_slippage > 0
    assert perf.turnover > 0
    assert len(result.portfolio_trades) == perf.n_trades


def test_sub_strategy_out_accepts_cost_fields():
    """子策略输出模型能承载成本字段（前端据此展示）。"""
    from app.schemas.backtests import SubStrategyResultOut

    out = SubStrategyResultOut(
        model_id="m1", name="子策略", weight=0.5,
        annual_return=0.1, annual_volatility=0.2, sharpe_ratio=0.5,
        max_drawdown=-0.1, n_trades=3, total_commission=12.5,
        total_slippage=4.0, turnover=0.8,
    )
    assert out.total_commission == 12.5
    assert out.total_slippage == 4.0
    assert out.turnover == 0.8
