# -*- coding: utf-8 -*-
"""因子截面面板服务 —— factor_panel 集合的导入编排与查询.

一个数据集（dataset）的一期（as_of_date）一股（code）一行。因子值收进 factors dict，
不写死因子列名，换一套因子只改导入文件与策略参数，不改表结构。
本集合被多个数据集共用，导入与查询均按 dataset 隔离（受控清单见
field_mappings.FACTOR_DATASETS）。

解析与写入步骤见 FactorPanelImporterMixin（factor_panel_importer.py）；
本文件负责连接、索引、导入编排与对外查询。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from app.config.collections import COL_FACTOR_PANEL
from app.config.database import Database
from app.models.factor_panel import normalize_date_str
from app.schemas.field_mappings import FACTOR_DATASETS, factor_name_mapping_for
from app.schemas.import_protocol import ImportMode, ImportResponse
from app.services.factor_panel_importer import FactorPanelImporterMixin

_SUPPORTED_MODES = (ImportMode.UPSERT, ImportMode.REPLACE, ImportMode.INCREMENTAL)
_MODE_HINT = " / ".join(m.value for m in _SUPPORTED_MODES)
_MAX_ERROR_DETAILS = 50
# 库内行的 dataset 缺失时的展示标签（迁移前旧数据）；不隐藏，直接暴露给调用方
_MISSING_DATASET_LABEL = "<缺失 dataset（未迁移）>"

# 按期汇总：因子键要先把 factors dict 拆成键数组，再在分组里收集去重
# 分组键带 dataset：本集合多数据集共存，不带会把不同数据集的同期日归成一行
_PERIOD_PIPELINE: List[Dict[str, Any]] = [
    {"$project": {
        "dataset": 1,
        "as_of_date": 1,
        "code": 1,
        "industry": 1,
        "total_mv": 1,
        "factor_keys": {"$map": {
            "input": {"$objectToArray": {"$ifNull": ["$factors", {}]}},
            "as": "kv",
            "in": "$$kv.k",
        }},
    }},
    {"$group": {
        "_id": {"dataset": "$dataset", "as_of_date": "$as_of_date"},
        "row_count": {"$sum": 1},
        "codes": {"$addToSet": "$code"},
        "industries": {"$addToSet": "$industry"},
        "factor_keys": {"$addToSet": "$factor_keys"},
        "mv_row_count": {"$sum": {"$cond": [
            {"$gt": [{"$ifNull": ["$total_mv", 0]}, 0]}, 1, 0,
        ]}},
    }},
    {"$sort": {"_id.dataset": 1, "_id.as_of_date": 1}},
]

# 因子键清单（含出现次数），供前端填写策略参数时参照；按 dataset 分开统计
_FACTOR_KEY_PIPELINE: List[Dict[str, Any]] = [
    {"$project": {
        "dataset": 1,
        "kv": {"$objectToArray": {"$ifNull": ["$factors", {}]}},
    }},
    {"$unwind": "$kv"},
    {"$group": {
        "_id": {"dataset": "$dataset", "key": "$kv.k"},
        "count": {"$sum": 1},
    }},
    {"$sort": {"_id.dataset": 1, "count": -1, "_id.key": 1}},
]

# 库内已有数据集汇总：行数 / 期数 / 券数
_DATASET_PIPELINE: List[Dict[str, Any]] = [
    {"$group": {
        "_id": "$dataset",
        "row_count": {"$sum": 1},
        "periods": {"$addToSet": "$as_of_date"},
        "codes": {"$addToSet": "$code"},
    }},
    {"$sort": {"_id": 1}},
]


class FactorPanelService(FactorPanelImporterMixin):
    """因子截面面板服务（factor_panel 集合）"""

    _indexes_ready = False

    def __init__(self, db=None):
        self._db = db
        self._collection = None
        self._asset_service = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.db[COL_FACTOR_PANEL]
        return self._collection

    @property
    def asset_service(self):
        """资产主数据服务（代码引用完整性校验走它，不越权直连 assets 集合）。"""
        if self._asset_service is None:
            from app.services.asset_service import AssetService

            self._asset_service = AssetService()
        return self._asset_service

    async def ensure_indexes(self) -> None:
        """创建业务主键与查询索引（幂等，进程内仅首次执行）。

        主键为 (dataset, as_of_date, code) 三元。dataset 维度引入前的三个旧索引
        必须先删：旧的 uniq_period_code{as_of_date,code} 是唯一索引，留着会让
        不同 dataset 的同 (as_of_date, code) 无法共存，与三元主键语义直接冲突。
        """
        if FactorPanelService._indexes_ready:
            return
        await self._drop_legacy_indexes()
        await self.collection.create_index(
            [("dataset", 1), ("as_of_date", 1), ("code", 1)],
            unique=True, name="uniq_dataset_period_code",
        )
        await self.collection.create_index(
            [("dataset", 1), ("code", 1), ("as_of_date", 1)],
            name="idx_dataset_code_period",
        )
        await self.collection.create_index(
            [("dataset", 1), ("as_of_date", 1), ("industry", 1)],
            name="idx_dataset_period_industry",
        )
        FactorPanelService._indexes_ready = True

    async def _drop_legacy_indexes(self) -> None:
        """删除 dataset 维度引入前的旧索引（不存在则跳过，幂等）。"""
        from pymongo.errors import OperationFailure

        for name in ("uniq_period_code", "idx_code_period", "idx_period_industry"):
            try:
                await self.collection.drop_index(name)
                logger.info("[FactorPanel] 已移除旧索引 {}（主键改三元）", name)
            except OperationFailure:
                pass  # 索引本就不存在，无需处理

    # ───────────────────────── 导入编排 ─────────────────────────

    async def import_from_excel(
        self,
        file_content: bytes,
        dataset: str,
        mode: str = ImportMode.UPSERT.value,
        filename: Optional[str] = None,
        operator: str = "system",
        as_of_date: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """从 Excel 导入因子截面（一个文件可含任意期数，按 as_of_date 列分组）。

        整个文件写入同一个 dataset：数据集是文件级属性，不做逐行列，
        避免同一文件内混入两个数据集。

        Args:
            file_content: Excel 文件字节流
            dataset: 目标数据集标识，必填且必须在 FACTOR_DATASETS 受控清单内；
                同时决定因子列名映射取哪一张分组表
            mode: upsert（默认，按主键逐行覆盖）/ replace（仅覆盖本 dataset 中
                  文件出现的那几期）/ incremental（只写库内没有的主键）
            filename: 源文件名，仅用于审计留痕
            operator: 操作人，仅用于审计留痕
            as_of_date: 前端指定的决策日（信号日）YYYY-MM-DD；文件无日期列时作为整期决策日
            dry_run: True=只解析预演（返回期/行数/因子键/告警），不写库不审计

        Returns:
            ImportResponse 的 dict 形式，另附 dataset / periods / period_rows /
            factor_keys / warnings

        Raises:
            ValueError: dataset 为空或不在受控清单、文件无法解析、缺少必填列、
                列名映射歧义、导入模式或生效日不支持
        """
        resolved_dataset = self._resolve_dataset(dataset)
        name_mapping = factor_name_mapping_for(resolved_dataset)
        import_mode = self._resolve_mode(mode)
        default_as_of = self._resolve_optional_period(as_of_date)
        await self.ensure_indexes()
        started = datetime.now()

        # 解析与逐行构建是 CPU 密集段，丢线程池，不阻塞 event loop
        loop = asyncio.get_running_loop()
        frame, fixed, factor_cols, unmapped = await loop.run_in_executor(
            None, self._parse_frame, file_content, name_mapping, default_as_of
        )
        docs, errors, skipped_reasons, non_numeric = await loop.run_in_executor(
            None, self._build_documents, frame, fixed, factor_cols,
            resolved_dataset, name_mapping, default_as_of,
        )
        warnings = await self._collect_warnings(docs, unmapped, non_numeric)
        periods = sorted({d["as_of_date"] for d in docs})
        date_range = f"{periods[0]} ~ {periods[-1]}" if periods else None

        inserted = updated = 0
        import_id: Optional[str] = None
        if not dry_run:
            inserted, updated, skipped_existing = await self._write(
                docs, import_mode, resolved_dataset, periods
            )
            if skipped_existing:
                skipped_reasons["already_in_db"] = skipped_existing
            import_id = await self._write_audit(
                import_mode, filename, operator, date_range, errors,
                {"dataset": resolved_dataset, "total_rows": len(frame),
                 "inserted": inserted, "updated": updated,
                 "skipped": sum(skipped_reasons.values()), "errors": len(errors)},
                int((datetime.now() - started).total_seconds() * 1000),
            )

        response = ImportResponse(
            target_collection=COL_FACTOR_PANEL,
            mode=import_mode,
            total_rows=len(frame),
            inserted_count=inserted,
            updated_count=updated,
            skipped_count=sum(skipped_reasons.values()),
            error_count=len(errors),
            errors=errors[:_MAX_ERROR_DETAILS],
            skipped_reasons=skipped_reasons,
            date_range=date_range,
            import_id=import_id,
        )
        payload = self._enrich_payload(response, docs, warnings, resolved_dataset)
        logger.info(
            "[FactorPanel] {} dataset={} mode={} rows={} ins={} upd={} skip={} err={} periods={}",
            "预演" if dry_run else "导入完成", resolved_dataset, import_mode.value,
            len(frame), inserted, updated, sum(skipped_reasons.values()),
            len(errors), len(periods),
        )
        return payload

    @staticmethod
    def _resolve_dataset(dataset: Optional[str]) -> str:
        """校验并规范化 dataset；空值或不在受控清单内直接报错（不静默兜底）。

        Raises:
            ValueError: dataset 为空，或不在 FACTOR_DATASETS 清单内
        """
        available = "、".join(sorted(FACTOR_DATASETS))
        name = str(dataset or "").strip()
        if not name:
            raise ValueError(
                "dataset 不能为空：factor_panel 被多个数据集共用，导入必须指明写入"
                f"哪个数据集，可选 {available}"
            )
        if name not in FACTOR_DATASETS:
            raise ValueError(
                f"未知的因子数据集 dataset={name!r}，可选 {available}；"
                "新增数据集请先在 field_mappings.FACTOR_DATASETS 登记"
            )
        return name

    @staticmethod
    def _resolve_optional_period(as_of_date: Optional[str]) -> Optional[str]:
        """规范化前端指定的决策日；空值返回 None，格式无法识别抛 ValueError。"""
        if as_of_date is None or not str(as_of_date).strip():
            return None
        period = normalize_date_str(as_of_date)
        if not period:
            raise ValueError(f"决策日 as_of_date 无法识别: {as_of_date!r}，请使用 YYYY-MM-DD")
        return period

    @staticmethod
    def _enrich_payload(
        response: ImportResponse,
        docs: List[Dict[str, Any]],
        warnings: Dict[str, Any],
        dataset: str,
    ) -> Dict[str, Any]:
        """在标准 ImportResponse 上附加前端预演/核对所需的派生字段。

        snapshot_periods：整期无因子值的期日。这些期会按成分快照写入
        （策略侧全截面入选等权），与打分期行为不同，必须显式回传让前端展示。
        经 _split_snapshot_periods 后，保留下来的每一期要么全有因子、要么全无，
        故按「存在无因子行」判定即可。
        """
        payload = response.dict()
        period_rows: Dict[str, int] = {}
        period_data_dates: Dict[str, Set[str]] = {}
        factor_keys: Set[str] = set()
        snapshot_periods: Set[str] = set()
        for doc in docs:
            period_rows[doc["as_of_date"]] = period_rows.get(doc["as_of_date"], 0) + 1
            factors = doc.get("factors") or {}
            factor_keys.update(factors.keys())
            if not factors:
                snapshot_periods.add(doc["as_of_date"])
            data_date = doc.get("data_date")
            if data_date:
                period_data_dates.setdefault(doc["as_of_date"], set()).add(data_date)
        # 同一期日必须对应同一个因子取数日：混入两个取数日 = 截面拼了两批数据，
        # 不报错但必须显式上报（策略无法从数值上发现这件事）。
        mixed_data_dates = sorted(p for p, v in period_data_dates.items() if len(v) > 1)
        if mixed_data_dates:
            warnings["periods_with_multiple_data_dates"] = mixed_data_dates
        payload["dataset"] = dataset
        payload["periods"] = sorted(period_rows)
        payload["period_rows"] = period_rows
        payload["period_data_dates"] = {
            p: sorted(v) for p, v in sorted(period_data_dates.items())
        }
        payload["factor_keys"] = sorted(factor_keys)
        payload["snapshot_periods"] = sorted(snapshot_periods)
        payload["warnings"] = warnings
        return payload

    @staticmethod
    def _resolve_mode(mode: str) -> ImportMode:
        """校验导入模式，不支持的值直接抛错（不静默回退到 upsert）。"""
        try:
            resolved = ImportMode((mode or ImportMode.UPSERT.value).strip().lower())
        except ValueError:
            raise ValueError(f"不支持的导入模式: {mode!r}，可选 {_MODE_HINT}")
        if resolved not in _SUPPORTED_MODES:
            raise ValueError(
                f"因子截面导入不支持 {resolved.value} 模式，可选 {_MODE_HINT}"
            )
        return resolved

    # ───────────────────────── 查询与维护 ─────────────────────────

    async def get_stats(self, dataset: Optional[str] = None) -> Dict[str, Any]:
        """面板总览：总行数、期数、起止期日、涉及代码数。

        Args:
            dataset: 指定数据集时只统计该数据集；None 时统计全库并附各数据集分解
        """
        flt = self._dataset_filter(dataset)
        total, periods, codes = await asyncio.gather(
            self.collection.count_documents(flt),
            self.collection.distinct("as_of_date", flt),
            self.collection.distinct("code", flt),
        )
        dates = sorted(p for p in periods if p)
        stats: Dict[str, Any] = {
            "dataset": dataset,
            "count": total,
            "period_count": len(dates),
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "stock_count": len([c for c in codes if c]),
        }
        if dataset is None:
            stats["datasets"] = await self.get_datasets()
        return stats

    async def get_datasets(self) -> List[Dict[str, Any]]:
        """数据集清单：受控清单中已登记的 + 库内实际存在的，并给出各自规模。

        两边取并集：已登记但库内无数据的数据集也要列出（row_count=0），
        否则前端看不到可导入的目标；库内存在但未登记的数据集标 registered=False，
        不静默忽略。
        """
        rows = await self.collection.aggregate(_DATASET_PIPELINE).to_list(None)
        present: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            present[row.get("_id") or _MISSING_DATASET_LABEL] = row
        out: List[Dict[str, Any]] = []
        for name in sorted(set(present) | set(FACTOR_DATASETS)):
            row = present.get(name) or {}
            periods = sorted(p for p in (row.get("periods") or []) if p)
            out.append({
                "dataset": name,
                "label": FACTOR_DATASETS.get(name, ""),
                "registered": name in FACTOR_DATASETS,
                "row_count": row.get("row_count", 0),
                "period_count": len(periods),
                "start_date": periods[0] if periods else None,
                "end_date": periods[-1] if periods else None,
                "code_count": len([c for c in (row.get("codes") or []) if c]),
            })
        return out

    async def get_periods(self, dataset: Optional[str] = None) -> List[Dict[str, Any]]:
        """按期汇总：数据集 / 期日 / 行数 / 证券数 / 行业数 / 因子键 / 有市值行数。"""
        rows = await self.collection.aggregate(
            self._with_match(_PERIOD_PIPELINE, self._dataset_filter(dataset))
        ).to_list(None)
        return [self._format_period(row) for row in rows]

    async def get_factor_names(self, dataset: Optional[str] = None) -> List[Dict[str, Any]]:
        """库内已出现过的因子键及出现次数，按数据集分开（次数降序）。"""
        rows = await self.collection.aggregate(
            self._with_match(_FACTOR_KEY_PIPELINE, self._dataset_filter(dataset))
        ).to_list(None)
        out: List[Dict[str, Any]] = []
        for row in rows:
            group = row.get("_id") or {}
            out.append({
                "dataset": group.get("dataset") or _MISSING_DATASET_LABEL,
                "name": group.get("key"),
                "count": row.get("count", 0),
            })
        return out

    @staticmethod
    def _dataset_filter(dataset: Optional[str]) -> Dict[str, Any]:
        """把可选 dataset 参数转成 Mongo 过滤条件；None 表示不限数据集。"""
        if dataset is None or not str(dataset).strip():
            return {}
        return {"dataset": FactorPanelService._resolve_dataset(dataset)}

    @staticmethod
    def _with_match(
        pipeline: List[Dict[str, Any]], flt: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """给聚合管道前置 $match；无过滤条件时原样返回（不生成空 $match）。"""
        if not flt:
            return pipeline
        return [{"$match": flt}] + pipeline

    async def get_period(self, dataset: str, as_of_date: str) -> List[Dict[str, Any]]:
        """读取某数据集某一期的全部截面行（按代码升序）。

        Args:
            dataset: 数据集标识，必填且须在受控清单内
            as_of_date: 期日，YYYY-MM-DD 或 YYYYMMDD

        Returns:
            该数据集该期全部文档（不含 _id）

        Raises:
            ValueError: dataset 为空或不在受控清单、期日格式无法识别

        dataset 为何必填：本集合多数据集共存，不指定会把同一期日下
        不同数据集的行混在一起返回，截面就不可用了。
        """
        resolved = self._resolve_dataset(dataset)
        cursor = self.collection.find(
            {"dataset": resolved, "as_of_date": self._resolve_period(as_of_date)},
            {"_id": 0},
        ).sort("code", 1)
        return [doc async for doc in cursor]

    async def delete_period(self, dataset: str, as_of_date: str) -> Dict[str, Any]:
        """整期删除（导错重来）；只删本数据集的该期。

        Args:
            dataset: 数据集标识，必填且须在受控清单内
            as_of_date: 期日，YYYY-MM-DD 或 YYYYMMDD

        Returns:
            {"dataset": 数据集, "as_of_date": 规范化期日, "deleted_count": 删除行数}

        Raises:
            ValueError: dataset 为空或不在受控清单、期日格式无法识别

        dataset 为何必填：删除条件不带 dataset 会跨数据集删掉同一期日的
        全部行，与导入侧 REPLACE 的跨数据集误删是同一类事故。
        """
        resolved = self._resolve_dataset(dataset)
        period = self._resolve_period(as_of_date)
        result = await self.collection.delete_many(
            {"dataset": resolved, "as_of_date": period}
        )
        logger.info(
            "[FactorPanel] 删除期 dataset={} {} 共 {} 行",
            resolved, period, result.deleted_count,
        )
        return {
            "dataset": resolved,
            "as_of_date": period,
            "deleted_count": int(result.deleted_count),
        }

    @staticmethod
    def _resolve_period(as_of_date: str) -> str:
        """把期日参数规范化为 YYYY-MM-DD。"""
        period = normalize_date_str(as_of_date)
        if not period:
            raise ValueError("as_of_date 不能为空")
        return period

    @staticmethod
    def _format_period(row: Dict[str, Any]) -> Dict[str, Any]:
        """聚合结果 → 前端可用的期汇总结构（分组键为 {dataset, as_of_date}）。"""
        keys = sorted({k for grp in (row.get("factor_keys") or []) for k in (grp or [])})
        industries = {i for i in (row.get("industries") or []) if i}
        group = row.get("_id") or {}
        return {
            "dataset": group.get("dataset") or _MISSING_DATASET_LABEL,
            "as_of_date": group.get("as_of_date"),
            "row_count": row.get("row_count", 0),
            "stock_count": len(row.get("codes") or []),
            "industry_count": len(industries),
            "factor_keys": keys,
            "mv_row_count": row.get("mv_row_count", 0),
        }
