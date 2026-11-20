# -*- coding: utf-8 -*-
"""
大类资产配置监测系统 - 组合跟踪器

本模块实现每日单日更新逻辑，包括：
- 汇率获取方法
- 收益率计算方法
- 持仓初始化方法
- 每日损益更新方法
- 调仓执行方法
- 权重计算方法
- 每日处理主方法

注意：核心计算逻辑与 monitor_vs 完全一致，不做任何算法修改
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple, TYPE_CHECKING

from app.monitor import config
from app.monitor.monitor_runtime import resolve_asset_currency_for_monitor

if TYPE_CHECKING:
    from app.monitor.monitor_runtime import MonitorRuntimeConfig
from app.monitor.types import PortfolioState, DailyResult
from app.monitor.time_norm import normalize_calendar_timestamp


class PortfolioTracker:
    """组合跟踪器，处理每日组合更新"""
    
    def __init__(self):
        """初始化，加载 config 参数"""
        self.base_value = config.BASE_VALUE
        self.asset_list = config.ASSET_LIST
        self.asset_currency = config.ASSET_CURRENCY
        # 通用监控净值口径：gross NAV（不计交易成本与复制成本）。
        # 资产级实盘费率体系尚未建立，config.TRADING_COST / REPLICATION_COST
        # 不再参与通用监控计算。研究员策略（sharpe_18 / hybrid_12）由各自
        # engine 内置费率独立计费，不经过本类。
        # 两个字典留作将来按资产配置费率的入口。
        self.trading_cost: Dict[str, float] = {}
        self.replication_cost: Dict[str, float] = {}
        # 传统持仓模型开关（任务#11）。
        # 启用后 update_daily_pnl/execute_rebalance 走与回测 engine.py 完全一致的
        # NAV = cash + Σ(qty × close) 路径；主观/手动配置策略专用。
        # 默认 False：量化策略仍维持原 APL 多币种路径。
        self.traditional_mode: bool = False

    def configure(self, rt: Optional["MonitorRuntimeConfig"] = None) -> None:
        """按实盘运行时配置切换资产宇宙与费率子集；rt 为 None 时恢复全局 config。

        额外副作用：根据 rt.manual_allocation_mode 决定是否启用传统持仓模型（任务#11）。
        """
        if rt is None:
            self.asset_list = list(config.ASSET_LIST)
            self.asset_currency = dict(config.ASSET_CURRENCY)
            self.trading_cost = {}
            self.replication_cost = {}
            self.traditional_mode = False
            return
        self.asset_list = list(rt.asset_list)
        an = rt.asset_names  # code→name 映射（来自策略模型/资产主数据）
        self.asset_currency = {
            a: resolve_asset_currency_for_monitor(a, asset_names=an) for a in self.asset_list
        }
        # 费率留空：通用监控按 gross NAV 计算，不再回退到 config 兜底表。
        self.trading_cost = {}
        self.replication_cost = {}
        # 主观/手动配置策略 → 启用与回测 engine.py 一致的传统持仓模型。
        self.traditional_mode = bool(getattr(rt, "manual_allocation_mode", False))

    # =========================================================================
    # 资产解析辅助（兼容 state 中 asset_list 之外的遗留持仓）
    # =========================================================================

    def _resolve_currency(self, asset: str) -> str:
        """取资产计价币种；asset_list 之外的资产回退至全局解析。"""
        if asset in self.asset_currency:
            return self.asset_currency.get(asset, 'CNH')
        return resolve_asset_currency_for_monitor(asset)

    def _resolve_replication_cost(self, asset: str) -> float:
        """通用监控复制费率：未配置时恒为 0（gross NAV 口径）。

        self.replication_cost 留作将来按资产配置实盘费率的入口；
        研究员策略自带费率，由各自 engine 计算，不经过本方法。
        """
        return float(self.replication_cost.get(asset, 0.0))

    def _resolve_trading_cost(self, asset: str) -> float:
        """通用监控交易费率：未配置时恒为 0（gross NAV 口径）。"""
        return float(self.trading_cost.get(asset, 0.0))

    def _active_assets(self, state: PortfolioState) -> list:
        """
        返回当前需要参与计算的资产并集：
            asset_list ∪ {state 中 positions_cny / positions_local / apl_local 非零的资产}

        关键：当策略运行时配置的 asset_list 与 MongoDB 中已恢复 state 不一致
        （例如旧的 12 类全集状态被新主观策略覆盖运行）时，state 内仍有非零持仓
        但不在 asset_list 中的资产，必须继续被纳入 NAV 计算与调仓清算流程，
        否则 update_daily_pnl 的 nav 求和会丢失这些资产的累计损益，导致 NAV
        在非调仓日跨步骤跳动（向下跳）或被异常重置（向上跳）。
        """
        seen = set()
        out = []
        for a in self.asset_list:
            if a not in seen:
                seen.add(a)
                out.append(a)
        # 合并 state 中所有非零键
        def _nz(d, k):
            try:
                return abs(float(d.get(k, 0.0))) > 1e-12
            except (TypeError, ValueError):
                return False
        for d in (state.positions_cny, state.positions_local, state.apl_local):
            if not d:
                continue
            for k in list(d.keys()):
                if k is None:
                    continue
                sk = str(k)
                if sk in seen:
                    continue
                if _nz(state.positions_cny, sk) or _nz(state.positions_local, sk) or _nz(state.apl_local, sk):
                    seen.add(sk)
                    out.append(sk)
        return out
    
    # =========================================================================
    # 传统持仓模型辅助（任务#11：与回测 engine.py 一致的 NAV = cash + Σ(qty×close)）
    # =========================================================================

    def _initialize_positions_traditional(
        self,
        state: PortfolioState,
        initial_weights: Dict[str, float],
        prices_today: Dict[str, float],
    ) -> None:
        """传统持仓模型初始化（主观策略首日）。

        与回测 engine.py 起始建仓路径对齐：
            position = Position(quantity={}, cash=initial_cash)
        随后立即调仓到初始权重（调仓内部会按交易费扣减）。
        """
        # 初始净值 = base_value（与现有 APL 路径保持同一起点）
        state.nav = float(self.base_value)
        state.nav_base = float(self.base_value)
        state.cash = float(self.base_value)
        state.quantities = {}
        # 任务#12：初始化 last_prices，首日后跳入节假日仍可回退估值
        if not hasattr(state, 'last_prices') or state.last_prices is None:
            state.last_prices = {}
        for asset, raw in (prices_today or {}).items():
            try:
                p = float(raw) if raw is not None else 0.0
            except (TypeError, ValueError):
                p = 0.0
            if not np.isnan(p) and p > 0:
                state.last_prices[asset] = p
        # 零初始化兼容字段（保持与原路径 nav_history / 报表公用）
        for asset in self.asset_list:
            state.positions_cny[asset] = 0.0
            state.positions_local[asset] = 0.0
            state.apl_local[asset] = 0.0
            state.target_weights[asset] = float(initial_weights.get(asset, 0.0) or 0.0)
        # 首日调仓 → 分配到目标权重（同回测期初建仓）
        self._execute_rebalance_traditional(
            state=state,
            new_weights=initial_weights,
            prices_today=prices_today,
            prev_nav=None,
        )
        # 初始化交易费不计入历史费用累计（与回测期初建仓一致由调用方控制）。

    def _update_daily_pnl_traditional(
        self,
        state: PortfolioState,
        prices_today: Dict[str, float],
        days_between: int = 1,
    ) -> float:
        """传统持仓模型每日 NAV / 复制费更新。

        公式严格对齐回测 engine.py：
            total_value = cash + Σ(qty × close_today)
            daily_rc    = Σ(|qty × close| × rc_rate / 365 × days_between)
            cash       -= daily_rc
            nav         = total_value - daily_rc

        任务#12 增强：节假日/停牌价格回退
            - prices_today 缺失/0/NaN 时回退到 state.last_prices 中上次有效价，
              避免 qty × 0 导致 NAV 跳走到仅剩 cash 所表现的负值。
            - 若所有持仓资产 prices_today 都缺失 → 认为是非交易日，跳过 NAV 重估与复制费扣减，
              NAV 保持与上一交易日一致（与回测仅遍历交易日的行为等效）。
        """
        # ------------------------------------------------------------------
        # 价格解析辅助：返回 (有效价 or 0.0, today_valid: bool)
        # ------------------------------------------------------------------
        last_prices = getattr(state, 'last_prices', None)
        if last_prices is None:
            last_prices = {}
            state.last_prices = last_prices

        def _parse_price(raw):
            if raw is None:
                return 0.0
            try:
                v = float(raw)
            except (TypeError, ValueError):
                return 0.0
            if np.isnan(v):
                return 0.0
            return v

        def _effective_price(asset: str):
            """今日价 → last_prices 回退。返回 (price, today_valid)。"""
            p_today = _parse_price(prices_today.get(asset))
            if p_today > 0:
                return p_today, True
            p_last = _parse_price(last_prices.get(asset))
            if p_last > 0:
                return p_last, False
            return 0.0, False

        # ------------------------------------------------------------------
        # 非交易日检测：所有持仓资产的 prices_today 都缺失 → NAV 不变
        # ------------------------------------------------------------------
        held_assets = []
        if state.quantities:
            for asset, qty in list(state.quantities.items()):
                try:
                    q = float(qty or 0.0)
                except (TypeError, ValueError):
                    continue
                if abs(q) > 1e-12:
                    held_assets.append(asset)

        if held_assets:
            any_today_valid = any(
                _parse_price(prices_today.get(a)) > 0 for a in held_assets
            )
            if not any_today_valid:
                # 非交易日：NAV / cash / quantities / positions_* 均保持不变，
                # 也不累计复制费（与回测仅在交易日序列上推进一致）。
                return 0.0

        # ------------------------------------------------------------------
        # 1) 市值重估 NAV（未扣复制费）
        # ------------------------------------------------------------------
        total_value = float(state.cash or 0.0)
        effective_prices: Dict[str, float] = {}
        if state.quantities:
            for asset, qty in list(state.quantities.items()):
                try:
                    q = float(qty or 0.0)
                except (TypeError, ValueError):
                    q = 0.0
                if q == 0.0:
                    continue
                p, _ = _effective_price(asset)
                effective_prices[asset] = p
                if p <= 0:
                    continue
                total_value += q * p

        # ------------------------------------------------------------------
        # 2) 复制费（仅从现金中扣，不动 quantities）
        # ------------------------------------------------------------------
        daily_rc_total = 0.0
        if state.quantities and days_between > 0:
            for asset, qty in list(state.quantities.items()):
                try:
                    q = float(qty or 0.0)
                except (TypeError, ValueError):
                    q = 0.0
                if q == 0.0:
                    continue
                rc_rate = self._resolve_replication_cost(asset)
                if rc_rate <= 0:
                    continue
                p = effective_prices.get(asset, 0.0)
                if p <= 0:
                    continue
                pos_value = abs(q * p)
                daily_rc_total += pos_value * (rc_rate / 365.0) * float(days_between)

        if daily_rc_total > 0:
            state.cash = float(state.cash or 0.0) - daily_rc_total

        state.nav = total_value - daily_rc_total
        state.total_replication_cost = float(state.total_replication_cost or 0.0) + daily_rc_total

        # ------------------------------------------------------------------
        # 3) 同步兼容字段：positions_cny / positions_local = qty × effective_price
        # ------------------------------------------------------------------
        if state.quantities:
            for asset, qty in list(state.quantities.items()):
                try:
                    q = float(qty or 0.0)
                except (TypeError, ValueError):
                    q = 0.0
                p = effective_prices.get(asset)
                if p is None:
                    p, _ = _effective_price(asset)
                mv = q * p
                state.positions_cny[asset] = mv
                state.positions_local[asset] = mv

        # ------------------------------------------------------------------
        # 4) 保存当日有效价格供后续节假日回退使用
        # ------------------------------------------------------------------
        if state.quantities:
            for asset in state.quantities:
                p_today = _parse_price(prices_today.get(asset))
                if p_today > 0:
                    last_prices[asset] = p_today

        return daily_rc_total

    def _execute_rebalance_traditional(
        self,
        state: PortfolioState,
        new_weights: Dict[str, float],
        prices_today: Dict[str, float],
        prev_nav: Optional[float] = None,
    ) -> float:
        """传统持仓模型调仓（与回测共用同一执行驱动 + ``RebalanceFill``）。

        执行语义（监控口径，与回测的增量成交不同）：
            current_nav = cash + Σ(qty × close_today)
            trade_cost = Σ |target_value - current_value| × tc_rate
            nav_after_cost = current_nav - trade_cost
            qty[a] = nav_after_cost × w[a] / close[a]；遗留资产清零
            cash = nav_after_cost - Σ(qty × close)

        成交与重建算术在 ``app.backtesting.fills.RebalanceFill``，记账原语在
        ``app.backtesting.state``；本方法只负责三件事：把 ``PortfolioState``
        投影成执行状态、把当日价格折成「NaN→0」的普通 dict、调完后的字段同步
        （``positions_cny`` 等与 ``nav_history`` 末条，与原实现逐位一致）。
        """
        from app.backtesting.config import BacktestConfig
        from app.backtesting.execution import ExecutionEngine
        from app.backtesting.fills import (
            RebalanceFill,
            active_asset_keys,
            resolve_cost_of,
        )
        from app.backtesting.state import to_exec_state

        active_assets = active_asset_keys(self.asset_list, state.quantities or {})

        # 取价：NaN 折成 0.0（内核只做算术，不再二次判断 nan）
        prices_use: Dict[str, float] = {}
        for asset in active_assets:
            price_raw = prices_today.get(asset)
            try:
                p = float(price_raw) if price_raw is not None else 0.0
            except (TypeError, ValueError):
                p = 0.0
            if np.isnan(p):
                p = 0.0
            prices_use[asset] = p

        driver = ExecutionEngine(
            BacktestConfig(
                name="monitor_traditional_rebalance",
                thscodes=list(active_assets),
                start_date="",
                end_date="",
            ),
            fill_model=RebalanceFill(),
        )
        batch = driver.execute(
            target_weights=new_weights,
            state=to_exec_state(state.quantities or {}, state.cash),
            prices=prices_use,
            keys=active_assets,
            cost_of=resolve_cost_of(self.trading_cost),
        )

        trade_cost = batch.trading_cost
        nav_after_cost = batch.nav
        if nav_after_cost is None:
            raise RuntimeError("RebalanceFill 未返回调仓后净值")
        new_quantities = batch.position.quantity

        # 1) 重建持仓与现金
        state.quantities = new_quantities
        state.cash = batch.position.cash
        state.nav = nav_after_cost  # = cash + Σ(qty×price)
        state.nav_base = state.nav

        # 2) 同步兼容字段：净值口径 positions_cny/positions_local 设为 target_value，apl 重置为 0
        for asset in active_assets:
            qty = new_quantities.get(asset, 0.0)
            price = prices_use.get(asset, 0.0)
            mv = qty * price
            state.positions_cny[asset] = mv
            state.positions_cny_base[asset] = mv  # 传统模型基准持仓 = 当日市值
            state.positions_local[asset] = mv  # 传统模型不变币种，两者一致
            state.apl_local[asset] = 0.0

        # 3) 同步调仓日 nav_history 末条（与回测调仓日快照对齐：记录扣费后 NAV）
        if state.nav_history and state.nav_history[-1].get('date') == state.date:
            last_entry = state.nav_history[-1]
            last_entry['nav'] = state.nav
            if prev_nav is not None and prev_nav > 0:
                last_entry['daily_return'] = state.nav / prev_nav - 1

        state.target_weights = dict(new_weights)
        state.pending_rebalance = None
        state.total_trading_cost = float(state.total_trading_cost or 0.0) + trade_cost
        return trade_cost

    # =========================================================================
    # 汇率获取方法
    # =========================================================================
    
    def get_fx_rate(self, currency: str, date, fx_df: pd.DataFrame) -> float:
        """
        获取指定货币在指定日期的汇率
        
        - CNH: 直接返回 1.0
        - 其他: 优先使用当日汇率
        - 若当日无数据：向前查找最近的有效汇率
        
        货币列名映射：
            HKD -> 'HKD' 列
            USD -> 'USD' 列
            EUR -> 'EUR' 列
        """
        if currency == 'CNH':
            return 1.0
        
        # 直接使用货币名称作为列名
        col_name = currency
        if col_name not in fx_df.columns:
            return 1.0
        if fx_df.empty:
            return 1.0

        date_ts = normalize_calendar_timestamp(
            pd.Timestamp(date) if isinstance(date, str) else date
        )

        # 索引统一为 DatetimeIndex。Mongo/Excel 异常或空表默认 RangeIndex 时，
        # 直接 fx_df.index <= Timestamp 会触发 numpy.ndarray 与 Timestamp 比较错误。
        idx = pd.to_datetime(fx_df.index, errors="coerce")
        ser = pd.Series(
            pd.to_numeric(fx_df[col_name], errors="coerce").to_numpy(),
            index=pd.DatetimeIndex(idx),
        )
        ser = ser[~ser.index.isna()].sort_index()
        if ser.empty:
            return 1.0

        if date_ts in ser.index:
            raw = ser.loc[date_ts]
            rate = float(raw.iloc[-1] if hasattr(raw, "iloc") else raw)
            if not np.isnan(rate):
                return rate

        past = ser[ser.index <= date_ts]
        for rate in reversed(past.to_numpy()):
            if not np.isnan(rate):
                return float(rate)

        return 1.0
    
    def get_all_fx_rates(self, date, fx_df: pd.DataFrame) -> Dict[str, float]:
        """
        获取所有相关货币的当日汇率（动态收集资产宇宙中所有计价货币）

        与原型 get_fx_rates(fx_df, date, assets) 对齐：按每个资产的计价货币
        获取汇率。必须覆盖 asset_currency 中出现的所有货币（含 JPY 等），
        否则该货币资产的 FX 变动完全不生效、持仓/交易费/PnL 全部错误。

        Returns:
            {'HKD': rate, 'USD': rate, 'EUR': rate, 'JPY': rate, 'CNH': 1.0, ...}
        """
        # 动态收集当前资产宇宙中所有计价货币（修复硬编码 4 币种遗漏 JPY 的 bug）
        currencies = set(['HKD', 'USD', 'EUR', 'CNH'])
        if hasattr(self, 'asset_currency') and self.asset_currency:
            currencies.update(self.asset_currency.values())
        return {currency: self.get_fx_rate(currency, date, fx_df) for currency in currencies}
    
    def get_asset_fx_rate(self, asset: str, date, fx_df: pd.DataFrame) -> float:
        """获取指定资产在指定日期的汇率"""
        currency = self.asset_currency.get(asset, 'CNH')
        return self.get_fx_rate(currency, date, fx_df)
    
    def get_all_asset_fx_rates(self, date, fx_df: pd.DataFrame) -> Dict[str, float]:
        """获取所有资产在指定日期的汇率"""
        return {asset: self.get_asset_fx_rate(asset, date, fx_df) for asset in self.asset_list}
    
    # =========================================================================
    # 收益率计算方法
    # =========================================================================
    
    def calc_asset_returns(self, prices_today: Dict[str, float], prices_yesterday: Dict[str, float],
                           fx_today: Dict[str, float], fx_yesterday: Dict[str, float]
                           ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """
        计算各资产的本币和人民币收益率
        
        本币收益率：ret_local = P_t / P_{t-1} - 1
        
        人民币收益率（含汇率）：
            若货币为 CNH：ret_cny = ret_local
            否则：ret_cny = (1 + ret_local) * (1 + ret_fx) - 1
            其中 ret_fx = FX_t / FX_{t-1} - 1
        
        Args:
            prices_today: 当日各资产价格 {资产名: 价格}
            prices_yesterday: 昨日各资产价格 {资产名: 价格}
            fx_today: 当日各货币汇率 {货币: 汇率}
            fx_yesterday: 昨日各货币汇率 {货币: 汇率}
        
        Returns:
            (dict_ret_local, dict_ret_cny)
        """
        ret_local = {}
        ret_cny = {}
        
        for asset in self.asset_list:
            p_today = prices_today.get(asset)
            p_yesterday = prices_yesterday.get(asset)
            
            # 本币收益率
            if (p_today is not None and p_yesterday is not None 
                and not np.isnan(p_today) and not np.isnan(p_yesterday) 
                and p_yesterday > 0):
                ret_local[asset] = p_today / p_yesterday - 1
            else:
                ret_local[asset] = 0.0
            
            # 人民币收益率（含汇率变动）
            currency = self.asset_currency.get(asset, 'CNH')
            
            if currency == 'CNH':
                ret_cny[asset] = ret_local[asset]
            else:
                fx_t = fx_today.get(currency, 1.0)
                fx_t_1 = fx_yesterday.get(currency, 1.0)
                
                if fx_t_1 > 0:
                    ret_fx = fx_t / fx_t_1 - 1
                    ret_cny[asset] = (1 + ret_local[asset]) * (1 + ret_fx) - 1
                else:
                    ret_cny[asset] = ret_local[asset]
        
        return ret_local, ret_cny
    
    # =========================================================================
    # 持仓初始化方法
    # =========================================================================
    
    def initialize_positions(self, state: PortfolioState, 
                             initial_weights: Dict[str, float],
                             fx_rates: Dict[str, float],
                             prices_today: Optional[Dict[str, float]] = None):
        """
        指数起始日处理：设置初始持仓
        
        - APL 路径（量化策略）：nav = BASE_VALUE，positions_cny = nav*weight…。
        - 传统路径（主观/手动配置、traditional_mode=True）：全现金起步后
          立即依 prices_today 调仓到初始权重，与回测 engine.py 期初建仓对齐。
        
        Args:
            state: 组合状态（原地修改）
            initial_weights: 初始权重 {资产名: 权重}
            fx_rates: 各货币汇率 {货币: 汇率}
            prices_today: 当日价格（传统模型必须提供）
        """
        if self.traditional_mode:
            if not prices_today:
                # 防御性：未传价格时退化到原路径，避免重建持仓全零
                pass
            else:
                self._initialize_positions_traditional(
                    state, initial_weights, prices_today
                )
                return

        state.nav = self.base_value
        state.nav_base = self.base_value
        
        for asset in self.asset_list:
            weight = initial_weights.get(asset, 0.0)
            currency = self.asset_currency.get(asset, 'CNH')
            fx_rate = fx_rates.get(currency, 1.0)
            
            # 设置持仓
            state.positions_cny[asset] = state.nav * weight
            state.positions_cny_base[asset] = state.nav * weight   # 与原型 handle_index_start 对齐
            state.positions_local[asset] = state.positions_cny[asset] / fx_rate
            state.apl_local[asset] = 0.0
            state.target_weights[asset] = weight
    
    # =========================================================================
    # 每日损益更新方法
    # =========================================================================
    
    def update_daily_pnl(self, state: PortfolioState, 
                         ret_local: Dict[str, float], ret_cny: Dict[str, float],
                         fx_rates: Dict[str, float], days_between: int = 1,
                         prices_today: Optional[Dict[str, float]] = None) -> float:
        """
        更新持仓和净值（每个有持仓的资产）

        - traditional_mode=True 且传入 prices_today 时：走与回测 engine.py 完全一致的
          NAV = cash + Σ(qty×close) 路径，忽略 ret_local/ret_cny/fx。
        - 其他情况：走原 APL 多币种路径。
        """
        # 主观策略模式：委托传统持仓模型（任务#11）
        if self.traditional_mode and prices_today is not None:
            return self._update_daily_pnl_traditional(
                state, prices_today, days_between
            )

        # 通用监控为 gross NAV：复制费率未配置时恒为 0，下列累计值保持为 0。
        daily_replication_cost = 0.0

        # 使用完整资产并集：asset_list ∪ state 中非零资产，避免遗留持仓丢失
        active_assets = self._active_assets(state)

        for asset in active_assets:
            # 跳过无持仓的资产
            if state.positions_cny.get(asset, 0) == 0:
                continue

            r_local = ret_local.get(asset, 0.0)
            r_cny = ret_cny.get(asset, 0.0)
            currency = self._resolve_currency(asset)
            fx_rate = fx_rates.get(currency, 1.0)

            # 1. 本币损益
            pnl_local = state.positions_local.get(asset, 0.0) * r_local

            # 2. 复制费用（本币）
            rc = self._resolve_replication_cost(asset)
            rc_cost_local = state.positions_local.get(asset, 0.0) * (rc / 365.0) * days_between
            daily_replication_cost += rc_cost_local * fx_rate

            # 3. 本币累计损益更新（扣除复制费用）
            state.apl_local[asset] = state.apl_local.get(asset, 0.0) + pnl_local - rc_cost_local

            # 4. 持仓更新（复利）
            state.positions_local[asset] = state.positions_local.get(asset, 0.0) * (1 + r_local)
            state.positions_cny[asset] = state.positions_cny.get(asset, 0.0) * (1 + r_cny)
            # positions_cny_base 不变（调仓日设定的基准持仓，日内不更新，与原型一致）

        # 5. 净值计算：nav = nav_base + sum(本币累计损益 × 当日汇率)
        # 必须遵循 state.apl_local 的全量键，避免遗留资产损益被丢弃导致 NAV 跳动
        total_apl_cny = 0.0
        seen_apl = set()
        for asset in active_assets:
            seen_apl.add(asset)
            currency = self._resolve_currency(asset)
            fx_rate = fx_rates.get(currency, 1.0)
            total_apl_cny += float(state.apl_local.get(asset, 0.0)) * fx_rate
        # 防御性兑底：apl_local 中还有未列入 active_assets 的键（例如 active 判定为零但仍有微量损益）
        if state.apl_local:
            for asset, val in list(state.apl_local.items()):
                if asset is None or asset in seen_apl:
                    continue
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                if v == 0.0:
                    continue
                currency = self._resolve_currency(str(asset))
                fx_rate = fx_rates.get(currency, 1.0)
                total_apl_cny += v * fx_rate

        state.nav = state.nav_base + total_apl_cny
        
        # 6. 累计复制费用
        state.total_replication_cost += daily_replication_cost
        
        return daily_replication_cost
    
    # =========================================================================
    # 调仓执行方法
    # =========================================================================
    
    def execute_rebalance(self, state: PortfolioState, 
                          new_weights: Dict[str, float],
                          fx_rates: Dict[str, float], 
                          rebalance_type: str = 'monthly',
                          prev_nav: float = None,
                          prices_today: Optional[Dict[str, float]] = None) -> float:
        """
        执行调仓。

        - traditional_mode=True 且传入 prices_today 时：走与回测 engine.py 一致的
          传统持仓调仓路径（NAV = cash + Σ(qty×close)，交易费 = Σ|ΔV|*tc）。
        - 其他情况：走原 APL 路径（监控域自有的权重台账调仓逻辑）。

        前置条件：调用本方法之前，必须已通过 update_daily_pnl 用旧权重
        计算了当日市场收益，state.nav 已反映「调仓前但含当日市场收益」的净值。

        Args:
            state: 组合状态（原地修改）
            new_weights: 新目标权重 {资产名: 权重}
            fx_rates: 各货币汇率 {货币: 汇率}
            rebalance_type: 调仓类型 'monthly' / 'vol_reset' / 'subjective'
            prev_nav: 前一日净值（仅用于同步 nav_history 末条 daily_return）
            prices_today: 当日价格（传统模型必须提供）

        Returns:
            交易费用
        """
        # 主观策略模式：委托传统持仓调仓（任务#11）
        if self.traditional_mode and prices_today is not None:
            return self._execute_rebalance_traditional(
                state=state,
                new_weights=new_weights,
                prices_today=prices_today,
                prev_nav=prev_nav,
            )

        # 调仓基准：与原型 handle_rebalance_execute 完全一致
        # - 持仓定标使用 prev_nav（前一日净值 nav[t-1]）
        # - 交易费从 state.nav 扣除（state.nav 已含当日 PnL，由 update_daily_pnl 更新）
        # - nav_base = state.nav（扣费后的当日净值）
        # prev_nav 由调用方（_process_single_day）传入，即上一处理日结束后的 state.nav
        rebalance_base_nav = prev_nav if (prev_nav is not None and prev_nav > 0) else state.nav

        # 通用监控为 gross NAV：交易费率未配置时恒为 0，调仓不扣成本。
        trade_cost = 0.0
        
        # 资产并集：当前 asset_list ∪ state 中遗留非零持仓。
        # 遗留资产（不在 asset_list）的目标权重为 0，调仓时会被卖出，apl/positions 一并清零，
        # 以保证调仓后 nav_base = nav 是干净的、后续计算不会重复计入遗留损益。
        active_assets = self._active_assets(state)
        
        # 1. 计算交易费用（基于 nav[t-1]，按本币计算后转换为人民币）
        for asset in active_assets:
            currency = self._resolve_currency(asset)
            fx_rate = fx_rates.get(currency, 1.0)
        
            # 目标持仓（本币）：遗留资产不在 new_weights 中，取 0
            target_pos_local = rebalance_base_nav * new_weights.get(asset, 0.0) / fx_rate
            # 自然增长后的当前持仓（本币）：update_daily_pnl 已应用 1+r_local
            natural_pos_local = state.positions_local.get(asset, 0.0)
            # 交易量（本币）
            trade_amount_local = abs(target_pos_local - natural_pos_local)
            # 交易费用（转为人民币）
            tc = self._resolve_trading_cost(asset)
            trade_cost += trade_amount_local * tc * fx_rate
        
        # 2. 扣除交易费用（与原型一致：从 state.nav 扣除，state.nav 已含当日 PnL）
        #    原型: state.nav -= trading_cost  (state.nav = nav_base + sum(apl*fx) 已更新)
        state.nav -= trade_cost

        # 3. 基于 prev_nav（前一日净值）重置持仓（与原型 handle_rebalance_execute 完全一致）
        #    原型: state.positions_cny[asset] = nav_for_position * weight
        #    其中 nav_for_position = prev_nav（前一日净值）
        for asset in active_assets:
            weight = new_weights.get(asset, 0.0)
            currency = self._resolve_currency(asset)
            fx_rate = fx_rates.get(currency, 1.0)

            state.positions_cny[asset] = rebalance_base_nav * weight
            state.positions_cny_base[asset] = rebalance_base_nav * weight  # 与原型 nav_for_position * weight 对齐
            state.positions_local[asset] = state.positions_cny[asset] / fx_rate if fx_rate else 0.0

        # 4. 重置累计损益（包含遗留资产，避免 nav_base 包括老 apl 后下一日双重计入）
        for asset in active_assets:
            state.apl_local[asset] = 0.0

        # 5. 更新净值基准（与原型一致：nav_base = state.nav，即当日扣费后净值）
        state.nav_base = state.nav
        # 保存以资产名为键的汇率
        fx_rates_asset = {}
        for asset in active_assets:
            currency = self._resolve_currency(asset)
            fx_rates_asset[asset] = fx_rates.get(currency, 1.0)
        state.last_rebalance_fx = fx_rates_asset
        
        # 6. 同步当日 nav_history 末条记录（与回测调仓日快照一致：记录扣费后净值）
        if state.nav_history and state.nav_history[-1].get('date') == state.date:
            last_entry = state.nav_history[-1]
            last_entry['nav'] = state.nav
            if prev_nav is not None and prev_nav > 0:
                last_entry['daily_return'] = state.nav / prev_nav - 1
        
        # 7. 更新目标权重
        state.target_weights = new_weights.copy()
        
        # 8. 清除待执行调仓
        state.pending_rebalance = None
        
        # 9. 累计交易费用
        state.total_trading_cost += trade_cost
        
        return trade_cost

    # =========================================================================
    # 权重计算方法
    # =========================================================================
    
    def calc_current_weights(self, state: PortfolioState) -> Dict[str, float]:
        """
        计算各资产的当前实际权重（人民币口径）
        
        w_asset = positions_cny[asset] / nav
        
        Args:
            state: 组合状态
        
        Returns:
            各资产权重 {资产名: 权重}
        """
        if state.nav <= 0:
            return {asset: 0.0 for asset in self.asset_list}

        # 返回 asset_list 中所有资产的当前权重；state 中遗留资产不参与权重报告
        # （仅参与损益/净值计算，在下一次调仓日被清算）。
        return {
            asset: state.positions_cny.get(asset, 0.0) / state.nav
            for asset in self.asset_list
        }
    
    # =========================================================================
    # 每日处理主方法
    # =========================================================================
    
    def process_day(self, state: PortfolioState, date: str,
                    prices_today: Dict[str, float], prices_yesterday: Dict[str, float],
                    fx_df: pd.DataFrame, trade_dates: list) -> DailyResult:
        """
        处理单个交易日的损益更新，更新 state（原地修改），返回 DailyResult
        
        注意：调仓执行不在此方法内进行，由主循环控制，
        以确保执行顺序正确：
        B.损益更新 → C.执行pending调仓 → D.月度调仓 → E.波动率监测
        
        Args:
            state: 组合状态（原地修改）
            date: 当前日期 (YYYY-MM-DD 字符串)
            prices_today: 当日各资产价格 {资产名: 价格}
            prices_yesterday: 昨日各资产价格 {资产名: 价格}
            fx_df: 汇率数据 DataFrame
            trade_dates: 交易日列表
        
        Returns:
            DailyResult: 当日处理结果
        """
        # 保存前一日净值（用于计算涨跌幅）
        prev_nav = state.nav
        
        # 获取当日和昨日汇率
        fx_today = self.get_all_fx_rates(date, fx_df)
        
        # 获取昨日日期（从 state 中获取）
        prev_date = state.date
        fx_yesterday = self.get_all_fx_rates(prev_date, fx_df)
        
        # 计算间隔天数
        date_ts = pd.Timestamp(date)
        prev_date_ts = pd.Timestamp(prev_date)
        days_between = (date_ts - prev_date_ts).days
        
        # A. 计算收益率
        ret_local, ret_cny = self.calc_asset_returns(
            prices_today, prices_yesterday, fx_today, fx_yesterday
        )
        
        # B. 每日损益更新（调仓由主循环控制，不在此处执行）
        # 注：traditional_mode=True 时，update_daily_pnl 内部会使用 prices_today
        # 走 NAV = cash + Σ(qty×close) 路径（与回测 engine.py 一致）。
        daily_replication_cost = self.update_daily_pnl(
            state, ret_local, ret_cny, fx_today, days_between,
            prices_today=prices_today,
        )
        
        # C. 更新状态日期和天数
        state.date = date
        state.day_count += 1
        
        # D. 计算当日状态
        asset_weights = self.calc_current_weights(state)
        total_leverage = sum(asset_weights.values())
        
        # 计算涨跌幅
        if prev_nav > 0:
            nav_change_pct = (state.nav / prev_nav - 1) * 100
        else:
            nav_change_pct = 0.0
        
        # E. 更新净值历史
        state.nav_history.append({
            'date': date,
            'nav': state.nav,
            'daily_return': nav_change_pct / 100,  # 转换为小数形式
        })
        
        # F. 构建并返回 DailyResult（调仓标志由主循环设置）
        return DailyResult(
            date=date,
            nav=state.nav,
            nav_change_pct=nav_change_pct,
            total_leverage=total_leverage,
            asset_weights=asset_weights,
            asset_returns_local=ret_local,
            asset_returns_cny=ret_cny,
            rebalance_executed=False,
            rebalance_type=None,
            trading_cost=0.0,
            replication_cost=daily_replication_cost,
        )
