"""
工具结果预算管控

三层防御体系（L1 已有，本模块实现 L2 + L3）：
- L1: 工具自截断（BaseTool.max_result_chars，工具内部生效）
- L2: 单结果持久化（超阈值 → 存 MongoDB → 返回 preview + result_id）
- L3: 轮次总预算（一轮工具总输出超限 → 从最大结果开始持久化）

设计原则：
- 不丢失数据：完整结果始终可通过 result_id 回读
- 上下文友好：preview 保留头尾关键信息，Agent 可判断是否需要回读
- 轻量无侵入：仅在 agent.py 的工具执行后调用，不改变工具本身逻辑
"""
import uuid
from dataclasses import dataclass

from loguru import logger

from app.agent.core.config import get_agent_settings


@dataclass(frozen=True)
class BudgetConfig:
    """预算配置（可按模型上下文窗口比例缩放）"""

    result_threshold: int = 12000   # L2 触发阈值（字符）
    turn_budget: int = 40000        # L3 轮次总预算（字符）
    preview_chars: int = 1500       # 持久化后保留的 preview 长度

    @classmethod
    def from_settings(cls) -> "BudgetConfig":
        """从全局配置构建"""
        cfg = get_agent_settings()
        return cls(
            result_threshold=cfg.AGENT_RESULT_BUDGET,
            turn_budget=cfg.AGENT_TURN_BUDGET,
            preview_chars=cfg.AGENT_BUDGET_PREVIEW_CHARS,
        )

    @classmethod
    def for_context_window(cls, max_tokens: int) -> "BudgetConfig":
        """按模型上下文窗口比例缩放（64K 为基准）"""
        cfg = get_agent_settings()
        ratio = max(0.5, min(2.0, max_tokens / 64000))
        return cls(
            result_threshold=int(cfg.AGENT_RESULT_BUDGET * ratio),
            turn_budget=int(cfg.AGENT_TURN_BUDGET * ratio),
            preview_chars=cfg.AGENT_BUDGET_PREVIEW_CHARS,
        )


class ToolResultBudget:
    """
    工具结果预算管控器

    每次对话实例化一个，负责 L2（单结果持久化）和 L3（轮次总预算）。
    依赖 ConversationStore 的 save_tool_result_full / get_tool_result_full 进行持久化。
    """

    def __init__(self, config: BudgetConfig, conversation_store):
        self.config = config
        self.store = conversation_store

    async def enforce_single(
        self,
        result_str: str,
        tool_name: str,
        tool_call_id: str,
        conversation_id: str,
        threshold_override: int = 0,
    ) -> str:
        """
        L2: 单结果超阈值 → 持久化 → 返回 preview。

        Args:
            result_str: 工具原始结果字符串
            tool_name: 工具名称
            tool_call_id: 工具调用 ID（用作 result_id）
            conversation_id: 对话 ID
            threshold_override: 工具级阈值覆盖（0=用全局默认）

        Returns:
            原始 result_str（未超限）或 preview 字符串（已持久化）
        """
        threshold = threshold_override or self.config.result_threshold
        if len(result_str) <= threshold:
            return result_str

        # 持久化完整结果
        result_id = tool_call_id or f"budget_{uuid.uuid4().hex[:12]}"
        try:
            await self.store.save_tool_result_full(
                message_id=result_id,
                tool_name=tool_name,
                full_result=result_str,
            )
            logger.info(
                "[Budget] L2 持久化: tool={}, result_id={}, 原始={}字符",
                tool_name, result_id, len(result_str),
            )
        except Exception as e:
            logger.warning("[Budget] L2 持久化失败（降级为截断）: {}", e)
            # 降级：直接截断，不丢失头尾
            return self._fallback_truncate(result_str, tool_name)

        return self._generate_preview(result_str, tool_name, result_id)

    async def enforce_turn(
        self,
        results: list[dict],
        conversation_id: str,
    ) -> list[dict]:
        """
        L3: 轮次总预算 → 从最大结果开始持久化，直到总量合规。

        Args:
            results: 本轮工具执行结果列表，每项含 result_str / name / tool_call_id
            conversation_id: 对话 ID

        Returns:
            处理后的 results（result_str 可能已被替换为 preview）
        """
        total_chars = sum(len(r.get("result_str", "")) for r in results)
        if total_chars <= self.config.turn_budget:
            return results

        logger.info(
            "[Budget] L3 轮次预算超限: total={}, budget={}",
            total_chars, self.config.turn_budget,
        )

        # 按 result_str 长度降序排列索引，从最大的开始持久化
        indexed = sorted(
            range(len(results)),
            key=lambda i: len(results[i].get("result_str", "")),
            reverse=True,
        )

        for idx in indexed:
            if total_chars <= self.config.turn_budget:
                break

            r = results[idx]
            original_str = r.get("result_str", "")
            if len(original_str) <= self.config.preview_chars:
                continue  # 已经很短了，跳过

            tool_call_id = r.get("tool_call_id", f"turn_{uuid.uuid4().hex[:8]}")
            new_str = await self.enforce_single(
                result_str=original_str,
                tool_name=r.get("name", "unknown"),
                tool_call_id=tool_call_id,
                conversation_id=conversation_id,
                threshold_override=self.config.preview_chars,  # 强制持久化
            )
            # 更新差值
            total_chars -= len(original_str) - len(new_str)
            results[idx] = {**r, "result_str": new_str}

        return results

    def _generate_preview(self, content: str, tool_name: str, result_id: str) -> str:
        """生成截断预览（保留头尾 + 回读提示）"""
        preview_chars = self.config.preview_chars
        head_chars = int(preview_chars * 0.7)
        tail_chars = preview_chars - head_chars

        head = content[:head_chars]
        tail = content[-tail_chars:] if tail_chars > 0 else ""
        total_len = len(content)

        return (
            f"{head}\n\n"
            f"[... 结果已截断，原始 {total_len} 字符。"
            f"完整结果请调用 read_tool_result 工具，传入 result_id=\"{result_id}\" ...]\n\n"
            f"{tail}"
        )

    def _fallback_truncate(self, content: str, tool_name: str) -> str:
        """持久化失败时的降级截断（保留头尾）"""
        keep = self.config.preview_chars // 2
        return (
            content[:keep]
            + f"\n...[截断，原始 {len(content)} 字符，持久化失败]...\n"
            + content[-keep:]
        )
