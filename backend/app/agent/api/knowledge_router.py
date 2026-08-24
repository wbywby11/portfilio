"""
知识库 REST API

前缀：/api/v1/knowledge
提供研究文档的 CRUD 和检索能力，供前端知识库管理页面调用。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel, Field

from app.agent.knowledge.knowledge_service import (
    KNOWLEDGE_CATEGORIES,
    KnowledgeService,
)
from app.schemas.response import Response

router = APIRouter()

# 模块级服务单例
_service: KnowledgeService | None = None


def _get_service() -> KnowledgeService:
    global _service
    if _service is None:
        _service = KnowledgeService()
    return _service


# ─── 文件解析工具 ─────────────────────────────────────────────────────────────

# 单文件解析上限（50MB）
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _extract_text(raw: bytes, suffix: str) -> str:
    """
    根据文件类型提取纯文本内容。

    Args:
        raw: 文件二进制内容
        suffix: 文件后缀（pdf/docx/txt）

    Returns:
        提取的文本内容
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("文件超过 50MB 上限")

    if suffix == "txt":
        # 尝试 UTF-8，回退 GBK
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("gbk", errors="replace")

    if suffix == "pdf":
        return _extract_pdf(raw)

    if suffix == "docx":
        return _extract_docx(raw)

    return ""


def _extract_pdf(raw: bytes) -> str:
    """PDF 文本提取（优先 pdfplumber，回退 PyPDF2）"""
    import io

    # 优先 pdfplumber（表格/布局更优）
    try:
        import pdfplumber

        pages_text = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
        if pages_text:
            return "\n\n".join(pages_text)
    except Exception as e:
        logger.debug("[知识库] pdfplumber 解析失败，回退 PyPDF2: {}", e)

    # 回退 PyPDF2
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        pages_text = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        return "\n\n".join(pages_text)
    except Exception as e:
        raise ValueError(f"PDF 解析失败: {e}")


def _extract_docx(raw: bytes) -> str:
    """Word (.docx) 文本提取"""
    import io

    try:
        from docx import Document

        doc = Document(io.BytesIO(raw))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

        # 也提取表格内容
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    paragraphs.append(" | ".join(cells))

        return "\n".join(paragraphs)
    except Exception as e:
        raise ValueError(f"DOCX 解析失败: {e}")


# ─── 请求模型 ────────────────────────────────────────────────────────────────


class KnowledgeCreateRequest(BaseModel):
    """新增知识文档"""
    title: str = Field(..., min_length=1, max_length=200, description="文档标题")
    content: str = Field(..., min_length=1, description="Markdown 全文")
    category: str = Field(default="research_report", description="分类")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    summary: str = Field(default="", max_length=200, description="摘要（空则自动生成）")
    source: str = Field(default="manual", description="来源标识")
    related_assets: list[str] = Field(default_factory=list, description="关联资产代码")


class KnowledgeUpdateRequest(BaseModel):
    """更新知识文档"""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content: Optional[str] = Field(default=None, min_length=1)
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    summary: Optional[str] = Field(default=None, max_length=200)
    related_assets: Optional[list[str]] = None


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.get("/categories", summary="获取知识库分类体系")
async def get_categories():
    """返回所有可用分类及中文名"""
    return Response.success(data=KNOWLEDGE_CATEGORIES)


@router.get("/documents", summary="检索知识文档列表")
async def list_documents(
    query: str = Query(default="", description="全文搜索关键词"),
    category: str = Query(default="", description="分类过滤"),
    asset_code: str = Query(default="", description="关联资产代码"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=50, description="每页条数"),
):
    """
    检索知识文档（分页）。

    支持全文关键词搜索 + 分类/资产代码过滤。
    """
    try:
        service = _get_service()
        skip = (page - 1) * page_size

        results = await service.store.search(
            query=query,
            category=category,
            asset_code=asset_code,
            limit=page_size,
            skip=skip,
        )
        total = await service.store.count(
            query=query, category=category, asset_code=asset_code
        )

        # 序列化 datetime
        for doc in results:
            if "updated_at" in doc:
                doc["updated_at"] = str(doc["updated_at"])
            if "created_at" in doc:
                doc["created_at"] = str(doc["created_at"])

        return Response.success(data={
            "items": results,
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    except Exception as e:
        logger.exception("[Knowledge] 检索失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_id}", summary="获取文档详情（含全文）")
async def get_document(doc_id: str):
    """按 ID 获取完整文档"""
    try:
        service = _get_service()
        result = await service.get_document(doc_id)
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["error"])

        doc = result["document"]
        # 序列化 datetime
        if "updated_at" in doc:
            doc["updated_at"] = str(doc["updated_at"])
        if "created_at" in doc:
            doc["created_at"] = str(doc["created_at"])

        return Response.success(data=doc)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Knowledge] 获取文档失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents", summary="新增知识文档")
async def create_document(req: KnowledgeCreateRequest):
    """新增知识文档（含校验和自动摘要）"""
    try:
        service = _get_service()
        result = await service.add_document(
            title=req.title,
            content=req.content,
            category=req.category,
            tags=req.tags,
            summary=req.summary,
            source=req.source,
            related_assets=req.related_assets,
        )
        if not result["success"]:
            return Response.error(message=result["error"], code=400)
        return Response.success(data=result, message="文档创建成功")
    except Exception as e:
        logger.exception("[Knowledge] 创建文档失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/upload", summary="上传文件自动录入")
async def upload_document(
    file: UploadFile = File(..., description="支持 PDF/DOCX/TXT 文件"),
    category: str = Form(default="research_report", description="分类"),
    tags: str = Form(default="", description="标签，逗号分隔"),
    related_assets: str = Form(default="", description="关联资产代码，逗号分隔"),
):
    """
    上传文件自动解析并录入知识库。

    支持格式：.pdf / .docx / .txt
    自动提取文本内容，文件名作为标题。
    """
    # 校验文件类型
    filename = file.filename or ""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = {"pdf", "docx", "txt"}
    if suffix not in allowed:
        return Response.error(
            message=f"不支持的文件格式 '.{suffix}'，仅支持 PDF/DOCX/TXT",
            code=400,
        )

    try:
        raw = await file.read()
        content = _extract_text(raw, suffix)
        if not content or not content.strip():
            return Response.error(message="文件解析后内容为空，请检查文件是否有效", code=400)

        # 文件名去后缀作为标题
        title = filename.rsplit(".", 1)[0] if "." in filename else filename

        # 解析可选参数
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        asset_list = [a.strip() for a in related_assets.split(",") if a.strip()] if related_assets else []

        service = _get_service()
        result = await service.add_document(
            title=title,
            content=content,
            category=category,
            tags=tag_list,
            source="imported",
            related_assets=asset_list,
        )
        if not result["success"]:
            return Response.error(message=result["error"], code=400)

        logger.info("[知识库] 文件上传录入成功: {} → id={}", filename, result["id"])
        return Response.success(
            data={**result, "filename": filename, "chars": len(content)},
            message=f"文件 '{filename}' 录入成功（提取 {len(content)} 字符）",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[知识库] 文件上传失败: {}", e)
        raise HTTPException(status_code=500, detail=f"文件解析失败: {str(e)}")


@router.put("/documents/{doc_id}", summary="更新知识文档")
async def update_document(doc_id: str, req: KnowledgeUpdateRequest):
    """更新文档字段（仅传入的字段会被更新）"""
    try:
        service = _get_service()
        updates = req.model_dump(exclude_none=True)
        if not updates:
            return Response.error(message="无有效更新字段", code=400)

        result = await service.update_document(doc_id, updates)
        if not result["success"]:
            return Response.error(message=result["error"], code=404)
        return Response.success(data=result, message="文档更新成功")
    except Exception as e:
        logger.exception("[Knowledge] 更新文档失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{doc_id}", summary="删除知识文档")
async def delete_document(doc_id: str):
    """删除指定文档"""
    try:
        service = _get_service()
        result = await service.delete_document(doc_id)
        if not result["success"]:
            return Response.error(message=result["error"], code=404)
        return Response.success(message="文档已删除")
    except Exception as e:
        logger.exception("[Knowledge] 删除文档失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", summary="知识库统计")
async def get_stats():
    """获取知识库文档总数和分类统计"""
    try:
        service = _get_service()
        total = await service.store.count()

        # 按分类统计
        category_stats = {}
        for cat_key, cat_label in KNOWLEDGE_CATEGORIES.items():
            count = await service.store.count(category=cat_key)
            category_stats[cat_key] = {"label": cat_label, "count": count}

        return Response.success(data={
            "total": total,
            "categories": category_stats,
        })
    except Exception as e:
        logger.exception("[Knowledge] 统计失败: {}", e)
        raise HTTPException(status_code=500, detail=str(e))
