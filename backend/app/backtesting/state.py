"""ExecutionState：执行层记账内核（计算内核层，模式无关）.

把「怎么估值、怎么算权重、成交怎么记账、调仓后怎么重建持仓」从两处实现里
抽出来：回测侧 ``ExecutionEngine``（逐资产增量成交、成本从 cash 扣）与监控侧
``PortfolioTracker._execute_rebalance_traditional``（扣费后按目标权重重建数量、
遗留资产强制清零）。两者的**经济语义不同**，因此不合并成一个成交模型，只共用
记账原语：

* 现值与权重：``mark_to_market`` / ``weights_of``
* 增量成交记账：``apply_fill`` / ``update_avg_cost``（回测 CloseFill 语义）
* 目标状态重建：``target_trade_cost`` / ``apply_target_state``（监控 RebalanceFill 语义）
* 状态搬运：``to_exec_state`` / ``from_exec_state``（监控 PortfolioState 投影）

零漂移约束（改任何一行前先读这一段）
------------------------------------
1. **求和容器不能换形态**。本仓库运行 Python 3.13，内置 ``sum()`` 对 float
   走补偿求和（Neumaier），与逐步 ``total += x`` 的左折叠**结果不同**。
   所以 ``mark_to_market`` 必须保持 ``cash + sum(生成器)`` 的原始形态；
   改成 for 循环累加会改变净值最低位，进而让全部基线漂移。
2. **顺序即结果**。``keys`` 由调用方显式传入且不得排序、不得去重、不得
   跳过零值——原来的顺序就是 ``position.quantity`` 的插入序。
3. **阈值即结果**。``abs(delta) < 1e-6`` 跳过、``new_qty < 1e-6`` 清仓、
   ``weight != 0.0 and price > 0`` 才重建：这些常量是既有行为的一部分。
4. **NaN 不在内核里处理**。监控路径把 NaN 价格折成 0.0 是在调用前完成
   （``portfolio_tracker.py`` 的 ``np.isnan`` 分支），内核只做算术——两处
   各判一次必然分叉。
5. **括号形态不能动**。``qty * price`` 与 ``price * qty`` 等价，
   ``qty * price / total`` 与 ``qty * (price / total)`` 不等价。

``last_buy_dates`` 当前只被 T+1 可交易性（P1 的 TradabilityChecker）读取，
P0 阶段仅登记不消费。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from app.backtesting.types import Position

__all__ = [
    "ExecutionState",
    "apply_fill",
    "apply_target_state",
    "as_float",
    "from_exec_state",
    "mark_to_market",
    "position_values",
    "target_trade_cost",
    "to_exec_state",
    "update_avg_cost",
    "weights_of",
]


@dataclass
class ExecutionState:
    """持仓 + 平均成本 + 最近买入日：回测执行器跨调仓持有的全部可变状态.

    ``position`` 可能被调用方整体替换（每日结算钩子、杠杆缩放都会返回新
    ``Position``），因此执行器每次调仓前必须与之对齐（见 ``sync_position``）。
    """

    position: Position
    avg_cost: Dict[str, float] = field(default_factory=dict)
    last_buy_dates: Dict[str, Any] = field(default_factory=dict)

    def sync_position(self, position: Position) -> None:
        """与引擎侧最新持仓对齐（引擎会整对象替换 position）."""
        self.position = position


# ----------------------------------------------------------------------
#  估值
# ----------------------------------------------------------------------

def as_float(value: Any, default: float = 0.0) -> float:
    """监控侧容错取值：None / 字符串 / 异常一律折成 ``default``."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def mark_to_market(
    position: Position,
    prices: Mapping[str, float],
    keys: Optional[Iterable[str]] = None,
) -> float:
    """按给定价格映射计算组合总市值（cash + 持仓市值）.

    ``sum()`` 的容器形态是基线的一部分：Python 3.12+ 对 float 求和采用
    补偿求和，改成累加循环会得到不同的最低位。见模块头第 1 条。
    """
    qty = position.quantity
    if keys is None:
        keys = tuple(qty)
    return position.cash + sum(qty[code] * prices.get(code, 0.0) for code in keys)


def weights_of(
    position: Position,
    prices: Mapping[str, float],
    total_value: float,
    keys: Optional[Iterable[str]] = None,
) -> Dict[str, float]:
    """持仓市值权重（总市值为 0 时全部记 0）."""
    qty = position.quantity
    if keys is None:
        keys = tuple(qty)
    return {
        code: (qty[code] * prices.get(code, 0.0) / total_value) if total_value > 0 else 0.0
        for code in keys
    }


def position_values(
    quantities: Mapping[str, float],
    prices: Mapping[str, float],
    keys: Iterable[str],
) -> Dict[str, float]:
    """监控侧口径：逐 ``keys`` 计算 ``qty × price``（用于换手成本估算）."""
    return {
        asset: as_float(quantities.get(asset, 0.0)) * prices.get(asset, 0.0)
        for asset in keys
    }


# ----------------------------------------------------------------------
#  增量成交（回测 CloseFill 语义）
# ----------------------------------------------------------------------

def update_avg_cost(
    avg_cost: Dict[str, float],
    code: str,
    side: str,
    quantity: float,
    price: float,
    current_qty: float,
) -> Dict[str, float]:
    """买入时按数量加权更新平均成本；卖出不改（清仓由 ``apply_fill`` 处理）."""
    if side != "buy":
        return avg_cost
    old_cost_total = avg_cost.get(code, 0.0) * current_qty
    new_cost_total = old_cost_total + price * quantity
    new_qty_total = current_qty + quantity
    avg_cost[code] = new_cost_total / new_qty_total if new_qty_total > 0 else price
    return avg_cost


def apply_fill(
    position: Position,
    avg_cost: Dict[str, float],
    code: str,
    side: str,
    quantity: float,
    price: float,
    commission: float,
    slippage_cost: float,
) -> float:
    """把一笔成交就地计入 ``position`` 与 ``avg_cost``，返回该笔 ``pnl``.

    与 ``execution.py`` 原内联实现的算术逐位一致：
    买入 ``cash -= 成交额 + 成本``，卖出 ``cash += 成交额 - 成本``；
    卖出盈亏按平均成本计，清仓（``< 1e-6``）时删除平均成本。
    """
    total_cost = commission + slippage_cost
    current_qty = position.quantity.get(code, 0.0)
    gross = quantity * price

    if side == "buy":
        position.cash -= gross + total_cost
        update_avg_cost(avg_cost, code, side, quantity, price, current_qty)
        position.quantity[code] = current_qty + quantity
        return -total_cost

    avg = avg_cost.get(code, 0.0)
    position.cash += gross - total_cost
    trade_pnl = (price - avg) * quantity - total_cost
    new_qty = current_qty - quantity
    position.quantity[code] = new_qty
    if new_qty < 1e-6:
        avg_cost.pop(code, None)
    return trade_pnl


# ----------------------------------------------------------------------
#  目标状态重建（监控 RebalanceFill 语义）
# ----------------------------------------------------------------------

def target_trade_cost(
    nav: float,
    weights: Mapping[str, float],
    current_values: Mapping[str, float],
    keys: Iterable[str],
    cost_of,
) -> float:
    """按「目标市值 vs 当前市值」的差额估算换手成本（逐资产累加）."""
    trade_cost = 0.0
    for asset in keys:
        target_value = nav * float(weights.get(asset, 0.0) or 0.0)
        trade_amount = abs(target_value - current_values.get(asset, 0.0))
        trade_cost += trade_amount * cost_of(asset)
    return trade_cost


def apply_target_state(
    weights: Mapping[str, float],
    prices: Mapping[str, float],
    keys: Iterable[str],
    nav_after_cost: float,
) -> Tuple[Position, float]:
    """按目标权重重建持仓数量与现金（监控口径），返回 ``(position, 持仓市值)``.

    不在 ``keys`` 里的资产不会被写出——调用方必须先把遗留持仓并入 ``keys``
    并在 ``weights`` 里给 0，才会被清仓（``_active_assets_traditional`` 的职责）。
    """
    new_quantities: Dict[str, float] = {}
    holdings_total = 0.0
    for asset in keys:
        weight = float(weights.get(asset, 0.0) or 0.0)
        price = prices.get(asset, 0.0)
        if weight != 0.0 and price > 0:
            target_value = nav_after_cost * weight
            qty = target_value / price
            new_quantities[asset] = qty
            holdings_total += qty * price
        else:
            # 遗留资产 / 无价资产一律清仓
            new_quantities[asset] = 0.0
    return Position(quantity=new_quantities, cash=nav_after_cost - holdings_total), holdings_total


# ----------------------------------------------------------------------
#  状态搬运（监控 PortfolioState ↔ ExecutionState）
# ----------------------------------------------------------------------

def to_exec_state(
    quantities: Mapping[str, Any],
    cash: Any,
    avg_cost: Optional[Dict[str, float]] = None,
) -> ExecutionState:
    """把监控侧 ``quantities/cash`` 投影成执行状态（键序保持原样）."""
    return ExecutionState(
        position=Position(
            quantity={asset: as_float(qty) for asset, qty in quantities.items()},
            cash=as_float(cash),
        ),
        avg_cost=dict(avg_cost or {}),
    )


def from_exec_state(state: ExecutionState) -> Tuple[Dict[str, float], float]:
    """把执行状态投影回监控侧 ``(quantities, cash)``."""
    return dict(state.position.quantity), state.position.cash
