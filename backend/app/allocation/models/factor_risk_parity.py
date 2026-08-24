"""Factor risk parity strategy implementation.

基于PCA因子的风险平价策略，自动从资产收益率中提取主成分作为风险因子。
因子提取逻辑已抽取为独立的 PcaFactorModel（app.allocation.factor_model），
本策略仅保留风险平价优化逻辑。

Entry point
-----------
    allocate(prices: DataFrame, **params) -> Series

核心特点
----------
1. 使用 PcaFactorModel 自动提取因子，因子模型可替换
2. 正确计算因子风险贡献，实现真正的因子风险平价
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from app.allocation.factor_model import PcaFactorModel
from app.allocation.models.base import BaseStrategyModel

logger = logging.getLogger(__name__)


class FactorRiskParityStrategy(BaseStrategyModel):
    """PCA因子风险平价策略。
    
    自动从资产收益率中提取PCA因子，并实现因子级别的风险平价配置。
    """
    
    @classmethod
    def get_param_schema(cls):
        """返回因子风险平价策略的参数Schema."""
        from app.allocation.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="factor_rp",
            display_name="因子风险平价",
            description="PCA主成分分解后在因子空间实现等风险贡献，控制因子维度风险暴露",
            params=[
                # PCA相关参数
                ParamSchema(
                    name="n_factors",
                    label="PCA因子数量",
                    type="number",
                    default=3,
                    min_value=0,
                    max_value=10,
                    step=1,
                    description=(
                        "PCA提取的因子数量，设为0表示根据解释方差自动确定。"
                        "必须小于资产数（等于资产数时PCA完全重构收益，特异性风险恒为0），"
                        "建议不超过资产数的一半，高阶主成分接近单资产噪声"
                    ),
                ),
                ParamSchema(
                    name="explained_variance",
                    label="解释方差阈值",
                    type="slider",
                    default=0.85,
                    min_value=0.7,
                    max_value=0.99,
                    step=0.01,
                    description="累计解释方差阈值，用于自动确定因子数量（仅当因子数量=0时生效）",
                    condition={"field": "n_factors", "value": 0},
                ),
                ParamSchema(
                    name="include_specific_risk",
                    label="包含特异性风险",
                    type="checkbox",
                    default=True,
                    description="是否在优化中考虑资产的特异性风险"
                ),
                ParamSchema(
                    name="min_weight",
                    label="单资产最小权重",
                    type="number",
                    default=0.0,
                    min_value=0.0,
                    max_value=None,
                    step=0.01,
                    description="单个资产的最小持仓权重",
                    group="advanced",
                ),
                ParamSchema(
                    name="max_weight",
                    label="单资产最大权重",
                    type="number",
                    default=1.0,
                    min_value=0.0,
                    max_value=None,
                    step=0.05,
                    description="单个资产的最大持仓权重",
                    group="advanced",
                ),
                ParamSchema(
                    name="maxiter",
                    label="最大迭代次数",
                    type="number",
                    default=1000,
                    min_value=100,
                    max_value=5000,
                    step=100,
                    description="优化器的最大迭代次数",
                    group="advanced",
                ),
            ]
        )
    
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """因子风险平价配置方法。
        
        核心原理：
        1. 使用 PcaFactorModel 从资产收益率提取因子
        2. 计算每个因子对组合总风险的贡献（TRC）
        3. 计算特异性风险的总贡献
        4. 优化目标：所有风险贡献占比相等
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")
        
        assets = prices.columns
        n_assets = len(assets)
        
        if n_assets < 2:
            raise ValueError("因子风险平价策略至少需要2个资产")
        
        # 1. 提取 PCA 因子
        n_factors = int(params.get("n_factors", 3))
        explained_variance = float(params.get("explained_variance", 0.85))
        include_specific = params.get("include_specific_risk", True)
        
        factor_model = PcaFactorModel(
            n_factors=n_factors,
            explained_variance=explained_variance,
            lookback_days=len(prices),  # 全样本
        )
        as_of = prices.index[-1]
        signal = factor_model.compute(prices, as_of)
        
        F = signal.factor_exposures.values  # (n_assets, n_factors)
        actual_n_factors = F.shape[1]
        factor_cov = signal.factor_covariance
        specific_risk = signal.specific_risk.values.copy()

        # 因子数不得达到资产数：PCA 会完全重构收益矩阵，残差为 0，
        # 特异性风险恒等于 0（实测量级 1e-18）。此时 include_specific_risk
        # 彻底失效，且目标函数中特异项的目标份额 1/(k+1) 永远无法达成，
        # 优化器仍会返回 success=True 的“尽力而为”解。
        if actual_n_factors >= n_assets:
            raise ValueError(
                f"PCA因子数({actual_n_factors})不得达到或超过资产数({n_assets})："
                "此时PCA完全重构收益，特异性风险恒为0，因子风险平价退化为对主成分坐标做ERC。\n"
                f"请将因子数降至 {n_assets - 1} 以下（建议不超过 {max(1, n_assets // 2)}），或增加资产数量"
            )
        if actual_n_factors > n_assets // 2:
            logger.warning(
                "因子风险平价: 因子数(%d)超过资产数(%d)的一半，"
                "高阶主成分接近单资产特异噪声，权重可能过度集中于噪声因子对应的资产",
                actual_n_factors, n_assets,
            )

        if not include_specific:
            specific_risk = np.zeros(n_assets)
        
        # 2. 目标函数：因子风险平价
        def objective(w: np.ndarray) -> float:
            b = F.T @ w
            factor_var = b.T @ factor_cov @ b
            specific_var = np.sum((w**2) * (specific_risk**2))
            total_var = factor_var + specific_var
            total_vol = np.sqrt(max(total_var, 1e-12))
            if total_vol < 1e-12:
                return 1e12
            marginal_factor_risk = factor_cov @ b / total_vol
            factor_trc = b * marginal_factor_risk
            specific_trc = specific_var / total_vol
            all_trc = np.concatenate([factor_trc, [specific_trc]])
            trc_shares = all_trc / total_vol
            target_share = 1.0 / len(trc_shares)
            return np.sum((trc_shares - target_share) ** 2)
        
        # 3. 优化约束和边界
        min_weight = float(params.get("min_weight", 0.0))
        max_weight = float(params.get("max_weight", 1.0))
        bounds = tuple((min_weight, max_weight) for _ in range(n_assets))
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        x0 = np.ones(n_assets) / n_assets
        
        # 4. 优化求解
        result = minimize(
            objective, x0, method="SLSQP",
            bounds=bounds, constraints=constraints,
            options={"maxiter": int(params.get("maxiter", 1000)), "ftol": 1e-8}
        )
        
        if not result.success:
            raise RuntimeError(
                f"因子风险平价优化失败: {result.message}\n"
                f"优化状态: {result.status}\n"
                f"目标函数值: {result.fun}\n"
                f"PCA因子数量: {actual_n_factors}\n"
                "请检查数据质量、参数配置或增加最大迭代次数"
            )
        
        # 5. 归一化权重
        w_opt = np.maximum(result.x, 0.0)
        w_opt = w_opt / np.sum(w_opt)

        # 6. 达成度检查：SLSQP 返回 success 仅说明收敛到局部最优，
        #    并不保证等风险贡献目标可达（可行域受权重约束与因子结构限制）。
        #    偏离过大时给出诊断，避免“尽力而为的解”被当成真正的因子风险平价。
        b_opt = F.T @ w_opt
        total_var_opt = float(
            b_opt @ factor_cov @ b_opt + np.sum((w_opt ** 2) * (specific_risk ** 2))
        )
        if total_var_opt > 1e-16:
            shares = np.concatenate([
                b_opt * (factor_cov @ b_opt) / total_var_opt,
                [float(np.sum((w_opt ** 2) * (specific_risk ** 2))) / total_var_opt],
            ])
            target_share = 1.0 / len(shares)
            max_dev = float(np.abs(shares - target_share).max())
            if max_dev > 0.5 * target_share:
                logger.warning(
                    "因子风险平价: 等风险贡献目标未达成，最大份额偏离=%.4f（目标份额=%.4f），"
                    "实际份额=%s。常见原因：权重上下限收紧、因子数偏高使特异性风险份额难以抬升",
                    max_dev, target_share, np.round(shares, 4).tolist(),
                )

        return pd.Series(w_opt, index=assets)
