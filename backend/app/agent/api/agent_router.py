"""
AI Agent API 路由
"""
from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from app.agent.schemas.agent_schemas import (
    AgentReply,
    ChatRequest,
    ConversationDetail,
    ConversationInfo,
    UpdateTitleRequest,
)
from app.agent.services.chat_service import ChatService
from app.agent.services.attachment_service import AttachmentService, ALLOWED_EXTENSIONS, MAX_FILE_SIZE
from app.agent.memory.memory_store import MemoryStore
from app.schemas.response import Response, PageData
from app.services.report_service import ReportService
from app.services.template_service import TemplateService

router = APIRouter()

# MemoryStore 为无状态查询层，保留全局单例
_memory_store = MemoryStore()

# ReportService 为无状态服务，保留全局单例
_report_service = ReportService()


def _get_chat_service() -> ChatService:
    """为每个请求创建独立的 ChatService 实例，确保多用户并发隔离"""
    return ChatService()


# ------------------------------------------------------------------
# 请求模型
# ------------------------------------------------------------------
class MemorySearchRequest(BaseModel):
    """记忆搜索请求"""
    keywords: list[str]
    user_id: str = "default"


# ------------------------------------------------------------------
# 对话接口
# ------------------------------------------------------------------
@router.post("/chat", summary="非流式对话")
async def chat(req: ChatRequest):
    """发送消息并获取 Agent 完整回复"""
    chat_service = _get_chat_service()
    try:
        reply: AgentReply = await chat_service.process_message(
            conversation_id=req.conversation_id,
            message=req.message,
            user_id=req.user_id,
            scene=req.scene,
            system_turn_addon=req.system_turn_addon,
            attachments=req.attachments,
        )
        return Response.success(data=reply.model_dump())
    except Exception as e:
        logger.error("POST /chat 异常: {}", e)
        return Response.error(message=f"对话处理失败: {e}")


@router.post("/chat/stream", summary="流式对话（SSE）")
async def chat_stream(req: ChatRequest):
    """发送消息并以 SSE 流式返回 Agent 回复"""
    chat_service = _get_chat_service()

    async def event_generator():
        import time as _time
        try:
            last_yield_time = _time.time()
            async for chunk in chat_service.process_message_stream(
                conversation_id=req.conversation_id,
                message=req.message,
                user_id=req.user_id,
                scene=req.scene,
                system_turn_addon=req.system_turn_addon,
                attachments=req.attachments,
            ):
                yield chunk
                last_yield_time = _time.time()
        except Exception as e:
            import json as _json
            logger.error("[chat_stream] 生成器异常: {}", e)
            yield f"event: error\ndata: {_json.dumps({'error': str(e)[:200]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ------------------------------------------------------------------
# 文件上传接口
# ------------------------------------------------------------------
@router.post("/upload-attachment", summary="上传对话附件")
async def upload_attachment(file: UploadFile = File(...)):
    """
    上传Excel/CSV文件用于数据导入

    - 限制：50MB，仅 .xlsx/.xls/.csv
    - 返回附件ID和文件预览
    """
    from pathlib import Path as _Path

    # 1. 校验文件名后缀
    file_name = file.filename or "unknown"
    ext = _Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，仅支持 {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # 2. 读取文件内容
    content = await file.read()

    # 3. 校验大小
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件大小 {len(content) / 1024 / 1024:.1f}MB 超过限制 {MAX_FILE_SIZE / 1024 / 1024:.0f}MB"
        )

    # 4. 调用 AttachmentService.save_file()
    try:
        result = await AttachmentService.save_file(file_name, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OverflowError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        logger.error("POST /upload-attachment 异常: {}", e)
        raise HTTPException(status_code=500, detail=f"文件上传失败: {e}")

    # 5. 返回结果
    return {"code": 200, "message": "success", "data": result}


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
        # 转换为 ConversationInfo
        conv_list = []
        for item in items:
            conv_list.append(
                ConversationInfo(
                    id=item["id"],
                    title=item.get("title", ""),
                    created_at=item["created_at"],
                    updated_at=item["updated_at"],
                    status=item.get("status", "active"),
                ).model_dump()
            )
        pages = (total + page_size - 1) // page_size if total > 0 else 0
        page_data = PageData(
            items=conv_list,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )
        return Response.success(data=page_data.model_dump())
    except Exception as e:
        logger.error("GET /conversations 异常: {}", e)
        return Response.error(message=f"获取对话列表失败: {e}")


@router.get("/conversations/{conversation_id}", summary="对话详情")
async def get_conversation(
    conversation_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=50, description="每页消息数"),
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
            id=conv["id"],
            title=conv.get("title", ""),
            messages=messages,
            created_at=conv["created_at"],
            updated_at=conv["updated_at"],
            total=total,
            has_more=has_more,
            page=page,
            page_size=page_size,
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
        "created_at": (
            doc["created_at"].isoformat() if doc.get("created_at") else ""
        ),
        "updated_at": (
            doc["updated_at"].isoformat() if doc.get("updated_at") else ""
        ),
    }


@router.get("/memories", summary="获取记忆列表")
async def list_memories(
    user_id: str = Query("default"),
    category: str = Query(None),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
):
    """获取记忆列表，按 updated_at 倒序，支持分页"""
    try:
        filter_doc: dict = {"user_id": user_id}
        if category:
            filter_doc["category"] = category

        # 获取总数
        total = await _memory_store.collection.count_documents(filter_doc)

        # 分页查询
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
        # 将关键词列表拼接为空格分隔的查询字符串，复用 MemoryStore.search
        query = " ".join(req.keywords)
        if not query.strip():
            return Response.error(message="关键词不能为空")

        results = await _memory_store.search(
            user_id=req.user_id,
            query=query,
            limit=10,
        )

        # search 返回的字段名为 memory_id，统一转为 id
        memories = []
        for item in results:
            memories.append({
                "id": item["memory_id"],
                "category": item.get("category", ""),
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "keywords": item.get("keywords", []),
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
            })

        return Response.success(data={"memories": memories, "total": len(memories)})
    except Exception as e:
        logger.error("POST /memories/search 异常: {}", e)
        return Response.error(message=f"搜索记忆失败: {e}")


# ------------------------------------------------------------------
# 报告管理接口
# ------------------------------------------------------------------
@router.get("/reports", summary="报告列表")
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    template_type: str | None = Query(None),
    status: str | None = Query(None),
):
    """获取报告列表（分页+筛选）"""
    try:
        items, total = await _report_service.list_reports(
            template_type=template_type, status=status,
            page=page, page_size=page_size,
        )
        pages = (total + page_size - 1) // page_size if total > 0 else 0
        page_data = PageData(items=items, total=total, page=page, page_size=page_size, pages=pages)
        return Response.success(data=page_data.model_dump())
    except Exception as e:
        logger.error("GET /reports 异常: {}", e)
        return Response.error(message=f"获取报告列表失败: {e}")


@router.get("/reports/{report_id}", summary="报告详情")
async def get_report_detail(report_id: str):
    """获取报告详情"""
    try:
        report = await _report_service.get_report(report_id)
        if not report:
            return Response.error(message="报告不存在")
        if "_id" in report:
            report["_id"] = str(report["_id"])
        for key in ("created_at", "updated_at"):
            if key in report and hasattr(report.get(key), "isoformat"):
                report[key] = report[key].isoformat()
        return Response.success(data=report)
    except Exception as e:
        logger.error("GET /reports/{} 异常: {}", report_id, e)
        return Response.error(message=f"获取报告详情失败: {e}")


@router.delete("/reports/{report_id}", summary="删除报告")
async def delete_report(report_id: str):
    """删除报告"""
    try:
        deleted = await _report_service.delete_report(report_id)
        if not deleted:
            return Response.error(message="报告不存在或已删除")
        return Response.success(data={"report_id": report_id})
    except Exception as e:
        logger.error("DELETE /reports/{} 异常: {}", report_id, e)
        return Response.error(message=f"删除报告失败: {e}")


@router.get("/reports/{report_id}/export", summary="导出报告")
async def export_report_api(report_id: str):
    """导出报告（Markdown 格式）"""
    try:
        result = await _report_service.export_report(report_id, "markdown")
        return Response.success(data=result)
    except Exception as e:
        logger.error("GET /reports/{}/export 异常: {}", report_id, e)
        return Response.error(message=f"导出报告失败: {e}")


# TemplateService 为无状态服务，保留全局单例
_template_service = TemplateService()


# ------------------------------------------------------------------
# 分析模板管理接口
# ------------------------------------------------------------------
@router.get("/analysis-templates", summary="分析模板列表")
async def list_analysis_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    status: str | None = Query(None),
):
    """获取分析模板列表（分页+筛选）"""
    try:
        items, total = await _template_service.list_templates(
            category=category, status=status,
            page=page, page_size=page_size,
        )
        pages = (total + page_size - 1) // page_size if total > 0 else 0
        page_data = PageData(items=items, total=total, page=page, page_size=page_size, pages=pages)
        return Response.success(data=page_data.model_dump())
    except Exception as e:
        logger.error("GET /analysis-templates 异常: {}", e)
        return Response.error(message=f"获取模板列表失败: {e}")


@router.post("/analysis-templates", summary="创建分析模板")
async def create_analysis_template(req: dict):
    """创建新的分析模板"""
    try:
        result = await _template_service.create_template(req)
        return Response.success(data=result)
    except Exception as e:
        logger.error("POST /analysis-templates 异常: {}", e)
        return Response.error(message=f"创建模板失败: {e}")


@router.get("/analysis-templates/{template_id}", summary="分析模板详情")
async def get_analysis_template(template_id: str):
    """获取分析模板详情"""
    try:
        template = await _template_service.get_template(template_id)
        if not template:
            return Response.error(message="模板不存在")
        return Response.success(data=template)
    except Exception as e:
        logger.error("GET /analysis-templates/{} 异常: {}", template_id, e)
        return Response.error(message=f"获取模板详情失败: {e}")


@router.put("/analysis-templates/{template_id}", summary="更新分析模板")
async def update_analysis_template(template_id: str, req: dict):
    """更新分析模板"""
    try:
        updated = await _template_service.update_template(template_id, req)
        if not updated:
            return Response.error(message="模板不存在或未修改")
        return Response.success(data={"template_id": template_id})
    except Exception as e:
        logger.error("PUT /analysis-templates/{} 异常: {}", template_id, e)
        return Response.error(message=f"更新模板失败: {e}")


@router.delete("/analysis-templates/{template_id}", summary="删除分析模板")
async def delete_analysis_template(template_id: str):
    """删除分析模板"""
    try:
        deleted = await _template_service.delete_template(template_id)
        if not deleted:
            return Response.error(message="模板不存在或已删除")
        return Response.success(data={"template_id": template_id})
    except Exception as e:
        logger.error("DELETE /analysis-templates/{} 异常: {}", template_id, e)
        return Response.error(message=f"删除模板失败: {e}")


@router.post("/analysis-templates/{template_id}/execute", summary="执行分析模板")
async def execute_analysis_template(template_id: str, req: dict):
    """执行分析模板，传入参数，返回分析结果"""
    try:
        user_params = req.get("params", {})
        result = await _template_service.execute_template(template_id, user_params)
        return Response.success(data=result)
    except ValueError as e:
        logger.warning("执行模板参数错误: {}", e)
        return Response.error(message=str(e))
    except Exception as e:
        logger.error("POST /analysis-templates/{}/execute 异常: {}", template_id, e)
        return Response.error(message=f"执行模板失败: {e}")
