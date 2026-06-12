"""主观配置策略（Manual Allocation Strategy）.

允许用户直接输入资产权重，无需优化计算。
适用于：
- 主观判断配置
- 基准组合构建
- 简单固定权重策略
"""

import pandas as pd
from app.strategies.models.base import BaseStrategyModel


class ManualAllocationStrategy(BaseStrategyModel):
    """主观配置策略.
    
    用户直接指定每个资产的权重，策略不做任何计算或优化。
    主要用于：
    1. 测试自定义配置方案
    2. 构建基准组合
    3. 实现固定权重策略
    """
    
    @classmethod
    def get_param_schema(cls):
        """返回参数Schema."""
        from app.strategies.models.param_schema import StrategyParamSchema, ParamSchema
        
        return StrategyParamSchema(
            strategy_type="manual_allocation",
            display_name="主观配置策略",
            description="用户直接输入资产权重，适用于主观判断或固定配置方案",
            params=[
                ParamSchema(
                    name="manual_weights",
                    label="资产权重配置",
                    type="dict",
                    default={},
                    description="资产代码到权重的映射，例如 {'000300.SH': 0.5, 'T.CFE': 0.5}"
                ),
                ParamSchema(
                    name="max_leverage",
                    label="最大杠杆",
                    type="number",
                    default=4,
                    min_value=1,
                    max_value=10,
                    step=0.5,
                    description="总仓位权重上限（倍数），如 4 表示 400%，初始权重、预设权重与步进调仓权重均不得超过此杠杆"
                ),
                ParamSchema(
                    name="auto_normalize",
                    label="自动归一化",
                    type="checkbox",
                    default=True,
                    description="如果权重总和不为1，是否自动归一化（推荐开启）"
                ),
                ParamSchema(
                    name="fill_missing",
                    label="未配置资产权重",
                    type="select",
                    default="zero",
                    options=[
                        ("zero", "设为0"),
                        ("equal", "等权分配剩余权重"),
                        ("error", "报错提示")
                    ],
                    description="对于未配置权重的资产如何处理"
                ),
            ]
        )
    
    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """执行主观配置.
        
        Args:
            prices: 价格数据（仅用于获取资产列表，不参与计算）
            **params: 策略参数
                - manual_weights: dict, 资产权重配置
                - auto_normalize: bool, 是否自动归一化
                - fill_missing: str, 未配置资产的处理方式
        
        Returns:
            权重Series
        """
        if prices.empty:
            raise ValueError("prices 数据为空")
        
        # 获取参数
        manual_weights = params.get("manual_weights", {})
        
        # 防御性处理：如果 manual_weights 是字符串，尝试解析为字典
        if isinstance(manual_weights, str):
            import json
            try:
                # 兼容处理单引号
                fixed_str = manual_weights.replace("'", '"')
                manual_weights = json.loads(fixed_str)
            except Exception:
                # 如果解析失败，可能是由于原本就是错误的格式，保持原样让后面逻辑报错或尝试修复
                pass
        
        # 确保 manual_weights 是字典
        if not isinstance(manual_weights, dict):
            try:
                manual_weights = dict(manual_weights)
            except (TypeError, ValueError):
                raise ValueError(f"manual_weights 参数格式错误，期望字典类型，实际收到: {type(manual_weights).__name__}")
                
        auto_normalize = params.get("auto_normalize", True)
        fill_missing = params.get("fill_missing", "zero")
        
        if not manual_weights:
            raise ValueError("manual_weights 参数为空，请配置至少一个资产的权重")
        
        # 获取所有资产列表
        all_assets = prices.columns.tolist()
        
        # 构建权重Series
        weights_dict = {}
        
        for asset in all_assets:
            if asset in manual_weights:
                # 已配置的资产
                weights_dict[asset] = float(manual_weights[asset])
            else:
                # 未配置的资产
                if fill_missing == "zero":
                    weights_dict[asset] = 0.0
                elif fill_missing == "error":
                    raise ValueError(f"资产 {asset} 未配置权重，请在 manual_weights 中指定")
                # "equal" 模式稍后处理
        
        weights = pd.Series(weights_dict)
        
        # 处理 "equal" 模式
        if fill_missing == "equal":
            # 计算已配置资产的权重总和
            configured_sum = sum(manual_weights.values())
            
            # 剩余权重
            remaining = 1.0 - configured_sum
            
            # 未配置资产列表
            unconfigured_assets = [a for a in all_assets if a not in manual_weights]
            
            if unconfigured_assets and remaining > 0:
                # 等权分配剩余权重
                equal_weight = remaining / len(unconfigured_assets)
                for asset in unconfigured_assets:
                    weights[asset] = equal_weight
        
        # 归一化
        if auto_normalize:
            weight_sum = weights.sum()
            if weight_sum <= 0:
                raise ValueError(f"权重总和为 {weight_sum}，无法归一化")
            weights = weights / weight_sum
        else:
            # 不归一化时检查权重总和
            weight_sum = weights.sum()
            if abs(weight_sum - 1.0) > 1e-6:
                import warnings
                warnings.warn(
                    f"权重总和为 {weight_sum:.4f}，不等于1.0。"
                    f"建议开启 auto_normalize 或手动调整权重。"
                )
        
        # 确保非负
        if (weights < 0).any():
            negative_assets = weights[weights < 0].index.tolist()
            raise ValueError(f"以下资产权重为负：{negative_assets}")
        
        return weights
