"""
Agent 提示词模块
"""
from app.agent.prompts.system_prompts import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_CORE,
    CREDIT_RATING_PROMPT,
    DATA_ANALYSIS_PROMPT,
    REPORT_WRITING_PROMPT,
    SCENE_PROMPTS,
    get_system_prompt,
)

__all__ = [
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_CORE",
    "CREDIT_RATING_PROMPT",
    "DATA_ANALYSIS_PROMPT",
    "REPORT_WRITING_PROMPT",
    "SCENE_PROMPTS",
    "get_system_prompt",
]
