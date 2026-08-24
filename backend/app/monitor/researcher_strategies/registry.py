"""研究员策略注册表

集中管理所有可用的研究员策略，提供按 code 查找和列表功能。
新增策略只需：
1. 在本目录新建定义文件（继承 ResearcherStrategyBase）
2. 在下方 _ALL_STRATEGIES 列表中注册实例
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.monitor.researcher_strategies.base import ResearcherStrategyBase
from app.monitor.researcher_strategies.hybrid_12 import HybridMomentum12Strategy
from app.monitor.researcher_strategies.sharpe_18 import SharpeBudget18Strategy

# ── 注册所有研究员策略实例 ──
_ALL_STRATEGIES: List[ResearcherStrategyBase] = [
    HybridMomentum12Strategy(),
    SharpeBudget18Strategy(),
]

# code → 实例 映射
RESEARCHER_STRATEGY_REGISTRY: Dict[str, ResearcherStrategyBase] = {
    s.code: s for s in _ALL_STRATEGIES
}


def get_researcher_strategy(code: str) -> Optional[ResearcherStrategyBase]:
    """按 code 获取研究员策略实例。

    Args:
        code: 策略唯一标识码（如 'hybrid_12', 'sharpe_18'）

    Returns:
        策略实例，未找到返回 None
    """
    return RESEARCHER_STRATEGY_REGISTRY.get(code)


def list_researcher_strategies() -> List[Dict]:
    """列出所有可用研究员策略的摘要信息。

    Returns:
        [{"code", "display_name", "description", "asset_count"}, ...]
    """
    return [
        {
            "code": s.code,
            "display_name": s.display_name,
            "description": s.description,
            "asset_count": len(s.asset_codes),
        }
        for s in _ALL_STRATEGIES
    ]
