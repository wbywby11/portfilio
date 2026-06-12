"""模型模板API模型"""
from typing import List, Any, Optional
from pydantic import BaseModel, Field, field_serializer, field_validator
from app.models.model_template import ParameterType


class ModelParameterOut(BaseModel):
    """模型参数输出模型"""
    name: str = Field(..., description="参数名称")
    label: str = Field(..., description="参数标签(显示名)")
    param_type: ParameterType = Field(..., description="参数类型")
    default_value: Any | None = Field(None, description="默认值")
    required: bool = Field(True, description="是否必填")
    description: Optional[str] = Field(None, description="参数说明")
    options: Optional[List[Any]] = Field(None, description="可选项列表(用于select类型)")
    min_value: Optional[float] = Field(None, description="最小值(用于number类型)")
    max_value: Optional[float] = Field(None, description="最大值(用于number类型)")

    @field_validator('default_value', mode='before')
    @classmethod
    def parse_default(cls, v, info):
        """处理默认值中的JSON字符串"""
        # 注意：mode='before' 时 info.data 可能还不完整，但我们可以尝试处理
        if isinstance(v, str) and (v.strip().startswith('{') or v.strip().startswith('[')):
            import json
            try:
                return json.loads(v)
            except Exception:
                return v
        return v

    @field_serializer('default_value')
    def serialize_default(self, value: Any) -> Any:
        if self.param_type == ParameterType.DICT and isinstance(value, dict):
            import json
            return json.dumps(value, ensure_ascii=False)
        return value



class ModelTemplateCreate(BaseModel):
    """创建模型模板请求"""
    code: str = Field(..., description="模板代码,如M001")
    name: str = Field(..., description="模板名称")
    description: str = Field(..., description="模板描述")
    source_code: Optional[str] = Field(None, description="算法源代码")
    parameters: List[ModelParameterOut] = Field(default_factory=list, description="参数定义列表")


class ModelTemplateOut(ModelTemplateCreate):
    """模型模板输出模型"""
    id: str = Field(..., description="模板ID")
    is_active: bool = Field(..., description="是否启用")
