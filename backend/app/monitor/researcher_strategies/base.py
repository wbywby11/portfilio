"""研究员策略基类

每个研究员策略继承此基类，提供：
- code: 唯一标识（用于注册表和 source_ref）
- display_name: 展示名称
- description: 策略描述
- asset_codes: 资产池代码列表
- composition: 三层组合配置（selector/allocator/controller/schedule/selection_params）
- strategy_params: 策略参数（传给 allocator.allocate）

通过 build_pipeline() 可直接实例化为 CompositionPipeline。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class ResearcherStrategyBase(ABC):
    """研究员策略基类。

    子类只需实现类属性/方法，即可被 registry 发现并实例化为 CompositionPipeline。
    """

    # ── 子类必须定义 ──

    @property
    @abstractmethod
    def code(self) -> str:
        """策略唯一标识码（如 'hybrid_12', 'sharpe_18'）"""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """策略展示名称"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """策略描述"""
        ...

    @property
    @abstractmethod
    def asset_codes(self) -> List[str]:
        """资产池代码列表（如 ['SH000300', 'SZ399006', ...]）"""
        ...

    @property
    @abstractmethod
    def composition(self) -> Dict[str, Any]:
        """三层组合配置，格式与 CompositionPipeline 的 composition 参数一致。

        必须包含:
        {
            "selector": str | None,
            "allocator": str,
            "controller": str | None,
            "schedule": {"rebalance_freq": ..., "execution_delay": ...},
            "selection_params": {...},  # 选择器参数（可选）
        }
        """
        ...

    @property
    @abstractmethod
    def strategy_params(self) -> Dict[str, Any]:
        """策略参数字典，传给 allocator.allocate()。

        包含分配器参数 + 选择器参数（Pipeline 内部会自动路由）。
        """
        ...

    # ── 可选覆盖 ──

    @property
    def asset_name_map(self) -> Dict[str, str]:
        """资产代码→中文名映射（用于展示）。默认空字典。"""
        return {}

    @property
    def weight_caps(self) -> Dict[str, float]:
        """资产权重上限（代码→上限）。默认空字典（不限制）。"""
        return {}

    @property
    def trading_costs(self) -> Dict[str, float]:
        """交易费率（代码→单次调仓费率）。默认空字典（走全局）。子类写死各自费率。"""
        return {}

    @property
    def replication_costs(self) -> Dict[str, float]:
        """复制费率（代码→年化费率）。默认空字典（走全局）。子类写死各自费率。"""
        return {}

    # ── 核心方法 ──

    def build_pipeline(self):
        """实例化为 CompositionPipeline（与回测共用三层引擎）。

        构造统一经 runner.build_pipeline（引擎唯一构造点契约）。

        Returns:
            CompositionPipeline 实例
        """
        from app.backtesting.runner import build_pipeline

        allocator = self._create_allocator()
        params = dict(self.strategy_params)

        # 注入权重上限
        caps = self.weight_caps
        if caps and "weight_caps" not in params:
            params["weight_caps"] = caps

        return build_pipeline(
            allocator=allocator,
            thscodes=self.asset_codes,
            composition=self.composition,
            strategy_params=params,
        )

    def _create_allocator(self):
        """创建分配器实例。默认 VolScaledBudgetStrategy，子类可覆盖。"""
        from app.allocation.models.vol_scaled_budget import VolScaledBudgetStrategy
        return VolScaledBudgetStrategy()

    def to_monitored_strategy_doc(self) -> Dict[str, Any]:
        """导出为 monitored_strategies 集合的文档格式（用于种子注册）。"""
        return {
            "display_name": self.display_name,
            "source_type": "researcher",
            "source_ref": self.code,
            "description": self.description,
            "asset_codes": self.asset_codes,
            "composition": self.composition,
            "strategy_params": self.strategy_params,
            "weight_caps": self.weight_caps,
            "asset_name_map": self.asset_name_map,
            "status": "active",
        }
