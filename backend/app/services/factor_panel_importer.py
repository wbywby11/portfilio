# -*- coding: utf-8 -*-
"""因子截面导入链路（FactorPanelService 的解析与写入部分）.

按 DATA_IMPORT_SPEC Layer 1/3 落地：列名映射只认 field_mappings 的口径表，
解析 → 类型转换 → 校验 → 分批写入 → 审计。行级错误不中断整体导入，
口径歧义（缺列、多列映射同一字段）直接抛错，不猜、不兜底。
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Union

import pandas as pd
from loguru import logger
from pydantic import ValidationError
from pymongo import UpdateOne

from app.config.collections import COL_FACTOR_PANEL
from app.models.factor_panel import FactorPanel, normalize_date_str
from app.schemas.field_mappings import (
    FACTOR_PANEL_COLUMN_MAPPING,
    FACTOR_PANEL_MV_UNIT_BY_COLUMN,
    FACTOR_PANEL_REQUIRED_FIELDS,
    categorical_factor_keys_for,
)
from app.schemas.import_protocol import ImportErrorDetail, ImportErrorCode, ImportMode
from app.services.factor_panel_templates import DATA_SHEET_NAME

_BATCH_SIZE = 1000
_MV_FIELDS = ("total_mv", "free_float_mv")
_BLANK_TOKENS = ("", "nan", "nat", "none", "null", "-", "—", "n/a", "na")


def _to_float(value: Any) -> Optional[float]:
    """单元格值转 float；空值/占位符/无法解析一律返回 None，不静默当 0。

    百分号直接剥掉：因子列口径是「百分数填原值」，12.34% 与 12.34 同义。
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("%", "")
        if text.lower() in _BLANK_TOKENS:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN


def _to_text(value: Any) -> Optional[str]:
    """单元格值转类别因子文本；空值/占位符/NaN 返回 None（不写空串）。

    pandas 读出的空单元格在 object 列里是 float('nan')，故先单独拦 NaN；
    其余空值写法走 _BLANK_TOKENS，与数值因子共用同一套口径。
    """
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    text = str(value).strip()
    if not text or text.lower() in _BLANK_TOKENS:
        return None
    return text


def _scaled_mv(value: Any, source_column: Optional[str]) -> Optional[float]:
    """市值转 float，并按列名登记的倍率统一换算为「元」。"""
    number = _to_float(value)
    if number is None:
        return None
    return number * FACTOR_PANEL_MV_UNIT_BY_COLUMN.get(str(source_column).strip(), 1.0)


def _error_code(exc_type: str) -> ImportErrorCode:
    """pydantic 校验错误类型 → 统一导入错误码。"""
    if exc_type == "missing":
        return ImportErrorCode.MISSING_REQUIRED
    if exc_type == "value_error":
        return ImportErrorCode.INVALID_VALUE
    return ImportErrorCode.TYPE_MISMATCH


class FactorPanelImporterMixin:
    """因子截面导入步骤集合（宿主类需提供 db / collection / asset_service）。"""

    # ───────────────────────── 解析 ─────────────────────────

    def _parse_frame(
        self, file_content: bytes, name_mapping: Dict[str, str],
        default_as_of_date: Optional[str] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, str], List[str], List[str]]:
        """同步解析段：读 sheet + 列分类。

        CPU 密集，由调用方放线程池执行（见 FactorPanelService.import_from_excel）。

        Args:
            file_content: Excel 字节流
            name_mapping: 本 dataset 的「中文列名 → 英文因子键」映射，由 service 层
                按 dataset 取好（factor_name_mapping_for）；本层不引用全局扁平表
            default_as_of_date: 前端指定的决策日；文件无日期列时用它，
                此时 as_of_date 不再作为必需列强制要求

        Returns:
            (数据表, 固定字段名→原列名, 因子列名列表, 无法识别的列名列表)
        """
        frame = self._read_sheet(file_content)
        fixed, factor_cols, unmapped = self._split_columns(frame, name_mapping, default_as_of_date)
        return frame, fixed, factor_cols, unmapped

    @staticmethod
    def _read_sheet(file_content: bytes) -> pd.DataFrame:
        """读取数据 sheet（优先模板 sheet 名，否则第一个），清掉全空行。"""
        try:
            workbook = pd.ExcelFile(io.BytesIO(file_content))
        except Exception as exc:
            raise ValueError(f"Excel 解析失败: {exc}")
        names = workbook.sheet_names
        sheet = DATA_SHEET_NAME if DATA_SHEET_NAME in names else names[0]
        frame = pd.read_excel(workbook, sheet_name=sheet)
        if frame is None or frame.empty:
            raise ValueError(f"sheet「{sheet}」没有数据行")
        frame.columns = [str(c).strip() for c in frame.columns]
        frame = frame.dropna(how="all").reset_index(drop=True)
        if frame.empty:
            raise ValueError(f"sheet「{sheet}」只有表头，没有有效数据行")
        return frame

    @staticmethod
    def _split_columns(
        frame: pd.DataFrame, name_mapping: Dict[str, str],
        default_as_of_date: Optional[str] = None,
    ) -> Tuple[Dict[str, str], List[str], List[str]]:
        """把 Excel 列分成「固定字段列 / 因子列 / 无法识别列」。

        命中 FACTOR_PANEL_COLUMN_MAPPING 的是固定字段列；命中 name_mapping 的
        一律按映射键登记为因子列（允许类别因子：发行人等文本列）；其余未映射列
        只要能解析出至少一个数值即视为因子列（因子本就允许部分缺失），
        全为非数值（如备注文本）则忽略。

        Args:
            frame: 数据表
            name_mapping: 本 dataset 的「中文列名 → 英文因子键」映射
            default_as_of_date: 前端指定的决策日；非空时 as_of_date 可不作为列存在

        Returns:
            (固定字段名 → 原列名, 因子列名列表, 无法识别的列名列表)

        Raises:
            ValueError: 缺少必填列，或多列映射到同一字段 / 同一因子键
        """
        fixed: Dict[str, str] = {}
        factor_cols: List[str] = []
        factor_keys: Dict[str, str] = {}
        unmapped: List[str] = []

        for column in frame.columns:
            field = FACTOR_PANEL_COLUMN_MAPPING.get(column)
            if field:
                if field in fixed:
                    raise ValueError(
                        f"列「{column}」与「{fixed[field]}」都映射到字段 {field}，请只保留一列"
                    )
                fixed[field] = column
                continue
            mapped_key = name_mapping.get(column)
            if mapped_key is None and pd.to_numeric(frame[column], errors="coerce").notna().sum() == 0:
                unmapped.append(column)
                continue
            key = mapped_key or column
            if key in factor_keys:
                raise ValueError(
                    f"因子列「{column}」与「{factor_keys[key]}」都映射到因子键 {key}，请只保留一列"
                )
            factor_keys[key] = column
            factor_cols.append(column)

        missing = sorted(f for f in FACTOR_PANEL_REQUIRED_FIELDS if f not in fixed)
        # 前端已指定决策日时，文件可不含 as_of_date 列（逐行填充见 _row_to_doc）
        if default_as_of_date and "as_of_date" in missing:
            missing.remove("as_of_date")
        if missing:
            raise ValueError(f"缺少必填列：{'、'.join(missing)}（可用列名见导入模板）")
        return fixed, factor_cols, unmapped

    def _build_documents(
        self,
        frame: pd.DataFrame,
        fixed: Dict[str, str],
        factor_cols: List[str],
        dataset: str,
        name_mapping: Dict[str, str],
        default_as_of_date: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[ImportErrorDetail], Dict[str, int], Dict[str, int]]:
        """逐行构建文档，收集行级错误、跳过原因与非数值单元格计数。

        单行失败不中断整体导入。类别因子键按 dataset 取（categorical_factor_keys_for），
        在循环外算一次，不逐行重复校验。

        Returns:
            (文档列表, 行级错误, 跳过原因计数, 数值因子列里的非数值单元格计数)
        """
        categorical_keys = categorical_factor_keys_for(dataset)
        docs: List[Dict[str, Any]] = []
        errors: List[ImportErrorDetail] = []
        skipped: Dict[str, int] = {}
        non_numeric: Dict[str, int] = {}
        seen: Set[Tuple[str, str]] = set()

        for index, row in frame.iterrows():
            doc, error, skip_reason, bad_cells = self._row_to_doc(
                row, int(index), fixed, factor_cols, dataset, name_mapping,
                categorical_keys, default_as_of_date,
            )
            for column, count in bad_cells.items():
                non_numeric[column] = non_numeric.get(column, 0) + count
            if error is not None:
                errors.append(error)
                continue
            if skip_reason is not None:
                skipped[skip_reason] = skipped.get(skip_reason, 0) + 1
                continue
            key = (doc["as_of_date"], doc["code"])
            if key in seen:
                errors.append(ImportErrorDetail(
                    row_index=int(index), code=ImportErrorCode.DUPLICATE_KEY,
                    field="as_of_date,code",
                    message=f"文件内主键重复：{key[0]} / {key[1]}，仅保留首次出现的行",
                ))
                continue
            seen.add(key)
            docs.append(doc)

        kept, empty_skipped = self._split_snapshot_periods(docs)
        if empty_skipped:
            skipped["factor_empty"] = skipped.get("factor_empty", 0) + empty_skipped
        return kept, errors, skipped, non_numeric

    @staticmethod
    def _split_snapshot_periods(
        docs: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], int]:
        """按整期定性因子全空的行：整期都无因子 = 成分快照期（保留），
        同期内只有个别行无因子 = 漏填（跳过并计数）。

        为何按整期判：策略把「截面缺打分因子列」当作成分快照期处理
        （全截面入选等权，见 bond_factor_score_index._is_constituent_snapshot），
        快照期本就没有因子值，一律跳过会让历史成分期无法经 Excel 通道导入。
        而同期内只有部分行无因子几乎总是漏填：写进去会让这些券在打分初筛
        时被剔除，故仍然跳过，并在提示里计数。

        Returns:
            (保留的文档列表按期日重排, 因漏填而跳过的行数)
        """
        by_period: Dict[str, List[Dict[str, Any]]] = {}
        for doc in docs:
            by_period.setdefault(doc["as_of_date"], []).append(doc)
        kept: List[Dict[str, Any]] = []
        empty_skipped = 0
        for period in sorted(by_period):
            rows = by_period[period]
            blanks = [d for d in rows if not d["factors"]]
            if len(blanks) == len(rows):
                kept.extend(rows)  # 整期无因子：成分快照期，全期保留
            else:
                kept.extend(d for d in rows if d["factors"])
                empty_skipped += len(blanks)
        return kept, empty_skipped

    @staticmethod
    def _row_to_doc(
        row: pd.Series,
        index: int,
        fixed: Dict[str, str],
        factor_cols: List[str],
        dataset: str,
        name_mapping: Dict[str, str],
        categorical_keys: FrozenSet[str],
        default_as_of_date: Optional[str] = None,
    ) -> Tuple[
        Optional[Dict[str, Any]],
        Optional[ImportErrorDetail],
        Optional[str],
        Dict[str, int],
    ]:
        """单行 → FactorPanel 文档。

        因子列按登记分两路：类别因子键（categorical_keys）按文本保留，其余
        按数值解析。数值列里出现非空文本（如 Wind 导出的「亏损」「--」）时置空
        但计数上报，不静默丢弃：静默丢会让该因子在部分行凭空缺失，排查时无从下手。

        Returns:
            (doc, error, skip_reason, 非数值单元格计数)，前三者中至多一个非 None
        """
        raw = {field: row.get(column) for field, column in fixed.items()}
        factors: Dict[str, Union[float, str]] = {}
        bad_cells: Dict[str, int] = {}
        for column in factor_cols:
            key = name_mapping.get(column, column)
            cell = row.get(column)
            if key in categorical_keys:
                text = _to_text(cell)
                if text is not None:
                    factors[key] = text
                continue
            value = _to_float(cell)
            if value is not None:
                factors[key] = value
            elif _to_text(cell) is not None:
                bad_cells[column] = 1

        # 因子全空不在本层定性：是「成分快照期」还是「漏填」要看同一期内的
        # 其他行，故先建出 factors={} 的文档，整期定性见 _split_snapshot_periods。

        # 决策日缺失/为空时用前端指定值；无法解析的原值保留，交给模型校验报错，不静默替换
        as_of_raw = raw.get("as_of_date")
        if default_as_of_date is not None:
            try:
                if normalize_date_str(as_of_raw) is None:
                    as_of_raw = default_as_of_date
            except (ValueError, TypeError):
                pass

        doc: Dict[str, Any] = {
            "dataset": dataset,
            "as_of_date": as_of_raw,
            "data_date": raw.get("data_date"),
            "code": raw.get("code"),
            # 文本固定列过一遍空值归一化：pandas 读出的 NaN 直接落库会被模型
            # 强转为字符串 "nan"，在 industry 上会被当成一个真实分组参与行业限额
            "name": _to_text(raw.get("name")),
            "industry": _to_text(raw.get("industry")),
            "factors": factors,
            "source": _to_text(raw.get("source")),
        }
        for field in _MV_FIELDS:
            doc[field] = _scaled_mv(raw.get(field), fixed.get(field))

        for field in _MV_FIELDS:
            value = doc[field]
            if value is not None and value <= 0:
                return None, ImportErrorDetail(
                    row_index=index, code=ImportErrorCode.INVALID_VALUE, field=field,
                    message=f"{field}={value} 必须 > 0；不提供市值请留空，不要填 0",
                    raw_value=value,
                ), None, bad_cells

        try:
            model = FactorPanel(**doc)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = str(first.get("loc", (None,))[0])
            return None, ImportErrorDetail(
                row_index=index, code=_error_code(first.get("type", "")), field=field,
                message=f"{field}: {first.get('msg')}", raw_value=doc.get(field),
            ), None, bad_cells

        payload = model.dict(exclude={"id"})
        payload["data_date"] = payload.get("data_date") or payload["as_of_date"]
        payload["imported_at"] = datetime.now()
        return payload, None, None, bad_cells

    async def _collect_warnings(
        self, docs: List[Dict[str, Any]], unmapped: List[str],
        non_numeric: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """统计不阻断导入、但会影响后续回测的问题。"""
        codes = {d["code"] for d in docs if d.get("code")}
        known = await self.asset_service.filter_existing_codes(codes)
        unknown = sorted(codes - known)
        return {
            "code_not_in_assets": len(unknown),
            "unknown_codes_sample": unknown[:20],
            "unmapped_columns": unmapped,
            # 数值因子列里出现文本的行数（已置空）：{列名: 行数}
            "non_numeric_cells": dict(non_numeric or {}),
        }

    # ───────────────────────── 写入 ─────────────────────────

    async def _write(
        self, docs: List[Dict[str, Any]], mode: ImportMode, dataset: str,
        periods: List[str],
    ) -> Tuple[int, int, int]:
        """按模式写入，返回 (inserted, updated, 因已存在而跳过的行数)。"""
        if not docs:
            return 0, 0, 0
        if mode is ImportMode.REPLACE:
            # 只覆盖「本 dataset 中、文件里出现的那几期」，其他期与其他 dataset 原样保留。
            # 删除条件必须带 dataset：本集合被多个数据集共用，只按期日删会跨 dataset 误删。
            await self.collection.delete_many(
                {"dataset": dataset, "as_of_date": {"$in": periods}}
            )
            return await self._insert_batches(docs), 0, 0
        if mode is ImportMode.INCREMENTAL:
            existing = await self._existing_keys(dataset, {d["as_of_date"] for d in docs})
            fresh = [d for d in docs if (d["as_of_date"], d["code"]) not in existing]
            return await self._insert_batches(fresh), 0, len(docs) - len(fresh)
        return await self._upsert_batches(docs)

    async def _upsert_batches(self, docs: List[Dict[str, Any]]) -> Tuple[int, int, int]:
        """按业务主键分批 upsert（重复导入结果一致）。

        Returns:
            (inserted, updated, 因已存在而跳过的行数)；upsert 模式不跳过任何行，
            第三位恒为 0，但必须占位：调用方按三元解包，少返一个会直接 ValueError。
        """
        inserted = updated = 0
        for start in range(0, len(docs), _BATCH_SIZE):
            batch = docs[start:start + _BATCH_SIZE]
            ops = [
                UpdateOne(
                    # 主键三元：不带 dataset 会跨数据集覆盖同 (as_of_date, code) 的行
                    {"dataset": d["dataset"], "as_of_date": d["as_of_date"], "code": d["code"]},
                    {"$set": d},
                    upsert=True,
                )
                for d in batch
            ]
            result = await self.collection.bulk_write(ops, ordered=False)
            inserted += result.upserted_count
            updated += result.modified_count
        return inserted, updated, 0

    async def _insert_batches(self, docs: List[Dict[str, Any]]) -> int:
        """分批插入，返回实际写入条数。"""
        inserted = 0
        for start in range(0, len(docs), _BATCH_SIZE):
            result = await self.collection.insert_many(
                docs[start:start + _BATCH_SIZE], ordered=False
            )
            inserted += len(result.inserted_ids)
        return inserted

    async def _existing_keys(self, dataset: str, periods: Set[str]) -> Set[Tuple[str, str]]:
        """读取本 dataset 这些期日下已存在的 (as_of_date, code) 主键集合。"""
        cursor = self.collection.find(
            {"dataset": dataset, "as_of_date": {"$in": sorted(periods)}},
            {"as_of_date": 1, "code": 1, "_id": 0},
        )
        return {(d["as_of_date"], d["code"]) async for d in cursor}

    async def _write_audit(
        self,
        mode: ImportMode,
        filename: Optional[str],
        operator: str,
        date_range: Optional[str],
        errors: List[ImportErrorDetail],
        stats: Dict[str, Any],
        duration_ms: int,
    ) -> Optional[str]:
        """写导入审计日志（stats 内记 dataset，便于按数据集追溯）；审计失败只告警，不阻断导入。"""
        try:
            from app.services.import_audit_service import ImportAuditService

            audit = ImportAuditService(db=self.db)
            return await audit.log_import(
                target_collection=COL_FACTOR_PANEL,
                import_mode=mode.value,
                source_type="excel",
                source_filename=filename,
                operator=operator,
                stats=stats,
                error_summary=[e.message for e in errors[:10]],
                date_range=date_range,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            logger.warning("[FactorPanel] 审计日志写入失败（不阻断导入）: {}", exc)
            return None
