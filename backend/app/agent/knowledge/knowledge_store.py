"""
知识库持久化层

MongoDB 集合: agent_knowledge
搜索方案: $regex 子串匹配（title/content/tags）+ 结构化字段过滤（零外部依赖）
说明: $text 全文索引按空格分词，对无空格的中文正文无法命中，故弃用。
      文档量在千级以内，正则扫描性能可接受。

文档结构:
{
    "_id": ObjectId,
    "title": str,              # 文档标题
    "category": str,           # 分类（research_report/product_doc/strategy_note/regulation/meeting_note）
    "tags": [str],             # 标签列表
    "content": str,            # Markdown 全文
    "summary": str,            # 摘要（≤200字，用于检索结果展示）
    "source": str,             # 来源（manual/agent_generated/imported）
    "related_assets": [str],   # 关联资产代码
    "created_at": datetime,
    "updated_at": datetime,
}
"""
import re
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from loguru import logger

from app.config.database import Database


class KnowledgeStore:
    """知识库 MongoDB 存储层"""

    COLLECTION = "agent_knowledge"

    _indexes_ensured: bool = False

    def __init__(self):
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        return self.db[self.COLLECTION]

    async def ensure_indexes(self) -> None:
        """确保索引存在（幂等，仅执行一次）"""
        if KnowledgeStore._indexes_ensured:
            return
        try:
            # 清理废弃的 $text 全文索引（按空格分词，中文正文无法命中，已改用 $regex）
            try:
                await self.collection.drop_index("idx_fulltext")
                logger.info("知识库已移除废弃的全文索引 idx_fulltext")
            except Exception:
                pass  # 索引不存在时忽略
            # 结构化过滤索引
            await self.collection.create_index(
                [("category", 1), ("updated_at", -1)],
                name="idx_category_updated",
            )
            await self.collection.create_index(
                [("related_assets", 1)],
                name="idx_related_assets",
            )
            KnowledgeStore._indexes_ensured = True
            logger.info("知识库 MongoDB 索引创建完成")
        except Exception as e:
            logger.warning("知识库索引创建失败（非致命）: {}", e)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def insert(self, doc: dict) -> str:
        """插入知识文档，返回文档 ID"""
        now = datetime.now(timezone.utc)
        doc["created_at"] = now
        doc["updated_at"] = now
        result = await self.collection.insert_one(doc)
        doc_id = str(result.inserted_id)
        logger.info("[Knowledge] 新增: id={}, title={}", doc_id, doc.get("title", ""))
        return doc_id

    async def get_by_id(self, knowledge_id: str) -> Optional[dict]:
        """按 ID 获取完整文档"""
        if not ObjectId.is_valid(knowledge_id):
            return None
        doc = await self.collection.find_one({"_id": ObjectId(knowledge_id)})
        if doc:
            doc["id"] = str(doc.pop("_id"))
        return doc

    async def update(self, knowledge_id: str, updates: dict) -> bool:
        """更新文档字段"""
        if not ObjectId.is_valid(knowledge_id):
            return False
        updates["updated_at"] = datetime.now(timezone.utc)
        result = await self.collection.update_one(
            {"_id": ObjectId(knowledge_id)},
            {"$set": updates},
        )
        return result.modified_count > 0

    async def delete(self, knowledge_id: str) -> bool:
        """删除文档"""
        if not ObjectId.is_valid(knowledge_id):
            return False
        result = await self.collection.delete_one({"_id": ObjectId(knowledge_id)})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filter(
        query: str = "",
        category: str = "",
        asset_code: str = "",
        tags: list[str] | None = None,
    ) -> dict:
        """构建检索过滤条件（search 与 count 共用，保证分页 total 一致）。

        关键词语义：空格分隔多词为 AND，单词在 title/content/tags 间为 OR，
        大小写不敏感子串匹配（支持无空格中文正文）。
        """
        filter_doc: dict = {}

        # 关键词子串匹配
        terms = [t for t in query.strip().split() if t] if query else []
        if terms:
            clauses = []
            for term in terms:
                regex = {"$regex": re.escape(term), "$options": "i"}
                clauses.append({"$or": [
                    {"title": regex}, {"content": regex}, {"tags": regex},
                ]})
            if len(clauses) == 1:
                filter_doc.update(clauses[0])
            else:
                filter_doc["$and"] = clauses

        # 结构化过滤
        if category:
            filter_doc["category"] = category
        if asset_code:
            filter_doc["related_assets"] = asset_code
        if tags:
            filter_doc["tags"] = {"$in": tags}

        return filter_doc

    async def search(
        self,
        query: str = "",
        category: str = "",
        asset_code: str = "",
        tags: list[str] | None = None,
        limit: int = 5,
        skip: int = 0,
    ) -> list[dict]:
        """
        多维检索：关键词子串匹配 + 分类 + 资产代码 + 标签。

        Args:
            query: 搜索关键词（空格分隔多词=AND，单词跨字段=OR）
            category: 分类过滤（空=不过滤）
            asset_code: 关联资产代码过滤
            tags: 标签过滤（任一匹配）
            limit: 返回条数上限
            skip: 跳过条数

        Returns:
            匹配文档列表（含 id/title/summary/category/tags）
        """
        filter_doc = self._build_filter(query, category, asset_code, tags)

        # 投影：不返回全文 content（节省带宽）
        projection = {
            "title": 1, "category": 1, "tags": 1,
            "summary": 1, "related_assets": 1, "source": 1,
            "updated_at": 1,
        }

        cursor = (
            self.collection.find(filter_doc, projection)
            .sort("updated_at", -1)
            .skip(skip)
            .limit(limit)
        )

        results = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            results.append(doc)

        return results

    async def count(
        self,
        query: str = "",
        category: str = "",
        asset_code: str = "",
        tags: list[str] | None = None,
    ) -> int:
        """统计文档总数（与 search 使用同一过滤条件，保证分页 total 准确）"""
        filter_doc = self._build_filter(query, category, asset_code, tags)
        return await self.collection.count_documents(filter_doc)
