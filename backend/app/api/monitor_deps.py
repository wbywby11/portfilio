# -*- coding: utf-8 -*-
"""监控 API 共享依赖 —— 服务注入、参数校验与统一错误。

``app/api/monitor.py`` 拆分为三个路由模块（主监控 / 运行批次 / 监测策略台账）后，
三者都要用到同一批依赖函数。放在这里而不是留在 ``monitor.py``，是为了让子模块
可以直接 import 而不触发「子模块 ↔ 主模块」的循环导入。

依赖函数的读写分界（批次化改造后的硬约束）：
- :func:`get_monitor_query_service` —— 纯读表，**所有 GET 端点的唯一数据入口**；
- :func:`get_monitor_service` —— 持有推演组件，**仅写入/触发端点可用**；
- :func:`missing` —— 展示数据缺失（批次未完成 / 缓存未建 / 快照未物化）统一 404。

边界由 ``tests/test_monitor_readonly_endpoints.py`` 的 AST 断言守住。
"""
import re
from datetime import datetime

from fastapi import HTTPException

from app.services.monitor_query_service import MonitorQueryService
from app.services.monitor_service import MonitorService

#: 批次号查询参数的统一描述文案（展示端点均适用）
BATCH_ID_DESC = "运行批次号；不传表示最新 completed 批次"


def get_monitor_service() -> MonitorService:
    """获取监控服务实例（**仅写入/触发端点可用**，GET 端点禁止注入）"""
    return MonitorService()


def get_monitor_query_service() -> MonitorQueryService:
    """获取监控只读查询服务（所有 GET 端点的唯一数据入口）"""
    return MonitorQueryService()


def missing(detail: str) -> HTTPException:
    """展示数据缺失的统一 404（批次未完成 / 缓存未建 / 快照未物化）."""
    return HTTPException(status_code=404, detail=detail)


async def assert_daily_monitor_eligible_gate() -> None:
    """日常监控准入检查：研究员策略始终可用，不再强制要求实盘发布策略。"""
    # 研究员策略始终可用，无需门禁
    pass


def validate_date_format(date_str: str, field_name: str = "日期") -> str:
    """验证日期格式 YYYY-MM-DD"""
    if not date_str:
        return date_str
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    if not re.match(pattern, date_str):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name}格式无效: {date_str}，应为 YYYY-MM-DD"
        )
    # 验证日期有效性
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name}无效: {date_str}，不是有效的日期"
        )
    return date_str


def validate_weights(weights: dict) -> dict:
    """校验权重字典的合法性"""
    if not weights:
        raise HTTPException(status_code=400, detail="权重不能为空")

    for asset, w in weights.items():
        if not isinstance(w, (int, float)):
            raise HTTPException(
                status_code=400,
                detail=f"资产 {asset} 的权重必须是数字，当前值: {w}"
            )
        if w < 0:
            raise HTTPException(
                status_code=400,
                detail=f"资产 {asset} 的权重不能为负数: {w}"
            )

    return weights
