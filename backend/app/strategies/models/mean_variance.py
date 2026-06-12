"""均值-方差模型 (Mean-Variance Optimization, MVO) 实现.

基于Markowitz现代投资组合理论，通过优化预期收益和风险的平衡来配置资产权重。

核心方法
-----------
    allocate(prices: DataFrame, **params) -> Series

关键参数
----------
- target_return: float, 目标年化收益率（如果设置，则在给定收益下最小化风险，默认0.10即10%）
- max_weight: float, 单资产最大权重（默认0.3即30%）
- min_weight: float, 单资产最小权重（默认0.0即允许空仓）
- lookback_days: int, 历史数据回看期（默认252天，约1年交易日）
- risk_free_rate: float, 无风险利率（默认0.03即3%）
- optimization_mode: str, 优化模式
    - "min_variance": 最小方差组合（忽略target_return）
    - "target_return": 在目标收益下最小化风险
    - "max_sharpe": 最大化夏普比率
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.strategies.formula.returns import compute_simple_returns
from app.strategies.formula.covariance import compute_covariance
from app.strategies.solvers.slsqp_solver import solve_slsqp
from app.strategies.models.base import BaseStrategyModel


class MeanVarianceOptimization(BaseStrategyModel):
    """均值-方差优化模型.
    
    基于Markowitz理论，在预期收益和风险之间寻找最优平衡。
    """
    
    @classmethod
    def get_param_schema(cls):
        """返回均值-方差模型的参数Schema."""
        from app.strategies.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="mean_variance",
            display_name="均值-方差模型 (MVO)",
            description="基于Markowitz现代投资组合理论，优化预期收益和风险的平衡",
            params=[
                ParamSchema(
                    name="optimization_mode",
                    label="优化模式",
                    type="select",
                    default="max_sharpe",
                    options=[
                        ("min_variance", "最小方差组合"),
                        ("target_return", "目标收益最小风险"),
                        ("max_sharpe", "最大夏普比率")
                    ],
                    description="选择优化目标：最小化风险、达到目标收益或最大化夏普比率"
                ),
                ParamSchema(
                    name="target_return",
                    label="目标年化收益率",
                    type="number",
                    default=0.10,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                    description="目标年化收益率（仅在'目标收益最小风险'模式下生效），范围：0-100%"
                ),
                ParamSchema(
                    name="lookback_days",
                    label="历史数据回看期",
                    type="number",
                    default=252,
                    min_value=20,
                    max_value=500,
                    step=1,
                    description="计算预期收益和协方差矩阵使用的历史数据天数（交易日），默认252天（约1年）"
                ),
                ParamSchema(
                    name="risk_free_rate",
                    label="无风险利率",
                    type="number",
                    default=0.03,
                    min_value=0.0,
                    max_value=0.1,
                    step=0.001,
                    description="年化无风险利率，用于计算夏普比率，默认3%（0.03）"
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
                    description="优化器的最大迭代次数，默认1000次"
                ),
            ]
        )
    
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """计算均值-方差模型的资产配置权重.
        
        核心逻辑：
        1. 基于历史价格计算预期收益率向量 E
        2. 计算协方差矩阵 Σ
        3. 根据优化模式求解：
           - min_variance: min w^T Σ w
           - target_return: min w^T Σ w, s.t. w^T E = μ*
           - max_sharpe: max (w^T E - rf) / sqrt(w^T Σ w)
        
        Args:
            prices: 资产价格历史数据，行为日期，列为资产代码
            **params: 策略参数
                - optimization_mode: 优化模式
                - target_return: 目标收益率（年化）
                - lookback_days: 历史数据回看期
                - risk_free_rate: 无风险利率
                - min_weight/max_weight: 权重边界
                - maxiter: 最大迭代次数
        
        Returns:
            pd.Series: 资产配置权重，索引为资产代码，值为权重（总和为1）
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")
        
        # 1. 获取参数
        optimization_mode = params.get("optimization_mode", "max_sharpe")
        target_return = float(params.get("target_return", 0.10))
        lookback_days = int(params.get("lookback_days", 252))  # 默认252天（约1年交易日）
        risk_free_rate = float(params.get("risk_free_rate", 0.03))  # 默认3%
        min_weight = float(params.get("min_weight", 0.0))  # 默认0（允许空仓）
        max_weight = float(params.get("max_weight", 0.3))  # 默认0.3（30%）
        maxiter = int(params.get("maxiter", 1000))  # 默认1000次
        
        # 2. 处理lookback_days参数：限制使用的历史数据范围
        if lookback_days is not None and lookback_days > 0:
            if len(prices) > lookback_days:
                prices = prices.iloc[-lookback_days:]
        
        # 3. 计算收益率和协方差矩阵
        returns = compute_simple_returns(prices)
        cov = compute_covariance(returns, method=params.get("cov_method", "sample"))
        
        assets = cov.columns
        n_assets = len(assets)
        if n_assets == 0:
            raise ValueError("No assets available after covariance computation")
        
        # 4. 计算预期收益率向量（年化）
        expected_returns = returns[assets].mean() * 252  # 日收益率 * 252 = 年化收益率
        expected_returns_values = expected_returns.values
        
        # 5. 协方差矩阵（年化）
        cov_annual = cov.values * 252  # 日协方差 * 252 = 年化协方差
        
        # 6. 检查约束条件的可行性，并在单资产或 max 过小时自动放宽以保证可解
        lower_bound = max(0.0, min_weight)
        if lower_bound * n_assets > 1.0:
            raise ValueError(
                f"约束条件不可行: min_weight={min_weight}, 资产数={n_assets}\n"
                f"所有资产的最小权重之和 ({lower_bound * n_assets:.4f}) 超过 1.0\n"
                f"建议: 降低 min_weight 至 {1.0 / n_assets:.4f} 以下"
            )
        # 保证至少存在可行解：若 max_weight * n_assets < 1，则单资产无法配满 1.0，自动将有效上限设为 1/n（单资产时为 1.0）
        effective_max_weight = max_weight
        if max_weight * n_assets < 1.0:
            effective_max_weight = 1.0 / n_assets

        # 7. 设置权重边界和基础约束
        bounds = tuple((lower_bound, effective_max_weight) for _ in range(n_assets))
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},  # 权重和为1
        ]
        
        # 8. 初始权重：等权配置
        x0 = np.full(shape=(n_assets,), fill_value=1.0 / n_assets, dtype=float)
        
        # 辅助函数：安全地将矩阵乘法结果转换为标量
        def to_scalar(value):
            if isinstance(value, (np.ndarray, list)):
                return float(value.item() if hasattr(value, 'item') else value[0])
            return float(value)
        
        # 9. 根据优化模式定义目标函数和约束
        if optimization_mode == "min_variance":
            # 最小方差组合：min w^T Σ w
            def objective(w: np.ndarray) -> float:
                return to_scalar(w @ cov_annual @ w)
        
        elif optimization_mode == "target_return":
            # 检查资产数量是否足够
            # target_return模式需要2个等式约束：权重和为1 + 目标收益约束
            # 如果资产数量少于2，约束条件会超过独立变量数量
            if n_assets < 2:
                # 提供更详细的错误信息，包括可能的解决方案
                error_msg = (
                    f"目标收益模式需要至少2个资产，当前只有 {n_assets} 个资产。\n"
                    f"约束条件数量（2个等式约束：权重和=1 + 目标收益约束）超过了独立变量数量（{n_assets}个权重）。\n\n"
                    f"可能的原因：\n"
                    f"1. 资产选择器选出的资产数量不足（如果启用了资产选择）\n"
                    f"2. 历史数据不足导致部分资产被过滤\n"
                    f"3. 资产池配置的资产数量本身就少于2个\n\n"
                    f"解决方案：\n"
                    f"1. 切换到'最小方差组合'或'最大夏普比率'模式（这些模式只需要1个等式约束）\n"
                    f"2. 增加资产选择数量（如果启用了资产选择）\n"
                    f"3. 增加资产池中的资产数量\n"
                    f"4. 检查历史数据是否完整"
                )
                raise ValueError(error_msg)
            
            # 检查预期收益率是否相同（如果相同，目标收益约束可能与权重和约束线性相关）
            expected_returns_std = np.std(expected_returns_values)
            if expected_returns_std < 1e-6:
                # 所有资产的预期收益率几乎相同
                # 在这种情况下，目标收益约束可能与权重和约束冲突
                avg_return = float(np.mean(expected_returns_values))
                if abs(avg_return - target_return) > 1e-6:
                    raise ValueError(
                        f"所有资产的预期收益率相同 ({avg_return:.4f})，但目标收益率 ({target_return:.4f}) 不同。\n"
                        f"无法满足目标收益约束。\n"
                        f"建议：将目标收益率设置为 {avg_return:.4f}，或切换到其他优化模式。"
                    )
                # 如果目标收益率与平均收益率相同，可以移除目标收益约束（因为权重和约束已经足够）
                # 但为了保持一致性，我们仍然保留约束，只是给出警告
                import warnings
                warnings.warn(
                    f"所有资产的预期收益率相同 ({avg_return:.4f})，目标收益约束可能冗余。"
                )
            
            # 检查目标收益率是否在可行范围内
            min_return = float(np.min(expected_returns_values))
            max_return = float(np.max(expected_returns_values))
            if target_return < min_return or target_return > max_return:
                raise ValueError(
                    f"目标收益率 ({target_return:.4f}) 超出可行范围 [{min_return:.4f}, {max_return:.4f}]\n"
                    f"无法满足目标收益约束。\n"
                    f"建议：将目标收益率调整到可行范围内，或切换到其他优化模式。"
                )
            
            # 目标收益最小风险：min w^T Σ w, s.t. w^T E = target_return
            def objective(w: np.ndarray) -> float:
                return to_scalar(w @ cov_annual @ w)
            
            # 添加收益率约束
            constraints.append({
                "type": "eq",
                "fun": lambda w: float(np.dot(w, expected_returns_values)) - target_return
            })
        
        elif optimization_mode == "max_sharpe":
            # 最大化夏普比率：max (w^T E - rf) / sqrt(w^T Σ w)
            # 等价于：min -[(w^T E - rf) / sqrt(w^T Σ w)]
            def objective(w: np.ndarray) -> float:
                portfolio_return = float(np.dot(w, expected_returns_values))
                portfolio_variance = to_scalar(w @ cov_annual @ w)
                portfolio_std = np.sqrt(max(portfolio_variance, 1e-12))
                sharpe = (portfolio_return - risk_free_rate) / portfolio_std
                return -sharpe  # 最小化负夏普比率 = 最大化夏普比率
        
        else:
            raise ValueError(f"不支持的优化模式: {optimization_mode}")
        
        # 10. 求解优化问题
        w_opt, success, message = solve_slsqp(
            x0=x0,
            objective=objective,
            bounds=bounds,
            constraints=constraints,
            maxiter=maxiter,
        )
        
        # 11. 检查优化结果
        if not success:
            # 提供更详细的错误信息
            error_details = [
                f"均值-方差优化失败: {message}",
                f"优化模式: {optimization_mode}",
                f"资产数量: {n_assets}",
                f"约束条件数量: {len(constraints)}",
            ]
            
            if optimization_mode == "target_return":
                min_return = float(np.min(expected_returns_values))
                max_return = float(np.max(expected_returns_values))
                error_details.extend([
                    f"目标收益率: {target_return:.4f}",
                    f"预期收益率范围: [{min_return:.4f}, {max_return:.4f}]",
                ])
                if "More equality constraints" in message or "equality constraints" in message.lower():
                    error_details.append(
                        f"\n注意：约束条件数量（{len(constraints)}）超过了独立变量数量（{n_assets}）。"
                    )
            
            error_details.append("\n建议：")
            error_details.append("1. 检查资产数量是否足够（target_return模式需要至少2个资产）")
            if optimization_mode == "target_return":
                error_details.append("2. 检查目标收益率是否在可行范围内")
                error_details.append("3. 如果启用了资产选择，检查选出的资产数量是否足够")
            error_details.append("4. 切换到其他优化模式（如min_variance或max_sharpe）")
            error_details.append("5. 增加最大迭代次数")
            error_details.append("6. 检查数据质量（是否有NaN或异常值）")
            
            raise RuntimeError("\n".join(error_details))
        
        # 12. 归一化权重
        w_opt = np.maximum(w_opt, 0.0)
        total = float(w_opt.sum())
        if total > 0:
            w_opt = w_opt / total
        
        weights = pd.Series(w_opt, index=assets)
        return weights
