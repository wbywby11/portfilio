"""
记忆管理器

在 MemoryStore 之上提供业务逻辑：
- 记忆分类管理
- 对话开始时加载相关记忆
- 每轮写入限制控制
"""
from loguru import logger

from app.agent.memory.memory_store import MemoryStore


class MemoryManager:
    """
    记忆管理器

    分类体系：
    - research_conclusion: 研究结论（如"股债负相关性在2024年减弱"）
    - user_preference: 用户偏好（如"偏好月度再平衡"）
    - asset_alias: 资产别名（如"十债"→"ZQGZ10.SH"）
    - strategy_insight: 策略洞察（如"BL模型在低相关性资产上效果好"）

    安全约束：
    - 每轮对话最多写入 3 条记忆
    """

    CATEGORIES = {
        "research_conclusion": "研究结论",
        "user_preference": "用户偏好",
        "asset_alias": "资产别名",
        "strategy_insight": "策略洞察",
    }

    MAX_WRITES_PER_TURN = 3  # 每轮对话最多写入条数

    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()
        self._turn_write_count: dict[str, int] = {}  # conversation_id → 写入次数

    def reset_turn_counter(self, conversation_id: str):
        """重置每轮写入计数器（每轮对话开始时调用）"""
        self._turn_write_count[conversation_id] = 0

    def can_write(self, conversation_id: str) -> bool:
        """检查当前轮次是否还能写入"""
        count = self._turn_write_count.get(conversation_id, 0)
        return count < self.MAX_WRITES_PER_TURN

    def record_write(self, conversation_id: str):
        """记录一次写入"""
        self._turn_write_count[conversation_id] = (
            self._turn_write_count.get(conversation_id, 0) + 1
        )

    async def save_memory(
        self,
        user_id: str,
        category: str,
        title: str,
        content: str,
        keywords: list[str] | None = None,
        conversation_id: str = "",
    ) -> dict:
        """
        保存记忆（带每轮限制检查）
        """
        # 分类校验
        if category not in self.CATEGORIES:
            return {
                "success": False,
                "error": f"无效分类 '{category}'，可选: {list(self.CATEGORIES.keys())}",
            }

        # 每轮写入限制
        if conversation_id and not self.can_write(conversation_id):
            return {
                "success": False,
                "error": f"本轮对话已达写入上限 ({self.MAX_WRITES_PER_TURN} 条)",
            }

        result = await self.store.save(user_id, category, title, content, keywords)

        if result.get("success") and conversation_id:
            self.record_write(conversation_id)

        return result

    async def recall_memories(
        self,
        user_id: str,
        query: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """检索相关记忆"""
        if category and category not in self.CATEGORIES:
            return []
        return await self.store.search(user_id, query, category, limit)

    async def get_relevant_context(self, user_id: str, user_message: str) -> str:
        """
        获取与当前用户消息相关的记忆上下文
        用于注入到 system prompt 中

        Returns:
            格式化的记忆上下文字符串，为空则返回空字符串
        """
        memories = await self.store.search(user_id, user_message, limit=5)

        if not memories:
            return ""

        # 格式化为上下文块
        lines = ["[相关研究记忆]"]
        for mem in memories:
            cat_name = self.CATEGORIES.get(mem["category"], mem["category"])
            lines.append(f"- [{cat_name}] {mem['title']}: {mem['content']}")

        return "\n".join(lines)

    async def list_memories(
        self, user_id: str, category: str | None = None
    ) -> list[dict]:
        """列出用户记忆"""
        return await self.store.list_by_category(user_id, category)

    async def update_memory(
        self, memory_id: str, content: str, user_id: str
    ) -> dict:
        """更新记忆"""
        return await self.store.update(memory_id, content, user_id)

    async def delete_memory(self, memory_id: str, user_id: str) -> dict:
        """删除记忆"""
        return await self.store.delete(memory_id, user_id)
