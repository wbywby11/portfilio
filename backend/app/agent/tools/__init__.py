"""
Agent 工具模块 — 纯自注册机制

添加新 Tool 的规范：
1. 在 app/agent/tools/ 下新建 .py 文件
2. 文件中定义一个继承 BaseTool 的类
3. 框架启动时自动扫描、实例化、注册 — 完毕
   无需修改本文件。
"""
import importlib
import pkgutil

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult, ToolRegistry, tool_registry


def auto_discover_tools(registry: ToolRegistry | None = None) -> list[str]:
    """自动扫描 tools 包下所有模块，发现并注册 BaseTool 子类。

    遍历当前包内所有非子包的模块，导入后查找 BaseTool 的非抽象子类，
    并尝试实例化注册到注册表。对于需要构造参数的工具（如记忆工具），
    若实例化失败会被捕获并记录，不影响其他工具。

    Args:
        registry: 目标注册表，默认使用全局 tool_registry。

    Returns:
        成功注册的工具名称列表。
    """
    target = registry or tool_registry

    import app.agent.tools as tools_pkg

    registered: list[str] = []

    for _, modname, ispkg in pkgutil.iter_modules(
        tools_pkg.__path__, tools_pkg.__name__ + "."
    ):
        if ispkg:
            continue
        # 跳过 base 和 pipeline_executor（框架模块，不含 Tool 定义）
        short_name = modname.rsplit(".", 1)[-1]
        if short_name in ("base", "pipeline_executor", "__init__"):
            continue
        try:
            module = importlib.import_module(modname)
        except Exception as e:
            logger.warning(
                "auto_discover_import_failed",
                extra={"module": modname, "error": str(e)},
            )
            continue

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseTool)
                and obj is not BaseTool
                and not getattr(obj, "__abstractmethods__", None)
            ):
                # 跳过已注册的同名工具
                if target.get_tool(getattr(obj, "name", "")):
                    continue
                try:
                    instance = obj()
                    target.register(instance)
                    registered.append(instance.name)
                except Exception as e:
                    logger.warning(
                        "auto_discover_register_failed",
                        extra={"tool_class": attr_name, "error": str(e)},
                    )

    logger.info(
        "auto_discover_completed",
        extra={"registered_count": len(registered), "tools": registered},
    )
    return registered


# ── 模块加载时自动执行工具发现 ──
_discovered = auto_discover_tools()


__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolRegistry",
    "tool_registry",
    "auto_discover_tools",
]
