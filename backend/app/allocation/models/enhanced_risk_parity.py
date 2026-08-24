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
- epsilon: float, 风险贡献份额偏离阈值 (默认0.01)
          约束风险贡献份额 RC%_i = w_i·(Σw)_i / (w^TΣw) 在 [1/N ± epsilon] 范围内
- lookback_days: int, 历史数据回看期 (默认252天)
- cov_method: str, 协方差计算方法 (默认"sample")
- maxiter: int, 优化器最大迭代次数 (默认2000)

量纲约定
----------
协方差与收益信号统一按年化口径参与优化（ANNUALIZATION_FACTOR=260），
与 app.analysis.performance 的绩效内核一致。这一点是必需的而非美观问题：
日频协方差下目标函数值约 1e-5，与 SLSQP 默认收敛容差 ftol=1e-6 同量级，
优化器会在第 1 次迭代即判定收敛并原样返回等权初值（假收敛）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.formula.returns import compute_simple_returns
from app.formula.covariance import compute_covariance
from app.solvers.slsqp_solver import solve_slsqp
from app.allocation.models.base import BaseStrategyModel

# 年化因子：与 app.analysis.performance.PERIODS_PER_YEAR 保持同一口径（260）
ANNUALIZATION_FACTOR: int = 260


class CovarianceSharpeOptimization(BaseStrategyModel):
    """协方差-夏普优化模型 (CSO).
    
    这是一个原创的大类资产配置策略，通过双目标优化框架，
    同时追求风险的均等分散和收益的Sharpe增强。
    """
    @classmethod
    def get_param_schema(cls):
        """返回协方差-夏普优化模型的参数Schema."""
        from app.allocation.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="cso",  # Covariance-Sharpe Optimization
            display_name="协方差-夏普优化",
            description="双目标优化：最小化组合方差同时引入Sharpe增强项，原创大类资产配置框架",
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
                    label="风险贡献份额偏离阈值",
                    type="number",
                    default=0.01,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.001,
                    description="允许各资产风险贡献份额偏离均值 1/N 的最大幅度（如 0.01 = 1个百分点），值越小风险分散越均匀"
                ),
                ParamSchema(
                    name="lambda_sharpe",
                    label="收益增强系数",
                    type="number",
                    default=0.0,
                    min_value=0.0,
                    max_value=0.1,
                    step=0.005,
                    description="控制组合方差与收益优化的平衡，0表示纯最小方差组合；有效区约 0.01~0.05，≥ 0.1 会向单一高夏普资产集中"
                ),
                ParamSchema(
                    name="lookback_days",
                    label="历史数据回看期",
                    type="number",
                    default=252,
                    min_value=20,
                    max_value=1000,
                    step=10,
                    description="计算协方差矩阵使用的历史数据天数（交易日），默认252天约1年"
                ),
                ParamSchema(
                    name="maxiter",
                    label="最大迭代次数",
                    type="number",
                    default=2000,
                    min_value=100,
                    max_value=20000,
                    step=100,
                    description="优化器的最大迭代次数",
                    group="advanced",
                ),
                ParamSchema(
                    name="cov_method",
                    label="协方差估计方法",
                    type="select",
                    default="sample",
                    options=[("sample", "样本协方差"), ("ledoit_wolf", "Ledoit-Wolf 收缩估计")],
                    description="协方差矩阵估计方法，样本较少时自动切换为 Ledoit-Wolf",
                    group="advanced",
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
                - max_weight: 单资产最大权重（默认0.5，与参数 Schema 声明一致）
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
        max_weight = float(params.get("max_weight", 0.5))
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
        # 年化：使目标函数脱离 SLSQP 收敛容差量级，避免第 1 次迭代即假收敛
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

        # 年化协方差矩阵值（提前提取用于约束计算）
        cov_values = cov.values * ANNUALIZATION_FACTOR

        # 定义风险贡献份额计算函数：RC%_i = w_i·(Σw)_i / (w^TΣw)
        def compute_rc_share(w: np.ndarray) -> np.ndarray:
            """计算风险贡献份额向量（无量纲，各分量之和为 1）.

            使用份额而非绝对风险贡献，是为了让 epsilon 具备与资产数无关、
            与协方差年化口径无关的固定语义（偏离 1/N 的百分点数）。
            绝对风险贡献量级随协方差口径漂移（日频约 1e-6），
            与 epsilon 默认值 0.01 相差三个数量级，会使约束恒成立而完全失效。

            Args:
                w: 权重向量

            Returns:
                np.ndarray: 风险贡献份额 RC%_i
            """
            port_var = float(w @ cov_values @ w)
            if port_var < 1e-16:
                return np.full_like(w, 1.0 / len(w))
            return w * (cov_values @ w) / port_var

        # 基础约束：权重和为1
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
        ]

        # 如果设置了epsilon，添加风险贡献份额约束
        # 约束形式：|RC%_i - 1/N| <= epsilon
        # 等价于：1/N - epsilon <= RC%_i <= 1/N + epsilon
        if epsilon is not None and epsilon > 0:
            target_share = 1.0 / n_assets
            for i in range(n_assets):
                # 上界约束：RC%_i - 1/N <= epsilon
                constraints.append({
                    "type": "ineq",
                    "fun": lambda w, idx=i: epsilon - (compute_rc_share(w)[idx] - target_share)
                })

                # 下界约束：1/N - RC%_i <= epsilon
                constraints.append({
                    "type": "ineq",
                    "fun": lambda w, idx=i: epsilon - (target_share - compute_rc_share(w)[idx])
                })

        # 4. 计算收益信号向量 S
        # 使用年化夏普率作为收益信号，与年化方差项同口径，
        # 否则 lambda_sharpe 的取值无法在两项之间形成可解释的权衡
        asset_returns = returns[assets]
        asset_mean = asset_returns.mean()
        asset_std = asset_returns.std()
        # 年化夏普率 = (日均值/日标准差) × √260，处理零标准差情况
        reward_signal = (
            (asset_mean / asset_std.replace(0.0, np.nan)).fillna(0.0)
            * np.sqrt(ANNUALIZATION_FACTOR)
        ).values  # 收益信号 S

        # 5. 定义目标函数：组合方差项 - 收益增强项
        # 原型公式：min 0.5·w^T·Σ·w - λ·w^T·S（Σ 与 S 均为年化口径）
        def objective(w: np.ndarray) -> float:
            """优化目标函数（原型公式）.
            
            目标函数形式：
                f(w) = 0.5 * w^T * Σ * w - λ * w^T * S
            
            其中：
                - 第一项：组合方差（风险项，年化）
                - 第二项：收益增强项（负号表示最大化收益，年化夏普）
                - λ：平衡系数，λ=0时退化为纯最小方差组合
            
            Args:
                w: 待优化的权重向量
            
            Returns:
                float: 目标函数值（越小越好）
            """
            # 1. 组合方差项：0.5 * w^T * Σ * w
            variance_term = 0.5 * float(w @ cov_values @ w)
            
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

        # 7. 检查优化结果
        if not success:
            raise RuntimeError(
                f"协方差-夏普优化失败: {message}\n"
                f"lambda_sharpe={lambda_sharpe}, epsilon={epsilon}, "
                f"资产数={n_assets}\n"
                "请检查数据质量、参数配置或增加最大迭代次数"
            )

        # 8. 后处理优化结果
        # 确保权重非负并归一化（由于数值误差，可能出现微小负值或总和不为1）
        w_opt = np.maximum(w_opt, 0.0)  # 截断负值为0
        total = float(w_opt.sum())
        if total > 0:
            w_opt = w_opt / total  # 归一化使总和为1

        weights = pd.Series(w_opt, index=assets)
        return weights
