"""统一API响应封装"""
from typing import TypeVar, Generic, Optional, Any
from pydantic import BaseModel, Field


T = TypeVar('T')


class Response(BaseModel, Generic[T]):
    """统一响应模型"""
    code: int = Field(default=200, description="响应状态码: 200=成功, 其他=失败")
    message: str = Field(default="success", description="响应消息")
    data: Optional[T] = Field(default=None, description="响应数据")
    
    class Config:
        json_schema_extra = {
            "example": {
                "code": 200,
                "message": "success",
                "data": None
            }
        }
    
    @classmethod
    def success(cls, data: T = None, message: str = "success") -> "Response[T]":
        """成功响应"""
        return cls(code=200, message=message, data=data)
    
    @classmethod
    def error(cls, message: str = "error", code: int = 500, data: T = None) -> "Response[T]":
        """错误响应"""
        return cls(code=code, message=message, data=data)


class PageData(BaseModel, Generic[T]):
    """分页数据模型"""
    items: list[T] = Field(default_factory=list, description="数据列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=10, description="每页记录数")
    pages: int = Field(default=0, description="总页数")
    
    class Config:
        json_schema_extra = {
            "example": {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 10,
                "pages": 0
            }
        }
