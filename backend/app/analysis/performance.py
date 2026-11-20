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
- 双口径：同一套输入同时给出 260（交易日）与 365（自然日）两个年化基准。原字段
  （`annual_return` / `annual_volatility` / `sharpe_ratio` / `calmar_ratio`）固定为
  260 口径，365 口径统一加 `_365` 后缀；累计收益、最大回撤、胜率不依赖年化因子，
  只给一份。
- 365 口径的分母是**日历天数** `n_calendar_days`（首末净值日期之差），不是交易日
  区间数 `n_periods`：
  年化收益 `(1 + total_return) ** (365 / n_calendar_days) - 1`；
  年化波动 `daily_std * sqrt(365 * n_periods / n_calendar_days)`，即把交易日收益
  视作均布在日历日上，换算成每日历日波动率后再按 365 天年化。
  若区间内交易日密度恰为 260/365，两项与 260 口径完全相等；实际差异只反映区间内
  交易日分布与「260 交易日/年」假设的偏差（通常在 0.0x 个百分点量级）。
  把 365 口径的分母仍写成 `n_periods` 等于把交易日日均当作日历日日均，年化值会
  被放大 365/260 倍（约 1.40 倍），波动率被放大 sqrt(365/260) 倍。
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

#: 次级年化因子（自然日/年）。与 260 口径并存，仅用于 `_365` 后缀字段；
#: 主字段语义不变，接入方按需读取。分母是日历天数，见 `calendar_span_days`。
PERIODS_PER_YEAR_365 = 365

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

    # 365 口径（自然日/年）：同一份 total_return / 日收益标准差只换年化因子；
    # 累计收益、最大回撤、胜率不依赖年化因子，不在此复制
    annual_return_365: float = 0.0
    annual_volatility_365: float = 0.0
    sharpe_ratio_365: float = 0.0
    calmar_ratio_365: float = 0.0

    # 交易统计
    win_rate: float = 0.0

    # 计算元信息
    n_periods: int = 0                 # 参与年化的区间数（= len(nav) - 1）
    n_calendar_days: int = 0           # 365 口径的分母：首末净值日期的日历天数差
    periods_per_year: int = PERIODS_PER_YEAR
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE

    # 数据质量告警
    warnings: List[str] = field(default_factory=list)


def calendar_span_days(index: pd.Index) -> Optional[int]:
    """首末日期之间的日历天数 — 365 自然日口径的分母.

    交易日频率的序列不能用交易日区间数做自然日年化的分母：那等于把「交易日
    日均」当成「日历日日均」，年化值被放大 365/260 倍（约 1.40 倍）。

    索引不是 DatetimeIndex 时抛 TypeError（调用方用错了入口，退回去会产出
    一个看起来正常的错误年化值）；首末未跨日属数据异常，返回 None 由调用方
    记入 warnings。
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError(
            f"自然日口径要求 DatetimeIndex，实际为 {type(index).__name__}；"
            "无法从非日期索引换算日历天数"
        )
    if len(index) < 2:
        return None
    span = int((index.max() - index.min()).days)
    return span if span > 0 else None


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

    # --- 365 口径（自然日/年）---
    # 分母是首末净值日期之间的日历天数，不是交易日区间数 n_periods：沿用
    # n_periods 等于把交易日日均当成日历日日均，年化值被放大 365/260 倍。
    # 日波动率按「交易日收益均布在日历日上」换算，即先换成每日历日波动率再乘 √365；
    # 当 n_calendar_days = n_periods × 365/260 时退化为 σ_d × √260，与主口径相同。
    span = calendar_span_days(series.index)
    if span is None:
        metrics.warnings.append(
            f"净值首末日期未跨日（{series.index.min()} → {series.index.max()}），"
            "无法计算自然日年化，365 口径字段保持 0"
        )
    else:
        metrics.n_calendar_days = span
        if metrics.total_return > -1.0:
            metrics.annual_return_365 = _to_float(
                (1.0 + metrics.total_return)
                ** (PERIODS_PER_YEAR_365 / span)
                - 1.0
            )
        else:
            metrics.annual_return_365 = -1.0
        metrics.annual_volatility_365 = _to_float(
            metrics.volatility
            * math.sqrt(PERIODS_PER_YEAR_365 * metrics.n_periods / span)
        )
    if metrics.annual_volatility_365 > 1e-12:
        metrics.sharpe_ratio_365 = _to_float(
            (metrics.annual_return_365 - risk_free_rate) / metrics.annual_volatility_365
        )
    if metrics.max_drawdown < -1e-12:
        metrics.calmar_ratio_365 = _to_float(
            metrics.annual_return_365 / abs(metrics.max_drawdown)
        )

    # --- 胜率 ---
    metrics.win_rate = _win_rate_from_rebalance(series, rebalance_dates)

    return metrics


def annualize_return(total_return: float, n_periods: int,
                     periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """CAGR 年化 — 供只有区间收益、没有完整净值序列的场景复用.

    `periods_per_year` 与 `n_periods` 必须是同一时间尺度：交易日序列传 260，
    日历日序列传 365。交易日序列配 365 会把年化值放大 365/260 倍，
    自然日年化请先用 `calendar_span_days` 取日历天数再传进来。
    """
    if n_periods <= 0 or total_return <= -1.0:
        return 0.0
    return _to_float((1.0 + total_return) ** (periods_per_year / n_periods) - 1.0)


def annualize_volatility(returns: pd.Series,
                         periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """日收益序列 → 年化波动率.

    `periods_per_year` 是「每年的收益观测数」。收益观测是交易日时只有 260
    这一个正确值；自然日口径要把收益换算到日历日尺度（σ × √(n_td / n_cal)）
    再按 365 天年化，不能直接传 365。
    """
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
