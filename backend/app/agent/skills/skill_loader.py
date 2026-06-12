"""技能文件发现、解析和加载模块"""

import yaml
import os
from dataclasses import dataclass, field
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class SkillStep:
    """Skill 中的单个工作流步骤"""
    name: str                                        # 步骤名称
    description: str = ""                            # 步骤描述
    tools: list[str] = field(default_factory=list)   # 该步骤使用的工具
    condition: str = ""                              # 执行条件（自然语言，LLM 判断）
    skip_if: str = ""                                # 跳过条件（自然语言，LLM 判断）


@dataclass
class Skill:
    """技能定义

    每个 Skill 对应一个 Markdown 文件，包含 YAML frontmatter 元数据
    和 Markdown 正文（工作流指导内容）。
    """

    name: str                                       # 唯一标识
    display_name: str                               # 显示名称
    description: str                                # 简要描述
    version: str = "1.0"
    tags: list[str] = field(default_factory=list)
    trigger_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)  # 排除关键词（命中时不匹配）
    toolset: list[str] = field(default_factory=list)   # 关联的工具集名称
    steps: list[SkillStep] = field(default_factory=list)   # 结构化步骤（从 YAML 解析）
    show_plan: bool = False                          # 是否在前端展示执行计划进度（仅复杂多步骤 Skill 开启）
    content: str = ""                               # Markdown 正文内容
    source_file: str = ""                           # 来源文件路径

    def to_prompt_section(self) -> str:
        """生成注入 system prompt 的文本段落（含条件步骤标注）"""
        header = f"### {self.display_name}"
        if not self.steps:
            # 无结构化步骤时，保持原有行为
            return f"{header}\n{self.content}"
        
        lines = [header]
        for i, step in enumerate(self.steps, 1):
            step_line = f"\n**第 {i} 步: {step.name}**"
            if step.tools:
                step_line += f"\n- 工具: {', '.join(step.tools)}"
            if step.description:
                step_line += f"\n- 说明: {step.description}"
            if step.condition:
                step_line += f"\n- 执行条件: {step.condition}"
            if step.skip_if:
                step_line += f"\n- 跳过条件: {step.skip_if}"
            lines.append(step_line)
        
        # 附加 Markdown body 中的详细说明
        if self.content:
            lines.append(f"\n{self.content}")
        return "\n".join(lines)


class SkillLoader:
    """技能文件发现、解析和加载

    扫描指定目录下的 ``.md`` 文件，解析其中的 YAML frontmatter
    与 Markdown body，构建 :class:`Skill` 实例。
    """

    def __init__(self, skills_dir: str):
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, Skill] = {}

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def load_all(self) -> dict[str, Skill]:
        """扫描 skills_dir 下所有 .md 文件并加载为 Skill 对象

        支持 A/B 测试：根据 SKILL_VERSION_CONFIG 配置，
        对指定 Skill 从版本子目录（如 ``docs/v2/``）加载替代版本。
        未配置版本的 Skill 从根目录加载，行为与改造前一致。

        Returns:
            以 skill name 为键的字典
        """
        if not self.skills_dir.exists():
            logger.warning("Skills 目录不存在: %s", self.skills_dir)
            return self._skills

        version_map = self._resolve_active_version()
        if version_map:
            logger.info("Skill 版本配置: %s", version_map)

        loaded: dict[str, Skill] = {}

        # 第一步：加载根目录下的所有默认版本
        for md_file in sorted(self.skills_dir.glob("*.md")):
            try:
                skill = self._parse_file(md_file)
                if skill is not None:
                    loaded[skill.name] = skill
                    logger.debug("已加载 Skill: %s (%s)", skill.name, md_file.name)
            except Exception as exc:
                logger.warning("解析 Skill 文件失败 [%s]: %s", md_file.name, exc)

        # 第二步：对配置了版本的 Skill，尝试从版本子目录替换
        for skill_name, version in version_map.items():
            version_file = self.skills_dir / version / f"{skill_name}.md"
            if version_file.exists():
                try:
                    skill = self._parse_file(version_file)
                    if skill is not None:
                        skill.version = version
                        loaded[skill.name] = skill
                        logger.info(
                            "Skill [%s] 已切换到版本 %s (%s)",
                            skill_name, version, version_file,
                        )
                except Exception as exc:
                    logger.warning(
                        "解析版本文件失败 [%s/%s.md]: %s，使用默认版本",
                        version, skill_name, exc,
                    )
            else:
                logger.warning(
                    "Skill [%s] 版本文件不存在: %s，回退到默认版本",
                    skill_name, version_file,
                )

        self._skills = loaded
        logger.info("共加载 %d 个 Skills", len(self._skills))
        return self._skills

    def reload(self) -> dict[str, Skill]:
        """重新扫描和加载（支持热更新）"""
        logger.info("重新加载 Skills …")
        self._skills.clear()
        return self.load_all()

    def get_skill(self, name: str) -> Skill | None:
        """按名称获取技能"""
        return self._skills.get(name)

    @property
    def skills(self) -> dict[str, Skill]:
        return self._skills

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_active_version() -> dict[str, str]:
        """解析 SKILL_VERSION_CONFIG 配置，返回 {skill_name: version} 映射

        配置格式为逗号分隔的 ``skill_name:version`` 对，例如::

            asset_allocation_analysis:v2,risk_diagnosis:v2

        Returns:
            版本映射字典；配置为空时返回空字典
        """
        from app.agent.core.config import get_agent_settings

        config_str = get_agent_settings().SKILL_VERSION_CONFIG
        version_map: dict[str, str] = {}
        if config_str:
            for item in config_str.split(","):
                item = item.strip()
                if ":" in item:
                    name, version = item.split(":", 1)
                    version_map[name.strip()] = version.strip()
        return version_map

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict, str]:
        """将文件内容拆分为 YAML frontmatter 和 Markdown body

        Args:
            text: 文件全部文本

        Returns:
            (metadata_dict, markdown_body)

        Raises:
            ValueError: 文件不包含有效的 YAML frontmatter
        """
        text = text.strip()
        if not text.startswith("---"):
            raise ValueError("文件缺少 YAML frontmatter (未以 --- 开头)")

        # 找到第二个 ---
        end_idx = text.find("---", 3)
        if end_idx == -1:
            raise ValueError("YAML frontmatter 未闭合 (缺少结束 ---)")

        yaml_text = text[3:end_idx].strip()
        body = text[end_idx + 3:].strip()

        metadata = yaml.safe_load(yaml_text)
        if not isinstance(metadata, dict):
            raise ValueError("YAML frontmatter 不是有效的映射")

        return metadata, body

    def _parse_file(self, filepath: Path) -> Skill | None:
        """解析单个 .md 文件为 Skill 对象"""
        raw = filepath.read_text(encoding="utf-8")
        metadata, body = self._parse_frontmatter(raw)

        name = metadata.get("name")
        if not name:
            logger.warning("Skill 文件缺少 name 字段，跳过: %s", filepath.name)
            return None

        # 解析结构化步骤
        raw_steps = metadata.get("steps", [])
        steps = []
        for s in raw_steps:
            if isinstance(s, dict):
                steps.append(SkillStep(
                    name=str(s.get("name", "")),
                    description=str(s.get("description", "")),
                    tools=list(s.get("tools", [])),
                    condition=str(s.get("condition", "")),
                    skip_if=str(s.get("skip_if", "")),
                ))

        return Skill(
            name=str(name),
            display_name=str(metadata.get("display_name", name)),
            description=str(metadata.get("description", "")),
            version=str(metadata.get("version", "1.0")),
            tags=list(metadata.get("tags", [])),
            trigger_keywords=list(metadata.get("trigger_keywords", [])),
            exclude_keywords=list(metadata.get("exclude_keywords", [])),
            toolset=list(metadata.get("toolset", [])),
            steps=steps,
            show_plan=bool(metadata.get("show_plan", False)),
            content=body,
            source_file=str(filepath),
        )
