# -*- coding: utf-8 -*-
"""独立策略统一接入管道单测（形态标识 / 运行前门禁 / 自带风控放行 / 日历口径）.

对应计划的 A、D、E、F 四层：
- A 形态标识：strategy_form 从 STRATEGY_MANIFEST 派生到模板与 API schema
- D 运行前门禁：四处挂载点在契约失败时抛 DataContractError，空契约快速通过
- E 日历口径：calendar_source 从模型参数透传到监控运行时与 coerce_trade_dates
- F 风控放行：has_native_vol_control()=True 时 Pipeline 代理调用，False 时仍短路

不触库、不启引擎（挂库的两处门禁用 monkeypatch 与源码静态守卫覆盖）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.allocation.models.base import BaseStrategyModel
from app.allocation.strategy_manifest import STRATEGY_MANIFEST, StrategyEntry
from app.backtesting.composition_pipeline import _PIPELINE_CONTROL_KEYS
from app.backtesting.data_contract import DataContract, DataContractError, GroupSpec
from app.backtesting.runner import _gate_prices, build_pipeline
from app.models.model_template import ModelTemplate
from app.monitor.monitor_runtime import MonitorRuntimeConfig, _resolve_calendar_source
from app.monitor.time_norm import coerce_trade_dates
from app.schemas.model_template import ModelTemplateCreate, ModelTemplateOut

APP_DIR = Path(__file__).resolve().parent.parent / "app"


def _prices(days=60, codes=("A1", "A2"), start="2020-01-01"):
    idx = pd.bdate_range(start, periods=days)
    rng = np.random.default_rng(3)
    return pd.DataFrame(
        {c: 100.0 * np.cumprod(1 + rng.normal(0.0003, 0.003, days)) for c in codes},
        index=idx,
    )


def _run(coro):
    """本仓未装 pytest-asyncio，协程统一用 asyncio.run 驱动."""
    return asyncio.run(coro)


_STANDALONE_COMPOSITION = {"selector": None, "allocator": "fake_standalone", "controller": None}


class _FakeBase(BaseStrategyModel):
    """记录调用次数的假分配器（默认无自带风控、空契约 = 存量策略行为）."""

    def __init__(self):
        self.trigger_calls = 0
        self.reset_calls = 0

    def allocate(self, prices, **params):
        return pd.Series(dtype=float)

    def check_volatility_trigger(self, current_weights, prices, **params):
        self.trigger_calls += 1
        return True, 0.08

    def compute_volatility_reset_weights(self, current_weights, prices, **params):
        self.reset_calls += 1
        return current_weights * 0.5


class _NativeVolAllocator(_FakeBase):
    """打包独立形态：composition 三层全 None，风控写在策略包内."""

    def has_native_vol_control(self) -> bool:
        return True


class _ContractAllocator(_FakeBase):
    """声明了数据契约的假分配器（资产池至少 15 只）."""

    @classmethod
    def get_data_contract(cls) -> DataContract:
        return DataContract(
            min_assets=15,
            min_history_days=260,
            calendar="prices",
            require_continuous=True,
            group_params={"g1": GroupSpec(required=True, cover_pool=True)},
        )


class _BrokenContractAllocator(_FakeBase):
    """契约声明本身报错：不得被静默放行."""

    @classmethod
    def get_data_contract(cls) -> DataContract:
        raise RuntimeError("contract declaration broken")


# ---------------------------------------------------------------------------
# A 层：形态标识
# ---------------------------------------------------------------------------


class TestStrategyForm:
    def test_strategy_entry_defaults_to_composite(self):
        entry = StrategyEntry(class_path="x.Y", name="n", description="d")
        assert entry.strategy_form == "composite"

    def test_all_registered_entries_have_valid_form(self):
        for code, entry in STRATEGY_MANIFEST.items():
            assert entry.strategy_form in ("composite", "standalone"), code

    def test_model_template_defaults_to_composite(self):
        tpl = ModelTemplate(code="c", name="n", description="d")
        assert tpl.strategy_form == "composite"

    def test_api_schema_exposes_strategy_form(self):
        """前端要能拿到 strategy_form，否则无法识别形态（仍渲染三层卡片）."""
        assert "strategy_form" in ModelTemplateCreate.model_fields
        assert "strategy_form" in ModelTemplateOut.model_fields
        out = ModelTemplateCreate(code="c", name="n", description="d")
        assert out.strategy_form == "composite"

    def test_builtin_templates_derive_form_from_manifest(self):
        from app.allocation.builtin_templates import get_builtin_templates

        derived = {t["code"]: t.get("strategy_form") for t in get_builtin_templates()}
        for code, entry in STRATEGY_MANIFEST.items():
            if code not in derived:
                continue  # 类加载失败的策略在派生时被跳过（既有行为）
            assert derived[code] == entry.strategy_form, code

    def test_category_unchanged_for_allocation_templates(self):
        """形态标识不新增分类，避免改动模板服务过滤逻辑."""
        from app.allocation.builtin_templates import get_builtin_templates

        for tpl in get_builtin_templates():
            if tpl["code"] in STRATEGY_MANIFEST:
                assert tpl["category"] == "allocation"


# ---------------------------------------------------------------------------
# F 层：策略自带风控放行
# ---------------------------------------------------------------------------


class TestNativeVolControl:
    def test_base_strategy_defaults_to_false(self):
        assert _FakeBase().has_native_vol_control() is False

    def test_short_circuit_when_no_controller_and_no_native_control(self):
        allocator = _FakeBase()
        pipeline = build_pipeline(allocator, ["A1"], _STANDALONE_COMPOSITION, {})
        assert pipeline.check_volatility_trigger(pd.Series({"A1": 1.0}), _prices()) == (False, None)
        assert pipeline.compute_volatility_reset_weights(pd.Series({"A1": 1.0}), _prices()) is None
        assert allocator.trigger_calls == 0
        assert allocator.reset_calls == 0

    def test_delegates_when_native_vol_control_declared(self):
        allocator = _NativeVolAllocator()
        pipeline = build_pipeline(allocator, ["A1"], _STANDALONE_COMPOSITION, {})
        triggered, vol = pipeline.check_volatility_trigger(pd.Series({"A1": 1.0}), _prices())
        assert (triggered, vol) == (True, 0.08)
        assert allocator.trigger_calls == 1

        reset = pipeline.compute_volatility_reset_weights(pd.Series({"A1": 1.0}), _prices())
        assert reset is not None and float(reset["A1"]) == pytest.approx(0.5)
        assert allocator.reset_calls == 1

    def test_controller_path_unchanged(self):
        """配置了 controller 的三层组合形态：无论是否声明自带风控都代理."""
        allocator = _FakeBase()
        composition = {"selector": None, "allocator": "fake", "controller": "rolling_vol"}
        pipeline = build_pipeline(allocator, ["A1"], composition, {})
        assert pipeline.check_volatility_trigger(pd.Series({"A1": 1.0}), _prices())[0] is True
        assert allocator.trigger_calls == 1

    def test_declaration_error_degrades_to_no_native_control(self):
        """声明读取异常时按无自带风控处理，不静默放大风控范围."""

        class _Raises(_FakeBase):
            def has_native_vol_control(self):
                raise RuntimeError("boom")

        pipeline = build_pipeline(_Raises(), ["A1"], _STANDALONE_COMPOSITION, {})
        assert pipeline.check_volatility_trigger(pd.Series({"A1": 1.0}), _prices()) == (False, None)

    def test_native_control_flag_is_cached(self):
        allocator = _NativeVolAllocator()
        pipeline = build_pipeline(allocator, ["A1"], _STANDALONE_COMPOSITION, {})
        assert pipeline._native_vol_control is None
        assert pipeline._allocator_has_native_vol_control() is True
        assert pipeline._native_vol_control is True

    def test_daily_stepper_vol_reset_has_no_controller_gate(self):
        """监控侧 vol_reset 走 signal_detector，不依赖 composition.controller."""
        source = (APP_DIR / "monitor" / "daily_stepper.py").read_text(encoding="utf-8")
        assert "controller" not in source
        assert "check_volatility_reset" in source


# ---------------------------------------------------------------------------
# D 层：运行前门禁
# ---------------------------------------------------------------------------


class TestGates:
    def test_build_pipeline_rejects_static_violation(self):
        with pytest.raises(DataContractError) as exc_info:
            build_pipeline(_ContractAllocator(), ["A1", "A2"], _STANDALONE_COMPOSITION, {})
        text = str(exc_info.value)
        assert "fake_standalone" in text   # 策略标识取 composition.allocator
        assert "too_few_assets" not in text  # 呈现的是中文说明而非机器码
        assert "2" in text and "15" in text

    def test_build_pipeline_passes_for_empty_contract(self):
        pipeline = build_pipeline(_FakeBase(), ["A1"], _STANDALONE_COMPOSITION, {})
        assert pipeline is not None

    def test_broken_contract_declaration_is_not_swallowed(self):
        with pytest.raises(RuntimeError, match="contract declaration broken"):
            build_pipeline(_BrokenContractAllocator(), ["A1"], _STANDALONE_COMPOSITION, {})

    def test_gate_prices_uses_strategy_prices_not_sanitized(self):
        """门禁必须读未清洗矩阵：sanitized 矩阵已 ffill 缺日，校验会恒通过."""
        raw = _prices(days=300)
        raw.iloc[100:150, 1] = np.nan           # A2 缺 50 天 + 只剩 250 条
        sanitized = raw.ffill()                  # 模拟 sanitize_prices 的结果

        spec = SimpleNamespace(
            allocator=_ContractAllocator(),
            composition=_STANDALONE_COMPOSITION,
            thscodes=["A1", "A2"],
            strategy_params={"g1": "A1,A2"},
            config=SimpleNamespace(thscodes=["A1", "A2"]),
            data_feed=SimpleNamespace(prices=sanitized, strategy_prices=raw),
        )
        with pytest.raises(DataContractError) as exc_info:
            _gate_prices(spec, None)
        codes = {v.code for v in exc_info.value.violations}
        assert "calendar_inconsistent" in codes
        assert "history_too_short" in codes

        # 同一份数据若误用 sanitized 矩阵，日历不一致检查会失效
        spec.data_feed.strategy_prices = None
        spec.data_feed.prices = sanitized
        report_codes = set()
        try:
            _gate_prices(spec, None)
        except DataContractError as exc:
            report_codes = {v.code for v in exc.violations}
        assert "calendar_inconsistent" not in report_codes

    def test_gate_prices_falls_back_to_strategy_allocator(self):
        """特殊路径（直传已构建策略）：从 Pipeline 取 allocator."""
        raw = _prices(days=300)
        raw.iloc[100, 1] = np.nan
        pipeline = SimpleNamespace(_allocator=_ContractAllocator())
        spec = SimpleNamespace(
            allocator=None,
            composition=_STANDALONE_COMPOSITION,
            thscodes=["A1", "A2"],
            strategy_params={"g1": "A1,A2"},
            config=SimpleNamespace(thscodes=["A1", "A2"]),
            data_feed=SimpleNamespace(prices=raw, strategy_prices=raw),
        )
        with pytest.raises(DataContractError):
            _gate_prices(spec, pipeline)

    def test_gate_prices_passes_for_empty_contract(self):
        raw = _prices(days=30)
        spec = SimpleNamespace(
            allocator=_FakeBase(),
            composition=_STANDALONE_COMPOSITION,
            thscodes=["A1", "A2"],
            strategy_params={},
            config=SimpleNamespace(thscodes=["A1", "A2"]),
            data_feed=SimpleNamespace(prices=raw, strategy_prices=raw),
        )
        _gate_prices(spec, None)  # 不抛即通过

    def test_publish_gate_is_wired(self):
        """挂载点 3：实盘发布前执行静态面契约门禁（防止被误删）."""
        source = (APP_DIR / "services" / "live_publish_service.py").read_text(encoding="utf-8")
        assert "enforce_static_contract" in source
        publish_body = source.split("async def publish_model", 1)[1].split("async def ", 1)[0]
        assert "enforce_static_contract" in publish_body
        # 门禁必须在冻结快照之前
        assert publish_body.index("enforce_static_contract") < publish_body.index(
            "_build_snapshot_with_universe(model)"
        )

    def test_monitor_gate_is_wired(self):
        """挂载点 4：监控初始化取数后执行数据面契约门禁."""
        source = (APP_DIR / "services" / "monitor_service.py").read_text(encoding="utf-8")
        assert source.count("enforce_price_contract") >= 2  # 局部 import + 调用
        anchor = source.index('raise ValueError("价格数据为空，无法初始化")')
        window = source[anchor: anchor + 2000]
        assert "enforce_price_contract" in window
        assert "prices=prices_df" in window

    def test_engine_gates_are_wired(self):
        """挂载点 1、2：唯一构造点与唯一运行入口都挂了门禁."""
        source = (APP_DIR / "backtesting" / "runner.py").read_text(encoding="utf-8")
        build_body = source.split("def build_pipeline(", 1)[1].split("def run_unified", 1)[0]
        assert "_gate_static(" in build_body
        run_body = source.split("def run_unified(", 1)[1].split("def generate_targets", 1)[0]
        assert "_gate_prices(" in run_body


class TestContractService:
    def test_resolve_contract_returns_none_for_unknown_template(self):
        from app.services.strategy_data_contract_service import resolve_contract

        assert resolve_contract(None) is None
        assert resolve_contract("") is None
        assert resolve_contract("no_such_template_code") is None

    def test_resolve_contract_reads_class_declaration(self):
        from app.services.strategy_data_contract_service import resolve_contract

        for code in STRATEGY_MANIFEST:
            contract = resolve_contract(code)
            if contract is None:
                continue  # 类加载失败时既有派生逻辑同样跳过
            assert isinstance(contract, DataContract)

    def test_check_static_contract_skips_without_contract(self, monkeypatch):
        import app.services.strategy_data_contract_service as svc

        monkeypatch.setattr(svc, "resolve_contract", lambda code: None)
        report = _run(svc.check_static_contract("x", ["A1"], {}))
        assert report.passed is True and not report.violations

    def test_check_static_contract_skips_for_empty_contract(self, monkeypatch):
        """存量策略（空契约）快速通过，不查库."""
        import app.services.strategy_data_contract_service as svc

        monkeypatch.setattr(svc, "resolve_contract", lambda code: DataContract())

        async def boom(codes):
            raise AssertionError("空契约不应查库")

        monkeypatch.setattr(svc, "load_asset_meta", boom)
        assert _run(svc.check_static_contract("x", ["A1"], {})).passed is True

    def test_check_static_contract_uses_asset_meta(self, monkeypatch):
        import app.services.strategy_data_contract_service as svc

        contract = DataContract(
            group_params={"g1": GroupSpec(required=True)},
            expected_asset_class={"g1": "固收"},
        )
        monkeypatch.setattr(svc, "resolve_contract", lambda code: contract)
        captured = {}

        async def fake_meta(codes):
            captured["codes"] = list(codes)
            return {"A1": {"asset_class": "权益"}}

        monkeypatch.setattr(svc, "load_asset_meta", fake_meta)
        report = _run(svc.check_static_contract("x", ["A1"], {"g1": "A1"}))
        assert [v.code for v in report.errors] == ["asset_class_mismatch"]
        assert captured["codes"] == ["A1"]

    def test_group_only_codes_are_looked_up_in_meta(self, monkeypatch):
        """分组参数里写了库中不存在的代码，同样需在发布时拦住."""
        import app.services.strategy_data_contract_service as svc

        contract = DataContract(
            group_params={"g1": GroupSpec(required=True)},
            expected_asset_class={"g1": "固收"},
        )
        monkeypatch.setattr(svc, "resolve_contract", lambda code: contract)
        captured = {}

        async def fake_meta(codes):
            captured["codes"] = list(codes)
            return {"A1": {"asset_class": "固收"}}

        monkeypatch.setattr(svc, "load_asset_meta", fake_meta)
        report = _run(svc.check_static_contract("x", ["A1"], {"g1": "A1,A9"}))
        assert captured["codes"] == ["A1", "A9"]
        assert "asset_not_found" in [v.code for v in report.errors]


# ---------------------------------------------------------------------------
# E 层：日历口径可声明
# ---------------------------------------------------------------------------


class TestCalendarSource:
    def test_default_source_keeps_trade_dates(self):
        prices = _prices(days=10)
        td = [pd.Timestamp("2019-01-01"), pd.Timestamp("2019-01-02")]
        assert coerce_trade_dates(td, prices) == td
        assert coerce_trade_dates(td, prices, "trade_dates") == td

    def test_prices_source_uses_price_index(self):
        prices = _prices(days=10)
        td = [pd.Timestamp("2019-01-01")]
        out = coerce_trade_dates(td, prices, "prices")
        assert out == sorted(prices.index.tolist())
        assert len(out) == 10

    def test_prices_source_falls_back_when_matrix_empty(self):
        td = [pd.Timestamp("2019-01-01")]
        assert coerce_trade_dates(td, pd.DataFrame(), "prices") == td

    def test_trade_dates_source_falls_back_to_prices_when_calendar_empty(self):
        prices = _prices(days=5)
        assert len(coerce_trade_dates([], prices)) == 5

    def test_resolve_calendar_source_always_prices(self):
        # 系统策略恒用价格日历（资产价格日期并集）；trade_dates 仅研究员策略
        # sharpe_18/hybrid_12 由 _build_rt_from_researcher 显式声明，不经此函数
        assert _resolve_calendar_source({}) == "prices"
        assert _resolve_calendar_source({"calendar_source": None}) == "prices"
        assert _resolve_calendar_source({"calendar_source": ""}) == "prices"
        assert _resolve_calendar_source({"calendar_source": "prices"}) == "prices"
        assert _resolve_calendar_source({"calendar_source": "trade_dates"}) == "prices"
        assert _resolve_calendar_source({"calendar_source": "TRADE_DATES"}) == "prices"

    def test_resolve_calendar_source_ignores_unknown_value(self):
        # 非法值不再回退 trade_dates，系统策略恒用价格日历
        assert _resolve_calendar_source({"calendar_source": "lunar"}) == "prices"

    def test_runtime_config_defaults_to_prices(self):
        # 系统策略默认资产价格日历；研究员策略在 _build_rt_from_researcher 显式改 trade_dates
        rt = MonitorRuntimeConfig(
            asset_list=["A1"], target_vol=0.05, vol_trigger_threshold=0.06,
            max_leverage=1.0, weight_caps={},
        )
        assert rt.calendar_source == "prices"

    def test_runtime_from_snapshot_passes_calendar_source(self):
        from app.monitor.monitor_runtime import monitor_runtime_from_snapshot

        snap = {
            "template_code": "nous_low_vol",
            "asset_codes": ["A1", "A2"],
            "parameters": {"calendar_source": "prices", "target_vol": 0.06},
        }
        rt = monitor_runtime_from_snapshot(snap)
        assert rt is not None
        assert rt.calendar_source == "prices"
        assert rt.strategy_params.get("calendar_source") == "prices"

    def test_runtime_from_snapshot_defaults_without_declaration(self):
        from app.monitor.monitor_runtime import monitor_runtime_from_snapshot

        snap = {"template_code": "risk_parity", "asset_codes": ["A1"], "parameters": {}}
        rt = monitor_runtime_from_snapshot(snap)
        assert rt.calendar_source == "prices"

    def test_param_schema_no_longer_declares_calendar_source(self):
        # 日历口径不再作为系统策略可配置参数：系统恒用资产价格日历（并集），
        # trade_dates 仅研究员策略内部使用，不对前端暴露
        from app.allocation.models.param_schema import model_level_param_group

        params = {p.name: p for p in model_level_param_group()}
        assert "calendar_source" not in params

    def test_calendar_source_is_runtime_whitelisted(self):
        from app.services.strategy_model_service import _RUNTIME_PARAM_WHITELIST

        assert "calendar_source" in _RUNTIME_PARAM_WHITELIST

    def test_calendar_source_not_forwarded_to_allocator(self):
        assert "calendar_source" in _PIPELINE_CONTROL_KEYS

    def test_contract_calendar_source_param_no_longer_warns(self):
        # calendar_source 模型参数已停用，契约不再因其与 calendar 声明不一致而告警
        from app.backtesting.data_contract import validate_static

        contract = DataContract(min_assets=1, calendar="prices")
        report = validate_static(contract, ["A1"], {"calendar_source": "trade_dates"})
        assert report.passed is True
        assert "calendar_source_mismatch" not in [v.code for v in report.warnings]
