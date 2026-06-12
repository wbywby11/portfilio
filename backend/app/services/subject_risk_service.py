"""
主体观点风险统计服务（薄封装）

底层逻辑见 app.services.data_hub_service.DataHubService，
connector_id = subject_opinion_risk。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models.subject_risk import SubjectRiskImportRequest, SubjectRiskQueryRequest
from app.services.data_hub_service import DataHubService, subject_risk_legacy_query_to_hub


SUBJECT_CONNECTOR_ID = "subject_opinion_risk"


class SubjectRiskService:
    """兼容旧 SubjectRiskService 公有方法签名"""

    def __init__(self) -> None:
        self._hub = DataHubService()

    async def ensure_indexes(self) -> None:
        from app.models.data_connector import get_connector

        conn = get_connector(SUBJECT_CONNECTOR_ID)
        if conn:
            await self._hub.ensure_indexes(conn)

    async def import_from_upstream(self, req: SubjectRiskImportRequest) -> Dict[str, Any]:
        if hasattr(req, "model_dump"):
            body = req.model_dump(mode="json")
        else:
            body = req.dict()
        return await self._hub.import_from_upstream(SUBJECT_CONNECTOR_ID, body)

    async def query_records(self, q: SubjectRiskQueryRequest) -> Dict[str, Any]:
        hub_q = subject_risk_legacy_query_to_hub(q)
        return await self._hub.query_records(SUBJECT_CONNECTOR_ID, hub_q)

    async def list_batches(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        return await self._hub.list_batches(SUBJECT_CONNECTOR_ID, page=page, page_size=page_size)

    async def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        return await self._hub.get_batch(SUBJECT_CONNECTOR_ID, batch_id)

    async def get_latest_fields(self) -> List[Dict[str, Any]]:
        return await self._hub.get_latest_fields(SUBJECT_CONNECTOR_ID)

    async def stats_overview(self) -> Dict[str, Any]:
        return await self._hub.stats_overview(SUBJECT_CONNECTOR_ID)

    async def get_record(self, risk_id: str) -> Optional[Dict[str, Any]]:
        return await self._hub.get_record_by_pk(SUBJECT_CONNECTOR_ID, risk_id)

    async def distinct_values(self, field: str, limit: int = 200) -> List[str]:
        return await self._hub.distinct_values(SUBJECT_CONNECTOR_ID, field, limit=limit)
