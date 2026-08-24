"""策略配置数据结构定义."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class StrategyConfig:
    """策略实例配置.
    
    用于保存用户配置的策略实例，包括策略类型、资产池和参数。
    配置持久化后可在回测、持仓建议等场景中复用。
    
    Attributes:
        id: 策略实例唯一标识
        name: 策略显示名称
        type: 策略类型标识（对应注册的策略类）
        thscodes: 默认资产池
        params: 策略参数字典
    """
    
    id: str
    name: str
    type: str
    thscodes: List[str]
    params: Dict[str, Any]
    
    def to_dict(self) -> dict:
        """转换为字典格式（用于序列化）."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "thscodes": self.thscodes,
            "params": self.params
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> StrategyConfig:
        """从字典构造（用于反序列化）."""
        return cls(
            id=data["id"],
            name=data["name"],
            type=data["type"],
            thscodes=data["thscodes"],
            params=data["params"]
        )
