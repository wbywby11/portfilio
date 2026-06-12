"""
任务计划管理器

管理 Agent 的执行计划（ExecutionPlan），支持 MongoDB 持久化。
每个对话最多一个活跃计划，计划包含最多 10 个步骤。
"""
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from loguru import logger

from app.config.database import Database


# ------------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------------

class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlanStep:
    """单个计划步骤"""

    step: str                                           # 步骤描述
    status: StepStatus = StepStatus.PENDING
    tools: list[str] = field(default_factory=list)      # 该步骤可能用的工具
    result_summary: str = ""                            # 完成后的摘要

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "status": self.status.value,
            "tools": self.tools,
            "result_summary": self.result_summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanStep":
        return cls(
            step=data.get("step", ""),
            status=StepStatus(data.get("status", "pending")),
            tools=data.get("tools", []),
            result_summary=data.get("result_summary", ""),
        )


@dataclass
class ExecutionPlan:
    """执行计划"""

    goal: str                                           # 总目标
    steps: list[PlanStep]                               # 步骤列表
    explanation: str = ""                               # 分解理由
    created_at: str = ""                                # ISO 时间
    updated_at: str = ""                                # ISO 时间

    def to_dict(self) -> dict:
        """序列化为可存入 MongoDB 的字典"""
        return {
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "explanation": self.explanation,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionPlan":
        """从 MongoDB 字典反序列化"""
        return cls(
            goal=data.get("goal", ""),
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
            explanation=data.get("explanation", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# ------------------------------------------------------------------
# PlanManager
# ------------------------------------------------------------------

class PlanManager:
    """
    任务计划管理器 — MongoDB 持久化

    集合: agent_plans
    文档结构:
    {
        "_id": ObjectId,
        "conversation_id": str,     # 对话 ID（唯一）
        "plan": {                   # ExecutionPlan 序列化
            "goal": str,
            "steps": [{ "step": str, "status": str, "tools": [str], "result_summary": str }],
            "explanation": str,
            "created_at": str,
            "updated_at": str,
        }
    }

    索引:
    - conversation_id 唯一索引
    """

    COLLECTION = "agent_plans"

    MAX_STEPS = 10
    MAX_IN_PROGRESS = 1

    _indexes_ensured: bool = False
    _index_lock: asyncio.Lock | None = None  # 延迟创建，避免在模块导入时绑定事件循环

    def __init__(self):
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        return self.db[self.COLLECTION]

    async def _ensure_indexes(self):
        """确保索引存在（幂等，仅执行一次，双重检查 + 异步锁保护）"""
        if PlanManager._indexes_ensured:
            return
        # 延迟创建锁，确保在事件循环内
        if PlanManager._index_lock is None:
            PlanManager._index_lock = asyncio.Lock()
        async with PlanManager._index_lock:
            if PlanManager._indexes_ensured:  # 双重检查
                return
            try:
                await self.collection.create_index(
                    "conversation_id",
                    unique=True,
                    name="idx_conversation_id_unique",
                    background=True,
                )
                PlanManager._indexes_ensured = True
                logger.info("计划集合 MongoDB 索引创建完成")
            except Exception as e:
                logger.warning("计划索引创建失败（非致命）: {}", e)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def save_plan(self, conversation_id: str, plan: ExecutionPlan) -> dict:
        """
        保存或更新计划（upsert）

        Returns:
            {"success": True} 或 {"success": False, "error": "..."}
        """
        await self._ensure_indexes()

        # 先校验
        valid, msg = self.validate_plan(plan)
        if not valid:
            return {"success": False, "error": msg}

        try:
            now = datetime.now(timezone.utc).isoformat()
            plan.updated_at = now
            if not plan.created_at:
                plan.created_at = now

            await self.collection.update_one(
                {"conversation_id": conversation_id},
                {"$set": {"plan": plan.to_dict()}},
                upsert=True,
            )
            logger.info("[PlanManager] 保存计划: conversation_id={}, goal={}", conversation_id, plan.goal)
            return {"success": True}
        except Exception as e:
            logger.error("[PlanManager] 保存计划失败: conversation_id={}, error={}", conversation_id, e)
            return {"success": False, "error": f"保存计划失败: {e}"}

    async def get_plan(self, conversation_id: str) -> Optional[ExecutionPlan]:
        """获取对话的当前计划"""
        await self._ensure_indexes()

        try:
            doc = await self.collection.find_one({"conversation_id": conversation_id})
            if doc and "plan" in doc:
                return ExecutionPlan.from_dict(doc["plan"])
            return None
        except Exception as e:
            logger.error("[PlanManager] 获取计划失败: conversation_id={}, error={}", conversation_id, e)
            return None

    async def delete_plan(self, conversation_id: str) -> dict:
        """删除对话的计划"""
        await self._ensure_indexes()

        try:
            result = await self.collection.delete_one({"conversation_id": conversation_id})
            if result.deleted_count > 0:
                logger.info("[PlanManager] 删除计划: conversation_id={}", conversation_id)
                return {"success": True}
            return {"success": False, "error": "计划不存在"}
        except Exception as e:
            logger.error("[PlanManager] 删除计划失败: conversation_id={}, error={}", conversation_id, e)
            return {"success": False, "error": f"删除计划失败: {e}"}

    # ------------------------------------------------------------------
    # 校验 & 格式化
    # ------------------------------------------------------------------

    @staticmethod
    def validate_plan(plan: ExecutionPlan) -> tuple[bool, str]:
        """
        校验计划合法性

        规则:
        1. 步骤数不超过 MAX_STEPS
        2. 最多 MAX_IN_PROGRESS 个 in_progress 步骤
        3. 步骤描述不能为空
        """
        if len(plan.steps) > PlanManager.MAX_STEPS:
            return False, f"步骤数 ({len(plan.steps)}) 超过上限 {PlanManager.MAX_STEPS}"

        in_progress_count = sum(1 for s in plan.steps if s.status == StepStatus.IN_PROGRESS)
        if in_progress_count > PlanManager.MAX_IN_PROGRESS:
            return False, f"同时进行的步骤 ({in_progress_count}) 超过上限 {PlanManager.MAX_IN_PROGRESS}"

        for i, s in enumerate(plan.steps):
            if not s.step.strip():
                return False, f"步骤 {i + 1} 描述为空"

        return True, ""

    @staticmethod
    def format_plan_for_prompt(plan: ExecutionPlan) -> str:
        """格式化计划为 prompt 注入文本"""
        STATUS_ICONS = {
            StepStatus.PENDING: "待执行",
            StepStatus.IN_PROGRESS: "进行中",
            StepStatus.COMPLETED: "已完成",
            StepStatus.FAILED: "已失败",
        }

        lines = ["[当前执行计划]", f"目标: {plan.goal}"]
        for i, step in enumerate(plan.steps, 1):
            icon = STATUS_ICONS.get(step.status, "待执行")
            line = f"{i}. [{icon}] {step.step}"
            if step.result_summary and step.status == StepStatus.COMPLETED:
                line += f" — {step.result_summary}"
            lines.append(line)

        # 进度统计
        completed = sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED)
        total = len(plan.steps)
        lines.append(f"\n进度: {completed}/{total} 步骤已完成")

        return "\n".join(lines)
