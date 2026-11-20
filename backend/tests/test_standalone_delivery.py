# -*- coding: utf-8 -*-
"""独立策略管道交付契约回归：日报落库 / 组合调仓记录 / 自定义监控指标.

覆盖三类「执行后必须落库、前端才能读到」的交付点：

1. ``monitor_daily_reports``：``run_init`` / ``run_daily`` / ``run_range`` 三条逐日
   推演路径都必须把当日运行结果写入日报集合（历史缺陷：初始化路径仅在
   ``manual_preset_step`` 逐步模式下写日报，常规启动后日报表恒空）。
   批次改造后 ``run_*`` 为「建批次 → 推演 → 收尾」外壳，逐日循环位于
   ``_run_*_impl``；守卫同时钉住委托关系与循环体写入位置。
   日报以 ``(monitor_id, date)`` 为业务主键 upsert，重复推演不产生重复文档。
2. ``rebalance_records``：「多个已发布策略直接组合」创建路径必须写入初始建仓
   记录（历史缺陷：该路径只创建 portfolios 文档，调仓历史恒空，而另外两条
   创建路径都会追溯写记录）。
3. ``monitor_states.custom_metrics``：策略自定义监控指标经通用路径
   （``allocator.compute_monitoring_metrics``）进入日度状态，并经 ``_json_safe``
   转成可落库类型；``PortfolioState → MonitorState`` 映射与日报
   ``performance.custom_metrics`` 透传一致。

全部用例不触库、不启引擎：集合与适配器以桩替代，源码结构用 AST 断言守卫。
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.models.monitor import MonitorDailyReport, MonitorState
from app.monitor.daily_stepper import DailyStepperMixin, _json_safe
from app.monitor.monitor_query import MonitorQueryMixin
from app.monitor.types import PortfolioState
from app.portfolio.models import PortfolioSource, RebalanceAction, RebalanceRecord
from app.portfolio.portfolio_service import PortfolioService
from app.services.monitor_service import MonitorService
from app.models.strategy_model import ModelStatus


def _run(coro):
    """本仓未装 pytest-asyncio，协程统一用 asyncio.run 驱动."""
    return asyncio.run(coro)


# ============================================================
# 桩：日报集合 / 宿主
# ============================================================

class _FakeReportsCollection:
    """按 (monitor_id, batch_id, date) 作键的假集合，模拟 replace_one(upsert=True)."""

    def __init__(self):
        self.docs = {}
        self.replace_calls = 0

    async def replace_one(self, flt, doc, upsert=False):
        self.replace_calls += 1
        self.docs[(flt["monitor_id"], flt.get("batch_id", "legacy"), flt["date"])] = doc
        return SimpleNamespace(matched_count=1, upserted_id=None)

    async def find_one(self, flt, **kwargs):
        return self.docs.get(
            (flt["monitor_id"], flt.get("batch_id", "legacy"), flt["date"])
        )


class _ReportHost(MonitorQueryMixin):
    """仅承载 _save_daily_report 的宿主桩."""

    def __init__(self, batch_id: str = "legacy"):
        self.reports_collection = _FakeReportsCollection()
        self._batch_id = batch_id

    def _current_batch_id(self) -> str:
        return self._batch_id or "legacy"


def _report_payload(date="2026-08-25", custom_metrics=None):
    payload = {
        "date": date,
        "nav": 1023.82,
        "nav_change_pct": 0.0012,
        "total_leverage": 1.0,
        "asset_weights": {"A.TEST": 0.6, "B.TEST": 0.4},
        "rebalance_executed": False,
        "rebalance_type": "none",
        "vol_reset_triggered": False,
    }
    if custom_metrics is not None:
        payload["custom_metrics"] = custom_metrics
    return payload


# ============================================================
# 一、日报落库（monitor_daily_reports）
# ============================================================

def test_save_daily_report_upserts_by_monitor_and_date():
    """同一 (monitor_id, batch_id, date) 重复写入只保留一份文档（幂等）."""
    host = _ReportHost()

    _run(host._save_daily_report("m-1", _report_payload()))
    _run(host._save_daily_report("m-1", _report_payload()))

    assert host.reports_collection.replace_calls == 2
    assert len(host.reports_collection.docs) == 1
    doc = host.reports_collection.docs[("m-1", "legacy", "2026-08-25")]
    assert doc["monitor_id"] == "m-1"
    assert doc["batch_id"] == "legacy"
    assert doc["date"] == "2026-08-25"
    assert doc["nav"] == pytest.approx(1023.82)
    assert doc["daily_return"] == pytest.approx(0.0012)
    # 持仓与信号映射
    assert {"asset": "A.TEST", "weight": 0.6} in doc["positions"]
    assert doc["signals"]["rebalance_executed"] is False


def test_save_daily_report_isolates_batches():
    """不同批次写同一交易日互不覆盖（重跑不抹除旧批次日报）."""
    host_a = _ReportHost(batch_id="batch-a")
    host_b = _ReportHost(batch_id="batch-b")

    _run(host_a._save_daily_report("m-1", _report_payload()))
    _run(host_b._save_daily_report("m-1", _report_payload()))

    assert host_a.reports_collection.docs[("m-1", "batch-a", "2026-08-25")]["batch_id"] == "batch-a"
    assert host_b.reports_collection.docs[("m-1", "batch-b", "2026-08-25")]["batch_id"] == "batch-b"


def test_save_daily_report_carries_custom_metrics():
    """自定义监控指标写入 performance.custom_metrics（前端指标区数据源）."""
    host = _ReportHost()
    metrics = {
        "rebalance_count": 251,
        "constraint_trigger_counts": {"C1": 46, "C7": 147},
        "realized_volatility": 0.01086,
    }

    _run(host._save_daily_report("m-1", _report_payload(custom_metrics=metrics)))

    doc = host.reports_collection.docs[("m-1", "legacy", "2026-08-25")]
    assert doc["performance"]["custom_metrics"] == metrics


def test_save_daily_report_omits_empty_custom_metrics():
    """未实现 compute_monitoring_metrics 的策略不产生多余字段（存量行为不变）."""
    host = _ReportHost()

    _run(host._save_daily_report("m-1", _report_payload()))
    _run(host._save_daily_report("m-1", _report_payload(custom_metrics={})))

    doc = host.reports_collection.docs[("m-1", "legacy", "2026-08-25")]
    assert "custom_metrics" not in doc["performance"]


def _await_calls_in_for_body(func_src: str, attr: str) -> bool:
    """判断函数内是否存在「for 循环体直接 await self.<attr>(...)」."""
    tree = ast.parse(textwrap.dedent(func_src))
    fn = tree.body[0]
    for node in ast.walk(fn):
        if not isinstance(node, ast.For):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Expr):
                continue
            call = stmt.value
            if not isinstance(call, ast.Await):
                continue
            inner = call.value
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == attr
            ):
                return True
    return False


# 批次改造后 run_* 只是外壳，逐日循环在 _run_*_impl；两端都要钉住，
# 否则把 impl 改名即可绕过日报断言。
_RUN_ENTRY_PAIRS = [
    ("run_init", "_run_init_impl"),
    ("run_daily", "_run_daily_impl"),
    ("run_range", "_run_range_impl"),
]


@pytest.mark.parametrize("entry,impl", _RUN_ENTRY_PAIRS)
def test_every_daily_loop_persists_report_unconditionally(entry, impl):
    """三条逐日推演路径的日报写入必须直挂循环体，不得包在 step_mode 分支内.

    历史缺陷：初始化路径写成 ``if step_mode: await self._save_daily_report(...)``，
    常规（非主观预设）启动后 monitor_daily_reports 恒为空表。
    """
    entry_src = inspect.getsource(getattr(MonitorService, entry))
    assert f"self.{impl}(" in entry_src, (
        f"{entry} 未委托到 {impl}；日报守卫需随实现位置同步更新"
    )

    src = inspect.getsource(getattr(MonitorService, impl))

    assert _await_calls_in_for_body(src, "_save_daily_report"), (
        f"{impl} 的逐日循环未直挂 _save_daily_report；"
        f"日报只在 step_mode 等条件下写入会导致常规启动后日报表为空"
    )

    # 反向守卫：日报写入不得被 if 语句包裹
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        body_src = "\n".join(ast.unparse(s) for s in node.body)
        assert "_save_daily_report" not in body_src, (
            f"{impl} 的 _save_daily_report 仍被条件分支包裹（{ast.unparse(node.test)}）"
        )


def test_monitor_daily_report_model_roundtrip():
    """日报 Pydantic 模型的 to_dict 字段与集合查询口径一致."""
    report = MonitorDailyReport(
        monitor_id="m-1",
        date="2026-08-25",
        nav=1023.82,
        performance={"custom_metrics": {"rebalance_count": 3}},
    )
    data = report.to_dict()

    assert data["monitor_id"] == "m-1"
    assert data["date"] == "2026-08-25"
    assert data["performance"]["custom_metrics"]["rebalance_count"] == 3
    assert "_id" not in data


# ============================================================
# 二、组合初始建仓记录（rebalance_records）
# ============================================================

class _StubModelService:
    def __init__(self, models):
        self._models = models

    async def get_model(self, model_id):
        return self._models.get(model_id)


def _published_model(model_id="m-1", name="测试独立策略", template="nous_low_vol",
                     status=ModelStatus.PUBLISHED):
    return SimpleNamespace(
        id=model_id,
        name=name,
        template_code=template,
        status=status,
    )


def _service_with_stubs(models):
    """构造不触库的 PortfolioService：策略查询、建组合、写记录全部打桩."""
    svc = PortfolioService()
    svc.strategy_model_service = _StubModelService(models)
    created = {}
    records = []

    async def fake_create_portfolio(portfolio):
        created["portfolio"] = portfolio
        return "pf-test-1"

    async def fake_add_rebalance_record(record):
        records.append(record)
        return f"rec-{len(records)}"

    svc.create_portfolio = fake_create_portfolio
    svc.add_rebalance_record = fake_add_rebalance_record
    return svc, created, records


def test_create_from_strategies_writes_initial_rebalance_record():
    """多策略直接组合必须落一条初始建仓调仓记录."""
    model = _published_model()
    svc, created, records = _service_with_stubs({"m-1": model})

    pid = _run(svc.create_from_strategies(
        strategy_ids=["m-1"],
        name="验收组合",
        initial_capital=10_000_000,
        sub_strategy_weights=[{"model_id": "m-1", "weight": 1.0}],
    ))

    assert pid == "pf-test-1"
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, RebalanceRecord)
    assert record.portfolio_id == "pf-test-1"
    assert record.action == RebalanceAction.BUY
    assert record.weights_before is None
    assert record.weights_after == {"m-1": 1.0}
    assert "建仓" in (record.reason or "")
    # 调仓日与组合成立日一致，便于前端按日期排序展示
    assert record.rebalance_date == created["portfolio"].inception_date


def test_create_from_strategies_record_weights_match_sub_allocations():
    """多子策略时建仓记录保存全部子策略权重，且与组合文档一致."""
    models = {
        "m-1": _published_model("m-1", "策略甲"),
        "m-2": _published_model("m-2", "策略乙"),
    }
    svc, created, records = _service_with_stubs(models)

    _run(svc.create_from_strategies(
        strategy_ids=["m-1", "m-2"],
        name="双子策略组合",
        initial_capital=10_000_000,
        sub_strategy_weights=[
            {"model_id": "m-1", "weight": 0.7},
            {"model_id": "m-2", "weight": 0.3},
        ],
    ))

    portfolio = created["portfolio"]
    assert portfolio.source == PortfolioSource.MANUAL
    assert records[0].weights_after == {"m-1": 0.7, "m-2": 0.3}
    assert {s.model_id: s.weight for s in portfolio.sub_strategies} == {"m-1": 0.7, "m-2": 0.3}


def test_create_from_strategies_rejects_unpublished_without_record():
    """未发布策略不得进入组合，也不产生任何调仓记录（前置校验不变）."""
    model = _published_model(status=ModelStatus.DRAFT)
    svc, created, records = _service_with_stubs({"m-1": model})

    with pytest.raises(ValueError, match="未发布"):
        _run(svc.create_from_strategies(
            strategy_ids=["m-1"],
            name="非法组合",
            sub_strategy_weights=[{"model_id": "m-1", "weight": 1.0}],
        ))

    assert not created
    assert not records


# ============================================================
# 三、自定义监控指标通用路径
# ============================================================

class _StubAdapter:
    """假适配器：返回 numpy 类型以验证 JSON 安全转换."""

    def __init__(self, payload=None, exc=None):
        self._payload = payload
        self._exc = exc
        self.calls = []

    def compute_monitoring_metrics(self, current_weights, prices_df):
        self.calls.append((dict(current_weights), prices_df.shape))
        if self._exc:
            raise self._exc
        return self._payload


class _MetricHost(DailyStepperMixin):
    def __init__(self, adapter):
        self._adapter = adapter
        self._merged_monitor_params = {}

    def _get_engine_adapter(self, rt):
        return self._adapter


def _state_with_weights(weights):
    return PortfolioState(
        date="2026-08-25",
        nav=1000.0,
        nav_base=1000.0,
        positions_cny={},
        positions_local={},
        apl_local={},
        target_weights=dict(weights),
        last_rebalance_date="",
        last_rebalance_fx={},
    )


def _prices(days=5, codes=("A.TEST", "B.TEST")):
    idx = pd.bdate_range("2026-08-19", periods=days)
    return pd.DataFrame({c: np.linspace(100.0, 101.0, days) for c in codes}, index=idx)


def test_json_safe_converts_numpy_and_nested_containers():
    """numpy 标量 / 数组 / 嵌套容器全部转成可落库原生类型."""
    raw = {
        "int64": np.int64(7),
        "float64": np.float64(0.25),
        "bool_": np.bool_(True),
        "array": np.array([1.0, 2.0]),
        "array_of_ints": np.array([1, 2]),
        "nested": {"inner": np.float64(0.5)},
        "tuple": (np.int64(1), "x"),
        "none": None,
        "text": "ok",
    }
    safe = _json_safe(raw)

    assert safe["int64"] == 7 and isinstance(safe["int64"], int)
    assert safe["float64"] == 0.25 and isinstance(safe["float64"], float)
    assert safe["bool_"] is True
    assert safe["array"] == [1.0, 2.0]
    assert safe["array_of_ints"] == [1, 2]
    assert safe["nested"] == {"inner": 0.5}
    assert safe["tuple"] == [1, "x"]
    assert safe["none"] is None
    assert safe["text"] == "ok"


def test_compute_custom_metrics_filters_weights_to_price_columns():
    """只有落在价格矩阵列内的持仓资产参与指标计算，且历史截止到当日."""
    adapter = _StubAdapter(payload={"rebalance_count": np.int64(3)})
    host = _MetricHost(adapter)
    state = _state_with_weights({"A.TEST": 0.6, "B.TEST": 0.4, "MISSING": 0.0})
    prices = _prices(days=5)
    date = prices.index[2]

    metrics = host._compute_custom_metrics(state, prices, date, rt=None)

    assert metrics == {"rebalance_count": 3}
    weights, shape = adapter.calls[0]
    assert set(weights) == {"A.TEST", "B.TEST"}
    assert shape == (3, 2)  # 截至信号日共 3 行


def test_compute_custom_metrics_returns_empty_without_usable_weights():
    """无持仓或无适配器时返回空字典，不抛错、不落脏数据."""
    host = _MetricHost(_StubAdapter(payload={"x": 1}))
    prices = _prices(days=5)

    assert host._compute_custom_metrics(_state_with_weights({}), prices, prices.index[-1]) == {}

    empty_host = _MetricHost(None)
    assert empty_host._compute_custom_metrics(
        _state_with_weights({"A.TEST": 1.0}), prices, prices.index[-1]
    ) == {}


def test_compute_custom_metrics_swallows_adapter_errors():
    """指标计算失败只记 warning，不得中断日度推演."""
    host = _MetricHost(_StubAdapter(exc=RuntimeError("boom")))
    prices = _prices(days=5)

    assert host._compute_custom_metrics(
        _state_with_weights({"A.TEST": 1.0}), prices, prices.index[-1]
    ) == {}


def test_portfolio_state_carries_custom_metrics_field():
    """日度内存态必须有 custom_metrics 槽位（步骤E2 写入点）."""
    state = PortfolioState(
        date="",
        nav=1000.0,
        nav_base=1000.0,
        positions_cny={},
        positions_local={},
        apl_local={},
        target_weights={},
        last_rebalance_date="",
        last_rebalance_fx={},
    )
    assert state.custom_metrics == {}
    state.custom_metrics = {"rebalance_count": 3}
    assert state.custom_metrics["rebalance_count"] == 3


def test_monitor_state_model_exposes_custom_metrics():
    """落库模型必须有 custom_metrics 字段，否则指标写不进 monitor_states."""
    assert "custom_metrics" in MonitorState.model_fields
    field = MonitorState.model_fields["custom_metrics"]
    assert field.default_factory is dict
    assert MonitorState(monitor_id="m-1", date="2026-08-25").custom_metrics == {}


def test_portfolio_state_to_state_maps_custom_metrics():
    """PortfolioState → MonitorState 的两条分支都要映射自定义指标."""
    ps = _state_with_weights({"A.TEST": 1.0})
    ps.custom_metrics = {"rebalance_count": 5, "constraint_trigger_counts": {"C1": 2}}
    stub_self = SimpleNamespace(_config_versions={}, _current_execution_policy=lambda: {})

    created = MonitorService._portfolio_state_to_state(stub_self, ps, "m-1", None)
    assert created.custom_metrics == ps.custom_metrics

    existing = MonitorState(monitor_id="m-1", date="2026-08-24")
    reused = MonitorService._portfolio_state_to_state(stub_self, ps, "m-1", existing)
    assert reused is existing
    assert reused.custom_metrics == ps.custom_metrics


def test_custom_metrics_are_json_safe_before_persisting():
    """落库前的指标须经 _json_safe，numpy 值不得直接进 Mongo."""
    ps = _state_with_weights({"A.TEST": 1.0})
    ps.custom_metrics = _json_safe({
        "rebalance_count": np.int64(11),
        "constraint_trigger_counts": {"C1": np.int64(4)},
    })
    stub_self = SimpleNamespace(_config_versions={}, _current_execution_policy=lambda: {})

    state = MonitorService._portfolio_state_to_state(stub_self, ps, "m-1", None)
    assert state.custom_metrics == {
        "rebalance_count": 11,
        "constraint_trigger_counts": {"C1": 4},
    }
    assert isinstance(state.custom_metrics["rebalance_count"], int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
