"""ExecutionEngine：目标权重 → 成交执行（计算内核层，模式无关）.

将目标权重信号按当前持仓与价格转换为成交（Order/Trade），
支持可选手续费率/滑点；指数口径场景（监控、GMSI2 对齐）可配零成本。

驱动化后本模块只负责「算资金基数 → 建上下文 → 交给 FillModel」：成交算术在
``fills.py``（``CloseFill`` 回测增量成交 / ``RebalanceFill`` 监控权重重建），
记账原语在 ``state.py``。本模块不再内联 qty/cash 计算。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence

from app.backtesting.config import BacktestConfig
from app.backtesting.fills import CloseFill, Fill, FillContext, FillModel
from app.backtesting.state import ExecutionState
from app.backtesting.types import Position, Trade, Bar
from app.backtesting.signal import TargetWeightSignal


@dataclass
class ExecutionResult:
    """一次调仓执行后的结果: 新持仓 + 交易列表."""

    position: Position
    trades: List[Trade]
    #: 被拒订单（P1 可交易性接入后才有内容；P0 恒空）
    rejected: List[Fill] = field(default_factory=list)
    #: 本轮交易成本合计（手续费 + 滑点）
    trading_cost: float = 0.0
    #: 成交后净值；仅当 FillModel 显式给出时为非 None（``RebalanceFill`` 扣费后
    #: NAV 是监控调仓的落库口径，``CloseFill`` 不产出该值）
    nav: Optional[float] = None


class ExecutionEngine:
    """订单执行与成本计算模块.

    采用市价单 + 线性手续费/滑点模型。
    通过 Bar.get_price() 按优先级取价（vwap → close），
    当 DataFeed 加载了 VWAP 宽表时自动使用更真实的成交价，
    缺失时无感回退到收盘价，所有策略自动受益。
    平均买入成本保存在 ``ExecutionState``（跨调仓可变，用于每笔 pnl）。

    ``fill_model`` 缺省为 ``CloseFill()``：既有回测语义；显式传入
    ``RebalanceFill()`` 即切换为监控口径的目标状态重建。
    ``tradability`` 为 P1 可交易性预留位，P0 不消费。
    """

    def __init__(
        self,
        config: BacktestConfig,
        fill_model: Optional[FillModel] = None,
        tradability=None,
    ) -> None:
        self._config = config
        self._fill: FillModel = fill_model or CloseFill()
        self._tradability = tradability
        # 跨调仓可变状态：平均买入成本 + 最近买入日
        self._state = ExecutionState(
            position=Position(quantity={}, cash=config.initial_cash)
        )
        self._avg_cost: Dict[str, float] = self._state.avg_cost

    @property
    def state(self) -> ExecutionState:
        """当前执行状态（平均成本跨调仓保留）."""
        return self._state

    def execute(
        self,
        target_weights: Mapping[str, float],
        state: Optional[ExecutionState] = None,
        bar: Optional[Bar] = None,
        prices: Optional[Mapping[str, float]] = None,
        keys: Optional[Sequence[str]] = None,
        cost_of=None,
    ) -> ExecutionResult:
        """按目标权重驱动一次调仓；成交算术全部委托 ``fill_model``.

        两种入口，由 ``fill_model.needs_equity`` 决定：

        * ``True``（``CloseFill``）：只传 ``bar``。驱动层用 ``Bar.get_price``
          逐资产取价、算总市值与净额配平后的资金基数 ``equity``。
        * ``False``（``RebalanceFill``）：传 ``prices``（NaN 已折成 0）与
          ``keys``（active_assets，含遗留持仓）。驱动层不碰价格，也不需要
          ``bar``——监控侧没有单个 "bar" 对象。
        """
        st = state if state is not None else self._state
        target_weights_dict = target_weights
        fill_keys = tuple(keys) if keys is not None else tuple(target_weights_dict)

        if self._fill.needs_equity:
            if bar is None:
                raise ValueError(f"{self._fill.name} 需要行情 bar（成交时间与价格来源）")

            # 防御性检查：确保 bar.close 是字典
            if not isinstance(bar.close, dict):
                raise TypeError(
                    f"bar.close 必须是字典类型，实际类型为 {type(bar.close)}。"
                    f"可能是数据格式问题，请检查数据源。"
                )

            # 取价缓存：Bar.get_price 是纯函数，缓存不改变结果，只免掉重复查找
            price_map: Dict[str, float] = dict(prices) if prices else {}

            def px(code: str) -> float:
                cached = price_map.get(code)
                if cached is None:
                    cached = bar.get_price(code)
                    price_map[code] = cached
                return cached

            # 当前组合总市值（执行口径：vwap 优先，与估值口径的 close 分开）
            total_value = st.position.cash + sum(
                qty * px(code)
                for code, qty in st.position.quantity.items()
            )

            # 声明了分资产费率表时按净额配平：先按「权重差 × 费率」估算本轮换手成本
            # （与「实际成交额 × 费率」等价），再按扣费后净值分配目标市值，
            # 使调仓后权重精确等于目标权重。未声明时沿用毛额分配，既有策略行为不变。
            invest_value = total_value
            by_code = self._config.commission_by_code or {}
            if by_code and total_value > 0:
                cost_rate = 0.0
                for code, w in target_weights_dict.items():
                    cur_w = (
                        st.position.quantity.get(code, 0.0) * px(code) / total_value
                    )
                    diff = abs(float(w) - cur_w)
                    cost_rate += diff * float(by_code.get(code, self._config.commission_rate))
                    cost_rate += diff * self._config.slippage
                invest_value = total_value * (1.0 - min(max(cost_rate, 0.0), 1.0))

            # 目标键的成交价先全部落实（CloseFill 只在目标键上成交）
            for code in target_weights_dict:
                px(code)
            fill_prices: Mapping[str, float] = price_map
            equity: Optional[float] = invest_value
        else:
            if prices is None:
                raise ValueError(
                    f"{self._fill.name} 需要显式 prices（按 keys 建好的价格映射）"
                )
            fill_prices = prices
            equity = None

        ctx = FillContext(
            bar=bar,
            config=self._config,
            target_weights=target_weights_dict,
            prices=fill_prices,
            keys=fill_keys,
            equity=equity,
            cost_of=cost_of,
        )
        batch = self._fill.fill(st, ctx)
        st.sync_position(batch.position)
        return ExecutionResult(
            position=batch.position,
            trades=batch.trades,
            rejected=batch.rejected,
            trading_cost=batch.trading_cost,
            nav=batch.nav,
        )

    def rebalance_to_target(
        self,
        bar: Bar,
        current_position: Position,
        target_signal: TargetWeightSignal,
    ) -> ExecutionResult:
        """按照目标权重进行一次调仓（保留原签名；内部委托 ``execute``）."""
        self._state.sync_position(current_position)
        return self.execute(
            target_weights=target_signal.target_weights,
            state=self._state,
            bar=bar,
        )
