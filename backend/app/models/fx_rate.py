"""
汇率数据模型

fx.xlsx 格式: 第一列为日期, 后续列为 EUR/USD/HKD/JPY/CNH 对人民币汇率
"""
from datetime import datetime
from typing import Optional, Dict
from pydantic import BaseModel, Field


class FxManualRatesIn(BaseModel):
    """手动录入单日汇率(对人民币, 须大于 0)"""

    date: str = Field(..., description="日期 YYYY-MM-DD")
    EUR: Optional[float] = Field(None, description="欧元对人民币")
    USD: Optional[float] = Field(None, description="美元对人民币")
    HKD: Optional[float] = Field(None, description="港币对人民币")
    JPY: Optional[float] = Field(None, description="日元对人民币汇率")
    CNH: Optional[float] = Field(None, description="离岸人民币, 通常 1.0")


class FxRate(BaseModel):
    """单日汇率记录"""

    date: str = Field(..., description="日期 YYYY-MM-DD")
    EUR: Optional[float] = Field(None, description="欧元对人民币汇率")
    USD: Optional[float] = Field(None, description="美元对人民币汇率")
    HKD: Optional[float] = Field(None, description="港币对人民币汇率")
    JPY: Optional[float] = Field(None, description="日元对人民币汇率")
    CNH: Optional[float] = Field(None, description="离岸人民币对人民币汇率, 通常为1.0")

    class Config:
        populate_by_name = True

    def get_rate(self, currency: str) -> float:
        """获取指定货币的汇率, CNH 或缺失时返回 1.0"""
        if currency == "CNH" or currency == "CNY":
            return 1.0
        val = getattr(self, currency, None)
        if val is not None and not (isinstance(val, float) and val != val):  # 非 NaN
            return float(val)
        return 1.0
