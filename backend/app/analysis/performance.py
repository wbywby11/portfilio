"""统一绩效内核 — 全系统唯一的净值绩效计算实现.

设计原则
--------
1. **单一数据源**：所有指标都从同一条净值序列（nav）推导，不存在「指标用一份数据、
   曲线用另一份数据」的分叉。回撤序列与最大回撤同源，`max_drawdown ==
   drawdown_series.min()` 恒成立。
2. **单一口径**：年化因子、无风险利率、年化天数分母集中在此处定义。调用方只能通过
   参数覆盖，不得自行实现。
3. **不篡改数值**：检测到数据异常（净值非正、单日跳变过大、序列过短等）时记录到
   `warnings`，由上层决定如何呈现，绝不静默钳制或填充指标值。

口径说明（对外承诺，改动需同步本文档）
--------------------------------------
- 年化因子 `periods_per_year = 260`（全系统统一口径：260 交易日/年，
  与监控/波动控制链路及研究员原型对齐；app/formula 默认同步为 260）。
- 年化收益采用 CAGR：`(1 + total_return) ** (periods_per_year / n_periods) - 1`，
  其中 `n_periods = len(nav) - 1`，即净值序列的**区间数**（等于日收益序列长度）。
- 年化波动率 = 日收益标准差 × √periods_per_year，日收益为 `nav.pct_change()`。
- 夏普比率采用**几何口径**：`(annual_return - risk_free_rate) / annual_volatility`。
  注意这与 `app.formula.sharpe_ratio.compute_sharpe_ratio` 的算术口径
  （日超额收益均值/标准差×√260）不同，后者用于因子/资产层分析，两者不可混用。
- 最大回撤基于净值本身：`(nav - nav.cummax()) / nav.cummax()`，取值 ≤ 0。
- 胜率 = 相邻两个调仓日之间净值上涨的周期占比（调仓周期胜率），不依赖交易方向，
  适配所有策略类型；未提供调仓日时为 0。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 全系统口径常量
# ---------------------------------------------------------------------------

#: 年化因子（交易日/年）。全系统统一口径 = 260（与监控/波动控制链路一致）。
PERIODS_PER_YEAR = 260

#: 默认无风险利率（年化）。调用方可覆盖；集中在此避免各处硬编码 0.02。
DEFAULT_RISK_FREE_RATE = 0.02

#: 计算指标所需的最小净值点数
MIN_NAV_POINTS = 2

#: 单日净值涨跌幅超过此阈值时记录告警（仅告警，不修改数值）
ABNORMAL_DAILY_CHANGE = 0.5


@dataclass
class PerformanceMetrics:
    """净值绩效指标集合.

    纯数据容器。`warnings` 承载计算过程中发现的数据质量问题，
    上层（API/前端）应当展示而不是忽略——历史上这些异常被静默钳制掉，
    导致失真的指标看起来「正常」。
    """

    # 收益类
    total_return: float = 0.0
    annual_return: float = 0.0

    # 波动与风险类
    volatility: float = 0.0            # 日度波动率
    annual_volatility: float = 0.0     # 年化波动率
    max_drawdown: float = 0.0          # 最大回撤（≤0）

    # 比率类
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0
    return_drawdown_ratio: float = 0.0

    # 交易统计
    win_rate: float = 0.0

    # 计算元信息
    n_periods: int = 0                 # 参与年化的区间数（= len(nav) - 1）
    periods_per_year: int = PERIODS_PER_YEAR
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE

    # 数据质量告警
    warnings: List[str] = field(default_factory=list)


def _to_float(value, default: float = 0.0) -> float:
    """安全转 float：None/NaN/inf 统一落到 default。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def clean_nav_series(nav: pd.Series) -> tuple[pd.Series, List[str]]:
    """净值序列基础清理：仅处理无法参与计算的值，并记录告警.

    只做两件事：
    1. 非数值/inf 转为 NaN 后前向填充（净值缺失沿用上一日，这是净值序列的定义），
       首部无值可沿用时后向填充——此处不会引入未来信息，因为首部填充只影响
       「组合尚未成立」的时段，其收益率恒为 0。
    2. 记录数据质量告警（缺失、非正净值、单日异常跳变）。

    **不做**指标钳制，也**不**替换异常跳变的净值——那会让指标与净值曲线脱钩。
    """
    warnings: List[str] = []
    if nav is None or len(nav) == 0:
        return pd.Series(dtype=float), ["净值序列为空"]

    s = pd.to_numeric(nav, errors="coerce")
    s = s.replace([np.inf, -np.inf], np.nan)

    n_missing = int(s.isna().sum())
    if n_missing:
        warnings.append(f"净值序列存在 {n_missing} 个缺失值，已按前值沿用")
    s = s.ffill().bfill()

    if s.isna().all():
        return pd.Series(dtype=float, index=nav.index), warnings + ["净值序列全部无效"]

    n_nonpositive = int((s <= 0).sum())
    if n_nonpositive:
        warnings.append(f"净值序列存在 {n_nonpositive} 个非正值，指标可能失真")

    if len(s) >= 2:
        pct = s.pct_change(fill_method=None)
        abnormal = pct.abs() > ABNORMAL_DAILY_CHANGE
        n_abnormal = int(abnormal.sum())
        if n_abnormal:
            worst = float(pct.abs().max())
            warnings.append(
                f"净值序列存在 {n_abnormal} 个单日跳变超过 "
                f"{ABNORMAL_DAILY_CHANGE:.0%} 的时点（最大 {worst:.1%}），"
                f"请核查行情数据"
            )

    return s, warnings


def compute_drawdown_series(nav: pd.Series) -> pd.Series:
    """回撤序列 — 全系统唯一实现.

    公式：`DD_t = (NAV_t - max(NAV_0..NAV_t)) / max(NAV_0..NAV_t)`，取值 ≤ 0。

    与 `compute_performance().max_drawdown` 严格同源：
    `compute_performance(nav).max_drawdown == compute_drawdown_series(nav).min()`。
    """
    if nav is None or len(nav) == 0:
        return pd.Series(dtype=float)

    s = pd.to_numeric(nav, errors="coerce").replace([np.inf, -np.inf], np.nan)
    s = s.ffill().bfill()
    if s.isna().all():
        return pd.Series(0.0, index=nav.index)

    peak = s.cummax()
    dd = (s - peak) / peak.where(peak > 0, np.nan)
    return dd.fillna(0.0).replace([np.inf, -np.inf], 0.0)


def _win_rate_from_rebalance(nav: pd.Series, rebalance_dates: Optional[Sequence]) -> float:
    """调仓周期胜率：相邻调仓日之间净值上涨的周期占比。"""
    if not rebalance_dates or nav is None or nav.empty:
        return 0.0

    marks: List[pd.Timestamp] = []
    for d in rebalance_dates:
        try:
            marks.append(pd.Timestamp(d).normalize())
        except (TypeError, ValueError):
            continue
    if len(marks) < 2:
        return 0.0

    normalized_index = pd.DatetimeIndex(
        [pd.Timestamp(t).normalize() for t in nav.index]
    )
    mark_set = set(marks)
    values = [
        float(v)
        for t, v in zip(normalized_index, nav.values)
        if t in mark_set
    ]
    if len(values) < 2:
        return 0.0

    wins = 0
    cycles = 0
    for prev, curr in zip(values[:-1], values[1:]):
        if prev > 0:
            cycles += 1
            if curr > prev:
                wins += 1
    return wins / cycles if cycles else 0.0


def compute_performance(
    nav: pd.Series,
    *,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = PERIODS_PER_YEAR,
    rebalance_dates: Optional[Sequence] = None,
) -> PerformanceMetrics:
    """从净值序列计算全套绩效指标 — 全系统唯一实现.

    Parameters
    ----------
    nav : pd.Series
        净值序列（DatetimeIndex → 净值/组合总市值）。起点值任意，内部按比值计算。
    risk_free_rate : float
        年化无风险利率，用于夏普比率。
    periods_per_year : int
        年化因子。除非有明确理由（如周频净值），保持默认 260。
    rebalance_dates : sequence, optional
        调仓日列表，用于计算调仓周期胜率。不提供则胜率为 0。

    Returns
    -------
    PerformanceMetrics
        指标 + `warnings`（数据质量问题清单）。任何情况下都返回对象，不抛异常。
    """
    metrics = PerformanceMetrics(
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )

    series, warnings = clean_nav_series(nav)
    metrics.warnings = warnings

    if series.empty or len(series) < MIN_NAV_POINTS:
        metrics.warnings.append(
            f"净值点数不足（{len(series)} < {MIN_NAV_POINTS}），无法计算绩效指标"
        )
        return metrics

    start_value = _to_float(series.iloc[0])
    end_value = _to_float(series.iloc[-1])
    if start_value <= 1e-12:
        metrics.warnings.append("期初净值为 0 或负数，无法计算收益率")
        return metrics

    # --- 收益 ---
    metrics.total_return = _to_float(end_value / start_value - 1.0)

    returns = series.pct_change(fill_method=None)
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    metrics.n_periods = len(returns)

    if metrics.n_periods == 0:
        metrics.warnings.append("有效日收益序列为空，无法计算年化指标")
        return metrics

    if metrics.total_return > -1.0:
        metrics.annual_return = _to_float(
            (1.0 + metrics.total_return) ** (periods_per_year / metrics.n_periods) - 1.0
        )
    else:
        metrics.annual_return = -1.0
        metrics.warnings.append("期末净值归零，年化收益按 -100% 处理")

    # --- 波动 ---
    metrics.volatility = _to_float(returns.std())
    metrics.annual_volatility = _to_float(
        metrics.volatility * math.sqrt(periods_per_year)
    )

    # --- 回撤（与 compute_drawdown_series 同源）---
    metrics.max_drawdown = _to_float(compute_drawdown_series(series).min())

    # --- 比率 ---
    if metrics.annual_volatility > 1e-12:
        metrics.sharpe_ratio = _to_float(
            (metrics.annual_return - risk_free_rate) / metrics.annual_volatility
        )
    if metrics.max_drawdown < -1e-12:
        abs_dd = abs(metrics.max_drawdown)
        metrics.calmar_ratio = _to_float(metrics.annual_return / abs_dd)
        metrics.return_drawdown_ratio = _to_float(metrics.total_return / abs_dd)

    # --- 胜率 ---
    metrics.win_rate = _win_rate_from_rebalance(series, rebalance_dates)

    return metrics


def annualize_return(total_return: float, n_periods: int,
                     periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """CAGR 年化 — 供只有区间收益、没有完整净值序列的场景复用。"""
    if n_periods <= 0 or total_return <= -1.0:
        return 0.0
    return _to_float((1.0 + total_return) ** (periods_per_year / n_periods) - 1.0)


def annualize_volatility(returns: pd.Series,
                         periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """日收益序列 → 年化波动率。"""
    if returns is None or len(returns) < 2:
        return 0.0
    return _to_float(float(returns.std()) * math.sqrt(periods_per_year))


def collect_warnings(*groups: Iterable[str]) -> List[str]:
    """合并多组告警并去重（保持首次出现顺序）。"""
    seen: dict[str, None] = {}
    for group in groups:
        for item in group or []:
            if item not in seen:
                seen[item] = None
    return list(seen.keys())
