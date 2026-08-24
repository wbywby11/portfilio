"""
记忆管理工具 — Agent 主动沉淀研究结论和用户偏好

Memory-as-Tool 设计：
- Agent 通过工具调用主动管理记忆（add / replace / remove）
- 每轮对话最多写入 3 条（由 MemoryManager 控制）
- 对话开始时注入冻结快照，对话中新增的记忆通过此工具写入
"""
from loguru import logger

from app.agent.memory import MemoryManager
from app.agent.tools.base import BaseTool

# 模块级单例（与 chat_service 共享同一实例逻辑）
_memory_manager: MemoryManager | None = None


def _get_memory_manager() -> MemoryManager:
    """延迟获取 MemoryManager 单例"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


class MemoryTool(BaseTool):
    """记忆管理工具 — Agent 主动沉淀研究知识"""

    name = "manage_memory"
    description = (
        "管理研究记忆，用于沉淀重要的研究结论、用户偏好和策略洞察。支持操作：\n"
        "- add: 新增记忆（需要 category + title + content）\n"
        "- replace: 替换已有记忆内容（需要 memory_id + content）\n"
        "- remove: 删除过时记忆（需要 memory_id）\n"
        "每轮对话最多写入 3 条。仅在确实有值得长期保留的信息时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove"],
                "description": "操作类型",
            },
            "category": {
                "type": "string",
                "enum": [
                    "research_conclusion",
                    "user_preference",
                    "asset_alias",
                    "strategy_insight",
                ],
                "description": "记忆分类（add 时必填）：research_conclusion=研究结论, user_preference=用户偏好, asset_alias=资产别名, strategy_insight=策略洞察",
            },
            "title": {
                "type": "string",
                "description": "记忆标题（add 时必填，简短概括）",
            },
            "content": {
                "type": "string",
                "description": "记忆内容（add/replace 时必填）",
            },
            "memory_id": {
                "type": "string",
                "description": "记忆 ID（replace/remove 时必填，从记忆快照中获取）",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "关键词列表（add 时可选，用于后续检索）",
            },
        },
        "required": ["action"],
    }

    # 记忆操作结果很短，无需预算管控
    max_result_chars = 2000
    budget_threshold = 0

    async def execute(self, action: str, **kwargs) -> dict:
        """委托 MemoryManager 执行记忆操作"""
        user_id = kwargs.get("user_id", "default")
        conversation_id = kwargs.get("conversation_id", "")

        manager = _get_memory_manager()

        logger.info(
            "[MemoryTool] action={}, user_id={}, category={}",
            action, user_id, kwargs.get("category", ""),
        )

        result = await manager.batch_execute(
            action=action,
            user_id=user_id,
            conversation_id=conversation_id,
            category=kwargs.get("category", ""),
            title=kwargs.get("title", ""),
            content=kwargs.get("content", ""),
            memory_id=kwargs.get("memory_id", ""),
            keywords=kwargs.get("keywords"),
        )

        return result
