"""
多模型路由与容错模块

支持配置多个 LLM 模型，按优先级排序。
主模型调用失败时自动降级到备选模型。
"""
import time
from dataclasses import dataclass, field
from loguru import logger
from app.agent.core.llm_client import LLMClient
from app.agent.core.error_handler import ErrorHandler, ErrorCategory


@dataclass
class ModelConfig:
    """单个模型的配置"""
    name: str              # 模型名称，如 "deepseek-chat"
    provider: str          # 提供商，如 "deepseek"
    api_key: str           # API Key
    base_url: str          # API 基础地址
    priority: int = 0      # 优先级（越小越优先）
    max_context: int = 64000  # 最大上下文窗口 token 数
    enabled: bool = True   # 是否启用


class ModelRouter:
    """
    模型路由器 — 多模型配置、自动容错降级

    设计原则：
    - Agent 不能自行决定使用哪个模型，由 Router 统一控制
    - 失败时自动降级到下一优先级模型
    - 临时标记不可用模型（冷却期后自动恢复）
    - API Key 仅在内存中，不持久化
    """

    # 模型不可用的冷却时间（秒）
    COOLDOWN_SECONDS = 300  # 5 分钟

    def __init__(self, models: list[ModelConfig]):
        # 按优先级排序
        self.models = sorted([m for m in models if m.enabled], key=lambda m: m.priority)
        if not self.models:
            raise ValueError("至少需要配置一个已启用的模型")

        # 为每个模型创建 LLMClient 实例
        from app.agent.core.config import get_agent_settings
        _settings = get_agent_settings()
        self._clients: dict[str, LLMClient] = {}
        for model in self.models:
            self._clients[model.name] = LLMClient(
                api_key=model.api_key,
                base_url=model.base_url,
                model=model.name,
                soft_tools=_settings.LLM_SOFT_TOOLS,
            )

        # 失败跟踪：模型名 → (失败次数, 最后失败时间)
        self._failures: dict[str, tuple[int, float]] = {}

        self._error_handler = ErrorHandler()

        logger.info(f"[ModelRouter] 初始化完成，可用模型: {[m.name for m in self.models]}")

    def get_client(self) -> tuple[LLMClient, ModelConfig]:
        """获取当前最优可用模型的客户端"""
        now = time.time()
        for model in self.models:
            # 检查是否在冷却期
            if model.name in self._failures:
                fail_count, last_fail_time = self._failures[model.name]
                if now - last_fail_time < self.COOLDOWN_SECONDS and fail_count >= 3:
                    logger.debug(f"[ModelRouter] 模型 {model.name} 在冷却期，跳过")
                    continue
                elif now - last_fail_time >= self.COOLDOWN_SECONDS:
                    # 冷却期已过，重置失败计数
                    del self._failures[model.name]

            return self._clients[model.name], model

        # 所有模型都在冷却期，强制使用最高优先级的
        logger.warning("[ModelRouter] 所有模型都在冷却期，强制使用主模型")
        primary = self.models[0]
        return self._clients[primary.name], primary

    def get_fallback_client(self, failed_model_name: str) -> tuple[LLMClient, ModelConfig] | None:
        """获取降级模型（跳过失败的模型）"""
        now = time.time()
        for model in self.models:
            if model.name == failed_model_name:
                continue
            # 检查冷却期
            if model.name in self._failures:
                fail_count, last_fail_time = self._failures[model.name]
                if now - last_fail_time < self.COOLDOWN_SECONDS and fail_count >= 3:
                    continue
            return self._clients[model.name], model
        return None

    def record_failure(self, model_name: str):
        """记录模型调用失败"""
        now = time.time()
        if model_name in self._failures:
            fail_count, _ = self._failures[model_name]
            self._failures[model_name] = (fail_count + 1, now)
        else:
            self._failures[model_name] = (1, now)
        logger.warning(f"[ModelRouter] 模型 {model_name} 调用失败，累计失败: {self._failures[model_name][0]} 次")

    def record_success(self, model_name: str):
        """记录模型调用成功，重置失败计数"""
        if model_name in self._failures:
            del self._failures[model_name]

    def get_model_status(self) -> list[dict]:
        """获取所有模型状态（用于监控/调试）"""
        now = time.time()
        status = []
        for model in self.models:
            info = {
                "name": model.name,
                "provider": model.provider,
                "priority": model.priority,
                "available": True,
            }
            if model.name in self._failures:
                fail_count, last_fail_time = self._failures[model.name]
                info["fail_count"] = fail_count
                info["available"] = not (fail_count >= 3 and now - last_fail_time < self.COOLDOWN_SECONDS)
                info["cooldown_remaining"] = max(0, self.COOLDOWN_SECONDS - (now - last_fail_time))
            status.append(info)
        return status
