"""
对话服务 - 编排 Agent 与对话存储

职责：Agent 初始化、消息重建、对话入口（chat / chat_stream）。
"""
import asyncio
import json
import uuid

from loguru import logger

from app.agent.core.agent import InvestmentAgent
from app.agent.core.budget import BudgetConfig, ToolResultBudget
from app.agent.core.config import get_agent_settings, get_model_configs
from app.agent.core.context_engine import ContextEngine
from app.agent.core.error_handler import ErrorHandler
from app.agent.core.model_router import ModelRouter
from app.agent.prompts.system_prompts import get_system_prompt
from app.agent.services.conversation_store import ConversationStore
from app.agent.tools.base import tool_registry
from app.agent.memory import MemoryManager

# 全局单例
_memory_manager = MemoryManager()


class ChatService:
    """对话服务：管理会话并编排 Agent 执行"""

    def __init__(self):
        self._agent: InvestmentAgent | None = None
        self._context_engine: ContextEngine | None = None
        self.store = ConversationStore()
        self.memory_manager = _memory_manager

    @property
    def agent(self) -> InvestmentAgent:
        if self._agent is None:
            self._init_agent()
        return self._agent

    @property
    def context_engine(self) -> ContextEngine:
        if self._context_engine is None:
            self._init_agent()
        return self._context_engine

    def _init_agent(self):
        """初始化 ContextEngine、Budget 和 Agent"""
        cfg = get_agent_settings()
        model_configs = get_model_configs()
        model_router = ModelRouter(model_configs)
        client, model_config = model_router.get_client()
        self._context_engine = ContextEngine(
            llm_client=client,
            max_context_tokens=model_config.max_context,
            compress_threshold=cfg.AGENT_COMPRESS_THRESHOLD,
            tool_result_max_chars=cfg.AGENT_TOOL_RESULT_MAX_CHARS,
            model_name=model_config.name,
        )
        # 工具结果预算管控器
        budget_config = BudgetConfig.for_context_window(model_config.max_context)
        budget = ToolResultBudget(config=budget_config, conversation_store=self.store)

        self._agent = InvestmentAgent(
            model_router=model_router,
            tool_registry=tool_registry,
            max_tool_rounds=cfg.AGENT_MAX_TOOL_ROUNDS,
            context_engine=self._context_engine,
            budget=budget,
        )

    async def _ensure_ready(self):
        await self.store.ensure_indexes()

    # ------------------------------------------------------------------
    # 消息重建
    # ------------------------------------------------------------------

    def _rebuild_messages(self, history: list[dict]) -> list[dict]:
        """重建可回放的消息链，正确处理 tool_calls 和 tool result。

        包含防守性逻辑：检测历史消息中重复的 tool_call_id 并重映射为唯一 ID，
        避免 DeepSeek 等 API 因 Duplicate tool_call_id 返回 400 错误。
        """
        messages: list[dict] = []
        valid_tool_call_ids: set[str] = set()

        # 第 0 步：检测重复 tool_call_id 并生成重映射表
        id_remap: dict[tuple[int, int], str] = {}
        seen_ids: set[str] = set()
        assistant_round: int = 0
        has_duplicates: bool = False

        for msg in history:
            if msg["role"] == "assistant" and msg.get("tool_calls_raw"):
                for tc_idx, tc in enumerate(msg["tool_calls_raw"]):
                    if isinstance(tc, dict) and tc.get("id"):
                        old_id = tc["id"]
                        if old_id in seen_ids:
                            new_id = f"soft_tool_{uuid.uuid4().hex[:8]}"
                            id_remap[(assistant_round, tc_idx)] = new_id
                            has_duplicates = True
                        else:
                            seen_ids.add(old_id)
                        valid_tool_call_ids.add(old_id)
                assistant_round += 1

        if has_duplicates:
            logger.info("rebuild_messages_dedup", extra={"remapped_count": len(id_remap)})

        # 第 1 步：重建消息，应用重映射
        assistant_round = 0
        current_remap: dict[str, str] = {}

        for msg in history:
            if msg["role"] == "assistant" and msg.get("tool_calls_raw"):
                current_remap = {}
                updated_tool_calls: list[dict] = []
                for tc_idx, tc in enumerate(msg["tool_calls_raw"]):
                    if isinstance(tc, dict):
                        old_id = tc.get("id", "")
                        new_id = id_remap.get((assistant_round, tc_idx), old_id)
                        if new_id != old_id:
                            current_remap[old_id] = new_id
                        updated_tool_calls.append({**tc, "id": new_id})
                    else:
                        updated_tool_calls.append(tc)
                messages.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": updated_tool_calls,
                })
                assistant_round += 1
            elif msg["role"] == "tool" and msg.get("tool_call_id"):
                if msg["tool_call_id"] in valid_tool_call_ids:
                    remapped_id = current_remap.get(msg["tool_call_id"], msg["tool_call_id"])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": remapped_id,
                        "content": msg.get("content", ""),
                    })
            else:
                messages.append({"role": msg["role"], "content": msg.get("content") or ""})

        # 第 2 步：确保每个 assistant 的 tool_calls 都有对应的 tool result
        final_messages: list[dict] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            final_messages.append(msg)
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                expected_ids = {
                    tc["id"] for tc in msg["tool_calls"]
                    if isinstance(tc, dict) and tc.get("id")
                }
                found_ids: set[str] = set()
                j = i + 1
                while j < len(messages) and messages[j]["role"] == "tool":
                    if messages[j].get("tool_call_id") in expected_ids:
                        found_ids.add(messages[j]["tool_call_id"])
                    final_messages.append(messages[j])
                    j += 1
                for missing_id in expected_ids - found_ids:
                    final_messages.append({
                        "role": "tool",
                        "tool_call_id": missing_id,
                        "content": "[系统提示] 此工具的执行结果在历史记录中丢失，请忽略。",
                    })
                i = j
            else:
                i += 1
        return final_messages

    # ------------------------------------------------------------------
    # 消息构建
    # ------------------------------------------------------------------

    async def _build_messages(self, conversation_id: str, user_id: str, user_message: str) -> list[dict]:
        """保存用户消息、构建 system_prompt + 历史消息"""
        await self.store.add_message(conversation_id, role="user", content=user_message)

        cfg = get_agent_settings()
        history = await self.store.get_messages(
            conversation_id, limit=cfg.AGENT_CONVERSATION_MAX_HISTORY
        )
        rebuilt = self._rebuild_messages(history)

        # System prompt + 记忆冻结快照
        self.memory_manager.reset_turn_counter(conversation_id)
        memory_snapshot = await self.memory_manager.get_frozen_snapshot(user_id)
        system_prompt = get_system_prompt()
        if memory_snapshot:
            system_prompt = system_prompt + "\n\n" + memory_snapshot

        # 对话长度告警
        count = await self.store.count_messages(conversation_id)
        if count > 80:
            system_prompt += (
                f"\n\n[系统告警] 当前对话已有 {count} 条消息，建议新建对话以保持最佳响应质量。"
            )

        # 通过 ContextEngine 准备最终消息（含压缩）
        return await self.context_engine.prepare_messages(
            system_prompt=system_prompt, history=rebuilt,
        )

    # ------------------------------------------------------------------
    # 非流式入口
    # ------------------------------------------------------------------

    async def process_message(
        self,
        conversation_id: str | None,
        message: str,
        user_id: str = "default",
    ) -> dict:
        """处理用户消息并返回 Agent 回复"""
        try:
            await self._ensure_ready()
            if not conversation_id:
                title = message[:30] if len(message) > 30 else message
                conversation_id = await self.store.create_conversation(user_id, title=title)

            messages = await self._build_messages(conversation_id, user_id, message)

            tool_context = {"user_id": user_id, "conversation_id": conversation_id}
            result = await self.agent.run(messages, tool_context=tool_context)

            await self.store.add_message(
                conversation_id, role="assistant",
                content=result["content"],
                tool_calls=result["tool_calls"] if result["tool_calls"] else None,
            )
            return {
                "conversation_id": conversation_id,
                "content": result["content"],
                "tool_calls": result["tool_calls"],
            }
        except Exception as e:
            logger.error("process_message 异常: {}", ErrorHandler.sanitize_error_message(str(e)))
            handler = ErrorHandler()
            safe_msg = handler.sanitize_error_message(str(e))
            return {
                "conversation_id": conversation_id or "",
                "content": f"抱歉，处理您的请求时遇到问题：{safe_msg}",
                "tool_calls": [],
            }

    # ------------------------------------------------------------------
    # 流式入口
    # ------------------------------------------------------------------

    async def process_message_stream(
        self,
        conversation_id: str | None,
        message: str,
        user_id: str = "default",
    ):
        """流式处理用户消息，yield SSE 格式字符串"""
        try:
            # 索引准备
            try:
                await asyncio.wait_for(self._ensure_ready(), timeout=5.0)
            except asyncio.TimeoutError:
                yield _sse("error", {"error": "系统初始化超时，请重试"})
                return
            except Exception as e:
                yield _sse("error", {"error": f"系统初始化失败: {str(e)[:100]}"})
                return

            # 创建或复用对话
            if not conversation_id:
                title = message[:30] if len(message) > 30 else message
                try:
                    conversation_id = await asyncio.wait_for(
                        self.store.create_conversation(user_id, title=title), timeout=10.0,
                    )
                except asyncio.TimeoutError:
                    yield _sse("error", {"error": "对话创建超时，请重试"})
                    return
                except Exception as e:
                    yield _sse("error", {"error": f"对话创建失败: {str(e)[:100]}"})
                    return

            yield _sse("conversation_id", {"conversation_id": conversation_id})

            messages = await self._build_messages(conversation_id, user_id, message)

            full_content = ""
            all_tool_calls: list[dict] = []

            tool_context = {"user_id": user_id, "conversation_id": conversation_id}
            async for event in self.agent.run_stream(messages, tool_context=tool_context):
                event_type = event["event"]
                event_data = event["data"]

                if event_type == "text_delta":
                    full_content += event_data["content"]
                elif event_type == "text_replace":
                    full_content = event_data.get("content", "") or ""
                elif event_type == "tool_result":
                    all_tool_calls.append(event_data)
                    # M3 确认协议：写工具返回 pending_confirmation 时额外推送确认卡片事件
                    tool_result = event_data.get("result")
                    if (
                        isinstance(tool_result, dict)
                        and tool_result.get("status") == "pending_confirmation"
                        and tool_result.get("token")
                    ):
                        yield _sse("confirm_request", {
                            "token": tool_result["token"],
                            "tool_name": event_data.get("name", ""),
                            "preview": tool_result.get("preview") or {},
                            "reused": bool(tool_result.get("reused")),
                        })

                yield _sse(event_type, event_data)

            # 保存 assistant 回复
            await self.store.add_message(
                conversation_id, role="assistant",
                content=full_content,
                tool_calls=all_tool_calls if all_tool_calls else None,
            )

        except Exception as e:
            logger.error("process_message_stream 异常: {}", ErrorHandler.sanitize_error_message(str(e)))
            handler = ErrorHandler()
            safe_msg = handler.sanitize_error_message(str(e))
            yield _sse("error", {"error": safe_msg})


# ======================================================================
# 模块级辅助函数
# ======================================================================

def _json_default(obj):
    """JSON 序列化兜底：处理 numpy、datetime 等非标准类型"""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return str(obj)


def _sse(event: str, data: dict) -> str:
    """构造 SSE 事件字符串"""
    try:
        json_str = json.dumps(data, ensure_ascii=False, default=_json_default)
        return f"event: {event}\ndata: {json_str}\n\n"
    except Exception as e:
        logger.error(f"[SSE] JSON 序列化失败: {e}, event={event}")
        return f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
