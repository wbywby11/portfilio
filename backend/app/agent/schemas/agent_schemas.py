"""
Agent 相关 Pydantic 数据模型
"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """对话请求"""
    conversation_id: Optional[str] = None
    message: str
    scene: Optional[str] = None  # 业务场景标识，如 asset_research / credit_rating / data_analysis / report_writing
    user_id: str = "default"  # 用户标识，用于多用户隔离
    system_turn_addon: Optional[str] = None  # 仅当轮拼入系统提示末尾，不入库用户消息
    attachments: Optional[List[str]] = Field(
        default=None,
        description="附件ID列表，通过 /upload-attachment 上传获得"
    )

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("消息内容不能为空")
        if len(v) > 10000:
            raise ValueError("消息内容不能超过 10000 个字符")
        return v

    @field_validator("system_turn_addon")
    @classmethod
    def optional_turn_addon(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 28000:
            raise ValueError("本轮补充指令不能超过 28000 个字符")
        return v


class AgentReply(BaseModel):
    """Agent 回复"""
    conversation_id: str
    content: str
    tool_calls: list[dict] = Field(default_factory=list)


class ConversationInfo(BaseModel):
    """对话摘要信息"""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    status: str = "active"


class ConversationDetail(BaseModel):
    """对话详情（含消息列表，支持分页）"""
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
