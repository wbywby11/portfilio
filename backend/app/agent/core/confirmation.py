"""
M3 确认卡片协议 — 确认记录管理与决策执行

两阶段执行模型：
1. ConfirmableTool.execute() 只创建 pending 记录并返回 token（不执行业务）
2. 用户确认后，决策 API 调 resolve_decision() 执行 tool.perform()（先过 M2 护栏）

TTL：pending 记录 30 分钟后过期（决策执行时校验，不做定时任务）。
状态机：pending → confirmed（执行成功）/ rejected（用户取消或护栏拒绝）
        / expired（超时）/ failed（执行异常）。
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.agent.core.write_guard import (
    WriteGuardError, log_write_action, rejection_result,
)
from app.config.collections import COL_AGENT_CONFIRMATIONS

CONFIRMATION_TTL_MINUTES = 30

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"

# 写回会话历史的结果摘要上限（防止超大结果污染消息）
_RESULT_SUMMARY_MAX_CHARS = 3000


def _bson_safe(obj):
    """JSON 往返一次，将 datetime/numpy 等非 BSON 原生类型转为可存储形态"""
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return str(obj)


class ConfirmationService:
    """确认记录的创建、查重、决策执行"""

    _db = None
    _indexes_ensured = False

    @classmethod
    def _collection(cls):
        if cls._db is None:
            from app.config.database import Database
            cls._db = Database.get_database()
        return cls._db[COL_AGENT_CONFIRMATIONS]

    @classmethod
    async def _ensure_indexes(cls):
        if cls._indexes_ensured:
            return
        try:
            coll = cls._collection()
            await coll.create_index("token", unique=True, name="uniq_token")
            await coll.create_index(
                [("conversation_id", 1), ("status", 1)], name="idx_conv_status",
            )
            cls._indexes_ensured = True
        except Exception as e:
            logger.warning("confirmation_index_failed", extra={"error": str(e)})

    # ------------------------------------------------------------------
    # 阶段一：创建确认记录
    # ------------------------------------------------------------------

    @classmethod
    async def request_confirmation(
        cls, conversation_id: str, tool_name: str, arguments: dict, preview: dict,
    ) -> tuple[str, bool]:
        """创建 pending 确认记录，返回 (token, 是否复用已有记录)"""
        await cls._ensure_indexes()
        coll = cls._collection()

        # 查重：同会话同工具同参数的未过期 pending 记录复用 token
        args_key = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)
        existing = await coll.find_one({
            "conversation_id": conversation_id,
            "tool_name": tool_name,
            "arguments_key": args_key,
            "status": STATUS_PENDING,
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        })
        if existing:
            logger.info("confirmation_reused", extra={"token": existing["token"], "tool": tool_name})
            return existing["token"], True

        now = datetime.now(timezone.utc)
        token = uuid.uuid4().hex
        await coll.insert_one({
            "token": token,
            "conversation_id": conversation_id,
            "tool_name": tool_name,
            "arguments": _bson_safe(arguments or {}),
            "arguments_key": args_key,
            "preview": _bson_safe(preview or {}),
            "status": STATUS_PENDING,
            "created_at": now,
            "expires_at": now + timedelta(minutes=CONFIRMATION_TTL_MINUTES),
            "decided_at": None,
            "result": None,
        })
        await log_write_action(conversation_id, tool_name, arguments, "pending_confirmation")
        logger.info("confirmation_created", extra={"token": token, "tool": tool_name})
        return token, False

    @classmethod
    async def get_record(cls, token: str) -> dict | None:
        """按 token 查确认记录（供决策 API / 前端重建卡片状态）"""
        doc = await cls._collection().find_one({"token": token}, {"_id": 0})
        return _bson_safe(doc) if doc else None

    @classmethod
    async def list_conversation_records(cls, conversation_id: str, limit: int = 20) -> list[dict]:
        """查会话的确认记录（时间倒序，供历史消息重建终态卡片）"""
        cursor = (
            cls._collection()
            .find({"conversation_id": conversation_id}, {"_id": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        items = []
        async for doc in cursor:
            items.append(_bson_safe(doc))
        return items

    # ------------------------------------------------------------------
    # 阶段二：决策执行
    # ------------------------------------------------------------------

    @classmethod
    async def resolve_decision(cls, token: str, decision: str) -> dict:
        """处理用户决策，返回响应体 {ok, status, result|error}"""
        from app.agent.services.conversation_store import ConversationStore
        from app.agent.tools.base import tool_registry

        coll = cls._collection()
        record = await coll.find_one({"token": token})
        if not record:
            return {"ok": False, "error": "确认记录不存在"}

        if record["status"] != STATUS_PENDING:
            return {"ok": False, "status": record["status"], "error": "该操作已处理，请勿重复提交"}

        now = datetime.now(timezone.utc)
        conversation_id = record.get("conversation_id", "")
        tool_name = record.get("tool_name", "")
        arguments = record.get("arguments") or {}

        # TTL 校验（执行时检查，不做定时任务）
        expires_at = record.get("expires_at")
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at <= now:
            await coll.update_one({"token": token}, {"$set": {"status": STATUS_EXPIRED, "decided_at": now}})
            await log_write_action(conversation_id, tool_name, arguments, "expired")
            return {"ok": False, "status": STATUS_EXPIRED, "error": "确认已过期，请重新发起操作"}

        # 拒绝分支
        if decision != "confirmed":
            await coll.update_one({"token": token}, {"$set": {"status": STATUS_REJECTED, "decided_at": now}})
            await log_write_action(conversation_id, tool_name, arguments, "cancelled")
            await ConversationStore().add_message(
                conversation_id, role="assistant",
                content=f"[操作已取消] 用户取消了待执行的 `{tool_name}` 操作，未产生任何变更。",
            )
            return {"ok": True, "status": STATUS_REJECTED}

        # 确认分支：执行真实逻辑（护栏校验在 perform 内部完成）
        tool = tool_registry.get_tool(tool_name)
        if not tool or not hasattr(tool, "perform"):
            return {"ok": False, "error": f"工具 {tool_name} 不可执行"}

        perform_args = dict(arguments)
        perform_args["conversation_id"] = conversation_id
        try:
            result = await tool.perform(**perform_args)
            status = STATUS_CONFIRMED
        except WriteGuardError as e:
            result = rejection_result(e.reason)
            status = STATUS_REJECTED
        except Exception as e:
            logger.error("confirmation_perform_failed", extra={"tool": tool_name, "error": str(e)})
            result = {"status": "failed", "error": str(e)}
            status = STATUS_FAILED

        await coll.update_one({"token": token}, {"$set": {
            "status": status, "decided_at": now, "result": _bson_safe(result),
        }})
        await log_write_action(conversation_id, tool_name, arguments, status, result)

        # 结果写回会话历史（后续轮次可引用）
        try:
            summary = json.dumps(result, ensure_ascii=False, default=str)
            if len(summary) > _RESULT_SUMMARY_MAX_CHARS:
                summary = summary[:_RESULT_SUMMARY_MAX_CHARS] + "...[已截断]"
            await ConversationStore().add_message(
                conversation_id, role="assistant",
                content=f"[`{tool_name}` 操作执行结果]\n{summary}",
            )
        except Exception as e:
            logger.warning("confirmation_result_message_failed", extra={"token": token, "error": str(e)})

        return {
            "ok": status == STATUS_CONFIRMED,
            "status": status,
            "result": _bson_safe(result),
        }
