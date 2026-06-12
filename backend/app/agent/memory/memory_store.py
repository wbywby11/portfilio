"""
记忆持久化层

使用 MongoDB 存储 Agent 的跨会话记忆。
支持按用户、按分类存储和检索记忆。
"""
import asyncio
import re
from datetime import datetime, timezone

from bson import ObjectId
from loguru import logger

from app.config.database import Database


class MemoryStore:
    """
    记忆持久化 - MongoDB 存储

    集合: agent_memories
    文档结构:
    {
        "_id": ObjectId,
        "user_id": str,
        "category": str,        # 记忆分类
        "title": str,           # 记忆标题
        "content": str,         # 记忆内容
        "keywords": [str],      # 关键词列表
        "created_at": datetime,
        "updated_at": datetime,
    }

    索引:
    - (user_id, category, updated_at DESC)  # 按用户+分类查询
    - (user_id, keywords)                    # 按用户+关键词检索
    """

    COLLECTION = "agent_memories"

    # 安全限制
    MAX_TOTAL_CHARS_PER_USER = 5000    # 每用户记忆总字符上限
    MAX_SINGLE_MEMORY_CHARS = 1000     # 单条记忆最大字符数
    MAX_MEMORIES_PER_USER = 50         # 每用户最大记忆条数
    MAX_KEYWORDS_PER_MEMORY = 10       # 单条记忆最大关键词数

    _indexes_ensured: bool = False
    _index_lock: asyncio.Lock | None = None  # 延迟创建，避免在模块导入时绑定事件循环

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

    async def _ensure_indexes(self):
        """确保索引存在（幂等，仅执行一次，双重检查 + 异步锁保护）"""
        if MemoryStore._indexes_ensured:
            return
        # 延迟创建锁，确保在事件循环内
        if MemoryStore._index_lock is None:
            MemoryStore._index_lock = asyncio.Lock()
        async with MemoryStore._index_lock:
            if MemoryStore._indexes_ensured:  # 双重检查
                return
            try:
                await self.collection.create_index(
                    [("user_id", 1), ("category", 1), ("updated_at", -1)],
                    name="idx_user_category_updated",
                    background=True,
                )
                await self.collection.create_index(
                    [("user_id", 1), ("keywords", 1)],
                    name="idx_user_keywords",
                    background=True,
                )
                MemoryStore._indexes_ensured = True
                logger.info("记忆集合 MongoDB 索引创建完成")
            except Exception as e:
                logger.warning("记忆索引创建失败（非致命）: {}", e)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def save(
        self,
        user_id: str,
        category: str,
        title: str,
        content: str,
        keywords: list[str] | None = None,
    ) -> dict:
        """
        保存一条记忆

        安全检查：
        1. 单条内容不超过 MAX_SINGLE_MEMORY_CHARS
        2. 用户总记忆不超过 MAX_TOTAL_CHARS_PER_USER
        3. 用户记忆条数不超过 MAX_MEMORIES_PER_USER
        4. 内容通过注入校验
        """
        await self._ensure_indexes()

        # 安全校验
        content = content.strip()
        if not content:
            return {"success": False, "error": "记忆内容不能为空"}

        if len(content) > self.MAX_SINGLE_MEMORY_CHARS:
            return {
                "success": False,
                "error": f"单条记忆不能超过 {self.MAX_SINGLE_MEMORY_CHARS} 字符",
            }

        # 内容注入校验
        injection_check = self._check_injection(content)
        if injection_check:
            return {"success": False, "error": f"记忆内容包含不安全内容: {injection_check}"}

        # 检查用户总记忆量
        stats = await self._get_user_stats(user_id)
        if stats["count"] >= self.MAX_MEMORIES_PER_USER:
            return {
                "success": False,
                "error": f"记忆数量已达上限 ({self.MAX_MEMORIES_PER_USER} 条)，请删除旧记忆后重试",
            }

        if stats["total_chars"] + len(content) > self.MAX_TOTAL_CHARS_PER_USER:
            return {
                "success": False,
                "error": f"记忆总量已接近上限 ({self.MAX_TOTAL_CHARS_PER_USER} 字符)，请删除旧记忆后重试",
            }

        # 关键词处理
        if keywords:
            keywords = [k.strip()[:20] for k in keywords[: self.MAX_KEYWORDS_PER_MEMORY]]
        else:
            keywords = []

        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user_id,
            "category": category,
            "title": title.strip()[:100],  # 标题最长 100 字符
            "content": content,
            "keywords": keywords,
            "created_at": now,
            "updated_at": now,
        }

        result = await self.collection.insert_one(doc)
        memory_id = str(result.inserted_id)
        logger.info("[MemoryStore] 保存记忆: user={}, category={}, id={}", user_id, category, memory_id)
        return {"success": True, "memory_id": memory_id}

    async def search(
        self,
        user_id: str,
        query: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """
        检索记忆 - 基于关键词匹配

        搜索策略：在 title、content、keywords 中查找包含查询词的记忆
        """
        await self._ensure_indexes()

        # 构建查询条件
        filter_doc: dict = {"user_id": user_id}
        if category:
            filter_doc["category"] = category

        # 文本搜索：在 title/content/keywords 中查找
        search_terms = query.strip().split()
        if search_terms:
            or_conditions = []
            for term in search_terms[:5]:  # 最多 5 个搜索词
                regex = {"$regex": re.escape(term), "$options": "i"}
                or_conditions.extend([
                    {"title": regex},
                    {"content": regex},
                    {"keywords": regex},
                ])
            filter_doc["$or"] = or_conditions

        cursor = (
            self.collection.find(filter_doc)
            .sort("updated_at", -1)
            .limit(min(limit, 10))  # 最多返回 10 条
        )

        results = []
        async for doc in cursor:
            results.append({
                "memory_id": str(doc["_id"]),
                "category": doc.get("category", ""),
                "title": doc.get("title", ""),
                "content": doc.get("content", ""),
                "keywords": doc.get("keywords", []),
                "created_at": (
                    doc["created_at"].isoformat() if doc.get("created_at") else ""
                ),
                "updated_at": (
                    doc["updated_at"].isoformat() if doc.get("updated_at") else ""
                ),
            })

        return results

    async def update(self, memory_id: str, content: str, user_id: str) -> dict:
        """更新记忆内容（需验证归属）"""
        content = content.strip()
        if not content:
            return {"success": False, "error": "内容不能为空"}

        if len(content) > self.MAX_SINGLE_MEMORY_CHARS:
            return {
                "success": False,
                "error": f"内容不能超过 {self.MAX_SINGLE_MEMORY_CHARS} 字符",
            }

        injection_check = self._check_injection(content)
        if injection_check:
            return {"success": False, "error": f"内容包含不安全内容: {injection_check}"}

        try:
            result = await self.collection.update_one(
                {"_id": ObjectId(memory_id), "user_id": user_id},
                {"$set": {"content": content, "updated_at": datetime.now(timezone.utc)}},
            )
            if result.modified_count > 0:
                return {"success": True}
            return {"success": False, "error": "记忆不存在或无权修改"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def delete(self, memory_id: str, user_id: str) -> dict:
        """删除记忆（需验证归属）"""
        try:
            result = await self.collection.delete_one(
                {"_id": ObjectId(memory_id), "user_id": user_id}
            )
            if result.deleted_count > 0:
                return {"success": True}
            return {"success": False, "error": "记忆不存在或无权删除"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def list_by_category(
        self, user_id: str, category: str | None = None
    ) -> list[dict]:
        """列出用户的记忆（按分类筛选）"""
        filter_doc: dict = {"user_id": user_id}
        if category:
            filter_doc["category"] = category

        cursor = (
            self.collection.find(filter_doc)
            .sort("updated_at", -1)
            .limit(50)
        )

        results = []
        async for doc in cursor:
            full_content = doc.get("content", "")
            results.append({
                "memory_id": str(doc["_id"]),
                "category": doc.get("category", ""),
                "title": doc.get("title", ""),
                "content": (
                    full_content[:100] + "..." if len(full_content) > 100 else full_content
                ),
                "keywords": doc.get("keywords", []),
                "updated_at": (
                    doc["updated_at"].isoformat() if doc.get("updated_at") else ""
                ),
            })
        return results

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    async def _get_user_stats(self, user_id: str) -> dict:
        """获取用户记忆统计"""
        pipeline = [
            {"$match": {"user_id": user_id}},
            {
                "$group": {
                    "_id": None,
                    "count": {"$sum": 1},
                    "total_chars": {"$sum": {"$strLenCP": "$content"}},
                }
            },
        ]
        async for result in self.collection.aggregate(pipeline):
            return {"count": result["count"], "total_chars": result["total_chars"]}
        return {"count": 0, "total_chars": 0}

    @staticmethod
    def _check_injection(content: str) -> str | None:
        """
        检查内容是否包含 prompt injection 模式

        返回检测到的问题描述，无问题则返回 None
        """
        # 检测常见的 prompt injection 模式
        patterns = [
            (r"ignore\s+(all\s+)?previous\s+instructions", "尝试覆盖系统指令"),
            (r"you\s+are\s+now\s+", "尝试重新定义角色"),
            (r"system\s*:\s*", "尝试注入系统消息"),
            (r"<\|.*?\|>", "包含特殊标记"),
            (r"\[INST\]|\[/INST\]", "包含指令标记"),
            (r"<<SYS>>|<</SYS>>", "包含系统标记"),
            (r"human\s*:\s*|assistant\s*:\s*", "包含角色标记"),
        ]

        content_lower = content.lower()
        for pattern, desc in patterns:
            if re.search(pattern, content_lower):
                logger.warning("[MemoryStore] 检测到注入模式: {}", desc)
                return desc

        # 检测不可见 Unicode 字符
        invisible_chars = [
            "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",  # 零宽字符
            "\u2028", "\u2029",  # 行/段分隔符
            "\ufeff",  # BOM
        ]
        for char in invisible_chars:
            if char in content:
                return "包含不可见控制字符"

        return None
