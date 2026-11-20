# -*- coding: utf-8 -*-
"""factor_panel 期日语义守卫：as_of 是决策日，data_date 不得晚于它.

研究员定稿的口径：``as_of_date`` 是信号决策日——T 日收盘用该截面算权重、
收益自 T+1 起；持仓明细的 ``startdate`` 是权重生效日，两者差一个交易日。
语义没有测试守住时，最典型的三种退化都不报错、只算错：

  - 把持仓生效日直接填进 ``as_of_date``：截面提前一天可用，回测偷跑一天收益；
  - ``data_date`` 晚于 ``as_of_date``：用了决策日之后才披露的数据（前视）；
  - 同一期日混入两个取数日：截面拼了两批数据，数值上完全看不出来。

本模块只断言校验与上报行为，不涉及 ``EQ_AS_OF`` 常量的取值与换算——
常量换算要等研究员确认后才动。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.factor_panel import FactorPanel
from app.schemas.import_protocol import ImportResponse
from app.services.factor_panel_service import FactorPanelService


def _panel(**overrides) -> FactorPanel:
    payload = {
        "dataset": "equity_quality_growth",
        "as_of_date": "2026-06-15",
        "data_date": "2026-03-31",
        "code": "000001.SZ",
        "industry": "银行",
        "factors": {"pe_ttm_dn": 8.5},
    }
    payload.update(overrides)
    return FactorPanel(**payload)


# ============================================================
# 一、前视校验：data_date <= as_of_date
# ============================================================

def test_data_date_after_as_of_is_rejected():
    """取数日晚于决策日即前视，模型直接拒绝（不是警告）."""
    with pytest.raises(ValidationError) as excinfo:
        _panel(data_date="2026-06-16")

    message = str(excinfo.value)
    assert "晚于决策日" in message
    assert "2026-06-16" in message and "2026-06-15" in message


@pytest.mark.parametrize("data_date", ["2026-06-15", "2026-03-31", "2019-12-31"])
def test_data_date_equal_or_before_as_of_is_allowed(data_date):
    """同期或更早的取数日都合法：截面只能用决策日及之前已披露的数据."""
    assert _panel(data_date=data_date).data_date == data_date


def test_blank_data_date_stays_none():
    """缺省不在这里补：补成 as_of 是 service 层的职责（导入时统一）."""
    assert _panel(data_date=None).data_date is None


# ============================================================
# 二、日期归一化：模型接受 YYYYMMDD，落库统一 YYYY-MM-DD
# ============================================================

@pytest.mark.parametrize("raw,expected", [
    ("20260615", "2026-06-15"),
    ("2026/06/15", "2026-06-15"),
    ("2026-06-15", "2026-06-15"),
    # 不补零与中文写法来自 Excel 手输，属于用户正常输入，不能报 400
    ("2026/6/15", "2026-06-15"),
    ("2026-6-15", "2026-06-15"),
    ("2026.6.15", "2026-06-15"),
    ("2026年6月15日", "2026-06-15"),
    ("2026-06-15 00:00:00", "2026-06-15"),
])
def test_as_of_date_is_normalized(raw, expected):
    """源文件里的多种写法统一成 YYYY-MM-DD，字符串序才等于日期序."""
    assert _panel(as_of_date=raw).as_of_date == expected


def test_unparsable_date_is_rejected():
    """无法识别的日期报错，不静默丢弃该行."""
    with pytest.raises(ValidationError):
        _panel(as_of_date="abc")


def test_impossible_date_is_rejected():
    """格式合法但日期不存在（2 月 30 日）必须报错，不能静默成 3 月 2 日."""
    with pytest.raises(ValidationError):
        _panel(as_of_date="2026-02-30")


# ============================================================
# 三、同一期多个取数日：不报错但必须显式上报
# ============================================================

def _doc(as_of: str, data_date: str, factors=None):
    return {
        "as_of_date": as_of,
        "data_date": data_date,
        "code": f"C-{data_date}",
        "factors": {"pe_ttm_dn": 1.0} if factors is None else factors,
    }


def _enrich(docs, warnings=None):
    return FactorPanelService._enrich_payload(
        ImportResponse(target_collection="factor_panel", total_rows=len(docs)),
        docs,
        {} if warnings is None else warnings,
        "equity_quality_growth",
    )


def test_same_period_with_two_data_dates_is_reported():
    """同期混入两批取数日：截面被拼接，必须让前端看见."""
    payload = _enrich([
        _doc("2026-06-15", "2026-03-31"),
        _doc("2026-06-15", "2026-06-15"),
    ])

    assert payload["warnings"]["periods_with_multiple_data_dates"] == ["2026-06-15"]
    assert payload["period_data_dates"] == {"2026-06-15": ["2026-03-31", "2026-06-15"]}


def test_single_data_date_per_period_is_not_reported():
    """每期只有一个取数日时不产生告警（正常导入不被打扰）."""
    payload = _enrich([
        _doc("2026-03-31", "2026-03-31"),
        _doc("2026-06-15", "2026-03-31"),
    ])

    assert "periods_with_multiple_data_dates" not in payload["warnings"]
    assert payload["period_data_dates"] == {
        "2026-03-31": ["2026-03-31"],
        "2026-06-15": ["2026-03-31"],
    }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
