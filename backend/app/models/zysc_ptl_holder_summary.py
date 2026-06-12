"""
产品持有人汇总 ZYSC_DWD_PTL_HOLDER_SUMMARY — 字段白名单（与上游返回中文列名一致）
"""

from __future__ import annotations

from typing import List

from app.config.settings import settings

HOLDER_NATURAL_PRIMARY = "_holder_row_uid"

# 业务字段 + 入库后合成的复合主键（非上游原生）
HOLDER_SUMMARY_FIELDS: List[str] = [
    HOLDER_NATURAL_PRIMARY,
    "产品代码",
    "生效日期",
    "前十份额",
    "前十金额",
    "个人份额",
    "个人金额",
    "机构份额",
    "机构金额",
    "数据日期",
    "数据时间",
    "数据来源",
    "导入方法",
]

HOLDER_SUMMARY_DATE_FIELDS: List[str] = [
    "生效日期",
    "数据日期",
]
