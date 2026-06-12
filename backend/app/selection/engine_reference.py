# -*- coding: utf-8 -*-
"""
大类资产配置指数 - 核心计算引擎

资产选择委托同域 advanced_momentum_factors；
权重计算使用本地实现（6 步流程）。
保留外部接口不变：select_assets_for_date / calc_weights_for_date。
"""
from __future__ import annotations

import warnings

import numpy as np

try:
    from loguru import logger as _log
except ImportError:
    import logging
    _log = logging.getLogger(__name__)
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple

# 抑制 rolling 全 NaN 窗口的 RuntimeWarning（结果为 NaN，行为正确）
warnings.filterwarnings("ignore", message="All-NaN slice encountered", category=RuntimeWarning)

# ---- 同域因子计算 ----
from app.selection.formula.advanced_momentum_factors import (
    select_momentum_and_reversal_assets,
)

# =============================================================================
# 算法常量（取自原 quant_core/config.py）
# =============================================================================
VOL_WINDOWS: List[int] = [22, 65, 130]       # 波动率计算窗口(交易日)
ANNUALIZE_FACTOR: int = 260                   # 年化因子（260交易日/年）
TARGET_VOL: float = 0.05                      # 目标波动率 5%
MAX_LEVERAGE: float = 4.0                     # 杠杆上限
RISK_BUDGET_BOTH: float = 2 / 8              # 动量+反转同时入选
RISK_BUDGET_SINGLE: float = 1 / 8            # 仅动量或仅反转入选
DEFAULT_WEIGHT_CAP: float = 0.1              # 默认单资产权重上限


# =============================================================================
# 第一部分：资产选择（委托 advanced_momentum_factors）
# =============================================================================


def select_assets_for_date(
    nav: pd.DataFrame,
    date_idx: int,
    calc_date: pd.Timestamp,
    min_history: int = 260,
    top_momentum: int = 7,
) -> Dict[str, Any]:
    """
    单次调仓的资产选择。
    内部委托 advanced_momentum_factors.select_momentum_and_reversal_assets，
    并将结果转换为原始中文键格式。
    """
    result: Dict[str, Any] = {
        "计算日期": calc_date,
        "有效资产": [],
        "动量详情": None,
        "动量排名": None,
        "动量入选": [],
        "反转详情": None,
        "反转排名": None,
        "反转入选": [],
        "最终入选": [],
        "入选矩阵_row": {},
    }

    # ------------------------------------------------------------------
    # 有效资产筛选（保留详细日志的业务逻辑）
    # ------------------------------------------------------------------
    valid_assets: List[str] = []
    asset_days: Dict[str, int] = {}
    for col in nav.columns:
        asset_data = nav[col].iloc[: date_idx + 1]
        n = asset_data.notna().sum()
        asset_days[col] = int(n)
        if n >= min_history:
            valid_assets.append(col)
        else:
            n_total = len(asset_data)
            if n_total < min_history:
                first_valid = asset_data.dropna()
                first_valid_date = first_valid.index[0] if len(first_valid) > 0 else None
                global_start = asset_data.index[0] if n_total > 0 else None
                global_end = asset_data.index[-1] if n_total > 0 else None
                first_valid_str = first_valid_date.strftime("%Y-%m-%d") if first_valid_date is not None else "无"
                global_start_str = global_start.strftime("%Y-%m-%d") if global_start is not None else "N/A"
                global_end_str = global_end.strftime("%Y-%m-%d") if global_end is not None else "N/A"
                _log.warning(
                    f"[资产选择] {col} 历史不足{min_history}天: 本资产有效{int(n)}天(首有效日{first_valid_str}), "
                    f"整体数据范围 {global_start_str}~{global_end_str} 共{n_total}行 (需{min_history})。"
                    f"若沪深300等应有更早数据，请检查回测lookback_days或数据库历史覆盖"
                )
            else:
                window = asset_data.iloc[-min_history:]
                missing_dates = window.index[window.isna()].tolist()
                n_missing = len(missing_dates)
                if n_missing > 0:
                    dates_str = ", ".join(d.strftime("%Y-%m-%d") for d in missing_dates[:30])
                    if n_missing > 30:
                        dates_str += f" ... 共{n_missing}天"
                    _log.warning(
                        f"[资产选择] {col} 近{min_history}日内缺少数据的日期: {dates_str}"
                    )

    result["有效资产"] = valid_assets
    excluded = [a for a in nav.columns if a not in valid_assets]
    if excluded and valid_assets:
        calc_str = calc_date.strftime("%Y-%m-%d") if hasattr(calc_date, "strftime") else str(calc_date)
        _log.warning(
            f"[资产选择] 计算日 {calc_str} 数据不足资产(不参与选择，其他资产继续): {', '.join(excluded)}"
        )

    # 无资产满足 min_history 时直接返回，不做 fallback
    if not valid_assets:
        calc_str = calc_date.strftime("%Y-%m-%d") if hasattr(calc_date, "strftime") else str(calc_date)
        hist_str = ", ".join(f"{a}={asset_days.get(a, 0)}天" for a in nav.columns)
        _log.warning(
            f"[资产选择] 计算日 {calc_str} 无有效资产(需{min_history}天)，权重全为0。各资产历史天数: {hist_str}"
        )
        return result

    # ------------------------------------------------------------------
    # 委托 advanced_momentum_factors 完成因子计算与资产选择
    # ------------------------------------------------------------------
    price_data = nav[valid_assets].iloc[: date_idx + 1]

    momentum_selected, reversal_selected, mom_df, rev_df = (
        select_momentum_and_reversal_assets(
            prices=price_data,
            n_momentum=top_momentum,
            n_reversal=1,
            min_history_days=min_history,
        )
    )

    # ------------------------------------------------------------------
    # 从 mom_df 提取得分字典
    # ------------------------------------------------------------------
    mom_scores: Dict[str, int] = {}
    if not mom_df.empty and "TotalMomentumScore" in mom_df.columns:
        mom_scores = {k: int(v) for k, v in mom_df["TotalMomentumScore"].to_dict().items()}

    rev_scores: Dict[str, float] = {}
    if not rev_df.empty and "TotalReversalScore" in rev_df.columns:
        rev_scores = rev_df["TotalReversalScore"].to_dict()

    # ------------------------------------------------------------------
    # 构建动量排名 DataFrame（与原始格式兼容）
    # ------------------------------------------------------------------
    mom_series = pd.Series(mom_scores).sort_values(ascending=False)
    mom_ranking_df = pd.DataFrame({
        "资产": mom_series.index,
        "动量得分": mom_series.values,
        "动量排名": range(1, len(mom_series) + 1),
    })
    mom_ranking_df["动量入选"] = mom_ranking_df["资产"].isin(momentum_selected)
    result["动量详情"] = mom_df
    result["动量排名"] = mom_ranking_df
    result["动量入选"] = momentum_selected

    # ------------------------------------------------------------------
    # 构建反转排名 DataFrame（与原始格式兼容）
    # ------------------------------------------------------------------
    rev_series = pd.Series(rev_scores).sort_values(ascending=False)
    skew_ranking_df = pd.DataFrame({
        "资产": rev_series.index,
        "反转综合得分": rev_series.values,
        "反转排名": range(1, len(rev_series) + 1),
    })
    # 附加偏度详情列
    if rev_df is not None and not rev_df.empty:
        for asset in skew_ranking_df["资产"]:
            if asset in rev_df.index:
                for c in ["Skew_10", "Skew_10_rank", "Skew_10_score",
                           "Skew_22", "Skew_22_rank", "Skew_22_score"]:
                    if c in rev_df.columns:
                        skew_ranking_df.loc[skew_ranking_df["资产"] == asset, c] = rev_df.loc[asset, c]
    skew_ranking_df["反转入选"] = skew_ranking_df["资产"].isin(reversal_selected)
    result["反转详情"] = rev_df
    result["反转排名"] = skew_ranking_df
    result["反转入选"] = reversal_selected

    # ------------------------------------------------------------------
    # 最终入选 & 入选矩阵
    # ------------------------------------------------------------------
    final_selected = list(set(momentum_selected + reversal_selected))
    result["最终入选"] = final_selected

    mom_set = set(momentum_selected)
    rev_set = set(reversal_selected)
    for asset in nav.columns:
        if asset not in valid_assets:
            result["入选矩阵_row"][asset] = 0
        elif asset in mom_set and asset in rev_set:
            result["入选矩阵_row"][asset] = 2
        elif asset in mom_set or asset in rev_set:
            result["入选矩阵_row"][asset] = 1
        else:
            result["入选矩阵_row"][asset] = 0

    return result


# =============================================================================
# 第二部分：权重计算（本地实现）
# =============================================================================

# ---- 私有辅助函数（取自 quant_core/volatility.py + weighting.py）----


def _calc_asset_volatility(
    prices: pd.DataFrame,
    date_idx: int,
    windows: List[int] = None,
    annualize_factor: int = None,
) -> Dict[str, float]:
    """
    计算各资产波动率：取多窗口（默认 22、65、130 日）年化波动率的最大值。
    使用 np.nanstd 对含 NaN 数据更鲁棒。
    """
    if windows is None:
        windows = VOL_WINDOWS
    if annualize_factor is None:
        annualize_factor = ANNUALIZE_FACTOR
    _ann = np.sqrt(annualize_factor)

    returns = prices.pct_change()

    vols: Dict[str, float] = {}
    for asset in prices.columns:
        asset_vols = []
        for w in windows:
            if date_idx >= w:
                ret_window = returns[asset].iloc[date_idx - w + 1:date_idx + 1]
                vol = float(np.nanstd(ret_window)) * _ann
                if not np.isnan(vol):
                    asset_vols.append(vol)
        vols[asset] = max(asset_vols) if asset_vols else np.nan

    return vols


def _calc_portfolio_volatility(
    prices: pd.DataFrame,
    weights: Dict[str, float],
    date_idx: int,
    windows: List[int] = None,
    annualize_factor: int = None,
    fillna_zero: bool = True,
) -> float:
    """
    计算组合波动率：权重加权收益率的多窗口年化波动率取最大值。
    """
    if windows is None:
        windows = VOL_WINDOWS
    if annualize_factor is None:
        annualize_factor = ANNUALIZE_FACTOR
    _ann = np.sqrt(annualize_factor)

    returns = prices.pct_change()

    valid_assets = [a for a in weights.keys() if weights[a] > 0 and a in returns.columns]
    if not valid_assets:
        return 0.0

    port_vols = []
    for w in windows:
        if date_idx >= w:
            port_returns = pd.Series(0.0, index=returns.index)
            for asset in valid_assets:
                asset_ret = returns[asset].fillna(0) if fillna_zero else returns[asset]
                port_returns += weights[asset] * asset_ret

            ret_window = port_returns.iloc[date_idx - w + 1:date_idx + 1]
            vol = float(np.nanstd(ret_window)) * _ann
            if not np.isnan(vol):
                port_vols.append(vol)

    return max(port_vols) if port_vols else 0.0


def _calc_risk_budgets(
    selected_assets: List[str],
    momentum_selected: List[str],
    reversal_selected: List[str],
    all_assets: List[str] = None,
    risk_budget_both: float = None,
    risk_budget_single: float = None,
) -> Dict[str, float]:
    """
    根据入选情况分配风险预算。
    动量+反转同时入选：2/8；仅动量或仅反转：1/8；未入选：0。
    """
    if risk_budget_both is None:
        risk_budget_both = RISK_BUDGET_BOTH
    if risk_budget_single is None:
        risk_budget_single = RISK_BUDGET_SINGLE

    mom_set = set(momentum_selected)
    rev_set = set(reversal_selected)

    assets_to_process = all_assets if all_assets is not None else list(
        set(selected_assets) | mom_set | rev_set
    )

    budgets: Dict[str, float] = {}
    for asset in assets_to_process:
        is_mom = asset in mom_set
        is_rev = asset in rev_set
        if is_mom and is_rev:
            budgets[asset] = risk_budget_both
        elif is_mom or is_rev:
            budgets[asset] = risk_budget_single
        else:
            budgets[asset] = 0.0

    return budgets


def _calc_initial_weights(
    risk_budgets: Dict[str, float],
    asset_vols: Dict[str, float],
    target_vol: float = None,
) -> Dict[str, float]:
    """
    计算初始权重：w_init = b × (target_vol / σ)
    """
    if target_vol is None:
        target_vol = TARGET_VOL

    weights: Dict[str, float] = {}
    for asset in risk_budgets.keys():
        b = risk_budgets[asset]
        sigma = asset_vols.get(asset, np.nan)
        if b > 0 and sigma > 0 and not np.isnan(sigma):
            weights[asset] = b * (target_vol / sigma)
        else:
            weights[asset] = 0.0

    return weights


def _apply_scale_constraint(
    weights: Dict[str, float],
    portfolio_vol: float,
    target_vol: float = None,
    max_leverage: float = None,
) -> Tuple[Dict[str, float], float]:
    """
    应用组合波动率与杠杆约束：scale = min(target_vol / σ_port, max_leverage / Σw)
    """
    if target_vol is None:
        target_vol = TARGET_VOL
    if max_leverage is None:
        max_leverage = MAX_LEVERAGE

    total_weight = sum(weights.values())

    if total_weight <= 0:
        return weights, 1.0

    scale_vol = target_vol / portfolio_vol if portfolio_vol > 0 else 1.0
    scale_leverage = max_leverage / total_weight
    scale = min(scale_vol, scale_leverage)

    scaled_weights = {k: v * scale for k, v in weights.items()}
    return scaled_weights, scale


def _apply_weight_caps(
    weights: Dict[str, float],
    caps: Dict[str, float] = None,
) -> Dict[str, float]:
    """
    应用权重上限截断（只截断超限权重，不做再分配）。
    """
    if caps is None:
        caps = {}

    if sum(weights.values()) <= 0:
        return weights

    capped = weights.copy()
    for asset in capped.keys():
        cap = caps.get(asset, 1.0)
        if capped[asset] > cap:
            capped[asset] = cap

    return capped


def calc_weights_for_date(
    nav: pd.DataFrame,
    date_idx: int,
    selection_row: Dict[str, int],
    all_assets: List[str],
    target_vol: float = 0.05,
    max_leverage: float = 4.0,
    weight_caps: Optional[Dict[str, float]] = None,
    fillna_zero: bool = False,
    risk_budget_both: float = None,
    risk_budget_single: float = None,
) -> Dict[str, Any]:
    """
    单日权重计算（本地 6 步流程）。
    默认 fillna_zero=False 与参考一致，确保 ex-ante vol 对齐。
    """
    weight_caps = weight_caps or {}
    default_cap = DEFAULT_WEIGHT_CAP

    # 从 selection_row（0/1/2 编码）还原为 momentum / reversal 列表
    momentum_selected: List[str] = []
    reversal_selected: List[str] = []
    selected_assets: List[str] = []
    for asset, status in selection_row.items():
        if status == 2:
            momentum_selected.append(asset)
            reversal_selected.append(asset)
            selected_assets.append(asset)
        elif status == 1:
            # status=1 无法区分动量/反转，风险预算均为 1/8，归入动量即可
            momentum_selected.append(asset)
            selected_assets.append(asset)

    # 构建权重上限（与原始逻辑一致：未指定的资产默认 0.1）
    caps = {a: weight_caps.get(a, default_cap) for a in all_assets}

    # 1. 分配风险预算
    budget_kwargs = {}
    if risk_budget_both is not None:
        budget_kwargs['risk_budget_both'] = risk_budget_both
    if risk_budget_single is not None:
        budget_kwargs['risk_budget_single'] = risk_budget_single
    risk_budgets = _calc_risk_budgets(
        selected_assets, momentum_selected, reversal_selected,
        all_assets=all_assets,
        **budget_kwargs,
    )

    # 2. 计算资产波动率
    asset_vols = _calc_asset_volatility(nav, date_idx)

    # 3. 计算初始权重
    initial_weights = _calc_initial_weights(risk_budgets, asset_vols, target_vol)

    # 4. 计算组合波动率（使用初始权重）
    portfolio_vol = _calc_portfolio_volatility(
        nav, initial_weights, date_idx, fillna_zero=fillna_zero,
    )

    # 5. 缩放约束
    scaled_weights, scale_factor = _apply_scale_constraint(
        initial_weights, portfolio_vol, target_vol, max_leverage,
    )

    # 6. 权重上限截断
    final_weights = _apply_weight_caps(scaled_weights, caps)

    total_leverage = sum(final_weights.values())

    # 转换为原始中文键格式
    total_weight = sum(initial_weights.values())
    scale_vol = target_vol / portfolio_vol if portfolio_vol > 0 else 1.0
    scale_leverage = max_leverage / total_weight if total_weight > 0 else 1.0

    return {
        "风险预算": risk_budgets,
        "资产波动率": asset_vols,
        "初始权重": initial_weights,
        "缩放后权重": scaled_weights,
        "最终权重": final_weights,
        "组合波动率": portfolio_vol,
        "缩放系数": scale_factor,
        "总杠杆": total_leverage,
        "_debug_total_weight": total_weight,
        "_debug_scale_vol": scale_vol,
        "_debug_scale_leverage": scale_leverage,
        "_debug_scaled_sum": sum(scaled_weights.values()),
    }
