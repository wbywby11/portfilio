"""参数版本快照 API Schema"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ParamVersionOut(BaseModel):
    """参数版本快照输出（供前端消费）"""

    id: str = Field(..., description="MongoDB _id")
    model_id: str = Field(..., description="关联的策略模型 ID")
    version: int = Field(..., description="版本号")

    allocator_params: Dict[str, Any] = Field(default_factory=dict)
    selector_enabled: bool = Field(False)
    selector_type: Optional[str] = Field(None)
    selector_params: Dict[str, Any] = Field(default_factory=dict)
    controller_code: Optional[str] = Field(None)
    controller_params: Dict[str, Any] = Field(default_factory=dict)

    template_code: str = Field("")
    asset_codes: List[str] = Field(default_factory=list)
    change_summary: Optional[str] = Field(None)
    created_at: datetime = Field(...)
    created_by: Optional[str] = Field(None)
    backtest_count: int = Field(0, description="该版本关联的回测记录数")

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v: Any) -> str:
        return str(v) if v is not None else ""

    model_config = {"protected_namespaces": ()}
