"""
汇率服务 - 提供汇率查询与向前填充

数据来源（优先级）：
1. MongoDB fx_rates 集合
2. 备选：portfilio-end/data/fx.xlsx（MongoDB 无数据时）

格式：{ date: "YYYY-MM-DD", EUR: float, USD: float, HKD: float, JPY: float, CNH: float }
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pymongo import UpdateOne

from app.config.database import Database
from app.config.collections import COL_FX_RATES

# 汇率文件路径：仅引用 portfilio-end 内 data 目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FX_XLSX_PATH = _PROJECT_ROOT / "data" / "fx.xlsx"


class FxService:
    """汇率服务"""

    FX_COLUMNS = ["EUR", "USD", "HKD", "JPY", "CNH"]

    def __init__(self):
        self._db = None
        self._collection = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.db[COL_FX_RATES]
        return self._collection

    @staticmethod
    def _dataframe_to_records(df: pd.DataFrame) -> Tuple[List[str], List[Dict[str, Any]]]:
        """解析 fx 格式 DataFrame，返回 (valid_cols, records)。"""
        if df.empty:
            return [], []

        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df.index = df.index.normalize()

        cols = {c: c.strip().upper() for c in df.columns if isinstance(c, str)}
        df.rename(columns=cols, inplace=True)

        valid_cols = [c for c in FxService.FX_COLUMNS if c in df.columns]
        if not valid_cols:
            return [], []
        df = df[valid_cols].copy()
        df = df.dropna(how="all")

        records: List[Dict[str, Any]] = []
        for dt, row in df.iterrows():
            date_str = dt.strftime("%Y-%m-%d")
            rec: Dict[str, Any] = {"date": date_str}
            has_value = False
            for col in valid_cols:
                v = row.get(col)
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    fv = float(v)
                    if fv > 0:
                        rec[col] = fv
                        has_value = True
            if has_value:
                records.append(rec)
        return valid_cols, records

    @staticmethod
    def _is_missing_stored_fx(val: Any) -> bool:
        """库内字段视为缺失时可被增量填补。"""
        if val is None:
            return True
        try:
            f = float(val)
            if math.isnan(f):
                return True
        except (TypeError, ValueError):
            return True
        return False

    async def import_from_dataframe(
        self, df: pd.DataFrame, mode: str = "replace"
    ) -> Dict[str, int]:
        """
        从 DataFrame 导入汇率数据（fx.xlsx 格式）

        mode:
        - replace: 删除集合内全部记录后插入文件中的全量数据
        - incremental: 仅填补缺失——无该日则插入；已有该日则只写入库中为空/缺失的币种列，不覆盖已有数值
        """
        valid_cols, records = self._dataframe_to_records(df)
        if not records:
            return {"inserted": 0, "updated": 0, "skipped_cells": 0}

        mode = (mode or "replace").strip().lower()
        if mode not in ("replace", "incremental"):
            mode = "replace"

        if mode == "replace":
            await self.collection.delete_many({})
            result = await self.collection.insert_many(records)
            return {"inserted": len(result.inserted_ids), "updated": 0, "skipped_cells": 0}

        inserted = 0
        updated = 0
        skipped_cells = 0

        # 预加载文件涉及日期的已有数据，避免逐条 find_one
        record_dates = [r["date"] for r in records]
        existing_map: Dict[str, Dict[str, Any]] = {}
        chunk_size = 500
        for ci in range(0, len(record_dates), chunk_size):
            chunk = record_dates[ci:ci + chunk_size]
            cursor = self.collection.find({"date": {"$in": chunk}})
            async for doc in cursor:
                existing_map[doc["date"]] = doc

        # 分离为插入和更新操作
        insert_docs: List[Dict[str, Any]] = []
        update_ops: List[UpdateOne] = []

        for rec in records:
            date_str = rec["date"]
            existing = existing_map.get(date_str)
            if not existing:
                insert_docs.append(rec)
                continue
            to_set: Dict[str, Any] = {}
            for col in self.FX_COLUMNS:
                if col not in rec:
                    continue
                new_v = rec[col]
                if new_v is None or (isinstance(new_v, float) and new_v <= 0):
                    continue
                old_v = existing.get(col)
                if self._is_missing_stored_fx(old_v):
                    to_set[col] = new_v
                else:
                    skipped_cells += 1
            if to_set:
                update_ops.append(
                    UpdateOne({"date": date_str}, {"$set": to_set})
                )

        # 批量插入
        if insert_docs:
            batch_size = 1000
            for bi in range(0, len(insert_docs), batch_size):
                batch = insert_docs[bi:bi + batch_size]
                result = await self.collection.insert_many(batch, ordered=False)
                inserted += len(result.inserted_ids)

        # 批量更新
        if update_ops:
            batch_size = 1000
            for bi in range(0, len(update_ops), batch_size):
                batch = update_ops[bi:bi + batch_size]
                result = await self.collection.bulk_write(batch, ordered=False)
                updated += result.modified_count

        return {"inserted": inserted, "updated": updated, "skipped_cells": skipped_cells}

    async def upsert_manual_rates(
        self,
        date_str: str,
        rates: Dict[str, Optional[float]],
    ) -> None:
        """
        手动录入：按日期 upsert，仅对传入且大于 0 的币种字段写入（覆盖该日该列），其余列保留原值。
        """
        to_set: Dict[str, Any] = {"date": date_str}
        for col in self.FX_COLUMNS:
            v = rates.get(col)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv <= 0:
                continue
            to_set[col] = fv
        if len(to_set) <= 1:
            raise ValueError("请至少填写一个大于 0 的汇率")
        await self.collection.update_one(
            {"date": date_str},
            {"$set": to_set},
            upsert=True,
        )

    @staticmethod
    def _load_from_xlsx(
        path: Optional[Path] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        从 data/fx.xlsx 加载汇率（仅引用 portfilio-end 内路径）
        """
        p = path or _FX_XLSX_PATH
        if not p.exists():
            return pd.DataFrame(columns=FxService.FX_COLUMNS)
        try:
            df = pd.read_excel(p, index_col=0, parse_dates=True)
        except Exception:
            return pd.DataFrame(columns=FxService.FX_COLUMNS)
        if df.empty:
            return pd.DataFrame(columns=FxService.FX_COLUMNS)
        df.columns = df.columns.astype(str).str.strip().str.upper()
        valid = [c for c in FxService.FX_COLUMNS if c in df.columns]
        if not valid:
            return pd.DataFrame(columns=FxService.FX_COLUMNS)
        df = df[[c for c in valid]].copy()
        for col in FxService.FX_COLUMNS:
            if col not in df.columns:
                df[col] = np.nan
        df = df[FxService.FX_COLUMNS]
        df.index = pd.to_datetime(df.index).normalize()
        if start_date or end_date:
            mask = True
            if start_date:
                mask = mask & (df.index >= pd.Timestamp(start_date))
            if end_date:
                mask = mask & (df.index <= pd.Timestamp(end_date))
            df = df.loc[mask]
        return df.sort_index()

    async def get_rates_dataframe(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        获取汇率 DataFrame，index 为日期。
        MongoDB 无数据时回退到 data/fx.xlsx。
        """
        try:
            query = {}
            if start_date or end_date:
                query["date"] = {}
                if start_date:
                    query["date"]["$gte"] = start_date
                if end_date:
                    query["date"]["$lte"] = end_date

            cursor = self.collection.find(query).sort("date", 1)
            rows = []
            async for doc in cursor:
                rows.append(doc)
            if rows:
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
                for col in self.FX_COLUMNS:
                    if col not in df.columns:
                        df[col] = np.nan
                df = df[self.FX_COLUMNS]
                return df.sort_index()
        except Exception:
            pass
        # MongoDB 无数据或异常时，从 data/fx.xlsx 加载
        return self._load_from_xlsx(start_date=start_date, end_date=end_date)

    async def get_rate(
        self,
        currency: str,
        date: pd.Timestamp,
        df_cache: Optional[pd.DataFrame] = None,
    ) -> float:
        """
        获取指定日期、货币的汇率，缺失时向前填充
        CNH/CNY 恒为 1.0
        """
        if currency in ("CNH", "CNY"):
            return 1.0

        currency = currency.upper()
        if currency not in self.FX_COLUMNS:
            return 1.0

        if df_cache is not None:
            df = df_cache
        else:
            df = await self.get_rates_dataframe()

        if df.empty or currency not in df.columns:
            return 1.0

        # 向前填充
        s = df[currency].replace([np.inf, -np.inf], np.nan).ffill()
        if date in s.index:
            v = s.loc[date]
            if pd.notna(v):
                return float(v)
        valid = s.index[s.index <= date]
        if len(valid) > 0:
            v = s.loc[valid[-1]]
            if pd.notna(v):
                return float(v)
        return 1.0
