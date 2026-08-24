"""TargetWeightSignal：目标权重信号原语（计算内核层，模式无关）.

策略层（CompositionPipeline）与执行/风控层之间的统一交接结构。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd


@dataclass
class TargetWeightSignal:
    """目标权重信号.

    由策略层生成，表示在某个时间点希望组合持有的权重结构。
    """

    time: pd.Timestamp
    target_weights: Dict[str, float]
    trigger_type: str | None = None  # 调仓触发类型：periodic / event / mixed 等
    reason: str | None = None  # 调仓原因说明（如：周期调仓、波动率重置触发等）
