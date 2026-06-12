"""会话级数据上下文 — 存储工具输出，支持跨轮次数据引用"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger


class DataContext:
    """
    每个对话拥有独立的 DataContext 实例，工具执行结果自动存入，
    后续工具可通过 source_ref 参数引用历史数据。

    类似 Jupyter Notebook 的单元格输出机制。
    """

    _instances: dict[str, "DataContext"] = {}
    MAX_RECORDS_PER_ENTRY = 10000
    TTL_SECONDS = 7200  # 2 小时过期

    @classmethod
    def get_instance(cls, conversation_id: str) -> "DataContext":
        """获取或创建会话的 DataContext"""
        cls._cleanup_expired()
        if conversation_id not in cls._instances:
            cls._instances[conversation_id] = cls(conversation_id)
        return cls._instances[conversation_id]

    @classmethod
    def _cleanup_expired(cls) -> None:
        """清理过期实例"""
        now = time.time()
        expired = [
            cid for cid, ctx in cls._instances.items()
            if now - ctx._last_access > cls.TTL_SECONDS
        ]
        for cid in expired:
            logger.info("data_context_expired", extra={"conversation_id": cid})
            del cls._instances[cid]

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self._store: dict[str, dict] = {}      # key → {data, metadata}
        self._tool_history: list[dict] = []     # 有序的工具调用历史
        self._step_counter: int = 0
        self._last_access: float = time.time()
        self._created_at: float = time.time()

    def store(
        self,
        data: Any,
        tool_name: str,
        params: dict,
        key: str | None = None,
    ) -> str:
        """
        存储数据集，返回引用 key。

        Args:
            data: 工具返回的数据（通常是 records 列表或 dict）
            tool_name: 产生数据的工具名
            params: 工具调用参数
            key: 自定义 key，不提供则自动生成 step_N

        Returns:
            存储 key（如 "step_1"）
        """
        self._last_access = time.time()

        if key is None:
            self._step_counter += 1
            key = f"step_{self._step_counter}"

        # 限制记录数
        if isinstance(data, list) and len(data) > self.MAX_RECORDS_PER_ENTRY:
            logger.warning("data_context_truncated", extra={
                "key": key, "original": len(data),
                "limit": self.MAX_RECORDS_PER_ENTRY,
            })
            data = data[:self.MAX_RECORDS_PER_ENTRY]

        entry: dict = {
            "data": data,
            "metadata": {
                "tool_name": tool_name,
                "params": params,
                "record_count": len(data) if isinstance(data, list) else 1,
                "created_at": time.time(),
            },
        }
        self._store[key] = entry

        # 记录工具调用历史
        self._tool_history.append({
            "step_key": key,
            "tool_name": tool_name,
            "params": params,
            "record_count": entry["metadata"]["record_count"],
            "timestamp": time.time(),
        })

        logger.info("data_context_stored", extra={
            "conversation_id": self.conversation_id,
            "key": key,
            "tool": tool_name,
            "records": entry["metadata"]["record_count"],
        })
        return key

    def get(self, key: str) -> Any | None:
        """获取数据集"""
        self._last_access = time.time()
        entry = self._store.get(key)
        if entry is None:
            logger.warning("data_context_miss", extra={
                "conversation_id": self.conversation_id, "key": key,
            })
            return None
        return entry["data"]

    def get_entry(self, key: str) -> dict | None:
        """获取完整条目（含元数据）"""
        self._last_access = time.time()
        return self._store.get(key)

    def list_datasets(self) -> list[dict]:
        """列出当前会话所有可用数据集摘要"""
        self._last_access = time.time()
        return [
            {
                "key": key,
                "tool_name": entry["metadata"]["tool_name"],
                "record_count": entry["metadata"]["record_count"],
            }
            for key, entry in self._store.items()
        ]

    def get_tool_history(self) -> list[dict]:
        """获取工具调用历史（用于工作流录制）"""
        self._last_access = time.time()
        return list(self._tool_history)

    @property
    def step_count(self) -> int:
        return self._step_counter

    def get_context_summary(self) -> str:
        """生成可注入 Prompt 的上下文摘要"""
        if not self._store:
            return ""
        lines: list[str] = ["当前会话已有数据："]
        for key, entry in self._store.items():
            meta = entry["metadata"]
            lines.append(
                f"- {key}: {meta['tool_name']} 产出, "
                f"{meta['record_count']} 条记录"
            )
        lines.append("后续工具可通过 source_ref 参数引用以上数据。")
        return "\n".join(lines)
