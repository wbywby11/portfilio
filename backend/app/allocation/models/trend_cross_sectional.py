"""趋势截面动量策略（纯权重计算层）。

趋势跟踪 + 截面动量双通道信号，按权重混合后归一化输出。
波动率控制委托给 DualWindowVolMonitor。
"""

import pandas as pd

from app.allocation.models.base import BaseStrategyModel


class TrendCrossSectionalStrategy(BaseStrategyModel):
    """趋势截面动量策略（纯权重传递层）.

    趋势跟踪 + 截面动量双通道信号混合后归一化输出。
    波动率控制委托给 DualWindowVolMonitor。
    """

    @classmethod
    def get_param_schema(cls):
        """返回策略的参数Schema — 只包含 allocator 自有参数.

        TF/CS 的信号计算参数（tf_lookback, tf_threshold, cs_lookback_months）
        属于选择器层，由前端「资产选择」区域配置。
        """
        from app.allocation.models.param_schema import (
            StrategyParamSchema, ParamSchema, vol_targeting_param_group,
            model_level_param_group,
        )

        return StrategyParamSchema(
            strategy_type="trend_cross_sectional",
            display_name="趋势-截面复合",
            description=(
                "趋势跟踪+截面动量双信号复合，按权重混合后归一化输出，支持多空交易。"
                "信号参数请在「资产选择」区域配置。"
            ),
            composition={
                "selector": None,
                "allocator": "trend_cross_sectional",
                "controller": "dual_window_vol",
                "schedule": {"rebalance_freq": "daily", "execution_delay": 0},
                # 多信号复合配置（由 Pipeline._run_multi_signal 执行）
                "multi_signal": [
                    {"selector": "trend_following", "weight_param": "combo_weight_tf", "weight": 0.5},
                    {"selector": "cross_sectional_long_short", "weight_param": "combo_weight_cs", "weight": 0.5},
                ],
            },
            params=[
                ParamSchema(
                    name="combo_weight_tf", label="趋势跟踪复合权重",
                    type="slider", default=0.5,
                    min_value=0.0, max_value=1.0, step=0.05,
                    description="趋势跟踪子通道权重（与截面动量权重之和应等于1）",
                ),
                ParamSchema(
                    name="combo_weight_cs", label="截面动量复合权重",
                    type="slider", default=0.5,
                    min_value=0.0, max_value=1.0, step=0.05,
                    description="截面动量子通道权重（与趋势跟踪权重之和应等于1）",
                ),
                ParamSchema(
                    name="target_vol", label="目标波动率",
                    type="number", default=0.03,
                    min_value=0.001, max_value=0.50, step=0.005,
                    description="年化目标波动率，传递给控制器用于权重缩放",
                ),
                ParamSchema(
                    name="signal_normalize", label="混合权重归一化",
                    type="boolean", default=True,
                    description=(
                        "开启：混合后权重归一化到 sum(|w|)=1；"
                        "关闭：保留复合权重原始比例，总敞口≤两通道权重之和"
                        "（对齐银河 GCMI 原型口径时关闭）"
                    ),
                ),
                ParamSchema(
                    name="allow_short", label="允许做空",
                    type="boolean", default=True,
                    description=(
                        "趋势-截面复合天然含多空权重（负权重做空）；"
                        "关闭后风控层会把负权重截断为 0，仅保留多头敞口"
                    ),
                ),
                # ━━━ 波动率定标（引擎收益层，vol_targeting_enabled 触发） ━━━
                *vol_targeting_param_group(),
                # ━━━ 模型级通用执行参数（调度/数据源/引擎层消费） ━━━
                *model_level_param_group(),
            ],
            # 信号时点：用执行日当日收盘价算信号并当日收盘成交（决策与成交同价，
            # 不构成前视）。对齐 GMSI 2.0 原型 TF 通道 shift(1) 语义：
            # 原型 tf_weights(t)（含 t 日收盘）作用于 t+1 日收益，等价于
            # 引擎在 t 日用含 t 日 bar 的历史算权重、t 日收盘建仓、t+1 日生效。
            signal_timing="execution_bar",
        )

    def get_execution_schedule(self):
        """声明执行调度：日频调仓，当日收盘成交（信号含当日收盘价）."""
        return {
            "rebalance_freq": "daily",
            "execution_delay": 0,
        }

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """接收混合信号权重，归一化输出。

        本方法不生成任何信号，信号混合由选择模块完成。

        Args:
            prices: Date × Ticker 结算价矩阵
            **params:
                _signal_weights: 多信号混合后的权重字典
                signal_normalize: 是否归一化（默认 True）

        Returns:
            Series, index=Ticker, value=权重（支持负值表示做空）
        """
        if prices.empty:
            return pd.Series(dtype=float)

        signal_weights = params.get("_signal_weights")
        if not signal_weights:
            # 本策略的 composition 硬编码了 multi_signal（trend_following +
            # cross_sectional_long_short），_signal_weights 必然由 Pipeline 注入。
            # 缺失只可能是配置或执行链路故障，不能退化为等权：
            # 等权结果会被当成「趋势-截面复合」的绩效展示，掩盖信号未生效的事实。
            raise ValueError(
                "趋势-截面复合策略未收到复合信号（_signal_weights 为空）。\n"
                "本策略依赖 composition.multi_signal 由 Pipeline 生成信号，"
                "请检查策略配置中的 multi_signal 是否完整、"
                "以及上游选择器（trend_following / cross_sectional_long_short）是否执行成功"
            )

        weights = pd.Series(signal_weights).reindex(prices.columns).fillna(0)

        # 归一化到 sum(|w|) = 1
        if params.get("signal_normalize", True):
            abs_sum = weights.abs().sum()
            if abs_sum > 0:
                weights = weights / abs_sum

        return weights
