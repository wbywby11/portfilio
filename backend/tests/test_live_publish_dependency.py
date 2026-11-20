# -*- coding: utf-8 -*-
"""实盘组合引用守卫测试（不依赖数据库）.

已实盘发布的组合引用成员策略时：
1. 成员不能取消发布；
2. 成员不能删除。
两项拦截都必须发生在任何状态变更/级联清理之前。
"""
import asyncio
from types import SimpleNamespace

import pytest

from app.models.strategy_model import ModelStatus
from app.services.live_portfolio_usage import live_portfolios_using
from app.services.live_publish_service import LivePublishService
from app.services.strategy_model_service import StrategyModelService


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        self._iter = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection=None):
        return _Cursor([
            d for d in self.docs
            if d.get("is_portfolio") and d.get("live_publish_enabled")
        ])


class _LiveModels:
    """LivePublishService 依赖的最小模型服务替身。"""

    def __init__(self, model, docs):
        self.model = model
        self.collection = _Collection(docs)

    async def get_model(self, model_id):
        return self.model


def _model_service(docs):
    svc = StrategyModelService.__new__(StrategyModelService)
    svc._collection = _Collection(docs)
    return svc


def _live_service(model, docs):
    svc = LivePublishService.__new__(LivePublishService)
    svc._models = _LiveModels(model, docs)
    return svc


def _live_portfolio_doc(name="实盘组合", members=("m1",), snapshot_members=None):
    snapshot_members = members if snapshot_members is None else snapshot_members
    return {
        "name": name,
        "is_portfolio": True,
        "live_publish_enabled": True,
        "live_snapshot": {
            "sub_strategies": [{"model_id": mid} for mid in snapshot_members]
        },
        "sub_strategies": [{"model_id": mid} for mid in members],
    }


def test_live_portfolios_using_reads_snapshot_and_ignores_non_live():
    docs = [
        _live_portfolio_doc(),
        {
            "name": "非实盘组合",
            "is_portfolio": True,
            "live_publish_enabled": False,
            "live_snapshot": {},
            "sub_strategies": [{"model_id": "m1"}],
        },
    ]
    assert asyncio.run(live_portfolios_using(_Collection(docs), "m1")) == ["实盘组合"]


def test_live_portfolios_using_falls_back_to_current_members():
    docs = [_live_portfolio_doc(members=("m1",), snapshot_members=("other",))]
    assert asyncio.run(live_portfolios_using(_Collection(docs), "m1")) == ["实盘组合"]


def test_unpublish_blocked_when_member_of_live_portfolio():
    svc = _live_service(
        SimpleNamespace(status=ModelStatus.PUBLISHED, name="成员策略"),
        [_live_portfolio_doc()],
    )
    with pytest.raises(ValueError, match="不能取消发布"):
        asyncio.run(svc.unpublish_model("m1"))


def test_delete_blocked_when_member_of_live_portfolio():
    svc = _model_service([_live_portfolio_doc()])

    async def fake_get_model(model_id):
        return SimpleNamespace(status=ModelStatus.PUBLISHED, name="成员策略")

    svc.get_model = fake_get_model
    with pytest.raises(ValueError, match="不能删除"):
        asyncio.run(svc.delete_model("m1"))
