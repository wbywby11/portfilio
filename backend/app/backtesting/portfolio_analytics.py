"""组合绩效分析 — 子策略分解、收益归因、相关性与组合级报告.

绩效口径统一由 `app.analysis.performance` 提供（年化因子 252、CAGR 年化、
回撤基于净值本身、夏普为几何口径、无风险利率可注入），本模块不重复实现指标公式。

归因口径（对外承诺）
--------------------
NAV 级复合组合的收益贡献采用**逐日权重 × 逐日子策略收益、按组合累计净值几何链接**：

    contribution_k = Σ_t  c_{k,t} · NAV_{t-1} / NAV_0
    其中 c_{k,t} = w_{k,t}^eff · r_{k,t}

`w_{k,t}^eff` 为组合引擎当日**实际生效**的权重（已含执行延迟与母层杠杆），
由 `PortfolioBacktestResult.sub_contributions` 直接给出。该口径满足可加性：

    Σ_k contribution_k + residual = 组合区间总收益

`residual` 为引擎内无法归属到子策略的部分（正常应约等于 0），如实上报而不掩盖。

配置效应以「等权买入持有」为基准：

    allocation_effect_k = contribution_k − contribution_k^{等权买入持有}
    Σ_k allocation_effect_k = 组合总收益 − 等权基准总收益

历史实现曾用「简化 Brinson」以组合自身作基准计算 allocation/timing，
数学上不可加、且「择时」项并无时间维度（只是权重 × 相对收益），已移除。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.analysis.performance import (
    DEFAULT_RISK_FREE_RATE,
    PERIODS_PER_YEAR,
    compute_performance,
)

logger = logging.getLogger(__name__)

#: 归因/相关性分析所需的最小有效样本数
MIN_SAMPLES = 10


# ======================================================================
#  数据结构
# ======================================================================

@dataclass
class SubStrategyDecomposition:
    """子策略收益分解结果"""
    sub_name: str
    weight: float                          # 目标配置权重
    sub_nav: Optional[pd.Series] = None    # 子策略净值序列
    avg_weight: float = 0.0                # 区间实际平均权重
    contribution: float = 0.0              # 对组合总收益的贡献（可加）
    contribution_pct: float = 0.0          # 贡献占组合总收益比例
    annual_return: float = 0.0             # 子策略年化收益
    annual_vol: float = 0.0                # 子策略年化波动
    sharpe: float = 0.0                    # 子策略夏普比率
    max_drawdown: float = 0.0              # 子策略最大回撤


@dataclass
class CorrelationDrag:
    """子策略间相关性对组合分散化效果的影响"""
    correlation_matrix: Optional[pd.DataFrame] = None
    avg_correlation: float = 0.0           # 平均相关系数
    diversification_ratio: float = 1.0     # 分散化比率 = 组合波动 / 加权子策略波动
    correlation_drag: float = 0.0          # 相关性拖累 = 加权波动 - 组合波动


@dataclass
class AttributionResult:
    """收益归因结果（可加性闭合）"""
    #: {子策略: {contribution, contribution_pct, allocation_effect, avg_weight, sub_return}}
    by_sub: Dict[str, Dict[str, float]] = field(default_factory=dict)
    total_return: float = 0.0              # 组合区间总收益
    explained: float = 0.0                 # Σ contribution
    residual: float = 0.0                  # total_return − explained
    benchmark_return: float = 0.0          # 等权买入持有基准的区间收益
    #: 贡献来源：exact（引擎逐日贡献）/ from_weight_history / static_weight_approx
    method: str = "exact"
    warnings: List[str] = field(default_factory=list)


@dataclass
class PortfolioReport:
    """完整组合评估报告"""
    # 基础绩效
    annual_return: float = 0.0
    annual_vol: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    calmar: float = 0.0
    total_return: float = 0.0

    # 相对基准指标
    tracking_error: Optional[float] = None
    information_ratio: Optional[float] = None
    beta: Optional[float] = None
    alpha: Optional[float] = None

    # 子策略分解
    sub_strategy_decomposition: List[SubStrategyDecomposition] = field(default_factory=list)
    correlation_analysis: Optional[CorrelationDrag] = None


# ======================================================================
#  逐日贡献与几何链接
# ======================================================================

def _daily_returns_frame(sub_navs: Dict[str, pd.Series]) -> pd.DataFrame:
    """子策略净值字典 → 共同日期上的日收益率矩阵（首日为 0）。"""
    valid = {
        name: pd.to_numeric(nav, errors="coerce")
        for name, nav in (sub_navs or {}).items()
        if nav is not None and len(nav) >= 2
    }
    if not valid:
        return pd.DataFrame()
    nav_df = pd.DataFrame(valid).sort_index().ffill()
    return nav_df.pct_change(fill_method=None).fillna(0.0)


def link_contributions(
    daily_contributions: pd.DataFrame,
    portfolio_nav: pd.Series,
) -> Dict[str, float]:
    """逐日贡献 → 区间贡献（按组合累计净值几何链接）.

    contribution_k = Σ_t c_{k,t} · NAV_{t-1} / NAV_0

    该链接方式使 Σ_k contribution_k 恰好等于组合区间总收益
    （前提是 Σ_k c_{k,t} 等于组合当日收益率）。
    """
    if daily_contributions is None or daily_contributions.empty:
        return {}
    if portfolio_nav is None or portfolio_nav.empty:
        return {}

    idx = daily_contributions.index.intersection(portfolio_nav.index)
    if len(idx) < 2:
        return {}

    contrib = daily_contributions.loc[idx].fillna(0.0)
    nav = pd.to_numeric(portfolio_nav.loc[idx], errors="coerce").ffill()
    base = float(nav.iloc[0])
    if not np.isfinite(base) or base <= 1e-12:
        return {}

    # NAV_{t-1}/NAV_0，首日的「前一日」即期初，比值为 1
    prev_ratio = (nav.shift(1) / base).fillna(1.0)
    linked = contrib.mul(prev_ratio, axis=0).sum(axis=0)
    return {str(k): float(v) for k, v in linked.items()}


def _buy_and_hold_contributions(
    returns_df: pd.DataFrame,
    init_weights: Dict[str, float],
) -> tuple[Dict[str, float], float]:
    """给定期初权重的买入持有组合：逐日贡献几何链接 → (各成分贡献, 组合总收益).

    权重随子策略净值自然漂移，期间不再平衡。用于构造归因基准。
    """
    if returns_df is None or returns_df.empty:
        return {}, 0.0

    names = [c for c in returns_df.columns if init_weights.get(c, 0.0) > 0]
    if not names:
        return {}, 0.0

    total_w = sum(init_weights[n] for n in names)
    if total_w <= 0:
        return {}, 0.0

    # 各成分的资本占比随净值漂移：value_{k,t} = w_k · Π(1+r_{k,s})
    growth = (1.0 + returns_df[names]).cumprod()
    values = growth.mul(pd.Series({n: init_weights[n] / total_w for n in names}), axis=1)
    port_value = values.sum(axis=1)

    prev_values = values.shift(1)
    prev_values.iloc[0] = pd.Series({n: init_weights[n] / total_w for n in names})
    # 贡献（相对期初资本 1）= 上一日资本占比 × 当日收益
    contrib = prev_values * returns_df[names]
    linked = {str(n): float(contrib[n].sum()) for n in names}
    total_return = float(port_value.iloc[-1] - 1.0)
    return linked, total_return


# ======================================================================
#  子策略收益分解
# ======================================================================

def decompose_sub_strategy_returns(
    composite_nav: pd.Series,
    sub_navs: Dict[str, pd.Series],
    weights: Dict[str, float],
    sub_contributions: Optional[pd.DataFrame] = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> List[SubStrategyDecomposition]:
    """将组合收益分解到各子策略。

    Parameters
    ----------
    composite_nav : pd.Series
        组合净值序列（DatetimeIndex）
    sub_navs : dict
        {子策略名: 子策略净值序列}
    weights : dict
        {子策略名: 目标配置权重}
    sub_contributions : pd.DataFrame, optional
        引擎输出的逐日贡献矩阵（index=日期, columns=子策略），
        由 `PortfolioBacktestResult.sub_contributions` 提供。
        提供时贡献为精确可加值；缺省时退化为「期初权重买入持有」近似。
    risk_free_rate : float
        计算子策略夏普用的年化无风险利率。

    Returns
    -------
    list[SubStrategyDecomposition]
    """
    if composite_nav is None or composite_nav.empty or not sub_navs:
        return []

    total_return = float(composite_nav.iloc[-1] / composite_nav.iloc[0] - 1)

    returns_df = _daily_returns_frame(sub_navs)
    if sub_contributions is not None and not sub_contributions.empty:
        contrib_map = link_contributions(sub_contributions, composite_nav)
        avg_weights = _avg_effective_weights(sub_contributions, returns_df)
    else:
        contrib_map, _ = _buy_and_hold_contributions(returns_df, weights or {})
        avg_weights = {}

    decompositions: List[SubStrategyDecomposition] = []
    for name, nav in sub_navs.items():
        w = float(weights.get(name, 0.0)) if weights else 0.0
        if nav is None or nav.empty:
            decompositions.append(SubStrategyDecomposition(
                sub_name=name, weight=w, sub_nav=nav,
            ))
            continue

        common_idx = composite_nav.index.intersection(nav.index)
        if len(common_idx) < 5:
            decompositions.append(SubStrategyDecomposition(
                sub_name=name, weight=w, sub_nav=nav,
            ))
            continue

        sub_aligned = nav.loc[common_idx]
        metrics = compute_performance(sub_aligned, risk_free_rate=risk_free_rate)

        contribution = float(contrib_map.get(name, 0.0))
        contribution_pct = (
            contribution / abs(total_return) if abs(total_return) > 1e-8 else 0.0
        )

        decompositions.append(SubStrategyDecomposition(
            sub_name=name,
            weight=w,
            sub_nav=sub_aligned,
            avg_weight=round(float(avg_weights.get(name, w)), 6),
            contribution=round(contribution, 6),
            contribution_pct=round(contribution_pct, 4),
            annual_return=round(metrics.annual_return, 6),
            annual_vol=round(metrics.annual_volatility, 6),
            sharpe=round(metrics.sharpe_ratio, 4),
            max_drawdown=round(metrics.max_drawdown, 6),
        ))

    return decompositions


def _avg_effective_weights(
    sub_contributions: pd.DataFrame,
    returns_df: pd.DataFrame,
) -> Dict[str, float]:
    """由逐日贡献反推区间平均生效权重：w_{k,t} = c_{k,t} / r_{k,t}（仅取 r≠0 的日子）。"""
    if sub_contributions is None or sub_contributions.empty or returns_df.empty:
        return {}
    out: Dict[str, float] = {}
    idx = sub_contributions.index.intersection(returns_df.index)
    for name in sub_contributions.columns:
        if name not in returns_df.columns:
            continue
        r = returns_df.loc[idx, name]
        c = sub_contributions.loc[idx, name]
        mask = r.abs() > 1e-12
        if not mask.any():
            continue
        out[str(name)] = float((c[mask] / r[mask]).mean())
    return out


# ======================================================================
#  子策略归因
# ======================================================================

def compute_sub_strategy_attribution(
    sub_navs: Dict[str, pd.Series],
    composite_nav: pd.Series,
    weights: Dict[str, float],
    sub_contributions: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """子策略收益归因（可加性闭合）。

    Parameters
    ----------
    sub_navs : dict
        {子策略名: 子策略净值序列}
    composite_nav : pd.Series
        组合净值序列
    weights : dict
        {子策略名: 目标配置权重}
    sub_contributions : pd.DataFrame, optional
        引擎输出的逐日贡献矩阵。提供时贡献精确可加；
        缺省时退化为「期初权重买入持有」近似，并在 warnings 中说明。

    Returns
    -------
    dict
        与 `AttributionResult` 同构的可 JSON 化字典：
        `{by_sub: {...}, total_return, explained, residual, benchmark_return, method, warnings}`
    """
    result = AttributionResult()
    if composite_nav is None or composite_nav.empty or not sub_navs:
        result.warnings.append("组合净值或子策略净值缺失，无法归因")
        return _attribution_to_dict(result)

    result.total_return = float(composite_nav.iloc[-1] / composite_nav.iloc[0] - 1)

    returns_df = _daily_returns_frame(sub_navs)
    if returns_df.empty or len(returns_df) < MIN_SAMPLES:
        result.warnings.append("子策略收益样本不足，无法归因")
        return _attribution_to_dict(result)

    if sub_contributions is not None and not sub_contributions.empty:
        contrib_map = link_contributions(sub_contributions, composite_nav)
        avg_weights = _avg_effective_weights(sub_contributions, returns_df)
        result.method = "exact"
    else:
        contrib_map, _ = _buy_and_hold_contributions(returns_df, weights or {})
        avg_weights = {}
        result.method = "static_weight_approx"
        result.warnings.append(
            "未提供引擎逐日贡献，贡献按「期初权重买入持有」近似计算，"
            "动态权重模型下会与实际贡献存在偏差（见 residual）"
        )

    # 等权买入持有基准
    eq_names = list(returns_df.columns)
    eq_weights = {n: 1.0 / len(eq_names) for n in eq_names}
    bench_contrib, bench_return = _buy_and_hold_contributions(returns_df, eq_weights)
    result.benchmark_return = round(bench_return, 6)

    for name in sub_navs.keys():
        contribution = float(contrib_map.get(name, 0.0))
        sub_ret = 0.0
        nav = sub_navs.get(name)
        if nav is not None and len(nav) >= 2 and float(nav.iloc[0]) > 1e-12:
            sub_ret = float(nav.iloc[-1] / nav.iloc[0] - 1)
        w = float(weights.get(name, 0.0)) if weights else 0.0
        result.by_sub[name] = {
            "contribution": round(contribution, 6),
            "contribution_pct": round(
                contribution / abs(result.total_return)
                if abs(result.total_return) > 1e-8 else 0.0, 4
            ),
            "allocation_effect": round(
                contribution - float(bench_contrib.get(name, 0.0)), 6
            ),
            "avg_weight": round(float(avg_weights.get(name, w)), 4),
            "weight": round(w, 4),
            "sub_return": round(sub_ret, 6),
        }

    result.explained = round(sum(contrib_map.values()), 6)
    result.residual = round(result.total_return - result.explained, 6)
    if abs(result.residual) > max(0.005, abs(result.total_return) * 0.02):
        result.warnings.append(
            f"归因残差 {result.residual:.2%} 偏大，组合收益中存在无法归属到子策略的部分"
            f"（母层波动率杠杆等引擎内操作）"
        )
    result.total_return = round(result.total_return, 6)
    return _attribution_to_dict(result)


def _attribution_to_dict(result: AttributionResult) -> Dict[str, Any]:
    return {
        "by_sub": result.by_sub,
        "total_return": result.total_return,
        "explained": result.explained,
        "residual": result.residual,
        "benchmark_return": result.benchmark_return,
        "benchmark": "equal_weight_buy_and_hold",
        "method": result.method,
        "warnings": result.warnings,
    }


# ======================================================================
#  相关性分析
# ======================================================================

def compute_correlation_drag(
    sub_navs: Dict[str, pd.Series],
    weights: Dict[str, float],
) -> CorrelationDrag:
    """分析子策略间相关性对组合分散化效果的影响。

    Returns
    -------
    CorrelationDrag:
        - correlation_matrix: 子策略间相关系数矩阵
        - avg_correlation: 平均相关系数
        - diversification_ratio: 分散化比率 = 组合波动 / 加权子策略波动
        - correlation_drag: 相关性拖累 = 加权波动 - 组合波动
    """
    if len(sub_navs or {}) < 2:
        return CorrelationDrag()

    returns_dict = {
        name: nav.pct_change(fill_method=None).dropna()
        for name, nav in sub_navs.items()
        if nav is not None and not nav.empty and len(nav) > 5
    }
    if len(returns_dict) < 2:
        return CorrelationDrag()

    ret_df = pd.DataFrame(returns_dict).dropna()
    if len(ret_df) < MIN_SAMPLES:
        return CorrelationDrag()

    corr_matrix = ret_df.corr()
    n = len(corr_matrix)

    # 平均相关系数（排除对角线）
    mask = ~np.eye(n, dtype=bool)
    avg_corr = float(corr_matrix.values[mask].mean()) if mask.any() else 0.0

    names = list(returns_dict.keys())
    vols = {name: float(ret_df[name].std() * np.sqrt(PERIODS_PER_YEAR)) for name in names}
    total_weight = sum(weights.get(name, 0.0) for name in names)
    if total_weight <= 0:
        return CorrelationDrag(
            correlation_matrix=corr_matrix,
            avg_correlation=round(avg_corr, 4),
        )

    w_norm = {name: weights.get(name, 0.0) / total_weight for name in names}
    weighted_vol = sum(w_norm[name] * vols[name] for name in names)

    w_array = np.array([w_norm[name] for name in names])
    cov_matrix = ret_df.cov().values * PERIODS_PER_YEAR
    portfolio_var = float(w_array @ cov_matrix @ w_array)
    portfolio_vol = float(np.sqrt(max(portfolio_var, 0.0)))

    div_ratio = portfolio_vol / weighted_vol if weighted_vol > 0 else 1.0
    corr_drag = weighted_vol - portfolio_vol

    return CorrelationDrag(
        correlation_matrix=corr_matrix,
        avg_correlation=round(avg_corr, 4),
        diversification_ratio=round(div_ratio, 4),
        correlation_drag=round(corr_drag, 6),
    )


# ======================================================================
#  相对基准指标
# ======================================================================

def _aligned_active_returns(
    portfolio_nav: pd.Series,
    benchmark_nav: pd.Series,
    min_samples: int = MIN_SAMPLES,
) -> Optional[tuple[pd.Series, pd.Series]]:
    """对齐组合与基准的日收益序列，样本不足返回 None。"""
    if portfolio_nav is None or benchmark_nav is None:
        return None
    if portfolio_nav.empty or benchmark_nav.empty:
        return None

    common_idx = portfolio_nav.index.intersection(benchmark_nav.index)
    if len(common_idx) < min_samples:
        return None

    p_ret = portfolio_nav.loc[common_idx].pct_change(fill_method=None).dropna()
    b_ret = benchmark_nav.loc[common_idx].pct_change(fill_method=None).dropna()
    idx = p_ret.index.intersection(b_ret.index)
    if len(idx) < min_samples:
        return None
    return p_ret.loc[idx], b_ret.loc[idx]


def compute_tracking_error(
    portfolio_nav: pd.Series,
    benchmark_nav: pd.Series,
) -> float:
    """跟踪误差（年化）= std(组合日收益 − 基准日收益) × √252。"""
    pair = _aligned_active_returns(portfolio_nav, benchmark_nav)
    if pair is None:
        return 0.0
    p_ret, b_ret = pair
    return float((p_ret - b_ret).std() * np.sqrt(PERIODS_PER_YEAR))


def compute_information_ratio(
    portfolio_nav: pd.Series,
    benchmark_nav: pd.Series,
) -> float:
    """信息比率 = (组合年化 − 基准年化) / 跟踪误差。年化口径同统一内核。"""
    te = compute_tracking_error(portfolio_nav, benchmark_nav)
    if te < 1e-8:
        return 0.0

    common_idx = portfolio_nav.index.intersection(benchmark_nav.index)
    if len(common_idx) < MIN_SAMPLES:
        return 0.0

    p_annual = compute_performance(portfolio_nav.loc[common_idx]).annual_return
    b_annual = compute_performance(benchmark_nav.loc[common_idx]).annual_return
    return float((p_annual - b_annual) / te)


def compute_beta_alpha(
    portfolio_nav: pd.Series,
    benchmark_nav: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> Dict[str, float]:
    """Beta / Alpha（CAPM）。

    Beta = Cov(Rp, Rm) / Var(Rm)
    Alpha = Rp_annual − [Rf + Beta × (Rm_annual − Rf)]
    """
    empty = {"beta": 0.0, "alpha": 0.0, "r_squared": 0.0}
    pair = _aligned_active_returns(portfolio_nav, benchmark_nav, min_samples=20)
    if pair is None:
        return empty
    p, m = pair

    var_m = float(np.var(m.values, ddof=1))
    beta = float(np.cov(p.values, m.values)[0, 1]) / var_m if var_m > 0 else 0.0

    common_idx = portfolio_nav.index.intersection(benchmark_nav.index)
    p_annual = compute_performance(
        portfolio_nav.loc[common_idx], risk_free_rate=risk_free_rate
    ).annual_return
    m_annual = compute_performance(
        benchmark_nav.loc[common_idx], risk_free_rate=risk_free_rate
    ).annual_return
    alpha = p_annual - (risk_free_rate + beta * (m_annual - risk_free_rate))

    corr = float(p.corr(m))
    r_squared = corr ** 2 if np.isfinite(corr) else 0.0

    return {
        "beta": round(beta, 4),
        "alpha": round(alpha, 6),
        "r_squared": round(r_squared, 4),
    }


# ======================================================================
#  组合级评估报告
# ======================================================================

def compute_portfolio_report(
    portfolio_nav: pd.Series,
    benchmark_nav: Optional[pd.Series] = None,
    sub_navs: Optional[Dict[str, pd.Series]] = None,
    weights: Optional[Dict[str, float]] = None,
    sub_contributions: Optional[pd.DataFrame] = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> Dict[str, Any]:
    """生成完整的组合评估报告。

    基础绩效直接取自统一内核 `app.analysis.performance.compute_performance`，
    与单策略回测、组合回测使用完全一致的口径。
    """
    report: Dict[str, Any] = {}

    if portfolio_nav is not None and not portfolio_nav.empty:
        metrics = compute_performance(portfolio_nav, risk_free_rate=risk_free_rate)
        report.update({
            "annual_return": round(metrics.annual_return, 6),
            "annual_vol": round(metrics.annual_volatility, 6),
            "sharpe": round(metrics.sharpe_ratio, 4),
            "max_drawdown": round(metrics.max_drawdown, 6),
            "calmar": round(metrics.calmar_ratio, 4),
            "total_return": round(metrics.total_return, 6),
            "risk_free_rate": risk_free_rate,
            "periods_per_year": metrics.periods_per_year,
        })
        if metrics.warnings:
            report["warnings"] = list(metrics.warnings)

    if benchmark_nav is not None and not benchmark_nav.empty:
        report["tracking_error"] = round(compute_tracking_error(portfolio_nav, benchmark_nav), 6)
        report["information_ratio"] = round(compute_information_ratio(portfolio_nav, benchmark_nav), 4)
        ba = compute_beta_alpha(portfolio_nav, benchmark_nav, risk_free_rate=risk_free_rate)
        report["beta"] = ba["beta"]
        report["alpha"] = ba["alpha"]
        report["r_squared"] = ba["r_squared"]

    if sub_navs and weights:
        decomps = decompose_sub_strategy_returns(
            portfolio_nav, sub_navs, weights,
            sub_contributions=sub_contributions,
            risk_free_rate=risk_free_rate,
        )
        report["sub_strategy_decomposition"] = [
            {
                "sub_name": d.sub_name,
                "weight": d.weight,
                "avg_weight": d.avg_weight,
                "contribution": d.contribution,
                "contribution_pct": d.contribution_pct,
                "annual_return": d.annual_return,
                "annual_vol": d.annual_vol,
                "sharpe": d.sharpe,
                "max_drawdown": d.max_drawdown,
            }
            for d in decomps
        ]

        corr = compute_correlation_drag(sub_navs, weights)
        report["correlation_analysis"] = {
            "avg_correlation": corr.avg_correlation,
            "diversification_ratio": corr.diversification_ratio,
            "correlation_drag": corr.correlation_drag,
        }
        if corr.correlation_matrix is not None:
            report["correlation_analysis"]["correlation_matrix"] = corr.correlation_matrix.to_dict()

        report["attribution"] = compute_sub_strategy_attribution(
            sub_navs, portfolio_nav, weights, sub_contributions=sub_contributions,
        )

    return report


# ======================================================================
#  穿透分析
# ======================================================================

def compute_lookthrough_weights(
    sub_snapshots_by_key: Dict[str, list],
    weight_history: pd.DataFrame,
    rebalance_dates: list,
) -> Dict[str, Dict[str, float]]:
    """穿透分析：计算资产级持仓权重。

    对于每个调仓日，将组合级策略权重与子策略内部资产权重相乘后求和，
    得到组合穿透后的真实资产持仓权重。

    Parameters
    ----------
    sub_snapshots_by_key : Dict[str, list]
        各子策略的 PortfolioSnapshot 列表，key 为 sub_model_id
    weight_history : DataFrame
        组合引擎输出的策略级权重历史 (DatetimeIndex × sub_model_id)
    rebalance_dates : list
        调仓日列表（pd.Timestamp 或类似类型）

    Returns
    -------
    Dict[str, Dict[str, float]]
        {date_str: {thscode: lookthrough_weight}}
    """
    if not sub_snapshots_by_key or weight_history is None or weight_history.empty:
        return {}
    if not rebalance_dates:
        return {}

    # 为每个子策略构建 {date_str: {thscode: weight}} 映射
    sub_asset_weights_by_key: Dict[str, Dict[str, Dict[str, float]]] = {}
    for key, snapshots in sub_snapshots_by_key.items():
        date_to_weights: Dict[str, Dict[str, float]] = {}
        for snap in snapshots:
            snap_date_str = snap.time.strftime("%Y-%m-%d") if hasattr(snap.time, "strftime") else str(snap.time)
            if snap.weights:
                date_to_weights[snap_date_str] = {k: float(v) for k, v in snap.weights.items() if v != 0}
        sub_asset_weights_by_key[key] = date_to_weights

    result: Dict[str, Dict[str, float]] = {}
    for rebal_date in rebalance_dates:
        date_str = rebal_date.strftime("%Y-%m-%d") if hasattr(rebal_date, "strftime") else str(rebal_date)
        # 获取该日策略级权重
        if rebal_date not in weight_history.index:
            continue
        w_row = weight_history.loc[rebal_date]
        strategy_weights = {k: float(v) for k, v in w_row.items()}

        # 穿透计算：组合资产权重 = Σ(策略权重 × 子策略内资产权重)
        asset_weights: Dict[str, float] = {}
        for strat_key, strat_w in strategy_weights.items():
            if strat_w <= 0:
                continue
            sub_date_weights = sub_asset_weights_by_key.get(strat_key, {})
            # 优先精确匹配，否则向前查找最近日期
            sub_weights = sub_date_weights.get(date_str)
            if sub_weights is None:
                # 向前查找最近的资产权重（最多回溯 5 个自然日）
                for offset in range(1, 6):
                    lookup = (rebal_date - pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
                    if lookup in sub_date_weights:
                        sub_weights = sub_date_weights[lookup]
                        break
            if not sub_weights:
                continue
            for asset_code, asset_w in sub_weights.items():
                asset_weights[asset_code] = asset_weights.get(asset_code, 0.0) + strat_w * asset_w

        if asset_weights:
            result[date_str] = {k: round(v, 6) for k, v in asset_weights.items()}

    return result
