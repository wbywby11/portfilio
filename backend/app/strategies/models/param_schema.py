"""策略参数Schema定义，用于前后端参数配置与验证."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Optional


@dataclass
class ParamSchema:
    """单个策略参数的元信息定义.
    
    用于前端动态生成表单，以及后端参数验证。
    """
    
    name: str  # 参数名称（内部标识）
    label: str  # 参数显示名称（前端展示）
    type: Literal["number", "slider", "select", "text", "checkbox", "dict"]  # 输入组件类型
    default: Any  # 默认值
    description: str = ""  # 参数说明
    
    # 数值类参数
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    
    # 选择类参数
    options: Optional[List[tuple[Any, str]]] = None  # [(value, label), ...]
    
    # 验证规则
    required: bool = False
    
    def validate(self, value: Any) -> tuple[bool, str]:
        """验证参数值是否符合规范.
        
        Returns:
            (is_valid, error_message)
        """
        # 必填检查
        if self.required and value is None:
            return False, f"参数 {self.label} 为必填项"
        
        if value is None:
            return True, ""
        
        # 类型检查
        if self.type in ["number", "slider"]:
            try:
                value = float(value)
            except (ValueError, TypeError):
                return False, f"参数 {self.label} 必须为数值"
            
            if self.min_value is not None and value < self.min_value:
                return False, f"参数 {self.label} 不能小于 {self.min_value}"
            
            if self.max_value is not None and value > self.max_value:
                return False, f"参数 {self.label} 不能大于 {self.max_value}"
        
        elif self.type == "select":
            if self.options:
                valid_values = [opt[0] for opt in self.options]
                if value not in valid_values:
                    return False, f"参数 {self.label} 的值不在可选范围内"
        
        elif self.type == "dict":
            if isinstance(value, str):
                import json
                try:
                    json.loads(value)
                except Exception:
                    return False, f"参数 {self.label} 必须是有效的JSON字符串"
            elif not isinstance(value, dict):
                return False, f"参数 {self.label} 必须是字典或JSON字符串"
        
        return True, ""


@dataclass
class StrategyParamSchema:
    """策略完整参数Schema.
    
    包含策略的所有参数定义和元信息。
    """
    
    strategy_type: str  # 策略类型标识
    display_name: str  # 策略显示名称
    description: str  # 策略说明
    params: List[ParamSchema]  # 参数列表
    
    # 扩展：支持的监控指标及其对应的阈值参数
    # 格式: [{"name": "portfolio_volatility", "label": "组合波动率", "threshold_param": "vol_reset_threshold"}]
    monitoring_metrics: List[dict[str, str]] = None
    
    def validate_params(self, params_dict: dict[str, Any]) -> tuple[bool, List[str]]:
        """验证参数字典是否符合Schema定义.
        
        Returns:
            (is_valid, error_messages)
        """
        errors = []
        
        for param_schema in self.params:
            value = params_dict.get(param_schema.name)
            is_valid, error_msg = param_schema.validate(value)
            
            if not is_valid:
                errors.append(error_msg)
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> dict:
        """转换为字典格式，便于前端使用."""
        import json
        
        def serialize_value(val, p_type):
            if p_type == "dict" and isinstance(val, dict):
                return json.dumps(val, ensure_ascii=False)
            return val

        return {
            "strategy_type": self.strategy_type,
            "display_name": self.display_name,
            "description": self.description,
            "monitoring_metrics": self.monitoring_metrics or [],
            "params": [
                {
                    "name": p.name,
                    "label": p.label,
                    "type": p.type,
                    "default": serialize_value(p.default, p.type),
                    "description": p.description,
                    "min_value": p.min_value,
                    "max_value": p.max_value,
                    "step": p.step,
                    "options": p.options,
                    "required": p.required,
                }
                for p in self.params
            ],
        }
