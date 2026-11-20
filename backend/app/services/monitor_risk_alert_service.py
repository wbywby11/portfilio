"""监控风险预警记录服务

管理 ``monitor_risk_alerts`` 集合：策略通道与组合通道写入同一份记录，
用 ``monitor_kind`` 区分来源（strategy / portfolio）。

写入语义：一次运行 = 某监控实例在某信号日的一批预警。
按 ``(monitor_id, batch_id, signal_date)`` 先删后插，重跑幂等；历史日期保留。

批次维度（``batch_id``）约定与 ``monitor_operation_service`` 一致：
写入侧空值归一到 ``LEGACY_BATCH_ID``（预警永远有所属批次），
读取侧 ``batch_id=None`` 表示跨批次不过滤。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config.collections import COL_MONITOR_RISK_ALERTS
from app.config.database import Database
from app.models.monitor import LEGACY_BATCH_ID, MonitorRiskAlert

SEVERITY_VALUES = ("green", "yellow", "red", "info")
SIGNAL_TYPE_VALUES = ("vol_compare", "corr_reversal", "stale_skip")
# 排序权重：red 置顶，info（停更跳过提示）垫底；Mongo 字符串排序不满足业务顺序，用聚合映射
SEVERITY_RANK = {"red": 0, "yellow": 1, "green": 2, "info": 3}


def _write_batch_id(batch_id: Optional[str]) -> str:
    """写入侧批次号归一：空值落 ``legacy``，保证预警永远有所属批次。"""
    text = str(batch_id or "").strip()
    return text or LEGACY_BATCH_ID


def _severity_rank_stage() -> Dict[str, Any]:
    """聚合阶段：把 severity 映射为 `_severity_rank` 供自定义排序。"""
    return {
        "$addFields": {
            "_severity_rank": {
                "$switch": {
                    "branches": [
                        {"case": {"$eq": ["$severity", sev]}, "then": rank}
                        for sev, rank in SEVERITY_RANK.items()
                    ],
                    "default": 9,
                }
            }
        }
    }


class MonitorRiskAlertService:
    """风险预警记录 CRUD 服务"""

    def __init__(self):
        self.db = Database.get_database()
        self.collection = self.db[COL_MONITOR_RISK_ALERTS]

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    async def replace_for_signal_date(
        self,
        monitor_id: str,
        monitor_kind: str,
        signal_date: str,
        alerts: List[Dict[str, Any]],
        batch_id: Optional[str] = None,
    ) -> int:
        """覆盖写入某监控实例某信号日的预警批次（幂等）。

        Args:
            monitor_id: 监控实例 ID
            monitor_kind: strategy / portfolio
            signal_date: 信号日 YYYY-MM-DD
            alerts: RiskAlert.to_dict() 列表
            batch_id: 所属运行批次；空值归一为 ``legacy``

        Returns:
            实际写入条数
        """
        if not monitor_id or not signal_date:
            return 0
        batch = _write_batch_id(batch_id)
        # 先清同批次同日旧预警：重跑（初始化/日常补算）不产生重复预警；
        # 限定 batch_id 后，旧批次已封存的预警不会被新一次跑批抹除。
        await self.collection.delete_many({
            "monitor_id": monitor_id,
            "batch_id": batch,
            "signal_date": signal_date,
        })
        if not alerts:
            return 0

        now = datetime.now()
        docs = []
        for item in alerts:
            doc = MonitorRiskAlert(
                alert_id=str(uuid.uuid4()),
                monitor_id=monitor_id,
                batch_id=batch,
                monitor_kind=monitor_kind,
                signal_type=str(item.get("signal_type") or ""),
                severity=str(item.get("severity") or ""),
                trigger_value=float(item.get("trigger_value") or 0.0),
                threshold=float(item.get("threshold") or 0.0),
                window_pair=dict(item.get("window_pair") or {}),
                asset_codes=[str(c) for c in (item.get("asset_codes") or [])],
                signal_date=signal_date,
                detail=dict(item.get("detail") or {}),
                created_at=now,
            ).to_dict()
            docs.append(doc)
        result = await self.collection.insert_many(docs)
        return len(result.inserted_ids)

    async def delete_by_monitor(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> int:
        """删除某监控实例的预警（测试清理用）；传 ``batch_id`` 时只删该批次。"""
        query: Dict[str, Any] = {"monitor_id": monitor_id}
        if batch_id:
            query["batch_id"] = str(batch_id)
        result = await self.collection.delete_many(query)
        return result.deleted_count

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def list_alerts(
        self,
        monitor_id: Optional[str] = None,
        severity: Optional[str] = None,
        signal_type: Optional[str] = None,
        monitor_kind: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
        batch_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按条件查询预警（red→yellow→green→info 优先，同级按信号日倒序）。

        Args:
            monitor_id: 监控实例 ID；不传则跨实例查询（组合详情页汇总用）
            severity: green / yellow / red / info
            signal_type: vol_compare / corr_reversal / stale_skip
            monitor_kind: strategy / portfolio
            start_date / end_date: 信号日区间 YYYY-MM-DD（闭区间）
            limit: 返回条数上限
            offset: 跳过条数（分页）
            batch_id: 限定运行批次；为空时跨批次
        """
        query = self._build_query(
            monitor_id=monitor_id, severity=severity, signal_type=signal_type,
            monitor_kind=monitor_kind, start_date=start_date, end_date=end_date,
            batch_id=batch_id,
        )
        limit = max(1, int(limit or 200))
        pipeline = [
            {"$match": query},
            _severity_rank_stage(),
            {"$sort": {"_severity_rank": 1, "signal_date": -1, "trigger_value": -1}},
            {"$skip": max(0, int(offset or 0))},
            {"$limit": limit},
        ]
        docs = await self.collection.aggregate(pipeline).to_list(length=limit)
        return [self._serialize(doc) for doc in docs]

    async def search_alerts(
        self,
        monitor_id: Optional[str] = None,
        severity: Optional[str] = None,
        signal_type: Optional[str] = None,
        monitor_kind: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        batch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """分页查询预警（端点用）：返回 items / total / counts / limit / offset。"""
        query = self._build_query(
            monitor_id=monitor_id, severity=severity, signal_type=signal_type,
            monitor_kind=monitor_kind, start_date=start_date, end_date=end_date,
            batch_id=batch_id,
        )
        limit = max(1, int(limit or 50))
        offset = max(0, int(offset or 0))
        total = await self.collection.count_documents(query)

        counts = {sev: 0 for sev in SEVERITY_VALUES}
        rows = await self.collection.aggregate([
            {"$match": query},
            {"$group": {"_id": "$severity", "n": {"$sum": 1}}},
        ]).to_list(length=10)
        for row in rows:
            if row.get("_id") in counts:
                counts[row["_id"]] = int(row.get("n") or 0)

        items = await self.list_alerts(
            monitor_id=monitor_id, severity=severity, signal_type=signal_type,
            monitor_kind=monitor_kind, start_date=start_date, end_date=end_date,
            limit=limit, offset=offset, batch_id=batch_id,
        )
        return {
            "items": items,
            "total": total,
            "counts": counts,
            "limit": limit,
            "offset": offset,
        }

    @staticmethod
    def _build_query(
        monitor_id: Optional[str] = None,
        severity: Optional[str] = None,
        signal_type: Optional[str] = None,
        monitor_kind: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """拼装查询条件（signal_date 为 YYYY-MM-DD 字符串，可直接比较）。"""
        query: Dict[str, Any] = {}
        if monitor_id:
            query["monitor_id"] = monitor_id
        if severity:
            query["severity"] = severity
        if signal_type:
            query["signal_type"] = signal_type
        if monitor_kind:
            query["monitor_kind"] = monitor_kind
        if batch_id:
            query["batch_id"] = str(batch_id)
        if start_date or end_date:
            date_query: Dict[str, Any] = {}
            if start_date:
                date_query["$gte"] = start_date
            if end_date:
                date_query["$lte"] = end_date
            query["signal_date"] = date_query
        return query

    @staticmethod
    def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
        """把 Mongo 文档转为可 JSON 输出形态（去掉聚合临时字段）。"""
        doc = dict(doc)
        doc.pop("_severity_rank", None)
        doc["_id"] = str(doc["_id"])
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        return doc

    async def latest_batch(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """取某监控实例最新一个信号日的预警批次与级别统计。

        Args:
            batch_id: 限定运行批次；为空时跨批次取最新。

        Returns:
            ``{"signal_date": ..., "monitor_kind": ..., "counts": {...}, "items": [...]}``；
            无记录时 signal_date 为空、items 为空。
        """
        base_query = {"monitor_id": monitor_id}
        if batch_id:
            base_query["batch_id"] = str(batch_id)
        latest = await self.collection.find_one(
            base_query, sort=[("signal_date", -1)]
        )
        if not latest:
            return {"signal_date": None, "monitor_kind": None, "counts": {}, "items": []}
        signal_date = latest.get("signal_date")
        items = await self.list_alerts(
            monitor_id=monitor_id, limit=500, batch_id=batch_id
        )
        items = [d for d in items if d.get("signal_date") == signal_date]
        counts = {s: 0 for s in SEVERITY_VALUES}
        for item in items:
            sev = item.get("severity")
            if sev in counts:
                counts[sev] += 1
        logger.debug(
            f"[风险预警] 读取最新批次: monitor={monitor_id}, date={signal_date}, "
            f"counts={counts}"
        )
        return {
            "signal_date": signal_date,
            "monitor_kind": latest.get("monitor_kind"),
            "counts": counts,
            "items": items,
        }
