"""app.backtesting —— 系统计算引擎（包名保留历史命名）.

定位声明
--------
本包是系统的**计算引擎**，"回测"只是其运行模式之一。全量历史回测、
监控每日前向推演、模拟交易、组合第二段引擎运行+产品层四种计算模式共享本包的
同一份策略计算逻辑，保证多模式结果一致；内核修复对所有模式同时生效。
组合层的编排（合成资产 + 组合权重 allocator）位于应用层
``app.portfolio.composite_runner``，经唯一入口 ``run_unified`` 调用本包内核。

包内三层结构
------------
1. 计算内核（模式无关，纯计算）
   composition_pipeline / composition_builder / strategy_api / engine /
   schedule / data_feed / execution / risk / signal / types / config /
   synthetic_feed / runner
2. 模式编排（产品层叠加）
   product_layer
3. 报告分析（指标口径委托 app.analysis.performance，不自行实现公式）
   analytics / portfolio_analytics

依赖方向规则（由 tests/test_backtesting_boundary.py 守卫）
----------------------------------------------------------
- 允许：上层（api / services / portfolio / monitor）导入本包
- 允许：本包向下依赖策略三层（selection / allocation / control）
- 禁止：本包反向依赖 api / monitor / portfolio / services
  （白名单例外见 docs/backtesting计算引擎架构.md 第 3 节）

facade 用法
-----------
新代码推荐从包级导入关键符号（懒加载，按需解析子模块）：

    from app.backtesting import BacktestEngine, CompositionPipeline
    from app.backtesting import RunSpec, run_unified

存量 ``from app.backtesting.<module> import ...`` 细粒度导入完全兼容，
不强制迁移。
"""
from __future__ import annotations

from typing import Any

# facade 符号 → 所在子模块（懒加载映射，避免包导入时的 eager 依赖）
_FACADE: dict = {
    # 计算内核
    "CompositionPipeline": "composition_pipeline",
    "build_strategy_composition": "composition_builder",
    "IStrategy": "strategy_api",
    "BacktestEngine": "engine",
    "BacktestConfig": "config",
    "ScheduleResolver": "schedule",
    "DataFeed": "data_feed",
    "ExecutionEngine": "execution",
    "RiskManager": "risk",
    "RiskConfig": "risk",
    # 合成资产价格构建（组合第二段引擎运行的数据输入）
    "build_synthetic_prices": "synthetic_feed",
    # 唯一运行入口（两步计算：generate_targets / run_unified）
    "RunSpec": "runner",
    "run_unified": "runner",
    "generate_targets": "runner",
    "build_pipeline": "runner",
    # 报告分析
    "PerformanceAnalyzer": "analytics",
    "PerformanceSummary": "analytics",
}

__all__ = sorted(_FACADE)


def __getattr__(name: str) -> Any:
    """PEP 562 懒加载 facade：首次访问时才导入对应子模块."""
    module_name = _FACADE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value  # 缓存，后续访问零开销
    return value


def __dir__() -> list:
    return sorted(set(globals()) | set(__all__))
