"""Control 模块 - 每日监测与波动率控制.

提供可插拔的监测控制器，供回测引擎与监控系统调用。

用法:
    from app.control import create_monitor, CONTROL_REGISTRY

    monitor = create_monitor("rolling_vol")
    metrics = monitor.compute_metrics(current_weights, prices, **params)
    triggered, vol = monitor.check_trigger(current_weights, prices, **params)
    reset_weights = monitor.compute_reset_weights(current_weights, prices, **params)

注册表:
    CONTROL_REGISTRY 字典映射 monitor_type 字符串到对应的 Monitor 类。
    新增控制器只需：
    1. 继承 BaseMonitor 并实现三个抽象方法
    2. 在 CONTROL_REGISTRY 中注册
"""

from __future__ import annotations

from typing import Dict, Type

from app.control.base import BaseMonitor
from app.control.volatility.rolling_vol import RollingVolMonitor
from app.control.volatility.dual_window_vol import DualWindowVolMonitor

# ---------------------------------------------------------------------------
# 注册表：monitor_type -> Monitor 类
# ---------------------------------------------------------------------------
CONTROL_REGISTRY: Dict[str, Type[BaseMonitor]] = {
    "rolling_vol": RollingVolMonitor,
    "dual_window_vol": DualWindowVolMonitor,
}


def create_monitor(monitor_type: str, **kwargs) -> BaseMonitor:
    """工厂方法：根据 monitor_type 创建对应的 Monitor 实例.

    Args:
        monitor_type: 注册在 CONTROL_REGISTRY 中的类型名称
        **kwargs:     传递给 Monitor 构造函数的参数（当前各 Monitor 无构造参数，预留扩展）

    Returns:
        BaseMonitor 实例

    Raises:
        ValueError: monitor_type 未在注册表中注册
    """
    cls = CONTROL_REGISTRY.get(monitor_type)
    if cls is None:
        available = ", ".join(sorted(CONTROL_REGISTRY.keys()))
        raise ValueError(
            f"未知的 monitor_type: {monitor_type!r}。"
            f"可用类型: {available}"
        )
    return cls(**kwargs)


__all__ = [
    "BaseMonitor",
    "RollingVolMonitor",
    "DualWindowVolMonitor",
    "CONTROL_REGISTRY",
    "create_monitor",
]
