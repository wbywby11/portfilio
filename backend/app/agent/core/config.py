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

    # 原有单模型配置（保留向后兼容）
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""  # 必须通过环境变量 LLM_BASE_URL 配置
    LLM_MODEL: str = ""     # 必须通过环境变量 LLM_MODEL 配置

    # 多模型配置（JSON 字符串格式，从环境变量读取）
    # 格式: '[{"name":"deepseek-chat","provider":"deepseek","api_key":"sk-...","base_url":"https://api.deepseek.com","priority":0},...]'
    LLM_MODELS: str = ""  # JSON 字符串，为空则使用单模型配置

    AGENT_MAX_TOOL_ROUNDS: int = 30  # 从50降至30，促进收敛
    AGENT_CONVERSATION_MAX_HISTORY: int = 50
    AGENT_MAX_RETRIES: int = 3
    AGENT_RETRY_BASE_BACKOFF: float = 1.0

    # 模型最大上下文窗口（用于上下文压缩判断）
    LLM_MAX_CONTEXT_TOKENS: int = 64000

    # 上下文压缩配置
    AGENT_COMPRESS_THRESHOLD: float = 0.45      # 触发压缩的 token 占比阈值
    # 单个工具结果进入模型前的最大字符数（过小会频繁出现「数据被截断」，多资产/大表请调大或通过 .env 配置）
    AGENT_TOOL_RESULT_MAX_CHARS: int = 25000

    # Skill A/B 测试版本配置
    # 格式: "skill_name:version,skill_name:version"
    # 示例: "asset_allocation_analysis:v2,risk_diagnosis:v2"
    # 为空表示全部使用默认版本（docs/ 根目录）
    SKILL_VERSION_CONFIG: str = ""

    # 软工具模式：固定启用，统一内外网行为
    # 工具描述被注入到 system prompt 中，模型以文本形式输出工具调用
    # 不再向 LLM 发送原生 tools 参数，兼容 DeepSeek、Qwen 等各类网关
    LLM_SOFT_TOOLS: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


# ─── 工具结果分级截断配置 ───
TOOL_RESULT_LIMITS: dict[str, int] = {
    "query_assets": 4000,
    "search_assets": 4000,
    "data_query": 50000,            # 支持大批量查询（如一年日线）
    "query_asset_prices": 50000,   # 支持一年日线250条（约10KB）
    "data_analyze": 30000,          # 分析结果可能较大
    "compute_metrics": 30000,       # 指标计算结果
    "smart_table_router": 16000,   # 表路由结果需完整展示
    "smart_auto_analyze": 15000,   # 自动分析结果
    "domain_query": 20000,         # 域查询结果
    "subject_risk_search": 15000,  # 风险搜索结果
    "data_analysis": 20000,        # 数据分析结果
    "recommend_strategy": 5000,
    "compare_strategies": 8000,
    "compute_weights": 6000,
    "run_backtest": 6000,
    "generate_strategy_report": 3000,
    "save_memory": 2000,
    "search_memory": 3000,
    "default": 8000,
}

# 存储时的二次压缩限制
TOOL_RESULT_STORAGE_LIMIT: int = 4000

# ─── 轮次预警阈值 ───
AGENT_WARN_ROUND: int = int(os.getenv("AGENT_WARN_ROUND", "3"))
AGENT_FORCE_CONCLUDE_ROUND: int = int(os.getenv("AGENT_FORCE_CONCLUDE_ROUND", "25"))

# ─── 上下文预算全局分配 ───
CONTEXT_BUDGET: dict[str, float] = {
    "system_prompt": 0.25,        # 系统提示词 25%
    "memory_context": 0.05,       # 记忆上下文 5%
    "conversation_history": 0.45, # 对话历史 45%
    "tool_results": 0.15,         # 工具结果 15%
    "response_reserve": 0.10,     # 模型回复预留 10%
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

    # 回退：从单模型配置构建
    return [ModelConfig(
        name=settings.LLM_MODEL,
        provider="default",
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        priority=0,
        max_context=settings.LLM_MAX_CONTEXT_TOKENS,
    )]
