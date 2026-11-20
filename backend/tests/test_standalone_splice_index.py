# -*- coding: utf-8 -*-
"""因子的拼接指数（splice）单测：factor_score_index / bond_factor_score_index.

覆盖两个模板的拼接口径：

- 无可用截面（执行日早于最早期截面）+ 配置拼接指数 → 100% 持有指数；
- 截面滞后超 ``panel_max_lag_days`` + 配置拼接指数 → 自动拼接；
- 未配置拼接指数 → 保持原报错（存量模型零影响）；
- ``splice_until`` 显式窗口内无条件拼接，窗口外恢复因子打分；
- 拼接指数不在资产池 / 截止日无承接标的 / 日期非法 → 报错不静默；
- 面板根本未注入 → 即使配置拼接指数也报错（拼接只补历史，不掩盖管道故障）；
- bond 的成分快照（有截面但缺因子列）优先于拼接；
- 契约门禁 ``_check_params_coherent`` 拦截池外拼接指数与错配的截止日。

不触库、不启引擎，全部用构造的价格矩阵与截面。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.standalone_strategies.bond_factor_score_index.strategy import (
    BondFactorScoreIndexStrategy,
)
from app.standalone_strategies.factor_score_index.strategy import (
    FactorScoreIndexStrategy,
)

# 资产池：两只股票 + 两只债 + 拼接指数（真实指数代码形态）
_EQUITY_CODES = ("600000.SH", "600001.SH")
_BOND_CODES = ("102001.IB", "102002.IB")
_SPLICE_CODE = "512190.SH"

# 交易日轴：覆盖 2020 全年，够表达「早于首期截面」「滞后 21 个交易日」两种场景
_TRADE_DAYS = pd.bdate_range("2020-01-02", "2020-12-31")

# 首期截面日（晚于回测起点，模拟「历史截面没补」）
_FIRST_PANEL_DATE = pd.Timestamp("2021-01-04")


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture()
def equity_prices() -> pd.DataFrame:
    """股票池 + 拼接指数：全区间日频价格."""
    idx = _TRADE_DAYS
    return pd.DataFrame(
        {
            _EQUITY_CODES[0]: np.linspace(10.0, 12.0, len(idx)),
            _EQUITY_CODES[1]: np.linspace(20.0, 18.0, len(idx)),
            _SPLICE_CODE: np.linspace(1.0, 1.3, len(idx)),
        },
        index=idx,
    )


@pytest.fixture()
def bond_prices() -> pd.DataFrame:
    """券池 + 拼接指数：全区间日频价格."""
    idx = _TRADE_DAYS
    return pd.DataFrame(
        {
            _BOND_CODES[0]: np.linspace(100.0, 105.0, len(idx)),
            _BOND_CODES[1]: np.linspace(100.0, 103.0, len(idx)),
            _SPLICE_CODE: np.linspace(1.0, 1.3, len(idx)),
        },
        index=idx,
    )


def _equity_panel() -> pd.DataFrame:
    """股票因子截面：三因子 + 行业 + 市值齐备."""
    return pd.DataFrame(
        {
            "industry": ["银行", "医药"],
            "total_mv": [1.0e11, 5.0e10],
            "free_float_mv": [8.0e10, 4.0e10],
            "data_date": ["2019-12-31", "2019-12-31"],
            "profit_yoy_sq_dn": [30.0, 10.0],
            "pe_ttm_dn": [8.0, 40.0],
            "dividend_yield_ttm": [3.0, 1.0],
        },
        index=list(_EQUITY_CODES),
    )


def _bond_panel() -> pd.DataFrame:
    """债券券池截面：三因子 + 券池分组 + 发行人齐备."""
    return pd.DataFrame(
        {
            "industry": ["其它信用债", "其它信用债"],
            "issuer": ["发行人甲", "发行人乙"],
            "issue_size": [10.0, 20.0],
            "issuer_size": [100.0, 200.0],
            "modified_duration": [2.5, 3.0],
        },
        index=list(_BOND_CODES),
    )


def _bond_snapshot_panel() -> pd.DataFrame:
    """债券成分快照截面：缺数值因子列 → constituent_snapshot 模式."""
    return pd.DataFrame(
        {
            "industry": ["其它信用债", "其它信用债"],
            "issuer": ["发行人甲", "发行人乙"],
            "name": ["债A", "债B"],
        },
        index=list(_BOND_CODES),
    )


# ---------------------------------------------------------------------------
# factor_score_index：拼接判定
# ---------------------------------------------------------------------------


def test_factor_splices_when_no_panel_before_as_of(equity_prices):
    """执行日早于首期截面：配置拼接指数后改持指数，不再报错."""
    strat = FactorScoreIndexStrategy()
    as_of = pd.Timestamp("2020-03-02")
    w = strat.allocate(
        equity_prices,
        _as_of=as_of,
        _panel_factor_panel={_FIRST_PANEL_DATE: _equity_panel()},
        splice_index_code=_SPLICE_CODE,
    )
    assert w[_SPLICE_CODE] == pytest.approx(1.0)
    assert w.drop(_SPLICE_CODE).abs().sum() == pytest.approx(0.0)
    assert w.index.tolist() == list(equity_prices.columns)


def test_factor_splices_when_panel_lag_exceeds_limit(equity_prices):
    """截面存在但滞后超上限：自动拼接（该期截面不可信）."""
    strat = FactorScoreIndexStrategy()
    panel_date = pd.Timestamp("2020-06-01")
    w = strat.allocate(
        equity_prices,
        _as_of=pd.Timestamp("2020-06-30"),
        _panel_factor_panel={panel_date: _equity_panel()},
        panel_max_lag_days=5,
        splice_index_code=_SPLICE_CODE,
    )
    assert w[_SPLICE_CODE] == pytest.approx(1.0)


def test_factor_without_splice_keeps_original_error(equity_prices):
    """未配置拼接指数：保持原口径报错，不隐式改持指数."""
    strat = FactorScoreIndexStrategy()
    with pytest.raises(ValueError, match="之前无可用因子截面"):
        strat.allocate(
            equity_prices,
            _as_of=pd.Timestamp("2020-03-02"),
            _panel_factor_panel={_FIRST_PANEL_DATE: _equity_panel()},
        )


def test_factor_error_hints_splice_when_no_panel(equity_prices):
    """报错文本给出拼接指数的修复建议，而不只是「请补截面」."""
    strat = FactorScoreIndexStrategy()
    with pytest.raises(ValueError, match="splice_index_code"):
        strat.allocate(
            equity_prices,
            _as_of=pd.Timestamp("2020-03-02"),
            _panel_factor_panel={_FIRST_PANEL_DATE: _equity_panel()},
        )


def test_factor_panel_not_injected_raises_even_with_splice(equity_prices):
    """面板未注入属管道故障：即使配置拼接指数也不兜底."""
    strat = FactorScoreIndexStrategy()
    with pytest.raises(ValueError, match="未注入 factor_panel"):
        strat.allocate(
            equity_prices,
            _as_of=pd.Timestamp("2020-03-02"),
            splice_index_code=_SPLICE_CODE,
        )


# ---------------------------------------------------------------------------
# factor_score_index：splice_until 显式窗口
# ---------------------------------------------------------------------------


def test_factor_splice_until_forces_window(equity_prices):
    """截面可用但处于截止日之前：强制拼接（早期因子质量差时用它切换）."""
    strat = FactorScoreIndexStrategy()
    as_of = pd.Timestamp("2020-06-01")
    w = strat.allocate(
        equity_prices,
        _as_of=as_of,
        _panel_factor_panel={as_of: _equity_panel()},
        splice_index_code=_SPLICE_CODE,
        splice_until="2020-12-31",
    )
    assert w[_SPLICE_CODE] == pytest.approx(1.0)


def test_factor_splice_until_passed_resumes_scoring(equity_prices):
    """截止日之后：恢复因子打分，指数权重清零."""
    strat = FactorScoreIndexStrategy()
    panel_date = pd.Timestamp("2020-11-30")
    w = strat.allocate(
        equity_prices,
        _as_of=pd.Timestamp("2020-12-01"),
        _panel_factor_panel={panel_date: _equity_panel()},
        splice_index_code=_SPLICE_CODE,
        splice_until="2020-06-30",
    )
    assert w[_SPLICE_CODE] == pytest.approx(0.0)
    assert w[list(_EQUITY_CODES)].sum() == pytest.approx(1.0)


def test_factor_splice_until_without_code_raises(equity_prices):
    """只配截止日不配指数：参数不自洽，直接报错."""
    strat = FactorScoreIndexStrategy()
    with pytest.raises(ValueError, match="splice_index_code 为空"):
        strat.allocate(
            equity_prices,
            _as_of=pd.Timestamp("2020-06-01"),
            _panel_factor_panel={pd.Timestamp("2020-06-01"): _equity_panel()},
            splice_until="2020-12-31",
        )


def test_factor_splice_until_bad_format_raises(equity_prices):
    """截止日格式非法：报错，不静默当成空值."""
    strat = FactorScoreIndexStrategy()
    with pytest.raises(ValueError, match="splice_until"):
        strat.allocate(
            equity_prices,
            _as_of=pd.Timestamp("2020-06-01"),
            _panel_factor_panel={pd.Timestamp("2020-06-01"): _equity_panel()},
            splice_index_code=_SPLICE_CODE,
            splice_until="2020-13-01",
        )


def test_factor_splice_code_outside_pool_raises(equity_prices):
    """拼接指数不在资产池：报错，不让 reindex 静默清零."""
    strat = FactorScoreIndexStrategy()
    with pytest.raises(ValueError, match="不在资产池"):
        strat.allocate(
            equity_prices,
            _as_of=pd.Timestamp("2020-03-02"),
            _panel_factor_panel={_FIRST_PANEL_DATE: _equity_panel()},
            splice_index_code="999999.SH",
        )


# ---------------------------------------------------------------------------
# bond_factor_score_index：拼接与成分快照的优先级
# ---------------------------------------------------------------------------


def test_bond_splices_when_no_panel_before_as_of(bond_prices):
    """执行日早于首期券池截面：配置拼接指数后改持指数."""
    strat = BondFactorScoreIndexStrategy()
    w = strat.allocate(
        bond_prices,
        _as_of=pd.Timestamp("2020-03-02"),
        _panel_factor_panel={_FIRST_PANEL_DATE: _bond_panel()},
        splice_index_code=_SPLICE_CODE,
    )
    assert w[_SPLICE_CODE] == pytest.approx(1.0)
    assert w.drop(_SPLICE_CODE).abs().sum() == pytest.approx(0.0)


def test_bond_without_splice_keeps_original_error(bond_prices):
    """未配置拼接指数：保持「之前无可用券池截面」报错."""
    strat = BondFactorScoreIndexStrategy()
    with pytest.raises(ValueError, match="之前无可用券池截面"):
        strat.allocate(
            bond_prices,
            _as_of=pd.Timestamp("2020-03-02"),
            _panel_factor_panel={_FIRST_PANEL_DATE: _bond_panel()},
        )


def test_bond_snapshot_precedes_splice(bond_prices):
    """有截面但缺因子列：走成分快照等权，不触发拼接."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2020-06-01")
    w = strat.allocate(
        bond_prices,
        _as_of=as_of,
        _panel_factor_panel={as_of: _bond_snapshot_panel()},
        splice_index_code=_SPLICE_CODE,
    )
    assert w[_SPLICE_CODE] == pytest.approx(0.0)
    assert w[list(_BOND_CODES)].sum() == pytest.approx(1.0)


def test_bond_splice_until_forces_window(bond_prices):
    """截止日之前：即使截面可用也强制持有拼接指数."""
    strat = BondFactorScoreIndexStrategy()
    as_of = pd.Timestamp("2020-06-01")
    w = strat.allocate(
        bond_prices,
        _as_of=as_of,
        _panel_factor_panel={as_of: _bond_panel()},
        splice_index_code=_SPLICE_CODE,
        splice_until="2020-12-31",
    )
    assert w[_SPLICE_CODE] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 审计指标与契约门禁
# ---------------------------------------------------------------------------


def test_factor_splice_metrics_are_auditable(equity_prices):
    """拼接期指标留痕：selection_source / splice_reason / splice_index_code."""
    strat = FactorScoreIndexStrategy()
    strat.allocate(
        equity_prices,
        _as_of=pd.Timestamp("2020-03-02"),
        _panel_factor_panel={_FIRST_PANEL_DATE: _equity_panel()},
        splice_index_code=_SPLICE_CODE,
    )
    metrics = strat.compute_monitoring_metrics(pd.Series(dtype=float), equity_prices)
    assert metrics["selection_source"] == "index_splice"
    assert metrics["splice_index_code"] == _SPLICE_CODE
    assert metrics["splice_reason"] == "no_panel_before_as_of"
    assert metrics["rebalance_count"] == 1


def test_bond_splice_metrics_are_auditable(bond_prices):
    """债券侧同样留痕：拼接期 selection_source=index_splice."""
    strat = BondFactorScoreIndexStrategy()
    strat.allocate(
        bond_prices,
        _as_of=pd.Timestamp("2020-03-02"),
        _panel_factor_panel={_FIRST_PANEL_DATE: _bond_panel()},
        splice_index_code=_SPLICE_CODE,
    )
    metrics = strat.compute_monitoring_metrics(pd.Series(dtype=float), bond_prices)
    assert metrics["selection_source"] == "index_splice"
    assert metrics["splice_reason"] == "no_panel_before_as_of"


def test_contract_check_rejects_splice_code_outside_pool(equity_prices):
    """契约门禁：运行前就拦下池外拼接指数，不等 allocate 才发现."""
    strat = FactorScoreIndexStrategy()
    reason = strat._check_params_coherent(equity_prices, {"splice_index_code": "999999.SH"})
    assert reason and "不在资产池" in reason


def test_contract_check_rejects_until_without_code():
    """契约门禁：只配截止日不配指数属参数不自洽."""
    strat = BondFactorScoreIndexStrategy()
    reason = strat._check_params_coherent(None, {"splice_until": "2020-12-31"})
    assert reason and "splice_index_code 为空" in reason


def test_contract_check_passes_with_valid_splice(equity_prices):
    """池内拼接指数 + 合法截止日：门禁放行."""
    strat = FactorScoreIndexStrategy()
    assert strat._check_params_coherent(
        equity_prices,
        {"splice_index_code": _SPLICE_CODE, "splice_until": "2022-12-31"},
    ) is None
