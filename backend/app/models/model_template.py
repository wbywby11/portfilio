"""
模型模板数据模型
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class ParameterType(str, Enum):
    """参数类型"""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    SELECT = "select"
    DATE = "date"
    ARRAY = "array"
    SLIDER = "slider"
    TEXT = "text"
    CHECKBOX = "checkbox"
    DICT = "dict"


class ModelParameter(BaseModel):
    """模型参数定义（统一参数Schema）"""
    name: str = Field(..., description="参数名称")
    label: str = Field(..., description="参数标签(显示名)")
    param_type: ParameterType = Field(..., description="参数类型")
    default_value: Any = Field(None, description="默认值")
    required: bool = Field(True, description="是否必填")
    description: Optional[str] = Field(None, description="参数说明")
    options: Optional[List[Any]] = Field(None, description="可选项(用于select类型)")
    min_value: Optional[float] = Field(None, description="最小值(用于number类型)")
    max_value: Optional[float] = Field(None, description="最大值(用于number类型)")
    step: Optional[float] = Field(None, description="步长(用于number/slider类型)")
    
    def to_param_schema(self):
        """转换为策略参数Schema格式.
        
        Returns:
            ParamSchema实例
        """
        from app.strategies.models.param_schema import ParamSchema
        
        # 类型映射
        type_mapping = {
            "string": "text",
            "number": "number",
            "boolean": "checkbox",
            "select": "select",
            "slider": "slider",
            "text": "text",
            "checkbox": "checkbox",
            "dict": "dict"
        }
        
        param_type = type_mapping.get(self.param_type.value, "text")
        
        # 处理选项格式：[(value, label), ...]
        options = None
        if self.options and param_type == "select":
            options = [(opt, opt) for opt in self.options] if isinstance(self.options[0], (str, int, float)) else self.options
        
        return ParamSchema(
            name=self.name,
            label=self.label,
            type=param_type,
            default=self.default_value,
            description=self.description or "",
            min_value=self.min_value,
            max_value=self.max_value,
            step=self.step,
            options=options,
            required=self.required
        )


class ModelTemplate(BaseModel):
    """模型模板（支持动态策略定义）"""
    id: Optional[str] = Field(None, alias="_id")
    code: str = Field(..., description="模板代码,如M001")
    name: str = Field(..., description="模板名称")
    description: str = Field(..., description="模板描述")
    source_code: Optional[str] = Field(None, description="算法源代码（Python类定义）")
    parameters: List[ModelParameter] = Field(default_factory=list, description="参数定义列表")
    is_active: bool = Field(True, description="是否启用")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}
    
    def to_strategy_param_schema(self):
        """转换为策略参数Schema格式.
        
        Returns:
            StrategyParamSchema实例
        """
        from app.strategies.models.param_schema import StrategyParamSchema
        
        param_schemas = [param.to_param_schema() for param in self.parameters]
        
        monitoring_metrics = []
        # 尝试从源代码加载类并获取监控指标
        if self.source_code:
            try:
                from app.strategies.dynamic_loader import DynamicStrategyLoader
                strategy_cls = DynamicStrategyLoader.load_strategy_class_from_template(self)
                if hasattr(strategy_cls, "get_param_schema"):
                    cls_schema = strategy_cls.get_param_schema()
                    if hasattr(cls_schema, "monitoring_metrics") and cls_schema.monitoring_metrics:
                        monitoring_metrics = cls_schema.monitoring_metrics
            except Exception:
                # 忽略加载错误，回退到空列表
                pass
        
        return StrategyParamSchema(
            strategy_type=self.code,
            display_name=self.name,
            description=self.description,
            params=param_schemas,
            monitoring_metrics=monitoring_metrics
        )
