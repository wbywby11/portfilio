"""
Agent 配置
"""
import json
import os
from functools import lru_cache

from loguru import logger
from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    """AI Agent 配置，从环境变量加载"""

    # 单模型配置
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""

    # 多模型配置（JSON 字符串格式）
    LLM_MODELS: str = ""

    # Agent 行为配置
    AGENT_MAX_TOOL_ROUNDS: int = 30
    AGENT_CONVERSATION_MAX_HISTORY: int = 50
    AGENT_MAX_RETRIES: int = 3
    AGENT_RETRY_BASE_BACKOFF: float = 1.0

    # 模型最大上下文窗口
    LLM_MAX_CONTEXT_TOKENS: int = 64000

    # 上下文压缩配置
    AGENT_COMPRESS_THRESHOLD: float = 0.45
    AGENT_TOOL_RESULT_MAX_CHARS: int = 25000

    # 工具结果预算管控
    AGENT_RESULT_BUDGET: int = 12000      # L2 单结果持久化阈值（字符）
    AGENT_TURN_BUDGET: int = 40000        # L3 轮次总预算（字符）
    AGENT_BUDGET_PREVIEW_CHARS: int = 1500  # 持久化后保留的 preview 长度

    # 知识库配置
    KNOWLEDGE_MAX_CONTENT_CHARS: int = 50000   # 单篇文档内容上限
    KNOWLEDGE_SEARCH_LIMIT: int = 5            # 默认检索返回条数
    KNOWLEDGE_SEARCH_MAX_LIMIT: int = 10       # 检索返回条数上限

    # 工具协议模式：soft=软工具（prompt 注入+文本解析） / native=原生 function call
    # 内网确认网关能力后可切换；删除任一协议时同步清理 tool_protocol.py 对应类
    LLM_TOOL_MODE: str = "soft"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


# ─── 轮次预警阈值 ───
AGENT_WARN_ROUND: int = int(os.getenv("AGENT_WARN_ROUND", "3"))
AGENT_FORCE_CONCLUDE_ROUND: int = int(os.getenv("AGENT_FORCE_CONCLUDE_ROUND", "25"))

# ─── 上下文预算全局分配 ───
CONTEXT_BUDGET: dict[str, float] = {
    "system_prompt": 0.25,
    "memory_context": 0.05,
    "conversation_history": 0.45,
    "tool_results": 0.15,
    "response_reserve": 0.10,
}

MAX_CONTEXT_TOKENS: int = int(os.getenv("AGENT_MAX_CONTEXT_TOKENS", "64000"))


@lru_cache()
def get_agent_settings() -> AgentSettings:
    """获取 AgentSettings 单例"""
    return AgentSettings()


def get_model_configs() -> list:
    """
    解析模型配置列表。
    优先使用 LLM_MODELS 环境变量（JSON 列表）。
    如果未配置，则从单模型配置自动构建。
    """
    from app.agent.core.model_router import ModelConfig

    settings = get_agent_settings()

    if settings.LLM_MODELS:
        try:
            models_data = json.loads(settings.LLM_MODELS)
            return [ModelConfig(**m) for m in models_data]
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"LLM_MODELS 解析失败，回退到单模型配置: {e}")

    return [ModelConfig(
        name=settings.LLM_MODEL,
        provider="default",
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        priority=0,
        max_context=settings.LLM_MAX_CONTEXT_TOKENS,
    )]
