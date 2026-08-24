# -*- coding: utf-8 -*-
"""
交易日历初始化 / 增量导入

目标集合: trade_dates
幂等键:   date（datetime，唯一）
输入格式: Excel，单列日期（列名参照 TRADE_DATES_COLUMN_MAPPING）

注意：trade_dates.date 存储为 datetime（ISODate），这是历史设计，
     与其他集合的 'YYYY-MM-DD' 字符串不同。本脚本写入时自动转为 datetime。

Excel 模板：
  交易日
  2020-01-02
  2020-01-03
  ...

用法：
    python -m scripts.seed.seed_trade_dates --file data/seed/trade_dates.xlsx
    python -m scripts.seed.seed_trade_dates --file data/seed/trade_dates.xlsx --dry-run
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from pymongo import UpdateOne

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.schemas.field_mappings import TRADE_DATES_COLUMN_MAPPING  # noqa: E402
from scripts.seed.base import SeedBase  # noqa: E402


class SeedTradeDates(SeedBase):
    name = "seed_trade_dates"
    target_collection = "trade_dates"
    description = "交易日历导入（trade_dates 集合）"

    def parse(self, file_path: Path) -> List[Dict[str, Any]]:
        df = pd.read_excel(file_path, dtype=str)
        df.columns = df.columns.astype(str).str.strip()
        df.rename(columns=TRADE_DATES_COLUMN_MAPPING, inplace=True)

        if "date" not in df.columns:
            raise ValueError("缺少必须列: 交易日（date）")

        df["date"] = df["date"].astype(str).str.strip()
        df = df.dropna(subset=["date"])
        df = df[df["date"] != ""]
        df = df.drop_duplicates(subset=["date"], keep="first")
        return df[["date"]].to_dict("records")

    def validate(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        valid = []
        errors = []
        for i, rec in enumerate(records):
            raw = rec.get("date", "")
            # 尝试解析为 datetime
            dt = self._parse_to_datetime(raw)
            if dt is None:
                errors.append(f"行{i}: 无法解析日期 '{raw}'")
                continue
            # 合理性：1990 ~ 2035
            if dt.year < 1990 or dt.year > 2035:
                errors.append(f"行{i}: 日期超出合理范围 '{raw}'")
                continue
            rec["_dt"] = dt
            valid.append(rec)
        return valid, errors

    def build_ops(self, records: List[Dict[str, Any]]) -> List[UpdateOne]:
        ops = []
        for rec in records:
            dt = rec["_dt"]
            # trade_dates 用 datetime 存储（历史设计）
            ops.append(UpdateOne(
                {"date": dt},
                {"$setOnInsert": {"date": dt}},
                upsert=True,
            ))
        return ops

    def post_import(self, stats: Dict[str, int]) -> None:
        if self.dry_run:
            return
        total = self.db[self.target_collection].count_documents({})
        # 查询日期范围
        first = self.db[self.target_collection].find_one(sort=[("date", 1)])
        last = self.db[self.target_collection].find_one(sort=[("date", -1)])
        range_str = ""
        if first and last:
            range_str = f"（{first['date'].strftime('%Y-%m-%d')} ~ {last['date'].strftime('%Y-%m-%d')}）"
        print(f"  [verify] trade_dates 集合当前共 {total} 条{range_str}")

    @staticmethod
    def _parse_to_datetime(raw: str) -> datetime | None:
        """将字符串解析为 datetime（兼容多格式）"""
        raw = raw.strip()
        if not raw:
            return None
        # YYYYMMDD
        if len(raw) == 8 and raw.isdigit():
            raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        try:
            ts = pd.Timestamp(raw)
            return ts.to_pydatetime()
        except Exception:
            return None


if __name__ == "__main__":
    SeedTradeDates.run()
