# -*- coding: utf-8 -*-
"""
集中字段映射 —— 所有导入路径的唯一映射来源

DATA_ARCHITECTURE.md §3.3 规定：
  所有导入路径（前端 API、Agent Tool、脚本）必须引用同一份映射，
  禁止在各导入文件中硬编码列名映射。

使用方式：
    from app.schemas.field_mappings import (
        PRICE_COLUMN_MAPPING,
        ASSET_COLUMN_MAPPING,
        TRADE_DATES_COLUMN_MAPPING,
    )
"""

# ─────────────────────────────────────────────────────────────────────────────
# 行情字段映射（asset_prices 导入）
# Excel/JSON 列名 → PriceDataPoint 标准字段名
# ─────────────────────────────────────────────────────────────────────────────
PRICE_COLUMN_MAPPING: dict[str, str] = {
    # 日期
    "日期": "date",
    "日期*": "date",
    "交易日期": "date",
    "trade_date": "date",
    "Date": "date",
    "DATE": "date",
    "date": "date",
    # 开盘价
    "开盘价": "open",
    "开盘价*": "open",
    "Open": "open",
    "OPEN": "open",
    "open": "open",
    # 最高价
    "最高价": "high",
    "最高价*": "high",
    "High": "high",
    "HIGH": "high",
    "high": "high",
    # 最低价
    "最低价": "low",
    "最低价*": "low",
    "Low": "low",
    "LOW": "low",
    "low": "low",
    # 收盘价
    "收盘价": "close",
    "收盘价*": "close",
    "收盘": "close",
    "Close": "close",
    "CLOSE": "close",
    "close": "close",
    # 成交量
    "成交量": "volume",
    "成交量*": "volume",
    "Volume": "volume",
    "VOLUME": "volume",
    "volume": "volume",
    # 成交额
    "成交额": "amount",
    "成交额*": "amount",
    "Amount": "amount",
    "AMOUNT": "amount",
    "amount": "amount",
    # 规模
    "规模": "scale",
    "规模*": "scale",
    "基金规模": "scale",
    "Scale": "scale",
    "SCALE": "scale",
    "scale": "scale",
}

# 行情导入允许的标准字段名集合
PRICE_ALLOWED_FIELDS: frozenset = frozenset(
    {"date", "open", "high", "low", "close", "volume", "amount", "scale"}
)


# ─────────────────────────────────────────────────────────────────────────────
# 资产主数据映射（assets 导入）
# Excel 列名 → Asset 模型字段名
# ─────────────────────────────────────────────────────────────────────────────
ASSET_COLUMN_MAPPING: dict[str, str] = {
    "资产代码*": "code",
    "资产代码": "code",
    "资产名称*": "name",
    "资产名称": "name",
    "资产类型*": "asset_type",
    "资产类型": "asset_type",
    # 三维度正交分类（新字段，导入时优先采用，缺失则由 Asset 模型 backfill）
    "工具形态*": "instrument_type",
    "工具形态": "instrument_type",
    "instrument_type*": "instrument_type",
    "instrument_type": "instrument_type",
    "资产大类*": "asset_class",
    "资产大类": "asset_class",
    "asset_class*": "asset_class",
    "asset_class": "asset_class",
    "证券细分*": "security_type",
    "证券细分": "security_type",
    "security_type*": "security_type",
    "security_type": "security_type",
    "交易所": "exchange",
    "资产描述": "description",
    "展期天数(k)": "rollover_days",
    "持仓量阈值(th)": "rollover_threshold",
    "观察窗口起点(p)": "rollover_window_p",
    "观察窗口终点(q)": "rollover_window_q",
    "替代标的代码": "substitute_code",
    "切换日期(YYYYMMDD)": "switch_date",
}


# ─────────────────────────────────────────────────────────────────────────────
# 交易日历映射（trade_dates 导入）
# Excel 列名 → 标准字段名 "date"
# ─────────────────────────────────────────────────────────────────────────────
TRADE_DATES_COLUMN_MAPPING: dict[str, str] = {
    "交易日": "date",
    "交易日期": "date",
    "交易日期*": "date",
    "trade_dates": "date",
    "trade_date": "date",
    "TradeDate": "date",
    "TRADE_DATE": "date",
    "TRADE_DATES": "date",
    "日期": "date",
    "日期*": "date",
    "Date": "date",
    "DATE": "date",
    "date": "date",
}
