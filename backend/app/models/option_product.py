# -*- coding: utf-8 -*-
"""
收益凭证估值模块 —— MongoDB 数据模型

对应集合:
- option_products: 产品定义
- option_market_data: 市场数据
- option_vol_surfaces: 波动率曲面
- option_valuations: 估值快照
- option_valuation_history: 估值历史
- option_lifecycle_events: 生命周期事件
- option_risk_reports: 风险报告
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


# ── 枚举 ─────────────────────────────────────────────

class OptionProductType(str, Enum):
    """收益凭证产品类型"""
    FIXED = "fixed"                # 固定收益
    BINARY = "binary"              # 二元结构
    SPREAD = "spread"              # 价差结构
    SHARKFIN = "sharkfin"          # 鲨鱼鳍
    SNOWBALL = "snowball"          # 雪球
    PHOENIX = "phoenix"            # 凤凰
    DOUBLE_BARRIER = "double_barrier"  # 双鲨
    ASIAN = "asian"                # 亚式期权
    RAINBOW = "rainbow"            # 彩虹期权
    RANGE_ACCRUAL = "range_accrual"  # 区间累积
    CALLABLE_FIXED = "callable_fixed"  # 可赎回固收
    DIGITAL_RANGE = "digital_range"  # 数字区间
    AMERICAN_OPTION = "american_option"  # 美式期权（二叉树）
    FD_OPTION = "fd_option"          # 有限差分期权（PDE）
    LOCAL_VOL_OPTION = "local_vol_option"  # 局部波动率期权（Dupire）


class OptionProductStatus(str, Enum):
    """收益凭证产品状态"""
    ACTIVE = "active"
    PENDING = "pending"
    KNOCKED_OUT = "knocked_out"
    KNOCKED_IN = "knocked_in"
    MATURED = "matured"


# ── 产品定义 ──────────────────────────────────────────

class OptionProduct(BaseModel):
    """收益凭证产品模型 (option_products 集合)"""
    id: Optional[str] = Field(None, alias="_id")
    product_id: str = Field(..., description="产品编号，如 SNOW_001")
    name: str = Field(..., description="产品名称")
    type: OptionProductType = Field(..., description="产品类型")
    issuer: str = Field("", description="发行方")
    issue_date: str = Field(..., description="发行日期 YYYY-MM-DD")
    maturity_date: str = Field(..., description="到期日期 YYYY-MM-DD")
    principal: float = Field(..., description="本金（元）")
    underlying: str = Field(..., description="标的资产代码，如 000300.SH")
    status: OptionProductStatus = Field(default=OptionProductStatus.ACTIVE, description="产品状态")
    params: Dict[str, Any] = Field(default_factory=dict, description="产品条款参数")
    knock_out_date: Optional[str] = Field(None, description="敲出日期 YYYY-MM-DD")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        populate_by_name = True


# ── 市场数据 ──────────────────────────────────────────

class OptionMarketData(BaseModel):
    """市场数据模型 (option_market_data 集合)"""
    id: Optional[str] = Field(None, alias="_id")
    date: str = Field(..., description="日期 YYYY-MM-DD")
    underlying: str = Field(..., description="标的资产代码")
    spot: float = Field(..., description="标的价格")
    dividend_yield: float = Field(0.0, description="分红率")
    vol_1m: float = Field(0.20, description="1M 波动率")
    vol_3m: float = Field(0.18, description="3M 波动率")
    vol_6m: float = Field(0.17, description="6M 波动率")
    vol_12m: float = Field(0.16, description="12M 波动率")
    rate_1m: float = Field(0.02, description="1M 利率")
    rate_3m: float = Field(0.02, description="3M 利率")
    rate_6m: float = Field(0.02, description="6M 利率")
    rate_1y: float = Field(0.025, description="1Y 利率")
    rate_2y: float = Field(0.028, description="2Y 利率")
    rate_5y: float = Field(0.03, description="5Y 利率")
    created_at: datetime = Field(default_factory=datetime.now)


# ── 波动率曲面 ────────────────────────────────────────

class OptionVolSurface(BaseModel):
    """波动率曲面模型 (option_vol_surfaces 集合)"""
    id: Optional[str] = Field(None, alias="_id")
    underlying: str = Field(..., description="标的资产代码")
    moneyness_grid: List[float] = Field(..., description="货币性网格 K/S")
    tenor_grid: List[float] = Field(..., description="期限网格（年）")
    vol_grid: List[List[float]] = Field(..., description="波动率网格 shape=(tenors, moneyness)")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ── 估值快照 ──────────────────────────────────────────

class OptionValuation(BaseModel):
    """估值快照模型 (option_valuations 集合)"""
    id: Optional[str] = Field(None, alias="_id")
    date: str = Field(..., description="估值日期 YYYY-MM-DD")
    product_id: str = Field(..., description="产品编号")
    name: str = Field("", description="产品名称")
    type: str = Field("", description="产品类型")
    issuer: str = Field("", description="发行方")
    status: str = Field("", description="产品状态")
    principal: float = Field(0.0, description="本金")
    underlying: str = Field("", description="标的代码")
    price_total: float = Field(0.0, description="总估值")
    fixed_part: float = Field(0.0, description="固收部分")
    option_part: float = Field(0.0, description="期权部分")
    spot: float = Field(0.0, description="标的价格")
    vol: float = Field(0.0, description="波动率")
    delta: float = Field(0.0)
    gamma: float = Field(0.0)
    vega: float = Field(0.0)
    theta: float = Field(0.0)
    rho: float = Field(0.0)
    method: str = Field("", description="定价方法")
    error: str = Field("", description="错误信息")
    created_at: datetime = Field(default_factory=datetime.now)


# ── 生命周期事件 ──────────────────────────────────────

class OptionLifecycleEvent(BaseModel):
    """生命周期事件模型 (option_lifecycle_events 集合)"""
    id: Optional[str] = Field(None, alias="_id")
    product_id: str = Field(..., description="产品编号")
    event_type: str = Field(..., description="事件类型: knock_out/knock_in/maturity")
    event_date: str = Field(..., description="事件日期 YYYY-MM-DD")
    spot: float = Field(0.0, description="标的价格")
    barrier_level: float = Field(0.0, description="障碍价")
    description: str = Field("", description="事件描述")
    created_at: datetime = Field(default_factory=datetime.now)


# ── 风险报告 ──────────────────────────────────────────

class OptionRiskReport(BaseModel):
    """风险报告模型 (option_risk_reports 集合)"""
    id: Optional[str] = Field(None, alias="_id")
    date: str = Field(..., description="报告日期 YYYY-MM-DD")
    scenario: Optional[Dict[str, Any]] = Field(None, description="情景分析结果")
    stress: Optional[Dict[str, Any]] = Field(None, description="压力测试结果")
    pnl: Optional[List[Dict[str, Any]]] = Field(None, description="P&L 归因")
    created_at: datetime = Field(default_factory=datetime.now)


# ── 估值历史 ────────────────────────────────────────

class OptionValuationHistory(BaseModel):
    """估值历史记录 (option_valuation_history 集合)

    写入时机: 每次执行估值后自动写入，包含完整估值快照。
    与 option_valuations 的区别: valuations 只保留最新，history 累加所有历史记录。
    """
    id: Optional[str] = Field(None, alias="_id")
    product_id: str = Field(..., description="产品编号")
    date: str = Field(..., description="估值日期 YYYY-MM-DD")
    # 估值快照（包含价格、Greeks、标的等完整信息）
    valuation: OptionValuation = Field(..., description="完整估值快照")
    created_at: datetime = Field(default_factory=datetime.now, description="记录时间")

    class Config:
        populate_by_name = True
