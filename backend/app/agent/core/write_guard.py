"""
M2 写操作边界护栏

来源标记约定（存量数据不打标，缺省即用户创建，默认拒绝）：
- agent 写入的任何文档必须经 stamp_agent_origin() 附加 created_by + agent_meta
- 修改/删除类操作执行前必须经 assert_agent_owned() 校验，目标非 agent 创建即拒绝
- 所有写操作（含被拒的）经 log_write_action() 落 COL_AGENT_WRITE_LOGS 审计
"""
import json
from datetime import datetime, timezone

from loguru import logger

from app.config.collections import COL_AGENT_WRITE_LOGS

# agent 来源标记值（无 created_by 字段的文档一律视为用户创建）
AGENT_CREATED_BY = "agent"

# 审计记录中 result 字段的最大序列化长度（防止大结果撑爆审计集合）
_AUDIT_RESULT_MAX_CHARS = 4000


class WriteGuardError(Exception):
    """护栏拒绝：目标实体不存在或非 agent 创建"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def stamp_agent_origin(doc: dict, conversation_id: str, tool_name: str) -> dict:
    """为待写入文档附加 agent 来源标记，返回原 dict（可链式使用）"""
    doc["created_by"] = AGENT_CREATED_BY
    doc["agent_meta"] = {
        "conversation_id": conversation_id or "",
        "tool_name": tool_name,
        "created_at": datetime.now(timezone.utc),
    }
    return doc


def is_agent_created(doc: dict | None) -> bool:
    """判断文档是否为 agent 创建（缺省/None 一律 False）"""
    return bool(doc) and doc.get("created_by") == AGENT_CREATED_BY


def assert_agent_owned(doc: dict | None, entity_label: str, page_hint: str = "") -> None:
    """校验目标实体为 agent 创建，否则抛 WriteGuardError。

    Args:
        doc: 目标文档（None 视为不存在）
        entity_label: 实体中文名（用于拒绝文案，如"组合"）
        page_hint: 引导用户前往的页面名（如"组合管理"），空则不引导
    """
    if doc is None:
        raise WriteGuardError(f"目标{entity_label}不存在，无法修改。")
    if not is_agent_created(doc):
        hint = f"，请到{page_hint}页面修改" if page_hint else ""
        raise WriteGuardError(
            f"该{entity_label}为您手动创建，Agent 无权修改{hint}。"
        )


def rejection_result(reason: str) -> dict:
    """构造护栏拒绝的工具结果（agent 应如实转达原因）"""
    return {"status": "rejected", "reason": reason}


async def log_write_action(
    conversation_id: str,
    tool_name: str,
    arguments: dict,
    decision: str,
    result=None,
) -> None:
    """写操作审计落库（best-effort，失败仅告警不阻断业务）。

    Args:
        decision: allowed / rejected / pending_confirmation / confirmed / cancelled / expired / failed
        result: 执行结果（序列化后截断存储）
    """
    from app.config.database import Database

    result_str: str | None = None
    if result is not None:
        try:
            result_str = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            result_str = str(result)
        if len(result_str) > _AUDIT_RESULT_MAX_CHARS:
            result_str = result_str[:_AUDIT_RESULT_MAX_CHARS] + "...[已截断]"

    try:
        db = Database.get_database()
        await db[COL_AGENT_WRITE_LOGS].insert_one({
            "conversation_id": conversation_id or "",
            "tool": tool_name,
            "arguments": arguments or {},
            "decision": decision,
            "result": result_str,
            "at": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning("agent_write_log_failed", extra={"tool": tool_name, "error": str(e)})
