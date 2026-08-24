# -*- coding: utf-8 -*-
"""
投资组合权重构建服务

提供多种子策略权重分配算法：
- equal_weight: 等权分配 (1/N)
- risk_parity: 风险平价（基于子策略 NAV 收益率协方差的风险贡献均等化）
- min_variance: 最小方差（最小化组合波动率）
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


class WeightMethod(str, Enum):
    """权重构建方法"""
    CUSTOM = "custom"               # 用户自定义（直接使用 sub_strategies 中的 weight）
    EQUAL_WEIGHT = "equal_weight"   # 等权分配
    RISK_PARITY = "risk_parity"     # 风险平价
    MIN_VARIANCE = "min_variance"   # 最小方差


class PortfolioWeightBuilder:
    """
    投资组合权重构建器

    基于子策略历史 NAV 收益率序列计算最优权重分配。
    """

    @staticmethod
    def compute_weights(
        sub_nav_series: Dict[str, pd.Series],
        method: str = "equal_weight",
        lookback_days: int = 252,
        min_weight: float = 0.05,
        max_weight: float = 0.80,
        allow_fallback: bool = False,
        degradation_notes: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """
        根据指定方法计算子策略权重。

        Parameters
        ----------
        sub_nav_series : Dict[str, pd.Series]
            各子策略的 NAV 序列（DatetimeIndex → float）。
        method : str
            权重方法: "equal_weight" / "risk_parity" / "min_variance" / "custom"
        lookback_days : int
            用于计算协方差的历史数据回看期（交易日）。
        min_weight : float
            单个子策略最小权重。
        max_weight : float
            单个子策略最大权重。
        allow_fallback : bool
            样本不足 / 协方差非法 / 优化失败时是否允许降级为等权。
            默认 False（抛错）：调用方会把 method 落库并展示给用户，
            静默降级会让「风险平价」的标签配上等权的实际结果。
        degradation_notes : Optional[List[str]]
            传入列表可收集降级原因（仅 allow_fallback=True 时产生内容）。

        Returns
        -------
        Dict[str, float]
            子策略权重字典，权重和为 1.0。

        Raises
        ------
        ValueError
            method 不可识别，或 allow_fallback=False 时无法按该方法求解。
        """
        if not sub_nav_series:
            raise ValueError("sub_nav_series 为空")

        keys = list(sub_nav_series.keys())
        n = len(keys)

        if n == 1:
            return {keys[0]: 1.0}

        if method == WeightMethod.EQUAL_WEIGHT or method == "equal_weight":
            return PortfolioWeightBuilder._equal_weight(keys)
        elif method == WeightMethod.CUSTOM or method == "custom":
            # 自定义权重由调用方直接提供，本方法仅作为兼容入口
            return PortfolioWeightBuilder._equal_weight(keys)
        elif method == WeightMethod.RISK_PARITY or method == "risk_parity":
            return PortfolioWeightBuilder._risk_parity(
                sub_nav_series, keys, lookback_days, min_weight, max_weight,
                allow_fallback, degradation_notes,
            )
        elif method == WeightMethod.MIN_VARIANCE or method == "min_variance":
            return PortfolioWeightBuilder._min_variance(
                sub_nav_series, keys, lookback_days, min_weight, max_weight,
                allow_fallback, degradation_notes,
            )
        else:
            raise ValueError(
                f"未知的权重方法: {method}。"
                f"可选值: {', '.join(m.value for m in WeightMethod)}"
            )

    @staticmethod
    def _equal_weight(keys: List[str]) -> Dict[str, float]:
        """等权分配"""
        n = len(keys)
        w = 1.0 / n
        return {k: w for k in keys}

    @staticmethod
    def _fallback_or_raise(
        keys: List[str],
        method_label: str,
        reason: str,
        allow_fallback: bool,
        degradation_notes: Optional[List[str]],
    ) -> Dict[str, float]:
        """统一处理求解失败：允许降级则返回等权并留痕，否则抛出可操作错误。"""
        if not allow_fallback:
            raise ValueError(
                f"{method_label}权重求解失败: {reason}\n"
                f"子策略数={len(keys)}\n"
                "请延长建仓区间以积累足够的子策略净值历史、放宽权重上下限，"
                "或显式改用等权（equal_weight）"
            )
        note = f"{method_label}: {reason}, 降级为等权"
        logger.warning(note)
        if degradation_notes is not None:
            degradation_notes.append(note)
        return PortfolioWeightBuilder._equal_weight(keys)

    @staticmethod
    def _get_returns_matrix(
        sub_nav_series: Dict[str, pd.Series],
        keys: List[str],
        lookback_days: int,
    ) -> pd.DataFrame:
        """构建子策略收益率矩阵"""
        # 对齐所有子策略到共同日期
        all_navs = pd.DataFrame({k: sub_nav_series[k] for k in keys})
        all_navs = all_navs.sort_index().ffill().bfill()

        # 截取最近 lookback_days 天
        if len(all_navs) > lookback_days:
            all_navs = all_navs.iloc[-lookback_days:]

        # 计算日收益率
        returns = all_navs.pct_change().dropna()
        return returns

    @staticmethod
    def _risk_parity(
        sub_nav_series: Dict[str, pd.Series],
        keys: List[str],
        lookback_days: int,
        min_weight: float,
        max_weight: float,
        allow_fallback: bool = False,
        degradation_notes: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """
        风险平价权重计算

        目标：使各子策略的风险贡献均等。
        risk_contribution_i = w_i * (Cov * w)_i
        最小化 sum((RC_i - RC_target)^2)

        目标函数用归一化风险贡献占比（rc_pct），无量纲，因此对协方差是否
        年化不敏感；配合 ftol=1e-12 可避免 SLSQP 在日频尺度上假收敛。
        """
        returns = PortfolioWeightBuilder._get_returns_matrix(
            sub_nav_series, keys, lookback_days
        )
        n = len(keys)

        if returns.empty or len(returns) < max(n + 1, 10):
            return PortfolioWeightBuilder._fallback_or_raise(
                keys, "风险平价",
                f"样本不足 ({len(returns)} 行, 需要 {max(n + 1, 10)}+)",
                allow_fallback, degradation_notes,
            )

        cov_matrix = returns.cov().values

        # 检查协方差矩阵有效性
        if np.any(np.isnan(cov_matrix)) or np.any(np.isinf(cov_matrix)):
            return PortfolioWeightBuilder._fallback_or_raise(
                keys, "风险平价", "协方差矩阵含 NaN/Inf",
                allow_fallback, degradation_notes,
            )

        # 优化
        x0 = np.full(n, 1.0 / n)
        bounds = tuple((min_weight, max_weight) for _ in range(n))
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        def objective(w):
            port_var = w @ cov_matrix @ w
            if port_var <= 0:
                return 1e10
            marginal_risk = cov_matrix @ w
            risk_contrib = w * marginal_risk
            rc_pct = risk_contrib / port_var
            target = 1.0 / n
            return float(np.sum((rc_pct - target) ** 2))

        result = minimize(
            objective, x0, method="SLSQP",
            bounds=bounds, constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-12}
        )

        if result.success:
            weights = np.maximum(result.x, 0)
            weights = weights / weights.sum()
            return {keys[i]: round(float(weights[i]), 6) for i in range(n)}
        return PortfolioWeightBuilder._fallback_or_raise(
            keys, "风险平价", f"优化失败 ({result.message})",
            allow_fallback, degradation_notes,
        )

    @staticmethod
    def _min_variance(
        sub_nav_series: Dict[str, pd.Series],
        keys: List[str],
        lookback_days: int,
        min_weight: float,
        max_weight: float,
        allow_fallback: bool = False,
        degradation_notes: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """
        最小方差权重计算

        目标：最小化组合波动率 w^T * Cov * w
        """
        returns = PortfolioWeightBuilder._get_returns_matrix(
            sub_nav_series, keys, lookback_days
        )
        n = len(keys)

        if returns.empty or len(returns) < max(n + 1, 10):
            return PortfolioWeightBuilder._fallback_or_raise(
                keys, "最小方差",
                f"样本不足 ({len(returns)} 行, 需要 {max(n + 1, 10)}+)",
                allow_fallback, degradation_notes,
            )

        cov_matrix = returns.cov().values

        if np.any(np.isnan(cov_matrix)) or np.any(np.isinf(cov_matrix)):
            return PortfolioWeightBuilder._fallback_or_raise(
                keys, "最小方差", "协方差矩阵含 NaN/Inf",
                allow_fallback, degradation_notes,
            )

        # 优化
        x0 = np.full(n, 1.0 / n)
        bounds = tuple((min_weight, max_weight) for _ in range(n))
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        def objective(w):
            return float(w @ cov_matrix @ w)

        result = minimize(
            objective, x0, method="SLSQP",
            bounds=bounds, constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-12}
        )

        if result.success:
            weights = np.maximum(result.x, 0)
            weights = weights / weights.sum()
            return {keys[i]: round(float(weights[i]), 6) for i in range(n)}
        return PortfolioWeightBuilder._fallback_or_raise(
            keys, "最小方差", f"优化失败 ({result.message})",
            allow_fallback, degradation_notes,
        )
