# -*- coding: utf-8 -*-
"""发布冻结快照单元测试（纯函数，不依赖数据库）.

覆盖发布即冻结的核心契约：
  1. 快照固化运行口径字段（资产/参数/窗口/调仓频率/成员权重）；
  2. 指纹忽略 frozen_at，内容变化必然改变指纹；
  3. 回放快照只返回副本，不修改原模型；
  4. 组合快照冻结成员权重与权重模型参数。
"""
import pytest

from app.models.strategy_model import ModelStatus, StrategyModel
from app.services.published_snapshot import (
    apply_published_snapshot,
    build_published_snapshot,
    compute_config_fingerprint,
)


def _model(**overrides):
    data = dict(
        name="快照策略",
        template_code="manual_allocation",
        asset_codes=["A", "B"],
        asset_names={"A": "资产A", "B": "资产B"},
        rebalance_frequency="月",
        parameters={"target_vol": 0.05},
        momentum_windows="20,60,120,250",
        min_history_days=260,
        initial_nav=1000.0,
        status=ModelStatus.PUBLISHED,
    )
    data.update(overrides)
    return StrategyModel(**data)


def test_strategy_snapshot_freezes_runtime_fields():
    snap = build_published_snapshot(_model())

    assert snap["kind"] == "strategy"
    assert snap["is_portfolio"] is False
    assert snap["asset_codes"] == ["A", "B"]
    assert snap["parameters"]["target_vol"] == 0.05
    assert snap["momentum_windows"] == "20,60,120,250"
    assert snap["rebalance_frequency"] == "月"
    assert snap["frozen_at"]


def test_fingerprint_ignores_frozen_at_but_tracks_content():
    snap = build_published_snapshot(_model())
    same = dict(snap)
    same["frozen_at"] = "2000-01-01T00:00:00"
    assert compute_config_fingerprint(snap) == compute_config_fingerprint(same)

    changed = build_published_snapshot(_model(asset_codes=["A"]))
    assert compute_config_fingerprint(snap) != compute_config_fingerprint(changed)


def test_apply_snapshot_returns_copy_without_mutating_model():
    frozen = build_published_snapshot(_model())
    changed = _model(
        asset_codes=["A"],
        parameters={"target_vol": 0.2},
        min_history_days=120,
    )

    applied = apply_published_snapshot(changed, frozen)

    assert applied is not changed
    assert applied.asset_codes == ["A", "B"]
    assert applied.parameters["target_vol"] == 0.05
    assert applied.min_history_days == 260
    # 原模型保持发布后草稿状态，不被快照覆盖
    assert changed.asset_codes == ["A"]
    assert changed.parameters["target_vol"] == 0.2


def test_portfolio_snapshot_freezes_members_and_weight_model():
    portfolio = StrategyModel(
        name="组合",
        template_code="portfolio",
        asset_codes=[],
        rebalance_frequency="月",
        is_portfolio=True,
        sub_strategies=[
            {"model_id": "m1", "name": "子策略1", "weight": 0.6},
            {"model_id": "m2", "name": "子策略2", "weight": 0.4},
        ],
        weight_model_type="static",
        weight_model_params={"mode": "fixed"},
        initial_nav=1000.0,
    )

    snap = build_published_snapshot(portfolio)

    assert snap["kind"] == "portfolio"
    assert snap["is_portfolio"] is True
    assert [row["weight"] for row in snap["sub_strategies"]] == [0.6, 0.4]
    assert snap["weight_model_type"] == "static"
    assert snap["weight_model_params"] == {"mode": "fixed"}
    assert snap["initial_nav"] == 1000.0


def test_apply_portfolio_snapshot_restores_members():
    portfolio = StrategyModel(
        name="组合",
        template_code="portfolio",
        asset_codes=[],
        rebalance_frequency="月",
        is_portfolio=True,
        sub_strategies=[{"model_id": "m1", "name": "子策略1", "weight": 1.0}],
    )
    frozen = build_published_snapshot(portfolio)

    portfolio.sub_strategies = [
        {"model_id": "m2", "name": "被改动的子策略", "weight": 1.0}
    ]
    applied = apply_published_snapshot(portfolio, frozen)

    assert [row["model_id"] for row in applied.sub_strategies] == ["m1"]
    assert [row["model_id"] for row in portfolio.sub_strategies] == ["m2"]


@pytest.mark.parametrize("snapshot", [None, {}])
def test_apply_empty_snapshot_is_noop(snapshot):
    model = _model()
    assert apply_published_snapshot(model, snapshot) is model
