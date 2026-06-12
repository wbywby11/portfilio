"""
LLM 客户端 - 基于 OpenAI SDK 兼容接口
支持原生 tools 参数和软工具模式（prompt 注入 + 文本解析）
"""
import json
import re
import uuid
from typing import AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI

from app.agent.core.error_handler import ErrorHandler


class LLMClient:
    """LLM 客户端，支持 OpenAI 兼容 API（DeepSeek、OpenAI 等）

    软工具模式（soft_tools=True）：
    当 LLM 服务不支持原生 tools 参数时，将工具描述注入 system prompt，
    并解析模型输出文本中的 <tool_call> 标记来提取工具调用意图。
    """

    # 软工具调用标签匹配正则 - 提取 <tool_call> 内部全部内容
    _TOOL_CALL_CONTENT_PATTERN = re.compile(
        r'<tool_call>(.*?)</tool_call>',
        re.DOTALL,
    )
    # 通用 <tool_call> 块匹配（用于清理文本）
    _TOOL_CALL_BLOCK_PATTERN = re.compile(
        r'<tool_call>.*?</tool_call>',
        re.DOTALL,
    )
    # XML 子标签清除（用于从 tool_call 内容中剥离 XML 包装）
    _XML_TAG_STRIP = re.compile(r'</?[\w]+>', re.DOTALL)
    # XML 参数子标签提取（DeepSeek 纯 XML 格式降级）
    _TOOL_CALL_XML_PATTERN = re.compile(
        r'<tool_call>\s*<name>\s*(.*?)\s*</name>\s*<arguments>\s*(.*?)\s*</arguments>\s*</tool_call>',
        re.DOTALL,
    )
    _XML_PARAM_PATTERN = re.compile(
        r'<(\w+)>(.*?)</\1>',
        re.DOTALL,
    )
    # DSML 工具调用块匹配（DeepSeek ML 格式，兼容全角 ｜ 和 ASCII | 竖线，允许空格）
    _DSML_BAR = r'[\s\uff5c|]+'       # 竖线+空格组合（全角/ASCII混用）
    _DSML_TOOL_CALL_PATTERN = re.compile(
        r'<' + r'[\s\uff5c|]+' + r'DSML' + r'[\s\uff5c|]+' + r'(?:tool_calls|function_calls)>(.*?)</' + r'[\s\uff5c|]+' + r'DSML' + r'[\s\uff5c|]+' + r'(?:tool_calls|function_calls)>',
        re.DOTALL,
    )
    # DSML invoke 块提取
    _DSML_INVOKE_PATTERN = re.compile(
        r'<' + r'[\s\uff5c|]+' + r'DSML' + r'[\s\uff5c|]+' + r'invoke\s+name="(\w+)">(.*?)</' + r'[\s\uff5c|]+' + r'DSML' + r'[\s\uff5c|]+' + r'invoke>',
        re.DOTALL,
    )
    # DSML parameter 提取
    _DSML_PARAM_PATTERN = re.compile(
        r'<' + r'[\s\uff5c|]+' + r'DSML' + r'[\s\uff5c|]+' + r'parameter\s+name="(\w+)"\s+string="(true|false)">(.*?)(?:</' + r'[\s\uff5c|]+' + r'DSML' + r'[\s\uff5c|]+' + r'parameter>|<' + r'[\s\uff5c|]+' + r'DSML' + r'[\s\uff5c|]+' + r'parameter>|' + r'[\s\uff5c|]+' + r'DSML' + r'[\s\uff5c|]+' + r'parameter>)',
        re.DOTALL,
    )
    # 纯 JSON 工具调用（无 <tool_call> 包裹）
    _BARE_JSON_TOOL_PATTERN = re.compile(
        r'\{[\s]*"name"[\s]*:[\s]*"(\w+)"[\s]*,[\s]*"arguments"[\s]*:[\s]*\{.*?\}\s*\}',
        re.DOTALL,
    )

    def __init__(self, api_key: str, base_url: str, model: str, soft_tools: bool = False):
        self.model = model
        self.soft_tools = soft_tools
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        logger.info(
            "LLM 客户端初始化",
            extra={"model": model, "base_url": base_url, "soft_tools": soft_tools},
        )

    # ------------------------------------------------------------------
    # 软工具辅助方法
    # ------------------------------------------------------------------

    def _tools_to_prompt(self, tools: list[dict]) -> str:
        """将 OpenAI function calling 格式的 tools 转成自然语言 prompt。

        Args:
            tools: OpenAI 格式的工具列表

        Returns:
            用于注入 system prompt 的工具描述文本
        """
        lines: list[str] = [
            "## 工具调用格式（严格遵守）",
            "",
            "调用工具时按以下格式输出，标签内只允许单个 JSON 对象：",
            '<tool_call>',
            '{"name": "工具名称", "arguments": {"参数名": "参数值"}}',
            '</tool_call>',
            "",
            "规则：JSON 必须含 name + arguments 两字段；每个工具一个独立 <tool_call> 块；禁止用 XML 子标签；需要工具时本轮必须输出 <tool_call>。",
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
        """将工具描述注入到 messages 的第一条 system 消息中。

        Args:
            messages: 原始消息列表
            tools: OpenAI 格式的工具列表

        Returns:
            注入后的消息列表
        """
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

    def _parse_xml_arguments(self, xml_text: str) -> dict:
        """从 XML 子标签中提取参数键值对。

        Args:
            xml_text: XML 格式的参数文本，如 '<asset_type>指数</asset_type>'

        Returns:
            参数字典
        """
        params: dict = {}
        for match in self._XML_PARAM_PATTERN.finditer(xml_text):
            key = match.group(1)
            value = match.group(2).strip()
            # 尝试转换数值类型
            if value.isdigit():
                params[key] = int(value)
            else:
                try:
                    params[key] = float(value)
                except ValueError:
                    params[key] = value
        return params

    @staticmethod
    def _normalize_tool_arguments(arguments: dict) -> dict:
        """对工具参数中嵌套编码的 JSON 字符串进行解包。

        某些 LLM (如 Qwen3) 可能将 dict/list 参数序列化为 JSON 字符串，
        例如: {"config": "{\"title\": \"图表\"}"}
        本方法将这类嵌套字符串自动还原为原生 dict/list。

        Args:
            arguments: 工具调用参数字典

        Returns:
            正规化后的参数字典
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

    def _parse_dsml_tool_calls(self, text: str) -> list[dict]:
        """从 DSML 格式中提取工具调用。

        Args:
            text: 包含 DSML 标签的原始文本

        Returns:
            标准 tool_calls 格式列表
        """
        results: list[dict] = []
        dsml_blocks = self._DSML_TOOL_CALL_PATTERN.findall(text)
        for block in dsml_blocks:
            invokes = self._DSML_INVOKE_PATTERN.findall(block)
            for func_name, params_text in invokes:
                arguments: dict = {}
                for param_match in self._DSML_PARAM_PATTERN.finditer(params_text):
                    param_name = param_match.group(1)
                    is_string = param_match.group(2) == "true"
                    param_value = param_match.group(3).strip()
                    if is_string:
                        arguments[param_name] = param_value
                    else:
                        try:
                            arguments[param_name] = json.loads(param_value)
                        except (json.JSONDecodeError, ValueError):
                            arguments[param_name] = param_value
                arguments = self._normalize_tool_arguments(arguments)
                results.append({
                    "id": f"soft_tool_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                })
                logger.info(
                    "soft_tool_dsml_parsed",
                    extra={"name": func_name, "arg_count": len(arguments)},
                )
        return results

    def _parse_tool_calls_from_text(self, text: str) -> list[dict] | None:
        """从模型输出文本中解析 <tool_call> 标记。

        解析策略（按优先级）：
        1. 提取 <tool_call> 内容，剥离所有 XML 子标签后尝试 JSON 解析
        2. 如果剥离后不是有效 JSON，尝试纯 XML 子标签解析（<name>+<arguments> 格式）

        Args:
            text: 模型输出的完整文本

        Returns:
            标准 tool_calls 格式列表，未找到时返回 None
        """
        if not text:
            return None

        logger.info(
            "soft_tools_parse_start",
            extra={
                "text_len": len(text),
                "has_tool_call_tag": "<tool_call>" in text,
            },
        )

        tool_calls: list[dict] = []

        # 策略 1：提取内容 → 剥离 XML 标签 → JSON 解析
        blocks = self._TOOL_CALL_CONTENT_PATTERN.findall(text)
        logger.info(
            "soft_tools_parse_blocks",
            extra={"block_count": len(blocks)},
        )
        for idx, block_content in enumerate(blocks):
            # 剥离所有 XML 子标签（如 <insert>, <name>, <arguments> 等）
            cleaned = self._XML_TAG_STRIP.sub('', block_content).strip()
            if not cleaned.startswith('{'):
                # 尝试在 cleaned 中找到 JSON 对象
                json_start = cleaned.find('{')
                if json_start >= 0:
                    cleaned = cleaned[json_start:]
                else:
                    continue
            try:
                data = json.loads(cleaned)
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
            except json.JSONDecodeError as e:
                logger.info(
                    "soft_tool_json_parse_failed",
                    extra={"cleaned": cleaned[:200], "error": str(e)},
                )
                continue

        if tool_calls:
            return tool_calls

        # 策略 2：纯 XML 子标签格式（<name>xxx</name><arguments><k>v</k></arguments>）
        xml_matches = self._TOOL_CALL_XML_PATTERN.findall(text)
        for idx, (name, args_xml) in enumerate(xml_matches):
            name = name.strip()
            if not name:
                continue
            arguments = self._parse_xml_arguments(args_xml)
            arguments = self._normalize_tool_arguments(arguments)
            arguments_str = json.dumps(arguments, ensure_ascii=False)
            logger.info(
                "soft_tool_xml_fallback",
                extra={"name": name, "arguments": arguments_str},
            )
            tool_calls.append({
                "id": f"soft_tool_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments_str,
                },
            })

        # 策略 3：DSML 格式解析（DeepSeek ML 标签）
        if not tool_calls:
            dsml_results = self._parse_dsml_tool_calls(text)
            if dsml_results:
                logger.info(
                    "soft_tools_dsml_fallback",
                    extra={"count": len(dsml_results)},
                )
                tool_calls = dsml_results

        # 策略 4：纯 JSON 工具调用（无 <tool_call> 包裹）
        if not tool_calls:
            for match in self._BARE_JSON_TOOL_PATTERN.finditer(text):
                try:
                    data = json.loads(match.group(0))
                    name = data.get("name", "")
                    args = data.get("arguments", {})
                    if name and isinstance(args, dict):
                        args = self._normalize_tool_arguments(args)
                        tool_calls.append({
                            "id": f"soft_tool_{uuid.uuid4().hex[:8]}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args, ensure_ascii=False),
                            },
                        })
                        logger.info(
                            "soft_tool_bare_json_parsed",
                            extra={"name": name},
                        )
                except (json.JSONDecodeError, ValueError):
                    continue

        logger.info(
            "soft_tools_parse_result",
            extra={"parsed_count": len(tool_calls)},
        )
        return tool_calls if tool_calls else None

    def _strip_tool_call_tags(self, text: str) -> str:
        """移除文本中的 <tool_call> 块和 DSML 块，仅保留展示内容。

        对于纯 JSON 工具调用，因其缺少明确标签边界，仅在确认匹配时清理。

        Args:
            text: 原始模型输出文本

        Returns:
            清理后的文本
        """
        if not text:
            return text
        # 清理 <tool_call> 块
        cleaned = self._TOOL_CALL_BLOCK_PATTERN.sub("", text)
        # 清理 DSML 块
        cleaned = self._DSML_TOOL_CALL_PATTERN.sub("", cleaned)
        # 清理纯 JSON 工具调用（有明确的 name+arguments 结构，误删风险低）
        cleaned = self._BARE_JSON_TOOL_PATTERN.sub("", cleaned)
        return cleaned.strip()

    # ------------------------------------------------------------------
    # 非流式请求
    # ------------------------------------------------------------------

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """普通（非流式）请求，返回完整响应。

        软工具模式下：将 tools 注入 system prompt，模型以文本输出工具调用，
        客户端解析后返回标准 tool_calls 格式。

        Returns:
            dict: {"content": str | None, "tool_calls": list | None}
        """
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
        }

        if self.soft_tools:
            if tools:
                kwargs["messages"] = self._inject_tools_to_messages(messages, tools)
            else:
                logger.warning("soft_tools_no_tools", extra={"soft_tools": True})
        elif tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        else:
            logger.warning("no_tools_provided", extra={"soft_tools": self.soft_tools})

        try:
            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message

            # 软工具模式：只要启用就尝试从文本中解析工具调用（tools 可能为 None 但 LLM 仍可能输出调用）
            if self.soft_tools:
                raw_content = message.content or ""
                logger.info(
                    "soft_tools_raw_output",
                    extra={
                        "content_len": len(raw_content),
                        "has_tool_call_open": "<tool_call>" in raw_content,
                        "has_tool_call_close": "</tool_call>" in raw_content,
                    },
                )
                raw_tool_calls = self._parse_tool_calls_from_text(raw_content)
                content = self._strip_tool_call_tags(raw_content)
                return {"content": content, "tool_calls": raw_tool_calls}

            # 原生模式
            tool_calls = None
            if message.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]
            return {"content": message.content, "tool_calls": tool_calls}
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
        """流式请求，yield 每个 chunk。

        软工具模式下：模型输出纯文本流，客户端在流结束后解析 <tool_call> 标记，
        再 yield 对应的 tool_call_delta 事件，保证上层 Agent 无感知。

        Yields:
            dict: {"type": "content_delta", "content": str}
                  {"type": "tool_call_delta", "index": int, "id": str?, "name": str?, "arguments": str?}
                  {"type": "finish", "finish_reason": str}
        """
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }

        if self.soft_tools:
            if tools:
                kwargs["messages"] = self._inject_tools_to_messages(messages, tools)
            else:
                logger.warning("soft_tools_no_tools", extra={"soft_tools": True})
        elif tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        else:
            logger.warning("no_tools_provided", extra={"soft_tools": self.soft_tools})

        try:
            stream = await self._client.chat.completions.create(**kwargs)

            # 软工具模式需要累积完整文本后再解析
            accumulated_text = ""
            finish_reason: str | None = None

            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                # 文本增量（软工具模式下也可能包含 <tool_call> 标签）
                if delta.content:
                    if self.soft_tools:
                        accumulated_text += delta.content
                    yield {"type": "content_delta", "content": delta.content}

                # 原生模式：直接透传工具调用增量
                if not self.soft_tools and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        event: dict = {
                            "type": "tool_call_delta",
                            "index": tc_delta.index,
                        }
                        if tc_delta.id:
                            event["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                event["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                event["arguments"] = tc_delta.function.arguments
                        yield event

                if finish_reason:
                    break

            # 软工具模式：流结束后解析累积文本中的工具调用（只要启用就尝试解析）
            if self.soft_tools:
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
        except Exception as e:
            logger.error(
                "LLM chat_stream 请求失败",
                extra={"error": ErrorHandler.sanitize_error_message(str(e))},
            )
            raise
