"""
投资研究 Agent - ReAct 循环主控逻辑
"""
import asyncio
import json
import re
import time

from loguru import logger

from app.agent.core.config import get_agent_settings
from app.agent.core.error_handler import (
    ErrorHandler, HandleResult,
    ToolErrorCategory, classify_tool_error, generate_tool_diagnosis, generate_recovery_suggestion,
)
from app.agent.core.model_router import ModelRouter
from app.agent.tools.base import ToolRegistry
from app.agent.tools.pipeline_executor import PipelineExecutor


def _format_tool_result(tool_result) -> str:
    """将工具结果格式化为 LLM 可读的字符串。
    对于包含 Markdown 表格的字段，以纯文本形式展示而非 JSON 嵌套，
    避免 json.dumps 将换行符转义为 \\n 导致 LLM 无法识别 GFM 格式。
    """
    if not isinstance(tool_result, dict):
        return json.dumps(tool_result, ensure_ascii=False, default=str)

    def _is_gfm_table(value) -> bool:
        """判断字符串是否包含 GFM 表格标记"""
        return (isinstance(value, str)
                and '|' in value
                and '---' in value
                and '\n' in value)

    def _extract_tables(d: dict, prefix: str = "") -> tuple[dict, dict]:
        """递归提取包含 GFM 表格的字段。返回 (other_fields, table_fields)"""
        table_fields = {}
        other_fields = {}
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if _is_gfm_table(value):
                table_fields[full_key] = value
            elif isinstance(value, dict):
                # 递归检查嵌套 dict（如 data 字段）
                sub_other, sub_tables = _extract_tables(value, full_key)
                if sub_tables:
                    table_fields.update(sub_tables)
                    if sub_other:
                        other_fields[key] = sub_other
                else:
                    other_fields[key] = value
            else:
                other_fields[key] = value
        return other_fields, table_fields

    other_fields, table_fields = _extract_tables(tool_result)

    if not table_fields:
        # 没有表格字段，保持原有 JSON 序列化逻辑
        return json.dumps(tool_result, ensure_ascii=False, default=str)

    # 混合格式：非表格部分保持 JSON，表格作为纯文本追加
    parts = []
    if other_fields:
        parts.append(json.dumps(other_fields, ensure_ascii=False, default=str))
    for field_name, table_content in table_fields.items():
        parts.append(f"\n\n【{field_name}】:\n{table_content}")

    return "\n".join(parts)


_FORMAT_RETRY_PROMPT = (
    "你刚才的回复中提到了要使用工具，但没有按照正确格式输出工具调用。"
    "请**仅**按以下 XML 块输出（不要前言、不要复述计划、不要 Markdown 标题），可连续多个块：\n\n"
    "<tool_call>\n"
    '{"name": "工具名称", "arguments": {"参数名": "参数值"}}\n'
    "</tool_call>\n\n"
    "示例（产品概况）：\n"
    "<tool_call>\n"
    '{"name": "product_hub_query", "arguments": {"connector_id": "zysc_dwd_ptl_info", "limit": 25}}\n'
    "</tool_call>\n\n"
    "arguments 必须是合法 JSON 对象；字符串参数用双引号。请现在输出。"
)


class InvestmentAgent:
    """投资研究智能 Agent，实现 ReAct 工具调用循环"""

    # DSML 格式标签匹配模式（DeepSeek 降级模式输出，兼容全角 ｜/ASCII | 两种竖线 + 空格混用）
    # 使用 [\s\uff5c|]+ 匹配竖线+空格组合，兼容 function_calls 和 tool_calls 两种变体
    _DSML_BAR_PAT = r'[\s\uff5c|]+'
    _DSML_FULL_PATTERN = re.compile(
        r'<' + r'[\s\uff5c|]+' + r'[^>]*?' + r'[\s\uff5c|]+' + r'(?:function_calls|tool_calls)>.*?</' + r'[\s\uff5c|]+' + r'[^>]*?' + r'[\s\uff5c|]+' + r'(?:function_calls|tool_calls)>',
        re.DOTALL,
    )
    _DSML_PARTIAL_PATTERN = re.compile(
        r'</?'
        r'[\s\uff5c|]*DSML[\s\uff5c|]*'
        r'(?:function_calls|tool_calls|invoke|parameter)?'
        r'[^>]*>',
        re.IGNORECASE,
    )
    # 孤立/畸形标签（闭合标签残留、合并标签）
    _ORPHAN_TAG_PATTERN = re.compile(
        r'</?' + r'\s*(?:tool_call|tool_calls|function_calls|invoke|parameter|task)' + r'\s*>|'
        r'</?' + r'\s*(?:tasktool_call|taskfunction_calls)' + r'\s*>|'
        r'<' + r'[\s\uff5c|]\s*',
        re.IGNORECASE,
    )
    # 裸 JSON 工具调用模式
    _BARE_JSON_TOOL_PATTERN = re.compile(
        r'\s*\{[\s]*"name"[\s]*:[\s]*"\w+"[\s]*,[\s]*"arguments"[\s]*:[\s]*\{.*?\}\s*\}\s*',
        re.DOTALL,
    )

    def __init__(
        self,
        model_router: ModelRouter,
        tool_registry: ToolRegistry,
        max_tool_rounds: int = 10,
        context_engine=None,
    ):
        self.model_router = model_router
        self.tool_registry = tool_registry
        self.max_tool_rounds = max_tool_rounds
        self.context_engine = context_engine  # 可选，用于智能压缩
        cfg = get_agent_settings()
        self.error_handler = ErrorHandler(
            max_retries=cfg.AGENT_MAX_RETRIES,
            base_backoff=cfg.AGENT_RETRY_BASE_BACKOFF,
        )
        self.pipeline_executor = PipelineExecutor(self.tool_registry)
        self._active_scenes: set[str] = set()

    # ------------------------------------------------------------------
    # 带智能重试的 LLM 调用
    # ------------------------------------------------------------------
    async def _call_llm_with_retry(
        self, messages: list[dict], tools: list[dict] | None = None,
    ) -> dict:
        """带错误分类、智能重试和模型降级的 LLM 调用（非流式）"""
        working_messages = list(messages)
        retry_count = 0
        current_model_name = None

        while True:
            client, model_config = self.model_router.get_client()
            current_model_name = model_config.name

            try:
                result = await client.chat(working_messages, tools=tools)
                self.model_router.record_success(current_model_name)
                return result
            except Exception as e:
                self.model_router.record_failure(current_model_name)
                handle_result: HandleResult = await self.error_handler.handle(e, retry_count)

                if not handle_result.retry:
                    # 尝试降级到备选模型
                    fallback = self.model_router.get_fallback_client(current_model_name)
                    if fallback:
                        fallback_client, fallback_model = fallback
                        logger.info("[Agent] 模型 {} 失败，降级到 {}", current_model_name, fallback_model.name)
                        try:
                            result = await fallback_client.chat(working_messages, tools=tools)
                            self.model_router.record_success(fallback_model.name)
                            return result
                        except Exception:
                            self.model_router.record_failure(fallback_model.name)
                    logger.error("[Agent] LLM 调用失败且不可重试: {}", handle_result.user_message)
                    raise

                if handle_result.action == "compress" and self.context_engine:
                    # 使用 ContextEngine 智能压缩替代临时截断
                    compressed = await self.context_engine.prepare_messages(working_messages)
                    working_messages = compressed
                elif handle_result.action == "compress":
                    # 无 ContextEngine 时的降级方案：保留 system + 最近消息
                    if len(working_messages) > 10:
                        working_messages = [working_messages[0]] + working_messages[-8:]
                        logger.warning("无 ContextEngine，使用降级截断策略")
                logger.info(
                    "[Agent] LLM 调用失败，将在 {:.1f}s 后重试 ({}/{})",
                    handle_result.wait_seconds, retry_count + 1, self.error_handler.max_retries,
                )
                if handle_result.wait_seconds > 0:
                    await asyncio.sleep(handle_result.wait_seconds)
                retry_count += 1

    async def _call_llm_stream_with_retry(
        self, messages: list[dict], tools: list[dict] | None = None,
    ):
        """带错误分类、智能重试和模型降级的 LLM 流式调用，yield chunk"""
        working_messages = list(messages)
        retry_count = 0
        current_model_name = None

        while True:
            client, model_config = self.model_router.get_client()
            current_model_name = model_config.name

            try:
                async for chunk in client.chat_stream(working_messages, tools=tools):
                    yield chunk
                self.model_router.record_success(current_model_name)
                return  # 正常结束
            except Exception as e:
                self.model_router.record_failure(current_model_name)
                handle_result: HandleResult = await self.error_handler.handle(e, retry_count)

                if not handle_result.retry:
                    # 尝试降级到备选模型
                    fallback = self.model_router.get_fallback_client(current_model_name)
                    if fallback:
                        fallback_client, fallback_model = fallback
                        logger.info("[Agent] 流式模型 {} 失败，降级到 {}", current_model_name, fallback_model.name)
                        try:
                            async for chunk in fallback_client.chat_stream(working_messages, tools=tools):
                                yield chunk
                            self.model_router.record_success(fallback_model.name)
                            return
                        except Exception:
                            self.model_router.record_failure(fallback_model.name)
                    logger.error("[Agent] LLM 流式调用失败且不可重试: {}", handle_result.user_message)
                    raise

                if handle_result.action == "compress" and self.context_engine:
                    # 使用 ContextEngine 智能压缩替代临时截断
                    compressed = await self.context_engine.prepare_messages(working_messages)
                    working_messages = compressed
                elif handle_result.action == "compress":
                    # 无 ContextEngine 时的降级方案：保留 system + 最近消息
                    if len(working_messages) > 10:
                        working_messages = [working_messages[0]] + working_messages[-8:]
                        logger.warning("无 ContextEngine，使用降级截断策略")
                logger.info(
                    "[Agent] LLM 流式调用失败，将在 {:.1f}s 后重试 ({}/{})",
                    handle_result.wait_seconds, retry_count + 1, self.error_handler.max_retries,
                )
                if handle_result.wait_seconds > 0:
                    await asyncio.sleep(handle_result.wait_seconds)
                retry_count += 1

    # ------------------------------------------------------------------
    # 公共工具执行逻辑
    # ------------------------------------------------------------------
    async def _execute_single_tool(
        self,
        tool_call: dict,
        executed_tools: set,
        tool_failure_counts: dict,
        tool_context: dict,
    ) -> dict:
        """执行单个工具调用，包含依赖检查、超时处理、错误诊断。

        Args:
            tool_call: 工具调用字典，包含 function.name / function.arguments / id
            executed_tools: 已成功执行的工具名集合
            tool_failure_counts: 工具连续失败计数器
            tool_context: 注入到工具的额外上下文参数

        Returns:
            {
                "tool_call_id": str,
                "result": dict,       # 原始工具结果（用于 all_tool_calls 记录）
                "result_str": str,     # JSON 格式结果（含依赖警告，用于 message content）
                "success": bool,
            }
        """
        func_name = tool_call["function"]["name"]
        func_args_str = tool_call["function"].get("arguments", "{}")
        tool_call_id = tool_call["id"]

        logger.info(
            "[Agent] tool_call begin name={} id={}",
            func_name,
            tool_call_id,
        )

        # 解析参数
        try:
            func_args = json.loads(func_args_str) if func_args_str else {}
        except json.JSONDecodeError:
            logger.warning("工具参数 JSON 解析失败: {}", func_args_str)
            func_args = {}

        tool = self.tool_registry.get_tool(func_name)

        if not tool:
            tool_result = {"error": f"未知工具: {func_name}"}
            logger.warning("未知工具: {}", func_name)
            result_str = json.dumps(tool_result, ensure_ascii=False, default=str)
            return {"tool_call_id": tool_call_id, "result": tool_result, "result_str": result_str, "success": False}

        # 依赖检查（非阻断式）
        dep_warning = ""
        if tool.dependencies:
            missing_deps = [d for d in tool.dependencies if d not in executed_tools]
            if missing_deps:
                dep_warning = f"⚠️ 依赖提示：{func_name} 建议先调用 {', '.join(missing_deps)}。当前仍继续执行，但结果可能不完整。"
                logger.warning("[Agent] 工具依赖未满足: {} 缺少 {}", func_name, missing_deps)

        # Pipeline：自动执行前置依赖链，注入结果到参数中
        try:
            func_args = await self.pipeline_executor.execute_pipeline(
                target_tool_name=func_name,
                original_args=func_args,
                context=tool_context,
            )
        except Exception as e:
            logger.warning("[Agent] Pipeline 执行异常，使用原始参数继续: {}", str(e))

        # 执行工具 - 可靠超时获取：优先实例属性，再找类属性
        _timeout = getattr(tool, 'tool_timeout', None)
        if _timeout is None:
            _timeout = getattr(type(tool), 'tool_timeout', 60.0)
        logger.info("[Agent] 工具 {} 超时配置: {}s (实例={}, 类={})",
            func_name, _timeout,
            getattr(tool, 'tool_timeout', 'N/A'),
            getattr(type(tool), 'tool_timeout', 'N/A'))
        try:
            merged_args = {**func_args, **tool_context}
            tool_result = await asyncio.wait_for(
                tool.execute(**merged_args),
                timeout=_timeout,
            )
            # 成功：重置失败计数，记录已执行
            tool_failure_counts.pop(func_name, None)
            executed_tools.add(func_name)

        except asyncio.TimeoutError as e:
            category = ToolErrorCategory.TIMEOUT
            diagnosis = generate_tool_diagnosis(func_name, e, category, func_args)
            suggestion = generate_recovery_suggestion(category, func_name)
            tool_failure_counts[func_name] = tool_failure_counts.get(func_name, 0) + 1
            tool_result = {
                "error": f"工具 {func_name} 执行超时（{_timeout}秒）",
                "diagnosis": diagnosis,
                "suggestion": suggestion,
            }
            if tool_failure_counts[func_name] >= 2:
                tool_result["warning"] = f"⚠️ {func_name} 已连续失败 {tool_failure_counts[func_name]} 次，强烈建议换用其他工具或调整策略。"
            logger.warning("[Agent] 工具 {} 执行超时 ({}s)", func_name, _timeout)

        except Exception as e:
            category = classify_tool_error(func_name, e, func_args)
            diagnosis = generate_tool_diagnosis(func_name, e, category, func_args)
            suggestion = generate_recovery_suggestion(category, func_name)
            tool_failure_counts[func_name] = tool_failure_counts.get(func_name, 0) + 1
            tool_result = {
                "error": str(e),
                "diagnosis": diagnosis,
                "suggestion": suggestion,
            }
            if tool_failure_counts[func_name] >= 2:
                tool_result["warning"] = f"⚠️ {func_name} 已连续失败 {tool_failure_counts[func_name]} 次，强烈建议换用其他工具或调整策略。"
            logger.error("[Agent] 工具 {} 执行异常: {}", func_name, ErrorHandler.sanitize_error_message(str(e)))

        # 构造结果字符串（附加依赖警告）
        result_str = _format_tool_result(tool_result)
        if dep_warning:
            result_str = dep_warning + "\n" + result_str

        # 即时截断：避免超大工具结果占用过多上下文
        # 分级获取限制：工具实例显式覆盖(非默认8000) > TOOL_RESULT_LIMITS[tool_name] > TOOL_RESULT_LIMITS["default"]
        from app.agent.core.config import TOOL_RESULT_LIMITS
        _tool_instance = self.tool_registry.get_tool(func_name) if self.tool_registry else None
        _instance_limit = getattr(_tool_instance, 'max_result_chars', None) if _tool_instance else None
        _config_limit = TOOL_RESULT_LIMITS.get(func_name, TOOL_RESULT_LIMITS["default"])
        if _instance_limit and _instance_limit != 8000:
            # 子类显式覆盖了 max_result_chars，优先使用
            _max_chars = _instance_limit
        else:
            _max_chars = _config_limit

        if len(result_str) > _max_chars:
            logger.info("[Agent] 工具 {} 结果即时截断: {} -> {} chars",
                        func_name, len(result_str), _max_chars)
            # 尝试 JSON 结构感知截断
            try:
                parsed = json.loads(result_str)
                if isinstance(parsed, list) and len(parsed) > 3:
                    # 列表：保留尽可能多的条目在预算内，同时附加统计摘要
                    budget = int(_max_chars * 0.9)
                    preview = []
                    cur_size = 200  # 预留元数据空间
                    for item in parsed:
                        item_s = json.dumps(item, ensure_ascii=False, default=str)
                        if cur_size + len(item_s) + 2 <= budget:
                            preview.append(item)
                            cur_size += len(item_s) + 2
                        else:
                            break
                    result_str = json.dumps({
                        "_truncated": True,
                        "_total_items": len(parsed),
                        "_shown_items": len(preview),
                        "items": preview,
                        "_hint": f"共 {len(parsed)} 条记录，已展示前 {len(preview)} 条。请基于已有数据直接分析，无需再次拉取。",
                    }, ensure_ascii=False, default=str)
                elif isinstance(parsed, dict):
                    # 字典：保留关键字段
                    priority = ["success", "error", "message", "summary", "recommendation",
                                "comparison_table", "rankings", "result", "data", "items",
                                "total", "record_count", "upstream_sync"]
                    kept = {}
                    size = 0
                    budget = int(_max_chars * 0.85)
                    for k in priority:
                        if k in parsed:
                            s = json.dumps({k: parsed[k]}, ensure_ascii=False, default=str)
                            if size + len(s) <= budget:
                                kept[k] = parsed[k]
                                size += len(s)
                            elif k == "items" and isinstance(parsed[k], list):
                                # items 字段特殊处理：尽量多保留
                                sub_budget = budget - size - 200
                                sub_items = []
                                sub_size = 0
                                for item in parsed[k]:
                                    item_s = json.dumps(item, ensure_ascii=False, default=str)
                                    if sub_size + len(item_s) + 2 <= sub_budget:
                                        sub_items.append(item)
                                        sub_size += len(item_s) + 2
                                    else:
                                        break
                                kept[k] = sub_items
                                kept["_items_truncated"] = f"展示 {len(sub_items)}/{len(parsed[k])} 条"
                                size += sub_size + 100
                    for k, v in parsed.items():
                        if k not in kept:
                            s = json.dumps({k: v}, ensure_ascii=False, default=str)
                            if len(s) <= 300 and size + len(s) <= budget:
                                kept[k] = v
                                size += len(s)
                    omitted = [k for k in parsed if k not in kept]
                    if omitted:
                        kept["_truncated"] = True
                        kept["_omitted_fields"] = omitted
                    kept["_hint"] = "数据已截断，请基于当前可见数据直接给出分析结论，无需重复调用相同工具。"
                    result_str = _format_tool_result(kept)
            except (json.JSONDecodeError, TypeError):
                # 纯文本截断
                keep = _max_chars // 3
                result_str = (
                    result_str[:keep]
                    + f"\n...[已截断，原始 {len(result_str)} 字符]...\n"
                    + result_str[-keep:]
                )

        success = "error" not in tool_result
        return {"tool_call_id": tool_call_id, "result": tool_result, "result_str": result_str, "success": success}

    async def _execute_tools_parallel(
        self,
        tool_calls: list[dict],
        executed_tools: set,
        tool_failure_counts: dict,
        tool_context: dict | None,
    ) -> list[dict]:
        """并行执行多个工具调用，返回结果列表（保持原始顺序）。

        使用 asyncio.gather 并发执行所有工具，对于失败的工具通过
        return_exceptions=True 捕获异常而不中断其他工具。
        """
        if len(tool_calls) <= 1:
            # 单个工具无需并行，直接执行
            results = []
            for tc in tool_calls:
                result = await self._execute_single_tool(
                    tc, executed_tools, tool_failure_counts, tool_context
                )
                results.append(result)
            return results

        # 并发前：预填 executed_tools，避免依赖检查误报
        for tc in tool_calls:
            func_name = tc.get("function", {}).get("name", "")
            if func_name:
                executed_tools.add(func_name)

        # 创建并发任务
        tasks = [
            self._execute_single_tool(tc, executed_tools, tool_failure_counts, tool_context)
            for tc in tool_calls
        ]

        # 并发执行，捕获异常
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果：异常转为错误结果
        results = []
        for idx, raw in enumerate(raw_results):
            if isinstance(raw, Exception):
                tc = tool_calls[idx]
                func_name = tc.get("function", {}).get("name", "unknown")
                logger.error("[Agent] 并行工具 {} 执行异常: {}", func_name, raw)
                results.append({
                    "tool_call_id": tc.get("id", ""),
                    "result": {"error": str(raw)},
                    "result_str": json.dumps({"error": f"工具执行异常: {raw}"}, ensure_ascii=False),
                })
            else:
                results.append(raw)

        return results

    def _prepare_for_storage(self, tool_content: str, tool_name: str) -> str:
        """存储时进一步压缩工具结果，保留核心摘要信息"""
        from app.agent.core.config import TOOL_RESULT_STORAGE_LIMIT

        if len(tool_content) <= TOOL_RESULT_STORAGE_LIMIT:
            return tool_content

        # 尝试 JSON 结构感知压缩
        try:
            import json as _json
            data = _json.loads(tool_content)
            if isinstance(data, dict):
                # 优先保留关键字段
                priority_keys = ["success", "error", "message", "summary", "conclusion",
                               "recommendation", "total_count", "status"]
                compact = {}
                for key in priority_keys:
                    if key in data:
                        compact[key] = data[key]
                # 如果有 items/data/results 列表，只保留前3条
                for list_key in ["items", "data", "results", "records"]:
                    if list_key in data and isinstance(data[list_key], list):
                        compact[list_key] = data[list_key][:3]
                        compact[f"_{list_key}_total"] = len(data[list_key])
                compact["_storage_compressed"] = True
                result = _json.dumps(compact, ensure_ascii=False)
                if len(result) <= TOOL_RESULT_STORAGE_LIMIT:
                    return result
        except (json.JSONDecodeError, TypeError):
            pass

        # 纯文本回退：保留前2/3 + 截断标记
        limit = TOOL_RESULT_STORAGE_LIMIT - 100
        return tool_content[:limit] + "\n\n[... 存储已压缩，完整结果已截断 ...]"

    def _strip_dsml_tags(self, content: str) -> str:
        """检测并移除 DeepSeek 降级模式下输出的 DSML 格式工具调用标签。
        当 API 工具调用失败时，DeepSeek 会在纯文本中输出 DSML 格式，需要过滤。
        同时处理裸 JSON 工具调用和孤立/畸形标签。"""
        if not content:
            return content
        original = content
        # 1. 匹配完整的 DSML 格式工具调用块
        cleaned = self._DSML_FULL_PATTERN.sub('', content)
        # 2. 也处理不完整的 DSML 标签（可能在流式输出中被截断）
        cleaned = self._DSML_PARTIAL_PATTERN.sub('', cleaned)
        # 3. 移除裸 JSON 工具调用
        cleaned = self._BARE_JSON_TOOL_PATTERN.sub('', cleaned)
        # 4. 移除孤立/畸形标签
        cleaned = self._ORPHAN_TAG_PATTERN.sub('', cleaned)
        if cleaned != original:
            logger.warning(
                "[Agent] 检测到 DSML/工具调用格式标签并已过滤，"
                "这通常意味着工具定义 schema 存在问题导致 LLM 降级为纯文本模式"
            )
        # 5. 清理多余空行
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()

    # 内部思考过程开头特征正则（只截断开头连续的思考段落，保留正文）
    _THINKING_PREFIX_PATTERN = re.compile(
        r'^(?:好[的]?[，,].*?(?:\n\n|$)|'
        r'首先[，,].*?(?:\n\n|$)|'
        r'接下来[，,].*?(?:\n\n|$)|'
        r'最后[，,].*?(?:\n\n|$)|'
        r'用户之前.*?(?:\n\n|$)|'
        r'我需要.*?(?:\n\n|$)|'
        r'我将.*?(?:\n\n|$)|'
        r'现在[我看].*?(?:\n\n|$)|'
        r'让我[来们]?[看看查].*?(?:\n\n|$)|'
        r'根据.*?数据.*?(?:\n\n|$)|'
        r'看来.*?(?:\n\n|$)|'
        r'先[查询看做].*?(?:\n\n|$))+',
        re.DOTALL,
    )

    def _strip_internal_thinking(self, content: str) -> str:
        """剔除输出开头连续的内部思考段落，保留正式报告正文。

        仅处理开头的思考段，避免误删正文中的合理连接词。
        """
        if not content:
            return content
        cleaned = self._THINKING_PREFIX_PATTERN.sub('', content, count=1).lstrip()
        if cleaned != content.lstrip():
            logger.warning("[Agent] 检测到输出开头包含内部思考段落，已自动剔除")
        return cleaned

    def _check_next_step(self, tool_results: list[dict]) -> str | None:
        """检查工具返回结果中是否包含 next_step 指引。

        Args:
            tool_results: 工具执行结果列表，每个元素包含 result 字段

        Returns:
            如果存在 next_step，返回强制指令文本；否则返回 None
        """
        for result in tool_results:
            try:
                result_data = result.get("result", {})
                if isinstance(result_data, str):
                    result_data = json.loads(result_data)

                # 从 result.data.next_step 提取
                data = result_data.get("data", {}) if isinstance(result_data, dict) else {}
                next_step = data.get("next_step") if isinstance(data, dict) else None

                if next_step and isinstance(next_step, dict):
                    action = next_step.get("action", "")
                    params = next_step.get("suggested_params", {})
                    if action:
                        params_text = json.dumps(params, ensure_ascii=False, indent=2) if params else "{}"
                        return (
                            f"[系统建议] 上一步工具返回了 next_step 指引，强烈建议立即调用 {action} 工具以完成完整分析流程。"
                            f"预组装参数如下，请直接使用：\n{params_text}\n"
                            f"若用户明确表示只需查看推荐结果而不需要对比回测，可跳过此步骤；否则应按指引执行。"
                        )
            except (TypeError, ValueError, AttributeError):
                continue
        return None

    def _check_round_limit_warning(self, round_idx: int) -> str | None:
        """轮次预警：阶梯式提醒模型收敛"""
        from app.agent.core.config import AGENT_WARN_ROUND, AGENT_FORCE_CONCLUDE_ROUND

        current_round = round_idx + 1  # 转为 1-based
        max_rounds = self.max_tool_rounds

        if current_round >= AGENT_FORCE_CONCLUDE_ROUND:
            return (
                f"[强制收敛] 已使用 {current_round}/{max_rounds} 轮工具调用。"
                "你必须在本轮直接输出最终分析结论，不得再调用任何工具。"
                "【输出要求】直接输出面向用户的专业分析结论，禁止以第一/第二人称陈述思考过程，禁止描述工具调用过程和字段错误。"
            )
        elif current_round >= AGENT_WARN_ROUND:
            return (
                f"[System] 已使用 {current_round}/{max_rounds} 轮工具调用。"
                "请尽快基于已有数据输出分析结论。"
                "如果工具返回的数据已被截断，请直接基于可见部分分析，不要重复调用。"
                "【输出要求】直接输出面向用户的专业分析结论，禁止以第一/第二人称陈述思考过程，禁止描述工具调用过程和字段错误。"
            )
        return None
    
    def _check_token_budget_warning(self, messages: list[dict]) -> str | None:
        """当工具结果累积 token 超过预算80%时提醒模型收敛"""
        from app.agent.core.config import CONTEXT_BUDGET, MAX_CONTEXT_TOKENS
    
        tool_budget = int(MAX_CONTEXT_TOKENS * CONTEXT_BUDGET.get("tool_results", 0.15))
        tool_tokens = sum(
            self._estimate_tokens(m.get("content", ""))
            for m in messages if m.get("role") == "tool"
        )
    
        if tool_tokens > tool_budget * 0.8:
            return (
                f"[数据量预警] 工具结果已累积约 {tool_tokens} tokens（预算上限 {tool_budget}），"
                "请基于已有数据直接给出分析结论，避免继续调用工具。"
            )
        return None
    
    def _estimate_tokens(self, text: str) -> int:
        """简单的 token 估算（混合语言粗估：平均 3 字符 ≈ 1 token）"""
        if not text:
            return 0
        return len(text) // 3

    def _detect_tool_names_in_text(self, text: str, available_tools: list[dict]) -> list[str]:
        """检测文本中是否包含已知工具名，返回找到的工具名列表（保留给调试/日志使用）"""
        tool_names = [
            t["function"]["name"] for t in available_tools
            if "function" in t and "name" in t["function"]
        ]
        return [name for name in tool_names if name in text]

    # --- 渐进式意图检测配套正则 ---
    # 明确「我要调工具」的行动动词（第一/第二人称 + 马上要做的动作）
    _ACTION_INTENT_PATTERN = re.compile(
        r"(?:"
        r"我(?:将|会|来|现在|马上|需要|打算|准备)\s*[^。！？\n]{0,8}?(?:调用|使用|执行|查询|计算|分析|回测|对比|获取|生成|创建|检索)"
        r"|(?:正在|即将|下面|接下来)\s*[^。！？\n]{0,8}?(?:调用|查询|计算|分析|回测|对比|获取|生成|检索)"
        r"|调用\s*(?:以下|如下)?\s*工具"
        r"|(?:执行|发起)\s*(?:工具调用|函数调用|tool[_\s-]?call)"
        r")",
        re.IGNORECASE,
    )
    # 「信息告知」资源描述性语气 — 系统能做什么，不是当前要做什么
    _INFO_DESCRIPTION_PATTERN = re.compile(
        r"(?:系统|平台|本助手|我们|目前|当前).{0,20}?(?:可以|支持|提供|包含|包括|具备|拥有|内置)"
        r"|(?:可以|支持|提供|包含|包括)\s*(?:以下|如下|这些|多种)?\s*(?:工具|功能|数据|接口|能力|模型|策略)"
        r"|(?:有哪些|哪些).{0,20}?(?:工具|功能|数据|接口|能力|模型|策略|集合)",
    )
    # 明确格式信号：已经在输出 tool_call 但格式不完整
    _TOOL_CALL_TAG_PATTERN = re.compile(
        r'<\s*tool[_\s-]?call\s*>|```\s*tool[_\s-]?call'
        r'|<[\s\uff5c|][^>]*(?:function_calls|tool_calls)'
        r'|<[/]?\s*[\uff5c|]+\s*DSML\s*[\uff5c|]+'
        r'|"name"\s*:\s*"\w+"\s*,\s*"arguments"',
        re.IGNORECASE,
    )

    def _detect_tool_intent(
        self, text: str, available_tools: list[dict],
    ) -> tuple[bool, list[str], str]:
        """渐进式检测 LLM 文本中是否存在「真实调用工具的意图」。

        返回 ``(need_retry, hit_tool_names, reason)``：
        - need_retry=True 表示应触发 `_FORMAT_RETRY_PROMPT` 让 LLM 重新以 ``<tool_call>`` 形式输出；
        - need_retry=False 表示 LLM 是在介绍能力 / 直接回答，**不应**逼它再去调工具。

        三步判定（按优先级）：
          1) 文本中已出现 ``<tool_call>`` 等格式标签 → 说明 LLM 是要调用只是格式坏了，**重试**；
          2) 信息告知语气（"系统支持…""有哪些工具…"）→ **不重试**；
          3) 行动意图（"我将调用…""正在查询…"）+ 命中具体工具名 → **重试**。
          其他情况（只是文本中恰好写到了工具名）→ **不重试**，让 LLM 的直答通过。
        """
        if not text:
            return False, [], "empty_text"

        tool_names = [
            t["function"]["name"] for t in available_tools
            if "function" in t and "name" in t["function"]
        ]
        hit_names = [n for n in tool_names if n in text]

        # 步骤1：已出现工具调用标签 → 格式错误，必须重试
        if self._TOOL_CALL_TAG_PATTERN.search(text):
            return True, hit_names, "tool_call_tag_detected"

        if not hit_names:
            # 没提到任何工具名，直接放行
            return False, [], "no_tool_name"

        # 步骤2：判定是否为「信息告知」语气 — 用户问能力/有什么数据时最常见
        is_info_mode = bool(self._INFO_DESCRIPTION_PATTERN.search(text))

        # 步骤3：判定是否为「行动意图」语气
        is_action_mode = bool(self._ACTION_INTENT_PATTERN.search(text))

        # 行动意图优先于信息告知（两者都命中时，以行动为准）
        if is_action_mode:
            return True, hit_names, "action_intent_detected"

        # 纯信息告知 → 放行
        if is_info_mode:
            return False, hit_names, "info_description_mode"

        # 既没有明确行动意图、也不是信息告知 — 文本只是无意提到了工具名，放行
        return False, hit_names, "neutral_mention"

    # ------------------------------------------------------------------
    # 非流式运行
    # ------------------------------------------------------------------
    async def run(
        self,
        messages: list[dict],
        tool_context: dict | None = None,
        active_toolsets: list[str] | None = None,
    ) -> dict:
        """
        非流式运行：完成所有工具调用后返回最终回复。

        Args:
            messages: 消息列表
            tool_context: 传递给工具 execute() 的额外上下文（如 user_id, conversation_id）
            active_toolsets: 活跃工具集名称列表（来自 Skill 的 toolset），为 None 时使用全量工具

        Returns:
            dict: {"content": str, "tool_calls": list[dict], "tool_calls_raw": list[dict]}
        """
        self._active_scenes.clear()
        tool_context = dict(tool_context or {})
        tool_context["_active_scenes"] = self._active_scenes
        working_messages = list(messages)
        all_tool_calls: list[dict] = []
        all_tool_calls_raw: list[dict] = []  # OpenAI API 原始格式
        # 已执行工具集合，用于依赖检查
        executed_tools: set[str] = set()
        # 工具连续失败计数器，用于避免重复失败
        tool_failure_counts: dict[str, int] = {}
        # 工具调用去重缓存
        _tool_dedup_cache: dict[str, dict] = {}

        for round_idx in range(self.max_tool_rounds):
            # 每轮重新计算工具列表，支持运行时动态注入
            merged_toolsets = list(active_toolsets) if active_toolsets else []
            if self._active_scenes:
                merged_toolsets = list(set(merged_toolsets) | self._active_scenes)
            if merged_toolsets:
                openai_tools = self.tool_registry.get_filtered_openai_tools(merged_toolsets)
                if not openai_tools:
                    logger.warning(
                        "[Agent] 过滤后工具列表为空，退回全量工具",
                        extra={"toolsets": merged_toolsets},
                    )
                    openai_tools = self.tool_registry.get_openai_tools()
                logger.info("[Agent] 使用过滤工具集: {}", merged_toolsets)
            else:
                openai_tools = self.tool_registry.get_openai_tools()

            logger.info("Agent run - 第 {} 轮调用 LLM", round_idx + 1)

            # 轮次预警 + Token 预算预警
            round_warning = self._check_round_limit_warning(round_idx)
            token_warning = self._check_token_budget_warning(working_messages)
            warnings = [w for w in [round_warning, token_warning] if w]
            if warnings:
                warning_text = "\n".join(warnings)
                working_messages.append({"role": "system", "content": warning_text})

            response = await self._call_llm_with_retry(working_messages, tools=openai_tools)

            # 没有工具调用 → 判定是否存在「真实调用工具的意图」再决定是否触发格式化重试
            if not response.get("tool_calls"):
                content = response.get("content") or ""
                need_retry, detected_tools, intent_reason = self._detect_tool_intent(
                    content, openai_tools,
                )
                if need_retry and openai_tools:
                    logger.info(
                        "[Agent] 检测到真实调用意图({}), 触发格式化重试",
                        intent_reason,
                        extra={"detected_tools": detected_tools, "round": round_idx + 1},
                    )
                    retry_messages = working_messages + [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": _FORMAT_RETRY_PROMPT},
                    ]
                    retry_response = await self._call_llm_with_retry(
                        retry_messages, tools=openai_tools,
                    )
                    if retry_response.get("tool_calls"):
                        logger.info(
                            "[Agent] 格式化重试成功",
                            extra={"tool_count": len(retry_response["tool_calls"])},
                        )
                        # 将中间消息追加到 working_messages（保持对话连贯性）
                        working_messages.append({"role": "assistant", "content": content})
                        working_messages.append({"role": "user", "content": _FORMAT_RETRY_PROMPT})
                        response = retry_response
                        # 不 return，继续走下面的工具执行流程
                    else:
                        logger.info("[Agent] 格式化重试未产生工具调用，返回原始响应")
                        content = self._strip_dsml_tags(content)
                        return {
                            "content": content,
                            "tool_calls": all_tool_calls,
                            "tool_calls_raw": all_tool_calls_raw if all_tool_calls_raw else None,
                        }
                else:
                    content = self._strip_dsml_tags(content)
                    return {
                        "content": content,
                        "tool_calls": all_tool_calls,
                        "tool_calls_raw": all_tool_calls_raw if all_tool_calls_raw else None,
                    }

            # 处理工具调用
            tool_calls = response["tool_calls"]

            # 保留 OpenAI API 原始格式的 tool_calls
            round_tool_calls_raw = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                }
                for tc in tool_calls
            ]
            all_tool_calls_raw.extend(round_tool_calls_raw)

            # 将 assistant 消息（含 tool_calls）追加到上下文
            assistant_msg: dict = {"role": "assistant", "content": response.get("content") or ""}
            assistant_msg["tool_calls"] = tool_calls
            working_messages.append(assistant_msg)

            # 日志记录所有待执行工具
            tool_names = [tc["function"]["name"] for tc in tool_calls]
            if len(tool_calls) > 1:
                logger.info("[Agent] 并行执行 {} 个工具: {}", len(tool_calls), tool_names)
            else:
                logger.info("[Agent] 执行工具: {}", tool_names[0])

            # 去重检查：相同工具+参数不重复执行
            exec_tool_calls = []
            dedup_results: dict[int, dict] = {}
            _batch_seen_keys: dict[str, int] = {}  # 同一轮内去重
            for i, tc in enumerate(tool_calls):
                tc_name = tc["function"]["name"]
                tc_args = tc["function"].get("arguments", "{}") or "{}"
                try:
                    _pa = json.loads(tc_args)
                    # 可视化工具特殊处理：按 chart_type + title 去重
                    if tc_name == "data_visualize":
                        _ct = _pa.get("chart_type", "")
                        _cfg = _pa.get("config") or {}
                        if isinstance(_cfg, str):
                            try:
                                _cfg = json.loads(_cfg)
                            except (json.JSONDecodeError, ValueError):
                                _cfg = {}
                        if not isinstance(_cfg, dict):
                            _cfg = {}
                        _tt = _cfg.get("title", "")
                        dedup_key = f"{tc_name}::chart={_ct}::title={_tt}"
                    else:
                        dedup_key = f"{tc_name}::{json.dumps(_pa, sort_keys=True, ensure_ascii=False)}"
                except (json.JSONDecodeError, TypeError):
                    dedup_key = f"{tc_name}::{tc_args}"

                if dedup_key in _tool_dedup_cache:
                    logger.info("[Agent] 工具调用去重命中: {}", tc_name)
                    cached = _tool_dedup_cache[dedup_key]
                    dedup_results[i] = {
                        "tool_call_id": tc["id"],
                        "result": cached["result"],
                        "result_str": cached["result_str"] + '\n{"_dedup_hint": "该工具已使用相同参数执行过，结果与上次相同。请基于已有数据分析，勿再重复调用。"}',
                        "success": cached["success"],
                    }
                elif dedup_key in _batch_seen_keys:
                    logger.info("[Agent] 同轮内去重: {} 与本轮已提交的调用重复", tc_name)
                    dedup_results[i] = {"_pending_copy_from_key": dedup_key, "tool_call_id": tc["id"]}
                else:
                    _batch_seen_keys[dedup_key] = len(exec_tool_calls)
                    exec_tool_calls.append({**tc, "_dedup_key": dedup_key, "_sorted_idx": i})

            # 并行执行未命中缓存的工具
            if exec_tool_calls:
                exec_results = await self._execute_tools_parallel(
                    exec_tool_calls, executed_tools, tool_failure_counts, tool_context
                )
                for ei, etc in enumerate(exec_tool_calls):
                    sorted_idx = etc["_sorted_idx"]
                    dedup_results[sorted_idx] = exec_results[ei]
                    if exec_results[ei].get("success"):
                        _tool_dedup_cache[etc["_dedup_key"]] = exec_results[ei]

            # 处理同轮内去重的待复制结果
            for idx, r in list(dedup_results.items()):
                if isinstance(r, dict) and "_pending_copy_from_key" in r:
                    copy_key = r["_pending_copy_from_key"]
                    if copy_key in _tool_dedup_cache:
                        cached = _tool_dedup_cache[copy_key]
                        dedup_results[idx] = {
                            "tool_call_id": r["tool_call_id"],
                            "result": cached["result"],
                            "result_str": cached["result_str"] + '\n{"_dedup_hint": "本轮已执行过相同图表/分析，结果相同。"}',
                            "success": cached["success"],
                        }
                    else:
                        dedup_results[idx] = {
                            "tool_call_id": r["tool_call_id"],
                            "result": {"success": False, "error": "重复调用已跳过"},
                            "result_str": '{"_dedup_hint": "本轮已有相同调用但执行失败，请不要重复调用。"}',
                            "success": False,
                        }

            # 按原顺序处理结果
            for idx, tc in enumerate(tool_calls):
                result = dedup_results[idx]
                func_name = tc["function"]["name"]

                # 解析参数（与原代码保持一致）
                try:
                    args = json.loads(tc["function"].get("arguments", "{}") or "{}")
                except json.JSONDecodeError:
                    args = {}

                all_tool_calls.append({
                    "name": func_name,
                    "arguments": args,
                    "result": result["result"],
                    "result_str_storage": self._prepare_for_storage(result["result_str"], func_name),
                })

                # 追加 tool 角色消息
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "content": result["result_str"],
                })

            # 检查 next_step 并注入强制指令
            next_step_directive = self._check_next_step(list(dedup_results.values()))
            if next_step_directive:
                working_messages.append({
                    "role": "system",
                    "content": next_step_directive,
                })
                logger.info("next_step_directive_injected", extra={"directive": next_step_directive[:100]})

        # 超过最大轮次 → 优雅降级：做最终一次无工具调用生成总结
        logger.warning("Agent 工具调用达到最大轮次 {}", self.max_tool_rounds)
        working_messages.append({
            "role": "system",
            "content": (
                "[System] 已达到最大工具调用轮次。请直接输出面向用户的最终专业分析结论和总结，遵守以下硬性要求：\n"
                "1. 以中性专业报告口吻表达，不使用第一人称（我/我们）或第二人称（您/你）；\n"
                "2. 禁止输出内部思考过程（如“好的，用户之前…”“首先，需要回顾…”“接下来…”“最后，确保…”）；\n"
                "3. 禁止描述系统或工具调用细节（如“工具调用失败”“轮次限制”“字段名错误”“data_query 返回空结果”）；\n"
                "4. 直接以结构化标题/要点组织内容（如《核心风险全景》《行业分布》《主要结论》《建议》）；\n"
                "5. 若数据不足，以一句简短客观说明（如“当前样本覆盖有限”），不展开技术细节。"
            )
        })
        response = await self._call_llm_with_retry(working_messages, tools=None)
        content = self._strip_dsml_tags(response.get("content") or "")
        content = self._strip_internal_thinking(content)
        return {
            "content": content,
            "tool_calls": all_tool_calls,
            "tool_calls_raw": all_tool_calls_raw if all_tool_calls_raw else None,
        }

    # ------------------------------------------------------------------
    # 流式运行
    # ------------------------------------------------------------------
    async def run_stream(
        self,
        messages: list[dict],
        tool_context: dict | None = None,
        active_toolsets: list[str] | None = None,
    ):
        """
        流式运行：yield SSE 事件字典。

        Args:
            messages: 消息列表
            tool_context: 传递给工具 execute() 的额外上下文（如 user_id, conversation_id）
            active_toolsets: 活跃工具集名称列表（来自 Skill 的 toolset），为 None 时使用全量工具

        Yields:
            dict 形如:
              {"event": "text_delta", "data": {"content": str}}
              {"event": "tool_start", "data": {"name": str, "arguments": str}}
              {"event": "tool_result", "data": {"name": str, "result": dict}}
              {"event": "message_end", "data": {"tool_calls": list}}
        """
        self._active_scenes.clear()
        tool_context = dict(tool_context or {})
        tool_context["_active_scenes"] = self._active_scenes
        working_messages = list(messages)
        all_tool_calls: list[dict] = []
        all_tool_calls_raw: list[dict] = []  # OpenAI API 原始格式
        # 已执行工具集合，用于依赖检查
        executed_tools: set[str] = set()
        # 工具连续失败计数器，用于避免重复失败
        tool_failure_counts: dict[str, int] = {}
        # 工具调用去重缓存： key=(tool_name, normalized_args) -> result_str。
        # 相同工具+相同参数在同一会话中不重复执行，直接返回上次结果。
        _tool_dedup_cache: dict[str, dict] = {}

        for round_idx in range(self.max_tool_rounds):
            # 每轮重新计算工具列表，支持运行时动态注入
            merged_toolsets = list(active_toolsets) if active_toolsets else []
            if self._active_scenes:
                merged_toolsets = list(set(merged_toolsets) | self._active_scenes)
            if merged_toolsets:
                openai_tools = self.tool_registry.get_filtered_openai_tools(merged_toolsets)
                if not openai_tools:
                    logger.warning(
                        "[Agent stream] 过滤后工具列表为空，退回全量工具",
                        extra={"toolsets": merged_toolsets},
                    )
                    openai_tools = self.tool_registry.get_openai_tools()
                logger.info("[Agent stream] 使用过滤工具集: {}", merged_toolsets)
            else:
                openai_tools = self.tool_registry.get_openai_tools()

            logger.info("Agent run_stream - 第 {} 轮调用 LLM", round_idx + 1)

            # 轮次预警 + Token 预算预警
            round_warning = self._check_round_limit_warning(round_idx)
            token_warning = self._check_token_budget_warning(working_messages)
            warnings = [w for w in [round_warning, token_warning] if w]
            if warnings:
                warning_text = "\n".join(warnings)
                working_messages.append({"role": "system", "content": warning_text})

            # 收集流式响应
            full_content = ""
            # 缓冲本轮 text_delta，中间轮次（有 tool_calls）不推送给前端，避免泄露思考过程
            _round_text_buffer: list[str] = []
            # tool_calls 按 index 累积: {index: {"id": ..., "name": ..., "arguments": ...}}
            pending_tool_calls: dict[int, dict] = {}
            finish_reason: str | None = None

            async for chunk in self._call_llm_stream_with_retry(working_messages, tools=openai_tools):
                chunk_type = chunk["type"]

                if chunk_type == "content_delta":
                    full_content += chunk["content"]
                    # 先缓冲，不立即推送：等本轮结束后根据是否有 tool_calls 决定是否输出
                    _round_text_buffer.append(chunk["content"])

                elif chunk_type == "tool_call_delta":
                    idx = chunk["index"]
                    if idx not in pending_tool_calls:
                        pending_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                    tc = pending_tool_calls[idx]
                    if "id" in chunk:
                        tc["id"] = chunk["id"]
                    if "name" in chunk:
                        tc["name"] += chunk["name"]
                    if "arguments" in chunk:
                        tc["arguments"] += chunk["arguments"]

                elif chunk_type == "finish":
                    finish_reason = chunk["finish_reason"]

            # 没有工具调用 → 最终回复轮：刷新缓冲的文字给前端
            if not pending_tool_calls:
                # 将缓冲的 text_delta 逐条推送
                for _buf_chunk in _round_text_buffer:
                    yield {"event": "text_delta", "data": {"content": _buf_chunk}}
                _round_text_buffer.clear()

                need_retry, detected_tools, intent_reason = self._detect_tool_intent(
                    full_content, openai_tools,
                )
                if need_retry and openai_tools:
                    logger.info(
                        "[Agent stream] 检测到真实调用意图({}), 触发格式化重试",
                        intent_reason,
                        extra={"detected_tools": detected_tools, "round": round_idx + 1},
                    )
                    retry_messages = working_messages + [
                        {"role": "assistant", "content": full_content},
                        {"role": "user", "content": _FORMAT_RETRY_PROMPT},
                    ]
                    retry_response = await self._call_llm_with_retry(
                        retry_messages, tools=openai_tools,
                    )
                    if retry_response.get("tool_calls"):
                        logger.info(
                            "[Agent stream] 格式化重试成功",
                            extra={"tool_count": len(retry_response["tool_calls"])},
                        )
                        # 将中间消息追加到 working_messages（保持对话连贯性）
                        working_messages.append({"role": "assistant", "content": full_content})
                        working_messages.append({"role": "user", "content": _FORMAT_RETRY_PROMPT})
                        # 将重试得到的 tool_calls 转换为 pending_tool_calls 格式
                        for i, tc in enumerate(retry_response["tool_calls"]):
                            pending_tool_calls[i] = {
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "arguments": tc["function"].get("arguments", ""),
                            }
                        # 更新 full_content 为重试响应内容
                        full_content = retry_response.get("content") or ""
                        # 不 return，继续走下面的工具执行流程
                    else:
                        logger.info("[Agent stream] 格式化重试未产生工具调用，返回原始响应")
                        cleaned_content = self._strip_dsml_tags(full_content)
                        cleaned_content = self._strip_internal_thinking(cleaned_content)
                        if cleaned_content != full_content and cleaned_content:
                            yield {"event": "text_replace", "data": {"content": cleaned_content}}
                        yield {
                            "event": "message_end",
                            "data": {
                                "tool_calls": all_tool_calls,
                                "tool_calls_raw": all_tool_calls_raw if all_tool_calls_raw else None,
                            },
                        }
                        return
                else:
                    cleaned_content = self._strip_dsml_tags(full_content)
                    cleaned_content = self._strip_internal_thinking(cleaned_content)
                    if cleaned_content != full_content and cleaned_content:
                        yield {"event": "text_replace", "data": {"content": cleaned_content}}
                    yield {
                        "event": "message_end",
                        "data": {
                            "tool_calls": all_tool_calls,
                            "tool_calls_raw": all_tool_calls_raw if all_tool_calls_raw else None,
                        },
                    }
                    return

            # ── 本轮有工具调用 → 丢弃缓冲的思考文字，不推送给前端 ──
            if _round_text_buffer:
                logger.info(
                    "[Agent stream] 第 {} 轮存在工具调用，抑制 {} 字符的内部思考文字",
                    round_idx + 1, len(full_content),
                )
                _round_text_buffer.clear()

            # 构造 assistant 消息
            sorted_tcs = [pending_tool_calls[k] for k in sorted(pending_tool_calls)]
            assistant_tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in sorted_tcs
            ]
            all_tool_calls_raw.extend(assistant_tool_calls)
            working_messages.append({
                "role": "assistant",
                "content": full_content or "",
                "tool_calls": assistant_tool_calls,
            })

            # 中间轮次的 full_content 是“思考 + tool_call 指令”，不应暴露给用户。
            # 通过 text_replace(content="") 通知 chat_service/前端：清空本轮累积，
            # 避免未清洗的 DSML/裸 JSON/思考文字持久化到最终 assistant message。
            if full_content:
                yield {"event": "text_replace", "data": {"content": ""}}

            # 先 yield 所有 tool_start 事件
            for tc_raw in sorted_tcs:
                func_name = tc_raw["name"]
                func_args_str = tc_raw["arguments"]
                yield {"event": "tool_start", "data": {"name": func_name, "arguments": func_args_str}}

            # 构造执行用的 tool_call 格式，并进行去重检查
            exec_tool_calls = []
            dedup_results: dict[int, dict] = {}  # idx -> cached result
            _batch_seen_keys: dict[str, int] = {}  # 同一轮内的去重（key -> first idx in exec_tool_calls）
            for i, tc_raw in enumerate(sorted_tcs):
                tc_name = tc_raw["name"]
                tc_args = tc_raw["arguments"] or "{}"
                # 标准化参数用于去重 key
                try:
                    _parsed_args = json.loads(tc_args)
                    # 可视化工具特殊处理：按 chart_type + title 去重（因为 data_source 可能略有不同但产出相同图表）
                    if tc_name == "data_visualize":
                        _chart_type = _parsed_args.get("chart_type", "")
                        _cfg = _parsed_args.get("config") or {}
                        if isinstance(_cfg, str):
                            try:
                                _cfg = json.loads(_cfg)
                            except (json.JSONDecodeError, ValueError):
                                _cfg = {}
                        if not isinstance(_cfg, dict):
                            _cfg = {}
                        _title = _cfg.get("title", "")
                        dedup_key = f"{tc_name}::chart={_chart_type}::title={_title}"
                    else:
                        dedup_key = f"{tc_name}::{json.dumps(_parsed_args, sort_keys=True, ensure_ascii=False)}"
                except (json.JSONDecodeError, TypeError):
                    dedup_key = f"{tc_name}::{tc_args}"

                if dedup_key in _tool_dedup_cache:
                    logger.info("[Agent stream] 工具调用去重命中: {} 直接返回缓存结果", tc_name)
                    cached = _tool_dedup_cache[dedup_key]
                    dedup_results[i] = {
                        "tool_call_id": tc_raw["id"],
                        "result": cached["result"],
                        "result_str": cached["result_str"] + '\n{"_dedup_hint": "该工具已使用相同参数执行过，结果与上次相同。请基于已有数据分析，勿再重复调用。"}',
                        "success": cached["success"],
                    }
                elif dedup_key in _batch_seen_keys:
                    # 同一轮内重复的工具调用，标记为待复制（执行后从第一个结果复制）
                    logger.info("[Agent stream] 同轮内去重: {} 与本轮已提交的调用重复", tc_name)
                    dedup_results[i] = {"_pending_copy_from_key": dedup_key, "tool_call_id": tc_raw["id"]}
                else:
                    _batch_seen_keys[dedup_key] = len(exec_tool_calls)
                    exec_tool_calls.append({
                        "id": tc_raw["id"],
                        "function": {"name": tc_raw["name"], "arguments": tc_raw["arguments"]},
                        "_dedup_key": dedup_key,
                        "_sorted_idx": i,
                    })

            # 并行执行（仅执行未命中去重缓存的工具），并在执行期间定期 yield 心跳事件
            if exec_tool_calls:
                if len(exec_tool_calls) > 1:
                    logger.info("[Agent stream] 并行执行 {} 个工具", len(exec_tool_calls))
                else:
                    only = exec_tool_calls[0]["function"].get("name", "")
                    logger.info("[Agent stream] 执行工具: {}", only)

                # 使用 asyncio.Task 包装，在等待期间 yield 心跳
                _exec_task = asyncio.create_task(
                    self._execute_tools_parallel(
                        exec_tool_calls, executed_tools, tool_failure_counts, tool_context
                    )
                )
                _heartbeat_interval = 8  # 每8秒发送心跳
                _exec_start = time.time()
                while not _exec_task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(_exec_task), timeout=_heartbeat_interval)
                    except asyncio.TimeoutError:
                        _elapsed = time.time() - _exec_start
                        _tool_names = [tc["function"].get("name", "") for tc in exec_tool_calls]
                        logger.debug("[Agent stream] 工具执行中... 已耗时{:.0f}s, 工具: {}", _elapsed, _tool_names)
                        yield {"event": "heartbeat", "data": {"elapsed": int(_elapsed), "tools": _tool_names}}
                    except Exception:
                        break

                # 获取执行结果
                try:
                    exec_results = _exec_task.result()
                except Exception as _exec_err:
                    logger.error("[Agent stream] 工具执行任务异常: {}", _exec_err)
                    exec_results = [
                        {
                            "tool_call_id": tc.get("id", ""),
                            "result": {"error": str(_exec_err)},
                            "result_str": json.dumps({"error": f"工具执行异常: {_exec_err}"}, ensure_ascii=False),
                            "success": False,
                        }
                        for tc in exec_tool_calls
                    ]

                # 缓存新执行的结果并合并到按索引的结果字典
                for ei, etc in enumerate(exec_tool_calls):
                    sorted_idx = etc["_sorted_idx"]
                    dedup_results[sorted_idx] = exec_results[ei]
                    # 存入去重缓存（仅缓存成功结果）
                    if exec_results[ei].get("success"):
                        _tool_dedup_cache[etc["_dedup_key"]] = exec_results[ei]
            elif not dedup_results:
                logger.warning("[Agent stream] 无工具需执行")

            # 处理同轮内去重的待复制结果
            for idx, r in list(dedup_results.items()):
                if isinstance(r, dict) and "_pending_copy_from_key" in r:
                    copy_key = r["_pending_copy_from_key"]
                    if copy_key in _tool_dedup_cache:
                        cached = _tool_dedup_cache[copy_key]
                        dedup_results[idx] = {
                            "tool_call_id": r["tool_call_id"],
                            "result": cached["result"],
                            "result_str": cached["result_str"] + '\n{"_dedup_hint": "本轮已执行过相同图表/分析，结果相同，请勿重复生成。"}',
                            "success": cached["success"],
                        }
                    else:
                        # 执行失败时没进缓存，返回提示
                        dedup_results[idx] = {
                            "tool_call_id": r["tool_call_id"],
                            "result": {"success": False, "error": "重复调用已跳过"},
                            "result_str": '{"_dedup_hint": "本轮已有相同调用但执行失败，请不要重复调用。"}',
                            "success": False,
                        }

            # 按原始顺序处理结果并 yield
            for idx, tc_raw in enumerate(sorted_tcs):
                result = dedup_results[idx]
                func_name = tc_raw["name"]

                try:
                    args = json.loads(tc_raw["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}

                all_tool_calls.append({
                    "name": func_name,
                    "arguments": args,
                    "result": result["result"],
                    "result_str_storage": self._prepare_for_storage(result["result_str"], func_name),
                })

                yield {"event": "tool_result", "data": {"name": func_name, "result": result["result"]}}

                working_messages.append({
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "content": result["result_str"],
                })

            # 检查 next_step 并注入强制指令
            next_step_directive = self._check_next_step(list(dedup_results.values()))
            if next_step_directive:
                working_messages.append({
                    "role": "system",
                    "content": next_step_directive,
                })
                logger.info("next_step_directive_injected", extra={"directive": next_step_directive[:100]})

        # 超过最大轮次 → 优雅降级：做最后一次无工具的流式调用生成总结
        logger.warning("Agent stream 工具调用达到最大轮次 {}", self.max_tool_rounds)
        working_messages.append({
            "role": "system",
            "content": (
                "[System] 已达到最大工具调用轮次。请直接输出面向用户的最终专业分析结论和总结，遵守以下硬性要求：\n"
                "1. 以中性专业报告口吻表达，不使用第一人称（我/我们）或第二人称（您/你）；\n"
                "2. 禁止输出内部思考过程（如“好的，用户之前…”“首先，需要回顾…”“接下来…”“最后，确保…”）；\n"
                "3. 禁止描述系统或工具调用细节（如“工具调用失败”“轮次限制”“字段名错误”“data_query 返回空结果”）；\n"
                "4. 直接以结构化标题/要点组织内容（如《核心风险全景》《行业分布》《主要结论》《建议》）；\n"
                "5. 若数据不足，以一句简短客观说明（如“当前样本覆盖有限”），不展开技术细节。"
            )
        })
        final_content = ""
        async for chunk in self._call_llm_stream_with_retry(working_messages, tools=None):
            chunk_type = chunk["type"]
            if chunk_type == "content_delta":
                final_content += chunk["content"]
                yield {"event": "text_delta", "data": {"content": chunk["content"]}}

        # 对最终总结内容做 DSML 过滤 + 内部思考开头剔除
        cleaned_final = self._strip_dsml_tags(final_content)
        cleaned_final = self._strip_internal_thinking(cleaned_final)
        if cleaned_final != final_content and cleaned_final:
            yield {"event": "text_replace", "data": {"content": cleaned_final}}

        yield {
            "event": "message_end",
            "data": {
                "tool_calls": all_tool_calls,
                "tool_calls_raw": all_tool_calls_raw if all_tool_calls_raw else None,
            },
        }


