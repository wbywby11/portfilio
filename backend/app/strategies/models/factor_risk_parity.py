"""Factor risk parity strategy implementation.

基于PCA因子的风险平价策略，自动从资产收益率中提取主成分作为风险因子。

Entry point
-----------
    allocate(prices: DataFrame, **params) -> Series

核心特点
----------
1. 使用PCA从资产收益率自动提取因子，无需外部输入
2. 支持静态PCA（全样本）和滚动PCA（动态因子）
3. 可配置因子数量或累计解释方差阈值
4. 正确计算因子风险贡献，实现真正的因子风险平价
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.decomposition import PCA

from app.strategies.formula.returns import compute_simple_returns
from app.strategies.models.base import BaseStrategyModel


class FactorRiskParityStrategy(BaseStrategyModel):
    """PCA因子风险平价策略。
    
    自动从资产收益率中提取PCA因子，并实现因子级别的风险平价配置。
    """
    
    @classmethod
    def get_param_schema(cls):
        """返回因子风险平价策略的参数Schema."""
        from app.strategies.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="factor_rp",
            display_name="因子风险平价策略",
            description="基于PCA自动提取因子，实现因子级别的风险平价配置",
            params=[
                # PCA相关参数
                ParamSchema(
                    name="n_factors",
                    label="PCA因子数量",
                    type="number",
                    default=3,
                    min_value=1,
                    max_value=10,
                    step=1,
                    description="PCA提取的因子数量，设为0表示根据解释方差自动确定"
                ),
                ParamSchema(
                    name="explained_variance",
                    label="解释方差阈值",
                    type="slider",
                    default=0.85,
                    min_value=0.7,
                    max_value=0.99,
                    step=0.01,
                    description="累计解释方差阈值，用于自动确定因子数量（仅当因子数量=0时生效）"
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
                    description="单个资产的最小持仓权重"
                ),
                ParamSchema(
                    name="max_weight",
                    label="单资产最大权重",
                    type="number",
                    default=1.0,
                    min_value=0.0,
                    max_value=None,
                    step=0.05,
                    description="单个资产的最大持仓权重"
                ),
                ParamSchema(
                    name="maxiter",
                    label="最大迭代次数",
                    type="number",
                    default=1000,
                    min_value=100,
                    max_value=5000,
                    step=100,
                    description="优化器的最大迭代次数"
                ),
            ]
        )
    
    def _extract_pca_factors(self, returns: pd.DataFrame, 
                            n_factors: int,
                            explained_variance: float) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
        """使用PCA从资产收益率中提取因子。
        
        Args:
            returns: 资产收益率矩阵 (T x N)
            n_factors: 因子数量，0表示自动确定
            explained_variance: 累计解释方差阈值
            
        Returns:
            factor_exposures: 因子暴露矩阵 (资产 x 因子)
            factor_returns: 因子收益率时间序列 (日期 x 因子)
            specific_risk: 特异性风险向量 (每个资产)
        """
        assets = returns.columns
        
        # 检查数据质量
        if returns.isna().any().any():
            # 对缺失值进行处理：前向填充后向填充
            returns = returns.ffill().bfill()
            if returns.isna().any().any():
                nan_cols = returns.columns[returns.isna().any()].tolist()
                raise ValueError(
                    f"以下资产的收益率数据存在无法填充的NaN: {nan_cols}"
                )
        
        # 标准化处理
        returns_mean = returns.mean()
        returns_std = returns.std()
        
        # 检查零方差资产
        zero_std_assets = returns_std[returns_std == 0].index.tolist()
        if zero_std_assets:
            raise ValueError(
                f"以下资产的收益率方差为0，无法进行PCA: {zero_std_assets}"
            )
        
        returns_scaled = (returns - returns_mean) / returns_std
        
        # 执行PCA
        pca = PCA()
        factor_scores = pca.fit_transform(returns_scaled)  # (T, N)
        
        # 确定因子数量
        if n_factors == 0 or n_factors is None:
            # 根据解释方差自动确定
            cumulative_var = np.cumsum(pca.explained_variance_ratio_)
            n_factors = int(np.argmax(cumulative_var >= explained_variance) + 1)
        
        # 确保因子数量不超过资产数量
        n_factors = min(n_factors, len(assets))
        
        # 提取前n_factors个主成分
        factor_returns = pd.DataFrame(
            factor_scores[:, :n_factors],
            index=returns.index,
            columns=[f"PC{i+1}" for i in range(n_factors)]
        )
        
        # 因子暴露 = PCA载荷矩阵的转置
        factor_exposures = pd.DataFrame(
            pca.components_[:n_factors, :].T,
            index=assets,
            columns=[f"PC{i+1}" for i in range(n_factors)]
        )
        
        # 计算特异性风险：残差方差
        # 重构收益率
        reconstructed = factor_scores[:, :n_factors] @ pca.components_[:n_factors, :]
        residuals = returns_scaled.values - reconstructed
        specific_risk = np.std(residuals, axis=0, ddof=1) * returns_std.values  # 还原到原始尺度
        
        return factor_exposures, factor_returns, specific_risk
    
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """因子风险平价配置方法。
        
        核心原理：
        1. 使用PCA从资产收益率提取因子
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
        
        # 1. 计算收益率
        returns = compute_simple_returns(prices)
        
        if len(returns) < 20:
            raise ValueError(
                f"数据量不足：需要至少20个交易日的数据，实际仅有{len(returns)}个"
            )
        
        # 2. 提取PCA参数
        n_factors = int(params.get("n_factors", 3))
        explained_variance = float(params.get("explained_variance", 0.85))
        include_specific = params.get("include_specific_risk", True)
        
        # 3. 提取PCA因子
        factor_exposures, factor_returns, specific_risk = self._extract_pca_factors(
            returns, n_factors, explained_variance
        )
        
        F = factor_exposures.values  # (n_assets, n_factors)
        actual_n_factors = F.shape[1]
        
        # 4. 计算因子协方差矩阵
        factor_cov = factor_returns.cov().values  # (n_factors, n_factors)
        
        # 如果不包含特异性风险
        if not include_specific:
            specific_risk = np.zeros(n_assets)
        
        # 5. 目标函数：因子风险平价
        def objective(w: np.ndarray) -> float:
            """
            因子风险平价目标函数：最小化因子风险贡献的差异
            """
            # 计算组合因子暴露
            b = F.T @ w  # (n_factors,)
            
            # 计算因子风险部分方差
            factor_var = b.T @ factor_cov @ b
            
            # 计算特异性风险部分方差
            specific_var = np.sum((w**2) * (specific_risk**2))
            
            # 组合总波动率
            total_var = factor_var + specific_var
            total_vol = np.sqrt(max(total_var, 1e-12))
            
            if total_vol < 1e-12:
                return 1e12
            
            # 计算因子风险贡献（TRC）
            marginal_factor_risk = factor_cov @ b / total_vol
            factor_trc = b * marginal_factor_risk
            
            # 特异性风险贡献
            specific_trc = specific_var / total_vol
            
            # 构建风险贡献向量
            all_trc = np.concatenate([factor_trc, [specific_trc]])
            
            # 计算风险贡献占比
            trc_shares = all_trc / total_vol
            
            # 目标：所有风险贡献占比相等
            target_share = 1.0 / len(trc_shares)
            
            return np.sum((trc_shares - target_share) ** 2)
        
        # 6. 优化约束和边界
        min_weight = float(params.get("min_weight", 0.0))
        max_weight = float(params.get("max_weight", 1.0))
        bounds = tuple((min_weight, max_weight) for _ in range(n_assets))
        
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
        ]
        
        # 7. 初始解：等权重
        x0 = np.ones(n_assets) / n_assets
        
        # 8. 优化求解
        result = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": int(params.get("maxiter", 1000)), "ftol": 1e-8}
        )
        
        # 9. 检查优化结果
        if not result.success:
            raise RuntimeError(
                f"因子风险平价优化失败: {result.message}\n"
                f"优化状态: {result.status}\n"
                f"目标函数值: {result.fun}\n"
                f"PCA因子数量: {actual_n_factors}\n"
                "请检查数据质量、参数配置或增加最大迭代次数"
            )
        
        # 10. 归一化权重
        w_opt = np.maximum(result.x, 0.0)
        w_opt = w_opt / np.sum(w_opt)
        
        return pd.Series(w_opt, index=assets)
