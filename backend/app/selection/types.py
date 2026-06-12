"""资产选择模块数据类型定义."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
import pandas as pd


@dataclass
class SelectionResult:
    """资产选择结果.
    
    包含选中的资产列表、各资产得分、排名详情等信息。
    """
    
    selected_assets: List[str]  # 选中的资产代码
    scores: Dict[str, float]    # 各资产的综合得分
    ranking: pd.DataFrame       # 完整排名表（包含所有因子）
    timestamp: str              # 选择时间戳
    selector_type: str          # 选择器类型
    params: Dict[str, Any]      # 使用的参数
    tags: Dict[str, str] = None  # 资产来源标签(可选,用于动量+反转等多模型选择)
    
    def to_dict(self) -> dict:
        """转换为字典格式."""
        result = {
            "selected_assets": self.selected_assets,
            "scores": self.scores,
            "ranking": self.ranking.to_dict() if isinstance(self.ranking, pd.DataFrame) else {},
            "timestamp": self.timestamp,
            "selector_type": self.selector_type,
            "params": self.params
        }
        if self.tags is not None:
            result["tags"] = self.tags
        return result
