"""目标波动率策略 (Target Volatility Strategy) 实现.

这是一个非优化模型，核心特点：
1. 风险平价初始权重：根据波动率倒数分配权重
2. 目标波动率控制：通过缩放因子实现目标波动率（默认5%）
3. 三重约束：波动率约束、杠杆约束、单资产权重约束
4. 波动率重置机制：当波动率超过阈值时触发权重重置

MVP版本（阶段1）：
- 使用给定资产池（暂不实现动量筛选）
- 实现风险平价初始权重
- 实现波动率约束缩放
- 实现波动率重置计算
- 简化约束条件

核心方法
-----------
    allocate(prices: DataFrame, **params) -> Series
    compute_volatility_reset_weights(current_weights: Series, prices: DataFrame, **params) -> Series

关键参数
----------
- target_vol: float, 目标年化波动率（默认0.05 = 5%）
- vol_reset_threshold: float, 波动率重置阈值（默认0.06 = 6%）
- max_total_leverage: float, 最大杠杆倍数（默认4.0）
- max_weight: float, 单资产最大权重（默认0.3）
- vol_windows: list, 波动率计算窗口（默认[22, 65, 130]）
- min_history_days: int, 最小历史数据要求（默认250天）
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any

from app.strategies.formula.returns import compute_simple_returns
from app.strategies.formula.rolling_volatility import (
    compute_asset_rolling_volatility,
    compute_portfolio_volatility
)
from app.strategies.models.base import BaseStrategyModel


class TargetVolatilityStrategy(BaseStrategyModel):
    """目标波动率策略（非优化模型）.
    
    核心思想：
    1. 根据资产波动率倒数分配初始权重（风险平价思想）
    2. 计算模拟组合波动率
    3. 通过缩放因子调整权重以达到目标波动率
    """
    
    @classmethod
    def get_param_schema(cls):
        """返回目标波动率策略的参数Schema."""
        from app.strategies.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="target_volatility",
            display_name="目标波动率策略",
            description="基于风险平价和目标波动率控制的非优化资产配置策略（无需优化求解器）",
            monitoring_metrics=[
                {"name": "portfolio_volatility", "label": "组合波动率", "threshold_param": "vol_reset_threshold"}
            ],
            params=[
                ParamSchema(
                    name="target_vol",
                    label="目标年化波动率",
                    type="number",
                    default=0.05,
                    min_value=0.01,
                    max_value=0.15,
                    step=0.005,
                    description="组合目标波动率（默认5%），较低值更保守"
                ),
                ParamSchema(
                    name="max_total_leverage",
                    label="最大杠杆倍数",
                    type="number",
                    default=4.0,
                    min_value=1.0,
                    max_value=10.0,
                    step=0.5,
                    description="组合最大杠杆限制，权重和不超过此倍数"
                ),
                ParamSchema(
                    name="max_weight",
                    label="单资产最大权重",
                    type="number",
                    default=0.3,
                    min_value=0.1,
                    max_value=1.0,
                    step=0.05,
                    description="限制单个资产的最大持仓权重，防止过度集中"
                ),
                ParamSchema(
                    name="min_history_days",
                    label="最小历史数据要求",
                    type="number",
                    default=250,
                    min_value=100,
                    max_value=500,
                    step=10,
                    description="资产进入计算的最小交易日数要求"
                ),
                ParamSchema(
                    name="vol_reset_threshold",
                    label="波动率重置阈值",
                    type="number",
                    default=0.06,
                    min_value=0.03,
                    max_value=0.10,
                    step=0.005,
                    description="触发波动率重置的阈值（默认6%），当组合波动率超过此值时触发权重缩放"
                ),
                ParamSchema(
                    name="lookback_days",
                    label="历史数据回看期",
                    type="number",
                    default=260,
                    min_value=130,
                    max_value=520,
                    step=10,
                    description="计算波动率使用的历史数据长度（交易日）"
                ),
            ]
        )
    
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """计算目标波动率策略的资产配置权重.
        
        MVP版本流程：
        1. 筛选有效资产（满足最小历史数据要求）
        2. 计算每个资产的已实现波动率
        3. 计算初始权重（风险平价：w_init = b * σ_target / σ_realized）
        4. 计算模拟组合波动率
        5. 应用三重约束缩放
        
        Args:
            prices: 资产价格历史数据，行为日期，列为资产代码
            **params: 策略参数
                - target_vol: 目标年化波动率（默认0.05）
                - max_total_leverage: 最大杠杆倍数（默认4.0）
                - max_weight: 单资产最大权重（默认0.3）
                - min_history_days: 最小历史数据要求（默认250）
                - lookback_days: 历史数据回看期（默认260）
        
        Returns:
            pd.Series: 资产配置权重，索引为资产代码，值为权重
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")
        
        # 1. 获取参数
        target_vol = float(params.get("target_vol", 0.05))
        max_total_leverage = float(params.get("max_total_leverage", 4.0))
        max_weight = float(params.get("max_weight", 0.3))
        min_history_days = int(params.get("min_history_days", 250))
        lookback_days = int(params.get("lookback_days", 260))
        
        # 波动率计算窗口（固定为文档中的值）
        vol_windows = [22, 65, 130]
        
        # 2. 处理lookback_days：限制使用的历史数据范围
        if lookback_days > 0 and len(prices) > lookback_days:
            prices = prices.iloc[-lookback_days:]
        
        # 3. 筛选有效资产（满足最小历史数据要求）
        valid_assets = []
        for asset in prices.columns:
            asset_prices = prices[asset].dropna()
            if len(asset_prices) >= min_history_days:
                valid_assets.append(asset)
        
        if not valid_assets:
            raise ValueError(
                f"没有资产满足最小历史数据要求（{min_history_days}天），"
                f"请降低min_history_days参数或提供更长的价格数据"
            )
        
        # 只保留有效资产
        prices = prices[valid_assets]
        n_assets = len(valid_assets)
        
        # 4. 计算收益率
        returns = compute_simple_returns(prices)
        
        if returns.empty or len(returns) < max(vol_windows):
            raise ValueError(
                f"收益率数据不足以计算波动率（需要至少{max(vol_windows)}天），"
                f"实际只有{len(returns)}天"
            )
        
        # 5. 计算每个资产的已实现波动率
        asset_vols = compute_asset_rolling_volatility(
            prices, 
            windows=vol_windows,
            annualization_factor=260
        )
        
        # 检查是否有零波动率
        if (asset_vols == 0).any():
            zero_vol_assets = asset_vols[asset_vols == 0].index.tolist()
            raise ValueError(
                f"以下资产波动率为0，无法分配权重：{zero_vol_assets}，"
                f"请检查价格数据或排除这些资产"
            )
        
        # 6. 计算风险预算占比（MVP版本：等权）
        risk_budgets = pd.Series(1.0 / n_assets, index=valid_assets)
        
        # 7. 计算初始权重：w_init = b * (σ_target / σ_realized)
        # 这是风险平价思想：波动率高的资产分配小权重，波动率低的资产分配大权重
        init_weights = risk_budgets * (target_vol / asset_vols)
        
        # 8. 计算模拟组合波动率
        portfolio_vol = compute_portfolio_volatility(
            returns,
            init_weights,
            windows=vol_windows,
            annualization_factor=260
        )
        
        if portfolio_vol == 0:
            raise ValueError("组合波动率为0，无法计算缩放因子")
        
        # 9. 应用三重约束缩放
        final_weights = self._apply_constraints(
            init_weights=init_weights,
            portfolio_vol=portfolio_vol,
            target_vol=target_vol,
            max_total_leverage=max_total_leverage,
            max_weight=max_weight
        )
        
        # 10. 归一化（确保权重和为1）
        total = float(final_weights.sum())
        if total > 0:
            final_weights = final_weights / total
        else:
            # 如果所有权重都被约束为0，回退到等权
            final_weights = pd.Series(1.0 / n_assets, index=valid_assets)
        
        return final_weights
    
    def _apply_constraints(
        self,
        init_weights: pd.Series,
        portfolio_vol: float,
        target_vol: float,
        max_total_leverage: float,
        max_weight: float
    ) -> pd.Series:
        """应用三重约束缩放.
        
        根据文档公式：
        w_final = w_init * min(
            σ_target / σ_realized_port,  # 约束1: 波动率约束
            MaxTotalW / Σw_init,         # 约束2: 杠杆约束
            w_max / w_init               # 约束3: 单资产权重约束
        )
        
        Args:
            init_weights: 初始权重
            portfolio_vol: 组合已实现波动率
            target_vol: 目标波动率
            max_total_leverage: 最大杠杆倍数
            max_weight: 单资产最大权重
        
        Returns:
            pd.Series: 最终权重
        """
        # 约束1: 波动率约束
        vol_scale = target_vol / portfolio_vol if portfolio_vol > 0 else 1.0
        
        # 约束2: 杠杆约束
        total_weight = float(init_weights.sum())
        leverage_scale = max_total_leverage / total_weight if total_weight > 0 else 1.0
        
        # 约束3: 单资产权重约束（找到最严格的限制）
        # 对于每个资产：scale_i = w_max / w_init_i
        # 取所有资产中最小的scale
        weight_scales = max_weight / init_weights
        min_weight_scale = float(weight_scales.min())
        
        # 取三个约束中的最小值
        scale_factor = min(vol_scale, leverage_scale, min_weight_scale)
        
        # 应用缩放因子
        final_weights = init_weights * scale_factor
        
        return final_weights
    
    def compute_volatility_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> pd.Series | None:
        """计算波动率重置后的目标权重.
        
        这是一个独立的方法，用于在回测过程中触发波动率重置时调用。
        
        算法流程（基于文档）：
        1. 使用当前实际权重构建模拟组合历史收益率序列
        2. 计算多窗口年化波动率并取最大值作为触发信号
        3. 如果波动率 >= 阈值，计算重置权重
        4. 重置公式：VW = (target_vol / vol_trigger) × current_weight
        
        Args:
            current_weights: 当前实际持仓权重（pd.Series，索引为资产代码）
            prices: 资产价格历史数据（用于计算波动率）
            **params: 策略参数
                - target_vol: 目标年化波动率（默认0.05）
                - vol_reset_threshold: 重置阈值（默认0.06）
                - vol_windows: 波动率窗口（默认[22, 65, 130]）
                - enable_vol_reset: 是否启用波动率阈值重置（默认True）
        
        Returns:
            pd.Series | None: 重置后的目标权重，如果不需要重置或未启用则返回None/current_weights
        
        注意：
            - 这个方法只负责计算，不做触发判断
            - 触发判断应该在回测引擎中完成
        """
        if not params.get("enable_vol_reset", True):
            return current_weights
        # 获取参数
        target_vol = float(params.get("target_vol", 0.05))
        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))
        vol_windows = params.get("vol_windows", [22, 65, 130])
        # 优先使用引擎传入的信号日 VolTrigger（编制规则 4.3.4：用信号日波动率做缩放）
        vol_trigger_from_engine = params.get("_vol_trigger") or params.get("vol_trigger")
        if vol_trigger_from_engine is not None and vol_trigger_from_engine > 0:
            scale_factor = target_vol / float(vol_trigger_from_engine)
            return current_weights * scale_factor
        if prices.empty or current_weights.empty:
            return None
        
        # 步骤1：构建模拟组合历史收益率序列
        # IR_s = Σ(w_c × (TR_s / TR_{s-1} - 1))
        returns = compute_simple_returns(prices)
        
        # 确保权重和收益率的资产对齐
        common_assets = returns.columns.intersection(current_weights.index)
        if len(common_assets) == 0:
            return None
        
        aligned_weights = current_weights.reindex(common_assets).fillna(0)
        aligned_returns = returns[common_assets]
        
        # 计算组合收益率序列
        portfolio_returns = (aligned_returns * aligned_weights).sum(axis=1)
        
        # 步骤2：计算多窗口波动率并取最大值
        # σ_n = sqrt(260/(n-1) × Σ(r - mean(r))^2)
        vol_signals = []
        for window in vol_windows:
            if len(portfolio_returns) >= window:
                recent_returns = portfolio_returns.iloc[-window:]
                # 计算年化波动率
                vol = recent_returns.std() * np.sqrt(260)
                vol_signals.append(vol)
        
        if not vol_signals:
            return None
        
        # 取最大值作为波动率信号
        vol_trigger = max(vol_signals)
        
        # 步骤3：判断是否需要重置（这里只做计算，实际触发由引擎控制）
        # 为了让这个方法独立可用，我们返回信息
        if vol_trigger < vol_reset_threshold:
            # 波动率未超过阈值，不需要重置
            return None
        
        # 步骤4：计算重置权重
        # VW_c = (target_vol / vol_trigger) × current_weight
        scale_factor = target_vol / vol_trigger
        reset_weights = current_weights * scale_factor
        
        return reset_weights

    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> dict[str, Any]:
        """计算策略监控指标。"""
        # 计算当前组合波动率
        # 复用已有的 check_volatility_trigger 逻辑，但这里只取值
        _, vol_trigger = self.check_volatility_trigger(current_weights, prices, **params)
        
        return {
            "portfolio_volatility": vol_trigger,
        }

    def check_volatility_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params
    ) -> tuple[bool, float]:
        """检查是否触发波动率重置.
        
        这是一个辅助方法，用于在回测引擎中每日监控波动率。
        
        Args:
            current_weights: 当前实际持仓权重
            prices: 资产价格历史数据
            **params: 策略参数
        
        Returns:
            tuple: (是否触发, 当前波动率信号值)
                - 是否触发: bool
                - 波动率信号值: float（年化波动率）
        """
        if not params.get("enable_vol_reset", True):
            return False, 0.0
        vol_reset_threshold = float(params.get("vol_reset_threshold", 0.06))
        vol_windows = params.get("vol_windows", [22, 65, 130])
        
        if prices.empty or current_weights.empty:
            return False, 0.0
        
        # 构建组合收益率序列
        returns = compute_simple_returns(prices)
        common_assets = returns.columns.intersection(current_weights.index)
        
        if len(common_assets) == 0:
            return False, 0.0
        
        aligned_weights = current_weights.reindex(common_assets).fillna(0)
        aligned_returns = returns[common_assets]
        portfolio_returns = (aligned_returns * aligned_weights).sum(axis=1)
        
        # 计算多窗口波动率
        vol_signals = []
        for window in vol_windows:
            if len(portfolio_returns) >= window:
                recent_returns = portfolio_returns.iloc[-window:]
                vol = recent_returns.std() * np.sqrt(260)
                vol_signals.append(vol)
        
        if not vol_signals:
            return False, 0.0
        
        vol_trigger = max(vol_signals)
        is_triggered = vol_trigger >= vol_reset_threshold
        
        return is_triggered, vol_trigger
