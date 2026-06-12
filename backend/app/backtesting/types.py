from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any

import pandas as pd


@dataclass
class Bar:
    """单个时间点的行情数据.

    index 对应 data 模块中的 time 字段，close 为 {thscode: close_price}。
    """

    time: pd.Timestamp
    close: Dict[str, float]


@dataclass
class Position:
    """组合持仓状态（仅支持多头，第一版不考虑卖空/融资融券）."""

    quantity: Dict[str, float]  # {thscode: shares}
    cash: float


@dataclass
class Order:
    """订单结构（第一版主要由执行引擎内部使用，可后续扩展）。"""

    time: pd.Timestamp
    thscode: str
    side: str          # "buy" / "sell"
    quantity: float
    price: float | None = None  # 限价单可填，不填表示市价


@dataclass
class Trade:
    """成交记录."""

    time: pd.Timestamp
    thscode: str
    side: str
    quantity: float
    price: float
    commission: float
    slippage_cost: float


@dataclass
class PortfolioSnapshot:
    """某一时间点的组合快照，用于后续绩效分析."""

    time: pd.Timestamp
    total_value: float
    cash: float
    holdings_value: float
    weights: Dict[str, float]
    is_rebalance_day: bool = False  # 是否为调仓日（调仓日无收益）
    rebalance_type: str | None = None  # 调仓类型："regular" / "vol_reset" 等
    portfolio_volatility: float | None = None  # 当日组合波动率（用于监控）
    monitoring_metrics: Dict[str, Any] = field(default_factory=dict)  # 扩展监控指标库
    rebalance_reason: str | None = None  # 调仓原因（周期性调仓 / 条件触发等）
