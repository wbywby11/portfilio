"""
回测域工具 — query_backtests（读）+ run_backtest（写，需确认）

query_backtests action:
- list：回测记录列表（全库最近记录或按 model_id 过滤，四指标 + 区间摘要）
- detail：单条回测记录详情（四指标 + 净值曲线图表 + 权重轨迹摘要）

run_backtest：基于策略配置实例执行回测（两阶段确认，确认后自动持久化回测记录）。

复用链路：COL_BACKTEST_RECORDS 投影查询 + COL_STRATEGY_MODELS 名称回填；
run_backtest 复用 backtest_orchestration.run_backtest_by_model_core。
"""
from bson import ObjectId

from app.agent.tools._helpers import (
    fmt_date, fmt_datetime, line_chart, pct, round_or_none, sample_series,
)
from app.agent.tools.base import BaseTool, ConfirmableTool

# list 投影字段（只取四指标，不拉曲线/持仓等大字段）
_LIST_PROJECTION = {
    "model_id": 1, "start_date": 1, "end_date": 1, "initial_capital": 1,
    "benchmark_code": 1, "created_at": 1,
    "result.total_return": 1, "result.annual_return": 1,
    "result.annual_volatility": 1, "result.sharpe_ratio": 1,
    "result.max_drawdown": 1, "result.calmar_ratio": 1,
    "result.latest_unit_value": 1,
}


class QueryBacktestsTool(BaseTool):
    """回测记录查询工具"""

    name = "query_backtests"
    description = (
        "查询回测记录。两种模式：\n"
        "1) action=list：列出最近回测记录（可按 model_id 过滤），含四指标"
        "（年化收益/年化波动/夏普/最大回撤）与回测区间\n"
        "2) action=detail：查单条回测记录详情（传 record_id），含完整指标、"
        "净值曲线图表与权重变化轨迹摘要"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "detail"],
                "description": "查询模式",
            },
            "model_id": {
                "type": "string",
                "description": "list 模式按策略配置实例 ID 过滤（可选）",
            },
            "record_id": {
                "type": "string",
                "description": "detail 模式的回测记录 ID（必填）",
            },
            "limit": {
                "type": "integer",
                "description": "list 模式返回条数上限（默认 20，最大 50）",
            },
        },
        "required": ["action"],
    }

    max_result_chars = 10000

    async def execute(
        self,
        action: str = "list",
        model_id: str = "",
        record_id: str = "",
        limit: int = 20,
        **kwargs,
    ) -> dict:
        from app.services.strategy_model_service import StrategyModelService

        model_service = StrategyModelService()
        if action == "list":
            return await self._list_records(model_service, model_id, limit)
        if action == "detail":
            if not record_id:
                return {"success": False, "error": "detail 模式需要 record_id"}
            return await self._record_detail(model_service, record_id)
        return {"success": False, "error": f"未知 action: {action}（可选 list/detail）"}

    # ------------------------------------------------------------------

    async def _list_records(self, model_service, model_id: str, limit: int) -> dict:
        collection = model_service.backtest_collection
        limit = max(1, min(int(limit or 20), 50))

        query = {"model_id": model_id} if model_id else {}
        docs = []
        cursor = collection.find(query, _LIST_PROJECTION).sort("created_at", -1).limit(limit)
        async for doc in cursor:
            docs.append(doc)

        # 批量回填策略模型名称
        name_map = await self._model_name_map(model_service, {d.get("model_id", "") for d in docs})

        records = []
        for doc in docs:
            result = doc.get("result") or {}
            records.append({
                "id": str(doc["_id"]),
                "model_name": name_map.get(doc.get("model_id", ""), ""),
                "model_id": doc.get("model_id", ""),
                "start_date": fmt_date(doc.get("start_date")),
                "end_date": fmt_date(doc.get("end_date")),
                "annual_return_pct": pct(result.get("annual_return")),
                "annual_vol_pct": pct(result.get("annual_volatility")),
                "sharpe": round_or_none(result.get("sharpe_ratio"), 3),
                "max_drawdown_pct": pct(result.get("max_drawdown")),
                "latest_unit_value": round_or_none(result.get("latest_unit_value")),
                "created_at": fmt_datetime(doc.get("created_at")),
            })

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "metadata": {"record_count": len(records)},
            "summary": (
                f"共查到 {len(records)} 条回测记录（收益/波动/回撤为百分比）。"
                if records else "未查到回测记录。"
            ),
            "hint": "使用 action=detail 并传 record_id 可查看净值曲线与权重轨迹",
        }

    async def _record_detail(self, model_service, record_id: str) -> dict:
        collection = model_service.backtest_collection
        try:
            doc = await collection.find_one({"_id": ObjectId(record_id)})
        except Exception:
            return {"success": False, "error": f"无效的 record_id: {record_id}"}
        if not doc:
            return {"success": False, "error": f"未找到回测记录: {record_id}"}

        result = doc.get("result") or {}
        model_id = doc.get("model_id", "")
        name_map = await self._model_name_map(model_service, {model_id})
        model_name = name_map.get(model_id, model_id)

        metrics = {
            "total_return_pct": pct(result.get("total_return")),
            "annual_return_pct": pct(result.get("annual_return")),
            "annual_vol_pct": pct(result.get("annual_volatility")),
            "sharpe": round_or_none(result.get("sharpe_ratio"), 3),
            "max_drawdown_pct": pct(result.get("max_drawdown")),
            "calmar": round_or_none(result.get("calmar_ratio"), 3),
            "latest_unit_value": round_or_none(result.get("latest_unit_value")),
        }

        # 权重轨迹摘要（首/末次调仓 + 次数，不返回全量明细）
        weight_changes = result.get("weight_changes") or []
        weight_summary = {
            "rebalance_count": len(weight_changes),
            "first_date": fmt_date(weight_changes[0].get("date")) if weight_changes else "",
            "last_date": fmt_date(weight_changes[-1].get("date")) if weight_changes else "",
            "latest_weights": weight_changes[-1].get("weights") if weight_changes else {},
        }

        detail = {
            "id": str(doc["_id"]),
            "model_name": model_name,
            "model_id": model_id,
            "start_date": fmt_date(doc.get("start_date")),
            "end_date": fmt_date(doc.get("end_date")),
            "initial_capital": doc.get("initial_capital"),
            "benchmark_code": doc.get("benchmark_code"),
            "created_at": fmt_datetime(doc.get("created_at")),
            "metrics": metrics,
            "weight_trajectory": weight_summary,
            "position_days": len(result.get("positions") or []),
        }

        charts = self._build_nav_charts(model_name, result)

        return {
            "success": True,
            "count": 1,
            "data": {"records": [detail]},
            "charts": charts,
            "metadata": {"record_count": 1},
            "summary": (
                f"回测记录详情：{model_name}（{detail['start_date']} ~ {detail['end_date']}），"
                f"年化收益 {metrics['annual_return_pct']}%，夏普 {metrics['sharpe']}，"
                f"最大回撤 {metrics['max_drawdown_pct']}%，共 {weight_summary['rebalance_count']} 次调仓。"
            ),
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _build_nav_charts(model_name: str, result: dict) -> list[dict]:
        """净值曲线 → 折线图（降采样至 120 点以内）"""
        equity_curve = result.get("equity_curve") or []
        if not equity_curve:
            return []
        points = sample_series(equity_curve, max_points=120)
        x_data = [fmt_date(p.get("date")) for p in points]
        nav = [round_or_none(p.get("unit_value") or (
            (p.get("value") or 0) / 1000000
        )) for p in points]
        return [line_chart(f"{model_name} 回测净值曲线", x_data, [{"name": "单位净值", "data": nav}])]

    @staticmethod
    async def _model_name_map(model_service, model_ids: set[str]) -> dict[str, str]:
        """批量查询策略模型名称 {model_id: name}"""
        object_ids = []
        for mid in model_ids:
            if not mid:
                continue
            try:
                object_ids.append(ObjectId(mid))
            except Exception:
                continue
        if not object_ids:
            return {}
        name_map: dict[str, str] = {}
        cursor = model_service.collection.find({"_id": {"$in": object_ids}}, {"name": 1})
        async for doc in cursor:
            name_map[str(doc["_id"])] = doc.get("name", "")
        return name_map


def _normalize_date(value: str) -> str:
    """日期归一化为 YYYYMMDD（兼容 YYYY-MM-DD 输入）"""
    return (value or "").strip().replace("-", "")


class RunBacktestTool(ConfirmableTool):
    """执行回测（两阶段确认：确认后按策略配置实例运行并自动保存回测记录）"""

    name = "run_backtest"
    description = (
        "对指定策略配置实例执行回测（写操作，需用户确认后执行）。"
        "回测参数（策略参数/资产池/调仓频率）取自该实例的当前配置，"
        "仅指定回测日期区间。执行成功后自动保存回测记录，"
        "可用 query_backtests 查看结果。组合类模型（is_portfolio）不支持，"
        "请到回测页面操作。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "model_id": {
                "type": "string",
                "description": "策略配置实例 ID（来自 query_strategies）",
            },
            "start_date": {
                "type": "string",
                "description": "回测开始日期（YYYYMMDD 或 YYYY-MM-DD）",
            },
            "end_date": {
                "type": "string",
                "description": "回测结束日期（YYYYMMDD 或 YYYY-MM-DD）",
            },
            "remark": {
                "type": "string",
                "description": "回测备注（可选，保存到回测记录）",
            },
        },
        "required": ["model_id", "start_date", "end_date"],
    }

    tool_timeout = 120.0

    async def execute(self, **kwargs) -> dict:
        # 预校验：模型存在且非组合类，避免生成无效确认卡片
        error = await self._precheck(kwargs)
        if error:
            return {"success": False, "error": error}
        kwargs["start_date"] = _normalize_date(kwargs.get("start_date", ""))
        kwargs["end_date"] = _normalize_date(kwargs.get("end_date", ""))
        return await super().execute(**kwargs)

    def build_preview(self, arguments: dict) -> dict:
        return {
            "tool": self.name,
            "operation": "执行回测",
            "target": arguments.get("model_id", ""),
            "arguments": arguments,
        }

    async def perform(self, **kwargs) -> dict:
        from app.schemas.backtests import BacktestByModelRequest
        from app.services.asset_service import AssetService
        from app.services.backtest_orchestration import run_backtest_by_model_core
        from app.services.market_service import MarketService

        model_id = kwargs.get("model_id", "")
        error = await self._precheck(kwargs)
        if error:
            return {"success": False, "error": error}

        request = BacktestByModelRequest(
            start_date=_normalize_date(kwargs.get("start_date", "")),
            end_date=_normalize_date(kwargs.get("end_date", "")),
            remark=(kwargs.get("remark") or None),
        )
        response = await run_backtest_by_model_core(
            model_id, request, MarketService(), AssetService(),
        )
        if response.code != 200 or not response.data:
            return {"success": False, "error": response.message or "回测执行失败"}

        data = response.data if isinstance(response.data, dict) else response.data.model_dump()
        metrics = {
            "total_return_pct": pct(data.get("total_return")),
            "annual_return_pct": pct(data.get("annual_return")),
            "annual_vol_pct": pct(data.get("volatility")),
            "sharpe": round_or_none(data.get("sharpe_ratio"), 3),
            "max_drawdown_pct": pct(data.get("max_drawdown")),
        }
        return {
            "success": True,
            "record_id": str(data.get("record_id", "")),
            "model_id": model_id,
            "metrics": metrics,
            "summary": (
                f"回测完成：年化收益 {metrics['annual_return_pct']}%，夏普 {metrics['sharpe']}，"
                f"最大回撤 {metrics['max_drawdown_pct']}%。"
                "可用 query_backtests(action=detail) 查看净值曲线与权重轨迹。"
            ),
        }

    @staticmethod
    async def _precheck(kwargs: dict) -> str:
        """返回错误文案（空串=通过）"""
        from app.services.strategy_model_service import StrategyModelService

        model_id = kwargs.get("model_id", "")
        if not model_id:
            return "缺少 model_id"
        for key in ("start_date", "end_date"):
            if len(_normalize_date(kwargs.get(key, ""))) != 8 or not _normalize_date(kwargs.get(key, "")).isdigit():
                return f"{key} 格式无效，应为 YYYYMMDD 或 YYYY-MM-DD"
        model = await StrategyModelService().get_model(model_id)
        if not model:
            return f"策略配置实例不存在: {model_id}，请先用 query_strategies 确认"
        if getattr(model, "is_portfolio", False):
            return "该实例为组合模型，暂不支持对话内回测，请到回测页面操作"
        return ""
