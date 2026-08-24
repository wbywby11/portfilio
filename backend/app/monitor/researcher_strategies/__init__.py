"""研究员策略模块

将研究员独立开发的策略以一等公民形式管理，每个策略产出一个完整的
composition 定义，可直接实例化为 CompositionPipeline（与回测共用三层引擎）。

新增策略：
1. 在本目录新建定义文件（继承 ResearcherStrategyBase）
2. 在 registry.py 中注册
"""

from app.monitor.researcher_strategies.registry import (
    RESEARCHER_STRATEGY_REGISTRY,
    get_researcher_strategy,
    list_researcher_strategies,
)

__all__ = [
    "RESEARCHER_STRATEGY_REGISTRY",
    "get_researcher_strategy",
    "list_researcher_strategies",
]
