# -*- coding: utf-8 -*-
"""
MongoDB asset_prices 中 asset_code 与监控使用的标准代码（app.monitor.config）对齐。

本机若使用「标准码 + 后缀」（如 SH000300_TEST），在 .env 设置（大小写须与库内一致）：
  MONGO_ASSET_CODE_SUFFIX=_TEST
查询时使用后缀，透视后再还原为标准码，下游逻辑不变。
"""
from __future__ import annotations

from app.config.settings import settings
from app.monitor import config


def _suffix() -> str:
    return (getattr(settings, "MONGO_ASSET_CODE_SUFFIX", None) or "").strip()


def stored_price_code(canonical_code: str) -> str:
    """Mongo asset_prices 中实际存储的 asset_code（标准码 + 可选后缀）。"""
    suf = _suffix()
    if not suf:
        return str(canonical_code).strip()
    c = str(canonical_code).strip()
    if c.endswith(suf):
        return c
    return c + suf


def canonical_price_code(stored_code: str) -> str:
    """从 Mongo 读回的 asset_code 还原为 config 中的标准码。"""
    suf = _suffix()
    s = str(stored_code).strip()
    if suf and s.endswith(suf):
        return s[: -len(suf)]
    return s


def stored_price_codes_for_monitor() -> list[str]:
    """监控模块查询 12 资产时使用的 asset_code 列表（含后缀）。"""
    return [stored_price_code(c) for c in config.ASSET_NAME_TO_CODE.values()]
