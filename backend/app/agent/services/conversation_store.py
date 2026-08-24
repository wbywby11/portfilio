"""对话持久化 - MongoDB 异步存储"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from loguru import logger

from app.config.database import Database
from app.config.collections import COL_AGENT_CONVERSATIONS, COL_AGENT_MESSAGES

TOOL_RESULTS_COLLECTION = "agent_tool_results"


class ConversationStore:
    """对话与消息的 MongoDB CRUD"""

    _indexes_ensured: bool = False
    messages_collection: str = "agent_messages"

    def __init__(self):
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def conversations(self):
        return self.db[COL_AGENT_CONVERSATIONS]

    @property
    def messages(self):
        return self.db[COL_AGENT_MESSAGES]

    async def ensure_indexes(self):
        """确保 MongoDB 索引已创建（幂等，仅执行一次）"""
        if ConversationStore._indexes_ensured:
            return
        try:
            # 对话集合：按 user_id + status 查询，按 updated_at 排序
            await self.conversations.create_index(
                [("user_id", 1), ("status", 1), ("updated_at", -1)],
                name="idx_user_status_updated",
            )
            # 消息集合：按 conversation_id 查询，按 created_at 排序
            await self.messages.create_index(
                [("conversation_id", 1), ("created_at", -1)],
                name="idx_conv_created",
            )
            # 工具结果集合索引
            await self._ensure_tool_results_indexes()
            ConversationStore._indexes_ensured = True
            logger.info("Agent MongoDB 索引创建完成")
        except Exception as e:
            logger.warning("Agent MongoDB 索引创建失败（非致命）: {}", e)

    # ------------------------------------------------------------------
    # 对话 CRUD
    # ------------------------------------------------------------------
    async def create_conversation(self, user_id: str, title: str = "新对话") -> str:
        """创建对话，返回 conversation_id"""
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user_id,
            "title": title,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        result = await self.conversations.insert_one(doc)
        cid = str(result.inserted_id)
        logger.info("创建对话: id={}, user_id={}", cid, user_id)
        return cid

    async def get_conversations(
        self, user_id: str, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict], int]:
        """获取对话列表（分页），返回 (items, total)"""
        query = {"user_id": user_id, "status": "active"}
        total = await self.conversations.count_documents(query)

        skip = (page - 1) * page_size
        cursor = (
            self.conversations.find(query)
            .sort("updated_at", -1)
            .skip(skip)
            .limit(page_size)
        )
        items: list[dict] = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            items.append(doc)
        return items, total

    async def get_conversation(self, conversation_id: str) -> Optional[dict]:
        """获取单个对话"""
        try:
            doc = await self.conversations.find_one({"_id": ObjectId(conversation_id)})
        except Exception:
            logger.warning("无效的 conversation_id: {}", conversation_id)
            return None
        if doc:
            doc["id"] = str(doc.pop("_id"))
        return doc

    async def update_title(self, conversation_id: str, title: str):
        """更新对话标题"""
        await self.conversations.update_one(
            {"_id": ObjectId(conversation_id)},
            {"$set": {"title": title, "updated_at": datetime.now(timezone.utc)}},
        )
        logger.info("更新对话标题: id={}, title={}", conversation_id, title)

    async def delete_conversation(self, conversation_id: str):
        """软删除对话"""
        await self.conversations.update_one(
            {"_id": ObjectId(conversation_id)},
            {"$set": {"status": "deleted", "updated_at": datetime.now(timezone.utc)}},
        )
        logger.info("删除对话: id={}", conversation_id)

    # ------------------------------------------------------------------
    # 消息 CRUD
    # ------------------------------------------------------------------
    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        tool_calls_raw: list | None = None,
    ) -> str:
        """添加消息，返回 message_id"""
        now = datetime.now(timezone.utc)

        # 检测是否需要压缩工具结果
        is_compressed = False
        tool_result_ref: str | None = None
        store_content = content

        if role == "tool" and content and len(content) > 4000:
            # 大工具结果：生成摘要存入消息，完整结果另存
            is_compressed = True
            store_content = self._compress_tool_content(content)

        doc: dict = {
            "conversation_id": conversation_id,
            "role": role,
            "content": store_content,
            "created_at": now,
            # 新增元数据字段
            "content_size": len(content) if content else 0,
            "content_type": self._detect_content_type(role, store_content),
            "is_compressed": is_compressed,
        }
        if tool_calls is not None:
            doc["tool_calls"] = tool_calls
        if tool_call_id is not None:
            doc["tool_call_id"] = tool_call_id
        if tool_calls_raw is not None:
            doc["tool_calls_raw"] = tool_calls_raw

        result = await self.messages.insert_one(doc)
        message_id = str(result.inserted_id)

        # 大工具结果独立存储
        if is_compressed:
            tool_name = ""
            if tool_calls and len(tool_calls) > 0:
                tool_name = tool_calls[0].get("name", "")
            await self.save_tool_result_full(message_id, tool_name, content)
            # 回写 tool_result_ref
            await self.messages.update_one(
                {"_id": result.inserted_id},
                {"$set": {"tool_result_ref": message_id}},
            )

        # 同步更新对话的 updated_at
        try:
            await self.conversations.update_one(
                {"_id": ObjectId(conversation_id)},
                {"$set": {"updated_at": now}},
            )
        except Exception:
            pass

        return message_id

    async def get_messages(self, conversation_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        """获取对话消息列表（按时间正序，支持分页）"""
        cursor = (
            self.messages.find({"conversation_id": conversation_id})
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        items: list[dict] = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            items.append(doc)
        # 反转为时间正序
        items.reverse()
        return items

    async def count_messages(self, conversation_id: str) -> int:
        """统计对话消息总条数"""
        return await self.messages.count_documents({"conversation_id": conversation_id})

    # ------------------------------------------------------------------
    # 工具结果独立存储
    # ------------------------------------------------------------------
    async def _ensure_tool_results_indexes(self):
        """确保工具结果集合的索引（含TTL）"""
        coll = self.db[TOOL_RESULTS_COLLECTION]
        await coll.create_index("message_id")
        await coll.create_index("created_at", expireAfterSeconds=30 * 24 * 3600)  # 30天TTL

    async def save_tool_result_full(self, message_id: str, tool_name: str, full_result: str):
        """保存工具完整结果到独立集合（30天自动过期）"""
        if len(full_result) <= 4000:
            return  # 小结果不需要独立存储
        coll = self.db[TOOL_RESULTS_COLLECTION]
        await coll.insert_one({
            "message_id": message_id,
            "tool_name": tool_name,
            "full_result": full_result,
            "created_at": datetime.now(timezone.utc),
        })

    async def get_tool_result_full(self, message_id: str) -> str | None:
        """按需获取完整工具结果"""
        coll = self.db[TOOL_RESULTS_COLLECTION]
        doc = await coll.find_one({"message_id": message_id})
        return doc["full_result"] if doc else None

    # ------------------------------------------------------------------
    # 内容类型检测与压缩
    # ------------------------------------------------------------------
    def _detect_content_type(self, role: str, content: str | None) -> str:
        """检测消息内容类型"""
        if role == "tool":
            return "tool_result"
        if content and ("_compressed_summary" in content or "[摘要]" in content):
            return "summary"
        return "text"

    @staticmethod
    def _compress_tool_content(content: str) -> str:
        """压缩过长的工具结果内容，保留前后关键信息"""
        # 保留前 1500 字符 + 后 500 字符，中间用摘要标记
        head = content[:1500]
        tail = content[-500:]
        total_len = len(content)
        return (
            f"{head}\n\n[摘要] 原始结果共 {total_len} 字符，已压缩。"
            f"完整结果可通过 tool_result_ref 获取。\n\n...{tail}"
        )
