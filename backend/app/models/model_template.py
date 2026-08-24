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
    MAX_WEIGHT_DICT = "max_weight_dict"


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
    condition: Optional[Dict[str, Any]] = Field(None, description="条件显示规则")
    hidden: bool = Field(False, description="前端是否隐藏")
    group: str = Field("core", description="参数分组: core/advanced")
    
    def to_param_schema(self):
        """转换为策略参数Schema格式.
        
        Returns:
            ParamSchema实例
        """
        from app.allocation.models.param_schema import ParamSchema
        
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
            required=self.required,
            condition=self.condition,
            hidden=self.hidden,
            group=self.group,
        )


class ModelTemplate(BaseModel):
    """模型模板（支持动态策略定义）"""
    id: Optional[str] = Field(None, alias="_id")
    code: str = Field(..., description="模板代码,如M001")
    name: str = Field(..., description="模板名称")
    description: str = Field(..., description="模板描述")
    source_code: Optional[str] = Field(None, description="策略源代码（Python类定义）")
    pdf_filename: Optional[str] = Field(None, description="策略PDF文档文件名（用于前端展示）")
    parameters: List[ModelParameter] = Field(default_factory=list, description="参数定义列表")
    category: Optional[str] = Field("allocation", description="策略分类: allocation/selection/control")
    composition: Optional[Dict[str, Any]] = Field(None, description="三层组合配置: selector/allocator/controller")
    is_active: bool = Field(True, description="是否启用")
    is_builtin: bool = Field(False, description="是否为内置模板（builtin_templates.py 注册）")
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
        from app.allocation.models.param_schema import StrategyParamSchema
        
        param_schemas = [param.to_param_schema() for param in self.parameters]
        
        monitoring_metrics = []
        # 尝试从源代码加载类并获取监控指标
        if self.source_code:
            try:
                from app.allocation.dynamic_loader import DynamicStrategyLoader
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

    @property
    def param_schema(self) -> List[Dict[str, Any]]:
        """参数 JSON Schema 列表（文档对齐字段）

        从 parameters (List[ModelParameter]) 自动生成 dict 列表格式，
        与 DATA_ARCHITECTURE.md 中 param_schema: list[dict] 对齐。
        """
        result = []
        for param in self.parameters:
            item: Dict[str, Any] = {
                "name": param.name,
                "label": param.label,
                "type": param.param_type.value,
                "default": param.default_value,
                "required": param.required,
            }
            if param.description:
                item["description"] = param.description
            if param.options:
                item["options"] = param.options
            if param.min_value is not None:
                item["min_value"] = param.min_value
            if param.max_value is not None:
                item["max_value"] = param.max_value
            if param.step is not None:
                item["step"] = param.step
            result.append(item)
        return result
