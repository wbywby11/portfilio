"""
投资研究 Agent - ReAct 循环主控逻辑

核心能力：推理+行动的多轮工具调用循环，支持流式和非流式。
"""
import asyncio
import json
import time

from loguru import logger

from app.agent.core.config import get_agent_settings, AGENT_WARN_ROUND, AGENT_FORCE_CONCLUDE_ROUND
from app.agent.core.budget import ToolResultBudget
from app.agent.core.error_handler import (
    ErrorHandler, HandleResult,
    ToolErrorCategory, classify_tool_error, generate_tool_diagnosis, generate_recovery_suggestion,
)
from app.agent.core.model_router import ModelRouter
from app.agent.tools.base import ToolRegistry

# 最大轮次总结提示
_MAX_ROUND_PROMPT = (
    "[System] 已达到最大工具调用轮次。请直接输出面向用户的最终专业分析结论和总结。"
    "以结构化标题/要点组织内容，不描述工具调用细节。"
)


class InvestmentAgent:
    """投资研究智能 Agent，实现 ReAct 工具调用循环"""

    def __init__(
        self,
        model_router: ModelRouter,
        tool_registry: ToolRegistry,
        max_tool_rounds: int = 10,
        context_engine=None,
        budget: ToolResultBudget | None = None,
    ):
        self.model_router = model_router
        self.tool_registry = tool_registry
        self.max_tool_rounds = max_tool_rounds
        self.context_engine = context_engine
        self.budget = budget
        cfg = get_agent_settings()
        self.error_handler = ErrorHandler(
            max_retries=cfg.AGENT_MAX_RETRIES,
            base_backoff=cfg.AGENT_RETRY_BASE_BACKOFF,
        )

    # ------------------------------------------------------------------
    # 工具执行
    # ------------------------------------------------------------------

    async def _execute_tool(self, tool_call: dict, tool_context: dict) -> dict:
        """执行单个工具：查找 → 超时执行 → 错误诊断"""
        func_name = tool_call["function"]["name"]
        func_args_str = tool_call["function"].get("arguments", "{}")
        tool_call_id = tool_call["id"]

        logger.info("[Agent] tool_call begin name={} id={}", func_name, tool_call_id)

        # 解析参数
        try:
            func_args = json.loads(func_args_str) if func_args_str else {}
        except json.JSONDecodeError:
            logger.warning("工具参数 JSON 解析失败: {}", func_args_str[:200])
            func_args = {}

        tool = self.tool_registry.get_tool(func_name)
        if not tool:
            result_str = json.dumps({"error": f"未知工具: {func_name}"}, ensure_ascii=False)
            return {"tool_call_id": tool_call_id, "name": func_name,
                    "result": {"error": f"未知工具: {func_name}"}, "result_str": result_str, "success": False}

        # 执行工具
        timeout = getattr(tool, "tool_timeout", 60.0)
        try:
            tool_result = await asyncio.wait_for(
                tool.execute(**{**func_args, **tool_context}),
                timeout=timeout,
            )
            success = True
        except asyncio.TimeoutError as e:
            category = ToolErrorCategory.TIMEOUT
            diagnosis = generate_tool_diagnosis(func_name, e, category, func_args)
            suggestion = generate_recovery_suggestion(category, func_name)
            tool_result = {"error": f"工具 {func_name} 执行超时（{timeout}秒）",
                           "diagnosis": diagnosis, "suggestion": suggestion}
            success = False
            logger.warning("[Agent] 工具 {} 执行超时 ({}s)", func_name, timeout)
        except Exception as e:
            category = classify_tool_error(func_name, e, func_args)
            diagnosis = generate_tool_diagnosis(func_name, e, category, func_args)
            suggestion = generate_recovery_suggestion(category, func_name)
            tool_result = {"error": str(e), "diagnosis": diagnosis, "suggestion": suggestion}
            success = False
            logger.error("[Agent] 工具 {} 执行异常: {}", func_name, ErrorHandler.sanitize_error_message(str(e)))

        result_str = json.dumps(tool_result, ensure_ascii=False, default=str)

        # L1: 工具级截断（max_result_chars）
        max_chars = getattr(tool, "max_result_chars", 8000)
        if len(result_str) > max_chars:
            keep = max_chars // 3
            result_str = (
                result_str[:keep]
                + f"\n...[已截断，原始 {len(result_str)} 字符]...\n"
                + result_str[-keep:]
            )

        # L2: 预算管控持久化（超阈值→MongoDB→preview）
        if self.budget and success:
            conversation_id = tool_context.get("conversation_id", "")
            threshold = getattr(tool, "budget_threshold", 0)
            result_str = await self.budget.enforce_single(
                result_str=result_str,
                tool_name=func_name,
                tool_call_id=tool_call_id,
                conversation_id=conversation_id,
                threshold_override=threshold,
            )

        return {"tool_call_id": tool_call_id, "name": func_name,
                "result": tool_result, "result_str": result_str, "success": success}

    async def _execute_tool_round(self, tool_calls: list[dict], tool_context: dict) -> list[dict]:
        """执行一轮工具调用：去重 → 并行执行 → 按原始顺序返回结果"""
        tool_names = [tc.get("function", {}).get("name", "") for tc in tool_calls]
        if len(tool_calls) > 1:
            logger.info("[Agent] 并行执行 {} 个工具: {}", len(tool_calls), tool_names)
        elif tool_names:
            logger.info("[Agent] 执行工具: {}", tool_names[0])

        # 基础去重：同一工具名+参数只执行一次
        seen_keys: set[str] = set()
        exec_calls: list[dict] = []
        skip_map: dict[int, str] = {}

        for i, tc in enumerate(tool_calls):
            name = tc.get("function", {}).get("name", "")
            args = tc.get("function", {}).get("arguments", "{}")
            dedup_key = f"{name}::{args}"
            if dedup_key in seen_keys:
                skip_map[i] = dedup_key
            else:
                seen_keys.add(dedup_key)
                exec_calls.append(tc)

        # 并行执行
        if exec_calls:
            tasks = [self._execute_tool(tc, tool_context) for tc in exec_calls]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            raw_results = []

        # 组装结果（保持原始顺序）
        results: list[dict] = []
        exec_idx = 0
        for i, tc in enumerate(tool_calls):
            if i in skip_map:
                results.append({
                    "tool_call_id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", ""),
                    "result": {"_dedup_hint": "本轮已执行过相同调用，结果相同。"},
                    "result_str": '{"_dedup_hint": "本轮已执行过相同调用。"}',
                    "success": True,
                })
            else:
                raw = raw_results[exec_idx]
                exec_idx += 1
                if isinstance(raw, Exception):
                    logger.error("[Agent] 工具执行异常: {}", raw)
                    results.append({
                        "tool_call_id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", ""),
                        "result": {"error": str(raw)},
                        "result_str": json.dumps({"error": str(raw)}, ensure_ascii=False),
                        "success": False,
                    })
                else:
                    results.append(raw)

        return results

    # ------------------------------------------------------------------
    # 非流式运行
    # ------------------------------------------------------------------

    async def run(self, messages: list[dict], tool_context: dict | None = None) -> dict:
        """非流式 ReAct 循环，返回 {content, tool_calls}"""
        tool_context = dict(tool_context or {})
        working_messages = list(messages)
        all_tool_calls: list[dict] = []

        for round_idx in range(self.max_tool_rounds):
            logger.info("Agent run - 第 {} 轮", round_idx + 1)

            # 轮次预警
            warnings = [w for w in [
                self._check_round_limit_warning(round_idx),
                self._check_token_budget_warning(working_messages),
            ] if w]
            if warnings:
                working_messages.append({"role": "system", "content": "\n".join(warnings)})

            # LLM 调用（含重试）
            openai_tools = self.tool_registry.get_openai_tools()
            response = await self._call_llm(working_messages, tools=openai_tools)

            content = response.get("content") or ""

            # 没有工具调用 → 返回最终回复
            if not response.get("tool_calls"):
                return {"content": content, "tool_calls": all_tool_calls}

            # 处理工具调用
            tool_calls = response["tool_calls"]
            working_messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

            # 执行一轮工具
            round_results = await self._execute_tool_round(tool_calls, tool_context)

            # L3: 轮次总预算管控
            if self.budget:
                round_results = await self.budget.enforce_turn(
                    round_results, tool_context.get("conversation_id", "")
                )

            for result in round_results:
                func_name = result["name"]
                try:
                    args = json.loads(
                        next((tc["function"].get("arguments", "{}") for tc in tool_calls
                              if tc.get("id") == result["tool_call_id"]), "{}") or "{}"
                    )
                except (json.JSONDecodeError, StopIteration):
                    args = {}

                all_tool_calls.append({"name": func_name, "arguments": args, "result": result["result"]})
                working_messages.append({
                    "role": "tool", "tool_call_id": result["tool_call_id"], "content": result["result_str"],
                })

        # 超过最大轮次 → 生成总结
        logger.warning("Agent 工具调用达到最大轮次 {}", self.max_tool_rounds)
        working_messages.append({"role": "system", "content": _MAX_ROUND_PROMPT})
        response = await self._call_llm(working_messages, tools=None)
        return {"content": response.get("content") or "", "tool_calls": all_tool_calls}

    # ------------------------------------------------------------------
    # 流式运行
    # ------------------------------------------------------------------

    async def run_stream(self, messages: list[dict], tool_context: dict | None = None):
        """流式 ReAct 循环，yield SSE 事件字典"""
        tool_context = dict(tool_context or {})
        working_messages = list(messages)
        all_tool_calls: list[dict] = []

        for round_idx in range(self.max_tool_rounds):
            logger.info("Agent run_stream - 第 {} 轮", round_idx + 1)

            # 轮次预警
            warnings = [w for w in [
                self._check_round_limit_warning(round_idx),
                self._check_token_budget_warning(working_messages),
            ] if w]
            if warnings:
                working_messages.append({"role": "system", "content": "\n".join(warnings)})

            # 收集流式响应
            full_content = ""
            _round_text_buffer: list[str] = []
            pending_tool_calls: dict[int, dict] = {}

            openai_tools = self.tool_registry.get_openai_tools()
            async for chunk in self._call_llm_stream(working_messages, tools=openai_tools):
                chunk_type = chunk["type"]
                if chunk_type == "content_delta":
                    full_content += chunk["content"]
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

            # 没有工具调用 → 最终回复
            if not pending_tool_calls:
                for buf_chunk in _round_text_buffer:
                    yield {"event": "text_delta", "data": {"content": buf_chunk}}
                yield {"event": "message_end", "data": {"tool_calls": all_tool_calls}}
                return

            # 有工具调用 → 丢弃缓冲的思考文字
            # （仅软工具协议下模型会把工具调用混在文本里，需通知前端清空；
            # 删除软工具时同步移除本段与前端 case 'text_replace' 分支）
            _round_text_buffer.clear()
            if full_content and self.model_router.tool_protocol.emits_tool_text_marks:
                yield {"event": "text_replace", "data": {"content": ""}}

            # 构造 assistant 消息
            sorted_tcs = [pending_tool_calls[k] for k in sorted(pending_tool_calls)]
            assistant_tool_calls = [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in sorted_tcs
            ]
            working_messages.append({
                "role": "assistant", "content": full_content or "", "tool_calls": assistant_tool_calls,
            })

            # yield tool_start 事件
            for tc_raw in sorted_tcs:
                yield {"event": "tool_start", "data": {"name": tc_raw["name"], "arguments": tc_raw["arguments"]}}

            # 执行工具（带心跳）
            exec_task = asyncio.create_task(
                self._execute_tool_round(
                    [{"id": tc["id"], "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                     for tc in sorted_tcs],
                    tool_context,
                )
            )
            hb_interval = 8
            exec_start = time.time()
            while not exec_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(exec_task), timeout=hb_interval)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": {
                        "elapsed": int(time.time() - exec_start),
                        "tools": [tc["name"] for tc in sorted_tcs],
                    }}
                except Exception:
                    break
            try:
                round_results = exec_task.result()
            except Exception as e:
                logger.error("[Agent stream] 工具执行异常: {}", e)
                round_results = [
                    {"tool_call_id": tc.get("id", ""), "name": tc["name"],
                     "result": {"error": str(e)}, "result_str": json.dumps({"error": str(e)}, ensure_ascii=False),
                     "success": False}
                    for tc in sorted_tcs
                ]

            # L3: 轮次总预算管控
            if self.budget:
                round_results = await self.budget.enforce_turn(
                    round_results, tool_context.get("conversation_id", "")
                )

            # 处理结果
            for result in round_results:
                func_name = result["name"]
                try:
                    args = json.loads(
                        next((tc["arguments"] for tc in sorted_tcs
                              if tc.get("id") == result["tool_call_id"]), "{}") or "{}"
                    )
                except (json.JSONDecodeError, StopIteration):
                    args = {}
                all_tool_calls.append({"name": func_name, "arguments": args, "result": result["result"]})
                yield {"event": "tool_result", "data": {"name": func_name, "result": result["result"]}}
                working_messages.append({
                    "role": "tool", "tool_call_id": result["tool_call_id"], "content": result["result_str"],
                })

        # 超过最大轮次 → 生成总结
        logger.warning("Agent stream 工具调用达到最大轮次 {}", self.max_tool_rounds)
        working_messages.append({"role": "system", "content": _MAX_ROUND_PROMPT})
        async for chunk in self._call_llm_stream(working_messages, tools=None):
            if chunk["type"] == "content_delta":
                yield {"event": "text_delta", "data": {"content": chunk["content"]}}

        yield {"event": "message_end", "data": {"tool_calls": all_tool_calls}}

    # ------------------------------------------------------------------
    # LLM 调用（含重试 + 降级）
    # ------------------------------------------------------------------

    async def _call_llm(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """非流式 LLM 调用，含重试和模型降级"""
        working_messages = list(messages)
        retry_count = 0

        while True:
            client, model_config = self.model_router.get_client()
            current_model = model_config.name
            try:
                result = await client.chat(working_messages, tools=tools)
                self.model_router.record_success(current_model)
                return result
            except Exception as e:
                self.model_router.record_failure(current_model)
                handle_result: HandleResult = await self.error_handler.handle(e, retry_count)

                if not handle_result.retry:
                    fallback = self.model_router.get_fallback_client(current_model)
                    if fallback:
                        fallback_client, fallback_model = fallback
                        logger.info("[Agent] 模型 {} 失败，降级到 {}", current_model, fallback_model.name)
                        try:
                            result = await fallback_client.chat(working_messages, tools=tools)
                            self.model_router.record_success(fallback_model.name)
                            return result
                        except Exception:
                            self.model_router.record_failure(fallback_model.name)
                    logger.error("[Agent] LLM 调用失败: {}", handle_result.user_message)
                    raise

                await self._apply_recovery_action(handle_result, working_messages)
                if handle_result.wait_seconds > 0:
                    await asyncio.sleep(handle_result.wait_seconds)
                retry_count += 1

    async def _call_llm_stream(self, messages: list[dict], tools: list[dict] | None = None):
        """流式 LLM 调用（async generator），含重试和模型降级"""
        working_messages = list(messages)
        retry_count = 0

        while True:
            client, model_config = self.model_router.get_client()
            current_model = model_config.name
            try:
                async for chunk in client.chat_stream(working_messages, tools=tools):
                    yield chunk
                self.model_router.record_success(current_model)
                return
            except Exception as e:
                self.model_router.record_failure(current_model)
                handle_result: HandleResult = await self.error_handler.handle(e, retry_count)

                if not handle_result.retry:
                    fallback = self.model_router.get_fallback_client(current_model)
                    if fallback:
                        fallback_client, fallback_model = fallback
                        logger.info("[Agent] 流式模型 {} 失败，降级到 {}", current_model, fallback_model.name)
                        try:
                            async for chunk in fallback_client.chat_stream(working_messages, tools=tools):
                                yield chunk
                            self.model_router.record_success(fallback_model.name)
                            return
                        except Exception:
                            self.model_router.record_failure(fallback_model.name)
                    logger.error("[Agent] LLM 流式调用失败: {}", handle_result.user_message)
                    raise

                await self._apply_recovery_action(handle_result, working_messages)
                if handle_result.wait_seconds > 0:
                    await asyncio.sleep(handle_result.wait_seconds)
                retry_count += 1

    async def _apply_recovery_action(self, handle_result: HandleResult, working_messages: list[dict]):
        """应用重试恢复动作（压缩上下文）"""
        if handle_result.action == "compress" and self.context_engine:
            compressed = await self.context_engine.prepare_messages(working_messages)
            working_messages[:] = compressed
        elif handle_result.action == "compress":
            if len(working_messages) > 10:
                working_messages[:] = [working_messages[0]] + working_messages[-8:]
                logger.warning("无 ContextEngine，使用降级截断策略")
        logger.info("[Agent] LLM 调用失败，将在 {:.1f}s 后重试", handle_result.wait_seconds)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _check_round_limit_warning(self, round_idx: int) -> str | None:
        """轮次预警：阶梯式提醒模型收敛"""
        current_round = round_idx + 1
        if current_round >= AGENT_FORCE_CONCLUDE_ROUND:
            return (
                f"[强制收敛] 已使用 {current_round}/{self.max_tool_rounds} 轮工具调用。"
                "你必须在本轮直接输出最终分析结论，不得再调用任何工具。"
            )
        elif current_round >= AGENT_WARN_ROUND:
            return (
                f"[System] 已使用 {current_round}/{self.max_tool_rounds} 轮工具调用。"
                "请尽快基于已有数据输出分析结论。"
            )
        return None

    def _check_token_budget_warning(self, messages: list[dict]) -> str | None:
        """当工具结果累积 token 超过预算 80% 时提醒模型收敛"""
        from app.agent.core.config import CONTEXT_BUDGET, MAX_CONTEXT_TOKENS
        tool_budget = int(MAX_CONTEXT_TOKENS * CONTEXT_BUDGET.get("tool_results", 0.15))
        tool_tokens = sum(self._estimate_tokens(m.get("content", ""))
                          for m in messages if m.get("role") == "tool")
        if tool_tokens > tool_budget * 0.8:
            return (
                f"[数据量预警] 工具结果已累积约 {tool_tokens} tokens（预算上限 {tool_budget}），"
                "请基于已有数据直接给出分析结论。"
            )
        return None

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """简单 token 估算（混合语言粗估：3 字符 ≈ 1 token）"""
        return len(text) // 3 if text else 0
