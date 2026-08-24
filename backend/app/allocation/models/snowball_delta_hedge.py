"""类雪球 Delta 对冲策略 — 完整实现。

通过蒙特卡洛定价计算雪球期权的 Delta，动态调整 ETF 持仓仓位来复制雪球结构收益。
支持单合约滚动和多合约并行两种模式，支持单资产和多资产场景。

收益来源：
- KO（敲出）：赚取票息
- 未触发：拿满票息
- KI（敲入）后：承担下跌（做空对冲）

核心逻辑：
  每日循环 → 合约管理(KO/KI/到期/滚动) → MC定价 → Delta数值微分 → 仓位系数 → 调仓
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import zlib

import numpy as np
import pandas as pd
from loguru import logger

from app.allocation.models.base import BaseStrategyModel


# ============================================================
# 合约数据结构
# ============================================================

@dataclass
class _Contract:
    """一只存续中的雪球合约（内部状态）."""

    start_date: pd.Timestamp
    maturity_date: pd.Timestamp
    initial_spot: float
    KO_abs: float
    KI_abs: float
    coupon_annual: float
    sigma: float
    pricing_seed: int = 42
    knocked_in: bool = False
    knocked_out: bool = False
    settled: bool = False


# ============================================================
# 波动率计算（纯函数）
# ============================================================

def _compute_historical_volatility(close_prices: np.ndarray, window: int = 252) -> float:
    """历史波动率（年化）.

    年化系数 √252 对齐四象限原型 snowball_engine.pricer.compute_historical_volatility。
    """
    if len(close_prices) < 2:
        return 0.20
    prices = close_prices[-min(window, len(close_prices)):]
    log_returns = np.diff(np.log(prices))
    if len(log_returns) < 2:
        return 0.20
    daily_vol = np.std(log_returns, ddof=1)
    return float(daily_vol * np.sqrt(252))


def _compute_ewma_volatility(close_prices: np.ndarray, lam: float = 0.94) -> float:
    """EWMA 波动率（年化）."""
    if len(close_prices) < 2:
        return 0.20
    log_returns = np.diff(np.log(close_prices))
    n = len(log_returns)
    weights = np.array([(1 - lam) * lam ** i for i in range(n - 1, -1, -1)])
    weights = weights / weights.sum()
    variance = np.sum(weights * (log_returns ** 2))
    return float(np.sqrt(variance) * np.sqrt(252))


# ============================================================
# GBM 路径生成（纯函数）
# ============================================================

def _generate_gbm_paths(
    S: float, r: float, sigma: float, T: float,
    n_steps: int, n_paths: int, seed: int = 42,
) -> np.ndarray:
    """生成 GBM 价格路径矩阵 (n_paths, n_steps+1)."""
    rng = np.random.default_rng(seed)
    dt = T / max(n_steps, 1)
    Z = rng.standard_normal((n_paths, n_steps))
    drift = (r - 0.5 * sigma ** 2) * dt
    diffusion = sigma * np.sqrt(dt) * Z
    log_paths = np.log(S) + np.cumsum(drift + diffusion, axis=1)
    paths = np.exp(log_paths)
    return np.column_stack([np.full(n_paths, S), paths])


# ============================================================
# 雪球收益计算（纯函数）
# ============================================================

def _snowball_payoff(
    paths: np.ndarray, KO_abs: float, KI_abs: float,
    coupon_annual: float, dt_years: float, maturity_years: float,
    S0_contract: float, already_knocked_in: bool = False,
) -> np.ndarray:
    """按雪球规则计算每条路径的到期收益 (per unit notional)."""
    n_paths = paths.shape[0]
    above_KO = paths[:, 1:] >= KO_abs
    below_KI = paths[:, 1:] <= KI_abs

    ko_steps = np.argmax(above_KO, axis=1) + 1
    ko_steps[~above_KO.any(axis=1)] = 0

    has_KI = np.full(n_paths, True) if already_knocked_in else below_KI.any(axis=1)

    payoff = np.zeros(n_paths)

    # 敲出：coupon × 敲出时间
    ko_mask = ko_steps > 0
    if ko_mask.any():
        payoff[ko_mask] = coupon_annual * (ko_steps[ko_mask] * dt_years)

    # 未敲出 + 未敲入：满票息
    no_ko = ~ko_mask
    no_ki_no_ko = no_ko & ~has_KI
    payoff[no_ki_no_ko] = coupon_annual * maturity_years

    # 未敲出 + 曾敲入：承担下跌
    ki_no_ko = no_ko & has_KI
    if ki_no_ko.any():
        S_T = paths[ki_no_ko, -1]
        payoff[ki_no_ko] = np.minimum(0.0, S_T / S0_contract - 1.0)

    return payoff


# ============================================================
# MC 定价 + Delta（纯函数）
# ============================================================

def _price_snowball_mc(
    S: float, r: float, sigma: float, T_remain: float,
    KO_abs: float, KI_abs: float, coupon_annual: float,
    maturity_years: float, S0_contract: float,
    n_paths: int = 10000, seed: int = 42,
    already_knocked_in: bool = False,
) -> float:
    """蒙特卡洛定价：雪球期权 NPV (per unit notional)."""
    n_steps = max(int(T_remain * 365), 1)
    dt_years = T_remain / n_steps
    paths = _generate_gbm_paths(S, r, sigma, T_remain, n_steps, n_paths, seed)
    payoffs = _snowball_payoff(
        paths, KO_abs, KI_abs, coupon_annual, dt_years,
        maturity_years, S0_contract, already_knocked_in,
    )
    return float(np.mean(payoffs) * np.exp(-r * T_remain))


def _evaluate_contract(
    S: float, r: float, sigma: float, T_remain: float,
    KO_abs: float, KI_abs: float, coupon_annual: float,
    maturity_years: float, S0_contract: float,
    n_paths: int = 10000, seed: int = 42, eps: float = 0.005,
    already_knocked_in: bool = False, allow_short: bool = True,
) -> float:
    """定价 + Delta数值微分 → 仓位系数 delta_coef ∈ [-1,1] 或 [0,1]."""
    S_up = S * (1 + eps)
    S_down = S * (1 - eps)

    V_up = _price_snowball_mc(
        S_up, r, sigma, T_remain, KO_abs, KI_abs,
        coupon_annual, maturity_years, S0_contract, n_paths, seed, already_knocked_in,
    )
    V_down = _price_snowball_mc(
        S_down, r, sigma, T_remain, KO_abs, KI_abs,
        coupon_annual, maturity_years, S0_contract, n_paths, seed, already_knocked_in,
    )

    delta_raw = (V_up - V_down) / (2 * S * eps)
    coef = delta_raw * S0_contract

    if allow_short:
        return float(np.clip(coef, -1.0, 1.0))
    return float(np.clip(coef, 0.0, 1.0))


# ============================================================
# 策略类
# ============================================================

class SnowballDeltaHedgeStrategy(BaseStrategyModel):
    """类雪球 Delta 对冲分配器.

    有状态策略：实例持有合约生命周期状态，每日调仓时更新。
    支持单资产/多资产，每个资产独立管理合约。
    """

    def __init__(self):
        # 每个资产的合约状态
        self._contracts: Dict[str, List[_Contract]] = {}  # asset -> active contracts
        self._history: Dict[str, List[_Contract]] = {}    # asset -> settled contracts
        self._last_date: Optional[pd.Timestamp] = None
        self._deployed_count: Dict[str, int] = {}         # asset -> lifetime deployed
        self._deploy_day_counter: Dict[str, int] = {}     # asset -> day index for deployment
        self._initialized = False

    # ------------------------------------------------------------------
    # 执行调度：每日调仓，T+0
    # ------------------------------------------------------------------

    def get_execution_schedule(self) -> Optional[dict]:
        return {"rebalance_freq": "daily", "execution_delay": 0}

    # ------------------------------------------------------------------
    # 核心：allocate
    # ------------------------------------------------------------------

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """计算 Delta 对冲权重.

        每次调用时：
        1. 确定当前日期（prices 最后一行）
        2. 对每个资产执行合约生命周期管理
        3. MC 定价 → Delta → 仓位系数
        4. 返回权重 Series
        """
        if prices.empty:
            raise ValueError("prices DataFrame is empty")

        assets = list(prices.columns)
        current_date = prices.index[-1]
        n_assets = len(assets)

        # 解析参数
        maturity_days = int(params.get("maturity_days", 180))
        knock_out_pct = float(params.get("knock_out_pct", 1.15))
        knock_in_pct = float(params.get("knock_in_pct", 0.80))
        coupon_value = float(params.get("coupon_value", 0.06))
        rolling_mode = params.get("rolling_mode", "single")
        num_contracts = int(params.get("num_contracts", 24))
        deploy_interval = int(params.get("deploy_interval", 5))
        n_paths = int(params.get("n_paths", 10000))
        vol_model = params.get("vol_model", "historical")
        vol_window = int(params.get("vol_window", 252))
        risk_free_rate = float(params.get("risk_free_rate", 0.013))
        dividend_yield = float(params.get("dividend_yield", 0.0))
        greek_eps = float(params.get("greek_eps", 0.005))
        allow_short = bool(params.get("allow_short", True))
        ki_liquidation = bool(params.get("ki_liquidation", False))

        r_eff = risk_free_rate - dividend_yield

        # 检查数据是否足够计算波动率
        if len(prices) < vol_window + 1:
            # 数据不足，返回等权（预热期）
            logger.debug(
                "[Snowball] 数据不足({}行 < vol_window={}), 返回零权重",
                len(prices), vol_window,
            )
            return pd.Series(0.0, index=assets)

        # 对每个资产计算 delta_coef
        weights = {}
        for asset in assets:
            asset_prices = prices[asset].dropna()
            if len(asset_prices) < vol_window + 1:
                weights[asset] = 0.0
                continue

            current_price = float(asset_prices.iloc[-1])
            if current_price <= 0 or np.isnan(current_price):
                weights[asset] = 0.0
                continue

            delta_coef = self._process_asset(
                asset=asset,
                current_date=current_date,
                current_price=current_price,
                asset_prices=asset_prices,
                maturity_days=maturity_days,
                knock_out_pct=knock_out_pct,
                knock_in_pct=knock_in_pct,
                coupon_value=coupon_value,
                rolling_mode=rolling_mode,
                num_contracts=num_contracts,
                deploy_interval=deploy_interval,
                n_paths=n_paths,
                vol_model=vol_model,
                vol_window=vol_window,
                r_eff=r_eff,
                greek_eps=greek_eps,
                allow_short=allow_short,
                ki_liquidation=ki_liquidation,
            )

            # 多资产时等分资金
            weights[asset] = delta_coef / n_assets

        return pd.Series(weights)

    # ------------------------------------------------------------------
    # 单资产合约管理
    # ------------------------------------------------------------------

    def _process_asset(
        self, asset: str, current_date: pd.Timestamp, current_price: float,
        asset_prices: pd.Series, maturity_days: int, knock_out_pct: float,
        knock_in_pct: float, coupon_value: float, rolling_mode: str,
        num_contracts: int, deploy_interval: int, n_paths: int,
        vol_model: str, vol_window: int, r_eff: float, greek_eps: float,
        allow_short: bool, ki_liquidation: bool,
    ) -> float:
        """处理单个资产的合约生命周期，返回 delta_coef."""

        # 初始化资产状态
        if asset not in self._contracts:
            self._contracts[asset] = []
            self._history[asset] = []
            self._deployed_count[asset] = 0
            self._deploy_day_counter[asset] = 0

        active = self._contracts[asset]

        # 跳过重复日期（同一交易日多次调用）
        if self._last_date == current_date:
            pass  # 仍然执行，因为可能多资产不同步
        # 更新全局日期
        self._last_date = current_date

        if rolling_mode == "multi":
            return self._process_multi(
                asset, current_date, current_price, asset_prices,
                active, maturity_days, knock_out_pct, knock_in_pct,
                coupon_value, num_contracts, deploy_interval, n_paths,
                vol_model, vol_window, r_eff, greek_eps, allow_short, ki_liquidation,
            )
        else:
            return self._process_single(
                asset, current_date, current_price, asset_prices,
                active, maturity_days, knock_out_pct, knock_in_pct,
                coupon_value, n_paths, vol_model, vol_window, r_eff,
                greek_eps, allow_short, ki_liquidation,
            )

    def _process_single(
        self, asset: str, current_date: pd.Timestamp, current_price: float,
        asset_prices: pd.Series, active: List[_Contract],
        maturity_days: int, knock_out_pct: float, knock_in_pct: float,
        coupon_value: float, n_paths: int, vol_model: str, vol_window: int,
        r_eff: float, greek_eps: float, allow_short: bool, ki_liquidation: bool,
    ) -> float:
        """单合约滚动模式."""

        contract_terminated_today = False

        # 1. 检查存续合约的 KO/KI/到期
        if active:
            c = active[0]
            if not c.settled:
                if current_price >= c.KO_abs:
                    c.knocked_out = True
                    c.settled = True
                    contract_terminated_today = True
                if current_price <= c.KI_abs:
                    c.knocked_in = True
                    if ki_liquidation:
                        c.settled = True
                if not c.settled and current_date >= c.maturity_date:
                    c.settled = True
                    contract_terminated_today = True

        # 2. 归档已结算合约
        if active and active[0].settled:
            self._history[asset].append(active.pop(0))

        # 3. 开新合约（终止当天不开，等下一交易日；KI清算立即替换）
        if not active:
            if not contract_terminated_today:
                new_c = self._open_contract(
                    asset, current_date, current_price, asset_prices,
                    maturity_days, knock_out_pct, knock_in_pct,
                    coupon_value, vol_model, vol_window,
                )
                active.append(new_c)

        # 4. 无活跃合约（间隙日）
        if not active:
            return 0.0

        # 5. 定价 → Delta
        c = active[0]
        T_total = (c.maturity_date - c.start_date).days / 365.0
        T_remain = max((c.maturity_date - current_date).days / 365.0, 1.0 / 365.0)

        delta_coef = _evaluate_contract(
            S=current_price, r=r_eff, sigma=c.sigma, T_remain=T_remain,
            KO_abs=c.KO_abs, KI_abs=c.KI_abs, coupon_annual=c.coupon_annual,
            maturity_years=T_total, S0_contract=c.initial_spot,
            n_paths=n_paths, seed=c.pricing_seed, eps=greek_eps,
            already_knocked_in=c.knocked_in, allow_short=allow_short,
        )
        return delta_coef

    def _process_multi(
        self, asset: str, current_date: pd.Timestamp, current_price: float,
        asset_prices: pd.Series, active: List[_Contract],
        maturity_days: int, knock_out_pct: float, knock_in_pct: float,
        coupon_value: float, num_contracts: int, deploy_interval: int,
        n_paths: int, vol_model: str, vol_window: int, r_eff: float,
        greek_eps: float, allow_short: bool, ki_liquidation: bool,
    ) -> float:
        """多合约并行模式."""

        self._deploy_day_counter[asset] = self._deploy_day_counter.get(asset, 0) + 1
        day_idx = self._deploy_day_counter[asset] - 1

        deploy_done = self._deployed_count[asset] >= num_contracts
        pending = 0

        # 1. 检查所有合约 KO/KI/到期
        terminated_today = []
        ki_liquidated = []
        for c in active:
            if c.settled:
                continue
            if current_price >= c.KO_abs:
                c.knocked_out = True
                c.settled = True
                terminated_today.append(c)
            if current_price <= c.KI_abs:
                c.knocked_in = True
                if ki_liquidation:
                    c.settled = True
                    ki_liquidated.append(c)
            if not c.settled and current_date >= c.maturity_date:
                c.settled = True
                terminated_today.append(c)

        # 2. 归档
        for c in terminated_today + ki_liquidated:
            if c in active:
                active.remove(c)
                self._history[asset].append(c)

        # 2.5 KI 清算立即替换
        for _ in ki_liquidated:
            new_c = self._open_contract(
                asset, current_date, current_price, asset_prices,
                maturity_days, knock_out_pct, knock_in_pct,
                coupon_value, vol_model, vol_window,
            )
            active.append(new_c)
            if not deploy_done:
                self._deployed_count[asset] += 1
                if self._deployed_count[asset] >= num_contracts:
                    deploy_done = True

        # 3. 建仓调度
        if not deploy_done:
            deploy_day_indices = set(range(0, num_contracts * deploy_interval, deploy_interval))
            if day_idx in deploy_day_indices:
                pending += 1
        else:
            shortage = num_contracts - len(active)
            pending = max(pending, shortage)

        # 4. 执行建仓（KO/到期终止当天不开新约）
        if not terminated_today:
            while pending > 0:
                new_c = self._open_contract(
                    asset, current_date, current_price, asset_prices,
                    maturity_days, knock_out_pct, knock_in_pct,
                    coupon_value, vol_model, vol_window,
                )
                active.append(new_c)
                pending -= 1
                self._deployed_count[asset] += 1
                if self._deployed_count[asset] >= num_contracts:
                    deploy_done = True

        # 5. 定价：所有活跃合约取平均 Delta
        if not active:
            return 0.0

        total_coef = 0.0
        for c in active:
            T_total = (c.maturity_date - c.start_date).days / 365.0
            T_remain = max((c.maturity_date - current_date).days / 365.0, 1.0 / 365.0)
            coef = _evaluate_contract(
                S=current_price, r=r_eff, sigma=c.sigma, T_remain=T_remain,
                KO_abs=c.KO_abs, KI_abs=c.KI_abs, coupon_annual=c.coupon_annual,
                maturity_years=T_total, S0_contract=c.initial_spot,
                n_paths=n_paths, seed=c.pricing_seed, eps=greek_eps,
                already_knocked_in=c.knocked_in, allow_short=allow_short,
            )
            total_coef += coef

        return total_coef / len(active)

    # ------------------------------------------------------------------
    # 开新合约
    # ------------------------------------------------------------------

    def _open_contract(
        self, asset: str, date: pd.Timestamp, spot: float,
        asset_prices: pd.Series, maturity_days: int,
        knock_out_pct: float, knock_in_pct: float, coupon_value: float,
        vol_model: str, vol_window: int,
    ) -> _Contract:
        """成立新合约.

        到期日对齐原型：取 >= (成立日+maturity_days) 的下一交易日
        （用 asset_prices 的交易日索引近似，原型 _find_next_trading_day 同语义）。
        """
        maturity_calendar = date + pd.Timedelta(days=maturity_days)
        future = asset_prices.index[asset_prices.index >= maturity_calendar]
        maturity = future[0] if len(future) > 0 else maturity_calendar

        # 计算波动率
        close_arr = asset_prices.values[-vol_window - 1:]
        if vol_model == "ewma":
            sigma = _compute_ewma_volatility(close_arr)
        else:
            sigma = _compute_historical_volatility(close_arr, vol_window)

        # 合约级定价种子（基于成立日期确定性生成，对齐原型仅用日期）。
        # 使用 zlib.crc32 稳定哈希（Python 内置 hash() 每进程随机，不可复现），
        # 保证同一合约在回测/监控/跨进程重启下定价种子一致。
        contract_seed = zlib.crc32(date.strftime('%Y%m%d').encode('utf-8')) % (2 ** 31)

        return _Contract(
            start_date=date,
            maturity_date=maturity,
            initial_spot=spot,
            KO_abs=spot * knock_out_pct,
            KI_abs=spot * knock_in_pct,
            coupon_annual=coupon_value,
            sigma=sigma,
            pricing_seed=contract_seed,
        )

    # ------------------------------------------------------------------
    # 参数 Schema
    # ------------------------------------------------------------------

    @classmethod
    def get_param_schema(cls):
        """返回类雪球 Delta 对冲策略的参数 Schema."""
        from app.allocation.models.param_schema import StrategyParamSchema, ParamSchema

        return StrategyParamSchema(
            strategy_type="snowball_delta_hedge",
            display_name="类雪球Delta对冲",
            description=(
                "通过蒙特卡洛定价计算雪球期权Delta，动态调整ETF仓位复制雪球结构收益。"
                "支持单合约滚动/多合约并行，KO赚票息、KI后做空对冲。"
            ),
            internal_leverage=True,  # 仓位由 delta_coef 决定，Pipeline 不再缩放
            # 当日收盘价定价+当日成交（对齐四象限原型 snowball_engine 日循环语义）
            signal_timing="execution_bar",
            snapshot_weight_source="target",  # 权重可为负（做空对冲），市值归一化会失真
            composition={"selector": None, "allocator": "snowball_delta_hedge", "controller": None},
            params=[
                # === 核心参数（合约结构）===
                ParamSchema(
                    name="maturity_days",
                    label="合约期限(天)",
                    type="number",
                    default=180,
                    min_value=30,
                    max_value=365,
                    step=10,
                    description="雪球合约期限（自然日），到期后自动滚动开新约",
                    group="core",
                ),
                ParamSchema(
                    name="knock_out_pct",
                    label="敲出障碍(%)",
                    type="number",
                    default=1.15,
                    min_value=1.01,
                    max_value=1.50,
                    step=0.01,
                    description="相对期初价的敲出比例，如1.15表示涨15%触发敲出",
                    group="core",
                ),
                ParamSchema(
                    name="knock_in_pct",
                    label="敲入障碍(%)",
                    type="number",
                    default=0.80,
                    min_value=0.50,
                    max_value=0.99,
                    step=0.01,
                    description="相对期初价的敲入比例，如0.80表示跌20%触发敲入",
                    group="core",
                ),
                ParamSchema(
                    name="coupon_value",
                    label="年化票息(%)",
                    type="number",
                    default=0.06,
                    min_value=0.01,
                    max_value=0.30,
                    step=0.005,
                    description="年化票息率，KO或未触发时获得的收益",
                    group="core",
                ),
                # === 核心参数（滚动模式）===
                ParamSchema(
                    name="rolling_mode",
                    label="合约滚动模式",
                    type="select",
                    default="single",
                    options=[("single", "单合约滚动"), ("multi", "多合约并行")],
                    description="single=一只接一只；multi=多只同时运行分散时点风险",
                    group="core",
                ),
                ParamSchema(
                    name="num_contracts",
                    label="并行合约数",
                    type="number",
                    default=24,
                    min_value=2,
                    max_value=100,
                    step=1,
                    description="多合约并行模式下的目标合约数量",
                    group="core",
                    condition={"field": "rolling_mode", "value": "multi"},
                ),
                ParamSchema(
                    name="deploy_interval",
                    label="建仓间隔(交易日)",
                    type="number",
                    default=5,
                    min_value=1,
                    max_value=20,
                    step=1,
                    description="多合约建仓阶段每隔N个交易日建一只新合约",
                    group="core",
                    condition={"field": "rolling_mode", "value": "multi"},
                ),
                # === 高级参数（定价引擎）===
                ParamSchema(
                    name="n_paths",
                    label="MC模拟路径数",
                    type="number",
                    default=10000,
                    min_value=1000,
                    max_value=100000,
                    step=1000,
                    description="蒙特卡洛模拟路径数，越多越精确但越慢",
                    group="advanced",
                ),
                ParamSchema(
                    name="vol_model",
                    label="波动率模型",
                    type="select",
                    default="historical",
                    options=[("historical", "历史波动率"), ("ewma", "EWMA指数加权")],
                    description="波动率估计方法，EWMA对近期波动反应更快",
                    group="advanced",
                ),
                ParamSchema(
                    name="vol_window",
                    label="波动率窗口(日)",
                    type="number",
                    default=252,
                    min_value=20,
                    max_value=500,
                    step=10,
                    description="计算历史波动率的回溯窗口（交易日）",
                    group="advanced",
                ),
                ParamSchema(
                    name="risk_free_rate",
                    label="无风险利率",
                    type="number",
                    default=0.013,
                    min_value=0.0,
                    max_value=0.10,
                    step=0.001,
                    description="年化无风险利率，用于MC定价折现",
                    group="advanced",
                ),
                ParamSchema(
                    name="greek_eps",
                    label="Delta微分步长",
                    type="number",
                    default=0.005,
                    min_value=0.001,
                    max_value=0.05,
                    step=0.001,
                    description="数值微分计算Delta的相对步长ε",
                    group="advanced",
                ),
                # === 高级参数（风控）===
                ParamSchema(
                    name="allow_short",
                    label="允许做空",
                    type="boolean",
                    default=True,
                    description="KI后Delta为负需做空对冲；关闭则仓位限制在[0,1]（A股融券受限假设）",
                    group="advanced",
                ),
                ParamSchema(
                    name="ki_liquidation",
                    label="KI立即清算",
                    type="boolean",
                    default=False,
                    description="敲入后是否立即清算合约并开新约（无间隙日）；关闭则继续持有至到期/KO",
                    group="advanced",
                ),
            ],
        )
