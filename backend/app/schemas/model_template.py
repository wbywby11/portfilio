"""模型模板API模型"""
from typing import Dict, List, Any, Optional
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
    step: Optional[float] = Field(None, description="步长(用于number/slider类型)")
    condition: Optional[Dict[str, Any]] = Field(None, description="条件显示规则")
    hidden: bool = Field(False, description="前端是否隐藏")
    group: str = Field("core", description="参数分组: core/advanced")

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

    @field_validator('options', mode='before')
    @classmethod
    def coerce_options(cls, v):
        """历史脏数据兼容：options 若为字符串则尝试按 JSON 解析，
        无法还原的损坏值（如被 String() 强转的 '[object Object],...'）置 None，避免 PUT 422"""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if s.startswith('['):
                import json
                try:
                    return json.loads(s)
                except Exception:
                    return None
            return None
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
    source_code: Optional[str] = Field(None, description="策略源代码")
    pdf_filename: Optional[str] = Field(None, description="策略PDF文档文件名")
    parameters: List[ModelParameterOut] = Field(default_factory=list, description="参数定义列表")
    category: Optional[str] = Field("allocation", description="策略分类: allocation/selection/control")
    strategy_form: Optional[str] = Field(
        "composite",
        description="策略形态: composite=三层组合 / standalone=打包独立",
    )
    composition: Optional[dict] = Field(None, description="三层组合配置")


class ModelTemplateOut(ModelTemplateCreate):
    """模型模板输出模型"""
    id: str = Field(..., description="模板ID")
    is_active: bool = Field(..., description="是否启用")
