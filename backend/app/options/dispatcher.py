# -*- coding: utf-8 -*-
"""
定价派发器：根据产品类型路由到对应的 Pricer，返回结构化估值结果。

从 options_pricing/run_daily.py 提取核心逻辑，import 路径已更新。
计算逻辑零修改。
"""

from datetime import date, datetime
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
from dataclasses import field

import numpy as np

from app.options.core import (
    OptionPricer, MarketParams, PricingResult,
    SpreadOptionPricer, BinaryOptionPricer,
    BarrierOptionPricer, FixedIncomePricer,
    SnowballPricer, SnowballParams,
    PhoenixPricer, PhoenixParams,
    DoubleBarrierPricer,
    AsianOptionPricer, AsianParams,
    RainbowPricer, RainbowParams,
    RangeAccrualPricer, RangeAccrualParams,
    CallableFixedPricer, CallableFixedParams,
    DigitalRangePricer, DigitalRangeParams,
    BinomialTreePricer, BinomialTreeParams,
    FiniteDifferencePricer, FiniteDifferenceParams,
    SABRVolSurface, SABRParams,
    LocalVolPricer, LocalVolParams,
)
from app.options.data_loader import ProductRecord, MarketDataRecord, get_vol
from app.options.config import DEFAULT_N_PATHS, DEFAULT_MC_SEED


# ── 估值结果结构 ──────────────────────────────────────

@dataclass
class ValuationRecord:
    """单产品估值结果"""
    product_id: str
    name: str
    type: str
    issuer: str
    date: str
    status: str
    principal: float
    underlying: str
    price_total: float          # 总估值（元）
    fixed_part: float = 0.0     # 固定收益部分
    option_part: float = 0.0    # 期权部分
    spot: float = 0.0
    vol: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    rho: float = 0.0
    method: str = ""
    error: str = ""


# ── 定价派发器 ────────────────────────────────────────

class PricingDispatcher:
    """根据产品类型派发到对应的 Pricer

    用法:
        dispatcher = PricingDispatcher()
        rec = dispatcher.price_product(product, market, vol_surface=vol_surf)
    """

    def __init__(self):
        self.vanilla = OptionPricer()
        self.spread = SpreadOptionPricer()
        self.binary = BinaryOptionPricer()
        self.barrier = BarrierOptionPricer()
        self.fixed = FixedIncomePricer()
        self.snowball = SnowballPricer(n_paths=DEFAULT_N_PATHS)
        self.phoenix = PhoenixPricer(n_paths=DEFAULT_N_PATHS)
        self.double_barrier = DoubleBarrierPricer()
        self.asian = AsianOptionPricer(n_paths=DEFAULT_N_PATHS)
        self.rainbow = RainbowPricer(n_paths=DEFAULT_N_PATHS)
        self.range_accrual = RangeAccrualPricer(n_paths=DEFAULT_N_PATHS)
        self.callable_fixed = CallableFixedPricer()
        self.digital_range = DigitalRangePricer()
        # 高级定价器
        self.binomial = BinomialTreePricer()
        self.finite_diff = FiniteDifferencePricer()
        self.sabr = SABRVolSurface()
        self.local_vol = LocalVolPricer()

    def validate_record(self, rec: ValuationRecord, product) -> List[str]:
        """估值结果校验

        Returns:
            List[str]: 告警信息列表（空=正常）
        """
        warnings = []
        if rec.price_total > product.principal * 2.0 and rec.method not in ("skipped", "knocked_out", "matured", "expired"):
            warnings.append(f"估值异常偏高: {rec.price_total:,.0f} > 2x本金")
        if rec.price_total < 0:
            warnings.append(f"估值为负: {rec.price_total:,.0f}")
        if product.type == "fixed" and rec.method == "discount":
            ratio = rec.price_total / product.principal if product.principal > 0 else 0
            if not (0.90 < ratio < 1.15):
                warnings.append(f"固收估值偏离本金: {ratio:.2%}")
        return warnings

    def price_product(self, product, market, vol_surface=None) -> ValuationRecord:
        """对单个产品定价

        Args:
            product: ProductRecord
            market: MarketDataRecord
            vol_surface: 可选的 VolSurface 对象（用于波动率曲面插值）

        Returns:
            ValuationRecord
        """
        val_date = market.date
        rec = ValuationRecord(
            product_id=product.id,
            name=product.name,
            type=product.type,
            issuer=product.issuer,
            date=val_date.isoformat(),
            status=product.status,
            principal=product.principal,
            underlying=product.underlying,
            price_total=0.0,
        )

        try:
            # 非 active 状态处理
            if product.status == "pending":
                rec.price_total = 0.0
                rec.method = "skipped"
                return rec

            if product.status == "knocked_out":
                rec.price_total = product.principal
                rec.method = "knocked_out"
                return rec

            if product.status == "matured":
                rec.price_total = product.principal
                rec.method = "matured"
                return rec

            # 剩余期限
            remaining_days = (product.maturity_date - val_date).days
            tau = max(0, remaining_days / 365.0)
            if tau <= 0:
                rec.price_total = product.principal
                rec.method = "expired"
                return rec

            # 基础市场参数（利率曲线：根据剩余期限插值）
            rate = market.get_rate(tau)
            div = market.dividend_yield
            spot = market.spot
            vol = get_vol(market, remaining_days, moneyness=1.0, vol_surface=vol_surface)
            rec.spot = spot
            rec.vol = vol

            # 按类型路由
            if product.type == "fixed":
                rec = self._price_fixed(product, rec, rate, val_date)
            elif product.type == "binary":
                rec = self._price_binary(product, rec, spot, rate, div, vol, tau)
            elif product.type == "spread":
                rec = self._price_spread(product, rec, spot, rate, div, vol, tau)
            elif product.type == "sharkfin":
                rec = self._price_sharkfin(product, rec, spot, rate, div, vol, tau)
            elif product.type == "snowball":
                rec = self._price_snowball(product, rec, spot, rate, div, vol, tau)
            elif product.type == "phoenix":
                rec = self._price_phoenix(product, rec, spot, rate, div, vol, tau)
            elif product.type == "double_barrier":
                rec = self._price_double_barrier(product, rec, spot, rate, div, vol, tau)
            elif product.type == "asian":
                rec = self._price_asian(product, rec, spot, rate, div, vol, tau)
            elif product.type == "rainbow":
                rec = self._price_rainbow(product, rec, spot, rate, div, vol, tau)
            elif product.type == "range_accrual":
                rec = self._price_range_accrual(product, rec, spot, rate, div, vol, tau)
            elif product.type == "callable_fixed":
                rec = self._price_callable_fixed(product, rec, rate, val_date)
            elif product.type == "digital_range":
                rec = self._price_digital_range(product, rec, spot, rate, div, vol, tau)
            elif product.type == "american_option":
                rec = self._price_american_option(product, rec, spot, rate, div, vol, tau)
            elif product.type == "fd_option":
                rec = self._price_fd_option(product, rec, spot, rate, div, vol, tau)
            elif product.type == "local_vol_option":
                rec = self._price_local_vol_option(product, rec, spot, rate, div, vol, tau)
            else:
                rec.error = f"不支持的产品类型: {product.type}"

        except Exception as e:
            rec.error = str(e)

        return rec

    def _price_fixed(self, product, rec, rate, val_date) -> ValuationRecord:
        """固定收益定价"""
        pv = self.fixed.present_value(
            product.principal, product.params.get("coupon_rate", 0),
            product.issue_date, val_date, product.maturity_date, rate,
        )
        rec.price_total = pv
        rec.fixed_part = pv
        rec.method = "discount"
        return rec

    def _price_binary(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """二元结构定价"""
        params = product.params
        strike = params.get("strike", spot)
        high_return = params.get("high_return", 0.05)
        low_return = params.get("low_return", 0.005)

        mp = MarketParams(spot, strike, tau, vol, rate, div)
        binary_call = self.binary.call(mp)

        Dr = np.exp(-rate * tau)
        fixed_part = product.principal * Dr * (1 + low_return * tau)
        option_part = product.principal * (high_return - low_return) * tau * Dr * binary_call

        rec.price_total = fixed_part + option_part
        rec.fixed_part = fixed_part
        rec.option_part = option_part
        rec.method = "binary_analytic"
        return rec

    def _price_spread(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """价差结构定价"""
        params = product.params
        k_low = params.get("strike_low", spot * 0.95)
        k_high = params.get("strike_high", spot * 1.05)
        direction = params.get("direction", "bull")

        mp = MarketParams(spot, k_low, tau, vol, rate, div)

        if direction == "bull":
            result = self.spread.call_spread(mp, k_high)
        else:
            result = self.spread.put_spread(mp, k_high)

        Dr = np.exp(-rate * tau)
        fixed_part = product.principal * Dr
        n_units = product.principal / k_low
        option_part = n_units * result.price

        rec.price_total = fixed_part + option_part
        rec.fixed_part = fixed_part
        rec.option_part = option_part
        rec.delta = result.delta * n_units
        rec.gamma = result.gamma * n_units
        rec.vega = result.vega * n_units
        rec.theta = result.theta * n_units
        rec.method = "spread_analytic"
        return rec

    def _price_sharkfin(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """鲨鱼鳍结构定价（保底 + 向上敲出看涨）"""
        params = product.params
        spot_ref = params.get("spot_ref", spot)
        strike = params.get("strike", spot_ref)
        knock_out_ratio = params.get("knock_out_ratio", 1.10)
        participation = params.get("participation", 0.80)
        guaranteed = params.get("guaranteed", 1.0)

        barrier_level = knock_out_ratio * spot_ref
        barrier_level = BarrierOptionPricer.discrete_monitoring_correction(
            barrier_level, vol, tau, monitoring_freq=252, direction="up"
        )

        mp = MarketParams(spot, strike, tau, vol, rate, div)
        uo_call = self.barrier.up_and_out_call(mp, barrier=barrier_level)

        Dr = np.exp(-rate * tau)
        fixed_part = product.principal * guaranteed * Dr
        option_part = product.principal * participation * uo_call / spot_ref

        rec.price_total = fixed_part + option_part
        rec.fixed_part = fixed_part
        rec.option_part = option_part
        rec.method = "sharkfin_analytic"

        try:
            greeks = self.barrier.greeks(mp, barrier=barrier_level, option_type="uo_call")
            scale = product.principal * participation / spot_ref
            rec.delta = greeks["delta"] * scale
            rec.gamma = greeks["gamma"] * scale
            rec.vega = greeks["vega"] * scale
            rec.theta = greeks["theta"] * scale
            rec.rho = greeks["rho"] * scale
        except Exception:
            pass

        return rec

    def _price_snowball(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """雪球结构定价（MC）"""
        params = product.params
        spot_ref = params.get("spot_ref", spot)
        knock_out = params.get("knock_out", 1.03)
        knock_in = params.get("knock_in", 0.78)
        coupon_year = params.get("coupon_year", 0.20)
        obs_freq = params.get("obs_freq", "monthly")
        recovery_coupon_rate = params.get("recovery_coupon_rate", 0.0)
        use_cv = params.get("use_control_variate", True)

        sp = SnowballParams(
            spot_ref=spot_ref, knock_out=knock_out, knock_in=knock_in,
            coupon_year=coupon_year, tau=tau, obs_freq=obs_freq,
            vol=vol, r=rate, q=div,
            recovery_coupon_rate=recovery_coupon_rate,
            use_control_variate=use_cv,
        )

        result = self.snowball.price(sp, return_details=True)
        scale = product.principal / spot_ref
        rec.price_total = result["price"] * scale
        rec.fixed_part = 0.0
        rec.option_part = result["price"] * scale
        rec.spot = spot
        rec.vol = vol
        rec.method = result["method"]

        try:
            greeks = self.snowball.greeks(sp)
            rec.delta = greeks["delta"] * scale
            rec.vega = greeks["vega"] * scale
            rec.theta = greeks["theta"] * scale
            rec.rho = greeks["rho"] * scale
        except Exception:
            pass

        return rec

    def _price_phoenix(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """凤凰结构定价（MC）"""
        params = product.params
        spot_ref = params.get("spot_ref", spot)
        knock_out = params.get("knock_out", 1.03)
        knock_in = params.get("knock_in", 0.78)
        coupon_per_period = params.get("coupon_per_period", 0.015)
        obs_freq = params.get("obs_freq", "monthly")
        memory_flag = params.get("memory_flag", True)
        use_cv = params.get("use_control_variate", True)

        pp = PhoenixParams(
            spot_ref=spot_ref, knock_out=knock_out, knock_in=knock_in,
            coupon_per_period=coupon_per_period, tau=tau,
            obs_freq=obs_freq, memory_flag=memory_flag,
            vol=vol, r=rate, q=div,
            use_control_variate=use_cv,
        )

        result = self.phoenix.price(pp, return_details=True)
        scale = product.principal / spot_ref
        rec.price_total = result["price"] * scale
        rec.fixed_part = 0.0
        rec.option_part = result["price"] * scale
        rec.spot = spot
        rec.vol = vol
        rec.method = result["method"]

        return rec

    def _price_double_barrier(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """双鲨（双边障碍）定价"""
        params = product.params
        spot_ref = params.get("spot_ref", spot)
        strike = params.get("strike", spot_ref)
        barrier_low_pct = params.get("barrier_low", 0.80)
        barrier_high_pct = params.get("barrier_high", 1.20)
        guaranteed = params.get("guaranteed", 1.0)
        participation = params.get("participation", 1.0)

        mp = MarketParams(spot, strike, tau, vol, rate, div)
        barrier_low = barrier_low_pct * spot_ref
        barrier_high = barrier_high_pct * spot_ref

        dko_call = self.double_barrier.price(mp, barrier_low, barrier_high)

        Dr = np.exp(-rate * tau)
        fixed_part = product.principal * guaranteed * Dr
        option_part = product.principal * participation * dko_call / spot_ref

        rec.price_total = fixed_part + option_part
        rec.fixed_part = fixed_part
        rec.option_part = option_part
        rec.spot = spot
        rec.vol = vol
        rec.method = "double_barrier_mc"

        try:
            greeks = self.double_barrier.greeks(mp, barrier_low, barrier_high)
            scale = product.principal * participation / spot_ref
            rec.delta = greeks["delta"] * scale
            rec.gamma = greeks["gamma"] * scale
            rec.vega = greeks["vega"] * scale
            rec.theta = greeks["theta"] * scale
            rec.rho = greeks["rho"] * scale
        except Exception:
            pass

        return rec

    # ── 新增产品类型定价 ──────────────────────────────

    def _price_asian(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """亚式期权定价（本金保障型结构化产品）

        总价值 = 固收部分(本金折现) + 期权部分(嵌入式亚式期权)
        """
        params = product.params
        spot_ref = params.get("spot_ref", spot)
        strike = params.get("strike", spot_ref)
        obs_freq = params.get("obs_freq", "daily")
        avg_type = params.get("avg_type", "arithmetic")
        guaranteed = params.get("guaranteed", 1.0)

        ap = AsianParams(
            spot_ref=spot_ref, strike=strike, tau=tau,
            obs_freq=obs_freq, avg_type=avg_type,
            vol=vol, r=rate, q=div,
        )
        result = self.asian.price(ap, return_details=True)

        # 固收部分: 本金保障 × 折现
        Dr = np.exp(-rate * tau)
        rec.fixed_part = product.principal * guaranteed * Dr

        # 期权部分: 亚式期权每单位标的的价值 × 本金可购买的标的单位数
        units = product.principal / spot_ref if spot_ref else 1
        rec.option_part = result["price"] * units
        rec.price_total = rec.fixed_part + rec.option_part
        rec.method = result["method"]

        try:
            greeks = self.asian.greeks(ap)
            rec.delta = greeks["delta"] * units
            rec.vega = greeks["vega"] * units
            rec.theta = greeks["theta"] * units
        except Exception:
            pass

        return rec

    def _price_rainbow(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """彩虹期权定价（多标的挂钩）"""
        params = product.params
        spots = params.get("spots", [spot])
        strikes = params.get("strikes", [spot])
        vols = params.get("vols", [vol])
        correlations = params.get("correlations", [[1.0]])
        payoff_type = params.get("payoff_type", "best_of")

        rp = RainbowParams(
            spots=spots, strikes=strikes, tau=tau,
            vols=vols, correlations=correlations,
            payoff_type=payoff_type, r=rate, q=div,
        )
        result = self.rainbow.price(rp, return_details=True)
        rec.price_total = result["price"] * product.principal
        rec.option_part = rec.price_total
        rec.method = result["method"]
        return rec

    def _price_range_accrual(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """区间累积期权定价"""
        params = product.params
        spot_ref = params.get("spot_ref", spot)
        lower = params.get("lower_barrier", spot_ref * 0.95)
        upper = params.get("upper_barrier", spot_ref * 1.05)
        coupon_rate = params.get("coupon_rate", 0.05)
        obs_freq = params.get("obs_freq", "daily")

        rap = RangeAccrualParams(
            spot_ref=spot_ref, lower_barrier=lower, upper_barrier=upper,
            coupon_rate=coupon_rate, tau=tau, obs_freq=obs_freq,
            vol=vol, r=rate, q=div,
        )
        result = self.range_accrual.price(rap, return_details=True)
        scale = product.principal / spot_ref if spot_ref else 1
        rec.price_total = result["price"] * scale
        rec.fixed_part = result.get("fixed_part", 0) * scale
        rec.option_part = result.get("option_part", 0) * scale
        rec.method = result["method"]

        try:
            greeks = self.range_accrual.greeks(rap)
            rec.delta = greeks["delta"] * scale
            rec.vega = greeks["vega"] * scale
            rec.theta = greeks["theta"] * scale
        except Exception:
            pass

        return rec

    def _price_callable_fixed(self, product, rec, rate, val_date) -> ValuationRecord:
        """可赎回固收定价"""
        params = product.params
        coupon_rate = params.get("coupon_rate", 0.04)
        call_date_years = params.get("call_date", 1.0)
        call_price = params.get("call_price", product.principal)
        rate_vol = params.get("rate_vol", 0.01)
        tau = (product.maturity_date - val_date).days / 365.0

        cfp = CallableFixedParams(
            principal=product.principal, coupon_rate=coupon_rate,
            tau=max(tau, 0), call_date=call_date_years,
            call_price=call_price, r=rate, rate_vol=rate_vol,
        )
        result = self.callable_fixed.price(cfp, return_details=True)
        rec.price_total = result["price"]
        rec.fixed_part = result["price"]
        rec.method = result["method"]

        try:
            greeks = self.callable_fixed.greeks(cfp)
            rec.rho = greeks["dv01"]
        except Exception:
            pass

        return rec

    def _price_digital_range(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """数字区间期权定价（本金保障型结构化产品）

        总价值 = 固收部分(本金折现) + 期权部分(区间内额外收益的折现期望)
        """
        params = product.params
        lower = params.get("lower", spot * 0.95)
        upper = params.get("upper", spot * 1.05)
        payoff = params.get("payoff", product.principal * 0.1)
        guaranteed = params.get("guaranteed", 1.0)

        drp = DigitalRangeParams(
            spot=spot, lower=lower, upper=upper,
            payoff=payoff, tau=tau, r=rate, q=div, vol=vol,
        )
        result = self.digital_range.price(drp, return_details=True)

        # 固收部分: 本金保障 × 折现
        Dr = np.exp(-rate * tau)
        rec.fixed_part = product.principal * guaranteed * Dr

        # 期权部分: 区间内额外收益的折现期望值
        rec.option_part = result["price"]
        rec.price_total = rec.fixed_part + rec.option_part
        rec.method = result["method"]

        try:
            greeks = self.digital_range.greeks(drp)
            rec.delta = greeks["delta"]
            rec.theta = greeks["theta"]
        except Exception:
            pass

        return rec

    # ── 高级定价器路由 ──────────────────────────────

    def _price_american_option(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """美式期权定价（二叉树法）"""
        params = product.params
        strike = params.get("strike", spot)
        option_type = params.get("option_type", "call")
        n_steps = params.get("n_steps", 200)
        exercise_style = params.get("exercise_style", "american")

        btp = BinomialTreeParams(
            spot=spot, strike=strike, tau=tau, vol=vol,
            r=rate, q=div, n_steps=n_steps,
            option_type=option_type, exercise_style=exercise_style,
        )
        result = self.binomial.price(btp, return_details=True)
        scale = product.principal / spot if spot else 1
        rec.price_total = result["price"] * scale
        rec.option_part = result["price"] * scale
        rec.method = result["method"]

        try:
            greeks = self.binomial.greeks(btp)
            rec.delta = greeks["delta"] * scale
            rec.gamma = greeks["gamma"] * scale
            rec.vega = greeks["vega"] * scale
            rec.theta = greeks["theta"] * scale
            rec.rho = greeks["rho"] * scale
        except Exception:
            pass

        return rec

    def _price_fd_option(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """有限差分法定价（PDE 求解）"""
        params = product.params
        strike = params.get("strike", spot)
        option_type = params.get("option_type", "call")
        exercise_style = params.get("exercise_style", "european")
        n_space = params.get("n_space", 200)
        n_time = params.get("n_time", 500)

        fdp = FiniteDifferenceParams(
            spot=spot, strike=strike, tau=tau, vol=vol,
            r=rate, q=div, n_space=n_space, n_time=n_time,
            option_type=option_type, exercise_style=exercise_style,
        )
        result = self.finite_diff.price(fdp, return_details=True)
        scale = product.principal / spot if spot else 1
        rec.price_total = result["price"] * scale
        rec.option_part = result["price"] * scale
        rec.method = result["method"]

        try:
            greeks = self.finite_diff.greeks(fdp)
            rec.delta = greeks["delta"] * scale
            rec.vega = greeks["vega"] * scale
            rec.theta = greeks["theta"] * scale
        except Exception:
            pass

        return rec

    def _price_local_vol_option(self, product, rec, spot, rate, div, vol, tau) -> ValuationRecord:
        """局部波动率模型定价（Dupire）"""
        params = product.params
        strike = params.get("strike", spot)
        option_type = params.get("option_type", "call")
        n_space = params.get("n_space", 100)
        n_time = params.get("n_time", 200)

        lvp = LocalVolParams(
            spot=spot, strike=strike, tau=tau,
            r=rate, q=div, n_space=n_space, n_time=n_time,
            option_type=option_type,
        )
        result = self.local_vol.price(lvp, return_details=True)
        scale = product.principal / spot if spot else 1
        rec.price_total = result["price"] * scale
        rec.option_part = result["price"] * scale
        rec.method = result["method"]

        try:
            greeks = self.local_vol.greeks(lvp)
            rec.delta = greeks["delta"] * scale
            rec.theta = greeks["theta"] * scale
        except Exception:
            pass

        return rec
