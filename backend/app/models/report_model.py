"""
报告与知识库数据模型

用于报告写作工具集的数据结构定义，包含报告模板、报告实例和知识库文档模型。
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ReportTemplateType(str, Enum):
    """报告模板类型"""
    PERIODIC = "periodic"
    DUE_DILIGENCE = "due_diligence"
    INVESTMENT_DECISION = "investment_decision"
    PRODUCT_REVIEW = "product_review"
    COMPLIANCE = "compliance"


class ReportStatus(str, Enum):
    """报告状态"""
    DRAFT = "draft"
    FILLED = "filled"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReportSection(BaseModel):
    """报告章节"""
    name: str = Field(..., description="章节名称")
    title: str = Field(..., description="章节标题")
    content: str = Field(default="", description="章节内容")
    order: int = Field(default=0, description="排序序号")
    is_required: bool = Field(default=True, description="是否必填")

    class Config:
        populate_by_name = True


class Report(BaseModel):
    """报告实例模型

    存入 MongoDB reports 集合
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")
    report_id: str = Field(..., description="业务报告 ID（UUID）")
    template_type: ReportTemplateType = Field(..., description="模板类型")
    template_id: str = Field(..., description="模板标识")
    title: str = Field(..., description="报告标题")
    status: ReportStatus = Field(default=ReportStatus.DRAFT, description="报告状态")
    sections: List[ReportSection] = Field(default_factory=list, description="章节列表")
    data_context: Dict[str, Any] = Field(default_factory=dict, description="填充数据上下文")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
    created_by: str = Field(default="system", description="创建者")
    compliance_check: Optional[Dict[str, Any]] = Field(None, description="合规检查结果")

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class KnowledgeDocument(BaseModel):
    """知识库文档模型

    存入 MongoDB research_knowledge 集合
    """
    id: Optional[str] = Field(None, alias="_id", description="MongoDB 文档 ID")
    doc_id: str = Field(..., description="文档业务 ID")
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档内容")
    category: str = Field(default="general", description="分类")
    subcategory: Optional[str] = Field(None, description="子分类")
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    source: Optional[str] = Field(None, description="来源")
    author: Optional[str] = Field(None, description="作者")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
    relevance_score: Optional[float] = Field(None, description="相关性评分")

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
