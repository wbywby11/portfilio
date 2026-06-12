"""协方差-夏普优化模型 (Covariance-Sharpe Optimization, CSO) 实现.

本模型是原创的大类资产配置策略，核心特点：
1. 基于协方差矩阵的风险平价框架
2. 引入Sharpe比率增强项，平衡风险分散与收益优化
3. 支持风险贡献容忍度约束，精确控制风险分散程度
4. 支持单资产最大权重限制和历史数据回看期

核心方法
-----------
    allocate(prices: DataFrame, **params) -> Series

关键参数
----------
- lambda_sharpe: float, 收益增强系数 (默认0.0 = 纯最小方差)
- max_weight: float, 单资产最大权重 (默认0.5)
- epsilon: float, 风险贡献偏离阈值 (默认0.01)
          约束绝对风险贡献 RC_i = w_i·(Σw)_i 在 [mean(RC) ± epsilon] 范围内
- lookback_days: int, 历史数据回看期 (默认252天)
- cov_method: str, 协方差计算方法 (默认"sample")
- maxiter: int, 优化器最大迭代次数 (默认2000)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategies.formula.returns import compute_simple_returns
from app.strategies.formula.covariance import compute_covariance
from app.strategies.formula.risk_contribution import compute_risk_contribution
from app.strategies.formula.portfolio_returns import compute_portfolio_returns
from app.strategies.formula.sharpe_ratio import compute_sharpe_ratio
from app.strategies.solvers.slsqp_solver import solve_slsqp
from app.strategies.models.base import BaseStrategyModel


class CovarianceSharpeOptimization(BaseStrategyModel):
    """协方差-夏普优化模型 (CSO).
    
    这是一个原创的大类资产配置策略，通过双目标优化框架，
    同时追求风险的均等分散和收益的Sharpe增强。
    """
    @classmethod
    def get_param_schema(cls):
        """返回协方差-夏普优化模型的参数Schema."""
        from app.strategies.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="cso",  # Covariance-Sharpe Optimization
            display_name="协方差-夏普优化模型 (CSO)",
            description="原创策略：基于协方差矩阵的风险平价框架，引入Sharpe增强项优化收益，支持风险贡献精确控制",
            params=[
                ParamSchema(
                    name="max_weight",
                    label="单资产最大权重",
                    type="number",
                    default=0.5,
                    min_value=0.0,
                    max_value=None,
                    step=0.05,
                    description="限制单个资产的最大持仓权重，防止过度集中"
                ),
                ParamSchema(
                    name="epsilon",
                    label="风险贡献偏离阈值",
                    type="number",
                    default=0.01,
                    min_value=0.0,
                    max_value=None,
                    step=0.001,
                    description="允许绝对风险贡献偏离均值的最大幅度，值越小风险分散越均匀"
                ),
                ParamSchema(
                    name="lambda_sharpe",
                    label="收益增强系数",
                    type="number",
                    default=0.0,
                    min_value=0.0,
                    max_value=None,
                    step=0.1,
                    description="控制组合方差与收益优化的平衡，0表示纯最小方差组合"
                ),
                ParamSchema(
                    name="lookback_days",
                    label="历史数据回看期",
                    type="number",
                    default=252,
                    min_value=0.0,
                    max_value=None,
                    step=10,
                    description="计算协方差矩阵使用的历史数据天数（交易日），默认252天约1年"
                ),
                ParamSchema(
                    name="maxiter",
                    label="最大迭代次数",
                    type="number",
                    default=2000,
                    min_value=0.0,
                    max_value=None,
                    step=100,
                    description="优化器的最大迭代次数"
                ),
            ]
        )
    
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """计算协方差-夏普优化模型的资产配置权重.
        
        本方法实现CSO模型的核心优化逻辑：
        1. 基于历史价格计算收益率和协方差矩阵
        2. 设置风险贡献约束和权重边界
        3. 优化目标函数：min 0.5·w^T·Σ·w - λ·w^T·S
        4. 返回归一化的资产配置权重
        
        Args:
            prices: 资产价格历史数据，行为日期，列为资产代码
            **params: 策略参数
                - lambda_sharpe: 收益增强系数（默认0.0，纯最小方差）
                - max_weight: 单资产最大权重（默认1.0）
                - epsilon: 风险贡献偏离阈值（默认0.01）
                - lookback_days: 历史数据回看期（默认252天）
                - cov_method: 协方差计算方法（默认"sample"）
                - maxiter: 优化器最大迭代次数（默认2000）
        
        Returns:
            pd.Series: 资产配置权重，索引为资产代码，值为权重（总和为1）
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        # Parameters
        lambda_sharpe = float(params.get("lambda_sharpe", 0.0))
        max_weight = float(params.get("max_weight", 1.0))
        epsilon = float(params.get("epsilon", 0.01))  # 风险贡献偏离阈值
        lookback_days = int(params.get("lookback_days", 252))  # 转换为整数类型
        
        # 1. 处理lookback_days参数：限制使用的历史数据范围
        # 如果指定了lookback_days，仅使用最近N个交易日的数据计算协方差
        returns_full = compute_simple_returns(prices)
        if lookback_days is not None and lookback_days > 0 and len(returns_full) > lookback_days:
            returns = returns_full.iloc[-lookback_days:]  # 截取最近lookback_days条数据
        else:
            returns = returns_full  # 使用全部历史数据

        # 2. 计算协方差矩阵并初始化权重
        cov = compute_covariance(returns, method=params.get("cov_method", "sample"))
        assets = cov.columns
        n_assets = len(assets)
        if n_assets == 0:
            raise ValueError("No assets available after covariance computation")

        # 初始权重：等权配置，作为优化起点
        x0 = np.full(shape=(n_assets,), fill_value=1.0 / n_assets, dtype=float)

        # 3. 定义约束条件和边界
        # 权重边界：每个资产权重在 [0, max_weight] 范围内
        bounds = tuple((0.0, max_weight) for _ in range(n_assets))
        
        # 协方差矩阵值（提前提取用于约束计算）
        cov_values = cov.values
        
        # 定义绝对风险贡献计算函数：RC_i = w_i * (Σw)_i
        def compute_absolute_rc(w: np.ndarray) -> np.ndarray:
            """计算绝对风险贡献向量.
            
            Args:
                w: 权重向量
                
            Returns:
                np.ndarray: 绝对风险贡献 RC_i = w_i * (Σw)_i
            """
            sigma_w = cov_values @ w  # Σw
            return w * sigma_w  # 逐元素相乘
        
        # 基础约束：权重和为1
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
        ]
        
        # 如果设置了epsilon，添加绝对风险贡献约束
        # 约束形式：|RC_i - mean(RC)| <= epsilon
        # 等价于：mean(RC) - epsilon <= RC_i <= mean(RC) + epsilon
        if epsilon is not None and epsilon > 0:
            for i in range(n_assets):
                # 上界约束：RC_i - mean(RC) <= epsilon
                # 等价于：epsilon - (RC_i - mean(RC)) >= 0
                constraints.append({
                    "type": "ineq",
                    "fun": lambda w, idx=i: epsilon - (
                        compute_absolute_rc(w)[idx] - np.mean(compute_absolute_rc(w))
                    )
                })
                
                # 下界约束：mean(RC) - RC_i <= epsilon
                # 等价于：epsilon - (mean(RC) - RC_i) >= 0
                constraints.append({
                    "type": "ineq",
                    "fun": lambda w, idx=i: epsilon - (
                        np.mean(compute_absolute_rc(w)) - compute_absolute_rc(w)[idx]
                    )
                })

        # 4. 计算收益信号向量 S
        # 使用历史平均夏普率作为收益信号
        asset_returns = returns[assets]
        asset_mean = asset_returns.mean()
        asset_std = asset_returns.std()
        # 夏普率 = 均值/标准差，处理零标准差情况
        reward_signal = (asset_mean / asset_std.replace(0.0, np.nan)).fillna(0.0).values  # 收益信号 S

        # 5. 定义目标函数：组合方差项 - 收益增强项
        # 原型公式：min 0.5·w^T·Σ·w - λ·w^T·S
        def objective(w: np.ndarray) -> float:
            """优化目标函数（原型公式）.
            
            目标函数形式：
                f(w) = 0.5 * w^T * Σ * w - λ * w^T * S
            
            其中：
                - 第一项：组合方差（风险项）
                - 第二项：收益增强项（负号表示最大化收益）
                - λ：平衡系数，λ=0时退化为纯最小方差组合
            
            Args:
                w: 待优化的权重向量
            
            Returns:
                float: 目标函数值（越小越好）
            """
            # 辅助函数：安全地将矩阵乘法结果转换为标量
            def to_scalar(value):
                if isinstance(value, (np.ndarray, list)):
                    return float(value.item() if hasattr(value, 'item') else value[0])
                return float(value)
            
            # 1. 组合方差项：0.5 * w^T * Σ * w
            variance_term = 0.5 * to_scalar(w @ cov_values @ w)
            
            # 2. 收益增强项：-λ * w^T * S（负号表示最大化收益）
            if lambda_sharpe != 0.0:
                reward_term = -lambda_sharpe * float(np.dot(w, reward_signal))
            else:
                reward_term = 0.0
            
            return variance_term + reward_term

        # 6. 求解优化问题
        # 使用SLSQP算法（Sequential Least Squares Programming）求解约束优化
        w_opt, success, message = solve_slsqp(
            x0=x0,  # 初始权重
            objective=objective,  # 目标函数
            bounds=bounds,  # 权重边界
            constraints=constraints,  # 约束条件列表
            maxiter=int(params.get("maxiter", 2000)),  # 最大迭代次数
        )

        # 7. 后处理优化结果
        # 确保权重非负并归一化（由于数值误差，可能出现微小负值或总和不为1）
        w_opt = np.maximum(w_opt, 0.0)  # 截断负值为0
        total = float(w_opt.sum())
        if total > 0:
            w_opt = w_opt / total  # 归一化使总和为1

        weights = pd.Series(w_opt, index=assets)
        return weights
