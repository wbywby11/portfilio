"""
知识库精读工具 — Agent 按 ID 读取文档全文

设计原则：
- 配合 search_knowledge 使用：先搜摘要，再精读全文
- 全文可能较长，受 max_result_chars 截断保护
- budget_threshold > 0 允许 L2 持久化（超长文档→MongoDB→preview）
"""
from loguru import logger

from app.agent.knowledge.knowledge_service import KnowledgeService
from app.agent.tools.base import BaseTool

# 模块级单例（与 search_knowledge_tool 共享）
_knowledge_service: KnowledgeService | None = None


def _get_knowledge_service() -> KnowledgeService:
    """延迟获取 KnowledgeService 单例"""
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeService()
    return _knowledge_service


class ReadKnowledgeTool(BaseTool):
    """知识库精读工具 — 按 ID 读取文档全文"""

    name = "read_knowledge"
    description = (
        "读取知识库中指定文档的完整内容。"
        "需要先通过 search_knowledge 获取文档 id，再传入此工具精读全文。"
        "适用于需要引用具体数据、详细分析或完整段落的场景。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "knowledge_id": {
                "type": "string",
                "description": "文档 ID（从 search_knowledge 结果中获取）",
            },
        },
        "required": ["knowledge_id"],
    }

    # 全文可能较长，允许较大结果
    max_result_chars = 20000
    # 超过全局阈值时走 L2 持久化（长文档→MongoDB→preview）
    budget_threshold = 0

    async def execute(self, knowledge_id: str, **kwargs) -> dict:
        """读取文档全文"""
        if not knowledge_id or not isinstance(knowledge_id, str):
            return {"success": False, "error": "缺少有效的 knowledge_id 参数"}

        service = _get_knowledge_service()

        logger.info("[ReadKnowledge] 精读文档: id={}", knowledge_id)

        result = await service.get_document(knowledge_id)

        if not result["success"]:
            return result

        doc = result["document"]

        return {
            "success": True,
            "id": doc.get("id", knowledge_id),
            "title": doc.get("title", ""),
            "category": doc.get("category", ""),
            "tags": doc.get("tags", []),
            "related_assets": doc.get("related_assets", []),
            "source": doc.get("source", ""),
            "content": doc.get("content", ""),
            "updated_at": str(doc.get("updated_at", "")),
        }
