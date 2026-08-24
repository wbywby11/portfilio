# -*- coding: utf-8 -*-
"""
导入审计日志服务

DATA_IMPORT_SPEC.md Layer 4 规定：
  每次导入操作写入 _import_audit_log 集合，记录操作人、时间、目标集合、统计、错误。

使用方式：
    from app.services.import_audit_service import ImportAuditService

    audit = ImportAuditService()
    import_id = await audit.log_import(
        target_collection="asset_prices",
        import_mode="upsert",
        source_type="excel",
        source_filename="prices_2024.xlsx",
        operator="user_001",
        stats={"total_rows": 100, "inserted": 95, "updated": 3, "skipped": 2, "errors": 0},
        date_range="2024-01-01 ~ 2024-06-30",
        duration_ms=1234,
    )
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config.database import Database
from app.config.collections import COL_IMPORT_AUDIT_LOG


class ImportAuditService:
    """导入审计日志服务"""

    def __init__(self, db=None):
        self._db = db

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        return self.db[COL_IMPORT_AUDIT_LOG]

    async def log_import(
        self,
        target_collection: str,
        import_mode: str,
        source_type: str = "excel",
        source_filename: Optional[str] = None,
        operator: str = "system",
        stats: Optional[Dict[str, int]] = None,
        error_summary: Optional[List[str]] = None,
        date_range: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> str:
        """
        记录一次导入操作到审计日志。

        Parameters
        ----------
        target_collection : str
            目标集合名
        import_mode : str
            导入模式（upsert / replace / incremental / strict）
        source_type : str
            来源类型（excel / json / api_upstream）
        source_filename : str, optional
            源文件名
        operator : str
            操作人（用户ID / "agent" / "system"）
        stats : dict, optional
            统计信息 {total_rows, inserted, updated, skipped, errors}
        error_summary : list, optional
            错误摘要（前 10 条）
        date_range : str, optional
            数据日期范围
        duration_ms : int, optional
            耗时（毫秒）

        Returns
        -------
        str
            审计日志 _id（字符串形式）
        """
        doc = {
            "target_collection": target_collection,
            "import_mode": import_mode,
            "source_type": source_type,
            "source_filename": source_filename,
            "operator": operator,
            "created_at": datetime.now(),
            "stats": stats or {},
            "error_summary": (error_summary or [])[:10],
            "date_range": date_range,
            "duration_ms": duration_ms,
        }

        try:
            result = await self.collection.insert_one(doc)
            import_id = str(result.inserted_id)
            logger.info(
                "[ImportAudit] {} → {} mode={} rows={} ins={} upd={} err={} id={}",
                source_type,
                target_collection,
                import_mode,
                (stats or {}).get("total_rows", 0),
                (stats or {}).get("inserted", 0),
                (stats or {}).get("updated", 0),
                (stats or {}).get("errors", 0),
                import_id,
            )
            return import_id
        except Exception as e:
            # 审计日志写入失败不应阻断导入主流程
            logger.warning("[ImportAudit] 写入审计日志失败: {}", e)
            return ""

    async def ensure_indexes(self):
        """确保审计日志集合的索引存在"""
        try:
            await self.collection.create_index(
                [("target_collection", 1), ("created_at", -1)]
            )
            await self.collection.create_index(
                [("operator", 1), ("created_at", -1)]
            )
        except Exception as e:
            logger.warning("[ImportAudit] 创建索引失败: {}", e)

    async def get_recent_logs(
        self,
        target_collection: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """查询最近的导入审计日志"""
        query: Dict[str, Any] = {}
        if target_collection:
            query["target_collection"] = target_collection

        cursor = self.collection.find(query).sort("created_at", -1).limit(limit)
        logs = await cursor.to_list(length=limit)
        for log in logs:
            log["_id"] = str(log["_id"])
        return logs
