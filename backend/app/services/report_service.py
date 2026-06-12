"""
报告服务层

提供报告模板管理、章节填充、草稿生成、合规审查、导出及知识库检索功能。
"""
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from loguru import logger

from app.config.database import Database
from app.services.template_service import _deep_json_safe
from app.models.report_model import (
    KnowledgeDocument,
    Report,
    ReportSection,
    ReportStatus,
    ReportTemplateType,
)

# 模板目录路径（基于本文件位置定位）
TEMPLATE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "agent", "templates", "reports"
)

# 模板文件名映射
_TEMPLATE_FILES: Dict[str, str] = {
    ReportTemplateType.PERIODIC.value: "periodic_report.md",
    ReportTemplateType.DUE_DILIGENCE.value: "due_diligence.md",
    ReportTemplateType.INVESTMENT_DECISION.value: "investment_decision.md",
    ReportTemplateType.PRODUCT_REVIEW.value: "product_review.md",
    ReportTemplateType.COMPLIANCE.value: "compliance_report.md",
}

# 合规敏感关键词（中文金融合规场景）
_SENSITIVE_KEYWORDS: List[str] = [
    "内幕", "未公开", "保证收益", "保本", "稳赚", "零风险",
    "高息揽储", "资金池", "刚性兑付", "隐性担保", "抽屉协议",
]


class ReportService:
    """报告服务"""

    def __init__(self) -> None:
        self._db = None
        self._jinja_env_cached = None

    def _get_jinja_env(self):
        """延迟加载 Jinja2，避免未安装 jinja2 时无法启动 main（报告/草稿功能需 pip install jinja2）。"""
        if self._jinja_env_cached is None:
            import jinja2

            self._jinja_env_cached = jinja2.Environment(
                loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
                autoescape=False,
            )
        return self._jinja_env_cached

    def _get_db(self):
        """懒加载获取数据库实例"""
        if self._db is None:
            self._db = Database.get_database()
        if self._db is None:
            raise RuntimeError(
                "MongoDB 未初始化：请确认应用已启动且 MONGODB_URL 配置正确"
            )
        return self._db

    # ── 模板管理 ──────────────────────────────────────────

    def get_template(self, template_type: str) -> Dict[str, Any]:
        """获取报告模板内容与元数据

        Args:
            template_type: 模板类型，如 periodic / due_diligence 等

        Returns:
            包含模板内容、类型、章节的字典
        """
        if template_type not in _TEMPLATE_FILES:
            valid_types = ", ".join(_TEMPLATE_FILES.keys())
            logger.warning(
                "report_template_type_invalid",
                extra={"template_type": template_type, "valid_types": valid_types},
            )
            return {
                "success": False,
                "error": f"无效模板类型: {template_type}，可选: {valid_types}",
            }

        filename = _TEMPLATE_FILES[template_type]
        filepath = os.path.join(TEMPLATE_DIR, filename)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            logger.error(
                "report_template_not_found",
                extra={"filename": filename, "path": filepath},
            )
            return {
                "success": False,
                "error": f"模板文件不存在: {filename}",
            }
        except OSError as e:
            logger.error(
                "report_template_read_error",
                extra={"filename": filename, "error": str(e)},
            )
            return {
                "success": False,
                "error": f"模板读取失败: {e}",
            }

        # 从模板内容提取章节标题（一级 / 二级标题）
        sections = self._extract_sections_from_template(content)

        logger.info(
            "report_template_loaded",
            extra={"template_type": template_type, "sections_count": len(sections)},
        )

        return {
            "success": True,
            "template_type": template_type,
            "filename": filename,
            "content": content,
            "sections": sections,
        }

    def _extract_sections_from_template(self, content: str) -> List[Dict[str, Any]]:
        """从 Markdown 模板内容中提取章节结构"""
        sections: List[Dict[str, Any]] = []
        order = 0
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                title = stripped.replace("## ", "").strip()
                sections.append({
                    "name": title,
                    "title": title,
                    "order": order,
                    "is_required": True,
                })
                order += 1
            elif stripped.startswith("### "):
                title = stripped.replace("### ", "").strip()
                sections.append({
                    "name": title,
                    "title": title,
                    "order": order,
                    "is_required": False,
                })
                order += 1
        return sections

    # ── 章节填充 ──────────────────────────────────────────

    async def fill_section(
        self, template_id: str, section_name: str, content: str
    ) -> Dict[str, Any]:
        """填充报告章节内容到数据库

        Args:
            template_id: 模板/报告标识
            section_name: 章节名称
            content: 章节内容

        Returns:
            操作结果字典
        """
        db = self._get_db()
        collection = db["reports"]

        # 查找或创建报告文档
        report_doc = await collection.find_one({"template_id": template_id})

        if report_doc is None:
            # 新建报告文档
            report_id = str(uuid.uuid4())
            new_report = {
                "report_id": report_id,
                "template_id": template_id,
                "template_type": "unknown",
                "title": template_id,
                "status": ReportStatus.DRAFT.value,
                "sections": [
                    {
                        "name": section_name,
                        "title": section_name,
                        "content": content,
                        "order": 0,
                        "is_required": True,
                    }
                ],
                "data_context": {},
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "created_by": "system",
            }
            result = await collection.insert_one(new_report)
            logger.info(
                "report_section_created",
                extra={
                    "template_id": template_id,
                    "section_name": section_name,
                    "report_id": report_id,
                },
            )
            return {
                "success": True,
                "report_id": report_id,
                "action": "created",
                "section": section_name,
            }

        # 更新已有章节或追加新章节
        sections = report_doc.get("sections", [])
        found = False
        for sec in sections:
            if sec.get("name") == section_name:
                sec["content"] = content
                found = True
                break

        if not found:
            sections.append({
                "name": section_name,
                "title": section_name,
                "content": content,
                "order": len(sections),
                "is_required": True,
            })

        await collection.update_one(
            {"template_id": template_id},
            {
                "$set": {
                    "sections": sections,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(
            "report_section_filled",
            extra={
                "template_id": template_id,
                "section_name": section_name,
                "action": "updated" if found else "appended",
            },
        )

        return {
            "success": True,
            "report_id": report_doc.get("report_id", ""),
            "action": "updated" if found else "appended",
            "section": section_name,
        }

    # ── 草稿生成 ──────────────────────────────────────────

    async def generate_draft(
        self, template_id: str, data_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用 Jinja2 渲染模板生成报告初稿

        Args:
            template_id: 模板标识（对应模板类型，如 periodic）
            data_context: 填充数据上下文

        Returns:
            包含渲染后文本及元数据的字典
        """
        template_type = data_context.get("template_type", template_id)
        template_result = self.get_template(template_type)

        if not template_result.get("success"):
            return template_result

        template_content = template_result["content"]

        import jinja2

        try:
            jinja_template = self._get_jinja_env().from_string(template_content)
            rendered = jinja_template.render(**data_context)
        except jinja2.TemplateError as e:
            logger.error(
                "report_draft_render_error",
                extra={"template_type": template_type, "error": str(e)},
            )
            return {
                "success": False,
                "error": f"模板渲染失败: {e}",
            }

        # 保存到数据库
        db = self._get_db()
        collection = db["reports"]
        report_id = str(uuid.uuid4())

        report_doc = {
            "report_id": report_id,
            "template_id": template_id,
            "template_type": template_type,
            "title": data_context.get("report_title", f"{template_type}_draft"),
            "status": ReportStatus.DRAFT.value,
            "sections": [],
            "data_context": data_context,
            "rendered_content": rendered,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "system",
        }

        await collection.insert_one(report_doc)

        logger.info(
            "report_draft_generated",
            extra={
                "template_type": template_type,
                "report_id": report_id,
                "content_length": len(rendered),
            },
        )

        return {
            "success": True,
            "report_id": report_id,
            "template_type": template_type,
            "rendered_content": rendered,
            "content_length": len(rendered),
        }

    # ── 合规审查 ──────────────────────────────────────────

    async def review_compliance(self, report_id: str) -> Dict[str, Any]:
        """审查报告合规性

        检查项：
        1. 敏感关键词
        2. 必填章节是否已填充
        3. 内容长度合理性

        Args:
            report_id: 报告业务 ID

        Returns:
            合规审查结果字典
        """
        db = self._get_db()
        collection = db["reports"]

        report_doc = await collection.find_one({"report_id": report_id})
        if report_doc is None:
            logger.warning(
                "report_compliance_report_not_found",
                extra={"report_id": report_id},
            )
            return {
                "success": False,
                "error": f"报告不存在: {report_id}",
            }

        content = report_doc.get("rendered_content", "")
        sections = report_doc.get("sections", [])

        issues: List[Dict[str, Any]] = []
        score = 100

        # 1. 敏感关键词检查
        found_sensitive = []
        text_lower = content.lower()
        for keyword in _SENSITIVE_KEYWORDS:
            if keyword in text_lower:
                found_sensitive.append(keyword)

        if found_sensitive:
            issues.append({
                "type": "sensitive_keyword",
                "level": "high",
                "message": f"发现敏感关键词: {', '.join(found_sensitive)}",
                "details": found_sensitive,
            })
            score -= len(found_sensitive) * 15

        # 2. 必填章节检查
        empty_required = []
        for sec in sections:
            if sec.get("is_required") and not sec.get("content", "").strip():
                empty_required.append(sec.get("name", ""))

        if empty_required:
            issues.append({
                "type": "missing_required_section",
                "level": "medium",
                "message": f"以下必填章节未填充: {', '.join(empty_required)}",
                "details": empty_required,
            })
            score -= len(empty_required) * 10

        # 3. 内容长度检查（若内容过短视为异常）
        if len(content) < 200:
            issues.append({
                "type": "content_too_short",
                "level": "low",
                "message": f"报告内容过短（{len(content)} 字符），请补充内容",
                "details": {"current_length": len(content), "expected_min": 200},
            })
            score -= 10

        score = max(0, score)
        passed = score >= 80 and not any(i["level"] == "high" for i in issues)

        compliance_result = {
            "passed": passed,
            "score": score,
            "issues": issues,
            "checked_at": datetime.utcnow().isoformat(),
        }

        # 更新报告状态
        new_status = ReportStatus.APPROVED.value if passed else ReportStatus.UNDER_REVIEW.value
        await collection.update_one(
            {"report_id": report_id},
            {
                "$set": {
                    "compliance_check": compliance_result,
                    "status": new_status,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(
            "report_compliance_reviewed",
            extra={
                "report_id": report_id,
                "passed": passed,
                "score": score,
                "issues_count": len(issues),
            },
        )

        return {
            "success": True,
            "report_id": report_id,
            "passed": passed,
            "score": score,
            "issues": issues,
            "status": new_status,
        }

    # ── 导出报告 ──────────────────────────────────────────

    async def export_report(
        self, report_id: str, format: str = "docx"
    ) -> Dict[str, Any]:
        """导出报告

        当前实现：返回 Markdown 或简单 HTML 文本。
        后续可扩展为生成 python-docx / PDF。

        Args:
            report_id: 报告业务 ID
            format: 导出格式，默认 docx（当前降级为 markdown）

        Returns:
            包含导出内容的字典
        """
        db = self._get_db()
        collection = db["reports"]

        report_doc = await collection.find_one({"report_id": report_id})
        if report_doc is None:
            logger.warning(
                "report_export_report_not_found",
                extra={"report_id": report_id},
            )
            return {
                "success": False,
                "error": f"报告不存在: {report_id}",
            }

        content = report_doc.get("rendered_content", "")
        if not content:
            # 尝试从章节拼接
            sections = report_doc.get("sections", [])
            lines = []
            for sec in sorted(sections, key=lambda s: s.get("order", 0)):
                lines.append(f"## {sec.get('title', sec.get('name', ''))}")
                lines.append("")
                lines.append(sec.get("content", ""))
                lines.append("")
            content = "\n".join(lines)

        export_format = format.lower()
        if export_format in ("html", "pdf"):
            # 简单 Markdown 转 HTML
            html_body = self._markdown_to_html(content)
            exported_content = html_body
            mime_type = "text/html"
        else:
            # 默认返回 Markdown
            exported_content = content
            mime_type = "text/markdown"

        logger.info(
            "report_exported",
            extra={
                "report_id": report_id,
                "format": export_format,
                "mime_type": mime_type,
                "content_length": len(exported_content),
            },
        )

        return {
            "success": True,
            "report_id": report_id,
            "format": export_format,
            "mime_type": mime_type,
            "content": exported_content,
            "title": report_doc.get("title", ""),
        }

    def _markdown_to_html(self, markdown_text: str) -> str:
        """简易 Markdown 转 HTML（仅处理标题和换行）"""
        lines = markdown_text.splitlines()
        html_lines: List[str] = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>Report Export</title>",
            "</head>",
            "<body>",
        ]
        in_paragraph = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# "):
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
                text = stripped[2:]
                html_lines.append(f"<h1>{self._escape_html(text)}</h1>")
            elif stripped.startswith("## "):
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
                text = stripped[3:]
                html_lines.append(f"<h2>{self._escape_html(text)}</h2>")
            elif stripped.startswith("### "):
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
                text = stripped[4:]
                html_lines.append(f"<h3>{self._escape_html(text)}</h3>")
            elif stripped == "":
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
            elif stripped.startswith("---"):
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
                html_lines.append("<hr>")
            else:
                if not in_paragraph:
                    html_lines.append("<p>")
                    in_paragraph = True
                html_lines.append(self._escape_html(stripped) + "<br>")

        if in_paragraph:
            html_lines.append("</p>")

        html_lines.extend(["</body>", "</html>"])
        return "\n".join(html_lines)

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    # ── 知识库检索 ────────────────────────────────────────

    async def search_knowledge(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """从 research_knowledge 集合检索知识文档

        支持基于关键词的文本搜索，优先匹配标题、内容和关键词字段。

        Args:
            query: 检索关键词
            category: 可选分类筛选
            limit: 返回结果上限

        Returns:
            匹配的知识文档列表
        """
        db = self._get_db()
        collection = db["research_knowledge"]

        # 构建查询条件：在 title / content / keywords 中做模糊匹配
        keywords = [w.strip() for w in query.split() if w.strip()]
        if not keywords:
            return []

        or_conditions = []
        for kw in keywords:
            pattern = f".*{kw}.*"
            or_conditions.extend([
                {"title": {"$regex": pattern, "$options": "i"}},
                {"content": {"$regex": pattern, "$options": "i"}},
                {"keywords": {"$regex": pattern, "$options": "i"}},
            ])

        filter_spec: Dict[str, Any] = {"$or": or_conditions}
        if category:
            filter_spec["category"] = category

        try:
            cursor = collection.find(filter_spec).limit(limit)
            docs = await cursor.to_list(length=limit)
        except Exception as e:
            logger.error(
                "knowledge_search_error",
                extra={"query": query, "category": category, "error": str(e)},
            )
            return []

        results: List[Dict[str, Any]] = []
        for doc in docs:
            doc_id = str(doc.get("_id", ""))
            results.append({
                "doc_id": doc.get("doc_id", doc_id),
                "title": doc.get("title", ""),
                "content": doc.get("content", "")[:500],
                "category": doc.get("category", "general"),
                "subcategory": doc.get("subcategory"),
                "keywords": doc.get("keywords", []),
                "source": doc.get("source"),
                "author": doc.get("author"),
            })

        logger.info(
            "knowledge_searched",
            extra={
                "query": query,
                "category": category,
                "limit": limit,
                "results_count": len(results),
            },
        )

        return results

    # ── 报告查询与管理 ──────────────────────────────────────

    async def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """获取单个报告详情

        Args:
            report_id: 报告业务 ID

        Returns:
            报告文档字典，不存在则返回 None
        """
        db = self._get_db()
        collection = db["reports"]
        report_doc = await collection.find_one({"report_id": report_id})
        if report_doc is None:
            logger.warning(
                "report_get_not_found",
                extra={"report_id": report_id},
            )
            return None
        return _deep_json_safe(report_doc)

    async def list_reports(
        self,
        template_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        """获取报告列表（分页+筛选）

        Args:
            template_type: 可选模板类型筛选
            status: 可选状态筛选
            page: 页码，从 1 开始
            page_size: 每页条数

        Returns:
            (报告列表, 总数) 元组
        """
        db = self._get_db()
        collection = db["reports"]

        # 构建筛选条件
        filter_spec: Dict[str, Any] = {}
        if template_type is not None:
            filter_spec["template_type"] = template_type
        if status is not None:
            filter_spec["status"] = status

        total = await collection.count_documents(filter_spec)

        skip = (page - 1) * page_size
        cursor = (
            collection.find(filter_spec)
            .sort("created_at", -1)
            .skip(skip)
            .limit(page_size)
        )
        docs = await cursor.to_list(length=page_size)

        items: list[dict] = [_deep_json_safe(doc) for doc in docs]

        logger.info(
            "report_list_fetched",
            extra={
                "template_type": template_type,
                "status": status,
                "page": page,
                "page_size": page_size,
                "total": total,
                "returned": len(items),
            },
        )

        return items, total

    async def delete_report(self, report_id: str) -> bool:
        """删除报告

        Args:
            report_id: 报告业务 ID

        Returns:
            是否删除成功
        """
        db = self._get_db()
        collection = db["reports"]
        result = await collection.delete_one({"report_id": report_id})
        deleted = result.deleted_count > 0

        if deleted:
            logger.info(
                "report_deleted",
                extra={"report_id": report_id},
            )
        else:
            logger.warning(
                "report_delete_not_found",
                extra={"report_id": report_id},
            )

        return deleted
