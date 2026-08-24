"""Risk budget strategy implementation in the new strategies module.

This class exposes a single entry point:

    allocate(prices: DataFrame, **params) -> Series

Core optimization
---------
Support two risk budget calculation modes:
1. **Auto mode**: Based on Sharpe ratio/Sortino ratio to automatically calculate risk budget
   - Direct proportion method: Risk budget_i ∝ ratio_i
   - Active deviation method: Based on ratio, supports manual tuning
2. **Manual mode**: User directly specifies risk budget for each asset

Required params
---------------
- budget_mode: str, budget calculation mode ("auto_sharpe", "auto_sortino", "manual")
- lookback_days: int, historical data lookback period (required for auto mode)
- allocation_method: str, allocation method ("direct", "adjusted")
- manual_adjustments: dict, manual adjustment factors (only used in adjusted mode)
- risk_budgets: dict, manual risk budgets (only used in manual mode)

Optional params
---------------
- cov_method: covariance estimation method (default: "sample")
- min_weight: lower bound per asset (default: 0.0)
- max_weight: upper bound per asset (default: 1.0)
- risk_free_rate: float, risk-free rate (default: 0.02)
"""

from __future__ import annotations

import logging
from typing import Mapping

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from app.formula.returns import compute_simple_returns
from app.formula.covariance import compute_covariance
from app.formula.sharpe_ratio import compute_sharpe_ratio
from app.formula.sortino_ratio import compute_sortino_ratio
from app.solvers.slsqp_solver import solve_slsqp
from app.allocation.models.base import BaseStrategyModel


class RiskBudgetStrategy(BaseStrategyModel):
    @classmethod
    def get_param_schema(cls):
        """Returns the parameter schema for the risk budget strategy."""
        from app.allocation.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="risk_budget",
            display_name="风险预算",
            description="SLSQP优化匹配用户指定风险预算，支持Sharpe/Sortino/手动三种预算模式",
            params=[
                ParamSchema(
                    name="budget_mode",
                    label="预算计算模式",
                    type="select",
                    default="auto_sharpe",
                    options=[
                        ("auto_sharpe", "自动模式-夏普比率"),
                        ("auto_sortino", "自动模式-索提诺比率"),
                        ("manual", "手动模式")
                    ],
                    description="选择风险预算计算方法:基于比率自动计算或手动指定"
                ),
                ParamSchema(
                    name="lookback_days",
                    label="历史数据回看期",
                    type="number",
                    default=252,
                    min_value=20,
                    max_value=500,
                    step=1,
                    description="计算夏普/索提诺比率使用的历史数据天数（交易日），默认252天（约1年），仅自动模式生效"
                ),
                ParamSchema(
                    name="allocation_method",
                    label="分配方法",
                    type="select",
                    default="direct",
                    options=[
                        ("direct", "直接比例法"),
                        ("adjusted", "主动偏离法")
                    ],
                    description="直接比例:风险预算与比率成正比;主动偏离:支持手动微调(仅自动模式生效)"
                ),
                ParamSchema(
                    name="risk_free_rate",
                    label="无风险利率",
                    type="number",
                    default=0.02,
                    min_value=0.0,
                    max_value=0.1,
                    step=0.001,
                    description="年化无风险利率，用于计算夏普/索提诺比率，全系统统一口径 0.02（2%），仅自动模式生效",
                    group="advanced",
                ),
                ParamSchema(
                    name="risk_budgets",
                    label="手动风险预算",
                    type="dict",
                    default={},
                    description="为每个资产手动指定风险预算，总和将自动归一化（仅manual模式使用）",
                    condition={"field": "budget_mode", "value": "manual"},
                ),
                ParamSchema(
                    name="manual_adjustments",
                    label="手动调整系数",
                    type="dict",
                    default={},
                    description="在自动计算基础上进行微调，系数>1增加预算，<1降低预算（仅adjusted模式使用）",
                    condition={"field": "allocation_method", "value": "adjusted"},
                ),
                ParamSchema(
                    name="cov_method",
                    label="协方差估计方法",
                    type="select",
                    default="sample",
                    options=[
                        ("sample", "样本协方差"),
                        ("ewm", "指数加权"),
                        ("ledoit_wolf", "Ledoit-Wolf收缩"),
                        ("oracle", "Oracle近似收缩")
                    ],
                    description="选择协方差矩阵的估计方法",
                    group="advanced",
                ),
                ParamSchema(
                    name="min_weight",
                    label="单资产最小权重",
                    type="number",
                    default=0.0,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                    description="单个资产的最小持仓权重，范围：0-1，默认0（允许空仓）"
                ),
                ParamSchema(
                    name="max_weight",
                    label="单资产最大权重",
                    type="number",
                    default=0.3,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.05,
                    description="单个资产的最大持仓权重，范围：0-1，默认0.3（30%）"
                ),
                ParamSchema(
                    name="maxiter",
                    label="最大迭代次数",
                    type="number",
                    default=1000,
                    min_value=100,
                    max_value=10000,
                    step=100,
                    description="优化器的最大迭代次数",
                    group="advanced",
                ),
            ]
        )
    
    def _compute_ratio_based_budgets(
        self,
        prices: pd.DataFrame,
        assets: pd.Index,
        mode: str,
        lookback_days: int,
        risk_free_rate: float
    ) -> np.ndarray:
        """Calculate risk budgets based on Sharpe ratio or Sortino ratio.
        
        Args:
            prices: Price data
            assets: List of assets
            mode: Calculation mode ("auto_sharpe" or "auto_sortino")
            lookback_days: Lookback period
            risk_free_rate: Risk-free rate
            
        Returns:
            np.ndarray: Unnormalized risk budget array
        """
        # Slice the last lookback_days days of data
        if len(prices) > lookback_days:
            prices_window = prices.iloc[-lookback_days:]
        else:
            prices_window = prices
        
        # Calculate returns
        returns = compute_simple_returns(prices_window)
        
        # Calculate ratio for each asset
        ratios = []
        for asset in assets:
            if asset not in returns.columns:
                ratios.append(0.0)
                continue
            
            asset_returns = returns[asset].dropna()
            
            if len(asset_returns) < 10:  # Insufficient data
                ratios.append(0.0)
                continue
            
            try:
                if mode == "auto_sharpe":
                    ratio = compute_sharpe_ratio(
                        asset_returns,
                        risk_free_rate=risk_free_rate,
                        freq_factor=260
                    )
                else:  # auto_sortino
                    ratio = compute_sortino_ratio(
                        asset_returns,
                        risk_free_rate=risk_free_rate,
                        freq_factor=260
                    )
                
                # Handle negative or invalid values: set negative ratios to 0
                ratio = max(ratio, 0.0)
                ratios.append(ratio)
            except Exception as exc:
                logger.warning(
                    "风险预算: 资产 [%s] %s 比率计算失败: %s，该资产比率置 0",
                    asset, mode, exc,
                )
                ratios.append(0.0)
        
        ratios_array = np.array(ratios)
        
        # If all ratios are <= 0, data is insufficient for auto mode
        if ratios_array.sum() <= 0:
            raise ValueError(
                f"风险预算自动模式失败: 所有资产的 {mode} 比率均 <= 0 或数据不足。\n"
                "可能原因: 历史数据太短、资产收益全为负、或数据质量异常。\n"
                "建议: 增加 lookback_days、检查价格数据、或切换到手动模式。"
            )
        
        return ratios_array
    
    def _apply_manual_adjustments(
        self,
        base_budgets: np.ndarray,
        assets: pd.Index,
        adjustments: dict
    ) -> np.ndarray:
        """Apply manual adjustment factors.
        
        Args:
            base_budgets: Base risk budgets
            assets: List of assets
            adjustments: Adjustment factor dictionary {asset: factor}
            
        Returns:
            np.ndarray: Adjusted risk budgets
        """
        adjusted = base_budgets.copy()
        
        if not adjustments:
            return adjusted
        
        for i, asset in enumerate(assets):
            factor = adjustments.get(asset, 1.0)
            # Factor should be positive
            factor = max(float(factor), 0.0)
            adjusted[i] *= factor
        
        return adjusted
    
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """Calculate asset allocation weights for the risk budget strategy.
        
        Supports three modes:
        1. auto_sharpe: Automatically calculate risk budget based on Sharpe ratio
        2. auto_sortino: Automatically calculate risk budget based on Sortino ratio
        3. manual: Manually specify risk budget
        
        Args:
            prices: Historical asset price data
            **params: Strategy parameters
        
        Returns:
            pd.Series: Asset allocation weights
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        # Get parameters
        budget_mode = params.get("budget_mode", "auto_sharpe")
        allocation_method = params.get("allocation_method", "direct")
        lookback_days = int(params.get("lookback_days", 252))  # 默认252天（约1年交易日）
        risk_free_rate = params.get("risk_free_rate", 0.02)  # 默认2%（全系统统一口径）
        
        # 0. Handle lookback_days parameter: limit the range of historical data used
        if lookback_days is not None and lookback_days > 0:
            if len(prices) > lookback_days:
                prices = prices.iloc[-lookback_days:]

        # 1. Compute returns and covariance
        returns = compute_simple_returns(prices)
        cov = compute_covariance(returns, method=params.get("cov_method", "sample"))

        assets = cov.columns
        n_assets = len(assets)
        if n_assets == 0:
            raise ValueError("No assets available after covariance computation")

        # 2. Calculate risk budgets based on mode
        if budget_mode in ["auto_sharpe", "auto_sortino"]:
            # Auto mode: Calculate based on ratios
            risk_budgets = self._compute_ratio_based_budgets(
                prices=prices,
                assets=assets,
                mode=budget_mode,
                lookback_days=lookback_days,
                risk_free_rate=risk_free_rate
            )
            
            # If adjusted method, apply manual adjustments
            if allocation_method == "adjusted":
                manual_adjustments = params.get("manual_adjustments", {})
                risk_budgets = self._apply_manual_adjustments(
                    base_budgets=risk_budgets,
                    assets=assets,
                    adjustments=manual_adjustments
                )
        else:
            # Manual mode: Directly use user-specified risk budgets
            risk_budgets_param = params.get("risk_budgets", {})
            
            if not risk_budgets_param or not isinstance(risk_budgets_param, Mapping):
                # Not provided, default to equal allocation
                risk_budgets = np.ones(n_assets)
            else:
                risk_budgets = np.array([float(risk_budgets_param.get(a, 0.0)) for a in assets])
        
        # 3. Normalize risk budgets
        total_budget = risk_budgets.sum()
        if total_budget <= 0:
            raise ValueError("Total risk budget must be positive, please check ratio calculation or manual settings")
        risk_budgets = risk_budgets / total_budget

        # 4. Initial weights (equal weight)
        x0 = np.full(shape=(n_assets,), fill_value=1.0 / n_assets, dtype=float)

        # 5. Constraints and bounds
        min_weight = float(params.get("min_weight", 0.0))  # 默认0（允许空仓）
        max_weight = float(params.get("max_weight", 0.3))  # 默认0.3（30%）
        lower_bound = max(0.0, min_weight)
        bounds = tuple((lower_bound, max_weight) for _ in range(n_assets))
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
        ]

        cov_values = cov.values

        # 辅助函数：安全地将矩阵乘法结果转换为标量
        def to_scalar(value):
            if isinstance(value, (np.ndarray, list)):
                return float(value.item() if hasattr(value, 'item') else value[0])
            return float(value)
        
        # 6. Objective: match target risk budgets
        def objective(w: np.ndarray) -> float:
            # Portfolio volatility
            portfolio_vol = np.sqrt(max(to_scalar(w @ cov_values @ w), 1e-12))
            # Marginal contributions
            marginal = cov_values @ w / portfolio_vol
            risk_contrib = w * marginal
            # Normalize to risk contribution shares
            if risk_contrib.sum() <= 0:
                rc_norm = np.zeros_like(risk_contrib)
            else:
                rc_norm = risk_contrib / risk_contrib.sum()
            diff = rc_norm - risk_budgets
            return float(np.dot(diff, diff))

        # 7. Solve optimization
        w_opt, success, message = solve_slsqp(
            x0=x0,
            objective=objective,
            bounds=bounds,
            constraints=constraints,
            maxiter=int(params.get("maxiter", 1000)),  # 默认1000次
        )

        # 8. Check optimization result
        if not success:
            raise RuntimeError(
                f"Risk budget optimization failed: {message}\n"
                "Please check data quality, parameter settings, or increase maximum iterations"
            )

        # 9. Normalize to ensure long-only and sum to 1
        w_opt = np.maximum(w_opt, 0.0)
        total = float(w_opt.sum())
        if total > 0:
            w_opt = w_opt / total

        weights = pd.Series(w_opt, index=assets)
        return weights
