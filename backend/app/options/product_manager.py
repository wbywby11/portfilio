# -*- coding: utf-8 -*-
"""
产品生命周期管理模块

自动检测敲出/敲入事件，管理产品状态流转，记录事件。
计算逻辑从 options_pricing/product_manager.py 迁入，import 路径已更新。
"""

from datetime import date
from enum import Enum
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.options.data_loader import ProductRecord, MarketDataRecord


# ── 事件类型 ──────────────────────────────────────────

class LifecycleEvent(Enum):
    """产品生命周期事件类型"""
    KNOCK_OUT = "knock_out"      # 敲出
    KNOCK_IN = "knock_in"        # 敲入
    MATURITY = "maturity"        # 自然到期
    STATUS_CHANGE = "status_change"  # 手动状态变更


@dataclass
class ProductEvent:
    """产品事件记录"""
    product_id: str
    event_type: str
    event_date: str
    spot: float
    barrier_level: float
    description: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── 生命周期检测引擎 ──────────────────────────────────

class ProductLifecycleManager:
    """产品生命周期管理器

    职责：
    1. 检测敲出/敲入事件
    2. 更新产品状态
    3. 返回事件列表（由 Service 层负责持久化到 MongoDB）
    """

    def check_products(self, products: List['ProductRecord'],
                       market_data: Dict[str, 'MarketDataRecord'],
                       val_date: date,
                       state_map: Optional[Dict[str, dict]] = None,
                       trade_dates: Optional[List[str]] = None) -> List[ProductEvent]:
        """检测所有产品的生命周期事件

        Args:
            products: 产品列表
            market_data: 当日市场数据 {underlying: MarketDataRecord}
            val_date: 估值日期
            state_map: 运行时状态映射 {product_id: {"status": ...}}（来自 MongoDB）
            trade_dates: 交易日历列表 (YYYY-MM-DD 字符串)，用于观察日判定；
                        为 None 时回退为自然日判定（向后兼容）

        Returns:
            检测到的事件列表
        """
        events = []
        state_map = state_map or {}

        # 预处理交易日历：构建 set + sorted list + 按月分组
        self._td_set = set()
        self._td_sorted = []
        self._td_by_month = {}  # {(year, month): [day1, day2, ...]}
        if trade_dates:
            for ds in trade_dates:
                d = date.fromisoformat(ds) if isinstance(ds, str) else ds
                ds_str = d.isoformat()
                self._td_set.add(ds_str)
                self._td_sorted.append(d)
                key = (d.year, d.month)
                self._td_by_month.setdefault(key, []).append(d)
            self._td_sorted.sort()

        for prod in products:
            # 跳过已终结的产品
            runtime_status = state_map.get(prod.id, {}).get("status")
            if runtime_status in ("knocked_out", "matured"):
                continue

            # 检查到期
            if val_date >= prod.maturity_date:
                event = ProductEvent(
                    product_id=prod.id,
                    event_type=LifecycleEvent.MATURITY.value,
                    event_date=val_date.isoformat(),
                    spot=0.0,
                    barrier_level=0.0,
                    description=f"{prod.name} 到期（{prod.maturity_date.isoformat()}）"
                )
                events.append(event)
                prod.status = "matured"
                continue

            # 获取市场数据
            market = market_data.get(prod.underlying)
            if market is None:
                continue

            # 按产品类型检测
            if prod.type == "snowball":
                evts = self._check_snowball(prod, market, val_date)
                events.extend(evts)
            elif prod.type == "phoenix":
                evts = self._check_phoenix(prod, market, val_date)
                events.extend(evts)
            # 注：sharkfin/double_barrier 为每日检测，不需要观察日判定
            elif prod.type == "sharkfin":
                evts = self._check_sharkfin(prod, market, val_date)
                events.extend(evts)
            elif prod.type == "double_barrier":
                evts = self._check_double_barrier(prod, market, val_date)
                events.extend(evts)

        return events

    def _check_snowball(self, prod, market, val_date: date) -> List[ProductEvent]:
        """雪球：月度观察日敲出 + 每日敲入"""
        events = []
        params = prod.params
        spot_ref = params.get("spot_ref", market.spot)
        knock_out = params.get("knock_out", 1.03)
        knock_in = params.get("knock_in", 0.78)
        obs_freq = params.get("obs_freq", "monthly")

        ko_level = spot_ref * knock_out
        ki_level = spot_ref * knock_in
        spot = market.spot

        if self._is_observation_day(prod, val_date, obs_freq):
            if spot >= ko_level:
                event = ProductEvent(
                    product_id=prod.id,
                    event_type=LifecycleEvent.KNOCK_OUT.value,
                    event_date=val_date.isoformat(),
                    spot=spot, barrier_level=ko_level,
                    description=f"{prod.name} 触及敲出价 {ko_level:.2f}（当前 {spot:.2f}）"
                )
                events.append(event)
                prod.status = "knocked_out"
                return events

        if spot <= ki_level:
            event = ProductEvent(
                product_id=prod.id,
                event_type=LifecycleEvent.KNOCK_IN.value,
                event_date=val_date.isoformat(),
                spot=spot, barrier_level=ki_level,
                description=f"{prod.name} 触及敲入价 {ki_level:.2f}（当前 {spot:.2f}）"
            )
            events.append(event)
            prod.status = "knocked_in"

        return events

    def _check_phoenix(self, prod, market, val_date: date) -> List[ProductEvent]:
        """凤凰：月度观察日敲出 + 观察日敲入"""
        events = []
        params = prod.params
        spot_ref = params.get("spot_ref", market.spot)
        knock_out = params.get("knock_out", 1.03)
        knock_in = params.get("knock_in", 0.78)
        obs_freq = params.get("obs_freq", "monthly")

        ko_level = spot_ref * knock_out
        ki_level = spot_ref * knock_in
        spot = market.spot

        if not self._is_observation_day(prod, val_date, obs_freq):
            return events

        if spot >= ko_level:
            event = ProductEvent(
                product_id=prod.id,
                event_type=LifecycleEvent.KNOCK_OUT.value,
                event_date=val_date.isoformat(),
                spot=spot, barrier_level=ko_level,
                description=f"{prod.name} 触及敲出价 {ko_level:.2f}（当前 {spot:.2f}）"
            )
            events.append(event)
            prod.status = "knocked_out"
            return events

        if spot <= ki_level:
            event = ProductEvent(
                product_id=prod.id,
                event_type=LifecycleEvent.KNOCK_IN.value,
                event_date=val_date.isoformat(),
                spot=spot, barrier_level=ki_level,
                description=f"{prod.name} 触及敲入价 {ki_level:.2f}（当前 {spot:.2f}）"
            )
            events.append(event)
            prod.status = "knocked_in"

        return events

    def _check_sharkfin(self, prod, market, val_date: date) -> List[ProductEvent]:
        """鲨鱼鳍：每日敲出检测（无敲入）"""
        events = []
        params = prod.params
        spot_ref = params.get("spot_ref", market.spot)
        knock_out_ratio = params.get("knock_out_ratio", 1.10)

        ko_level = spot_ref * knock_out_ratio
        spot = market.spot

        if spot >= ko_level:
            event = ProductEvent(
                product_id=prod.id,
                event_type=LifecycleEvent.KNOCK_OUT.value,
                event_date=val_date.isoformat(),
                spot=spot, barrier_level=ko_level,
                description=f"{prod.name} 触及敲出价 {ko_level:.2f}（当前 {spot:.2f}）"
            )
            events.append(event)
            prod.status = "knocked_out"

        return events

    def _check_double_barrier(self, prod, market, val_date: date) -> List[ProductEvent]:
        """双鲨：每日双边敲出检测"""
        events = []
        params = prod.params
        spot_ref = params.get("spot_ref", market.spot)
        barrier_low = params.get("barrier_low", 0.85)
        barrier_high = params.get("barrier_high", 1.15)

        low_level = spot_ref * barrier_low
        high_level = spot_ref * barrier_high
        spot = market.spot

        knocked = False
        barrier = 0.0
        if spot >= high_level:
            barrier = high_level
            knocked = True
        elif spot <= low_level:
            barrier = low_level
            knocked = True

        if knocked:
            event = ProductEvent(
                product_id=prod.id,
                event_type=LifecycleEvent.KNOCK_OUT.value,
                event_date=val_date.isoformat(),
                spot=spot, barrier_level=barrier,
                description=f"{prod.name} 触及障碍价 {barrier:.2f}（当前 {spot:.2f}）"
            )
            events.append(event)
            prod.status = "knocked_out"

        return events

    def _is_observation_day(self, prod, val_date: date, obs_freq: str) -> bool:
        """判断是否为观察日

        基于交易日历判定：
        - daily: 当且仅当 val_date 是交易日
        - weekly: 每 5 个交易日为一个观察周期（从发行日起算）
        - monthly: 每月第 N 个交易日（N = 发行日在发行月中的交易日序号）

        若无交易日历数据，回退为自然日判定以保持向后兼容。
        """
        td_set = getattr(self, '_td_set', None)
        td_sorted = getattr(self, '_td_sorted', None)
        td_by_month = getattr(self, '_td_by_month', None)

        # 无交易日历时回退为自然日判定
        if not td_set:
            if obs_freq == "daily":
                return True
            elif obs_freq == "weekly":
                return val_date.weekday() == prod.issue_date.weekday()
            else:  # monthly
                return val_date.day == prod.issue_date.day

        # 非交易日一定不是观察日
        if val_date.isoformat() not in td_set:
            return False

        if obs_freq == "daily":
            return True

        elif obs_freq == "weekly":
            # 每 5 个交易日检查一次（从发行日的交易日位置起算）
            issue_key = (prod.issue_date.year, prod.issue_date.month)
            issue_month_days = td_by_month.get(issue_key, [])
            # 找到发行日在发行月交易日中的序号（1-based）
            issue_weekday_idx = prod.issue_date.weekday()  # 0=Monday
            # 简化：用发行日的 weekday 在交易日序列中定位，每 5 个交易日一次
            if val_date in td_sorted:
                val_idx = td_sorted.index(val_date)
                # 找到发行日在 td_sorted 中的位置
                try:
                    issue_idx = td_sorted.index(prod.issue_date)
                except ValueError:
                    # 发行日不在交易日历中（如周末发行），找最近的交易日
                    issue_idx = val_idx  # fallback
                diff = val_idx - issue_idx
                return diff >= 0 and diff % 5 == 0
            return False

        else:  # monthly
            # 每月第 N 个交易日
            # N = issue_date 在发行月交易日列表中的序号（1-based）
            issue_key = (prod.issue_date.year, prod.issue_date.month)
            issue_month_days = td_by_month.get(issue_key, [])
            if not issue_month_days:
                return False
            # 发行日的交易日序号
            try:
                n = issue_month_days.index(prod.issue_date) + 1
            except ValueError:
                # 发行日不在交易日历中（如周末），取同月最近的交易日序号
                n = 1
                for i, d in enumerate(issue_month_days):
                    if d >= prod.issue_date:
                        n = i + 1
                        break
                else:
                    n = len(issue_month_days)

            # 检查 val_date 是否是当月第 n 个交易日
            val_key = (val_date.year, val_date.month)
            val_month_days = td_by_month.get(val_key, [])
            if not val_month_days:
                return False
            if n <= len(val_month_days):
                return val_date == val_month_days[n - 1]
            # 当月交易日不足 n 个时，取最后一个交易日
            return val_date == val_month_days[-1]


def print_lifecycle_report(events: List[ProductEvent]):
    """打印生命周期检测报告"""
    if not events:
        return

    for e in events:
        icon = {"knock_out": "KO", "knock_in": "KI", "maturity": "MAT"}.get(e.event_type, "INFO")
        print(f"  [{icon}] [{e.product_id}] {e.description}")
