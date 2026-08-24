"""
LLM 客户端 - 基于 OpenAI SDK 兼容接口

协议差异（软工具注入/解析 vs 原生 tools 参数）全部委托给
app.agent.core.tool_protocol.ToolProtocol，本类只负责 SDK 调用与归一化输出。

对外归一化契约（与协议无关）：
- chat()      -> {"content": str | None, "tool_calls": list | None}
- chat_stream -> {"type": "content_delta", "content": str}
                 {"type": "tool_call_delta", "index": int, "id"?, "name"?, "arguments"?}
                 {"type": "finish", "finish_reason": str}
"""
from typing import AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI

from app.agent.core.error_handler import ErrorHandler
from app.agent.core.tool_protocol import ToolProtocol, get_tool_protocol


class LLMClient:
    """LLM 客户端，支持 OpenAI 兼容 API（DeepSeek、Qwen、OpenAI 等）"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        protocol: ToolProtocol | None = None,
    ):
        self.model = model
        self.protocol = protocol or get_tool_protocol()
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        logger.info(
            "LLM 客户端初始化",
            extra={"model": model, "base_url": base_url, "tool_mode": self.protocol.mode},
        )

    @property
    def tool_mode(self) -> str:
        """当前工具协议模式（soft / native）"""
        return self.protocol.mode

    # ------------------------------------------------------------------
    # 非流式请求
    # ------------------------------------------------------------------

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """普通（非流式）请求，返回归一化的完整响应。

        Returns:
            dict: {"content": str | None, "tool_calls": list | None}
        """
        adapted_messages, extra_kwargs = self.protocol.adapt_request(messages, tools)
        kwargs: dict = {
            "model": self.model,
            "messages": adapted_messages,
            **extra_kwargs,
        }

        try:
            response = await self._client.chat.completions.create(**kwargs)
            return self.protocol.parse_completion(response.choices[0].message)
        except Exception as e:
            logger.error(
                "LLM chat 请求失败",
                extra={"error": ErrorHandler.sanitize_error_message(str(e))},
            )
            raise

    # ------------------------------------------------------------------
    # 流式请求
    # ------------------------------------------------------------------

    async def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncGenerator[dict, None]:
        """流式请求，yield 归一化 chunk（协议差异由 protocol.handle_stream 吸收）。

        Yields:
            dict: {"type": "content_delta", "content": str}
                  {"type": "tool_call_delta", "index": int, "id": str?, "name": str?, "arguments": str?}
                  {"type": "finish", "finish_reason": str}
        """
        adapted_messages, extra_kwargs = self.protocol.adapt_request(messages, tools)
        kwargs: dict = {
            "model": self.model,
            "messages": adapted_messages,
            "stream": True,
            **extra_kwargs,
        }

        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for event in self.protocol.handle_stream(stream):
                yield event
        except Exception as e:
            logger.error(
                "LLM chat_stream 请求失败",
                extra={"error": ErrorHandler.sanitize_error_message(str(e))},
            )
            raise
