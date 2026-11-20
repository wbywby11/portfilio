"""实盘组合引用查询.

取消发布/删除策略前的依赖守卫共用：实盘组合的日常监控要求成员保持可用，
成员取消发布或被删除都会使组合监控直接失败。
"""
from typing import Any, List


async def live_portfolios_using(collection, model_id: str) -> List[str]:
    """返回实盘发布中且引用该模型的组合名称。

    同时检查组合实盘快照与当前成员：实盘快照决定正在运行的成员，
    当前成员覆盖实盘标记存在但快照缺失的存量数据。
    """
    names: List[str] = []
    cursor = collection.find(
        {"is_portfolio": True, "live_publish_enabled": True},
        {"name": 1, "sub_strategies": 1, "live_snapshot": 1},
    )
    async for doc in cursor:
        members: List[Any] = []
        live_snap = doc.get("live_snapshot") or {}
        if isinstance(live_snap, dict):
            members.extend(live_snap.get("sub_strategies") or [])
        members.extend(doc.get("sub_strategies") or [])
        for sub in members:
            if isinstance(sub, dict) and str(sub.get("model_id") or "") == model_id:
                names.append(doc.get("name") or str(doc.get("_id")))
                break
    return names


async def ensure_not_used_by_live_portfolio(
    collection, model_id: str, action: str
) -> None:
    """被实盘组合引用时拒绝操作（action 如“删除”“取消发布”）."""
    names = await live_portfolios_using(collection, model_id)
    if names:
        raise ValueError(
            f"该策略正被实盘组合使用，不能{action}：{'、'.join(names)}；"
            "请先取消组合实盘并调整组合成员（重新实盘发布）后再操作"
        )
