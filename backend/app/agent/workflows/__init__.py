"""
Workflow 模块 — 刚性步骤序列执行引擎

三层能力体系中的 Workflow 层：
- Tool:  原子能力（被调用）
- Skill: 灵活长任务（LLM 驱动）
- Workflow: 刚性长任务（引擎驱动，不经过 LLM）

添加新 Workflow 的规范：
1. 在 app/agent/workflows/definitions/ 下新建 .yaml 文件
2. 按 WorkflowDefinition schema 编写步骤定义
3. WorkflowLoader 自动扫描注册 — 完毕
   无需修改本文件。
"""
from app.agent.workflows.engine import (
    WorkflowEngine,
    WorkflowDefinition,
    WorkflowStep,
    WorkflowResult,
    StepResult,
)
from app.agent.workflows.loader import WorkflowLoader
from app.agent.workflows.evaluator import ConditionEvaluator

__all__ = [
    "WorkflowEngine",
    "WorkflowDefinition",
    "WorkflowStep",
    "WorkflowResult",
    "StepResult",
    "WorkflowLoader",
    "ConditionEvaluator",
]
