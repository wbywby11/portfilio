# -*- coding: utf-8 -*-
"""
资产费率与货币映射配置

策略：按 AssetType 默认值 + 可选覆盖（Asset 模型扩展字段）
来源：浙银理财/申万宏源《大类资产指数技术说明文档》B.1.4、B.1.5
"""
from __future__ import annotations

from typing import Optional
from app.models.asset import AssetType

# 按资产类型的默认交易费率（单次调仓）
DEFAULT_TRADING_COST_BY_TYPE = {
    AssetType.STOCK: 0.0010,   # 股票 0.10%
    AssetType.BOND: 0.0005,     # 债券 0.05%
    AssetType.COMMODITY: 0.0010,  # 商品 0.10%
    AssetType.FUND: 0.0010,
    AssetType.INDEX: 0.0010,
    AssetType.CURRENCY: 0.0,
    AssetType.CRYPTO: 0.0010,
}

# 按资产类型的默认复制费率（年化）
DEFAULT_REPLICATION_COST_BY_TYPE = {
    AssetType.STOCK: 0.0050,   # 股票 0.50%
    AssetType.BOND: 0.0030,    # 债券 0.30%
    AssetType.COMMODITY: 0.0050,  # 商品 0.50%
    AssetType.FUND: 0.0050,
    AssetType.INDEX: 0.0050,
    AssetType.CURRENCY: 0.0,
    AssetType.CRYPTO: 0.0050,
}

# 资产代码 -> 计价货币（与 step3 ASSET_CURRENCY 一致，用于资产库未配置 currency 时回退）
ASSET_CURRENCY_BY_CODE = {
    "SH000300": "CNH", "SZ399006": "CNH", "ZZ000001": "CNH", "HSTECH": "HKD",
    "SPX": "USD", "GDAXI": "EUR", "ZQGZ10": "CNH", "ZQGZ2": "CNH",
    "B00Y": "USD", "GLD": "CNH", "IRON": "CNH", "YSJS": "CNH",
    # 测试资产（与上同）
    "SH000300_TEST": "CNH", "SZ399006_TEST": "CNH", "ZZ000001_TEST": "CNH",
    "HSTECH_TEST": "HKD", "SPX_TEST": "USD", "GDAXI_TEST": "EUR",
    "ZQGZ10_TEST": "CNH", "ZQGZ2_TEST": "CNH", "B00Y_TEST": "USD",
    "GLD_TEST": "CNH", "IRON_TEST": "CNH", "YSJS_TEST": "CNH",
}

# 资产名称/别名 -> 计价货币
ASSET_CURRENCY_BY_NAME = {
    "沪深300": "CNH", "创业板指": "CNH", "红利低波": "CNH", "恒生科技": "HKD",
    "标普500": "USD", "德国DAX": "EUR", "中国10年国债": "CNH", "中国2年国债": "CNH",
    "布伦特原油": "USD", "黄金": "CNH", "铁矿石": "CNH", "中国有色金属": "CNH",
    # 测试资产
    "沪深300-测试": "CNH", "创业板指-测试": "CNH", "红利低波-测试": "CNH",
    "恒生科技-测试": "HKD", "标普500-测试": "USD", "德国DAX-测试": "EUR",
    "中国10年国债-测试": "CNH", "中国2年国债-测试": "CNH",
    "布伦特原油-测试": "USD", "黄金-测试": "CNH", "铁矿石-测试": "CNH",
    "中国有色金属-测试": "CNH",
}


def get_trading_cost(asset_type: AssetType, override: Optional[float]) -> float:
    """获取交易费率，override 优先"""
    if override is not None and override >= 0:
        return float(override)
    return DEFAULT_TRADING_COST_BY_TYPE.get(asset_type, 0.0010)


def get_replication_cost(asset_type: AssetType, override: Optional[float]) -> float:
    """获取复制费率（年化），override 优先"""
    if override is not None and override >= 0:
        return float(override)
    return DEFAULT_REPLICATION_COST_BY_TYPE.get(asset_type, 0.0050)


def get_currency_for_asset(code: str, name: Optional[str], override: Optional[str]) -> str:
    """获取资产计价货币，override 优先，否则按 code/name 查配置，默认 CNH"""
    if override and override.strip().upper() in ("CNH", "CNY", "USD", "HKD", "EUR"):
        return override.strip().upper()
    if code in ASSET_CURRENCY_BY_CODE:
        return ASSET_CURRENCY_BY_CODE[code]
    if name and name.strip() in ASSET_CURRENCY_BY_NAME:
        return ASSET_CURRENCY_BY_NAME[name.strip()]
    return "CNH"
