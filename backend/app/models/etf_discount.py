# -*- coding: utf-8 -*-
"""
ETF 折溢价数据模型

对应集合: etf_discount_market_data（历史一次性 Excel 导入，当前无在线写入链路）
被消费方: 回测专用 DataFeed（app/backtesting/data_feed.py，etf_discount 策略类型）
           → ETFDiscountSelector 消费其中的 close/discount_ratio/vwap 宽表

本模型是该集合的结构契约（字段清单与库内文档一一对应），
重新导入或补数据时应以此为准。
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EtfDiscountMarketData(BaseModel):
    """ETF 折溢价市场数据 (etf_discount_market_data 集合)

    注：date 字段在此集合为 datetime 类型（历史设计），非字符串。
    """
    id: Optional[str] = Field(None, alias="_id")
    date: datetime = Field(..., description="日期（datetime，历史设计）")
    code: str = Field(..., description="ETF 代码")
    close: float = Field(..., description="收盘价")
    open: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    pre_close: Optional[float] = Field(None, description="昨收盘价")
    nav: Optional[float] = Field(None, description="ETF 净值（IOPV）")
    volume: Optional[float] = Field(None, description="成交量")
    amt: Optional[float] = Field(None, description="成交额")
    val_mvc: Optional[float] = Field(None, description="总市值")
    vwap: Optional[float] = Field(None, description="成交量加权均价")
    discount_ratio: Optional[float] = Field(None, description="折溢价率（%）")
    swing: Optional[float] = Field(None, description="振幅（%）")
    mf_netinflow: Optional[float] = Field(None, description="主力资金净流入")

    class Config:
        populate_by_name = True
