"""
组合域工具 — query_portfolios（读）+ create_portfolio / adjust_portfolio（写，需确认）

query_portfolios action:
- list：组合列表（名称/来源/资金/绩效摘要）
- detail：单个组合详情（完整配置 + 当前持仓 + 绩效 + 权重分布图）

写工具边界（M2）：create_portfolio 新建自动打标 created_by=agent；
adjust_portfolio 仅允许修改 agent 创建的组合，用户手动创建的拒绝并引导到页面。

复用链路：app/portfolio/portfolio_service.PortfolioService
"""
from datetime import datetime

from bson import ObjectId

from app.agent.core.write_guard import (
    AGENT_CREATED_BY, assert_agent_owned, stamp_agent_origin,
)
from app.agent.tools._helpers import fmt_datetime, pct, pie_chart
from app.agent.tools.base import BaseTool, ConfirmableTool


class QueryPortfoliosTool(BaseTool):
    """组合查询工具"""

    name = "query_portfolios"
    description = (
        "查询投资组合。两种模式：\n"
        "1) action=list：列出所有组合（名称/来源/资金/绩效摘要）\n"
        "2) action=detail：查单个组合详情（传 portfolio_id），含子策略配置、"
        "当前持仓、绩效指标与权重分布图"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "detail"],
                "description": "查询模式",
            },
            "portfolio_id": {
                "type": "string",
                "description": "detail 模式的组合 ID（必填）",
            },
            "status": {
                "type": "string",
                "description": "list 模式按状态过滤（可选）",
            },
        },
        "required": ["action"],
    }

    max_result_chars = 10000

    async def execute(
        self,
        action: str = "list",
        portfolio_id: str = "",
        status: str = "",
        **kwargs,
    ) -> dict:
        from app.portfolio.portfolio_service import PortfolioService

        service = PortfolioService()
        if action == "list":
            return await self._list(service, status)
        if action == "detail":
            if not portfolio_id:
                return {"success": False, "error": "detail 模式需要 portfolio_id"}
            return await self._detail(service, portfolio_id)
        return {"success": False, "error": f"未知 action: {action}（可选 list/detail）"}

    # ------------------------------------------------------------------

    async def _list(self, service, status: str) -> dict:
        portfolios = await service.list_portfolios(status=status or None)

        records = []
        for p in portfolios:
            summary = p.latest_backtest_summary or {}
            records.append({
                "id": p.id,
                "name": p.name,
                "source": getattr(p.source, "value", str(p.source)),
                "status": getattr(p, "status", "") or "",
                "initial_capital": p.initial_capital,
                "current_capital": p.current_capital,
                "sub_strategy_count": len(p.sub_strategies or []),
                "position_count": len(p.positions or []),
                "annual_return_pct": pct(summary.get("annual_return")),
                "sharpe": summary.get("sharpe"),
                "max_drawdown_pct": pct(summary.get("max_drawdown")),
                "created_by": getattr(p, "created_by", None) or "user",
                "updated_at": fmt_datetime(getattr(p, "updated_at", None)),
            })

        return {
            "success": True,
            "count": len(records),
            "data": {"records": records},
            "metadata": {"record_count": len(records)},
            "summary": f"共 {len(records)} 个组合。" if records else "暂无组合。",
            "hint": "使用 action=detail 并传 portfolio_id 可查看持仓与权重分布",
        }

    async def _detail(self, service, portfolio_id: str) -> dict:
        try:
            portfolio = await service.get_portfolio(portfolio_id)
        except Exception:
            return {"success": False, "error": f"无效的 portfolio_id: {portfolio_id}"}
        if not portfolio:
            return {"success": False, "error": f"未找到组合: {portfolio_id}"}

        data = portfolio.dict(by_alias=True, exclude_none=True)
        data.pop("_id", None)
        summary = portfolio.latest_backtest_summary or {}
        metrics = {
            "annual_return_pct": pct(summary.get("annual_return")),
            "annual_vol_pct": pct(summary.get("annual_vol")),
            "sharpe": summary.get("sharpe"),
            "max_drawdown_pct": pct(summary.get("max_drawdown")),
        }

        # 权重分布图：按当前持仓市值占比
        charts = []
        pie_items = []
        positions = portfolio.positions or []
        total_value = sum(float(getattr(pos, "market_value", 0) or 0) for pos in positions)
        if total_value > 0:
            for pos in positions:
                code = getattr(pos, "asset_code", "") or getattr(pos, "code", "")
                name = getattr(pos, "asset_name", "") or code
                value = float(getattr(pos, "market_value", 0) or 0)
                if value > 0:
                    pie_items.append({"name": name or code, "value": round(value / total_value * 100, 2)})
            if pie_items:
                charts.append(pie_chart(f"{portfolio.name} 持仓权重分布", pie_items))

        detail_record = {
            "id": portfolio.id,
            "name": portfolio.name,
            "source": getattr(portfolio.source, "value", str(portfolio.source)),
            "sub_strategies": [
                {"model_id": s.get("model_id", ""), "weight": s.get("weight")}
                for s in (portfolio.sub_strategies or [])
                if isinstance(s, dict)
            ],
            "position_count": len(positions),
            "metrics": metrics,
        }

        return {
            "success": True,
            "count": 1,
            "data": {"records": [detail_record]},
            "charts": charts,
            "metadata": {"record_count": 1},
            "summary": (
                f"组合「{portfolio.name}」：{len(positions)} 项持仓，"
                f"年化收益 {metrics['annual_return_pct']}%，夏普 {metrics['sharpe']}，"
                f"最大回撤 {metrics['max_drawdown_pct']}%。"
            ),
            "portfolio_full": data,
        }


class CreatePortfolioTool(ConfirmableTool):
    """创建模拟组合（两阶段确认，新建实体自动打 agent 标记）"""

    name = "create_portfolio"
    description = (
        "按权重创建模拟组合（写操作，需用户确认后执行）。"
        "按各资产最新价格计算份额与市值；权重总和必须为 1。"
        "创建的组合标记为 agent 创建，后续可由 adjust_portfolio 调整。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "组合名称",
            },
            "positions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "asset_code": {"type": "string", "description": "资产代码"},
                        "weight": {"type": "number", "description": "权重（0~1，总和为 1）"},
                    },
                    "required": ["asset_code", "weight"],
                },
                "description": "持仓列表（按权重配置）",
            },
            "initial_capital": {
                "type": "number",
                "description": "初始资金（默认 1000 万）",
            },
            "description": {
                "type": "string",
                "description": "组合描述（可选）",
            },
            "inception_date": {
                "type": "string",
                "description": "建仓日期 YYYY-MM-DD（可选，默认今天）",
            },
        },
        "required": ["name", "positions"],
    }

    tool_timeout = 90.0

    async def execute(self, **kwargs) -> dict:
        error = self._validate(kwargs)
        if error:
            return {"success": False, "error": error}
        return await super().execute(**kwargs)

    def build_preview(self, arguments: dict) -> dict:
        return {
            "tool": self.name,
            "operation": "创建模拟组合",
            "target": arguments.get("name", ""),
            "arguments": arguments,
        }

    async def perform(self, **kwargs) -> dict:
        from app.portfolio.models import Portfolio, PortfolioSource, Position
        from app.portfolio.portfolio_service import PortfolioService
        from app.services.asset_service import AssetService

        error = self._validate(kwargs)
        if error:
            return {"success": False, "error": error}

        conversation_id = kwargs.get("conversation_id", "")
        name = kwargs["name"].strip()
        initial_capital = float(kwargs.get("initial_capital") or 10_000_000)
        inception = (
            datetime.strptime(kwargs["inception_date"], "%Y-%m-%d")
            if kwargs.get("inception_date") else datetime.now()
        )

        asset_codes = [p["asset_code"] for p in kwargs["positions"]]
        asset_service = AssetService()

        # 校验资产代码并取名称（Position.asset_name 必填）
        name_map: dict[str, str] = {}
        cursor = asset_service.collection.find({"code": {"$in": asset_codes}}, {"code": 1, "name": 1})
        async for asset_doc in cursor:
            name_map[asset_doc.get("code", "")] = asset_doc.get("name", "")
        unknown = [c for c in asset_codes if c not in name_map]
        if unknown:
            return {"success": False, "error": f"以下资产代码不存在: {', '.join(unknown)}"}

        import pandas as pd
        price_df = await asset_service.get_price_dataframe(
            asset_codes, inception - pd.Timedelta(days=30), datetime.now()
        )
        if price_df.empty:
            return {"success": False, "error": f"无法获取资产价格数据，请确认行情已导入: {', '.join(asset_codes)}"}

        latest_prices = price_df.iloc[-1].to_dict()
        positions = []
        for p in kwargs["positions"]:
            price = latest_prices.get(p["asset_code"])
            if price is None or price <= 0:
                return {"success": False, "error": f"资产 {p['asset_code']} 的价格数据不可用"}
            market_value = initial_capital * float(p["weight"])
            positions.append(Position(
                asset_code=p["asset_code"],
                asset_name=name_map[p["asset_code"]] or p["asset_code"],
                weight=float(p["weight"]),
                price=float(price),
                shares=market_value / float(price),
                market_value=market_value,
            ))

        portfolio = Portfolio(
            name=name,
            source=PortfolioSource.MANUAL,
            description=kwargs.get("description") or None,
            initial_capital=initial_capital,
            current_capital=initial_capital,
            inception_date=inception,
            positions=positions,
            created_by=AGENT_CREATED_BY,
        )
        service = PortfolioService()
        portfolio_id = await service.create_portfolio(portfolio)

        # 补打 agent_meta（Portfolio 模型不承载该字段，直接写文档）
        meta_doc = stamp_agent_origin({}, conversation_id=conversation_id, tool_name=self.name)
        await service.collection.update_one(
            {"_id": ObjectId(portfolio_id)}, {"$set": {"agent_meta": meta_doc["agent_meta"]}},
        )
        await service.ensure_portfolio_model(portfolio_id)

        return {
            "success": True,
            "portfolio_id": portfolio_id,
            "name": name,
            "summary": f"组合「{name}」创建成功，共 {len(positions)} 项持仓，初始资金 {initial_capital:,.0f}。",
        }

    @staticmethod
    def _validate(kwargs: dict) -> str:
        positions = kwargs.get("positions") or []
        if not kwargs.get("name", "").strip():
            return "缺少组合名称"
        if not positions:
            return "positions 不能为空"
        for p in positions:
            if not isinstance(p, dict) or not p.get("asset_code") or p.get("weight") is None:
                return "positions 每项需包含 asset_code 与 weight"
        total = sum(float(p["weight"]) for p in positions)
        if abs(total - 1.0) > 0.01:
            return f"权重总和必须为 1，当前: {total:.4f}"
        if kwargs.get("inception_date"):
            try:
                datetime.strptime(kwargs["inception_date"], "%Y-%m-%d")
            except ValueError:
                return "inception_date 格式无效，应为 YYYY-MM-DD"
        return ""


class AdjustPortfolioTool(ConfirmableTool):
    """调整组合子策略权重（两阶段确认 + M2 护栏：仅限 agent 创建的组合）"""

    name = "adjust_portfolio"
    description = (
        "调整组合内子策略权重（写操作，需用户确认后执行）。"
        "仅允许调整 agent 创建的组合；用户手动创建的组合会被拒绝，"
        "请到组合管理页面操作。新权重总和必须为 1，"
        "只调整组合内已有子策略的权重。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "portfolio_id": {
                "type": "string",
                "description": "组合 ID（来自 query_portfolios）",
            },
            "weights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "model_id": {"type": "string", "description": "子策略模型 ID"},
                        "weight": {"type": "number", "description": "新权重（0~1）"},
                    },
                    "required": ["model_id", "weight"],
                },
                "description": "新权重列表 [{model_id, weight}]，总和为 1",
            },
            "reason": {
                "type": "string",
                "description": "调整原因（记录到调仓历史）",
            },
        },
        "required": ["portfolio_id", "weights"],
    }

    tool_timeout = 90.0

    def build_preview(self, arguments: dict) -> dict:
        return {
            "tool": self.name,
            "operation": "调整组合子策略权重",
            "target": arguments.get("portfolio_id", ""),
            "arguments": arguments,
        }

    async def perform(self, **kwargs) -> dict:
        from app.portfolio.portfolio_service import PortfolioService

        portfolio_id = kwargs.get("portfolio_id", "")
        weights = kwargs.get("weights") or []
        if not portfolio_id or not weights:
            return {"success": False, "error": "缺少 portfolio_id 或 weights"}

        service = PortfolioService()
        try:
            doc = await service.collection.find_one({"_id": ObjectId(portfolio_id)})
        except Exception:
            return {"success": False, "error": f"无效的 portfolio_id: {portfolio_id}"}

        # M2 护栏：非 agent 创建的组合拒绝修改（抛 WriteGuardError 由确认框架转 rejected）
        assert_agent_owned(doc, "组合", page_hint="组合管理页面")

        try:
            await service.update_sub_strategy_weights(
                portfolio_id,
                [{"model_id": w.get("model_id", ""), "weight": float(w.get("weight", 0))} for w in weights],
                reason=kwargs.get("reason") or "Agent 调整子策略权重",
            )
        except ValueError as e:
            return {"success": False, "error": str(e)}

        return {
            "success": True,
            "portfolio_id": portfolio_id,
            "summary": f"组合权重调整完成，共调整 {len(weights)} 个子策略。",
        }
