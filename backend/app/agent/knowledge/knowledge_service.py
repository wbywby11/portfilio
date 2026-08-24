"""
知识库业务服务层

职责：文档摄入（校验、去重、摘要生成）、检索编排、统计。
不感知 HTTP 概念，供 Agent 工具和 API 路由调用。
"""
from loguru import logger

from app.agent.core.config import get_agent_settings
from app.agent.knowledge.knowledge_store import KnowledgeStore


# 知识库分类体系
KNOWLEDGE_CATEGORIES: dict[str, str] = {
    "research_report": "研究报告",
    "product_doc": "产品文档",
    "strategy_note": "策略笔记",
    "regulation": "法规制度",
    "meeting_note": "会议纪要",
    "market_commentary": "市场点评",
}

# 从配置中心读取上限
_settings = get_agent_settings()
MAX_CONTENT_CHARS: int = _settings.KNOWLEDGE_MAX_CONTENT_CHARS
MAX_SUMMARY_CHARS: int = 200
MAX_TAGS_PER_DOC: int = 10


class KnowledgeService:
    """知识库业务服务"""

    def __init__(self, store: KnowledgeStore | None = None):
        self.store = store or KnowledgeStore()

    async def ensure_ready(self) -> None:
        """确保索引就绪"""
        await self.store.ensure_indexes()

    # ------------------------------------------------------------------
    # 文档摄入
    # ------------------------------------------------------------------

    async def add_document(
        self,
        title: str,
        content: str,
        category: str = "research_report",
        tags: list[str] | None = None,
        summary: str = "",
        source: str = "manual",
        related_assets: list[str] | None = None,
    ) -> dict:
        """
        新增知识文档（含校验和自动摘要）。

        Args:
            title: 文档标题
            content: Markdown 全文
            category: 分类（必须在 KNOWLEDGE_CATEGORIES 中）
            tags: 标签列表
            summary: 摘要（空则自动截取前 200 字）
            source: 来源标识
            related_assets: 关联资产代码列表

        Returns:
            {"success": True, "id": str} 或 {"success": False, "error": str}
        """
        # 校验
        error = self._validate_input(title, content, category, tags)
        if error:
            return {"success": False, "error": error}

        # 自动摘要
        if not summary:
            summary = self._auto_summary(content)

        # 截断过长标签
        tags = (tags or [])[:MAX_TAGS_PER_DOC]

        doc = {
            "title": title.strip(),
            "content": content,
            "category": category,
            "tags": tags,
            "summary": summary[:MAX_SUMMARY_CHARS],
            "source": source,
            "related_assets": related_assets or [],
        }

        doc_id = await self.store.insert(doc)
        return {"success": True, "id": doc_id, "title": title.strip()}

    async def update_document(
        self, knowledge_id: str, updates: dict
    ) -> dict:
        """更新文档（仅允许更新 title/content/tags/summary/category/related_assets）"""
        allowed_fields = {"title", "content", "tags", "summary", "category", "related_assets"}
        filtered = {k: v for k, v in updates.items() if k in allowed_fields}
        if not filtered:
            return {"success": False, "error": "无有效更新字段"}

        ok = await self.store.update(knowledge_id, filtered)
        if not ok:
            return {"success": False, "error": f"文档不存在或无变更: {knowledge_id}"}
        return {"success": True, "id": knowledge_id}

    async def delete_document(self, knowledge_id: str) -> dict:
        """删除文档"""
        ok = await self.store.delete(knowledge_id)
        if not ok:
            return {"success": False, "error": f"文档不存在: {knowledge_id}"}
        return {"success": True, "id": knowledge_id}

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str = "",
        category: str = "",
        asset_code: str = "",
        tags: list[str] | None = None,
        limit: int = 5,
    ) -> dict:
        """
        检索知识文档。

        Returns:
            {"success": True, "results": [...], "total": int}
        """
        results = await self.store.search(
            query=query, category=category,
            asset_code=asset_code, tags=tags, limit=limit,
        )
        total = await self.store.count(
            query=query, category=category, asset_code=asset_code, tags=tags
        )
        return {"success": True, "results": results, "total": total}

    async def get_document(self, knowledge_id: str) -> dict:
        """获取完整文档内容"""
        doc = await self.store.get_by_id(knowledge_id)
        if not doc:
            return {"success": False, "error": f"文档不存在: {knowledge_id}"}
        return {"success": True, "document": doc}

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _validate_input(
        self, title: str, content: str, category: str, tags: list[str] | None
    ) -> str:
        """校验输入，返回错误信息（空=通过）"""
        if not title or not title.strip():
            return "标题不能为空"
        if not content or not content.strip():
            return "内容不能为空"
        if len(content) > MAX_CONTENT_CHARS:
            return f"内容超过上限（{MAX_CONTENT_CHARS} 字符）"
        if category not in KNOWLEDGE_CATEGORIES:
            valid = list(KNOWLEDGE_CATEGORIES.keys())
            return f"无效分类 '{category}'，可选: {valid}"
        return ""

    @staticmethod
    def _auto_summary(content: str) -> str:
        """自动截取摘要：取前 200 字（去除 Markdown 标记）"""
        # 简单去除 Markdown 标题标记和多余空行
        lines = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)
            if len("".join(lines)) >= MAX_SUMMARY_CHARS:
                break
        text = " ".join(lines)
        return text[:MAX_SUMMARY_CHARS]
