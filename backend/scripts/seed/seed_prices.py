# -*- coding: utf-8 -*-
"""
行情数据初始化 / 增量导入

目标集合: asset_prices（+ 自动注册 assets）
幂等键:   (asset_code, date)
输入格式: 支持两种 Excel 格式

格式 A — 宽表（Wind/同花顺导出）：
  Row 0: 基金代码 | 510300.SH | 518880.SH | ...
  Row 1: 基金名称 | 华泰柏瑞300ETF | 黄金ETF | ...
  Row 2+: 日期(datetime) | 收盘价(float) | ...

格式 B — 长表（标准导入模板）：
  资产代码* | 日期* | 开盘价 | 最高价 | 最低价 | 收盘价* | 成交量 | 成交额 | 规模
  510300.SH | 2024-01-02 | 3.52 | 3.55 | 3.50 | 3.53 | 12345 | 43567 | 280.5

说明：
  - 宽表格式仅含收盘价，其余 OHLCV 为 null
  - 资产不存在时自动创建（instrument_type=指数型, asset_class=权益）
  - 日期归一化为 'YYYY-MM-DD' 字符串

用法：
    python -m scripts.seed.seed_prices --file data/seed/prices.xlsx
    python -m scripts.seed.seed_prices --file data/seed/prices.xlsx --dry-run
    python -m scripts.seed.seed_prices --file data/seed/prices.xlsx --format wide
    python -m scripts.seed.seed_prices --file data/seed/prices.xlsx --format long
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from pymongo import UpdateOne

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.schemas.field_mappings import PRICE_COLUMN_MAPPING  # noqa: E402
from scripts.seed.base import SeedBase, normalize_date  # noqa: E402


# 长表模式额外的资产代码列映射
_CODE_MAPPING = {
    "资产代码*": "asset_code",
    "资产代码": "asset_code",
    "代码": "asset_code",
    "asset_code": "asset_code",
    "code": "asset_code",
    "Code": "asset_code",
    "CODE": "asset_code",
    "基金代码": "asset_code",
}


class SeedPrices(SeedBase):
    name = "seed_prices"
    target_collection = "asset_prices"
    batch_size = 1000
    description = "行情数据导入（asset_prices 集合，支持宽表/长表）"

    def __init__(self, args):
        super().__init__(args)
        self._asset_codes_seen: set = set()
        self._asset_names: Dict[str, str] = {}

    @classmethod
    def make_parser(cls):
        parser = super().make_parser()
        parser.add_argument(
            "--format", type=str, default="auto",
            choices=["auto", "wide", "long"],
            help="Excel 格式：wide=宽表(代码在列头), long=长表(标准模板), auto=自动检测"
        )
        parser.add_argument(
            "--auto-create-assets", action="store_true", default=True,
            help="资产不存在时自动创建（默认开启）"
        )
        return parser

    def parse(self, file_path: Path) -> List[Dict[str, Any]]:
        fmt = getattr(self.args, "format", "auto")

        if fmt == "auto":
            fmt = self._detect_format(file_path)
            print(f"     自动检测格式: {fmt}")

        if fmt == "wide":
            return self._parse_wide(file_path)
        else:
            return self._parse_long(file_path)

    def validate(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        valid = []
        errors = []
        for i, rec in enumerate(records):
            code = rec.get("asset_code", "").strip()
            date_str = rec.get("date", "")
            close = rec.get("close")

            if not code:
                errors.append(f"行{i}: asset_code 为空")
                continue
            if not date_str:
                errors.append(f"行{i} [{code}]: date 为空")
                continue
            if close is None:
                # 至少需要收盘价
                errors.append(f"行{i} [{code} {date_str}]: 无收盘价")
                continue
            try:
                close_f = float(close)
                if close_f <= 0:
                    errors.append(f"行{i} [{code} {date_str}]: close={close_f} ≤ 0")
                    continue
                rec["close"] = close_f
            except (TypeError, ValueError):
                errors.append(f"行{i} [{code} {date_str}]: close 无法转为数值")
                continue

            # 其他数值字段
            for field in ("open", "high", "low", "volume", "amount", "scale"):
                v = rec.get(field)
                if v is not None:
                    try:
                        rec[field] = float(v)
                    except (TypeError, ValueError):
                        rec[field] = None
                else:
                    rec[field] = None

            valid.append(rec)
        return valid, errors

    def build_ops(self, records: List[Dict[str, Any]]) -> List[UpdateOne]:
        ops = []
        for rec in records:
            code = rec["asset_code"]
            date_str = rec["date"]
            doc = {
                "asset_code": code,
                "date": date_str,
                "open": rec.get("open"),
                "high": rec.get("high"),
                "low": rec.get("low"),
                "close": rec["close"],
                "volume": rec.get("volume"),
                "amount": rec.get("amount"),
                "scale": rec.get("scale"),
            }
            ops.append(UpdateOne(
                {"asset_code": code, "date": date_str},
                {"$set": doc},
                upsert=True,
            ))
        return ops

    def post_import(self, stats: Dict[str, int]) -> None:
        # 自动创建缺失的资产
        if self.dry_run:
            if self._asset_codes_seen:
                print(f"  [info] 涉及 {len(self._asset_codes_seen)} 个资产代码")
            return

        if getattr(self.args, "auto_create_assets", True) and self._asset_codes_seen:
            self._ensure_assets()

        # 验证
        total_prices = self.db[self.target_collection].count_documents({})
        print(f"  [verify] asset_prices 集合当前共 {total_prices} 条")

        # 抽样
        if self._asset_codes_seen:
            sample_code = sorted(self._asset_codes_seen)[0]
            count = self.db[self.target_collection].count_documents({"asset_code": sample_code})
            latest = self.db[self.target_collection].find_one(
                {"asset_code": sample_code}, sort=[("date", -1)]
            )
            print(f"  [verify] {sample_code}: {count} 条, 最新 date={latest['date'] if latest else '-'}")

    # ─── 内部方法 ─────────────────────────────────────────────────────────────

    def _detect_format(self, file_path: Path) -> str:
        """自动检测 Excel 是宽表还是长表"""
        raw = pd.read_excel(file_path, header=None, nrows=3, engine="openpyxl")
        # 宽表特征：第一行第一列含"代码"或第一行第二列起像资产代码
        first_cell = str(raw.iat[0, 0]).strip() if raw.shape[1] > 0 else ""
        if "代码" in first_cell or "code" in first_cell.lower():
            return "wide"
        # 长表特征：第一行含"日期"和"资产代码"（或类似列名）
        header_row = set(str(c).strip() for c in raw.iloc[0].tolist())
        all_mappings = {**PRICE_COLUMN_MAPPING, **_CODE_MAPPING}
        matched = sum(1 for h in header_row if h in all_mappings)
        if matched >= 2:
            return "long"
        # 默认宽表（兼容旧脚本格式）
        return "wide"

    def _parse_wide(self, file_path: Path) -> List[Dict[str, Any]]:
        """解析宽表格式（Wind/同花顺）"""
        raw = pd.read_excel(file_path, header=None, engine="openpyxl")
        if raw.shape[0] < 3 or raw.shape[1] < 2:
            raise ValueError("宽表至少需要 3 行 2 列")

        # Row 0: 代码行
        codes: List[str] = []
        for j in range(1, raw.shape[1]):
            code = str(raw.iat[0, j]).strip()
            if code and code != "nan":
                codes.append(code)
            else:
                codes.append("")

        # Row 1: 名称行
        for j in range(1, raw.shape[1]):
            code = codes[j - 1] if j - 1 < len(codes) else ""
            if code:
                name = str(raw.iat[1, j]).strip()
                if name and name != "nan":
                    self._asset_names[code] = name

        # Row 2+: 数据行
        body = raw.iloc[2:].copy()
        body = body.dropna(how="all")
        dates = pd.to_datetime(body.iloc[:, 0], errors="coerce")
        body = body.assign(_dt=dates).dropna(subset=["_dt"])

        records = []
        for idx, (_, row) in enumerate(body.iterrows()):
            date_str = pd.Timestamp(row["_dt"]).strftime("%Y-%m-%d")
            for j, code in enumerate(codes, start=1):
                if not code:
                    continue
                val = row.iloc[j] if j < len(row) else None
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    continue
                try:
                    close_f = float(val)
                except (TypeError, ValueError):
                    continue
                if close_f <= 0:
                    continue
                records.append({
                    "asset_code": code,
                    "date": date_str,
                    "close": close_f,
                    "open": None, "high": None, "low": None,
                    "volume": None, "amount": None, "scale": None,
                })
                self._asset_codes_seen.add(code)

        return records

    def _parse_long(self, file_path: Path) -> List[Dict[str, Any]]:
        """解析长表格式（标准模板）"""
        df = pd.read_excel(file_path)
        df.columns = df.columns.astype(str).str.strip()

        # 映射列名
        all_mapping = {**PRICE_COLUMN_MAPPING, **_CODE_MAPPING}
        df.rename(columns=all_mapping, inplace=True)

        if "asset_code" not in df.columns:
            raise ValueError("长表缺少必须列: 资产代码（asset_code）")
        if "date" not in df.columns:
            raise ValueError("长表缺少必须列: 日期（date）")

        df["asset_code"] = df["asset_code"].astype(str).str.strip()
        df["date"] = df["date"].apply(normalize_date)
        df = df.dropna(subset=["asset_code", "date"])
        df = df[(df["asset_code"] != "") & (df["date"] != "")]

        # 记录资产代码
        self._asset_codes_seen.update(df["asset_code"].unique())

        cols = ["asset_code", "date", "open", "high", "low", "close", "volume", "amount", "scale"]
        present_cols = [c for c in cols if c in df.columns]
        return df[present_cols].to_dict("records")

    def _ensure_assets(self):
        """确保所有涉及的资产代码在 assets 集合中存在"""
        coll = self.db["assets"]
        existing = set()
        cursor = coll.find(
            {"code": {"$in": list(self._asset_codes_seen)}},
            {"code": 1}
        )
        for doc in cursor:
            existing.add(doc["code"])

        missing = self._asset_codes_seen - existing
        if not missing:
            print(f"  [assets] 所有 {len(self._asset_codes_seen)} 个资产已存在")
            return

        now = datetime.now(timezone.utc)
        ops = []
        for code in sorted(missing):
            name = self._asset_names.get(code, code)
            ops.append(UpdateOne(
                {"code": code},
                {"$set": {
                    "code": code,
                    "name": name,
                    "instrument_type": "指数型",
                    "asset_class": "权益",
                    "security_type": None,
                    "exchange": "",
                    "description": "",
                    "is_active": True,
                    "rollover_days": None,
                    "rollover_threshold": None,
                    "rollover_window_p": None,
                    "rollover_window_q": None,
                    "substitute_code": "",
                    "switch_date": "",
                    "updated_at": now,
                }, "$setOnInsert": {"created_at": now}},
                upsert=True,
            ))
        if ops:
            result = coll.bulk_write(ops, ordered=False)
            print(f"  [assets] 自动创建 {result.upserted_count} 个新资产")


if __name__ == "__main__":
    SeedPrices.run()
