"""资产选择器基类."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from app.selection.types import SelectionResult


class BaseAssetSelector(ABC):
    """资产选择器抽象基类.
    
    所有选择器需要实现：
    1. select() 方法：执行资产选择
    2. get_param_schema() 方法：返回参数Schema
    """
    
    @abstractmethod
    def select(
        self, 
        prices: pd.DataFrame, 
        n_assets: int,
        **params
    ) -> "SelectionResult":
        """从价格数据中筛选资产.
        
        Args:
            prices: 候选资产价格矩阵（index: 日期，columns: 资产代码）
            n_assets: 选择资产数量
            **params: 选择器参数
        
        Returns:
            SelectionResult: 选择结果（包含选中资产、得分、排名等）
        """
        raise NotImplementedError
    
    @classmethod
    def get_param_schema(cls):
        """返回参数Schema定义（用于前端表单生成）.
        
        Returns:
            dict: 参数Schema字典
        """
        return {
            "selector_type": cls.__name__,
            "display_name": cls.__name__,
            "description": "",
            "params": []
        }
