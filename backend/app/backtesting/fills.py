"""FillModel：一次调仓如何成交（计算内核层，模式无关）.

两种经济语义，两个实现，**不合并**：

* ``CloseFill``——回测口径：以当日收盘（``Bar.get_price``：vwap 优先、close
  回退）为成交价，逐资产做「目标数量 vs 当前数量」的增量成交，成本从现金扣，
  只遍历目标权重里的资产（不在目标里的旧持仓保持不动，永不清仓）。
* ``RebalanceFill``——监控口径：先按「目标市值 vs 当前市值」估算换手成本，
  从**净值**扣掉，再按目标权重整体重建持仓数量；遗留资产（在 active_assets
  里但目标权重为 0）强制清零。

这两条口径的差异是既有行为（C1-2/C1-3），不是待修的 bug：回测是逐笔成交的
仿真，监控是「按目标权重记账」。共享的是记账原语（``state.py``），不是成交
模型。

数值保真
--------
* 两处都不使用内置 ``sum()`` 做增量累加——Python 3.12+ 对 float 的 ``sum``
  是补偿求和，与 ``total += x`` 的左折叠结果不同。回测侧原本就用 ``sum``
  （见 ``state.mark_to_market``），监控侧原本就用 ``+=``（见
  ``RebalanceFill.fill`` 的 ``current_nav``），各自保持自己的容器形态。
* ``RebalanceFill`` 的 ``prices`` 必须是「NaN 已折成 0.0」的普通 dict：
  原实现 ``portfolio_tracker._execute_rebalance_traditional`` 会在循环里
  做 ``np.isnan`` 判断，那一步留在调用方，内核不重复判断。

P1 之后新增的 FillModel（NextOpenFill / ParticipationCapFill / AdvImpactFill）
只实现 ``fill``，``execute`` 与引擎主循环无需改动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Mapping, Optional, Sequence

from app.backtesting.config import BacktestConfig
from app.backtesting.state import (
    ExecutionState,
    apply_fill,
    apply_target_state,
    as_float,
    target_trade_cost,
)
from app.backtesting.types import Bar, Position, Trade

__all__ = [
    "CloseFill",
    "Fill",
    "FillBatch",
    "FillContext",
    "FillModel",
    "RebalanceFill",
]


@dataclass
class Fill:
    """单笔成交（或单笔被拒）。``reject_reason`` 供 P1 可交易性使用，P0 恒 None."""

    code: str
    side: str
    quantity: float
    price: float
    commission: float = 0.0
    slippage_cost: float = 0.0
    pnl: float = 0.0
    reject_reason: Optional[str] = None


@dataclass
class FillBatch:
    """一次调仓的成交结果：新持仓 + 逐笔成交 + 成本合计."""

    position: Position
    fills: List[Fill] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)
    trading_cost: float = 0.0
    rejected: List[Fill] = field(default_factory=list)
    #: 重建类模型给出的调仓后净值（= 扣费后净值）；增量成交模型不填
    nav: Optional[float] = None


@dataclass
class FillContext:
    """一次调仓的全部外部输入（无状态：同一 ctx 重复调用结果相同）."""

    bar: Optional[Bar]
    config: BacktestConfig
    target_weights: Mapping[str, float]
    #: 成交/重建价格。CloseFill: ``bar.get_price(code)``（vwap→close）；
    #: RebalanceFill: 当日收盘，且 NaN 已由调用方折成 0.0
    prices: Mapping[str, float]
    #: 遍历顺序。CloseFill: ``target_weights`` 的键序；RebalanceFill: active_assets
    keys: Sequence[str]
    #: CloseFill 的资金基数（分资产费率净额配平后的 invest_value）；
    #: RebalanceFill 忽略（它自己从持仓算净值）
    equity: Optional[float] = None
    #: RebalanceFill 的单资产成本率解析（监控侧 trading_cost 表）
    cost_of: Optional[Callable[[str], float]] = None


class FillModel:
    """成交模型协议（结构化子类型，无需继承）.

    实现类只需提供 ``name`` / ``needs_equity`` 与 ``fill`` 方法。批量入参是
    刻意的：tick 级驱动只需换掉 ctx 的行情供给，不必改签名。

    ``needs_equity=False`` 的模型（``RebalanceFill``）自己从持仓算净值，
    驱动层不预计算资金基数，也因此不需要 ``bar``。
    """

    name: str = "base"
    needs_equity: bool = True

    def fill(self, state: ExecutionState, ctx: FillContext) -> FillBatch:  # pragma: no cover
        raise NotImplementedError


# ----------------------------------------------------------------------
#  回测口径：增量成交
# ----------------------------------------------------------------------

class CloseFill(FillModel):
    """当日收盘成交、成本从现金扣、只动目标权重里的资产（回测 v1 行为）."""

    name = "close"
    needs_equity = True

    def fill(self, state: ExecutionState, ctx: FillContext) -> FillBatch:
        config = ctx.config
        bar = ctx.bar
        if bar is None:
            raise ValueError("CloseFill 需要行情 bar（成交时间与成交价都来自它）")

        by_code = config.commission_by_code or {}
        default_rate = config.commission_rate
        equity = ctx.equity if ctx.equity is not None else 0.0

        # 目标数量：先算目标市值再除以价格。键序必须与 target_weights 一致。
        target_qty = {
            code: (equity * weight) / (ctx.prices.get(code, 0.0) or 1e-8)
            for code, weight in ctx.target_weights.items()
        }

        position = Position(
            quantity=state.position.quantity.copy(),
            cash=state.position.cash,
        )
        batch = FillBatch(position=position)

        for code in ctx.target_weights.keys():
            current_qty = position.quantity.get(code, 0.0)
            delta = target_qty.get(code, 0.0) - current_qty
            if abs(delta) < 1e-6:
                continue

            side = "buy" if delta > 0 else "sell"
            trade_qty = abs(delta)
            price = ctx.prices.get(code, 0.0)
            gross = trade_qty * price
            commission = gross * float(by_code.get(code, default_rate))
            slippage_cost = gross * config.slippage

            pnl = apply_fill(
                position, state.avg_cost, code, side, trade_qty, price,
                commission, slippage_cost,
            )
            if side == "buy":
                state.last_buy_dates[code] = bar.time

            batch.fills.append(Fill(
                code=code, side=side, quantity=trade_qty, price=price,
                commission=commission, slippage_cost=slippage_cost, pnl=pnl,
            ))
            batch.trades.append(Trade(
                time=bar.time, thscode=code, side=side, quantity=trade_qty,
                price=price, commission=commission, slippage_cost=slippage_cost,
                pnl=pnl,
            ))
            batch.trading_cost += commission + slippage_cost

        return batch


# ----------------------------------------------------------------------
#  监控口径：扣费后按目标权重重构
# ----------------------------------------------------------------------

class RebalanceFill(FillModel):
    """扣换手成本后按目标权重整体重建持仓，遗留资产清零（监控 v1 行为）."""

    name = "rebalance"
    needs_equity = False

    def fill(self, state: ExecutionState, ctx: FillContext) -> FillBatch:
        keys = ctx.keys
        prices = ctx.prices
        weights = ctx.target_weights
        cost_of = ctx.cost_of or (lambda _asset: 0.0)

        # 调仓基准净值：逐步左折叠（与原实现的 ``current_nav += cv`` 逐位一致，
        # 不能换成内置 sum —— 那是补偿求和，末位会不同）。
        current_nav = state.position.cash
        current_values = {}
        for asset in keys:
            current_values[asset] = as_float(state.position.quantity.get(asset, 0.0)) * prices.get(asset, 0.0)
            current_nav += current_values[asset]

        trade_cost = target_trade_cost(current_nav, weights, current_values, keys, cost_of)
        nav_after_cost = current_nav - trade_cost

        position, _holdings_total = apply_target_state(weights, prices, keys, nav_after_cost)
        return FillBatch(
            position=position,
            trading_cost=trade_cost,
            nav=nav_after_cost,
        )


def active_asset_keys(
    ordered_assets: Sequence[str],
    quantities: Mapping[str, float],
    eps: float = 1e-12,
) -> List[str]:
    """``ordered_assets`` 在前，再并入 ``quantities`` 中非零的遗留资产（保序去重）.

    与 ``portfolio_tracker._active_assets_traditional`` 同语义，抽出来是为了
    让「遗留资产必须进遍历序列才会被清零」这条约束有单一实现：

    * 键统一 ``str()`` 化（asset_list 与 state 里的键类型可能不一致）；
    * ``None`` 键丢弃；
    * 遗留资产只按 ``|qty| > eps`` 入选——零仓位不会进重建序列。
    """
    seen = set()
    keys: List[str] = []
    for asset in ordered_assets:
        key = str(asset)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    for asset, qty in (quantities or {}).items():
        if asset is None:
            continue
        key = str(asset)
        if key in seen:
            continue
        if abs(as_float(qty)) > eps:
            seen.add(key)
            keys.append(key)
    return keys


def resolve_cost_of(trading_cost: Optional[Mapping[str, float]]) -> Callable[[str], float]:
    """``{asset: rate}`` → 取值函数；缺省表时恒 0（生产监控当前就是空表）."""

    def _cost_of(asset: str) -> float:
        return float((trading_cost or {}).get(asset, 0.0))

    return _cost_of
