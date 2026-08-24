# -*- coding: utf-8 -*-
"""收益凭证估值模块 API 请求/响应模型"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.models.option_product import OptionProductType, OptionProductStatus


# ── 产品 CRUD ─────────────────────────────────────────

class OptionProductCreate(BaseModel):
    """创建收益凭证产品请求"""
    product_id: str = Field(..., description="产品编号，如 SNOW_001")
    name: str = Field(..., description="产品名称")
    type: OptionProductType = Field(..., description="产品类型")
    issuer: str = Field("", description="发行方")
    issue_date: str = Field(..., description="发行日期 YYYY-MM-DD")
    maturity_date: str = Field(..., description="到期日期 YYYY-MM-DD")
    principal: float = Field(..., description="本金（元）")
    underlying: str = Field(..., description="标的资产代码")
    status: OptionProductStatus = Field(default=OptionProductStatus.ACTIVE)
    params: Dict[str, Any] = Field(default_factory=dict, description="产品条款参数")


class OptionProductUpdate(BaseModel):
    """更新收益凭证产品请求"""
    product_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[OptionProductType] = None
    issuer: Optional[str] = None
    issue_date: Optional[str] = None
    maturity_date: Optional[str] = None
    principal: Optional[float] = None
    underlying: Optional[str] = None
    status: Optional[OptionProductStatus] = None
    params: Optional[Dict[str, Any]] = None
    knock_out_date: Optional[str] = None


class OptionProductOut(BaseModel):
    """收益凭证产品返回模型"""
    id: str = Field(..., description="MongoDB _id")
    product_id: str
    name: str
    type: str
    issuer: str
    issue_date: str
    maturity_date: str
    principal: float
    underlying: str
    status: str
    params: Dict[str, Any]
    knock_out_date: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── 市场数据 ──────────────────────────────────────────

class OptionMarketDataImportItem(BaseModel):
    """单条市场数据导入记录"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    underlying: str = Field(..., description="标的代码")
    spot: float = Field(..., description="标的价格")
    dividend_yield: float = Field(0.0)
    vol_1m: float = Field(0.20)
    vol_3m: float = Field(0.18)
    vol_6m: float = Field(0.17)
    vol_12m: float = Field(0.16)
    rate_1m: float = Field(0.02)
    rate_3m: float = Field(0.02)
    rate_6m: float = Field(0.02)
    rate_1y: float = Field(0.025)
    rate_2y: float = Field(0.028)
    rate_5y: float = Field(0.03)


class OptionMarketDataImportRequest(BaseModel):
    """批量导入市场数据请求"""
    records: List[OptionMarketDataImportItem] = Field(..., description="市场数据记录列表")


class OptionMarketDataOut(BaseModel):
    """市场数据返回模型"""
    id: str
    date: str
    underlying: str
    spot: float
    dividend_yield: float
    vol_1m: float
    vol_3m: float
    vol_6m: float
    vol_12m: float
    rate_1m: float
    rate_3m: float
    rate_6m: float
    rate_1y: float
    rate_2y: float
    rate_5y: float


# ── 波动率曲面 ────────────────────────────────────────

class OptionVolSurfaceImportRequest(BaseModel):
    """导入波动率曲面请求"""
    underlying: str = Field(..., description="标的资产代码")
    moneyness_grid: List[float] = Field(..., description="货币性网格 K/S")
    tenor_grid: List[float] = Field(..., description="期限网格（年）")
    vol_grid: List[List[float]] = Field(..., description="波动率网格 shape=(tenors, moneyness)")


class OptionVolSurfaceOut(BaseModel):
    """波动率曲面返回模型"""
    id: str
    underlying: str
    moneyness_grid: List[float]
    tenor_grid: List[float]
    vol_grid: List[List[float]]
    created_at: Optional[str] = None


# ── 估值运行 ──────────────────────────────────────────

class OptionRunRequest(BaseModel):
    """估值运行请求"""
    date: str = Field(..., description="估值日期 YYYY-MM-DD")
    product_ids: Optional[List[str]] = Field(None, description="指定产品ID列表（空=全部）")
    skip_lifecycle: bool = Field(False, description="跳过生命周期检测")


class OptionRiskRunRequest(BaseModel):
    """风险分析运行请求"""
    date: str = Field(..., description="估值日期 YYYY-MM-DD")
    run_scenario: bool = Field(True, description="运行情景分析")
    run_stress: bool = Field(True, description="运行压力测试")
    run_pnl: bool = Field(False, description="运行 P&L 归因")


# ── 估值结果 ──────────────────────────────────────────

class OptionValuationOut(BaseModel):
    """估值结果返回"""
    product_id: str
    name: str
    type: str
    status: str
    principal: float
    underlying: str
    price_total: float
    fixed_part: float
    option_part: float
    spot: float
    vol: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    method: str
    error: str


class OptionValuationSnapshotOut(BaseModel):
    """估值快照返回"""
    date: str
    total_products: int
    success_count: int
    error_count: int
    total_value: float
    products: List[OptionValuationOut]


class OptionValuationHistoryItem(BaseModel):
    """估值历史单条"""
    date: str
    product_id: str
    name: str
    type: str
    principal: float
    price_total: float
    method: str
    error: str


# ── 事件日志 ──────────────────────────────────────────

class OptionEventOut(BaseModel):
    """事件日志返回"""
    product_id: str
    event_type: str
    event_date: str
    spot: float
    barrier_level: float
    description: str
