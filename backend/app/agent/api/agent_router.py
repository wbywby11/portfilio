"""
AI Agent API 路由

核心端点：chat / chat_stream + 对话管理 + 记忆管理。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from app.agent.services.chat_service import ChatService
from app.agent.memory.memory_store import MemoryStore
from app.schemas.response import Response, PageData

router = APIRouter()

# 全局单例
_memory_store = MemoryStore()


# ------------------------------------------------------------------
# 请求 / 响应模型（内联）
# ------------------------------------------------------------------

class ChatRequest(BaseModel):
    """对话请求"""
    conversation_id: Optional[str] = None
    message: str
    scene: Optional[str] = None
    user_id: str = "default"

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("消息内容不能为空")
        if len(v) > 10000:
            raise ValueError("消息内容不能超过 10000 个字符")
        return v


class ConversationInfo(BaseModel):
    """对话摘要"""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    status: str = "active"


class ConversationDetail(BaseModel):
    """对话详情"""
    id: str
    title: str
    messages: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    total: int = 0
    has_more: bool = False
    page: int = 1
    page_size: int = 20


class UpdateTitleRequest(BaseModel):
    """更新对话标题请求"""
    title: str


class MemorySearchRequest(BaseModel):
    """记忆搜索请求"""
    keywords: list[str]
    user_id: str = "default"


class ConfirmationDecisionRequest(BaseModel):
    """写操作确认决策请求"""
    decision: str = Field(..., description="confirmed（确认执行）或 rejected（取消）")

    @field_validator("decision")
    @classmethod
    def decision_valid(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in ("confirmed", "rejected"):
            raise ValueError("decision 必须为 confirmed 或 rejected")
        return v


# ------------------------------------------------------------------
# 对话接口
# ------------------------------------------------------------------

def _get_chat_service() -> ChatService:
    return ChatService()


@router.post("/chat", summary="非流式对话")
async def chat(req: ChatRequest):
    """发送消息并获取 Agent 完整回复"""
    chat_service = _get_chat_service()
    try:
        reply = await chat_service.process_message(
            conversation_id=req.conversation_id,
            message=req.message,
            user_id=req.user_id,
        )
        return Response.success(data=reply)
    except Exception as e:
        logger.error("POST /chat 异常: {}", e)
        return Response.error(message=f"对话处理失败: {e}")


@router.post("/chat/stream", summary="流式对话（SSE）")
async def chat_stream(req: ChatRequest):
    """发送消息并以 SSE 流式返回 Agent 回复"""
    chat_service = _get_chat_service()

    async def event_generator():
        try:
            async for chunk in chat_service.process_message_stream(
                conversation_id=req.conversation_id,
                message=req.message,
                user_id=req.user_id,
            ):
                yield chunk
        except Exception as e:
            import json as _json
            logger.error("[chat_stream] 生成器异常: {}", e)
            yield f"event: error\ndata: {_json.dumps({'error': str(e)[:200]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ------------------------------------------------------------------
# 对话管理接口
# ------------------------------------------------------------------

@router.get("/conversations", summary="对话列表")
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Query("default"),
):
    """获取对话列表（分页）"""
    chat_service = _get_chat_service()
    try:
        items, total = await chat_service.store.get_conversations(
            user_id=user_id, page=page, page_size=page_size
        )
        conv_list = [
            ConversationInfo(
                id=item["id"], title=item.get("title", ""),
                created_at=item["created_at"], updated_at=item["updated_at"],
                status=item.get("status", "active"),
            ).model_dump()
            for item in items
        ]
        pages = (total + page_size - 1) // page_size if total > 0 else 0
        page_data = PageData(items=conv_list, total=total, page=page, page_size=page_size, pages=pages)
        return Response.success(data=page_data.model_dump())
    except Exception as e:
        logger.error("GET /conversations 异常: {}", e)
        return Response.error(message=f"获取对话列表失败: {e}")


@router.get("/conversations/{conversation_id}", summary="对话详情")
async def get_conversation(
    conversation_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
):
    """获取对话详情（含消息列表，支持分页）"""
    chat_service = _get_chat_service()
    try:
        conv = await chat_service.store.get_conversation(conversation_id)
        if not conv:
            return Response.error(message="对话不存在", code=404)

        skip = (page - 1) * page_size
        messages = await chat_service.store.get_messages(
            conversation_id, limit=page_size, skip=skip
        )
        total = await chat_service.store.count_messages(conversation_id)
        has_more = (page * page_size) < total

        detail = ConversationDetail(
            id=conv["id"], title=conv.get("title", ""),
            messages=messages, created_at=conv["created_at"], updated_at=conv["updated_at"],
            total=total, has_more=has_more, page=page, page_size=page_size,
        )
        return Response.success(data=detail.model_dump())
    except Exception as e:
        logger.error("GET /conversations/{} 异常: {}", conversation_id, e)
        return Response.error(message=f"获取对话详情失败: {e}")


@router.delete("/conversations/{conversation_id}", summary="删除对话")
async def delete_conversation(conversation_id: str):
    """删除对话（软删除）"""
    chat_service = _get_chat_service()
    try:
        conv = await chat_service.store.get_conversation(conversation_id)
        if not conv:
            return Response.error(message="对话不存在", code=404)
        await chat_service.store.delete_conversation(conversation_id)
        return Response.success(message="删除成功")
    except Exception as e:
        logger.error("DELETE /conversations/{} 异常: {}", conversation_id, e)
        return Response.error(message=f"删除对话失败: {e}")


@router.put("/conversations/{conversation_id}/title", summary="更新对话标题")
async def update_title(conversation_id: str, req: UpdateTitleRequest):
    """更新对话标题"""
    chat_service = _get_chat_service()
    try:
        conv = await chat_service.store.get_conversation(conversation_id)
        if not conv:
            return Response.error(message="对话不存在", code=404)
        await chat_service.store.update_title(conversation_id, req.title)
        return Response.success(message="更新成功")
    except Exception as e:
        logger.error("PUT /conversations/{}/title 异常: {}", conversation_id, e)
        return Response.error(message=f"更新标题失败: {e}")


# ------------------------------------------------------------------
# 写操作确认接口（M3 确认卡片协议）
# ------------------------------------------------------------------

@router.get("/confirmations/{token}", summary="查询确认记录状态")
async def get_confirmation(token: str):
    """按 token 查询确认记录（前端断连重开后重建卡片状态）"""
    from app.agent.core.confirmation import ConfirmationService
    try:
        record = await ConfirmationService.get_record(token)
        if not record:
            return Response.error(message="确认记录不存在", code=404)
        return Response.success(data=record)
    except Exception as e:
        logger.error("GET /confirmations/{} 异常: {}", token, e)
        return Response.error(message=f"查询确认记录失败: {e}")


@router.get("/conversations/{conversation_id}/confirmations", summary="会话确认记录列表")
async def list_confirmations(conversation_id: str, limit: int = Query(20, ge=1, le=50)):
    """查会话的确认记录（时间倒序，供历史消息重建终态卡片）"""
    from app.agent.core.confirmation import ConfirmationService
    try:
        items = await ConfirmationService.list_conversation_records(conversation_id, limit=limit)
        return Response.success(data={"items": items, "total": len(items)})
    except Exception as e:
        logger.error("GET /conversations/{}/confirmations 异常: {}", conversation_id, e)
        return Response.error(message=f"查询确认记录失败: {e}")


@router.post("/confirmations/{token}/decision", summary="提交确认决策")
async def submit_confirmation_decision(token: str, req: ConfirmationDecisionRequest):
    """用户对待确认写操作提交决策。

    - confirmed：执行工具真实逻辑（先过 M2 护栏），结果写回确认记录与会话历史
    - rejected：仅记录状态，会话存"操作已取消"消息
    决策是独立 HTTP 请求，不依赖 SSE 连接存活。
    """
    from app.agent.core.confirmation import ConfirmationService
    try:
        outcome = await ConfirmationService.resolve_decision(token, req.decision)
        if not outcome.get("ok") and "status" not in outcome:
            return Response.error(message=outcome.get("error", "决策处理失败"), code=400)
        return Response.success(data=outcome, message=outcome.get("error") or "决策已处理")
    except Exception as e:
        logger.error("POST /confirmations/{}/decision 异常: {}", token, e)
        return Response.error(message=f"决策处理失败: {e}")


# ------------------------------------------------------------------
# 记忆管理接口
# ------------------------------------------------------------------

def _format_memory(doc: dict) -> dict:
    """将 MongoDB 文档格式化为 API 返回格式"""
    return {
        "id": str(doc["_id"]),
        "category": doc.get("category", ""),
        "title": doc.get("title", ""),
        "content": doc.get("content", ""),
        "keywords": doc.get("keywords", []),
        "created_at": doc["created_at"].isoformat() if doc.get("created_at") else "",
        "updated_at": doc["updated_at"].isoformat() if doc.get("updated_at") else "",
    }


@router.get("/memories", summary="获取记忆列表")
async def list_memories(
    user_id: str = Query("default"),
    category: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """获取记忆列表，按 updated_at 倒序，支持分页"""
    try:
        filter_doc: dict = {"user_id": user_id}
        if category:
            filter_doc["category"] = category

        total = await _memory_store.collection.count_documents(filter_doc)
        cursor = (
            _memory_store.collection.find(filter_doc)
            .sort("updated_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )

        memories = []
        async for doc in cursor:
            memories.append(_format_memory(doc))

        return Response.success(data={"memories": memories, "total": total})
    except Exception as e:
        logger.error("GET /memories 异常: {}", e)
        return Response.error(message=f"获取记忆列表失败: {e}")


@router.delete("/memories/{memory_id}", summary="删除指定记忆")
async def delete_memory(memory_id: str, user_id: str = Query("default")):
    """删除指定记忆"""
    try:
        result = await _memory_store.delete(memory_id, user_id)
        if result.get("success"):
            return Response.success(data={"success": True})
        return Response.error(message=result.get("error", "删除失败"), code=404)
    except Exception as e:
        logger.error("DELETE /memories/{} 异常: {}", memory_id, e)
        return Response.error(message=f"删除记忆失败: {e}")


@router.post("/memories/search", summary="按关键词搜索记忆")
async def search_memories(req: MemorySearchRequest):
    """按关键词搜索记忆"""
    try:
        query = " ".join(req.keywords)
        if not query.strip():
            return Response.error(message="关键词不能为空")

        results = await _memory_store.search(user_id=req.user_id, query=query, limit=10)

        memories = [
            {
                "id": item["memory_id"],
                "category": item.get("category", ""),
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "keywords": item.get("keywords", []),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
            }
            for item in results
        ]
        return Response.success(data={"memories": memories, "total": len(memories)})
    except Exception as e:
        logger.error("POST /memories/search 异常: {}", e)
        return Response.error(message=f"搜索记忆失败: {e}")
