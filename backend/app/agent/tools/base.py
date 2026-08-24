"""
工具基类与工具注册表

工具对接接口：所有工具只需继承 BaseTool 并实现 execute()，
然后在 ToolRegistry 中注册即可被 Agent 自动调用。
"""
from abc import ABC, abstractmethod

from loguru import logger


class BaseTool(ABC):
    """工具抽象基类 — 所有工具只需继承此类并实现 execute()"""

    name: str                        # 工具唯一标识
    description: str                 # 工具描述（注入 prompt）
    parameters: dict = None          # JSON Schema 参数定义

    max_result_chars: int = 8000     # 结果截断阈值（字符数），子类可覆盖
    tool_timeout: float = 60.0       # 执行超时（秒），子类可覆盖
    budget_threshold: int = 0        # L2 持久化阈值（0=用全局默认 AGENT_RESULT_BUDGET）

    def to_openai_tool(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        params = self.parameters
        if not params or not isinstance(params, dict) or "type" not in params:
            params = {"type": "object", "properties": {}, "required": []}
        elif "properties" not in params:
            params["properties"] = {}
        if "required" not in params:
            params["required"] = []

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs) -> dict:
        """执行工具，返回结果字典"""
        pass


class ConfirmableTool(BaseTool):
    """两阶段写工具基类（M3 确认卡片协议）

    execute() 不执行业务逻辑：查重 → 建 pending 确认记录 → 返回 token；
    真实写逻辑由子类实现 perform()，用户确认后由决策 API 执行。
    """

    # chat_service 经 tool_context 注入的上下文字段名（非 LLM 参数）
    _CONTEXT_KEYS = ("conversation_id", "user_id")

    @abstractmethod
    async def perform(self, **kwargs) -> dict:
        """真实写逻辑（仅在用户确认后执行，执行方已注入 conversation_id）"""
        pass

    def build_preview(self, arguments: dict) -> dict:
        """操作预览（确认卡片渲染内容），子类可覆盖提供结构化摘要"""
        return {"tool": self.name, "arguments": arguments}

    async def execute(self, **kwargs) -> dict:
        """不执行业务：创建/复用确认记录，返回 pending_confirmation"""
        from app.agent.core.confirmation import ConfirmationService

        context = {k: kwargs.pop(k) for k in self._CONTEXT_KEYS if k in kwargs}
        conversation_id = context.get("conversation_id", "")
        preview = self.build_preview(kwargs)
        token, reused = await ConfirmationService.request_confirmation(
            conversation_id=conversation_id,
            tool_name=self.name,
            arguments=kwargs,
            preview=preview,
        )
        return {
            "status": "pending_confirmation",
            "token": token,
            "reused": reused,
            "preview": preview,
            "message": "该操作需要用户确认，确认通过后才会执行。"
                       "请明确告知用户操作内容并等待确认，不得重复发起同一操作。",
        }


class ToolRegistry:
    """工具注册表 — 注册/查询/过滤"""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册工具"""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> BaseTool | None:
        """按名称获取工具"""
        return self._tools.get(name)

    def get_all_tools(self) -> list[BaseTool]:
        """获取所有已注册工具"""
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict]:
        """获取所有工具的 OpenAI function calling 格式列表"""
        return [t.to_openai_tool() for t in self._tools.values()]

    def get_filtered_openai_tools(self, tool_names: list[str]) -> list[dict]:
        """根据工具名称列表返回过滤后的 OpenAI 工具格式"""
        if not tool_names:
            return self.get_openai_tools()
        allowed = set(tool_names)
        return [t.to_openai_tool() for t in self._tools.values() if t.name in allowed]


# 全局工具注册表实例
tool_registry = ToolRegistry()
