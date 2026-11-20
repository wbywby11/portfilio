"""
宏观与估值序列数据模型（macro_series 集合）

长表存储：一条记录 = 一个序列在一个日期的一个取值。

与 fx_rates 的区别：fx 是「一日一行、多币种多列」的宽表；宏观序列条数随
序列数增长，且序列会增删，所以按 (code, date) 拆成长表，新增序列不改表结构。

存储形态：
    { code: "H00922_PE", date: "2024-01-31", value: 18.32,
      series_type: "valuation", unit: "倍", source: "中证指数" }

date 统一为字符串 "YYYY-MM-DD"（与 asset_prices / fx_rates 一致），范围查询
可直接用字符串比较，不经时区转换。
"""
from typing import Optional

from pydantic import BaseModel, Field


class MacroSeriesPoint(BaseModel):
    """单条宏观/估值序列观测值"""

    code: str = Field(..., description="序列代码，如 H00922_PE / CBA_10Y")
    date: str = Field(..., description="日期 YYYY-MM-DD")
    value: float = Field(..., description="该日取值（不作正负限制，PB / 利差可为负）")
    series_type: str = Field(
        "other", description="序列类型，取自 field_mappings.MACRO_SERIES_TYPES"
    )
    unit: Optional[str] = Field(None, description="单位，如 倍 / % / 点")
    source: Optional[str] = Field(None, description="数据来源，仅留痕核对，不参与计算")

    class Config:
        populate_by_name = True
