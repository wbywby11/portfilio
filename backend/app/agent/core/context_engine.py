"""
上下文压缩引擎

当对话历史的 token 数接近模型上下文窗口限制时，
自动压缩早期消息，减少 token 消耗同时保留关键信息。

三阶段压缩策略：
1. 工具结果智能摘要（无需 LLM 调用）— 对过长工具返回生成结构化摘要
2. 前置/尾部保护分区 — 前 N 条和尾部 token 预算保护区永不压缩
3. 历史摘要（LLM 调用）— 将可压缩区对话压缩为金融分析摘要，支持迭代更新
"""
import json
import os
import re
from typing import Optional

try:
    import tiktoken
except ImportError:  # 未安装时仍可启动；token 估算会退化为字符近似
    tiktoken = None  # type: ignore[misc, assignment]

from loguru import logger

from app.agent.core.config import CONTEXT_BUDGET, MAX_CONTEXT_TOKENS


class ContextEngine:
    """上下文压缩引擎"""

    # —— 摘要防幻觉标记 ——
    # 压缩摘要注入时包裹此前缀/后缀，明确告知 LLM 摘要仅供参考、不可执行
    SUMMARY_PREFIX = (
        "[以下是早期对话的压缩摘要，仅供参考。"
        "摘要中的操作/工具调用已完成，不要重新执行。"
        "当前任务以最新用户消息为准。]\n"
    )
    SUMMARY_END_MARKER = "\n--- 摘要结束 ---"

    def __init__(
        self,
        llm_client,  # LLMClient 实例，用于摘要生成
        max_context_tokens: int = 64000,
        compress_threshold: float = 0.55,  # 55% 时触发压缩
        tool_result_max_chars: int = int(os.getenv("AGENT_TOOL_RESULT_MAX_CHARS", "25000")),  # 单个工具结果最大字符数
        model_name: str = "gpt-4",          # 模型名称，用于 tiktoken 编码器选择
    ):
        self.llm_client = llm_client
        self.max_context_tokens = max_context_tokens
        self.compress_threshold = compress_threshold
        self.tool_result_max_chars = tool_result_max_chars
        self.model_name = model_name
        self._tiktoken_cache: dict = {}  # 编码器缓存
        self._tiktoken_missing_logged = False

        # —— 新增：压缩保护区配置 ——
        # 前置保护条数（system prompt + 前 2 轮用户对话）
        self.protect_first_n = int(
            os.getenv("AGENT_COMPRESS_PROTECT_FIRST", "4")
        )
        # 尾部保护保底条数
        self.protect_last_n = int(
            os.getenv("AGENT_COMPRESS_PROTECT_LAST", "6")
        )
        # 尾部 token 预算占阈值的比例
        self.tail_token_ratio = float(
            os.getenv("AGENT_COMPRESS_TAIL_RATIO", "0.20")
        )

        # —— 新增：迭代摘要状态 ——
        self._previous_summary: Optional[str] = None

    async def prepare_messages(
        self, system_prompt: str, history: list[dict]
    ) -> list[dict]:
        """
        智能组装消息列表，必要时压缩历史。

        Args:
            system_prompt: 系统提示词
            history: 已经通过 _rebuild_messages() 重建的完整消息列表

        Returns:
            准备好的消息列表，可直接发送给 LLM
        """
        messages = [{"role": "system", "content": system_prompt}]

        if not history:
            return messages

        # 估算当前 token 数
        all_messages = messages + history
        estimated_tokens = self.estimate_tokens(all_messages)
        threshold_tokens = int(self.max_context_tokens * self.compress_threshold)

        if estimated_tokens <= threshold_tokens:
            # 未超阈值，直接使用
            messages.extend(history)
            return messages

        logger.info(
            f"[ContextEngine] 预估 token 数 {estimated_tokens} 超过阈值 "
            f"{threshold_tokens}，开始压缩"
        )

        # 预算感知压缩（前置增强）
        history = self._apply_budget_aware_compression(history, estimated_tokens)

        # 阶段 1: 工具结果智能摘要（无需 LLM）
        pruned_history = self._prune_tool_results(history)
        estimated_after_prune = self.estimate_tokens(messages + pruned_history)

        if estimated_after_prune <= threshold_tokens:
            logger.info(
                f"[ContextEngine] 工具结果剪枝后 token: {estimated_after_prune}，"
                f"未超阈值，跳过摘要"
            )
            messages.extend(pruned_history)
            return messages

        # 阶段 2: 历史摘要压缩（带前置/尾部保护）
        logger.info(
            f"[ContextEngine] 剪枝后仍超阈值 ({estimated_after_prune})，"
            f"执行历史摘要"
        )
        compressed = await self._compress_history(
            pruned_history, threshold_tokens
        )
        messages.extend(compressed)

        final_tokens = self.estimate_tokens(messages)
        logger.info(f"[ContextEngine] 压缩完成，最终 token 数: {final_tokens}")
        return messages

    # ------------------------------------------------------------------ #
    #  预算感知压缩（前置增强）
    # ------------------------------------------------------------------ #

    def _apply_budget_aware_compression(self, messages: list[dict], current_tokens: int) -> list[dict]:
        """基于全局预算分配进行智能压缩"""
        tool_budget_tokens = int(MAX_CONTEXT_TOKENS * CONTEXT_BUDGET["tool_results"])
        history_budget_tokens = int(MAX_CONTEXT_TOKENS * CONTEXT_BUDGET["conversation_history"])

        # 1. 计算当前各部分 token 占用
        tool_tokens = 0
        history_tokens = 0
        tool_messages_indices = []

        for i, msg in enumerate(messages):
            msg_tokens = self._estimate_tokens_str(msg.get("content", ""))
            if msg.get("role") == "tool":
                tool_tokens += msg_tokens
                tool_messages_indices.append((i, msg_tokens))
            elif msg.get("role") in ("user", "assistant"):
                history_tokens += msg_tokens

        # 2. 工具结果超预算：从最旧的开始压缩
        if tool_tokens > tool_budget_tokens:
            excess = tool_tokens - tool_budget_tokens
            # 按时间顺序（索引从小到大 = 最旧优先）压缩
            for idx, tokens in tool_messages_indices:
                if excess <= 0:
                    break
                original_content = messages[idx].get("content", "")
                # 压缩为简短摘要
                compressed = self._compress_tool_result_to_summary(original_content)
                messages[idx]["content"] = compressed
                saved = tokens - self._estimate_tokens_str(compressed)
                excess -= saved

        # 3. 对话历史超预算：标记需要 LLM 摘要
        if history_tokens > history_budget_tokens:
            messages = self._aggressive_history_summary(messages, history_budget_tokens)

        return messages

    def _compress_tool_result_to_summary(self, content: str) -> str:
        """将工具结果压缩为极简摘要（不调用LLM，纯规则）"""
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                # 保留状态和摘要字段
                summary_parts = []
                if "success" in data:
                    summary_parts.append(f"状态: {'成功' if data['success'] else '失败'}")
                if "error" in data:
                    summary_parts.append(f"错误: {data['error']}")
                if "summary" in data:
                    summary_parts.append(f"摘要: {data['summary']}")
                elif "message" in data:
                    summary_parts.append(f"信息: {data['message']}")
                # 列表类字段只统计数量
                for key in ["items", "data", "results", "records", "assets"]:
                    if key in data and isinstance(data[key], list):
                        summary_parts.append(f"{key}: 共{len(data[key])}条")
                if summary_parts:
                    return "[预算压缩] " + " | ".join(summary_parts)
        except (json.JSONDecodeError, TypeError):
            pass

        # 纯文本：保留前200字符
        if len(content) > 300:
            return f"[预算压缩] {content[:200]}..."
        return content

    def _aggressive_history_summary(self, messages: list[dict], budget_tokens: int) -> list[dict]:
        """对话历史超预算时的激进压缩策略"""
        # 计算需要保护的头尾消息
        protect_first = getattr(self, 'protect_first_n', 4)
        protect_last = getattr(self, 'protect_last_n', 6)

        if len(messages) <= protect_first + protect_last:
            return messages

        # 中间部分标记为需要 LLM 摘要（通过添加标记，让后续阶段处理）
        middle_start = protect_first
        middle_end = len(messages) - protect_last

        # 对中间的 user/assistant 消息进行硬截断（每条最多保留500字符）
        for i in range(middle_start, middle_end):
            if messages[i].get("role") in ("user", "assistant"):
                content = messages[i].get("content", "")
                if len(content) > 500:
                    messages[i]["content"] = content[:500] + "\n[... 历史内容已压缩 ...]"

        return messages

    def _estimate_tokens_str(self, text: str) -> int:
        """估算单个字符串的 token 数"""
        if not text:
            return 0
        encoding = self._get_tiktoken_encoding()
        if encoding is not None:
            try:
                return len(encoding.encode(text))
            except Exception:
                pass
        return max(len(text) // 4, 1)

    def get_budget_overspend_warning(self, messages: list[dict]) -> str | None:
        """检查是否存在预算超支，返回预警文本或 None"""
        tool_budget = int(MAX_CONTEXT_TOKENS * CONTEXT_BUDGET["tool_results"])
        tool_tokens = sum(
            self._estimate_tokens_str(m.get("content", ""))
            for m in messages if m.get("role") == "tool"
        )

        if tool_tokens > tool_budget * 0.9:
            return (
                f"[预算预警] 工具结果已占用 {tool_tokens} tokens（预算 {tool_budget}），"
                "请尽量基于已有数据给出结论，减少后续工具调用。"
            )

        total_tokens = self.estimate_tokens(messages)
        if total_tokens > MAX_CONTEXT_TOKENS * 0.75:
            return (
                f"[上下文预警] 总 token 已达 {total_tokens}/{MAX_CONTEXT_TOKENS}，"
                "请精简回复并避免不必要的工具调用。"
            )

        return None

    # ------------------------------------------------------------------ #
    #  阶段 1: 工具结果智能摘要
    # ------------------------------------------------------------------ #

    def _prune_tool_results(self, history: list[dict]) -> list[dict]:
        """
        阶段 1: 工具结果剪枝（无需 LLM 调用）
        对过长的 tool result 生成智能摘要，保留关键信息。
        """
        # 先建一个 tool_call_id -> tool_name 的映射，用于摘要
        tool_name_map: dict[str, str] = {}
        for msg in history:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    if isinstance(tc, dict):
                        tc_id = tc.get("id", "")
                        func = tc.get("function", {})
                        tool_name_map[tc_id] = func.get("name", "unknown")

        pruned = []
        for msg in history:
            if (
                msg.get("role") == "tool"
                and len(msg.get("content", "")) > self.tool_result_max_chars
            ):
                content = msg["content"]
                tool_id = msg.get("tool_call_id", "")
                tool_name = tool_name_map.get(tool_id, "unknown")

                # 尝试智能摘要
                smart_summary = self._build_smart_tool_summary(
                    tool_name, content
                )
                if smart_summary:
                    pruned.append({**msg, "content": smart_summary})
                else:
                    # 增强回退：尝试 JSON 结构感知截断
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, list):
                            truncated_content = self._truncate_json_list(parsed, self.tool_result_max_chars)
                        elif isinstance(parsed, dict):
                            truncated_content = self._truncate_json_dict(parsed, self.tool_result_max_chars)
                        else:
                            raise ValueError("非列表/字典类型")
                    except (json.JSONDecodeError, ValueError, TypeError):
                        # 最终回退：纯文本前后截断
                        keep_chars = self.tool_result_max_chars // 3
                        truncated_content = (
                            content[:keep_chars]
                            + f"\n...[已截断，原始 {len(content)} 字符]...\n"
                            + content[-keep_chars:]
                        )
                    pruned.append({**msg, "content": truncated_content})
            else:
                pruned.append(msg)
        return pruned

    def _truncate_json_list(self, data: list, max_chars: int) -> str:
        """智能截断 JSON 列表：保留前 3 项 + 统计摘要。

        适用于资产列表、回测记录等大数组场景。
        """
        total = len(data)
        preview_count = min(3, total)
        preview = data[:preview_count]

        # 检测是否包含金融指标字段
        financial_keys = {"annual_return", "sharpe_ratio", "max_drawdown", "total_return", "volatility"}
        has_financial = any(
            isinstance(item, dict) and financial_keys & set(item.keys())
            for item in preview
        )

        result = {
            "_truncated": True,
            "_total_items": total,
            "_preview_count": preview_count,
            "items": preview,
        }

        if has_financial and total > preview_count:
            # 尝试提取关键指标的极值
            try:
                for key in financial_keys:
                    values = [
                        item[key] for item in data
                        if isinstance(item, dict) and key in item and isinstance(item[key], (int, float))
                    ]
                    if values:
                        result[f"_{key}_range"] = f"{min(values):.4f} ~ {max(values):.4f}"
            except Exception:
                pass

        result["_summary"] = f"共 {total} 条记录，展示前 {preview_count} 条"
        return json.dumps(result, ensure_ascii=False, default=str)

    def _truncate_json_dict(self, data: dict, max_chars: int) -> str:
        """智能截断 JSON 字典：优先保留关键字段，大字段递归截断。"""
        # 关键字段优先级（从高到低）
        priority_keys = [
            "success", "error", "message",
            "summary", "recommendation", "comparison_table",
            "rankings", "result", "strategy_type",
            "charts",  # 图表放最后（通常最大）
        ]

        truncated = {}
        current_size = 0
        budget = int(max_chars * 0.8)  # 留 20% 余量给元数据

        # 第一轮：按优先级添加关键字段
        for key in priority_keys:
            if key in data:
                field_str = json.dumps({key: data[key]}, ensure_ascii=False, default=str)
                if current_size + len(field_str) <= budget:
                    truncated[key] = data[key]
                    current_size += len(field_str)

        # 第二轮：添加剩余小字段
        for key, value in data.items():
            if key in truncated:
                continue
            field_str = json.dumps({key: value}, ensure_ascii=False, default=str)
            if len(field_str) <= 200 and current_size + len(field_str) <= budget:
                truncated[key] = value
                current_size += len(field_str)

        # 标记截断的大字段
        omitted = [k for k in data if k not in truncated]
        if omitted:
            truncated["_truncated"] = True
            truncated["_omitted_fields"] = omitted
            truncated["_original_fields"] = len(data)

        return json.dumps(truncated, ensure_ascii=False, default=str)

    def _build_smart_tool_summary(
        self, tool_name: str, content: str
    ) -> Optional[str]:
        """
        根据工具名和返回内容，生成 1 行结构化摘要。
        如果无法解析内容则返回 None，调用方回退到截断方式。
        """
        original_len = len(content)

        # 尝试解析 JSON
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            data = None

        if data is not None and isinstance(data, dict):
            # 检查是否有 error 字段
            if "error" in data:
                return (
                    f"[{tool_name}] 错误: {str(data['error'])[:200]}"
                    f"（共 {original_len} 字符）"
                )

            # 提取关键指标（金融回测场景常见字段）
            summary_parts = []

            # 检查 data 数组
            for key in ("data", "results", "items", "records", "assets"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    # 提取前几个标识符
                    ids = []
                    for item in items[:5]:
                        if isinstance(item, dict):
                            for id_key in (
                                "code", "symbol", "asset_code",
                                "name", "id",
                            ):
                                if id_key in item:
                                    ids.append(str(item[id_key]))
                                    break
                    preview = ", ".join(ids)
                    if len(items) > 5:
                        preview += ", ..."
                    summary_parts.append(
                        f"返回 {len(items)} 条{key}: {preview}"
                    )
                    break

            # 检查金融指标字段
            metric_keys = {
                "annual_return": "年化收益",
                "annualized_return": "年化收益",
                "sharpe_ratio": "夏普比率",
                "max_drawdown": "最大回撤",
                "total_return": "总收益",
                "volatility": "波动率",
            }
            found_metrics = []
            for mk, label in metric_keys.items():
                val = data.get(mk)
                if val is not None:
                    if isinstance(val, float):
                        found_metrics.append(f"{label} {val:.2%}")
                    else:
                        found_metrics.append(f"{label} {val}")
            if found_metrics:
                summary_parts.append(", ".join(found_metrics))

            # 如果有 status / message 字段
            if "status" in data:
                summary_parts.insert(0, f"状态: {data['status']}")
            if "message" in data and not summary_parts:
                summary_parts.append(str(data["message"])[:200])

            if summary_parts:
                detail = "; ".join(summary_parts)
                return (
                    f"[{tool_name}] {detail}（共 {original_len} 字符）"
                )

        # 尝试从纯文本中提取关键信息（如回测结果文本）
        if isinstance(content, str) and len(content) > self.tool_result_max_chars:
            # 查找常见金融指标模式
            patterns = {
                "年化收益": r"年化收益[率]?\s*[:：]?\s*([-\d.]+%?)",
                "最大回撤": r"最大回撤\s*[:：]?\s*([-\d.]+%?)",
                "夏普比率": r"夏普比率\s*[:：]?\s*([-\d.]+)",
            }
            found = []
            for label, pattern in patterns.items():
                m = re.search(pattern, content)
                if m:
                    found.append(f"{label} {m.group(1)}")
            if found:
                return (
                    f"[{tool_name}] {', '.join(found)}（共 {original_len} 字符）"
                )

        # 无法解析，返回 None 让调用方回退
        return None

    # ------------------------------------------------------------------ #
    #  阶段 2: 历史摘要（带前置保护 + Token 预算尾部保护）
    # ------------------------------------------------------------------ #

    async def _compress_history(
        self, history: list[dict], threshold_tokens: int
    ) -> list[dict]:
        """
        阶段 2: 历史摘要（LLM 调用）
        将消息分为三段：
        - 前置保护区（永不压缩）
        - 可压缩区（生成摘要）
        - 尾部保护区（由 token 预算动态决定，保底 protect_last_n 条）
        """
        if len(history) <= self.protect_first_n + self.protect_last_n:
            # 消息太少，无法分区，直接返回
            return history

        # —— 0. 清理历史中残留的旧摘要（防叠加） ——
        history = self._normalize_stale_summary(history)

        # —— 1. 划分前置保护区 ——
        head = history[: self.protect_first_n]
        remaining = history[self.protect_first_n :]

        # —— 2. 从末尾向前累积 token，确定尾部保护区 ——
        tail_budget = int(threshold_tokens * self.tail_token_ratio)
        tail_start_idx = len(remaining)  # 从 remaining 的末尾开始
        accumulated_tokens = 0

        for i in range(len(remaining) - 1, -1, -1):
            msg_tokens = self.estimate_tokens([remaining[i]])
            if accumulated_tokens + msg_tokens > tail_budget:
                # 预算耗尽，停在这里
                break
            accumulated_tokens += msg_tokens
            tail_start_idx = i

        # 保底：至少保留 protect_last_n 条
        max_tail_start = len(remaining) - self.protect_last_n
        if tail_start_idx > max_tail_start:
            tail_start_idx = max(max_tail_start, 0)

        # —— 3. 调整边界，不切断 tool_call / tool_result 对 ——
        tail_start_idx = self._adjust_split_boundary(
            remaining, tail_start_idx
        )

        compressible = remaining[:tail_start_idx]
        tail = remaining[tail_start_idx:]

        if not compressible:
            # 没有可压缩内容
            return history

        logger.info(
            f"[ContextEngine] 分区: 前置保护={len(head)}, "
            f"可压缩={len(compressible)}, 尾部保护={len(tail)}"
        )

        # —— 4. 计算摘要 token 预算 ——
        compressed_tokens = self.estimate_tokens(compressible)
        summary_max_tokens = min(int(compressed_tokens * 0.20), 2000)
        summary_max_tokens = max(summary_max_tokens, 200)  # 至少给 200

        # —— 5. 用 LLM 生成摘要 ——
        summary = await self._generate_summary(
            compressible, summary_max_tokens
        )

        # —— 6. 保存迭代摘要 ——
        if summary:
            self._previous_summary = summary

        # —— 7. 组装结果 ——
        result = list(head)
        if summary:
            result.append({
                "role": "system",
                "content": f"{self.SUMMARY_PREFIX}{summary}{self.SUMMARY_END_MARKER}",
            })
        result.extend(tail)
        return result

    def _normalize_stale_summary(self, messages: list[dict]) -> list[dict]:
        """
        清理历史消息中残留的旧摘要前缀（防叠加）。
        当历史中已存在带 SUMMARY_PREFIX 的 system 消息时，移除它（新摘要会替代）。
        """
        cleaned = []
        for msg in messages:
            if (
                msg.get("role") == "system"
                and isinstance(msg.get("content"), str)
                and msg["content"].startswith(self.SUMMARY_PREFIX)
            ):
                # 跳过旧摘要消息（新压缩会生成替代）
                continue
            cleaned.append(msg)
        return cleaned

    def _adjust_split_boundary(
        self, messages: list[dict], split_idx: int
    ) -> int:
        """
        调整分割边界，确保不切断 tool_call/tool_result 对。
        - 如果尾部以孤立的 tool result 开头，向前移动边界
        - 如果可压缩区以带 tool_calls 的 assistant 结尾，向后移动边界
        """
        n = len(messages)
        if split_idx <= 0 or split_idx >= n:
            return split_idx

        # 如果尾部第一条是 tool result，向前吸收（把对应的 assistant+tool 都放到尾部）
        while (
            split_idx > 0
            and split_idx < n
            and messages[split_idx].get("role") == "tool"
        ):
            split_idx -= 1

        # 如果可压缩区最后一条是带 tool_calls 的 assistant，向后推（放到尾部）
        while (
            split_idx > 0
            and messages[split_idx - 1].get("role") == "assistant"
            and messages[split_idx - 1].get("tool_calls")
        ):
            split_idx -= 1

        return max(split_idx, 0)

    # ------------------------------------------------------------------ #
    #  摘要生成
    # ------------------------------------------------------------------ #

    async def _generate_summary(
        self, messages: list[dict], max_tokens: int = 2000
    ) -> str:
        """调用 LLM 生成对话摘要，针对金融研究场景定制，支持迭代更新"""
        conversation_text = self._format_messages_for_summary(messages)

        # —— 金融分析摘要模板 ——
        summary_prompt = (
            "请将以下对话历史压缩为结构化摘要，保留关键信息：\n\n"
            "## 研究主题\n（用户关注的核心问题）\n\n"
            "## 涉及资产\n（提及的资产代码和名称）\n\n"
            "## 已完成分析\n（已执行的分析步骤和使用的工具）\n\n"
            "## 关键结论\n（重要的数据发现和分析结论）\n\n"
            "## 用户偏好\n（用户表达的偏好和约束条件）\n\n"
            "## 待办事项\n（尚未完成的分析或用户请求）\n\n"
            "重要：摘要仅供后续对话参考上下文，不要包含任何待执行指令或操作建议。\n\n"
        )

        # —— 迭代摘要：在已有摘要基础上更新 ——
        if self._previous_summary:
            summary_prompt += (
                "以下是之前的摘要，请在此基础上更新"
                "（整合新信息，保留仍然相关的旧信息）：\n"
                f"{self._previous_summary}\n\n"
            )

        # —— 摘要 token 预算提示 ——
        summary_prompt += (
            f"请将摘要控制在约 {max_tokens} 个 token 以内。\n\n"
            f"对话历史：\n{conversation_text}"
        )

        try:
            result = await self.llm_client.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个对话摘要助手，负责压缩金融研究对话历史。"
                            "输出简洁的结构化摘要。"
                        ),
                    },
                    {"role": "user", "content": summary_prompt},
                ],
                tools=None,  # 不携带工具能力！安全约束
            )
            return result.get("content", "")
        except Exception as e:
            logger.warning(f"[ContextEngine] 摘要生成失败，跳过压缩: {e}")
            return ""

    def _format_messages_for_summary(self, messages: list[dict]) -> str:
        """将消息列表格式化为可读文本"""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                if msg.get("tool_calls"):
                    # 记录工具调用
                    tool_names = []
                    for tc in msg["tool_calls"]:
                        if isinstance(tc, dict):
                            func = tc.get("function", {})
                            tool_names.append(func.get("name", "unknown"))
                    lines.append(f"助手: [调用工具: {', '.join(tool_names)}]")
                if content:
                    # 截断过长的 assistant 回复
                    if len(content) > 500:
                        content = content[:500] + "..."
                    lines.append(f"助手: {content}")
            elif role == "tool":
                tool_content = content
                if len(tool_content) > 300:
                    tool_content = tool_content[:300] + "..."
                lines.append(f"工具结果: {tool_content}")

        return "\n".join(lines)

    def _get_tiktoken_encoding(self):
        """获取或缓存 tiktoken 编码器；未安装 tiktoken 时返回 None。"""
        if tiktoken is None:
            return None
        if self.model_name in self._tiktoken_cache:
            return self._tiktoken_cache[self.model_name]

        enc = tiktoken.get_encoding("cl100k_base")
        self._tiktoken_cache[self.model_name] = enc
        logger.info("[ContextEngine] tiktoken 编码器已加载: cl100k_base (模型: {})", self.model_name)
        return enc

    def _count_tokens_per_message(self, msg: dict, encoding) -> int:
        """按 OpenAI 规则精确计算单条消息的 token 数。

        每条消息额外 4 tokens（<|im_start|>role\ncontent<|im_end|>）
        """
        tokens = 4  # 消息包装开销

        for key, value in msg.items():
            if value is None:
                continue
            if key == "content":
                if isinstance(value, str) and value:
                    tokens += len(encoding.encode(value))
            elif key == "tool_calls":
                if isinstance(value, list):
                    for tc in value:
                        tokens += 20  # 每个 tool_call 结构开销
                        if isinstance(tc, dict) and tc.get("function"):
                            func = tc["function"]
                            if func.get("name"):
                                tokens += len(encoding.encode(func["name"]))
                            if func.get("arguments"):
                                tokens += len(encoding.encode(func["arguments"]))
            elif key == "role":
                tokens += 1  # role 字段通常 1 token
            elif key == "tool_call_id":
                tokens += len(encoding.encode(str(value)))
            # name 等其他字段
            elif isinstance(value, str):
                tokens += len(encoding.encode(value))

        return tokens

    def estimate_tokens(self, messages: list[dict]) -> int:
        """使用 tiktoken 精确计算消息列表的 token 数。"""
        encoding = self._get_tiktoken_encoding()
        if encoding is None:
            if not self._tiktoken_missing_logged:
                logger.warning(
                    "[ContextEngine] 未安装 tiktoken，token 计数使用粗略估算。"
                    "请执行: pip install tiktoken"
                )
                self._tiktoken_missing_logged = True
            total_text = ""
            for msg in messages:
                content = msg.get("content")
                if content and isinstance(content, str):
                    total_text += content
            return max(len(total_text) // 4, 1)

        try:
            total = sum(
                self._count_tokens_per_message(msg, encoding)
                for msg in messages
            )
            total += 3  # 每次请求的回复开销
            return total
        except Exception as e:
            logger.warning("[ContextEngine] tiktoken 计数异常，使用简单估算: {}", e)
            total_text = ""
            for msg in messages:
                content = msg.get("content")
                if content and isinstance(content, str):
                    total_text += content
            return max(len(total_text) // 4, 1)
