"""资产选择服务 - 选择器管理与调度."""

from __future__ import annotations

from typing import Any, Dict, List, TYPE_CHECKING

import pandas as pd

from app.selection.selectors.base import BaseAssetSelector
from app.selection.types import SelectionResult

if TYPE_CHECKING:
    pass


class SelectionService:
    """资产选择服务.
    
    核心职责：
    1. 选择器注册管理：维护选择器类型到实现类的映射
    2. 参数验证：基于Schema验证选择器参数
    3. 资产选择执行：提供统一的资产选择接口
    """
    
    def __init__(self):
        # 选择器注册表：{selector_type: selector_class}
        self._registry: Dict[str, type[BaseAssetSelector]] = {}
    
    def register(self, selector_type: str, selector_cls: type[BaseAssetSelector]) -> None:
        """注册选择器类型.
        
        Args:
            selector_type: 选择器类型标识（如 "momentum"）
            selector_cls: 选择器实现类（必须继承BaseAssetSelector）
        """
        if not issubclass(selector_cls, BaseAssetSelector):
            raise TypeError(f"{selector_cls} 必须继承 BaseAssetSelector")
        
        self._registry[selector_type] = selector_cls
    
    def list_selector_types(self) -> List[str]:
        """列出所有已注册的选择器类型."""
        return list(self._registry.keys())
    
    def get_selector_class(self, selector_type: str) -> type[BaseAssetSelector]:
        """获取选择器实现类.
        
        Args:
            selector_type: 选择器类型标识
        
        Returns:
            选择器实现类
        
        Raises:
            KeyError: 选择器类型不存在
        """
        if selector_type not in self._registry:
            raise KeyError(f"选择器类型 '{selector_type}' 未注册")
        
        return self._registry[selector_type]
    
    def get_param_schema(self, selector_type: str) -> dict:
        """获取选择器参数Schema.
        
        Args:
            selector_type: 选择器类型标识
        
        Returns:
            Schema字典（包含参数定义、显示名称、说明等）
        
        Raises:
            KeyError: 选择器类型不存在
        """
        selector_cls = self.get_selector_class(selector_type)
        schema = selector_cls.get_param_schema()
        return schema
    
    def select_assets(
        self,
        selector_type: str,
        prices: pd.DataFrame,
        n_assets: int,
        **params
    ) -> SelectionResult:
        """执行资产选择.
        
        Args:
            selector_type: 选择器类型
            prices: 候选资产价格矩阵
            n_assets: 选择资产数量
            **params: 选择器参数
        
        Returns:
            SelectionResult: 选择结果
        
        Raises:
            KeyError: 选择器类型不存在
            ValueError: 参数验证失败或选择执行失败
        """
        selector_cls = self.get_selector_class(selector_type)
        selector = selector_cls()
        result = selector.select(prices, n_assets, **params)
        return result
