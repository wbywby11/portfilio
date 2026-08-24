# -*- coding: utf-8 -*-
"""
统一导入协议 —— ImportResponse Schema 与 ImportMode 枚举

DATA_IMPORT_SPEC.md Layer 2 规定：
  所有导入端点返回统一 ImportResponse 格式。

使用方式：
    from app.schemas.import_protocol import ImportResponse, ImportMode
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ImportMode(str, Enum):
    """导入模式"""
    UPSERT = "upsert"           # 按业务主键 upsert（默认）
    REPLACE = "replace"         # 清空后全量覆盖
    INCREMENTAL = "incremental"  # 仅新增，已有跳过
    STRICT = "strict"           # 有任何错误则全部回滚


class ImportErrorCode(str, Enum):
    """导入错误码"""
    PARSE_FAILED = "parse_failed"         # 文件/格式解析失败
    MISSING_REQUIRED = "missing_required"  # 必填字段缺失
    TYPE_MISMATCH = "type_mismatch"       # 字段类型不匹配
    INVALID_VALUE = "invalid_value"       # 值域校验失败
    REF_NOT_FOUND = "ref_not_found"       # 外键引用不存在
    DUPLICATE_KEY = "duplicate_key"       # 主键重复（仅 strict 模式）
    INTERNAL = "internal"                 # 服务端内部错误


class ImportErrorDetail(BaseModel):
    """单条导入错误明细"""
    row_index: Optional[int] = Field(None, description="出错行号（0-based）")
    code: str = Field(..., description="错误码（ImportErrorCode）")
    field: Optional[str] = Field(None, description="出错字段名")
    message: str = Field(..., description="人类可读错误描述")
    raw_value: Optional[Any] = Field(None, description="原始值")


class ImportResponse(BaseModel):
    """
    统一导入响应 Schema

    所有导入端点（资产、行情、汇率、交易日历、期权等）
    统一返回此格式，便于前端统一解析和审计日志记录。
    """
    target_collection: str = Field(..., description="目标集合名")
    mode: ImportMode = Field(ImportMode.UPSERT, description="导入模式")
    total_rows: int = Field(0, description="文件/请求中总行数")
    inserted_count: int = Field(0, description="新增条数")
    updated_count: int = Field(0, description="更新条数")
    skipped_count: int = Field(0, description="跳过条数")
    error_count: int = Field(0, description="错误条数")
    errors: List[ImportErrorDetail] = Field(
        default_factory=list,
        description="错误明细（最多前 50 条）",
    )
    skipped_reasons: Dict[str, int] = Field(
        default_factory=dict,
        description="跳过原因分类，如 {'non_trade_day': 3, 'duplicate': 5}",
    )
    date_range: Optional[str] = Field(None, description="数据日期范围 YYYY-MM-DD ~ YYYY-MM-DD")
    import_id: Optional[str] = Field(None, description="审计日志 ID")

    @property
    def success(self) -> bool:
        """是否全部成功（无错误）"""
        return self.error_count == 0

    @property
    def touched_count(self) -> int:
        """实际写入条数（新增 + 更新）"""
        return self.inserted_count + self.updated_count

    def to_audit_stats(self) -> Dict[str, int]:
        """生成审计日志中的 stats 字段"""
        return {
            "total_rows": self.total_rows,
            "inserted": self.inserted_count,
            "updated": self.updated_count,
            "skipped": self.skipped_count,
            "errors": self.error_count,
        }
