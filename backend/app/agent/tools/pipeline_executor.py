"""工具组合 Pipeline 执行器

自动执行目标工具的前置依赖链，将前置工具的输出注入到目标工具的参数中。
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PipelineExecutor:
    """执行工具的 pipeline 前置调用链

    当目标工具声明了 pipeline（前置依赖工具列表），PipelineExecutor 在执行
    目标工具前自动运行前置工具并将结果注入到目标工具的参数中。

    pipeline 格式: [{"tool": "tool_name", "extract": "field_name"}]
    - tool: 前置工具名称
    - extract: 从前置工具输出中提取的字段名，提取值将以该字段名注入目标参数
    """

    def __init__(self, tool_registry):
        """
        Args:
            tool_registry: ToolRegistry 实例，用于按名称查找工具
        """
        self.registry = tool_registry

    async def execute_pipeline(
        self,
        target_tool_name: str,
        original_args: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行目标工具的前置调用链，返回增强后的参数

        流程:
        1. 根据 target_tool_name 从 registry 查找工具定义
        2. 检查该工具的 pipeline 字段
        3. 如果 pipeline 为空或 None，直接返回 original_args
        4. 遍历 pipeline 中的每个步骤:
           a. 检查 extract 指定的字段是否已在 original_args 中存在且非空 → 跳过
           b. 从 registry 查找前置工具
           c. 构建前置工具的输入参数（从 original_args 和 context 中提取）
           d. 执行前置工具
           e. 解析前置工具的输出，提取 extract 字段
           f. 将提取的值合并到结果参数中
        5. 返回增强后的参数字典

        Args:
            target_tool_name: 目标工具名称
            original_args: 原始调用参数
            context: 可选的额外上下文（如 conversation_id 等）

        Returns:
            增强后的参数字典（原始参数 + pipeline 注入的参数）
        """
        target_tool = self.registry.get_tool(target_tool_name)
        if not target_tool:
            logger.warning("[Pipeline] 未找到目标工具: %s，跳过 pipeline", target_tool_name)
            return dict(original_args)

        pipeline = getattr(target_tool, "pipeline", None)
        if not pipeline:
            return dict(original_args)

        # 复制原始参数，避免修改原始字典
        enhanced_args = dict(original_args)

        # 循环检测：收集本次 pipeline 已执行的工具名
        visited: set[str] = {target_tool_name}

        for step in pipeline:
            dep_tool_name = step.get("tool")
            extract_field = step.get("extract")

            if not dep_tool_name or not extract_field:
                logger.warning(
                    "[Pipeline] 无效的 pipeline 步骤配置: %s，跳过", step
                )
                continue

            # 循环检测
            if dep_tool_name in visited:
                logger.warning(
                    "[Pipeline] 检测到循环依赖: %s 已在执行链中，跳过",
                    dep_tool_name,
                )
                continue
            visited.add(dep_tool_name)

            # 幂等性：如果目标字段已有非空值，跳过
            existing_value = enhanced_args.get(extract_field)
            if existing_value is not None and existing_value != "" and existing_value != []:
                logger.debug(
                    "[Pipeline] 字段 '%s' 已存在值，跳过前置工具 %s",
                    extract_field,
                    dep_tool_name,
                )
                continue

            # 查找前置工具
            dep_tool = self.registry.get_tool(dep_tool_name)
            if not dep_tool:
                logger.warning(
                    "[Pipeline] 前置工具 '%s' 未注册，跳过", dep_tool_name
                )
                continue

            # 构建前置工具的输入参数：合并 original_args 和 context
            dep_args: dict[str, Any] = {}
            dep_args.update(enhanced_args)
            if context:
                dep_args.update(context)

            # 执行前置工具（失败不阻断）
            try:
                logger.info(
                    "[Pipeline] 执行前置工具: %s → 提取字段: %s",
                    dep_tool_name,
                    extract_field,
                )
                dep_result = await dep_tool.execute(**dep_args)

                # 解析输出并提取字段
                extracted = self._extract_field(dep_result, extract_field)
                if extracted is not None:
                    enhanced_args[extract_field] = extracted
                    logger.info(
                        "[Pipeline] 成功从 %s 提取字段 '%s'",
                        dep_tool_name,
                        extract_field,
                    )
                else:
                    logger.warning(
                        "[Pipeline] 前置工具 %s 的输出中未找到字段 '%s'",
                        dep_tool_name,
                        extract_field,
                    )

            except Exception as e:
                logger.warning(
                    "[Pipeline] 前置工具 %s 执行失败: %s，跳过该步骤",
                    dep_tool_name,
                    str(e),
                )
                continue

        return enhanced_args

    @staticmethod
    def _extract_field(result: Any, field_name: str) -> Any:
        """从工具执行结果中提取指定字段

        支持以下结果格式:
        1. dict → 直接取 result[field_name] 或 result["data"][field_name]
        2. str (JSON) → json.loads 后按 dict 处理
        3. 其他 → 返回 None

        Args:
            result: 工具执行返回值
            field_name: 要提取的字段名

        Returns:
            提取到的值，未找到返回 None
        """
        # 如果是字符串，尝试 JSON 解析
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return None

        if not isinstance(result, dict):
            return None

        # 优先从顶层提取
        if field_name in result:
            return result[field_name]

        # 其次从 data 子字典提取（ToolResult.success 格式）
        data = result.get("data")
        if isinstance(data, dict) and field_name in data:
            return data[field_name]

        return None
