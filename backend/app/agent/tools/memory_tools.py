"""
记忆类工具 — 包装 MemoryManager 为 Agent 可调用的 BaseTool

提供 2 个记忆相关工具：
- save_memory     保存研究记忆（结论、偏好、别名、洞察）
- recall_memories 按语义检索相关记忆
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.agent.memory.memory_manager import MemoryManager
from app.agent.tools.base import BaseTool, ToolResult

# 分类枚举值（与 MemoryManager.CATEGORIES 保持一致）
_VALID_CATEGORIES: list[str] = [
    "research_conclusion",
    "user_preference",
    "asset_alias",
    "strategy_insight",
]

# 分类中文映射
_CATEGORY_LABELS: dict[str, str] = {
    "research_conclusion": "研究结论",
    "user_preference": "用户偏好",
    "asset_alias": "资产别名",
    "strategy_insight": "策略洞察",
}


class SaveMemoryTool(BaseTool):
    """保存研究记忆到长期存储"""

    name = "save_memory"
    description = (
        "保存一条研究记忆（研究结论、用户偏好、资产别名、策略洞察），"
        "供后续对话检索使用。每轮对话最多保存 3 条。"
    )
    category = "memory"
    tags = ["记忆", "保存", "知识"]
    parameters = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": _VALID_CATEGORIES,
                "description": (
                    "记忆分类: research_conclusion(研究结论), "
                    "user_preference(用户偏好), asset_alias(资产别名), "
                    "strategy_insight(策略洞察)"
                ),
            },
            "title": {
                "type": "string",
                "maxLength": 100,
                "description": "记忆标题，≤100字符",
            },
            "content": {
                "type": "string",
                "maxLength": 1000,
                "description": "记忆内容，≤1000字符",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 10,
                "description": "关键词列表，可选，≤10个",
            },
        },
        "required": ["category", "title", "content"],
    }

    def __init__(self) -> None:
        # 延迟初始化：MemoryManager 在首次 execute 时创建
        self._memory_manager: MemoryManager | None = None

    def _get_manager(self) -> MemoryManager:
        """延迟获取 MemoryManager 实例"""
        if self._memory_manager is None:
            self._memory_manager = MemoryManager()
        return self._memory_manager

    async def execute(self, **kwargs: Any) -> dict:
        """执行记忆保存"""
        # 参数提取
        cat: str = kwargs.get("category", "")
        title: str = kwargs.get("title", "")
        content: str = kwargs.get("content", "")
        keywords: list[str] = kwargs.get("keywords", [])

        # 从 tool_context 提取上下文信息
        tool_context: dict = kwargs.get("tool_context", {})
        user_id: str = tool_context.get("user_id", "default")
        conversation_id: str = tool_context.get("conversation_id", "")

        # 参数校验
        if not cat or cat not in _VALID_CATEGORIES:
            return ToolResult.error(
                f"无效分类 '{cat}'，可选: {_VALID_CATEGORIES}"
            )
        if not title or len(title) > 100:
            return ToolResult.error("标题不能为空且不超过100字符")
        if not content or len(content) > 1000:
            return ToolResult.error("内容不能为空且不超过1000字符")
        if keywords and len(keywords) > 10:
            return ToolResult.error("关键词不能超过10个")

        # 调用 MemoryManager
        manager = self._get_manager()
        try:
            result = await manager.save_memory(
                user_id=user_id,
                category=cat,
                title=title,
                content=content,
                keywords=keywords or None,
                conversation_id=conversation_id,
            )
        except Exception as e:
            logger.error(
                "save_memory_failed",
                extra={"user_id": user_id, "category": cat, "error": str(e)},
            )
            return ToolResult.error(f"记忆保存失败: {e}")

        if not result.get("success"):
            return ToolResult.error(result.get("error", "记忆保存失败"))

        cat_label = _CATEGORY_LABELS.get(cat, cat)
        memory_id = result.get("memory_id", "")

        logger.info(
            "save_memory_success",
            extra={
                "user_id": user_id,
                "memory_id": memory_id,
                "category": cat,
                "title": title,
            },
        )

        return {
            "success": True,
            "memory_id": str(memory_id),
            "summary": f"已保存 [{cat_label}] '{title}'",
        }


class RecallMemoriesTool(BaseTool):
    """按语义检索相关研究记忆"""

    name = "recall_memories"
    description = (
        "根据查询语句检索相关的研究记忆，支持按分类过滤。"
        "用于在对话中回忆之前保存的研究结论、用户偏好、资产别名或策略洞察。"
    )
    category = "memory"
    tags = ["记忆", "检索", "召回"]
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索查询语句，描述需要回忆的内容",
            },
            "category": {
                "type": "string",
                "enum": _VALID_CATEGORIES,
                "description": (
                    "按分类过滤（可选）: research_conclusion, "
                    "user_preference, asset_alias, strategy_insight"
                ),
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 5,
                "description": "返回结果数量，默认5，范围1-10",
            },
        },
        "required": ["query"],
    }

    def __init__(self) -> None:
        self._memory_manager: MemoryManager | None = None

    def _get_manager(self) -> MemoryManager:
        """延迟获取 MemoryManager 实例"""
        if self._memory_manager is None:
            self._memory_manager = MemoryManager()
        return self._memory_manager

    async def execute(self, **kwargs: Any) -> dict:
        """执行记忆检索"""
        query: str = kwargs.get("query", "")
        cat: str | None = kwargs.get("category")
        limit: int = kwargs.get("limit", 5)

        # 从 tool_context 提取上下文信息
        tool_context: dict = kwargs.get("tool_context", {})
        user_id: str = tool_context.get("user_id", "default")

        # 参数校验
        if not query:
            return ToolResult.error("查询语句不能为空")
        if cat and cat not in _VALID_CATEGORIES:
            return ToolResult.error(
                f"无效分类 '{cat}'，可选: {_VALID_CATEGORIES}"
            )
        limit = max(1, min(10, limit))

        # 调用 MemoryManager
        manager = self._get_manager()
        try:
            memories = await manager.recall_memories(
                user_id=user_id,
                query=query,
                category=cat,
                limit=limit,
            )
        except Exception as e:
            logger.error(
                "recall_memories_failed",
                extra={"user_id": user_id, "query": query, "error": str(e)},
            )
            return ToolResult.error(f"记忆检索失败: {e}")

        count = len(memories)

        # 构建摘要
        if count == 0:
            summary = f"未找到与 '{query}' 相关的记忆"
        else:
            cat_info = f"[{_CATEGORY_LABELS.get(cat, cat)}] " if cat else ""
            summary = f"找到 {count} 条{cat_info}相关记忆"

        logger.info(
            "recall_memories_success",
            extra={
                "user_id": user_id,
                "query": query,
                "category": cat,
                "count": count,
            },
        )

        return {
            "success": True,
            "memories": memories,
            "count": count,
            "summary": summary,
        }
