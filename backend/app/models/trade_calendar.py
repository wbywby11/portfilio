# -*- coding: utf-8 -*-
"""
交易日历数据模型

对应集合: trade_dates

特殊说明: 此集合 date 字段为 datetime 类型（历史设计），非字符串 YYYY-MM-DD，
查询时必须使用 datetime 对象，与系统其他集合的日期标准不同。
详见 DATA_ARCHITECTURE.md §1.3 日期标准。

写入来源: Excel/CSV 导入（app/data/trade_dates.py）
被消费方: 回测引擎、监控系统、导入跳过非交易日、Agent 查询
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TradeDate(BaseModel):
    """交易日历条目 (trade_dates 集合)

    注意：date 为 datetime 类型（ISODate），非字符串。
    """
    id: Optional[str] = Field(None, alias="_id")
    date: datetime = Field(..., description="交易日（ISODate，历史设计）")

    class Config:
        populate_by_name = True
