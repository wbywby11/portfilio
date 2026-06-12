"""
计划管理工具 — 包装 PlanManager 为 BaseTool

提供 1 个计划相关 BaseTool：
- update_plan  创建或更新 Agent 执行计划
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.agent.core.plan_manager import (
    PlanManager,
    ExecutionPlan,
    PlanStep,
    StepStatus,
)


class UpdatePlanTool(BaseTool):
    """创建或更新 Agent 执行计划"""

    name = "update_plan"
    description = (
        "创建或更新当前对话的执行计划。"
        "计划包含目标和步骤列表（最多10步），每个步骤有状态标记。"
        "同一时刻最多1个步骤为进行中。"
    )
    category = "plan"
    tags = ["计划", "任务管理", "执行"]
    parameters = {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "任务总目标",
            },
            "steps": {
                "type": "array",
                "description": "步骤列表，每项包含步骤描述和状态",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {
                            "type": "string",
                            "description": "步骤描述",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "failed"],
                            "description": "步骤状态",
                        },
                        "tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "该步骤可能使用的工具名称列表",
                        },
                        "result_summary": {
                            "type": "string",
                            "description": "步骤完成后的结果摘要",
                        },
                    },
                    "required": ["step", "status"],
                },
            },
            "explanation": {
                "type": "string",
                "description": "计划分解理由说明",
            },
        },
        "required": ["goal", "steps"],
    }

    async def execute(self, **kwargs: Any) -> dict:
        """执行计划更新流程"""
        # ── 1. 提取参数 ──
        tool_context: dict = kwargs.get("tool_context", {})
        conversation_id: str = tool_context.get("conversation_id", "")
        if not conversation_id:
            return ToolResult.error("缺少 conversation_id，无法保存计划")

        goal: str = kwargs.get("goal", "")
        steps_raw: list[dict] = kwargs.get("steps", [])
        explanation: str = kwargs.get("explanation", "")

        if not goal:
            return ToolResult.error("goal 不能为空")
        if not steps_raw:
            return ToolResult.error("steps 不能为空")

        # ── 2. 构建 PlanStep 列表 ──
        plan_steps: list[PlanStep] = []
        for raw in steps_raw:
            try:
                status = StepStatus(raw.get("status", "pending"))
            except ValueError:
                return ToolResult.error(
                    f"无效的步骤状态: {raw.get('status')}，"
                    f"允许值: pending, in_progress, completed, failed"
                )
            plan_steps.append(
                PlanStep(
                    step=raw.get("step", ""),
                    status=status,
                    tools=raw.get("tools", []),
                    result_summary=raw.get("result_summary", ""),
                )
            )

        # ── 3. 构建 ExecutionPlan ──
        plan = ExecutionPlan(
            goal=goal,
            steps=plan_steps,
            explanation=explanation,
        )

        # ── 4. 校验计划 ──
        valid, msg = PlanManager.validate_plan(plan)
        if not valid:
            logger.warning(
                "plan_validation_failed",
                extra={"conversation_id": conversation_id, "reason": msg},
            )
            return ToolResult.error(f"计划校验失败: {msg}")

        # ── 5. 保存计划 ──
        plan_manager = PlanManager()
        save_result = await plan_manager.save_plan(conversation_id, plan)

        if not save_result.get("success"):
            return ToolResult.error(
                save_result.get("error", "计划保存失败")
            )

        # ── 6. 构建返回 ──
        completed_count = sum(
            1 for s in plan_steps if s.status == StepStatus.COMPLETED
        )
        total_count = len(plan_steps)

        logger.info(
            "plan_updated",
            extra={
                "conversation_id": conversation_id,
                "goal": goal,
                "completed": completed_count,
                "total": total_count,
            },
        )

        return {
            "success": True,
            "plan": plan.to_dict(),
            "summary": f"计划更新成功: {completed_count}/{total_count} 步骤已完成",
        }
