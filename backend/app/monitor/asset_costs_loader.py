# -*- coding: utf-8 -*-
"""
从项目根目录 data/资产费用.xlsx 加载交易费率、复制费率，与 app.monitor.config 默认值合并。

列名兼容：资产|资产代码|资产名称；交易费率|交易成本|交易费用；复制费率|复制成本|复制费用。
资产列可为中文名（与 ASSET_LIST 一致）、标准 asset_code，或带 MONGO_ASSET_CODE_SUFFIX / _TEST 后缀的代码（如 SH000300_TEST），会映射到同一资产以合并费率。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
from loguru import logger

from app.monitor import config
from app.monitor.mongo_asset_codes import canonical_price_code

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FEES_PATH = _PROJECT_ROOT / "data" / "资产费用.xlsx"


def _resolve_asset_key(raw: str) -> Optional[str]:
    """解析为 config.ASSET_LIST 中的中文资产名，用于写入 trading/replication 字典。"""

    def _match(x: str) -> Optional[str]:
        if not x:
            return None
        if x in config.ASSET_LIST:
            return x
        if x in config.ASSET_CODE_TO_NAME:
            return config.ASSET_CODE_TO_NAME[x]
        if x in config.ASSET_NAME_TO_CODE:
            return x
        return None

    s = str(raw).strip()
    hit = _match(s)
    if hit:
        return hit

    # 与 Mongo 一致：去掉 MONGO_ASSET_CODE_SUFFIX（如 _TEST）再按标准码匹配
    canon = canonical_price_code(s)
    hit = _match(canon)
    if hit:
        return hit

    # 未配置后缀但表中写死大写 _TEST 时仍识别
    suf = "_TEST"
    if s.endswith(suf) and len(s) > len(suf):
        hit = _match(s[: -len(suf)])
        if hit:
            return hit

    return None


def load_merged_asset_costs() -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    以 config.TRADING_COST / REPLICATION_COST 为底，用 Excel 中存在的行覆盖对应资产。
    文件不存在或解析失败时返回 config 的拷贝。
    """
    trading = dict(config.TRADING_COST)
    replication = dict(config.REPLICATION_COST)

    if not _FEES_PATH.exists():
        return trading, replication

    try:
        df = pd.read_excel(_FEES_PATH)
    except Exception as e:
        logger.warning("读取资产费用表失败 {}: {}，使用 config 默认费率", _FEES_PATH, e)
        return trading, replication

    asset_col = None
    for c in ("资产", "资产代码", "资产名称"):
        if c in df.columns:
            asset_col = c
            break
    tc_col = next(
        (c for c in ("交易费率", "交易成本", "交易费用", "trading_cost") if c in df.columns),
        None,
    )
    rc_col = next(
        (c for c in ("复制费率", "复制成本", "复制费用", "replication_cost") if c in df.columns),
        None,
    )

    if asset_col is None or (tc_col is None and rc_col is None):
        logger.warning("资产费用表列不识别，跳过；需要资产列及交易/复制费率列之一: {}", _FEES_PATH)
        return trading, replication

    n_tc, n_rc = 0, 0
    for _, row in df.iterrows():
        key = _resolve_asset_key(row.get(asset_col, ""))
        if key is None:
            continue
        if tc_col is not None:
            v = row.get(tc_col)
            if pd.notna(v):
                try:
                    trading[key] = float(v)
                    n_tc += 1
                except (TypeError, ValueError):
                    pass
        if rc_col is not None:
            v = row.get(rc_col)
            if pd.notna(v):
                try:
                    replication[key] = float(v)
                    n_rc += 1
                except (TypeError, ValueError):
                    pass

    if n_tc or n_rc:
        logger.info(
            "已从 {} 合并费率：覆盖交易费率 {} 条、复制费率 {} 条",
            _FEES_PATH,
            n_tc,
            n_rc,
        )
    return trading, replication
