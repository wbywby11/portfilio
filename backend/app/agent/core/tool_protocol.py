"""
工具协议适配层 — 软工具 / 原生 function call 双模共存的唯一边界文件

设计目标：
- ReAct 主循环（agent.py）与消息历史格式对协议无感知，消费的是归一化结构
- 软工具的全部代码（✿ 标记注入/解析/清洗）聚集在 SoftToolProtocol 内
- 原生的全部逻辑聚集在 NativeToolProtocol 内
- 通过 config.LLM_TOOL_MODE 单开关切换（.env 可覆盖）

归一化契约（两种协议对外输出一致）：
- 非流式：{"content": str | None, "tool_calls": list | None}
- 流式事件：{"type": "content_delta", "content": str}
           {"type": "tool_call_delta", "index": int, "id"?, "name"?, "arguments"?}
           {"type": "finish", "finish_reason": str}
- arguments 归一化：两协议均解包工具参数中嵌套编码的 JSON 字符串（_normalize_tool_arguments）

确认内网网关能力后的删除路径：
- 确认原生可用：.env 设 LLM_TOOL_MODE=native，回归验证后删除 SoftToolProtocol
  类，并清理三处软工具专属切点：agent.py 的 text_replace 事件发送、
  chat_service.py 的 text_replace 分支、前端 AgentChatPanel 的 case 'text_replace'
- 确认原生不可用：删除 NativeToolProtocol 类及配置中 native 取值说明
"""
import json
import re
import uuid
from typing import Any, AsyncIterator

from loguru import logger


class ToolProtocol:
    """工具协议基类，定义请求适配 / 响应解析 / 提示词注入契约"""

    mode: str = ""
    # 模型输出中是否会出现文本形态的工具标记（决定 agent 是否发送 text_replace 事件）
    emits_tool_text_marks: bool = False
    # 格式纠错重试提示（模型未按协议输出工具调用时追加；原生模式无此需求）。
    # 当前为契约预留：主链路暂无消费点（重构前后均无），待实现格式纠错重试机制时由 ReAct 循环消费
    format_retry_prompt: str | None = None

    def adapt_request(
        self, messages: list[dict], tools: list[dict] | None
    ) -> tuple[list[dict], dict]:
        """请求侧适配。

        Returns:
            (messages, extra_kwargs)：适配后的消息列表 + 附加给 SDK 调用的参数
        """
        raise NotImplementedError

    def parse_completion(self, message: Any) -> dict:
        """非流式响应归一化为 {"content", "tool_calls"}"""
        raise NotImplementedError

    async def handle_stream(self, stream: AsyncIterator) -> AsyncIterator[dict]:
        """流式响应归一化为 content_delta / tool_call_delta / finish 事件"""
        raise NotImplementedError
        yield  # pragma: no cover（使方法成为 async generator）

    def strip_display_marks(self, text: str) -> str:
        """清除展示文本中的协议标记（原生模式为恒等函数）"""
        return text

    @staticmethod
    def _normalize_tool_arguments(arguments: dict) -> dict:
        """对工具参数中嵌套编码的 JSON 字符串进行解包（两协议共用的归一化）。

        某些 LLM（如 Qwen3）可能将 dict/list 参数序列化为 JSON 字符串，
        例如 {"config": "{\"title\": \"图表\"}"}，此处还原为原生 dict/list。
        """
        if not isinstance(arguments, dict):
            return arguments
        normalized = {}
        for key, value in arguments.items():
            if isinstance(value, str) and value.strip().startswith(("{", "[")):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, (dict, list)):
                        normalized[key] = parsed
                    else:
                        normalized[key] = value
                except (json.JSONDecodeError, ValueError):
                    normalized[key] = value
            else:
                normalized[key] = value
        return normalized

    def _normalize_arguments_str(self, arguments_str: str) -> str:
        """归一化 arguments JSON 字符串（原生路径使用），解析失败时原样返回"""
        try:
            parsed = json.loads(arguments_str or "{}")
        except (json.JSONDecodeError, ValueError):
            return arguments_str
        if isinstance(parsed, dict):
            parsed = self._normalize_tool_arguments(parsed)
        return json.dumps(parsed, ensure_ascii=False)

    def system_prompt_addon(self) -> str:
        """需追加到系统提示词的协议说明（原生模式返回空串）"""
        return ""


class SoftToolProtocol(ToolProtocol):
    """软工具协议：工具定义注入 system prompt，模型以文本输出 ✿function_call✿ 块。

    使用 Qwen 原生训练格式（✿function_call✿ / ✿return✿）引导模型输出，
    该格式是 Qwen2.5 预训练阶段见过的 function calling 格式，比自定义标签更稳定。
    """

    mode = "soft"
    emits_tool_text_marks = True

    format_retry_prompt = (
        "你刚才的回复中提到了要使用工具，但没有按照正确格式输出工具调用。"
        "请**仅**按以下格式输出（✿ 是固定标记符，不可省略或替换），可连续多个块：\n\n"
        "✿function_call✿\n"
        '{"name": "工具名称", "arguments": {"参数名": "参数值"}}\n'
        "✿return✿\n\n"
        "arguments 必须是合法 JSON 对象；字符串参数用双引号。请现在输出。"
    )

    # 工具调用块匹配：✿function_call✿{"name":"...","arguments":{...}}✿return✿
    _TOOL_CALL_PATTERN = re.compile(
        r'✿\s*function_call\s*✿\s*(\{.*?\})\s*✿\s*return\s*✿',
        re.DOTALL,
    )
    # 用于清理文本中的工具调用块
    _TOOL_CALL_BLOCK_PATTERN = re.compile(
        r'✿\s*function_call\s*✿.*?✿\s*return\s*✿',
        re.DOTALL,
    )

    # ------------------------------------------------------------------
    # 请求侧：工具定义注入 system prompt
    # ------------------------------------------------------------------

    def adapt_request(
        self, messages: list[dict], tools: list[dict] | None
    ) -> tuple[list[dict], dict]:
        if tools:
            return self._inject_tools_to_messages(messages, tools), {}
        # 最大轮次总结 / 上下文压缩等预期场景本就不携带工具，降级为 debug 避免告警噪音
        logger.debug("soft_tools_no_tools", extra={"soft_tools": True})
        return list(messages), {}

    def _tools_to_prompt(self, tools: list[dict]) -> str:
        """将 OpenAI function calling 格式的 tools 转成 Qwen 原生训练格式 prompt"""
        lines: list[str] = [
            "## 工具调用格式（严格遵守）",
            "",
            "需要调用工具时，必须使用以下格式输出（✿ 是固定标记符，不可省略或替换）：",
            "✿function_call✿",
            '{"name": "工具名称", "arguments": {"参数名": "参数值"}}',
            "✿return✿",
            "",
            "规则：",
            "- ✿function_call✿ 和 ✿return✿ 之间的内容必须是合法 JSON 对象",
            "- JSON 必须含 name 和 arguments 两个字段",
            "- 每个工具调用一个独立的 ✿function_call✿...✿return✿ 块",
            "- 需要工具时本轮必须输出工具调用块，禁止仅用文字描述要调用工具",
            "- 可以连续输出多个工具调用块",
            "",
            "## 可用工具列表",
            "",
        ]
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            description = func.get("description", "")
            params = func.get("parameters", {})

            lines.append(f"【{name}】{description}")

            properties = params.get("properties", {})
            required = params.get("required", [])

            if properties:
                lines.append("参数：")
                for param_name, param_schema in properties.items():
                    param_type = param_schema.get("type", "any")
                    param_desc = param_schema.get("description", "")
                    req_mark = "（必填）" if param_name in required else "（可选）"
                    lines.append(f"- {param_name}: {param_type}{req_mark}，{param_desc}")
            else:
                lines.append("参数：无")
            lines.append("")
        return "\n".join(lines)

    def _inject_tools_to_messages(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        """将工具描述注入到 messages 的第一条 system 消息中"""
        tool_prompt = self._tools_to_prompt(tools)
        new_messages: list[dict] = list(messages)

        system_idx = -1
        for i, msg in enumerate(new_messages):
            if msg.get("role") == "system":
                system_idx = i
                break

        if system_idx >= 0:
            original_content = new_messages[system_idx].get("content", "")
            new_messages[system_idx] = {
                "role": "system",
                "content": original_content + "\n\n" + tool_prompt,
            }
        else:
            new_messages.insert(0, {"role": "system", "content": tool_prompt})
        return new_messages

    # ------------------------------------------------------------------
    # 响应侧：从文本解析工具调用
    # ------------------------------------------------------------------

    def parse_completion(self, message: Any) -> dict:
        raw_content = message.content or ""
        logger.info(
            "soft_tools_raw_output",
            extra={
                "content_len": len(raw_content),
                "has_function_call_marker": "✿function_call✿" in raw_content,
            },
        )
        return {
            "content": self.strip_display_marks(raw_content),
            "tool_calls": self._parse_tool_calls_from_text(raw_content),
        }

    async def handle_stream(self, stream: AsyncIterator) -> AsyncIterator[dict]:
        """软工具流式：文本增量直接透传，流结束后从累积全文解析工具调用"""
        accumulated_text = ""
        finish_reason: str | None = None

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            if delta.content:
                accumulated_text += delta.content
                yield {"type": "content_delta", "content": delta.content}

            if finish_reason:
                break

        raw_tool_calls = self._parse_tool_calls_from_text(accumulated_text)
        if raw_tool_calls:
            for idx, tc in enumerate(raw_tool_calls):
                yield {
                    "type": "tool_call_delta",
                    "index": idx,
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                }

        if finish_reason:
            yield {"type": "finish", "finish_reason": finish_reason}

    def strip_display_marks(self, text: str) -> str:
        """移除文本中的 ✿function_call✿...✿return✿ 块，仅保留展示内容"""
        if not text:
            return text
        cleaned = self._TOOL_CALL_BLOCK_PATTERN.sub("", text)
        # 清理残留的孤立标记
        cleaned = cleaned.replace("✿function_call✿", "").replace("✿return✿", "")
        return cleaned.strip()

    def system_prompt_addon(self) -> str:
        return (
            "\n\n## 工具调用格式提醒\n"
            "需调工具时必须输出 `✿function_call✿` 块"
            "（含 `{\"name\":\"...\",\"arguments\":{...}}` JSON，以 `✿return✿` 结尾），"
            "禁止仅用文字描述要调用工具。"
        )

    # ------------------------------------------------------------------
    # 内部解析辅助
    # ------------------------------------------------------------------

    def _parse_tool_calls_from_text(self, text: str) -> list[dict] | None:
        """从模型输出文本中提取 ✿function_call✿...✿return✿ 之间的 JSON 对象"""
        if not text:
            return None

        logger.info(
            "soft_tools_parse_start",
            extra={
                "text_len": len(text),
                "has_function_call_marker": "✿function_call✿" in text,
            },
        )

        tool_calls: list[dict] = []

        for match in self._TOOL_CALL_PATTERN.finditer(text):
            json_str = match.group(1).strip()
            try:
                data = json.loads(json_str)
                name = data.get("name", "")
                arguments = data.get("arguments", {})

                if isinstance(arguments, dict):
                    arguments = self._normalize_tool_arguments(arguments)
                    arguments_str = json.dumps(arguments, ensure_ascii=False)
                elif isinstance(arguments, str):
                    try:
                        temp = json.loads(arguments)
                        if isinstance(temp, dict):
                            temp = self._normalize_tool_arguments(temp)
                        arguments_str = json.dumps(temp, ensure_ascii=False)
                    except (json.JSONDecodeError, ValueError):
                        arguments_str = arguments
                else:
                    arguments_str = json.dumps(arguments, ensure_ascii=False)

                tool_calls.append({
                    "id": f"soft_tool_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": arguments_str,
                    },
                })
                logger.info(
                    "soft_tool_parsed",
                    extra={"name": name, "arg_count": len(arguments) if isinstance(arguments, dict) else 0},
                )
            except json.JSONDecodeError as e:
                logger.warning(
                    "soft_tool_json_parse_failed",
                    extra={"json_str": json_str[:200], "error": str(e)},
                )
                continue

        logger.info(
            "soft_tools_parse_result",
            extra={"parsed_count": len(tool_calls)},
        )
        return tool_calls if tool_calls else None


class NativeToolProtocol(ToolProtocol):
    """原生 function call 协议：tools 参数透传，响应直接携带 tool_calls"""

    mode = "native"
    emits_tool_text_marks = False
    format_retry_prompt = None

    def adapt_request(
        self, messages: list[dict], tools: list[dict] | None
    ) -> tuple[list[dict], dict]:
        if tools:
            return list(messages), {"tools": tools, "tool_choice": "auto"}
        logger.warning("no_tools_provided", extra={"tool_mode": "native"})
        return list(messages), {}

    def parse_completion(self, message: Any) -> dict:
        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": self._normalize_arguments_str(tc.function.arguments),
                    },
                }
                for tc in message.tool_calls
            ]
        return {"content": message.content, "tool_calls": tool_calls}

    async def handle_stream(self, stream: AsyncIterator) -> AsyncIterator[dict]:
        """原生流式：文本增量直接透传；tool_calls 分片按 index 累积，
        流结束后归一化 arguments 并一次性 yield 完整 tool_call_delta（与 soft 契约对齐）"""
        finish_reason: str | None = None
        acc: dict[int, dict] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            if delta.content:
                yield {"type": "content_delta", "content": delta.content}

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    entry = acc.setdefault(
                        tc_delta.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

            if finish_reason:
                break

        for idx, entry in sorted(acc.items()):
            yield {
                "type": "tool_call_delta",
                "index": idx,
                "id": entry["id"],
                "name": entry["name"],
                "arguments": self._normalize_arguments_str(entry["arguments"]),
            }

        if finish_reason:
            yield {"type": "finish", "finish_reason": finish_reason}


# ----------------------------------------------------------------------
# 工厂
# ----------------------------------------------------------------------

_PROTOCOLS: dict[str, type[ToolProtocol]] = {
    "soft": SoftToolProtocol,
    "native": NativeToolProtocol,
}


def get_tool_protocol(mode: str | None = None) -> ToolProtocol:
    """按配置实例化工具协议。

    Args:
        mode: "soft" / "native"；缺省时读取 config.LLM_TOOL_MODE

    Raises:
        ValueError: mode 非法时抛出，附带可选值提示
    """
    if mode is None:
        from app.agent.core.config import get_agent_settings
        mode = get_agent_settings().LLM_TOOL_MODE

    mode = (mode or "soft").strip().lower()
    protocol_cls = _PROTOCOLS.get(mode)
    if protocol_cls is None:
        raise ValueError(
            f"[tool_protocol] 非法的 LLM_TOOL_MODE='{mode}'，"
            f"可选值：{list(_PROTOCOLS.keys())}。请在 .env 中修正后重启服务。"
        )
    return protocol_cls()
