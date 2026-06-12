"""
分析模板服务层

提供分析模板的 CRUD 管理、参数校验、变量替换、逐步执行引擎及 Jinja2 渲染输出能力。
执行结果自动存入 reports 集合，可在报告中心查看。
"""
import re
import uuid
from datetime import date, datetime
from typing import Any, Optional

from bson import ObjectId
from loguru import logger

from app.agent.tools.base import tool_registry
from app.config.database import Database


def _deep_json_safe(obj: Any) -> Any:
    """将 Mongo 文档转为可 JSON 序列化的结构（嵌套 ObjectId / datetime 等）。"""
    if obj is None:
        return None
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _deep_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    try:
        from bson.decimal128 import Decimal128

        if isinstance(obj, Decimal128):
            return str(obj.to_decimal())
    except Exception:
        pass
    return str(obj)


class TemplateService:
    """分析模板服务 — CRUD + 执行引擎"""

    COLLECTION = "analysis_templates"

    # ---- CRUD ----

    async def create_template(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建分析模板

        Args:
            data: 模板字段字典，包含 name、display_name、steps 等

        Returns:
            包含 template_id 的字典
        """
        db = Database.get_database()
        template_id = str(uuid.uuid4())
        now = datetime.utcnow()
        doc: dict[str, Any] = {
            "template_id": template_id,
            **data,
            "status": data.get("status", "active"),
            "created_at": now,
            "updated_at": now,
            "created_by": data.get("created_by", "default"),
        }
        await db[self.COLLECTION].insert_one(doc)
        logger.info(
            "analysis_template_created",
            extra={"template_id": template_id, "name": data.get("name")},
        )
        return {"template_id": template_id}

    async def update_template(self, template_id: str, data: dict[str, Any]) -> bool:
        """更新分析模板

        Args:
            template_id: 模板唯一 ID
            data: 需更新的字段字典

        Returns:
            是否更新成功
        """
        db = Database.get_database()
        data["updated_at"] = datetime.utcnow()
        result = await db[self.COLLECTION].update_one(
            {"template_id": template_id},
            {"$set": data},
        )
        updated = result.modified_count > 0
        if updated:
            logger.info(
                "analysis_template_updated",
                extra={"template_id": template_id},
            )
        else:
            logger.warning(
                "analysis_template_update_noop",
                extra={"template_id": template_id},
            )
        return updated

    async def delete_template(self, template_id: str) -> bool:
        """删除分析模板

        Args:
            template_id: 模板唯一 ID

        Returns:
            是否删除成功
        """
        db = Database.get_database()
        result = await db[self.COLLECTION].delete_one({"template_id": template_id})
        deleted = result.deleted_count > 0
        if deleted:
            logger.info(
                "analysis_template_deleted",
                extra={"template_id": template_id},
            )
        else:
            logger.warning(
                "analysis_template_delete_not_found",
                extra={"template_id": template_id},
            )
        return deleted

    async def get_template(self, template_id: str) -> Optional[dict[str, Any]]:
        """获取模板详情

        Args:
            template_id: 模板唯一 ID

        Returns:
            模板文档字典，不存在则返回 None
        """
        db = Database.get_database()
        doc = await db[self.COLLECTION].find_one({"template_id": template_id})
        if doc is None:
            logger.warning(
                "analysis_template_not_found",
                extra={"template_id": template_id},
            )
            return None
        return _deep_json_safe(doc)

    async def list_templates(
        self,
        category: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """获取模板列表（分页 + 筛选）

        Args:
            category: 可选分类筛选
            status: 可选状态筛选
            page: 页码，从 1 开始
            page_size: 每页条数

        Returns:
            (模板列表, 总数) 元组
        """
        db = Database.get_database()
        if db is None:
            raise RuntimeError(
                "MongoDB 未初始化：请确认应用已启动且 MONGODB_URL 配置正确"
            )
        query: dict[str, Any] = {}
        if category:
            query["category"] = category
        if status:
            query["status"] = status

        total = await db[self.COLLECTION].count_documents(query)
        cursor = (
            db[self.COLLECTION]
            .find(query)
            .sort("created_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items: list[dict[str, Any]] = []
        async for doc in cursor:
            items.append(_deep_json_safe(doc))

        logger.info(
            "analysis_template_list_fetched",
            extra={
                "category": category,
                "status": status,
                "page": page,
                "page_size": page_size,
                "total": total,
                "returned": len(items),
            },
        )
        return items, total

    # ---- 执行引擎 ----

    async def execute_template(
        self,
        template_id: str,
        user_params: dict[str, Any],
    ) -> dict[str, Any]:
        """执行分析模板

        流程: 加载模板 → 校验参数 → 替换变量 → 逐步调用工具 → Jinja2 渲染输出 → 存入报告

        Args:
            template_id: 模板唯一 ID
            user_params: 用户传入的参数字典

        Returns:
            包含 template_id、report_id、rendered_content、step_results 的字典

        Raises:
            ValueError: 模板不存在或参数校验失败
        """
        # 1. 加载模板
        template = await self.get_template(template_id)
        if not template:
            raise ValueError(f"模板不存在: {template_id}")

        # 2. 校验参数
        self._validate_params(template.get("parameters", []), user_params)

        # 3. 填充默认值
        resolved_params = self._fill_defaults(template.get("parameters", []), user_params)

        # 4. 逐步执行
        steps = template.get("steps", [])
        step_results: list[dict[str, Any]] = []

        for i, step in enumerate(steps):
            step_name = step.get("name", f"步骤{i + 1}")
            tool_name = step.get("tool", "")
            raw_params = step.get("tool_params", {})

            # 替换变量占位符
            tool_params = self._resolve_variables(raw_params, resolved_params)

            logger.info(
                "analysis_template_step_start",
                extra={
                    "template_id": template_id,
                    "step": i + 1,
                    "step_name": step_name,
                    "tool": tool_name,
                },
            )

            try:
                tool = tool_registry.get_tool(tool_name)
                if not tool:
                    step_results.append({
                        "name": step_name,
                        "step": i + 1,
                        "success": False,
                        "error": f"工具不存在: {tool_name}",
                        "summary": "",
                    })
                    continue

                # BaseTool.execute(**kwargs) 返回 dict
                result: dict[str, Any] = await tool.execute(**tool_params)

                step_results.append({
                    "name": step_name,
                    "step": i + 1,
                    "success": result.get("success", True),
                    "summary": result.get("summary", ""),
                    "data": result.get("data", {}),
                })
            except TypeError as e:
                logger.error(
                    "analysis_template_step_type_error",
                    extra={
                        "template_id": template_id,
                        "step_name": step_name,
                        "tool": tool_name,
                        "error": str(e),
                    },
                )
                step_results.append({
                    "name": step_name,
                    "step": i + 1,
                    "success": False,
                    "error": str(e),
                    "summary": "",
                })
            except Exception as e:
                logger.error(
                    "analysis_template_step_failed",
                    extra={
                        "template_id": template_id,
                        "step_name": step_name,
                        "tool": tool_name,
                        "error": str(e),
                    },
                )
                step_results.append({
                    "name": step_name,
                    "step": i + 1,
                    "success": False,
                    "error": str(e),
                    "summary": "",
                })

        # 5. 渲染输出模板
        output_tpl = template.get("output_template", "")
        rendered_content = self._render_output(output_tpl, step_results, resolved_params)

        # 6. 存入报告集合
        report_id = await self._save_as_report(template, rendered_content, step_results)

        logger.info(
            "analysis_template_executed",
            extra={
                "template_id": template_id,
                "report_id": report_id,
                "steps_count": len(step_results),
                "steps_success": sum(1 for s in step_results if s.get("success")),
            },
        )

        return {
            "template_id": template_id,
            "report_id": report_id,
            "rendered_content": rendered_content,
            "step_results": [
                {
                    "name": s["name"],
                    "step": s["step"],
                    "success": s["success"],
                    "summary": s.get("summary", ""),
                }
                for s in step_results
            ],
        }

    # ---- 内部方法 ----

    def _validate_params(
        self, parameters: list[dict[str, Any]], user_params: dict[str, Any],
    ) -> None:
        """校验用户参数满足模板要求

        Args:
            parameters: 模板参数定义列表
            user_params: 用户传入的参数字典

        Raises:
            ValueError: 缺少必填参数
        """
        for param in parameters:
            name = param.get("name", "")
            if param.get("required") and name not in user_params:
                if param.get("default") is None:
                    raise ValueError(f"缺少必填参数: {name}")

    def _fill_defaults(
        self, parameters: list[dict[str, Any]], user_params: dict[str, Any],
    ) -> dict[str, Any]:
        """用默认值填充缺失参数

        Args:
            parameters: 模板参数定义列表
            user_params: 用户传入的参数字典

        Returns:
            合并默认值后的参数字典
        """
        resolved = dict(user_params)
        for param in parameters:
            name = param.get("name", "")
            if name not in resolved and param.get("default") is not None:
                resolved[name] = param["default"]
        return resolved

    def _resolve_variables(self, data: Any, variables: dict[str, Any]) -> Any:
        """递归替换 ${var_name} 占位符

        Args:
            data: 待替换的数据（支持 str / dict / list / 其他）
            variables: 变量名 → 值的映射

        Returns:
            替换后的数据
        """
        if isinstance(data, str):
            def replace_var(match: re.Match) -> str:
                var_name = match.group(1)
                return str(variables.get(var_name, match.group(0)))
            return re.sub(r"\$\{(\w+)\}", replace_var, data)
        elif isinstance(data, dict):
            return {k: self._resolve_variables(v, variables) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._resolve_variables(item, variables) for item in data]
        return data

    def _render_output(
        self,
        output_template: str,
        step_results: list[dict[str, Any]],
        params: dict[str, Any],
    ) -> str:
        """用 Jinja2 渲染输出模板

        Args:
            output_template: Jinja2 模板字符串
            step_results: 各步骤执行结果列表
            params: 已解析的参数字典

        Returns:
            渲染后的 Markdown 文本
        """
        if not output_template:
            # 无模板时生成默认摘要
            lines = ["## 分析结果\n"]
            for s in step_results:
                status = "✓" if s.get("success") else "✗"
                lines.append(f"### {status} {s['name']}\n{s.get('summary', '无摘要')}\n")
            return "\n".join(lines)

        import jinja2

        try:
            env = jinja2.Environment(undefined=jinja2.Undefined)
            tpl = env.from_string(output_template)
            context: dict[str, Any] = {
                "step_results": step_results,
                "params": params,
            }
            return tpl.render(**context)
        except jinja2.TemplateError as e:
            logger.warning(
                "analysis_template_render_failed",
                extra={"error": str(e)},
            )
            return f"## 分析结果\n\n模板渲染失败: {e}"

    async def _save_as_report(
        self,
        template: dict[str, Any],
        rendered_content: str,
        step_results: list[dict[str, Any]],
    ) -> str:
        """将执行结果存入 reports 集合

        Args:
            template: 模板文档字典
            rendered_content: 渲染后的内容
            step_results: 各步骤执行结果列表

        Returns:
            生成的 report_id
        """
        db = Database.get_database()
        report_id = str(uuid.uuid4())
        now = datetime.utcnow()
        report_doc: dict[str, Any] = {
            "report_id": report_id,
            "template_id": template.get("template_id"),
            "template_type": "analysis_template",
            "title": f"{template.get('display_name', '分析报告')} - {now.strftime('%Y%m%d_%H%M')}",
            "status": "approved",
            "sections": [],
            "data_context": {
                "step_results_summary": [
                    {
                        "name": s["name"],
                        "success": s["success"],
                        "summary": s.get("summary", ""),
                    }
                    for s in step_results
                ],
            },
            "rendered_content": rendered_content,
            "created_at": now,
            "updated_at": now,
            "created_by": template.get("created_by", "system"),
        }
        await db.reports.insert_one(report_doc)
        logger.info(
            "analysis_template_report_saved",
            extra={"report_id": report_id},
        )
        return report_id
