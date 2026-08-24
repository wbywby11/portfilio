"""
报告域工具 — save_report（写，免确认）+ query_reports（读）

- save_report：将多轮分析整理为 Markdown 报告存入 COL_REPORTS（created_by=agent）。
  只新建 agent 自有文档、不触碰业务实体，免确认卡片。
  图表以 ```echarts 围栏块嵌入（合法 ECharts option JSON，前端渲染），
  数据必须来自本轮工具查询结果。
- query_reports(action=list/detail)：查历史报告。
"""
from datetime import datetime, timezone

from bson import ObjectId

from app.agent.core.write_guard import stamp_agent_origin
from app.agent.tools._helpers import bson_safe, fmt_datetime
from app.agent.tools.base import BaseTool


def _reports_collection():
    from app.config.database import Database
    from app.config.collections import COL_REPORTS

    return Database.get_database()[COL_REPORTS]


class SaveReportTool(BaseTool):
    """保存研究报告（免确认：仅新建 agent 自有文档）"""

    name = "save_report"
    description = (
        "将分析结论整理为 Markdown 研究报告并保存（新建 agent 自有文档，免确认）。"
        "图表用 ```echarts 围栏代码块嵌入（限 line/bar/pie，块内为合法 ECharts option JSON，"
        "数据必须来自本轮工具查询结果）。保存后可用 query_reports 查询。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "报告标题",
            },
            "markdown": {
                "type": "string",
                "description": "报告正文（Markdown，可含 ```echarts 图表围栏块）",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标签列表（可选，便于检索）",
            },
        },
        "required": ["title", "markdown"],
    }

    max_result_chars = 2000

    async def execute(
        self,
        title: str = "",
        markdown: str = "",
        tags: list | None = None,
        **kwargs,
    ) -> dict:
        title = (title or "").strip()
        markdown = (markdown or "").strip()
        if not title:
            return {"success": False, "error": "缺少报告标题"}
        if not markdown:
            return {"success": False, "error": "报告正文不能为空"}

        conversation_id = kwargs.get("conversation_id", "")
        now = datetime.now(timezone.utc)
        doc = {
            "title": title,
            "markdown": markdown,
            "tags": [str(t).strip() for t in (tags or []) if str(t).strip()],
            "created_at": now,
            "updated_at": now,
        }
        stamp_agent_origin(doc, conversation_id=conversation_id, tool_name=self.name)

        result = await _reports_collection().insert_one(doc)
        report_id = str(result.inserted_id)
        return {
            "success": True,
            "report_id": report_id,
            "title": title,
            "summary": f"报告「{title}」已保存（{len(markdown)} 字符）。",
        }


class QueryReportsTool(BaseTool):
    """报告查询工具"""

    name = "query_reports"
    description = (
        "查询已保存的研究报告。两种模式：\n"
        "1) action=list：最近报告列表（可按标签过滤），含标题/标签/创建时间\n"
        "2) action=detail：单篇报告全文（传 report_id，Markdown 含 echarts 图表块）"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "detail"],
                "description": "查询模式",
            },
            "tag": {
                "type": "string",
                "description": "list 模式按标签过滤（可选）",
            },
            "report_id": {
                "type": "string",
                "description": "detail 模式的报告 ID（必填）",
            },
            "limit": {
                "type": "integer",
                "description": "list 模式返回条数上限（默认 20，最大 50）",
            },
        },
        "required": ["action"],
    }

    max_result_chars = 10000

    async def execute(
        self,
        action: str = "list",
        tag: str = "",
        report_id: str = "",
        limit: int = 20,
        **kwargs,
    ) -> dict:
        if action == "list":
            return await self._list(tag, limit)
        if action == "detail":
            if not report_id:
                return {"success": False, "error": "detail 模式需要 report_id"}
            return await self._detail(report_id)
        return {"success": False, "error": f"未知 action: {action}（可选 list/detail）"}

    async def _list(self, tag: str, limit: int) -> dict:
        limit = max(1, min(int(limit or 20), 50))
        query = {"tags": tag} if tag else {}
        cursor = (
            _reports_collection()
            .find(query, {"markdown": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        records = []
        async for doc in cursor:
            records.append({
                "id": str(doc["_id"]),
                "title": doc.get("title", ""),
                "tags": doc.get("tags") or [],
                "created_by": doc.get("created_by") or "user",
                "created_at": fmt_datetime(doc.get("created_at")),
            })

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "metadata": {"record_count": len(records)},
            "summary": f"共 {len(records)} 篇报告。" if records else "暂无报告。",
            "hint": "使用 action=detail 并传 report_id 可查看报告全文",
        }

    async def _detail(self, report_id: str) -> dict:
        try:
            doc = await _reports_collection().find_one({"_id": ObjectId(report_id)})
        except Exception:
            return {"success": False, "error": f"无效的 report_id: {report_id}"}
        if not doc:
            return {"success": False, "error": f"未找到报告: {report_id}"}
        doc["_id"] = str(doc["_id"])
        return {
            "success": True,
            "report": bson_safe(doc),
            "summary": f"报告「{doc.get('title', '')}」全文已返回。",
        }
