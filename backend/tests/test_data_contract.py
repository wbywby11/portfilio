# -*- coding: utf-8 -*-
"""策略数据契约校验纯函数单测（app/backtesting/data_contract.py）.

覆盖计划 C 层的全部违规场景：历史不足、日历不一致、单日跳变、价格非正、
分组必填/最小组内只数/未覆盖全池/池外成员、资产大类不匹配、
声明了 custom_check 却未实现，以及空契约快速通过。

本模块不触库、不启引擎，纯 pandas 构造。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.data_contract import (
    CALENDAR_SOURCES,
    ContractReport,
    ContractViolation,
    DataContract,
    DataContractError,
    GroupSpec,
    merge_reports,
    parse_asset_codes,
    validate_custom,
    validate_static,
    validate_with_prices,
)


def _codes(*items):
    return [f"A{i}" for i in items]


def _prices(days=300, codes=("A1", "A2"), start="2020-01-01", seed=7):
    """构造连续日历的价格矩阵（几何随机游走，无缺日、无异常跳变）."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=days)
    data = {}
    for j, code in enumerate(codes):
        rets = rng.normal(0.0004, 0.004, size=days)
        data[code] = 100.0 * (1 + j * 0.1) * np.cumprod(1 + rets)
    return pd.DataFrame(data, index=idx)


def _violation_codes(report: ContractReport):
    return [v.code for v in report.violations]


# ---------------------------------------------------------------------------
# 空契约：存量策略零影响
# ---------------------------------------------------------------------------


class TestEmptyContract:
    def test_default_contract_is_empty(self):
        assert DataContract().is_empty is True

    def test_empty_contract_passes_all_three_validators(self):
        contract = DataContract()
        assert validate_static(contract, [], {}).passed is True
        assert validate_with_prices(contract, [], {}, None).passed is True
        assert validate_custom(contract, object(), None, {}).passed is True

    def test_none_contract_passes(self):
        assert validate_static(None, _codes(1), {}).passed is True
        assert validate_with_prices(None, _codes(1), {}, None).passed is True
        assert validate_custom(None, object(), None, {}).passed is True

    def test_any_single_requirement_makes_contract_non_empty(self):
        assert DataContract(min_assets=1).is_empty is False
        assert DataContract(min_history_days=1).is_empty is False
        assert DataContract(require_continuous=True).is_empty is False
        assert DataContract(max_single_day_jump=0.5).is_empty is False
        assert DataContract(min_price=1.0).is_empty is False
        assert DataContract(calendar="trade_dates").is_empty is False
        assert DataContract(custom_checks=("x",)).is_empty is False
        assert DataContract(group_params={"g": GroupSpec()}).is_empty is False
        assert DataContract(expected_asset_class={"g": "权益"}).is_empty is False


# ---------------------------------------------------------------------------
# validate_static
# ---------------------------------------------------------------------------


class TestValidateStatic:
    def test_too_few_assets(self):
        contract = DataContract(min_assets=15)
        report = validate_static(contract, _codes(1, 2, 3), {})
        assert report.passed is False
        assert "too_few_assets" in _violation_codes(report)
        text = report.errors[0].message
        assert "3" in text and "15" in text  # 含实际值与要求值

    def test_empty_pool_message(self):
        report = validate_static(DataContract(min_assets=2), [], {})
        assert "too_few_assets" in _violation_codes(report)
        assert "资产池为空" in report.errors[0].message

    def test_min_assets_satisfied(self):
        assert validate_static(DataContract(min_assets=2), _codes(1, 2), {}).passed

    def test_group_required_but_missing(self):
        contract = DataContract(group_params={"qdii_codes": GroupSpec(required=True)})
        report = validate_static(contract, _codes(1), {"qdii_codes": ""})
        assert "group_missing" in _violation_codes(report)

    def test_group_optional_and_empty_ok(self):
        contract = DataContract(
            group_params={"gold_codes": GroupSpec(required=False, cover_pool=False)}
        )
        assert validate_static(contract, _codes(1), {}).passed is True

    def test_group_too_small(self):
        contract = DataContract(
            group_params={"a_bond_codes": GroupSpec(required=True, min_size=3)}
        )
        report = validate_static(contract, _codes(1, 2), {"a_bond_codes": "A1,A2"})
        assert "group_too_small" in _violation_codes(report)

    def test_pool_not_covered(self):
        contract = DataContract(
            group_params={
                "g1": GroupSpec(required=True, cover_pool=True),
                "g2": GroupSpec(required=False, cover_pool=True),
            }
        )
        report = validate_static(
            contract, _codes(1, 2, 3), {"g1": "A1", "g2": "A2"}
        )
        assert "pool_not_covered" in _violation_codes(report)
        assert "A3" in report.errors[0].message

    def test_group_member_not_in_pool(self):
        contract = DataContract(
            group_params={"g1": GroupSpec(required=True, cover_pool=True)}
        )
        report = validate_static(contract, _codes(1), {"g1": "A1,A9"})
        codes = _violation_codes(report)
        assert "group_member_not_in_pool" in codes
        assert "A9" in [v.message for v in report.errors][0]

    def test_full_pool_covered_passes(self):
        contract = DataContract(
            min_assets=2,
            group_params={
                "g1": GroupSpec(required=True, cover_pool=True, min_size=1),
                "g2": GroupSpec(required=True, cover_pool=True, min_size=1),
            },
        )
        report = validate_static(contract, _codes(1, 2), {"g1": "A1", "g2": "A2"})
        assert report.passed is True, report.violations

    def test_expected_asset_class_skipped_without_meta(self):
        """引擎层拿不到库数据：asset_meta=None 时跳过资产大类校验."""
        contract = DataContract(
            group_params={"g1": GroupSpec(required=True)},
            expected_asset_class={"g1": "固收"},
        )
        assert validate_static(contract, _codes(1), {"g1": "A1"}, None).passed is True

    def test_asset_class_mismatch(self):
        contract = DataContract(
            group_params={"g1": GroupSpec(required=True)},
            expected_asset_class={"g1": "固收"},
        )
        meta = {"A1": {"asset_class": "权益", "instrument_type": "指数型"}}
        report = validate_static(contract, _codes(1), {"g1": "A1"}, meta)
        assert "asset_class_mismatch" in _violation_codes(report)
        assert report.errors[0].asset == "A1"

    def test_asset_not_found_in_meta(self):
        contract = DataContract(
            group_params={"g1": GroupSpec(required=True)},
            expected_asset_class={"g1": "固收"},
        )
        report = validate_static(contract, _codes(1), {"g1": "A1"}, {})
        assert "asset_not_found" in _violation_codes(report)

    def test_asset_class_match_passes(self):
        contract = DataContract(
            group_params={"g1": GroupSpec(required=True)},
            expected_asset_class={"g1": "固收"},
        )
        meta = {"A1": {"asset_class": "固收"}}
        assert validate_static(contract, _codes(1), {"g1": "A1"}, meta).passed is True

    def test_calendar_source_param_no_longer_warns(self):
        """calendar_source 已从系统参数收敛，契约不再对其做一致性告警."""
        contract = DataContract(min_assets=1, calendar="prices")
        report = validate_static(
            contract, _codes(1), {"calendar_source": "trade_dates"}
        )
        assert report.passed is True
        assert "calendar_source_mismatch" not in [v.code for v in report.warnings]

    def test_unknown_calendar_is_error(self):
        report = validate_static(DataContract(calendar="lunar"), _codes(1), {})
        assert "unknown_calendar" in _violation_codes(report)
        assert report.passed is False

    def test_declared_calendars_are_all_known(self):
        for cal in CALENDAR_SOURCES:
            report = validate_static(DataContract(calendar=cal), _codes(1), {})
            assert "unknown_calendar" not in _violation_codes(report)


# ---------------------------------------------------------------------------
# validate_with_prices
# ---------------------------------------------------------------------------


class TestValidateWithPrices:
    def test_history_too_short_lists_actual_count_and_first_valid_day(self):
        prices = _prices(days=300, codes=("A1", "A2"))
        prices.iloc[:100, 1] = np.nan  # A2 只剩 200 条
        contract = DataContract(min_history_days=260)
        report = validate_with_prices(contract, ["A1", "A2"], {}, prices)
        assert "history_too_short" in _violation_codes(report)
        err = [v for v in report.errors if v.code == "history_too_short"][0]
        assert err.asset == "A2"
        assert "200" in err.message and "260" in err.message
        assert "首个有效日" in err.message

    def test_history_sufficient_passes(self):
        prices = _prices(days=300)
        assert validate_with_prices(
            DataContract(min_history_days=260), ["A1", "A2"], {}, prices
        ).passed is True

    def test_calendar_inconsistent(self):
        prices = _prices(days=50, codes=("A1", "A2"))
        prices.iloc[10, 1] = np.nan  # A2 缺一天
        report = validate_with_prices(
            DataContract(require_continuous=True), ["A1", "A2"], {}, prices
        )
        assert "calendar_inconsistent" in _violation_codes(report)
        assert str(prices.index[10].date()) in report.errors[0].message

    def test_continuous_calendar_passes(self):
        prices = _prices(days=50)
        assert validate_with_prices(
            DataContract(require_continuous=True), ["A1", "A2"], {}, prices
        ).passed is True

    def test_single_day_jump(self):
        prices = _prices(days=50, codes=("A1",))
        prices.iloc[20, 0] = prices.iloc[19, 0] * 1.8  # +80%
        report = validate_with_prices(
            DataContract(max_single_day_jump=0.25), ["A1"], {}, prices
        )
        assert "price_jump" in _violation_codes(report)
        assert "80.0%" in report.errors[0].message

    def test_jump_within_threshold_passes(self):
        prices = _prices(days=50, codes=("A1",))
        assert validate_with_prices(
            DataContract(max_single_day_jump=0.25), ["A1"], {}, prices
        ).passed is True

    def test_non_positive_price_detected_by_default_min_price(self):
        """min_price 缺省 0.0 即要求价格严格为正（0 与负值都是脏数据）."""
        prices = _prices(days=20, codes=("A1",))
        prices.iloc[5, 0] = 0.0
        prices.iloc[6, 0] = -1.5
        report = validate_with_prices(DataContract(min_history_days=1), ["A1"], {}, prices)
        assert "non_positive_price" in _violation_codes(report)

    def test_prices_empty(self):
        report = validate_with_prices(
            DataContract(min_history_days=10), ["A1"], {}, pd.DataFrame()
        )
        assert "prices_empty" in _violation_codes(report)

    def test_prices_none(self):
        report = validate_with_prices(DataContract(min_history_days=10), ["A1"], {}, None)
        assert "prices_empty" in _violation_codes(report)

    def test_missing_asset_column(self):
        prices = _prices(days=20, codes=("A1",))
        report = validate_with_prices(
            DataContract(min_history_days=10), ["A1", "A9"], {}, prices
        )
        assert "prices_missing_assets" in _violation_codes(report)
        assert "A9" in report.errors[0].message

    def test_static_only_contract_skips_price_checks(self):
        """仅声明静态面要求时，价格为空也不报 prices_empty."""
        contract = DataContract(min_assets=1, group_params={"g": GroupSpec()})
        assert validate_with_prices(contract, _codes(1), {}, None).passed is True


# ---------------------------------------------------------------------------
# validate_custom
# ---------------------------------------------------------------------------


class _CustomStrategy:
    """实现了两个自定义检查的假策略."""

    def __init__(self, fail_reason=None, raise_exc=None):
        self._fail_reason = fail_reason
        self._raise_exc = raise_exc
        self.calls = []

    def _check_group_caps_feasible(self, prices, params):
        self.calls.append(("group_caps_feasible", prices is not None, dict(params)))
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._fail_reason


class TestValidateCustom:
    def test_pass_when_check_returns_none(self):
        strategy = _CustomStrategy()
        contract = DataContract(custom_checks=("group_caps_feasible",))
        report = validate_custom(contract, strategy, _prices(days=5), {"k": 1})
        assert report.passed is True
        assert strategy.calls[0][0] == "group_caps_feasible"
        assert strategy.calls[0][2] == {"k": 1}

    def test_empty_string_means_pass(self):
        contract = DataContract(custom_checks=("group_caps_feasible",))
        assert validate_custom(contract, _CustomStrategy(""), None, {}).passed is True

    def test_failed_reason_reported(self):
        contract = DataContract(custom_checks=("group_caps_feasible",))
        report = validate_custom(
            contract, _CustomStrategy("qdii_cap 之和超过 1"), None, {}
        )
        assert "custom_check_failed" in _violation_codes(report)
        assert "qdii_cap 之和超过 1" in report.errors[0].message

    def test_declared_but_not_implemented_is_error(self):
        """声明了却没实现属于配置错误，不静默跳过."""
        contract = DataContract(custom_checks=("not_implemented",))
        report = validate_custom(contract, _CustomStrategy(), None, {})
        assert "custom_check_missing" in _violation_codes(report)
        assert report.passed is False
        assert "_check_not_implemented" in report.errors[0].message

    def test_check_raising_is_not_treated_as_pass(self):
        contract = DataContract(custom_checks=("group_caps_feasible",))
        report = validate_custom(
            contract, _CustomStrategy(raise_exc=RuntimeError("boom")), None, {}
        )
        assert "custom_check_error" in _violation_codes(report)
        assert report.passed is False
        assert "boom" in report.errors[0].message

    def test_no_custom_checks_short_circuits(self):
        assert validate_custom(DataContract(), object(), None, {}).passed is True


# ---------------------------------------------------------------------------
# 报告与异常
# ---------------------------------------------------------------------------


class TestReportAndError:
    def test_raise_if_failed_noop_when_passed(self):
        ContractReport().raise_if_failed("demo")  # 不抛即通过

    def test_raise_if_failed_message_contains_label_values_and_hints(self):
        report = validate_static(DataContract(min_assets=15), _codes(1, 2), {})
        with pytest.raises(DataContractError) as exc_info:
            report.raise_if_failed("nous_low_vol")
        text = str(exc_info.value)
        assert "nous_low_vol" in text          # 策略标识
        assert "2" in text and "15" in text    # 实际值与要求值
        assert "修复建议" in text               # 修复建议
        assert exc_info.value.strategy_label == "nous_low_vol"
        assert len(exc_info.value.violations) == 1

    def test_data_contract_error_is_value_error(self):
        """继承 ValueError，复用 API 层既有的 400 转换惯例."""
        report = validate_static(DataContract(min_assets=1), [], {})
        with pytest.raises(ValueError):
            report.raise_if_failed("x")

    def test_warnings_alone_do_not_block(self):
        report = ContractReport()
        report.add(code="w", message="提示", level="warning")
        assert report.passed is True
        report.raise_if_failed("x")
        assert len(report.warnings) == 1 and not report.errors

    def test_violation_format(self):
        v = ContractViolation(
            level="error", code="c", message="消息", hint="建议", asset="A1"
        )
        assert v.format() == "[A1] 消息（修复建议：建议）"
        assert ContractViolation("error", "c", "消息").format() == "消息"

    def test_merge_reports(self):
        a = validate_static(DataContract(min_assets=5), _codes(1), {})
        b = validate_with_prices(
            DataContract(min_history_days=10), ["A1"], {}, pd.DataFrame()
        )
        merged = merge_reports(a, b, None)
        assert "too_few_assets" in _violation_codes(merged)
        assert "prices_empty" in _violation_codes(merged)
        assert merged.passed is False


# ---------------------------------------------------------------------------
# parse_asset_codes
# ---------------------------------------------------------------------------


class TestParseAssetCodes:
    @pytest.mark.parametrize("raw", [None, "", "   ", [], ()])
    def test_empty_inputs(self, raw):
        assert parse_asset_codes(raw) == []

    def test_comma_separated_text(self):
        assert parse_asset_codes("A1, A2 ,A3") == ["A1", "A2", "A3"]

    def test_chinese_and_other_separators(self):
        assert parse_asset_codes("A1，A2、A3；A4;A5|A6") == [
            "A1", "A2", "A3", "A4", "A5", "A6",
        ]

    def test_whitespace_and_newline_separated(self):
        assert parse_asset_codes("A1\nA2\tA3 A4") == ["A1", "A2", "A3", "A4"]

    def test_list_input_preserved(self):
        assert parse_asset_codes(["A1", " A2 ", ""]) == ["A1", "A2"]

    def test_non_string_scalars_stringified(self):
        assert parse_asset_codes([10, 20]) == ["10", "20"]
