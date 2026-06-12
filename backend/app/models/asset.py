"""
资产数据模型
"""
from datetime import datetime
from typing import Optional, List, Union
from pydantic import BaseModel, Field, field_validator, field_serializer
from enum import Enum


class AssetType(str, Enum):
    """资产类型"""
    # 具体资产类型
    STOCK = "股票"
    BOND = "债券"
    COMMODITY = "商品"
    CURRENCY = "货币"
    FUND = "基金"
    INDEX = "指数"
    CRYPTO = "数字货币"
    
    # 前端分类（兼容）
    INDEX_CATEGORY = "指数类"  # 指数类：包含指数类型
    SPOT_CATEGORY = "现货类"    # 现货类：包含股票、债券、基金、货币、数字货币等
    FUTURES_CATEGORY = "期货类"  # 期货类：包含商品期货等


class Asset(BaseModel):
    """资产模型"""
    id: Optional[str] = Field(None, alias="_id")
    code: str = Field(..., description="资产代码")
    name: str = Field(..., description="资产名称")
    asset_type: AssetType = Field(..., description="资产类型")
    exchange: Optional[str] = Field(None, description="交易所")
    description: Optional[str] = Field(None, description="资产描述")
    is_active: bool = Field(True, description="是否启用")
    
    # 期货展期参数（仅期货类资产需要）
    rollover_days: Optional[int] = Field(None, description="展期天数 k")
    rollover_threshold: Optional[float] = Field(None, description="持仓量阈值 th")
    rollover_window_p: Optional[int] = Field(None, description="观察窗口起点参数 p（LTD-p）")
    rollover_window_q: Optional[int] = Field(None, description="观察窗口终点参数 q（LTD-q）")
    
    # 现货切换参数（仅现货/ETF类资产需要）
    substitute_code: Optional[str] = Field(None, description="替代标的代码（上市前使用）")
    switch_date: Optional[str] = Field(None, description="切换日期（YYYYMMDD）")

    # 动量策略：计价货币与费率（可选覆盖，不设则按 AssetType 默认值）
    currency: Optional[str] = Field(None, description="计价货币 CNH/USD/HKD/EUR")
    trading_cost_rate: Optional[float] = Field(None, description="交易费率（单次调仓），覆盖 AssetType 默认值")
    replication_cost_rate: Optional[float] = Field(None, description="复制费率年化，覆盖 AssetType 默认值")

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.strftime('%Y-%m-%d') if v else None
        }


class AssetPrice(BaseModel):
    """资产行情数据"""
    id: Optional[str] = Field(None, alias="_id")
    asset_code: str = Field(..., description="资产代码")
    date: str = Field(..., description="日期（格式：YYYY-MM-DD）")
    open: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    close: float = Field(..., description="收盘价")
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    scale: Optional[float] = Field(None, description="规模（如 AUM、份额规模等）")
    
    @field_validator('date', mode='before')
    @classmethod
    def validate_date(cls, v: Union[str, datetime]) -> str:
        """验证并转换日期格式为 YYYY-MM-DD"""
        if isinstance(v, datetime):
            return v.strftime('%Y-%m-%d')
        elif isinstance(v, str):
            # 尝试解析多种格式
            v = v.strip()
            # 移除分隔符
            clean_date = v.replace('-', '').replace('/', '')
            if len(clean_date) == 8:
                # YYYYMMDD 格式
                dt = datetime.strptime(clean_date, '%Y%m%d')
                return dt.strftime('%Y-%m-%d')
            elif len(v) == 10 and (v.count('-') == 2 or v.count('/') == 2):
                # YYYY-MM-DD 或 YYYY/MM/DD 格式
                dt = datetime.strptime(v.replace('/', '-'), '%Y-%m-%d')
                return dt.strftime('%Y-%m-%d')
            else:
                raise ValueError(f"不支持的日期格式: {v}，请使用 YYYY-MM-DD 或 YYYYMMDD")
        else:
            raise ValueError(f"日期类型必须是字符串或datetime对象")
    
    class Config:
        populate_by_name = True
