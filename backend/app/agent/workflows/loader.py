"""
Workflow YAML 定义加载器

自动扫描 definitions/ 目录下的 .yaml 文件，
解析为 WorkflowDefinition 对象并注册到内部注册表。

添加新 Workflow 的规范：
1. 在 app/agent/workflows/definitions/ 下新建 .yaml 文件
2. 必须包含 workflow_id, name, steps 字段
3. 本加载器自动扫描注册，无需修改其他代码
"""
import yaml
from pathlib import Path
from typing import Optional

from loguru import logger

from app.agent.workflows.engine import WorkflowDefinition, WorkflowStep


class WorkflowLoader:
    """Workflow YAML 文件发现、解析和管理

    使用方式:
        loader = WorkflowLoader("/path/to/definitions")
        loader.load_all()
        wf = loader.get_workflow("asset_price_batch")
    """

    def __init__(self, definitions_dir: str) -> None:
        """
        Args:
            definitions_dir: YAML 定义文件所在目录的绝对路径
        """
        self.definitions_dir = Path(definitions_dir)
        self._workflows: dict[str, WorkflowDefinition] = {}

    def load_all(self) -> dict[str, WorkflowDefinition]:
        """扫描目录下所有 .yaml/.yml 文件并加载

        Returns:
            以 workflow_id 为键的字典
        """
        if not self.definitions_dir.exists():
            logger.warning("[WorkflowLoader] 定义目录不存在: {}", self.definitions_dir)
            return self._workflows

        loaded: dict[str, WorkflowDefinition] = {}

        for yaml_file in sorted(self.definitions_dir.glob("*.yaml")):
            try:
                wf = self._parse_file(yaml_file)
                if wf:
                    loaded[wf.workflow_id] = wf
                    logger.debug("[WorkflowLoader] 已加载: {} ({})", wf.name, yaml_file.name)
            except Exception as e:
                logger.warning("[WorkflowLoader] 解析失败 [{}]: {}", yaml_file.name, e)

        # 也扫描 .yml 扩展名
        for yml_file in sorted(self.definitions_dir.glob("*.yml")):
            try:
                wf = self._parse_file(yml_file)
                if wf and wf.workflow_id not in loaded:
                    loaded[wf.workflow_id] = wf
                    logger.debug("[WorkflowLoader] 已加载: {} ({})", wf.name, yml_file.name)
            except Exception as e:
                logger.warning("[WorkflowLoader] 解析失败 [{}]: {}", yml_file.name, e)

        self._workflows = loaded
        logger.info("[WorkflowLoader] 共加载 {} 个 Workflow", len(self._workflows))
        return self._workflows

    def reload(self) -> dict[str, WorkflowDefinition]:
        """重新扫描和加载（支持热重载）"""
        logger.info("[WorkflowLoader] 重新加载 Workflows …")
        self._workflows.clear()
        return self.load_all()

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """按 ID 获取工作流定义"""
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> list[dict]:
        """返回所有已注册工作流的摘要列表"""
        return [
            {
                "workflow_id": wf.workflow_id,
                "name": wf.name,
                "description": wf.description,
                "step_count": len(wf.steps),
            }
            for wf in self._workflows.values()
        ]

    @property
    def workflows(self) -> dict[str, WorkflowDefinition]:
        return self._workflows

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_file(filepath: Path) -> Optional[WorkflowDefinition]:
        """解析单个 YAML 文件为 WorkflowDefinition"""
        raw = filepath.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)

        if not isinstance(data, dict):
            logger.warning("[WorkflowLoader] YAML 内容不是映射: {}", filepath.name)
            return None

        workflow_id = data.get("workflow_id")
        if not workflow_id:
            logger.warning("[WorkflowLoader] 缺少 workflow_id: {}", filepath.name)
            return None

        name = data.get("name", workflow_id)
        description = data.get("description", "")
        input_schema = data.get("input_schema", {})

        # 解析步骤
        raw_steps = data.get("steps", [])
        steps: list[WorkflowStep] = []
        for s in raw_steps:
            if not isinstance(s, dict):
                continue
            step_id = s.get("step_id")
            tool_name = s.get("tool_name")
            if not step_id or not tool_name:
                logger.warning(
                    "[WorkflowLoader] 步骤缺少 step_id 或 tool_name: {} in {}",
                    s, filepath.name,
                )
                continue
            steps.append(WorkflowStep(
                step_id=str(step_id),
                name=str(s.get("name", step_id)),
                tool_name=str(tool_name),
                parameters=dict(s.get("parameters", {})),
                condition=str(s.get("condition", "")),
                on_failure=str(s.get("on_failure", "abort")),
                retry_count=int(s.get("retry_count", 0)),
                timeout=float(s.get("timeout", 60.0)),
            ))

        if not steps:
            logger.warning("[WorkflowLoader] 无有效步骤: {}", filepath.name)
            return None

        return WorkflowDefinition(
            workflow_id=str(workflow_id),
            name=str(name),
            description=str(description),
            steps=steps,
            input_schema=input_schema,
        )
