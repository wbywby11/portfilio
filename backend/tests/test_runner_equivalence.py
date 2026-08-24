# -*- coding: utf-8 -*-
"""runner 唯一入口等价性测试（P1 数值零变化守卫）.

验证经 ``runner.run_unified`` 运行与历史上在调用点直接构造
CompositionPipeline + RiskManager + ExecutionEngine + BacktestEngine
的运行结果逐快照、逐成交完全一致——收敛只改接线，不改数值。
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.engine import BacktestEngine
from app.backtesting.execution import ExecutionEngine
from app.backtesting.risk import RiskManager, RiskConfig
from app.backtesting.runner import RunSpec, run_unified


def _make_prices(n_days: int = 300, n_assets: int = 4, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    codes = [f"ASSET{i}.TEST" for i in range(n_assets)]
    rets = rng.normal(0.0004, 0.01, size=(n_days, n_assets))
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=dates, columns=codes)


def _make_config(prices: pd.DataFrame) -> BacktestConfig:
    return BacktestConfig(
        name="runner_equivalence",
        thscodes=list(prices.columns),
        start_date=prices.index[60].strftime("%Y%m%d"),
        end_date=prices.index[-1].strftime("%Y%m%d"),
        rebalance_freq="monthly",
        initial_cash=10_000_000.0,
        commission_rate=0.0003,
        slippage=0.0005,
    )


def _make_risk_parity_allocator():
    from app.allocation.models.risk_parity import RiskParityStrategy

    return RiskParityStrategy()


def _run_legacy(config: BacktestConfig, data_feed: DataFeed, risk_config: RiskConfig):
    """历史调用点的直接构造方式（收敛前写法，仅测试内保留）."""
    from app.backtesting.composition_pipeline import CompositionPipeline

    composition = {"selector": None, "allocator": "risk_parity", "controller": None}
    strategy = CompositionPipeline(
        allocator=_make_risk_parity_allocator(),
        thscodes=config.thscodes,
        composition=composition,
        strategy_params={},
    )
    engine = BacktestEngine(
        config=config,
        data_feed=data_feed,
        strategy=strategy,
        risk_manager=RiskManager(risk_config),
        execution_engine=ExecutionEngine(config),
    )
    return engine.run()


class TestRunnerEquivalence:
    """run_unified 与直接构造的数值等价性."""

    def _feeds(self):
        prices = _make_prices()
        config = _make_config(prices)
        # 两个独立 DataFeed 实例，避免引擎内部状态互相影响
        feed_a = DataFeed(prices=prices.copy(), config=config)
        feed_b = DataFeed(prices=prices.copy(), config=config)
        return config, feed_a, feed_b

    def test_snapshots_and_trades_identical(self):
        config, feed_a, feed_b = self._feeds()
        risk_config = RiskConfig()

        legacy = _run_legacy(config, feed_a, risk_config)
        unified = run_unified(RunSpec(
            config=config,
            data_feed=feed_b,
            allocator=_make_risk_parity_allocator(),
            thscodes=config.thscodes,
            composition={"selector": None, "allocator": "risk_parity", "controller": None},
            strategy_params={},
            risk_config=risk_config,
        ))

        assert len(legacy.snapshots) == len(unified.snapshots)
        assert len(legacy.snapshots) > 0
        for s1, s2 in zip(legacy.snapshots, unified.snapshots):
            assert s1.time == s2.time
            assert s1.total_value == pytest.approx(s2.total_value, rel=0, abs=0)
            assert s1.weights.keys() == s2.weights.keys()
            for code in s1.weights:
                v1 = s1.weights[code] or 0.0
                v2 = s2.weights[code] or 0.0
                assert v1 == pytest.approx(v2, rel=0, abs=1e-15)

        assert len(legacy.trades) == len(unified.trades)
        for t1, t2 in zip(legacy.trades, unified.trades):
            assert t1.time == t2.time
            assert t1.thscode == t2.thscode
            assert t1.quantity == pytest.approx(t2.quantity, rel=0, abs=0)
            assert t1.commission == pytest.approx(t2.commission, rel=0, abs=0)

    def test_nav_series_identical(self):
        config, feed_a, feed_b = self._feeds()
        legacy = _run_legacy(config, feed_a, RiskConfig())
        unified = run_unified(RunSpec(
            config=config,
            data_feed=feed_b,
            allocator=_make_risk_parity_allocator(),
            composition={"selector": None, "allocator": "risk_parity", "controller": None},
        ))
        nav_legacy = pd.Series([s.total_value for s in legacy.snapshots])
        nav_unified = pd.Series([s.total_value for s in unified.snapshots])
        pd.testing.assert_series_equal(nav_legacy, nav_unified, check_names=False)


if __name__ == "__main__":
    t = TestRunnerEquivalence()
    t.test_snapshots_and_trades_identical()
    print("[PASS] test_snapshots_and_trades_identical")
    t.test_nav_series_identical()
    print("[PASS] test_nav_series_identical")
    print("\nAll runner equivalence tests passed!")
