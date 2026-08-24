# -*- coding: utf-8 -*-
"""
资产主数据初始化 / 增量导入

目标集合: assets
幂等键:   code（唯一）
输入格式: Excel，列名参照 ASSET_COLUMN_MAPPING

Excel 模板列（必填带 *）：
  资产代码* | 资产名称* | 工具形态* | 资产大类* | 证券细分 | 交易所 | 计价货币 | 描述 |
  展期天数(k) | 持仓量阈值(th) | 观察窗口起点(p) | 观察窗口终点(q) | 替代标的代码 | 切换日期

用法：
    python -m scripts.seed.seed_assets --file data/seed/assets.xlsx
    python -m scripts.seed.seed_assets --file data/seed/assets.xlsx --dry-run
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from pymongo import UpdateOne

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.schemas.field_mappings import ASSET_COLUMN_MAPPING  # noqa: E402
from scripts.seed.base import SeedBase, normalize_date  # noqa: E402


# 扩展映射：新增三维度分类列（ASSET_COLUMN_MAPPING 中尚无）
_EXTRA_MAPPING: Dict[str, str] = {
    "工具形态*": "instrument_type",
    "工具形态": "instrument_type",
    "instrument_type": "instrument_type",
    "资产大类*": "asset_class",
    "资产大类": "asset_class",
    "asset_class": "asset_class",
    "证券细分": "security_type",
    "security_type": "security_type",
    "计价货币": "currency",
    "currency": "currency",
    "交易费率": "trading_cost_rate",
    "trading_cost_rate": "trading_cost_rate",
    "复制费率": "replication_cost_rate",
    "replication_cost_rate": "replication_cost_rate",
}

# 合并映射
FULL_ASSET_MAPPING = {**ASSET_COLUMN_MAPPING, **_EXTRA_MAPPING}

# 合法枚举值
VALID_INSTRUMENT_TYPES = {"指数型", "现货型", "期货型"}
VALID_ASSET_CLASSES = {"权益", "固收", "商品", "货币", "另类"}
VALID_SECURITY_TYPES = {"股票", "指数", "ETF", "LOF", "基金", "债券", "期货", "数字货币", "存款", ""}


class SeedAssets(SeedBase):
    name = "seed_assets"
    target_collection = "assets"
    description = "资产主数据导入（assets 集合）"

    def parse(self, file_path: Path) -> List[Dict[str, Any]]:
        df = pd.read_excel(file_path, dtype=str)
        df.columns = df.columns.astype(str).str.strip()
        df.rename(columns=FULL_ASSET_MAPPING, inplace=True)
        # 去重：以 code 为准
        if "code" not in df.columns:
            raise ValueError("缺少必须列: 资产代码（code）")
        df["code"] = df["code"].astype(str).str.strip()
        df = df.dropna(subset=["code"])
        df = df[df["code"] != ""]
        df = df.drop_duplicates(subset=["code"], keep="first")
        return df.to_dict("records")

    def validate(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        valid = []
        errors = []
        for i, rec in enumerate(records):
            code = rec.get("code", "").strip()
            name = rec.get("name", "").strip()
            if not code:
                errors.append(f"行{i}: 资产代码为空")
                continue
            if not name:
                rec["name"] = code  # 名称缺失时用代码代替

            # 枚举校验
            it = rec.get("instrument_type", "").strip()
            if it and it not in VALID_INSTRUMENT_TYPES:
                errors.append(f"行{i} [{code}]: instrument_type='{it}' 不合法")
                continue
            ac = rec.get("asset_class", "").strip()
            if ac and ac not in VALID_ASSET_CLASSES:
                errors.append(f"行{i} [{code}]: asset_class='{ac}' 不合法")
                continue

            # 默认值
            if not it:
                rec["instrument_type"] = "指数型"
            if not ac:
                rec["asset_class"] = "权益"

            valid.append(rec)
        return valid, errors

    def build_ops(self, records: List[Dict[str, Any]]) -> List[UpdateOne]:
        now = datetime.now(timezone.utc)
        ops = []
        for rec in records:
            code = rec["code"].strip()
            doc = {
                "code": code,
                "name": rec.get("name", code).strip(),
                "instrument_type": rec.get("instrument_type", "指数型").strip(),
                "asset_class": rec.get("asset_class", "权益").strip(),
                "security_type": rec.get("security_type", "").strip() or None,
                "exchange": rec.get("exchange", "").strip() or "",
                "description": rec.get("description", "").strip() or "",
                "currency": rec.get("currency", "").strip() or None,
                "is_active": True,
                "trading_cost_rate": _to_float(rec.get("trading_cost_rate")),
                "replication_cost_rate": _to_float(rec.get("replication_cost_rate")),
                "rollover_days": _to_int(rec.get("rollover_days")),
                "rollover_threshold": _to_float(rec.get("rollover_threshold")),
                "rollover_window_p": _to_int(rec.get("rollover_window_p")),
                "rollover_window_q": _to_int(rec.get("rollover_window_q")),
                "substitute_code": rec.get("substitute_code", "").strip() or "",
                "switch_date": normalize_date(rec.get("switch_date")) or "",
                "updated_at": now,
            }
            # upsert by code; $setOnInsert 保留首次 created_at
            ops.append(UpdateOne(
                {"code": code},
                {"$set": doc, "$setOnInsert": {"created_at": now}},
                upsert=True,
            ))
        return ops

    def post_import(self, stats: Dict[str, int]) -> None:
        if self.dry_run:
            return
        total_assets = self.db[self.target_collection].count_documents({})
        print(f"  [verify] assets 集合当前共 {total_assets} 条")


def _to_float(v: Any) -> float | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    SeedAssets.run()
