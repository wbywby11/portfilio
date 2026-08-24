"""
知识库检索工具 — Agent 通过关键词/分类/资产代码检索研究文档

设计原则：
- 返回摘要级结果（不含全文），控制上下文消耗
- 支持多维过滤：全文关键词 + 分类 + 资产代码 + 标签
- 结果数量受 config 限制，避免上下文膨胀
"""
from loguru import logger

from app.agent.knowledge.knowledge_service import KnowledgeService
from app.agent.tools.base import BaseTool

# 模块级单例
_knowledge_service: KnowledgeService | None = None


def _get_knowledge_service() -> KnowledgeService:
    """延迟获取 KnowledgeService 单例"""
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeService()
    return _knowledge_service


class SearchKnowledgeTool(BaseTool):
    """知识库检索工具 — 关键词 + 结构化过滤"""

    name = "search_knowledge"
    description = (
        "检索知识库中的研究文档。支持关键词全文搜索和多维过滤。\n"
        "返回匹配文档的标题、摘要、分类和标签（不含全文）。\n"
        "如需查看全文，请使用 read_knowledge 工具。\n"
        "可用分类: research_report(研究报告), product_doc(产品文档), "
        "strategy_note(策略笔记), regulation(法规制度), "
        "meeting_note(会议纪要), market_commentary(市场点评)"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词（空格分隔多词，如'风险平价 2024'）",
            },
            "category": {
                "type": "string",
                "enum": [
                    "research_report", "product_doc", "strategy_note",
                    "regulation", "meeting_note", "market_commentary",
                ],
                "description": "按分类过滤（可选）",
            },
            "asset_code": {
                "type": "string",
                "description": "按关联资产代码过滤（可选，如'000300.SH'）",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "按标签过滤（可选，任一匹配即返回）",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数上限（默认 5，最大 10）",
            },
        },
        "required": [],
    }

    # 检索结果为摘要级，较短
    max_result_chars = 6000
    budget_threshold = 0

    async def execute(
        self,
        query: str = "",
        category: str = "",
        asset_code: str = "",
        tags: list[str] | None = None,
        limit: int = 5,
        **kwargs,
    ) -> dict:
        """执行知识库检索"""
        # 至少要有一个检索条件
        if not query and not category and not asset_code and not tags:
            return {
                "success": False,
                "error": "请至少提供一个检索条件（query/category/asset_code/tags）",
            }

        # 限制返回条数
        limit = max(1, min(limit, 10))

        service = _get_knowledge_service()

        logger.info(
            "[SearchKnowledge] query='{}', category='{}', asset='{}', limit={}",
            query, category, asset_code, limit,
        )

        result = await service.search(
            query=query,
            category=category,
            asset_code=asset_code,
            tags=tags,
            limit=limit,
        )

        if not result["success"]:
            return result

        # 格式化输出，方便 Agent 阅读
        results = result["results"]
        formatted = []
        for doc in results:
            formatted.append({
                "id": doc.get("id", ""),
                "title": doc.get("title", ""),
                "category": doc.get("category", ""),
                "summary": doc.get("summary", ""),
                "tags": doc.get("tags", []),
                "related_assets": doc.get("related_assets", []),
                "updated_at": str(doc.get("updated_at", "")),
            })

        return {
            "success": True,
            "total": result["total"],
            "count": len(formatted),
            "results": formatted,
            "hint": "使用 read_knowledge 工具传入 id 可查看全文",
        }
