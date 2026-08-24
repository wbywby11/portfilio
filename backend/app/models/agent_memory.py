# -*- coding: utf-8 -*-
"""
AI Agent 记忆数据模型

对应集合: agent_memories

写入来源: Agent 运行时自动写入（memory_store.py）
被消费方: Agent 跨会话长期记忆、用户偏好存储

安全限制（memory_store.py 定义）：
- 每用户记忆总字符上限: 5000
- 单条记忆最大字符数: 1000
- 每用户最大记忆条数: 50
- 单条记忆最大关键词数: 10
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class AgentMemory(BaseModel):
    """Agent 跨会话记忆 (agent_memories 集合)

    索引:
    - (user_id, category, updated_at DESC)
    - (user_id, keywords)
    """
    id: Optional[str] = Field(None, alias="_id")
    user_id: str = Field(..., description="用户 ID")
    category: str = Field(..., description="记忆分类（如 user_preference, project_knowledge 等）")
    title: str = Field(..., description="记忆标题（最长 100 字符）")
    content: str = Field(..., description="记忆内容（最长 1000 字符）")
    keywords: List[str] = Field(default_factory=list, description="关键词列表（最多 10 个）")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        populate_by_name = True
