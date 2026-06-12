"""
分析模板管理工具 — 原子能力层

提供 DataTemplateTool (data_template)：
分析模板的查询、保存、执行
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.services.template_service import TemplateService

_template_service = TemplateService()


class DataTemplateTool(BaseTool):
    """分析模板管理工具"""

    name = "data_template"
    description = (
        "分析模板管理。支持："
        "list(查看已保存的分析模板), "
        "save(将分析流程保存为可复用模板), "
        "execute(执行已保存的模板,可覆盖参数如日期范围), "
        "save_from_context(从当前对话的数据上下文中自动提取工具调用历史，保存为可复用的数据加工模板)"
    )
    category = "data"
    tags = ["模板", "复用", "保存", "自动化"]

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "save", "execute", "save_from_context"],
                "description": (
                    "操作类型: list-查看模板, save-保存模板, execute-执行模板, "
                    "save_from_context-从当前对话的数据上下文中自动提取工具调用历史，保存为可复用的数据加工模板"
                ),
            },
            "template_id": {
                "type": "string",
                "description": "模板ID（execute时必填）",
            },
            "user_params": {
                "type": "object",
                "description": "执行时覆盖的参数",
            },
            "template_data": {
                "type": "object",
                "description": "模板定义(save时): {name, description, steps}",
            },
            "name": {
                "type": "string",
                "description": "模板名称，用于 save_from_context action",
            },
            "description": {
                "type": "string",
                "description": "模板描述，用于 save_from_context action",
            },
            "conversation_id": {
                "type": "string",
                "description": "会话ID，save_from_context 时必填",
            },
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> dict:
        action: str = kwargs.get("action", "")
        handler = {
            "list": self._list,
            "save": self._save,
            "execute": self._execute,
            "save_from_context": self._handle_save_from_context,
        }.get(action)

        if handler is None:
            return ToolResult.error(f"不支持的操作: {action}")

        try:
            result = await handler(**kwargs)
        except ValueError as e:
            logger.error("[DataTemplate] 参数错误: {}", e)
            return ToolResult.error(f"参数错误: {e}")
        except Exception as e:
            logger.error("[DataTemplate] 执行失败: {}", e)
            return ToolResult.error(f"模板操作失败: {e}")

        # 模板工具不直接访问业务表，仅访问模板存储集合
        if not (isinstance(result, dict) and result.get("success")):
            return result
        if "_lineage_meta" in result:
            return result
        return self.attach_lineage(
            result,
            tables=["model_templates"],
            domains=["meta"],
            fields={"model_templates": ["template_id", "name", "category", "steps"]},
            records_returned=result.get("metadata", {}).get("record_count", 0),
            query_operation=f"data_template:{action}",
        )

    async def _list(self, **kwargs: Any) -> dict:
        user_params: dict = kwargs.get("user_params", {}) or {}
        category = user_params.get("category", "data_analysis")
        page = int(user_params.get("page", 1))
        page_size = int(user_params.get("page_size", 20))

        templates, total = await _template_service.list_templates(
            category=category, page=page, page_size=page_size,
        )

        items = [
            {
                "template_id": t.get("template_id"),
                "name": t.get("name"),
                "display_name": t.get("display_name", t.get("name")),
                "description": t.get("description", ""),
                "status": t.get("status"),
                "created_at": t.get("created_at"),
            }
            for t in templates
        ]

        return ToolResult.success(
            data={"templates": items, "total": total, "page": page},
            summary=f"共 {total} 个模板，当前第 {page} 页返回 {len(items)} 个",
            data_shape="records",
            record_count=len(items),
        )

    async def _save(self, **kwargs: Any) -> dict:
        template_data: dict | None = kwargs.get("template_data")
        if not template_data:
            return ToolResult.error("save 需要 template_data 参数")

        name = template_data.get("name", "")
        if not name:
            return ToolResult.error("模板 name 不能为空")

        doc = {
            "name": name,
            "display_name": template_data.get("display_name", name),
            "description": template_data.get("description", ""),
            "category": template_data.get("category", "data_analysis"),
            "steps": template_data.get("steps", []),
            "parameters": template_data.get("parameters", []),
            "output_template": template_data.get("output_template", ""),
        }

        result = await _template_service.create_template(doc)
        template_id = result.get("template_id", "")

        return ToolResult.success(
            data={"template_id": template_id},
            summary=f"模板 '{name}' 已保存，ID: {template_id}",
            data_shape="single",
            record_count=1,
        )

    async def _handle_save_from_context(self, **kwargs: Any) -> dict:
        """从 DataContext 自动提取工具调用历史，保存为模板"""
        conversation_id: str | None = kwargs.get("conversation_id")
        if not conversation_id:
            return ToolResult.error("save_from_context 需要会话上下文")

        # 延迟导入避免循环依赖
        from app.agent.services.data_context import DataContext

        ctx = DataContext.get_instance(conversation_id)
        tool_history: list[dict] = ctx.get_tool_history()

        if not tool_history:
            return ToolResult.error("当前对话没有数据加工历史，无法保存模板")

        name: str = kwargs.get("name", "未命名工作流")
        description: str = kwargs.get("description", "")

        # 将工具调用历史转换为模板步骤格式
        steps: list[dict] = []
        for h in tool_history:
            step: dict = {
                "tool": h["tool_name"],
                "tool_params": h["params"],
            }
            steps.append(step)

        doc: dict = {
            "name": name,
            "display_name": name,
            "description": description or f"从对话自动录制的数据加工流程（{len(steps)} 步）",
            "category": "data_analysis",
            "steps": steps,
            "parameters": [],
            "output_template": "",
        }

        result: dict = await _template_service.create_template(doc)
        template_id: str = result.get("template_id", "")

        logger.info("template_saved_from_context", extra={
            "conversation_id": conversation_id,
            "template_id": template_id,
            "name": name,
            "step_count": len(steps),
        })

        return ToolResult.success(
            data={
                "template_id": template_id,
                "template_name": name,
                "step_count": len(steps),
                "steps_summary": [
                    {"step": i + 1, "tool": s["tool"]}
                    for i, s in enumerate(steps)
                ],
            },
            summary=f"已保存数据加工模板「{name}」，包含 {len(steps)} 个步骤",
            data_shape="single",
            record_count=1,
        )

    async def _execute(self, **kwargs: Any) -> dict:
        template_id: str = kwargs.get("template_id", "")
        if not template_id:
            return ToolResult.error("execute 需要 template_id 参数")

        user_params: dict = kwargs.get("user_params", {}) or {}

        result = await _template_service.execute_template(
            template_id=template_id, user_params=user_params,
        )

        return ToolResult.success(
            data={
                "template_id": result.get("template_id"),
                "report_id": result.get("report_id"),
                "rendered_content": result.get("rendered_content", ""),
                "step_results": result.get("step_results", []),
            },
            summary=(
                f"模板执行完成，报告ID: {result.get('report_id')}, "
                f"共 {len(result.get('step_results', []))} 步"
            ),
            data_shape="report",
            record_count=len(result.get("step_results", [])),
        )
