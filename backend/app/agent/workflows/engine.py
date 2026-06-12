"""
Workflow 引擎 — 纯步骤序列执行器

按 YAML 定义的步骤顺序调用 Tool，不经过 LLM。
支持参数模板渲染、条件分支、失败策略（abort/skip/retry）和超时控制。
"""
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from loguru import logger

from app.agent.workflows.evaluator import ConditionEvaluator


# ── 数据模型 ──────────────────────────────────────────────

@dataclass
class WorkflowStep:
    """单个工作流步骤"""
    step_id: str                                    # 唯一标识
    name: str                                       # 步骤名称（用于日志和展示）
    tool_name: str                                  # 调用的 Tool 名称
    parameters: dict = field(default_factory=dict)  # 参数模板，支持 "${step_id.field}" 引用
    condition: str = ""                             # 安全表达式，引擎求值
    on_failure: str = "abort"                       # 失败策略: "abort" | "skip" | "retry"
    retry_count: int = 0                            # 重试次数（仅 on_failure="retry" 时生效）
    timeout: float = 60.0                           # 超时秒数


@dataclass
class WorkflowDefinition:
    """工作流定义"""
    workflow_id: str                                 # 唯一标识
    name: str                                        # 工作流名称
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    input_schema: dict = field(default_factory=dict)  # JSON Schema，校验输入


@dataclass
class StepResult:
    """单步执行结果"""
    step_id: str
    status: str = "completed"                        # "completed" | "skipped" | "failed"
    output: dict = field(default_factory=dict)
    duration_ms: int = 0
    error: str = ""


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    workflow_id: str
    status: str = "completed"                        # "completed" | "failed" | "partial"
    step_results: list[StepResult] = field(default_factory=list)
    final_output: dict = field(default_factory=dict)  # 最后一步的输出
    total_duration_ms: int = 0


# ── 参数模板渲染 ──────────────────────────────────────────

# 匹配 ${xxx.yyy} 或 ${xxx} 模板变量
_TEMPLATE_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_ref(ref_path: str, context: dict[str, Any]) -> Any:
    """解析模板引用路径（如 'input.asset_codes' 或 'step_id.field'）

    Args:
        ref_path: 点分路径，如 "input.asset_codes" 或 "get_prices.data.prices"
        context: 上下文字典

    Returns:
        解析到的值，未找到返回 None
    """
    parts = ref_path.split(".")
    current: Any = context
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def render_parameters(template: dict, context: dict[str, Any]) -> dict:
    """渲染参数模板，将 ${ref} 替换为 context 中的实际值

    支持嵌套字典和列表中的模板变量。
    当整个值是一个 "${ref}" 时，保留原始类型（非字符串）；
    当值是包含 "${ref}" 的字符串时，做字符串替换。

    Args:
        template: 参数模板字典
        context: 上下文字典

    Returns:
        渲染后的参数字典
    """
    result: dict = {}
    for key, value in template.items():
        result[key] = _render_value(value, context)
    return result


def _render_value(value: Any, context: dict[str, Any]) -> Any:
    """递归渲染单个值"""
    if isinstance(value, str):
        # 整个值是单一模板引用 → 保留原始类型
        match = _TEMPLATE_PATTERN.fullmatch(value)
        if match:
            resolved = _resolve_ref(match.group(1), context)
            return resolved if resolved is not None else value

        # 部分模板引用 → 字符串替换
        def _replacer(m: re.Match) -> str:
            resolved = _resolve_ref(m.group(1), context)
            return str(resolved) if resolved is not None else m.group(0)

        return _TEMPLATE_PATTERN.sub(_replacer, value)

    if isinstance(value, dict):
        return {k: _render_value(v, context) for k, v in value.items()}

    if isinstance(value, list):
        return [_render_value(item, context) for item in value]

    return value


# ── 引擎 ──────────────────────────────────────────────────

class WorkflowEngine:
    """纯引擎执行器 — 按步骤顺序调用 Tool，不经过 LLM

    使用方式:
        engine = WorkflowEngine(tool_registry)
        result = await engine.execute(workflow_def, inputs={"asset_codes": [...]})
    """

    def __init__(self, tool_registry: Any) -> None:
        """
        Args:
            tool_registry: ToolRegistry 实例，用于查找工具
        """
        self.tool_registry = tool_registry
        self._evaluator = ConditionEvaluator()

    async def execute(
        self,
        workflow: WorkflowDefinition,
        inputs: dict[str, Any],
        on_step_complete: Optional[Callable] = None,
    ) -> WorkflowResult:
        """执行工作流

        Args:
            workflow: 工作流定义
            inputs: 用户输入参数
            on_step_complete: 步骤完成回调 (step_result) → 用于前端进度推送

        Returns:
            WorkflowResult
        """
        start_time = time.monotonic()
        context: dict[str, Any] = {"input": inputs}
        step_results: list[StepResult] = []
        final_status = "completed"

        logger.info(
            "[Workflow] 开始执行: {} ({})",
            workflow.name, workflow.workflow_id,
            extra={"workflow_id": workflow.workflow_id},
        )

        for step in workflow.steps:
            step_result = await self._execute_step(step, context)
            step_results.append(step_result)

            # 存入上下文供后续步骤引用
            if step_result.status == "completed":
                context[step.step_id] = step_result.output

            # 回调
            if on_step_complete:
                try:
                    on_step_complete(step_result)
                except Exception as e:
                    logger.warning("[Workflow] 步骤回调异常: {}", e)

            # 失败处理
            if step_result.status == "failed" and step.on_failure == "abort":
                final_status = "failed"
                logger.error(
                    "[Workflow] 步骤 {} 失败，中止工作流: {}",
                    step.step_id, step_result.error,
                )
                break

        total_ms = int((time.monotonic() - start_time) * 1000)

        # 确定最终输出
        last_completed = None
        for sr in reversed(step_results):
            if sr.status == "completed":
                last_completed = sr
                break

        result = WorkflowResult(
            workflow_id=workflow.workflow_id,
            status=final_status,
            step_results=step_results,
            final_output=last_completed.output if last_completed else {},
            total_duration_ms=total_ms,
        )

        logger.info(
            "[Workflow] 执行完成: {} | 状态={} | 耗时={}ms",
            workflow.workflow_id, final_status, total_ms,
        )
        return result

    async def _execute_step(
        self,
        step: WorkflowStep,
        context: dict[str, Any],
    ) -> StepResult:
        """执行单个步骤"""
        step_start = time.monotonic()

        # 1. 条件求值
        if step.condition:
            try:
                should_run = self._evaluator.evaluate(step.condition, context)
                if not should_run:
                    logger.info("[Workflow] 步骤 {} 条件不满足，跳过", step.step_id)
                    return StepResult(
                        step_id=step.step_id,
                        status="skipped",
                        duration_ms=0,
                    )
            except Exception as e:
                logger.warning("[Workflow] 步骤 {} 条件求值异常: {}，继续执行", step.step_id, e)

        # 2. 查找工具
        tool = self.tool_registry.get_tool(step.tool_name)
        if not tool:
            return StepResult(
                step_id=step.step_id,
                status="failed",
                error=f"工具 '{step.tool_name}' 未注册",
                duration_ms=int((time.monotonic() - step_start) * 1000),
            )

        # 3. 渲染参数
        try:
            params = render_parameters(step.parameters, context)
        except Exception as e:
            return StepResult(
                step_id=step.step_id,
                status="failed",
                error=f"参数渲染失败: {e}",
                duration_ms=int((time.monotonic() - step_start) * 1000),
            )

        # 4. 执行（含重试）
        max_attempts = (step.retry_count + 1) if step.on_failure == "retry" else 1
        last_error = ""

        for attempt in range(max_attempts):
            try:
                logger.info(
                    "[Workflow] 执行步骤 {}.{} → tool={}{}",
                    step.step_id, step.name, step.tool_name,
                    f" (尝试 {attempt + 1}/{max_attempts})" if max_attempts > 1 else "",
                )
                output = await asyncio.wait_for(
                    tool.execute(**params),
                    timeout=step.timeout,
                )
                duration_ms = int((time.monotonic() - step_start) * 1000)

                # 检查工具返回是否为错误
                if isinstance(output, dict) and output.get("error"):
                    last_error = str(output["error"])
                    if attempt < max_attempts - 1:
                        logger.warning("[Workflow] 步骤 {} 返回错误，重试: {}", step.step_id, last_error)
                        continue
                    # 最后一次尝试仍失败
                    if step.on_failure == "skip":
                        return StepResult(step_id=step.step_id, status="skipped", error=last_error, duration_ms=duration_ms)
                    return StepResult(step_id=step.step_id, status="failed", error=last_error, duration_ms=duration_ms)

                return StepResult(
                    step_id=step.step_id,
                    status="completed",
                    output=output if isinstance(output, dict) else {"result": output},
                    duration_ms=duration_ms,
                )

            except asyncio.TimeoutError:
                last_error = f"超时 ({step.timeout}s)"
                logger.warning("[Workflow] 步骤 {} 超时", step.step_id)
            except Exception as e:
                last_error = str(e)
                logger.error("[Workflow] 步骤 {} 执行异常: {}", step.step_id, e)

        # 所有尝试用尽
        duration_ms = int((time.monotonic() - step_start) * 1000)
        if step.on_failure == "skip":
            return StepResult(step_id=step.step_id, status="skipped", error=last_error, duration_ms=duration_ms)
        return StepResult(step_id=step.step_id, status="failed", error=last_error, duration_ms=duration_ms)
