"""RiskManager：杠杆/权重上限约束（计算内核层，模式无关）.

对策略层产出的目标权重应用 RiskConfig 约束（总杠杆上限、单品种权重上限等），
只做缩放/裁剪，不改变策略信号方向。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from app.backtesting.signal import TargetWeightSignal


@dataclass
class RiskConfig:
    """风控参数配置.

    - max_total_leverage: 最大杠杆倍数。当策略输出权重和超过此值时按此值缩放；
      为 None 时不强制归一化，允许权重和大于 1（杠杆持仓）。
    - max_weight_dict: 单资产最大权重限制（资产代码->最大权重，如 {"GLD": 0.10}），
      超过时按上限截断；为 None 或空时不约束单资产。
    - allow_negative_weights: 是否允许负权重（做空）。默认 False（权重截断到 0）；
      类雪球 Delta 对冲等策略 KI 后需要负权重对冲（对应策略参数 allow_short=True），
      若强制置零会破坏策略语义（对齐四象限原型 allow_short 行为）。
    """
    max_total_leverage: float | None = None  # None 表示不强制和为 1，保留策略输出的杠杆
    max_weight_dict: Optional[Dict[str, float]] = None  # 单资产权重上限（浙银理财编制规则等）
    allow_negative_weights: bool = False  # True 时保留策略输出的负权重（做空）


class RiskManager:
    """风控管理器.

    对策略生成的目标权重信号进行风险约束调整。
    支持最大杠杆倍数大于 1 时持仓权重和大于 1，不强制归一化为和 1。
    """

    def __init__(self, config: RiskConfig | None = None) -> None:
        self._config = config or RiskConfig()

    def apply_risk_checks(
        self,
        signal: TargetWeightSignal,
        history_prices: pd.DataFrame,
    ) -> TargetWeightSignal:
        """对目标权重信号做风控处理，并返回调整后的信号.

        - 保证权重非负
        - 按 max_weight_dict 限制单资产权重上限（浙银理财编制规则）
        - 不强制归一化为和 1：当策略 max_total_leverage > 1 时，权重和可以大于 1（杠杆）
        - 仅当配置了 max_total_leverage 且权重和超过该值时，按 max_total_leverage 缩放
        """
        weights = signal.target_weights.copy()

        # TODO: 后续可扩展
        # 1. 流动性风险检查（基于成交额/换手率等）
        # 2. 极端行情风险检查（基于历史波动或跌幅等）

        # 非负约束（允许做空的策略跳过：如类雪球 Delta 对冲 KI 后的负 Delta 仓位）
        allow_negative = getattr(self._config, "allow_negative_weights", False)
        if not allow_negative:
            weights = {k: max(float(v), 0.0) for k, v in weights.items()}

        # 单资产权重上限（浙银理财编制规则或用户配置）
        max_weight_dict = getattr(self._config, "max_weight_dict", None)
        if isinstance(max_weight_dict, dict) and max_weight_dict:
            default_max = 0.10
            for code in list(weights.keys()):
                cap = max_weight_dict.get(code, default_max)
                try:
                    cap_f = float(cap)
                    if weights[code] > cap_f:
                        weights[code] = cap_f
                except (TypeError, ValueError):
                    pass
        total = sum(weights.values())

        if total <= 0:
            return TargetWeightSignal(time=signal.time, target_weights=weights)


        # 仅当配置了最大杠杆且权重和超过该值时缩放，否则保留策略输出（允许杠杆）
        max_leverage = getattr(self._config, "max_total_leverage", None)
        if max_leverage is not None and total > max_leverage:
            scale = max_leverage / total
            weights = {k: v * scale for k, v in weights.items()}

        return TargetWeightSignal(time=signal.time, target_weights=weights)
