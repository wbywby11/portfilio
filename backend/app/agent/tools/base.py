"""
工具基类与工具注册表
"""
from abc import ABC, abstractmethod
from typing import Any, Optional

from loguru import logger


class BaseTool(ABC):
    """工具抽象基类"""

    name: str
    description: str
    parameters: dict = None  # JSON Schema

    max_result_chars: int = 8000  # 默认单工具最大结果字符数，子类可覆盖
    tool_timeout: float = 60.0    # 工具执行超时（秒），数据导入等耗时工具可覆盖为更大值

    # ── 元数据（可选，保持向后兼容） ──
    # 注意：使用 None 代替可变默认值，通过 __init_subclass__ 确保每个子类拥有独立副本
    tags: list[str] | None = None           # 语义标签，如 ["资产", "查询"]
    category: str = "general"     # 工具分类: asset / analysis / strategy / backtest / memory / data / general
    dependencies: list[str] | None = None   # 前置工具名称列表，如 ["create_strategy_model"]
    pipeline: list[dict] | None = None   # 自动前置调用链，格式: [{"tool": "name", "extract": "field"}]

    _EMPTY_SCHEMA = {"type": "object", "properties": {}}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # 确保每个子类拥有自己的 tags 和 dependencies 列表，避免共享可变对象
        if cls.tags is None:
            cls.tags = []
        if cls.dependencies is None:
            cls.dependencies = []
        if cls.pipeline is None:
            cls.pipeline = []

    def to_openai_tool(self) -> dict:
        """转换为 OpenAI function calling 格式，确保 parameters schema 合法。
        DeepSeek API 要求 parameters 必须是完整的 JSON Schema 对象
        （type: "object" + properties + required），否则会触发 HTTP 400。
        """
        params = self.parameters
        # 防御：确保 parameters 是完整的 JSON Schema 对象
        if not params or not isinstance(params, dict) or "type" not in params:
            params = {"type": "object", "properties": {}, "required": []}
        elif "properties" not in params:
            params["properties"] = {}
        if "required" not in params:
            params["required"] = []

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs) -> dict:
        """执行工具，返回结果字典"""
        pass

    # ============================================================
    # 血缘辅助方法
    # ============================================================
    @staticmethod
    def attach_lineage(
        result: dict,
        tables: list[str] | None = None,
        domains: list[str] | None = None,
        fields: dict[str, list[str]] | None = None,
        join_path: str = "",
        records_returned: int = 0,
        total_in_collection: int = 0,
        query_operation: str = "",
        views: list[dict] | None = None,
        upstream_lineage: dict | None = None,
        **extra,
    ) -> dict:
        """为工具返回结果附加标准化血缘元数据。

        使用占：所有访问业务表的工具都应调用本方法，避免重复定义血缘结构。

        Args:
            result: 工具原始返回结果（dict）
            tables: 实际访问的表名列表
            domains: 涉及的域代码列表
            fields: {表名: [字段名列表]}
            join_path: 多表关联路径
            records_returned: 实际返回记录数
            total_in_collection: 库内总记录数（反幻觉关键字段）
            query_operation: 工具操作名
            views: 如使用了视图，填充 [{view_id, view_type, view_name}]
            upstream_lineage: 上游工具返回的 _lineage_meta（用于透传补充）
            **extra: 其他自定义字段

        Returns:
            附带 _lineage_meta 字段的 result
        """
        meta: dict = {
            "tables_used": list(tables or []),
            "domains_involved": list(domains or []),
            "fields_accessed": dict(fields or {}),
            "join_path": join_path,
            "records_returned": records_returned,
            "total_in_collection": total_in_collection,
            "query_operation": query_operation,
        }
        if views:
            meta["views_referenced"] = views
        # 透传上游血缘：合并 tables/domains/fields
        if upstream_lineage and isinstance(upstream_lineage, dict):
            up_tables = upstream_lineage.get("tables_used") or []
            for t in up_tables:
                if t not in meta["tables_used"]:
                    meta["tables_used"].append(t)
            up_domains = upstream_lineage.get("domains_involved") or []
            for d in up_domains:
                if d not in meta["domains_involved"]:
                    meta["domains_involved"].append(d)
            up_fields = upstream_lineage.get("fields_accessed") or {}
            for tbl, flds in up_fields.items():
                cur = set(meta["fields_accessed"].get(tbl, []))
                cur.update(flds or [])
                meta["fields_accessed"][tbl] = list(cur)
            meta["upstream_query_operation"] = upstream_lineage.get("query_operation", "")
        meta.update(extra)
        result["_lineage_meta"] = meta
        return result


class ToolResult:
    """标准化工具返回结构（辅助构建器，实际返回仍为 dict）
    
    提供 success() 和 error() 静态方法，帮助工具构建标准化返回格式。
    实际返回值仍然是 dict，保持与现有代码的向后兼容性。
    """
    
    @staticmethod
    def success(data: dict, charts: list | None = None, summary: str = "",
                data_shape: str = "unknown", record_count: int = 0,
                validation: dict = None) -> dict:
        """构建成功返回"""
        result = {"success": True, "data": data, "summary": summary}
        if charts:
            result["charts"] = charts
        result["metadata"] = {
            "data_shape": data_shape,
            "record_count": record_count,
        }
        if validation is not None:
            result["validation"] = validation
        return result
    
    @staticmethod
    def error(message: str, **extra) -> dict:
        """构建错误返回"""
        return {"success": False, "error": message, **extra}


class ToolRegistry:
    """工具注册表"""

    # 预定义工具集：按典型场景分组（新增 Tool 后在此按需填充）
    TOOLSETS: dict[str, list[str]] = {
        "asset": ["query_assets", "query_asset_prices"],
        "data": [
            "smart_table_router",
            "smart_auto_analyze",
            "data_query",
            "domain_query",
            "data_transform",
            "data_analyze",
            "data_visualize",
            "data_template",
            "subject_risk_search",
            "product_hub_query",
            "semantic_profile",
        ],
        "strategy": [
            "list_strategy_types",
            "create_strategy_model",
            "recommend_strategy",
            "compute_weights",
        ],
        "backtest": [
            "execute_backtest",
            "compare_strategies",
        ],
        "portfolio": [
            "create_portfolio",
            "get_portfolio",
            "get_rebalance_history",
            "execute_rebalance",
        ],
        "report": ["generate_strategy_report"],
        "memory": ["save_memory", "recall_memories"],
        "plan": ["update_plan"],
        # 与前端 agentScenes toolset: 'credit' 对齐，供 Skill / 扩展引用
        "credit": [
            "data_query",
            "data_transform",
            "data_analyze",
            "data_visualize",
            "data_template",
            "subject_risk_search",
            "save_memory",
            "recall_memories",
            "update_plan",
        ],
    }

    # 分类中文映射（用于摘要输出，新增分类时在此扩展）
    _CATEGORY_LABELS: dict[str, str] = {
        "asset": "资产类工具",
        "data": "数据分析工具",
        "strategy": "策略类工具",
        "backtest": "回测类工具",
        "portfolio": "组合管理工具",
        "memory": "记忆工具",
        "plan": "计划工具",
        "general": "通用工具",
    }

    # 始终可用的基础工具（不受动态过滤影响，新增基础工具时在此扩展）
    BASE_TOOLS: set[str] = set()

    # 通用工具名称列表（用于场景过滤和提示构建）
    COMMON_TOOLS: list[str] = []

    # 业务场景到工具名称的映射（新增场景时在此扩展）
    SCENE_TOOLSETS: dict[str, list[str]] = {
        "data_analysis": [
            "smart_table_router",
            "smart_auto_analyze",
            "data_query",
            "domain_query",
            "data_transform",
            "data_analyze",
            "data_visualize",
            "data_template",
            "semantic_profile",
            "save_memory",
            "recall_memories",
            "update_plan",
        ],
        "enterprise_data_qa": [
            "smart_table_router",
            "smart_auto_analyze",
            "subject_risk_search",
            "product_hub_query",
            "data_query",
            "domain_query",
            "data_transform",
            "data_analyze",
            "data_visualize",
            "data_template",
            "semantic_profile",
            "save_memory",
            "recall_memories",
            "update_plan",
        ],
        "credit_rating": [
            "smart_table_router",
            "smart_auto_analyze",
            "data_query",
            "domain_query",
            "data_transform",
            "data_analyze",
            "data_visualize",
            "data_template",
            "semantic_profile",
            "subject_risk_search",
            "save_memory",
            "recall_memories",
            "update_plan",
        ],
        "asset_research": [
            "query_assets",
            "query_asset_prices",
            "domain_query",
            "data_analyze",
            "list_strategy_types",
            "create_strategy_model",
            "execute_backtest",
            "compare_strategies",
            "recommend_strategy",
            "compute_weights",
            "create_portfolio",
            "get_portfolio",
            "get_rebalance_history",
            "execute_rebalance",
            "generate_strategy_report",
            "save_memory",
            "recall_memories",
            "update_plan",
        ],
    }

    # 智能匹配初始工具集（用于自动模式下的工具选择）
    AUTO_MODE_TOOLS: list[str] = [
        "smart_table_router",
        "smart_auto_analyze",
        "data_query",
        "domain_query",
        "data_analyze",
        "data_transform",
        "data_visualize",
        "data_import",
        "subject_risk_search",
        "product_hub_query",
    ]

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册工具"""
        self._tools[tool.name] = tool

    def register_dynamic(self, tool: BaseTool) -> None:
        """运行时动态注册工具。允许覆盖已有工具，支持热更新。"""
        action = "updated" if tool.name in self._tools else "registered"
        self._tools[tool.name] = tool
        logger.info(
            "tool_dynamic_registered",
            extra={"tool_name": tool.name, "action": action},
        )

    def get_tool(self, name: str) -> BaseTool | None:
        """按名称获取工具"""
        return self._tools.get(name)

    def get_all_tools(self) -> list[BaseTool]:
        """获取所有已注册工具"""
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict]:
        """获取所有工具的 OpenAI function calling 格式列表"""
        return [t.to_openai_tool() for t in self._tools.values()]

    def get_scene_tools(self, scene: str) -> list[BaseTool]:
        """按场景返回已注册的工具实例列表（仅返回实际存在的工具）。

        Args:
            scene: 业务场景名称，如 "asset_research", "data_analysis" 等。

        Returns:
            该场景下已在注册表中的工具实例列表。
        """
        names = self.SCENE_TOOLSETS.get(scene, [])
        return [self._tools[n] for n in names if n in self._tools]

    def get_filtered_openai_tools(self, toolset_names: list[str]) -> list[dict]:
        """根据工具集名称列表，返回过滤后的 OpenAI 工具格式

        支持预定义工具集（TOOLSETS）和业务场景工具集（SCENE_TOOLSETS）。

        Args:
            toolset_names: 工具集或场景名称列表（如 ["research", "asset_research"]）

        Returns:
            过滤后的工具 schema 列表。如果 toolset_names 为空，返回全部工具。
        """
        if not toolset_names:
            return self.get_openai_tools()

        allowed = set(self.COMMON_TOOLS)
        for ts_name in toolset_names:
            names = self.TOOLSETS.get(ts_name, [])
            allowed.update(names)
            scene_names = self.SCENE_TOOLSETS.get(ts_name, [])
            allowed.update(scene_names)
            # 直接工具名：ts_name 本身就是一个已注册工具名时，纳入白名单
            if ts_name in self._tools:
                allowed.add(ts_name)

        return [t.to_openai_tool() for t in self._tools.values() if t.name in allowed]

    # ── 元数据查询方法 ──────────────────────────────────────

    def get_tools_by_category(self, category: str) -> list[BaseTool]:
        """按分类获取工具列表"""
        return [t for t in self._tools.values() if getattr(t, "category", "general") == category]

    def get_tools_by_tags(self, tags: list[str]) -> list[BaseTool]:
        """按标签获取工具（任意匹配）"""
        tag_set = set(tags)
        return [
            t for t in self._tools.values()
            if tag_set & set(getattr(t, "tags", []))
        ]

    def get_toolset(self, toolset_name: str) -> list[BaseTool]:
        """获取预定义工具集"""
        names = self.TOOLSETS.get(toolset_name, [])
        return [self._tools[n] for n in names if n in self._tools]

    def get_tool_metadata_summary(self) -> str:
        """生成工具分组摘要文本（用于注入 system prompt）"""
        groups: dict[str, list[str]] = {}
        for tool in self._tools.values():
            cat = getattr(tool, "category", "general")
            groups.setdefault(cat, []).append(tool.name)

        lines = []
        for cat, label in self._CATEGORY_LABELS.items():
            if cat in groups:
                lines.append(f"[{label}] {', '.join(groups[cat])}")
        # 处理未在映射中的分类
        for cat, names in groups.items():
            if cat not in self._CATEGORY_LABELS:
                lines.append(f"[{cat}] {', '.join(names)}")
        return "\n".join(lines)

    # ── 依赖关系查询方法 ──────────────────────────────────

    def get_dependency_hint(self, tool_name: str) -> Optional[str]:
        """获取工具的依赖提示信息"""
        tool = self.get_tool(tool_name)
        if not tool or not tool.dependencies:
            return None
        dep_names = ", ".join(tool.dependencies)
        return f"注意：{tool.name}({tool_name}) 建议先调用以下工具：{dep_names}"

    def get_dependency_graph_text(self) -> str:
        """生成工具依赖关系图的文本描述，用于注入系统 prompt"""
        lines = ["## 工具依赖关系", "以下工具有前置依赖，请按顺序调用："]
        has_deps = False
        for name, tool in sorted(self._tools.items()):
            if tool.dependencies:
                has_deps = True
                deps = " → ".join(tool.dependencies)
                lines.append(f"- {deps} → {name}")
        if not has_deps:
            return ""
        return "\n".join(lines)


# 全局工具注册表实例
tool_registry = ToolRegistry()
