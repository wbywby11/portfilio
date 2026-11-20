"""宏观与估值序列服务 —— macro_series 集合的导入、查询与统计

集合形态（长表）：{code, date, value, series_type, unit, source}，业务主键 (code, date)。
不落 assets / asset_prices：这些序列不是可交易资产，只作为策略面板
（``PANEL_LOADERS["macro_series"]``）与前端图表的数据源。

导入文件两种形态，自动识别：

- **宽表**（官方模板）：第一列为日期，后续每列列名为序列代码，逐列展开成长表
- **长表**：列包含 ``code`` 与 ``value``（可选 ``date`` / ``series_type`` / ``unit`` / ``source``）

可选的「序列说明」工作表（默认名见 ``MACRO_SERIES_META_SHEET``）给出每个序列的
``series_type`` / ``unit`` / ``source``。缺该表时统一落 ``other`` + 空单位，并在
导入结果里报告数量 —— 不从代码名猜类型（``_PE`` / ``_PB`` 之类的后缀不是契约）。

导入模式：

- ``replace``：**仅清空文件中出现的序列代码**后重写，其他序列不受影响。不做整集合
  清空 —— macro_series 是一个集合装多条序列，整清空会让「只导入一条序列」的操作
  顺带删掉别的序列
- ``incremental``：只补库内没有的 (code, date)，已有取值不覆盖

``value`` 只要求是有限数值，**不作正负限制**：PB、信用利差、ERP 分量都可以为负，
照搬 fx 的「值必须大于 0」会把这些序列静默丢成空。
"""
from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from pymongo import UpdateOne

from app.config.collections import COL_MACRO_SERIES
from app.config.database import Database
from app.schemas.field_mappings import (
    MACRO_SERIES_COLUMN_MAPPING,
    MACRO_SERIES_DEFAULT_TYPE,
    MACRO_SERIES_META_SHEET,
    MACRO_SERIES_TYPES,
)

# Excel 空列头读进来是 "Unnamed: 3"，不是序列代码
_UNNAMED_HEADER = re.compile(r"^Unnamed:\s*\d+$", re.IGNORECASE)

# 列名映射的大小写无感查找表（"Pe" / "PE" / "pe" 都认）
_MAPPING_LOWER: Dict[str, str] = {
    str(k).strip().lower(): v for k, v in MACRO_SERIES_COLUMN_MAPPING.items()
}

_BATCH_INSERT = 2000
_BATCH_UPSERT = 1000


def _map_column(name: Any) -> Optional[str]:
    """列名 → 标准字段名；未登记的返回 None（宽表里即「该列是序列代码」）。"""
    s = str(name or "").strip()
    if not s:
        return None
    return MACRO_SERIES_COLUMN_MAPPING.get(s) or _MAPPING_LOWER.get(s.lower())


class MacroSeriesService:
    """宏观与估值序列服务"""

    def __init__(self):
        self._db = None
        self._collection = None
        self._indexes_ready = False

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.db[COL_MACRO_SERIES]
        return self._collection

    async def ensure_indexes(self) -> None:
        """建查询与去重所需索引（幂等，仅首次生效）。"""
        if self._indexes_ready:
            return
        await self.collection.create_index(
            [("code", 1), ("date", 1)], unique=True, name="uniq_code_date"
        )
        await self.collection.create_index(
            [("series_type", 1), ("code", 1)], name="idx_type_code"
        )
        self._indexes_ready = True

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_code(code: Any) -> str:
        """序列代码规范化：去空白 + 转大写。

        库内与策略参数两侧都必须走这里，否则 ``h00922_pe`` 与 ``H00922_PE``
        会被当成两条序列（或策略取不到已导入的序列）。
        """
        return str(code or "").strip().upper()

    @staticmethod
    def _valid_types() -> str:
        return "、".join(sorted(MACRO_SERIES_TYPES))

    @classmethod
    def parse_meta_sheet(
        cls, meta_df: Optional[pd.DataFrame]
    ) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
        """解析「序列说明」表 → ({code: {series_type, unit, source}}, 告警)。

        表中出现的 code 必须是数据表里也有的序列，否则告警但不阻断（说明表可以
        提前写好整份序列清单，分几次导数据）。
        """
        warnings: List[str] = []
        if meta_df is None or meta_df.empty:
            return {}, warnings

        df = meta_df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        mapped = {c: _map_column(c) for c in df.columns}
        code_col = next((c for c, f in mapped.items() if f == "code"), None)
        if code_col is None:
            warnings.append(
                "序列说明表缺少「序列代码」列，已按 other 归类全部序列"
            )
            return {}, warnings

        meta: Dict[str, Dict[str, Any]] = {}
        for _, row in df.iterrows():
            code = cls.normalize_code(row.get(code_col))
            if not code or _UNNAMED_HEADER.match(code):
                continue
            stype = str(row.get(next((c for c, f in mapped.items() if f == "series_type"), ""), "") or "").strip()
            if stype and stype not in MACRO_SERIES_TYPES:
                warnings.append(
                    f"序列 {code} 的 series_type={stype!r} 不在受控词表内"
                    f"（可选：{cls._valid_types()}），已按 {MACRO_SERIES_DEFAULT_TYPE} 归档"
                )
                stype = MACRO_SERIES_DEFAULT_TYPE
            unit_col = next((c for c, f in mapped.items() if f == "unit"), None)
            source_col = next((c for c, f in mapped.items() if f == "source"), None)
            meta[code] = {
                "series_type": stype or MACRO_SERIES_DEFAULT_TYPE,
                "unit": _clean_text(row.get(unit_col)) if unit_col else None,
                "source": _clean_text(row.get(source_col)) if source_col else None,
            }
        return meta, warnings

    @classmethod
    def _parse_long(
        cls,
        df: pd.DataFrame,
        mapped: Dict[str, Optional[str]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """长表解析：每行一条记录，列已映射为 code / value / date / series_type ...。"""
        code_col = next((c for c, f in mapped.items() if f == "code"), None)
        value_col = next((c for c, f in mapped.items() if f == "value"), None)
        date_col = next((c for c, f in mapped.items() if f == "date"), None)
        type_col = next((c for c, f in mapped.items() if f == "series_type"), None)
        unit_col = next((c for c, f in mapped.items() if f == "unit"), None)
        source_col = next((c for c, f in mapped.items() if f == "source"), None)
        if date_col is None:
            raise ValueError(
                "长表中未找到日期列：需要一列名为 日期/date 的列（"
                f"当前列：{list(df.columns)}）"
            )

        dates = pd.to_datetime(df[date_col], errors="coerce")
        codes = df[code_col].map(cls.normalize_code)
        raw_values = df[value_col]
        values = pd.to_numeric(raw_values, errors="coerce")

        records: List[Dict[str, Any]] = []
        # empty_cell 是源单元格本就为空（各序列起止日不同属正常），不计为错误；
        # bad_value 是「填了值但不是数字」（如 N/A、—），才是需要提醒的
        skipped = {"bad_date": 0, "bad_value": 0, "empty_cell": 0, "empty_code": 0}
        for dt, code, v, raw, stype, unit, source in zip(
            dates,
            codes,
            values,
            raw_values,
            df[type_col] if type_col else [None] * len(df),
            df[unit_col] if unit_col else [None] * len(df),
            df[source_col] if source_col else [None] * len(df),
        ):
            if not code or _UNNAMED_HEADER.match(code):
                skipped["empty_code"] += 1
                continue
            if pd.isna(dt):
                skipped["bad_date"] += 1
                continue
            if not _is_finite(v):
                skipped["empty_cell" if pd.isna(raw) else "bad_value"] += 1
                continue
            records.append(
                {
                    "code": code,
                    "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                    "value": float(v),
                    "series_type": _clean_text(stype) or MACRO_SERIES_DEFAULT_TYPE,
                    "unit": _clean_text(unit),
                    "source": _clean_text(source),
                }
            )
        return records, {"format": "long", "skipped": skipped}

    @classmethod
    def _parse_wide(
        cls, df: pd.DataFrame, mapped: Dict[str, Optional[str]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """宽表解析：第一列（或映射为 date 的列）为日期，其余列为序列代码。"""
        date_col = next((c for c, f in mapped.items() if f == "date"), None)
        if date_col is None:
            date_col = df.columns[0]
        series_cols = [
            c
            for c in df.columns
            if c != date_col and str(c or "").strip() and not _UNNAMED_HEADER.match(str(c).strip())
        ]
        if not series_cols:
            raise ValueError("宽表中未找到序列列：第一列应为日期，后续每列列名为序列代码")

        dates = pd.to_datetime(df[date_col], errors="coerce")
        records: List[Dict[str, Any]] = []
        skipped = {"bad_date": 0, "bad_value": 0, "empty_cell": 0, "empty_code": 0}
        for col in series_cols:
            code = cls.normalize_code(col)
            raw_values = df[col]
            values = pd.to_numeric(raw_values, errors="coerce")
            for dt, v, raw in zip(dates, values, raw_values):
                if pd.isna(dt):
                    # 同一行的日期对各列共用，按列计数会重复报；只按列内首个空日计
                    continue
                if not _is_finite(v):
                    skipped["empty_cell" if pd.isna(raw) else "bad_value"] += 1
                    continue
                records.append(
                    {
                        "code": code,
                        "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                        "value": float(v),
                        "series_type": MACRO_SERIES_DEFAULT_TYPE,
                        "unit": None,
                        "source": None,
                    }
                )
        bad_dates = int(dates.isna().sum())
        skipped["bad_date"] = bad_dates
        return records, {"format": "wide", "skipped": skipped}

    @classmethod
    def parse_dataframe(
        cls,
        df: pd.DataFrame,
        meta_df: Optional[pd.DataFrame] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """解析导入文件 → (records, report)。

        report: {format, codes, skipped: {...}, duplicates, meta_applied, warnings}
        """
        if df is None or df.empty:
            raise ValueError("数据表为空，请检查文件内容")

        work = df.copy()
        work.columns = [str(c).strip() for c in work.columns]
        mapped = {c: _map_column(c) for c in work.columns}
        fields = {v for v in mapped.values() if v}

        if {"code", "value"} <= fields:
            records, report = cls._parse_long(work, mapped)
        else:
            if "date" not in fields:
                # 宽表首列常读成 "Unnamed: 0" 或写了别的名字，按位置当日期列
                first = work.columns[0]
                work = work.rename(columns={first: "date"})
                mapped = {c: _map_column(c) for c in work.columns}
            records, report = cls._parse_wide(work, mapped)

        if not records:
            raise ValueError(
                "未解析出任何有效记录：请确认第一列为日期、后续列名为序列代码，"
                f"且数值为数字。跳过统计：{report['skipped']}"
            )

        # 同文件内 (code, date) 重复时保留最后一条（后写的覆盖先写的）
        deduped: Dict[Tuple[str, str], Dict[str, Any]] = {}
        dup = 0
        for rec in records:
            key = (rec["code"], rec["date"])
            if key in deduped:
                dup += 1
            deduped[key] = rec
        records = list(deduped.values())

        meta, meta_warnings = cls.parse_meta_sheet(meta_df)
        applied = 0
        for rec in records:
            info = meta.get(rec["code"])
            if not info:
                continue
            rec["series_type"] = info.get("series_type") or rec["series_type"]
            if info.get("unit"):
                rec["unit"] = info["unit"]
            if info.get("source"):
                rec["source"] = info["source"]
            applied += 1

        codes = sorted({r["code"] for r in records})
        missing_meta = [c for c in codes if c not in meta]
        warnings = list(meta_warnings)
        if missing_meta:
            warnings.append(
                f"{len(missing_meta)} 条序列未在序列说明表中登记，已按 "
                f"{MACRO_SERIES_DEFAULT_TYPE} 归类："
                + "、".join(missing_meta[:10])
                + ("…" if len(missing_meta) > 10 else "")
            )

        report.update(
            {
                "codes": codes,
                "duplicates": dup,
                "meta_applied": applied,
                "warnings": warnings,
            }
        )
        return records, report

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    async def import_dataframes(
        self,
        df: pd.DataFrame,
        mode: str = "replace",
        meta_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """导入宏观序列（宽表或长表）。

        Args:
            df: 数据表（宽表或长表）
            mode: replace（按序列覆盖）| incremental（只补缺失 (code, date)）
            meta_df: 可选「序列说明」表

        Returns:
            {inserted, updated, skipped_existing, skipped_cells, duplicates,
             modes, codes, date_range, warnings, meta_applied}
        """
        mode_norm = (mode or "replace").strip().lower()
        if mode_norm not in ("replace", "incremental"):
            raise ValueError("mode 须为 replace（按序列覆盖）或 incremental（增量填补）")

        records, report = self.parse_dataframe(df, meta_df)
        await self.ensure_indexes()

        codes = report["codes"]
        inserted = 0
        skipped_existing = 0
        updated = 0

        if mode_norm == "replace":
            await self.collection.delete_many({"code": {"$in": codes}})
            for i in range(0, len(records), _BATCH_INSERT):
                batch = records[i : i + _BATCH_INSERT]
                result = await self.collection.insert_many(batch, ordered=False)
                inserted += len(result.inserted_ids)
        else:
            ops = [
                UpdateOne(
                    {"code": rec["code"], "date": rec["date"]},
                    {"$setOnInsert": rec},
                    upsert=True,
                )
                for rec in records
            ]
            for i in range(0, len(ops), _BATCH_UPSERT):
                result = await self.collection.bulk_write(
                    ops[i : i + _BATCH_UPSERT], ordered=False
                )
                inserted += result.upserted_count
                updated += result.modified_count
            skipped_existing = len(records) - inserted - updated

        dates = [r["date"] for r in records]
        return {
            "inserted": inserted,
            "updated": updated,
            "skipped_existing": skipped_existing,
            "skipped_cells": report["skipped"],
            "duplicates": report["duplicates"],
            "mode": mode_norm,
            "format": report["format"],
            "codes": codes,
            "meta_applied": report["meta_applied"],
            "date_range": f"{min(dates)} ~ {max(dates)}",
            "warnings": report["warnings"],
        }

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def list_series(
        self, series_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """列出库内全部序列：code / series_type / unit / source / count / start / end。"""
        match: Dict[str, Any] = {}
        stype = (series_type or "").strip()
        if stype:
            if stype not in MACRO_SERIES_TYPES:
                raise ValueError(
                    f"未知的 series_type={stype!r}，可选：{self._valid_types()}"
                )
            match["series_type"] = stype

        pipeline: List[Dict[str, Any]] = []
        if match:
            pipeline.append({"$match": match})
        pipeline += [
            # 先按日期倒序，使 $first 取到该序列最新一条的元数据（跨日一致，可复现）
            {"$sort": {"code": 1, "date": -1}},
            {
                "$group": {
                    "_id": "$code",
                    "count": {"$sum": 1},
                    "start_date": {"$min": "$date"},
                    "end_date": {"$max": "$date"},
                    "series_type": {"$first": "$series_type"},
                    "unit": {"$first": "$unit"},
                    "source": {"$first": "$source"},
                    "series": {"$addToSet": "$series_type"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        rows: List[Dict[str, Any]] = []
        async for doc in self.collection.aggregate(pipeline):
            types = [t for t in (doc.get("series") or []) if t]
            rows.append(
                {
                    "code": doc["_id"],
                    "series_type": types[0] if types else None,
                    "series_types": sorted(types),
                    "unit": doc.get("unit"),
                    "source": doc.get("source"),
                    "count": int(doc.get("count") or 0),
                    "start_date": doc.get("start_date"),
                    "end_date": doc.get("end_date"),
                }
            )
        return rows

    async def stats(self) -> Dict[str, Any]:
        """集合级统计：条数、序列数、日期范围、按类型的序列数与条数。"""
        series = await self.list_series()
        if not series:
            return {
                "count": 0,
                "series_count": 0,
                "start_date": None,
                "end_date": None,
                "by_type": [],
            }
        by_type: Dict[str, Dict[str, int]] = {}
        for s in series:
            key = s.get("series_type") or MACRO_SERIES_DEFAULT_TYPE
            slot = by_type.setdefault(key, {"series_count": 0, "count": 0})
            slot["series_count"] += 1
            slot["count"] += s["count"]
        starts = [s["start_date"] for s in series if s.get("start_date")]
        ends = [s["end_date"] for s in series if s.get("end_date")]
        return {
            "count": sum(s["count"] for s in series),
            "series_count": len(series),
            "start_date": min(starts) if starts else None,
            "end_date": max(ends) if ends else None,
            "by_type": [
                {"series_type": k, "label": MACRO_SERIES_TYPES.get(k, k), **v}
                for k, v in sorted(by_type.items())
            ],
        }

    async def get_series(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.Series:
        """取单条序列的时序（index=DatetimeIndex，name=code），供前端图表。"""
        norm = self.normalize_code(code)
        if not norm:
            raise ValueError("序列代码不能为空")
        query: Dict[str, Any] = {"code": norm}
        if start_date or end_date:
            query["date"] = {}
            if start_date:
                query["date"]["$gte"] = start_date
            if end_date:
                query["date"]["$lte"] = end_date
        docs = await self.collection.find(
            query, {"_id": 0, "date": 1, "value": 1}
        ).sort("date", 1).to_list(length=None)
        if not docs:
            return pd.Series(dtype="float64", name=norm)
        s = pd.Series(
            [float(d["value"]) for d in docs],
            index=pd.to_datetime([d["date"] for d in docs]),
            name=norm,
        )
        return s.sort_index()

    @staticmethod
    def build_template() -> Tuple[io.BytesIO, str]:
        """生成导入模板：数据 sheet（宽表）+ 序列说明 sheet。"""
        data = pd.DataFrame(
            {
                "日期": ["2024-01-02", "2024-01-03"],
                "H00922_PE": [17.85, 17.91],
                "CBA_10Y": [2.56, 2.57],
            }
        )
        meta = pd.DataFrame(
            {
                "序列代码": ["H00922_PE", "CBA_10Y"],
                "序列类型": ["valuation", "bond_yield"],
                "单位": ["倍", "%"],
                "来源": ["中证指数", "中债"],
            }
        )
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            data.to_excel(writer, sheet_name="数据", index=False)
            meta.to_excel(writer, sheet_name=MACRO_SERIES_META_SHEET, index=False)
        output.seek(0)
        return output, "macro_series_template.xlsx"


def _clean_text(value: Any) -> Optional[str]:
    """单元格 → 去空白字符串；空值 / NaN / "nan" 一律返回 None。"""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    return s


def _is_finite(value: Any) -> bool:
    """是否为可用于计算的有限数值（允许 0 与负数）。"""
    if value is None:
        return False
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(f))
