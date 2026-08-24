"""Control 模块 - 抽象基类定义.

提供每日监测与波动率控制的统一接口，供回测引擎和监控系统调用。
策略可通过 vol_control_type 参数选择具体的控制实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd


class BaseMonitor(ABC):
    """监测控制器抽象基类.

    所有控制策略（波动率监测、回撤控制等）均需继承此类并实现以下三个核心方法：
    - compute_metrics:      计算当前监控指标（如年化波动率、最大回撤等）
    - check_trigger:        判断是否触发控制动作（如波动率超阈值）
    - compute_reset_weights:触发后计算调整后的权重

    子类通过注册到 CONTROL_REGISTRY 后，可由 create_monitor() 工厂方法实例化。
    """

    @abstractmethod
    def compute_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> Dict[str, Any]:
        """计算监控指标.

        Args:
            current_weights: 当前持仓权重（index=资产代码, value=权重）
            prices:          资产价格历史数据（index=日期, columns=资产代码）
            **params:        策略/控制参数

        Returns:
            监控指标字典，例如 {"portfolio_volatility": 0.052}
            无法计算时应返回空字典 {}。
        """
        raise NotImplementedError

    @abstractmethod
    def check_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> tuple[bool, float | None]:
        """检查是否触发控制动作.

        Args:
            current_weights: 当前持仓权重
            prices:          资产价格历史数据
            **params:        策略/控制参数，需含 enable_vol_reset、vol_reset_threshold 等

        Returns:
            (triggered, signal_value)
            - triggered:    是否触发
            - signal_value: 触发信号值（如当前年化波动率）；无法计算时返回 None
        """
        raise NotImplementedError

    @abstractmethod
    def compute_reset_weights(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> pd.Series:
        """计算触发后的重置权重.

        典型实现：按 target_vol / signal_vol 等比例缩放当前权重。
        若支持外部传入信号日触发值（_vol_trigger），应优先使用该值进行缩放。

        Args:
            current_weights: 当前持仓权重
            prices:          资产价格历史数据
            **params:        策略/控制参数，可含 _vol_trigger（信号日已实现值）

        Returns:
            重置后的权重 Series；未触发或无法计算时返回 current_weights。
        """
        raise NotImplementedError
