# -*- coding: utf-8 -*-
"""
AI Agent 对话数据模型

对应集合:
- agent_conversations: 会话元数据
- agent_messages: 消息记录
- agent_tool_results: 工具完整结果（大结果独立存储，30 天 TTL）

写入来源: Agent 运行时自动写入（conversation_store.py）
被消费方: Agent 对话管理、前端消息展示
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentConversation(BaseModel):
    """会话 (agent_conversations 集合)"""
    id: Optional[str] = Field(None, alias="_id")
    user_id: str = Field(..., description="用户 ID")
    title: str = Field("新对话", description="会话标题")
    status: str = Field("active", description="会话状态: active / deleted")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        populate_by_name = True


class AgentMessage(BaseModel):
    """消息 (agent_messages 集合)"""
    id: Optional[str] = Field(None, alias="_id")
    conversation_id: str = Field(..., description="所属会话 ID")
    role: str = Field(..., description="消息角色: user / assistant / tool / system")
    content: str = Field("", description="消息内容（可能被压缩）")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="工具调用记录")
    tool_call_id: Optional[str] = Field(None, description="工具调用 ID")
    tool_calls_raw: Optional[List[Any]] = Field(None, description="原始工具调用（兼容不同格式）")
    tool_result_ref: Optional[str] = Field(None, description="完整工具结果的 message_id 引用")
    content_size: int = Field(0, description="内容字节大小")
    content_type: str = Field("text", description="内容类型: text / tool_result / summary")
    is_compressed: bool = Field(False, description="是否已压缩")
    lineageSummary: Optional[Dict[str, Any]] = Field(None, description="数据血缘摘要（用于前端展示）")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    class Config:
        populate_by_name = True


class AgentToolResult(BaseModel):
    """工具完整结果 (agent_tool_results 集合，30 天 TTL 自动过期)

    当工具返回结果超过 4000 字符时，完整结果独立存储，消息中保留压缩摘要。
    """
    id: Optional[str] = Field(None, alias="_id")
    message_id: str = Field(..., description="关联的消息 ID")
    tool_name: str = Field("", description="工具名称")
    full_result: str = Field("", description="完整结果内容")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    class Config:
        populate_by_name = True
