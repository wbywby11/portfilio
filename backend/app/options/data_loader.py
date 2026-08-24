# -*- coding: utf-8 -*-
"""
数据加载器：产品参数 + 市场数据结构 + 波动率插值 + 波动率曲面

数据层适配：支持从 MongoDB 文档构建 ProductRecord / MarketDataRecord，
也保留原始 YAML/CSV 加载接口（用于独立测试和数据迁移）。

核心数据结构（ProductRecord / MarketDataRecord）与原型完全兼容，
确保 PricingDispatcher / risk.py / vol/ 无需修改。
"""

from datetime import date, datetime
from typing import Dict, List, Optional, TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from app.options.vol.surface import VolSurface

from app.options.config import VOL_TENOR_DAYS, RATE_TENORS, RATE_TENOR_YEARS


# ── 数据结构 ──────────────────────────────────────────

class ProductRecord:
    """单条产品记录（兼容原型 YAML 格式 + MongoDB 文档格式）"""

    def __init__(self, raw: dict):
        self.id: str = raw["id"]
        self.name: str = raw["name"]
        self.type: str = raw["type"]
        self.issuer: str = raw.get("issuer", "")
        self.issue_date: date = self._parse_date(raw["issue_date"])
        self.maturity_date: date = self._parse_date(raw["maturity_date"])
        self.principal: float = float(raw["principal"])
        self.underlying: str = raw["underlying"]
        self.status: str = raw.get("status", "active")
        self.params: dict = raw.get("params", {})
        self.knock_out_date: Optional[date] = None
        if raw.get("knock_out_date"):
            self.knock_out_date = self._parse_date(raw["knock_out_date"])

    @staticmethod
    def _parse_date(val) -> date:
        if isinstance(val, date):
            return val
        if isinstance(val, datetime):
            return val.date()
        return datetime.strptime(str(val), "%Y-%m-%d").date()

    def remaining_days(self, val_date: date) -> int:
        """剩余天数"""
        return max(0, (self.maturity_date - val_date).days)


class MarketDataRecord:
    """单日市场数据（兼容原型 CSV 格式 + MongoDB 文档格式）"""

    def __init__(self, row: dict):
        self.date: date = ProductRecord._parse_date(row["date"])
        self.underlying: str = row["underlying"]
        self.spot: float = float(row["spot"])
        self.rate_1y: float = float(row.get("rate_1y", row.get("rate_1Y", 0.02)))
        self.dividend_yield: float = float(row.get("dividend_yield", 0.0))

        # 波动率（各期限）
        self.vols: Dict[str, float] = {
            "1M":  float(row.get("vol_1m",  row.get("vols", {}).get("1M",  0.20))),
            "3M":  float(row.get("vol_3m",  row.get("vols", {}).get("3M",  0.18))),
            "6M":  float(row.get("vol_6m",  row.get("vols", {}).get("6M",  0.17))),
            "12M": float(row.get("vol_12m", row.get("vols", {}).get("12M", 0.16))),
        }

        # 利率曲线（各期限）
        self.rates: Dict[str, float] = {}
        _rate_col_map = {"1M": "rate_1m", "3M": "rate_3m", "6M": "rate_6m",
                         "1Y": "rate_1y", "2Y": "rate_2y", "5Y": "rate_5y"}
        for tenor in RATE_TENORS:
            col = _rate_col_map.get(tenor, f"rate_{tenor.lower()}")
            self.rates[tenor] = float(row.get(col, row.get("rates", {}).get(tenor, self.rate_1y)))

    def get_rate(self, tau_years: float) -> float:
        """根据期限（年）从利率曲线插值获取零息利率"""
        tenors_y = sorted(RATE_TENOR_YEARS.values())
        rates_sorted = [self.rates[t] for t in sorted(RATE_TENOR_YEARS.keys(),
                                                       key=lambda k: RATE_TENOR_YEARS[k])]
        if tau_years <= tenors_y[0]:
            return rates_sorted[0]
        if tau_years >= tenors_y[-1]:
            return rates_sorted[-1]
        for i in range(len(tenors_y) - 1):
            if tenors_y[i] <= tau_years <= tenors_y[i + 1]:
                t = (tau_years - tenors_y[i]) / (tenors_y[i + 1] - tenors_y[i])
                return rates_sorted[i] + t * (rates_sorted[i + 1] - rates_sorted[i])
        return rates_sorted[-1]

    def discount(self, tau_years: float) -> float:
        """使用利率曲线计算折现因子 D(0, T) = exp(-r(T) * T)"""
        rate = self.get_rate(tau_years)
        return np.exp(-rate * tau_years)


# ── 波动率插值 ─────────────────────────────────────────

def interpolate_vol(market: MarketDataRecord, remaining_days: int) -> float:
    """按剩余期限线性插值波动率"""
    if remaining_days <= 0:
        return market.vols["1M"]

    days = sorted(VOL_TENOR_DAYS.values())
    vols = [market.vols[k] for k in sorted(VOL_TENOR_DAYS.keys(), key=lambda k: VOL_TENOR_DAYS[k])]

    if remaining_days <= days[0]:
        return vols[0]
    if remaining_days >= days[-1]:
        return vols[-1]

    for i in range(len(days) - 1):
        if days[i] <= remaining_days <= days[i + 1]:
            t = (remaining_days - days[i]) / (days[i + 1] - days[i])
            return vols[i] + t * (vols[i + 1] - vols[i])

    return vols[-1]


# ── 波动率曲面工具 ────────────────────────────────────

def build_vol_surface_from_doc(doc: dict) -> 'VolSurface':
    """从 MongoDB 文档构建 VolSurface 对象

    Args:
        doc: MongoDB 文档，包含 moneyness_grid, tenor_grid, vol_grid 字段

    Returns:
        VolSurface 实例
    """
    from app.options.vol.surface import VolSurface
    return VolSurface(
        moneyness_grid=doc["moneyness_grid"],
        tenor_grid=doc["tenor_grid"],
        vol_grid=doc["vol_grid"],
    )


def get_vol(market: MarketDataRecord, remaining_days: int,
            moneyness: float = 1.0,
            vol_surface: Optional['VolSurface'] = None) -> float:
    """从波动率曲面获取波动率（优于旧的 interpolate_vol）

    优先使用波动率曲面，若无曲面数据则退化为平坦插值。

    Args:
        market: 市场数据
        remaining_days: 剩余天数
        moneyness: 货币性 K/S
        vol_surface: 可选的波动率曲面对象（由 Service 层注入）
    """
    if vol_surface is not None:
        tenor_years = remaining_days / 365.0
        return vol_surface.get_vol(moneyness, tenor_years)

    return interpolate_vol(market, remaining_days)
