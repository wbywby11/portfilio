"""
数据运维域工具 — query_import_logs / query_data_connectors（读）+ trigger_data_sync（写，需确认）

- query_import_logs(action=list/detail)：导入历史与失败溯源（COL_IMPORT_AUDIT_LOG）
- query_data_connectors(action=list/status)：API 接数管理（连接器清单 + 最近同步状态）
- trigger_data_sync：按连接器触发上游拉取（两阶段确认，纯新建批次天然合规）

复用链路：ImportAuditService + DataHubService（连接器注册表驱动）。
价格文件类导入仍由用户在页面上传，agent 不代做。
"""
from bson import ObjectId
from loguru import logger

from app.agent.tools._helpers import bson_safe, fmt_datetime
from app.agent.tools.base import BaseTool, ConfirmableTool


class QueryImportLogsTool(BaseTool):
    """导入审计查询工具"""

    name = "query_import_logs"
    description = (
        "查询数据导入历史（审计日志），用于溯源'数据是什么时候、由谁、以什么方式导入的'。"
        "两种模式：\n"
        "1) action=list：最近导入记录（可按 target_collection 过滤），含导入方式/操作人/统计/失败摘要\n"
        "2) action=detail：单条导入日志完整详情（传 log_id）"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "detail"],
                "description": "查询模式",
            },
            "target_collection": {
                "type": "string",
                "description": "list 模式按目标集合过滤（可选，如 asset_prices）",
            },
            "log_id": {
                "type": "string",
                "description": "detail 模式的日志 ID（必填）",
            },
            "limit": {
                "type": "integer",
                "description": "list 模式返回条数上限（默认 20，最大 50）",
            },
        },
        "required": ["action"],
    }

    max_result_chars = 8000

    async def execute(
        self,
        action: str = "list",
        target_collection: str = "",
        log_id: str = "",
        limit: int = 20,
        **kwargs,
    ) -> dict:
        from app.services.import_audit_service import ImportAuditService

        service = ImportAuditService()
        if action == "list":
            return await self._list(service, target_collection, limit)
        if action == "detail":
            if not log_id:
                return {"success": False, "error": "detail 模式需要 log_id"}
            return await self._detail(service, log_id)
        return {"success": False, "error": f"未知 action: {action}（可选 list/detail）"}

    async def _list(self, service, target_collection: str, limit: int) -> dict:
        limit = max(1, min(int(limit or 20), 50))
        logs = await service.get_recent_logs(
            target_collection=target_collection or None, limit=limit,
        )

        records = []
        for log in logs:
            stats = log.get("stats") or {}
            records.append({
                "id": log.get("_id", ""),
                "target_collection": log.get("target_collection", ""),
                "source_type": log.get("source_type", ""),
                "import_mode": log.get("import_mode", ""),
                "operator": log.get("operator", ""),
                "source_filename": log.get("source_filename", ""),
                "date_range": log.get("date_range", ""),
                "inserted": stats.get("inserted"),
                "updated": stats.get("updated"),
                "failed": stats.get("failed"),
                "has_errors": bool(log.get("error_summary")),
                "created_at": fmt_datetime(log.get("created_at")),
            })

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "metadata": {"record_count": len(records)},
            "summary": f"共 {len(records)} 条导入记录。" if records else "暂无导入记录。",
            "hint": "has_errors=true 的记录可用 action=detail 查看失败原因",
        }

    async def _detail(self, service, log_id: str) -> dict:
        try:
            doc = await service.collection.find_one({"_id": ObjectId(log_id)})
        except Exception:
            return {"success": False, "error": f"无效的 log_id: {log_id}"}
        if not doc:
            return {"success": False, "error": f"未找到导入日志: {log_id}"}
        doc["_id"] = str(doc["_id"])
        return {
            "success": True,
            "log": bson_safe(doc),
        }


class QueryDataConnectorsTool(BaseTool):
    """API 数据连接器查询工具（API 接数管理）"""

    name = "query_data_connectors"
    description = (
        "查询 API 数据接入（DataHub）连接器信息。两种模式：\n"
        "1) action=list：已注册连接器清单（数据源名称/说明/目标集合/主键）\n"
        "2) action=status：指定连接器的最近同步批次状态（传 connector_id），"
        "含成功条数/失败原因，用于判断某数据源是否正常更新"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "status"],
                "description": "查询模式",
            },
            "connector_id": {
                "type": "string",
                "description": "status 模式的连接器 ID（必填，来自 action=list）",
            },
        },
        "required": ["action"],
    }

    max_result_chars = 8000

    async def execute(
        self,
        action: str = "list",
        connector_id: str = "",
        **kwargs,
    ) -> dict:
        if action == "list":
            return await self._list()
        if action == "status":
            if not connector_id:
                return {"success": False, "error": "status 模式需要 connector_id"}
            return await self._status(connector_id)
        return {"success": False, "error": f"未知 action: {action}（可选 list/status）"}

    async def _list(self) -> dict:
        from app.models.data_connector import list_connectors_public

        connectors = list_connectors_public()
        records = [{
            "connector_id": c.get("connector_id", ""),
            "title": c.get("title", ""),
            "description": c.get("description", ""),
            "import_param_style": c.get("import_param_style", ""),
        } for c in connectors]

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "metadata": {"record_count": len(records)},
            "summary": f"共 {len(records)} 个 API 数据连接器。" if records else "暂无已注册连接器。",
            "hint": "使用 action=status 并传 connector_id 可查看最近同步状态",
        }

    async def _status(self, connector_id: str) -> dict:
        from app.models.data_connector import get_connector
        from app.services.data_hub_service import DataHubService

        conn = get_connector(connector_id)
        if not conn:
            return {"success": False, "error": f"未知连接器: {connector_id}，请先用 action=list 查看"}

        try:
            batches_result = await DataHubService().list_batches(connector_id, page=1, page_size=5)
        except Exception as e:
            logger.warning("connector_status_failed", extra={"connector_id": connector_id, "error": str(e)})
            return {"success": False, "error": f"查询批次失败: {e}"}

        batches = bson_safe(batches_result.get("items", []))
        latest = batches[0] if batches else None

        return {
            "success": True,
            "connector": {
                "connector_id": conn.connector_id,
                "title": conn.title,
                "records_collection": conn.records_collection,
                "primary_key": conn.primary_key,
            },
            "latest_batch": latest,
            "recent_batches": batches,
            "count": len(batches),
            "summary": (
                f"连接器「{conn.title}」最近一次同步：{latest.get('started_at', '无记录')}"
                if latest else f"连接器「{conn.title}」尚无同步记录。"
            ),
        }


class TriggerDataSyncTool(ConfirmableTool):
    """触发数据连接器同步（两阶段确认：确认后拉取上游数据入库）"""

    name = "trigger_data_sync"
    description = (
        "触发 API 数据连接器从上游拉取数据入库（写操作，需用户确认后执行）。"
        "按日期区间拉取，执行后生成导入批次，可用 query_data_connectors(action=status) "
        "查看结果。仅支持已注册的 API 连接器；价格/汇率等文件类数据请用户在页面上传，"
        "agent 不代做。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "connector_id": {
                "type": "string",
                "description": "连接器 ID（来自 query_data_connectors 的 action=list）",
            },
            "start_date": {
                "type": "string",
                "description": "拉取起始日期 YYYY-MM-DD",
            },
            "end_date": {
                "type": "string",
                "description": "拉取结束日期 YYYY-MM-DD",
            },
            "rownum": {
                "type": "integer",
                "description": "单次拉取最大行数（可选，默认 100000）",
            },
        },
        "required": ["connector_id", "start_date", "end_date"],
    }

    tool_timeout = 600.0

    async def execute(self, **kwargs) -> dict:
        error = self._precheck(kwargs)
        if error:
            return {"success": False, "error": error}
        return await super().execute(**kwargs)

    def build_preview(self, arguments: dict) -> dict:
        from app.models.data_connector import get_connector

        conn = get_connector(arguments.get("connector_id", ""))
        return {
            "tool": self.name,
            "operation": "触发数据同步",
            "target": conn.title if conn else arguments.get("connector_id", ""),
            "target_collection": conn.records_collection if conn else "",
            "arguments": arguments,
        }

    async def perform(self, **kwargs) -> dict:
        from app.models.data_connector import get_connector
        from app.models.subject_risk import SubjectRiskImportRequest
        from app.services.data_hub_service import DataHubService

        connector_id = kwargs.get("connector_id", "")
        error = self._precheck(kwargs)
        if error:
            return {"success": False, "error": error}

        conn = get_connector(connector_id)
        body = SubjectRiskImportRequest(
            startDate=kwargs["start_date"],
            endDate=kwargs["end_date"],
            rownum=int(kwargs.get("rownum") or 100000),
        ).model_dump(mode="json")

        result = await DataHubService().import_from_upstream(connector_id, body)
        status = result.get("status", "unknown")
        if status in ("failed_network", "failed_upstream", "failed_unknown"):
            return {
                "success": False,
                "status": status,
                "error": result.get("error") or result.get("upstream_message") or "同步失败",
                "batch_id": result.get("batch_id", ""),
            }

        return {
            "success": True,
            "status": status,
            "batch_id": result.get("batch_id", ""),
            "connector": conn.title,
            "target_collection": conn.records_collection,
            "stats": {
                "total_returned": result.get("total_returned", 0),
                "inserted": result.get("inserted", 0),
                "updated": result.get("updated", 0),
                "failed": result.get("failed", 0),
            },
            "summary": (
                f"同步完成（{status}）：返回 {result.get('total_returned', 0)} 条，"
                f"新增 {result.get('inserted', 0)}，更新 {result.get('updated', 0)}，"
                f"失败 {result.get('failed', 0)}。"
            ),
        }

    @staticmethod
    def _precheck(kwargs: dict) -> str:
        """返回错误文案（空串=通过）"""
        from app.models.data_connector import get_connector

        connector_id = kwargs.get("connector_id", "")
        if not connector_id:
            return "缺少 connector_id"
        conn = get_connector(connector_id)
        if not conn:
            return f"未知连接器: {connector_id}，请先用 query_data_connectors(action=list) 查看"
        if conn.family != "get_py_result":
            return f"连接器「{conn.title}」类型（{conn.family}）暂不支持对话内同步"
        for key in ("start_date", "end_date"):
            value = kwargs.get(key, "")
            if len(value) != 10 or value[4] != "-" or value[7] != "-":
                return f"{key} 格式无效，应为 YYYY-MM-DD"
        return ""
