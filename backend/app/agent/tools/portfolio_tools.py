"""
组合（Portfolio）类工具 — 原子能力层

提供 4 个组合相关 BaseTool：
- create_portfolio         创建模拟组合（可从策略模型驱动或手工输入权重）
- get_portfolio            查询组合持仓详情
- get_rebalance_history    查询组合调仓历史
- execute_rebalance        手工执行一次调仓（记录调仓前后权重）

设计规范：
- 仅调用 PortfolioService，不做业务编排
- 不自动触发监控/波动率监测，除非用户显式请求
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.chart_builder import ChartBuilder
from app.models.portfolio import (
    Portfolio,
    PortfolioType,
    Position,
    RebalanceAction,
    RebalanceRecord,
)
from app.services.asset_service import AssetService
from app.services.portfolio_service import PortfolioService

_portfolio_service = PortfolioService()
_asset_service = AssetService()


def _parse_datetime(date_str: Optional[str]) -> Optional[datetime]:
    """将 YYYY-MM-DD 字符串转为 datetime；失败返回 None。"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def _serialize_position(pos: Position) -> Dict[str, Any]:
    return {
        "asset_code": pos.asset_code,
        "asset_name": pos.asset_name,
        "weight": pos.weight,
        "shares": pos.shares,
        "market_value": pos.market_value,
        "price": pos.price,
    }


# ═══════════════════════════════════════════════════════════════
#  Tool 1: create_portfolio
# ═══════════════════════════════════════════════════════════════

class CreatePortfolioTool(BaseTool):
    """创建模拟组合。支持两种方式：
    1) 模型驱动：传入 model_id，从策略模型追溯生成历史持仓和业绩。
    2) 手工输入：传入 positions（含资产代码+权重）创建初始持仓。
    """

    name = "create_portfolio"
    description = (
        "创建一个模拟组合。优先使用 model_id（从已有策略模型构建，自动回溯历史业绩）；"
        "若无 model_id 则使用 positions 手工指定初始权重。返回 portfolio_id。"
    )
    category = "portfolio"
    tags = ["组合", "创建"]
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "组合名称"},
            "model_id": {"type": "string", "description": "策略模型 ID（模型驱动模式）"},
            "positions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "asset_code": {"type": "string"},
                        "weight": {"type": "number"},
                    },
                    "required": ["asset_code", "weight"],
                },
                "description": "手工持仓列表 [{asset_code, weight}]（手工模式）",
            },
            "inception_date": {
                "type": "string",
                "description": "建仓日期 YYYY-MM-DD，默认今天",
            },
            "initial_capital": {
                "type": "number",
                "description": "初始资金，默认 1000 万",
            },
            "description": {"type": "string", "description": "组合描述"},
        },
        "required": ["name"],
    }

    async def execute(self, **kwargs) -> dict:
        name = (kwargs.get("name") or "").strip()
        if not name:
            return ToolResult.error("必须提供 name")

        initial_capital = float(kwargs.get("initial_capital") or 10_000_000.0)
        inception_dt = _parse_datetime(kwargs.get("inception_date")) or datetime.now()
        model_id = kwargs.get("model_id")
        positions_in = kwargs.get("positions") or []

        try:
            if model_id:
                portfolio_id = await _portfolio_service.create_from_model(
                    model_id=model_id,
                    inception_date=inception_dt,
                    name=name,
                    initial_capital=initial_capital,
                )
                portfolio = await _portfolio_service.get_portfolio(portfolio_id)
                return ToolResult.success(
                    data={
                        "portfolio_id": portfolio_id,
                        "name": name,
                        "model_id": model_id,
                        "inception_date": inception_dt.strftime("%Y-%m-%d"),
                        "initial_capital": initial_capital,
                        "current_capital": portfolio.current_capital if portfolio else initial_capital,
                        "position_count": len(portfolio.positions) if portfolio else 0,
                    },
                    summary=f"模型驱动组合 '{name}' 创建成功，portfolio_id={portfolio_id}",
                    record_count=1,
                )

            if not positions_in:
                return ToolResult.error(
                    "手工模式必须提供 positions（资产代码+权重），"
                    "或使用 model_id 从策略模型创建"
                )

            # 手工模式：解析持仓并补齐资产名称
            positions: List[Position] = []
            weight_sum = 0.0
            for p in positions_in:
                code = p.get("asset_code")
                weight = float(p.get("weight") or 0.0)
                if not code:
                    continue
                asset = await _asset_service.get_asset_by_code(code)
                asset_name = asset.name if asset else code
                positions.append(Position(
                    asset_code=code,
                    asset_name=asset_name,
                    weight=weight,
                    market_value=initial_capital * weight,
                ))
                weight_sum += weight
            if not positions:
                return ToolResult.error("positions 无有效资产")
            if abs(weight_sum - 1.0) > 0.01:
                logger.warning(
                    "[CreatePortfolioTool] 权重之和 {:.4f} 不等于 1.0，仍按输入创建",
                    weight_sum,
                )

            portfolio = Portfolio(
                name=name,
                portfolio_type=PortfolioType.MANUAL,
                description=kwargs.get("description"),
                initial_capital=initial_capital,
                current_capital=initial_capital,
                positions=positions,
                inception_date=inception_dt,
            )
            portfolio_id = await _portfolio_service.create_portfolio(portfolio)
            return ToolResult.success(
                data={
                    "portfolio_id": portfolio_id,
                    "name": name,
                    "inception_date": inception_dt.strftime("%Y-%m-%d"),
                    "initial_capital": initial_capital,
                    "position_count": len(positions),
                    "weight_sum": round(weight_sum, 4),
                },
                summary=f"手工组合 '{name}' 创建成功，portfolio_id={portfolio_id}",
                record_count=1,
            )
        except Exception as e:
            logger.error("[CreatePortfolioTool] 创建失败: {}", e)
            return ToolResult.error(f"创建组合失败: {e}")


# ═══════════════════════════════════════════════════════════════
#  Tool 2: get_portfolio
# ═══════════════════════════════════════════════════════════════

class GetPortfolioTool(BaseTool):
    """查询模拟组合详情（含持仓、业绩、权重饼图）。"""

    name = "get_portfolio"
    description = (
        "查询指定组合的当前持仓、资金、业绩指标。"
        "返回持仓表格与权重饼图。如未指定 portfolio_id 则返回组合列表。"
    )
    category = "portfolio"
    tags = ["组合", "持仓", "查询"]
    parameters = {
        "type": "object",
        "properties": {
            "portfolio_id": {"type": "string", "description": "组合 ID；不传则返回组合列表"},
            "limit": {"type": "integer", "description": "列表模式下的返回数量上限，默认 50"},
        },
        "required": [],
    }

    async def execute(self, **kwargs) -> dict:
        portfolio_id = kwargs.get("portfolio_id")
        try:
            if not portfolio_id:
                limit = min(int(kwargs.get("limit") or 50), 200)
                portfolios = await _portfolio_service.list_portfolios(skip=0, limit=limit)
                items = [
                    {
                        "portfolio_id": p.id,
                        "name": p.name,
                        "portfolio_type": str(p.portfolio_type),
                        "model_id": p.model_id,
                        "current_capital": p.current_capital,
                        "position_count": len(p.positions),
                        "inception_date": p.inception_date.strftime("%Y-%m-%d"),
                    }
                    for p in portfolios
                ]
                _r = ToolResult.success(
                    data={"portfolios": items},
                    summary=f"共 {len(items)} 个组合。",
                    record_count=len(items),
                )
                return self.attach_lineage(
                    _r,
                    tables=["portfolios"],
                    domains=["portfolio"],
                    fields={"portfolios": ["id", "name", "portfolio_type", "current_capital", "positions"]},
                    records_returned=len(items),
                    query_operation="get_portfolio:list",
                )

            portfolio = await _portfolio_service.get_portfolio(portfolio_id)
            if not portfolio:
                return ToolResult.error(f"未找到组合: {portfolio_id}")

            positions = [_serialize_position(p) for p in portfolio.positions]
            perf = portfolio.performance.dict() if portfolio.performance else None

            charts: List[Dict[str, Any]] = []
            pie_items = [
                {"name": p.asset_name or p.asset_code, "value": round(float(p.weight or 0.0) * 100, 4)}
                for p in portfolio.positions if p.weight
            ]
            if pie_items:
                charts.append(ChartBuilder.build_pie(
                    title=f"{portfolio.name} - 当前权重分配",
                    data_items=pie_items,
                ))

            summary = (
                f"组合 '{portfolio.name}' 共 {len(positions)} 项持仓，"
                f"当前资金 {portfolio.current_capital:,.2f}"
            )
            if perf and perf.get("total_return") is not None:
                summary += f"，累计收益 {perf['total_return']*100:.2f}%"

            _r = ToolResult.success(
                data={
                    "portfolio_id": portfolio.id,
                    "name": portfolio.name,
                    "portfolio_type": str(portfolio.portfolio_type),
                    "model_id": portfolio.model_id,
                    "rebalance_frequency": portfolio.rebalance_frequency,
                    "initial_capital": portfolio.initial_capital,
                    "current_capital": portfolio.current_capital,
                    "inception_date": portfolio.inception_date.strftime("%Y-%m-%d"),
                    "positions": positions,
                    "performance": perf,
                },
                charts=charts,
                summary=summary,
                record_count=len(positions),
            )
            return self.attach_lineage(
                _r,
                tables=["portfolios"],
                domains=["portfolio"],
                fields={"portfolios": ["id", "name", "positions", "performance", "current_capital"]},
                records_returned=len(positions),
                query_operation="get_portfolio:detail",
                portfolio_id=portfolio.id,
            )
        except Exception as e:
            logger.error("[GetPortfolioTool] 查询失败: {}", e)
            return ToolResult.error(f"查询组合失败: {e}")


# ═══════════════════════════════════════════════════════════════
#  Tool 3: get_rebalance_history
# ═══════════════════════════════════════════════════════════════

class GetRebalanceHistoryTool(BaseTool):
    """查询组合历次调仓记录。"""

    name = "get_rebalance_history"
    description = (
        "查询指定组合的调仓历史记录，按时间升序排列。"
        "每条记录包含调仓日期、动作、前后权重差异和调仓原因。"
    )
    category = "portfolio"
    tags = ["组合", "调仓", "历史"]
    parameters = {
        "type": "object",
        "properties": {
            "portfolio_id": {"type": "string", "description": "组合 ID"},
        },
        "required": ["portfolio_id"],
    }

    async def execute(self, **kwargs) -> dict:
        portfolio_id = (kwargs.get("portfolio_id") or "").strip()
        if not portfolio_id:
            return ToolResult.error("必须提供 portfolio_id")

        try:
            records = await _portfolio_service.list_rebalance_records(portfolio_id)
            items: List[Dict[str, Any]] = []
            for r in records:
                before_weights = {p.asset_code: p.weight for p in r.positions_before if p.weight is not None}
                after_weights = {p.asset_code: p.weight for p in r.positions_after if p.weight is not None}
                all_codes = set(before_weights.keys()) | set(after_weights.keys())
                weight_diff = {
                    code: round(
                        float(after_weights.get(code, 0.0) or 0.0)
                        - float(before_weights.get(code, 0.0) or 0.0),
                        6,
                    )
                    for code in all_codes
                }
                items.append({
                    "rebalance_date": r.rebalance_date.strftime("%Y-%m-%d"),
                    "action": str(r.action),
                    "reason": r.reason,
                    "weights_before": before_weights,
                    "weights_after": after_weights,
                    "weight_diff": weight_diff,
                })

            return ToolResult.success(
                data={
                    "portfolio_id": portfolio_id,
                    "rebalance_records": items,
                },
                summary=f"组合 {portfolio_id} 共 {len(items)} 条调仓记录。",
                record_count=len(items),
            )
        except Exception as e:
            logger.error("[GetRebalanceHistoryTool] 查询失败: {}", e)
            return ToolResult.error(f"查询调仓历史失败: {e}")


# ═══════════════════════════════════════════════════════════════
#  Tool 4: execute_rebalance
# ═══════════════════════════════════════════════════════════════

class ExecuteRebalanceTool(BaseTool):
    """手工执行一次调仓：将组合权重调整到目标权重并记录。"""

    name = "execute_rebalance"
    description = (
        "对指定组合手工执行一次调仓，写入调仓记录并更新组合当前持仓。"
        "需要提供目标权重字典 target_weights。"
    )
    category = "portfolio"
    tags = ["组合", "调仓", "执行"]
    parameters = {
        "type": "object",
        "properties": {
            "portfolio_id": {"type": "string", "description": "组合 ID"},
            "target_weights": {
                "type": "object",
                "description": "目标权重字典 {asset_code: weight}，权重和应约等于 1",
            },
            "reason": {"type": "string", "description": "调仓原因"},
            "rebalance_date": {
                "type": "string",
                "description": "调仓日期 YYYY-MM-DD，默认今天",
            },
        },
        "required": ["portfolio_id", "target_weights"],
    }

    async def execute(self, **kwargs) -> dict:
        portfolio_id = (kwargs.get("portfolio_id") or "").strip()
        target_weights = kwargs.get("target_weights") or {}
        if not portfolio_id or not target_weights:
            return ToolResult.error("必须提供 portfolio_id 和 target_weights")

        reason = kwargs.get("reason") or "手工调仓"
        rebal_dt = _parse_datetime(kwargs.get("rebalance_date")) or datetime.now()

        try:
            portfolio = await _portfolio_service.get_portfolio(portfolio_id)
            if not portfolio:
                return ToolResult.error(f"未找到组合: {portfolio_id}")

            # 构造调仓前/后持仓
            positions_before = list(portfolio.positions)
            asset_name_map: Dict[str, str] = {p.asset_code: p.asset_name for p in positions_before}

            positions_after: List[Position] = []
            for code, weight in target_weights.items():
                w = float(weight or 0.0)
                if w <= 0:
                    continue
                if code not in asset_name_map:
                    asset = await _asset_service.get_asset_by_code(code)
                    asset_name_map[code] = asset.name if asset else code
                positions_after.append(Position(
                    asset_code=code,
                    asset_name=asset_name_map[code],
                    weight=w,
                    market_value=portfolio.current_capital * w,
                ))
            if not positions_after:
                return ToolResult.error("target_weights 无有效权重")

            record = RebalanceRecord(
                portfolio_id=portfolio_id,
                rebalance_date=rebal_dt,
                action=RebalanceAction.ADJUST,
                positions_before=positions_before,
                positions_after=positions_after,
                reason=reason,
            )
            record_id = await _portfolio_service.add_rebalance_record(record)

            # 更新组合当前持仓
            from bson import ObjectId
            await _portfolio_service.collection.update_one(
                {"_id": ObjectId(portfolio_id)},
                {"$set": {
                    "positions": [p.dict() for p in positions_after],
                    "updated_at": datetime.now(),
                }},
            )

            return ToolResult.success(
                data={
                    "portfolio_id": portfolio_id,
                    "record_id": record_id,
                    "rebalance_date": rebal_dt.strftime("%Y-%m-%d"),
                    "reason": reason,
                    "weights_after": {p.asset_code: p.weight for p in positions_after},
                },
                summary=(
                    f"组合 {portfolio_id} 已调仓，"
                    f"共 {len(positions_after)} 项目标持仓，原因：{reason}"
                ),
                record_count=1,
            )
        except Exception as e:
            logger.error("[ExecuteRebalanceTool] 调仓失败: {}", e)
            return ToolResult.error(f"执行调仓失败: {e}")
