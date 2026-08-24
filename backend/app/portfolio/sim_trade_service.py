# -*- coding: utf-8 -*-
"""
模拟交易服务层

编排模拟交易的完整业务逻辑：
- 推进模拟组合
- 查询成交记录和快照
- 跟踪误差报告
- 绩效归因报告
- 批量推进
"""
from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any

from bson import ObjectId

from app.config.database import Database
from app.portfolio.models import Portfolio, PortfolioSource, SimTrade, SimDailySnapshot
from app.portfolio.sim_trade_engine import SimTradeEngine
from app.portfolio.portfolio_service import PortfolioService

logger = logging.getLogger("uvicorn.error")


class SimTradeService:
    """模拟交易服务"""

    def __init__(self):
        self._db = None
        self._engine = SimTradeEngine()
        self._portfolio_service = PortfolioService()

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def trades_collection(self):
        from app.config.collections import COL_SIM_TRADES
        return self.db[COL_SIM_TRADES]

    @property
    def snapshots_collection(self):
        from app.config.collections import COL_SIM_DAILY_SNAPSHOTS
        return self.db[COL_SIM_DAILY_SNAPSHOTS]

    # ────────────────────────────────────────────────
    #  推进
    # ────────────────────────────────────────────────

    async def advance_portfolio(
        self,
        portfolio_id: str,
        target_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """推进指定模拟组合到目标日期（默认到今天）"""
        if target_date is None:
            target_date = date.today()

        portfolio = await self._portfolio_service.get_portfolio(portfolio_id)
        if not portfolio:
            return {"message": f"组合不存在: {portfolio_id}", "days_advanced": 0, "trades_generated": 0}

        # 根据来源类型分路推进
        if portfolio.source == PortfolioSource.SINGLE_STRATEGY:
            # 单策略：使用现有引擎逻辑
            result = await self._engine.advance_to_date(portfolio, target_date)
        elif portfolio.source == PortfolioSource.PORTFOLIO_MODEL:
            # 多策略组合：NAV层复合推进
            result = await self._engine.advance_portfolio_model_to_date(portfolio, target_date)
        else:
            # 兼容旧数据：检查是否有 model_id（旧的模型驱动类型）
            if hasattr(portfolio, 'model_id') and portfolio.model_id:
                result = await self._engine.advance_to_date(portfolio, target_date)
            else:
                return {"message": "仅模型驱动组合支持模拟交易推进", "days_advanced": 0, "trades_generated": 0}

        result["portfolio_id"] = portfolio_id
        result["portfolio_name"] = portfolio.name
        result["target_date"] = target_date.strftime("%Y-%m-%d")
        return result

    async def batch_advance(
        self,
        target_date: Optional[date] = None,
        portfolio_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """批量推进所有模型驱动组合"""
        if target_date is None:
            target_date = date.today()

        results = []

        if portfolio_ids:
            # 推进指定组合
            for pid in portfolio_ids:
                try:
                    result = await self.advance_portfolio(pid, target_date)
                    results.append(result)
                except Exception as e:
                    logger.error(f"[SimTrade] 批量推进失败 {pid}: {e}")
                    results.append({
                        "portfolio_id": pid, "message": str(e),
                        "days_advanced": 0, "trades_generated": 0,
                        "target_date": target_date.strftime("%Y-%m-%d"),
                    })
        else:
            # 推进所有可模拟交易的组合（单策略+组合模型来源）
            from app.config.collections import COL_PORTFOLIOS
            cursor = self.db[COL_PORTFOLIOS].find({
                "source": {"$in": [
                    PortfolioSource.SINGLE_STRATEGY.value,
                    PortfolioSource.PORTFOLIO_MODEL.value,
                ]}
            })
            async for doc in cursor:
                pid = str(doc["_id"])
                try:
                    result = await self.advance_portfolio(pid, target_date)
                    results.append(result)
                except Exception as e:
                    logger.error(f"[SimTrade] 批量推进失败 {pid}: {e}")
                    results.append({
                        "portfolio_id": pid, "message": str(e),
                        "days_advanced": 0, "trades_generated": 0,
                        "target_date": target_date.strftime("%Y-%m-%d"),
                    })

        return results

    # ────────────────────────────────────────────────
    #  查询
    # ────────────────────────────────────────────────

    async def get_trades(
        self,
        portfolio_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """查询成交记录（分页 + 日期筛选）"""
        query: Dict[str, Any] = {"portfolio_id": portfolio_id}
        if start_date:
            query["trade_date"] = query.get("trade_date", {})
            query["trade_date"]["$gte"] = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            query["trade_date"] = query.get("trade_date", {})
            query["trade_date"]["$lte"] = datetime.strptime(end_date, "%Y-%m-%d")

        total = await self.trades_collection.count_documents(query)
        cursor = self.trades_collection.find(query).sort("trade_date", -1).skip(skip).limit(limit)
        items = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            items.append(self._format_trade(doc))

        return {"items": items, "total": total, "skip": skip, "limit": limit}

    async def get_snapshots(
        self,
        portfolio_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip: int = 0,
        limit: int = 500,
    ) -> Dict[str, Any]:
        """查询逐日快照"""
        query: Dict[str, Any] = {"portfolio_id": portfolio_id}
        if start_date:
            query["date"] = query.get("date", {})
            query["date"]["$gte"] = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            query["date"] = query.get("date", {})
            query["date"]["$lte"] = datetime.strptime(end_date, "%Y-%m-%d")

        total = await self.snapshots_collection.count_documents(query)
        cursor = self.snapshots_collection.find(query).sort("date", 1).skip(skip).limit(limit)
        items = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            items.append(self._format_snapshot(doc))

        return {"items": items, "total": total, "skip": skip, "limit": limit}

    # ────────────────────────────────────────────────
    #  报告
    # ────────────────────────────────────────────────

    async def get_tracking_report(self, portfolio_id: str) -> Dict[str, Any]:
        """获取跟踪误差报告"""
        portfolio = await self._portfolio_service.get_portfolio(portfolio_id)
        if not portfolio:
            raise ValueError(f"组合不存在: {portfolio_id}")

        result = await self._engine.compute_tracking_error(portfolio)
        result["portfolio_id"] = portfolio_id
        result["portfolio_name"] = portfolio.name
        return result

    async def get_attribution_report(self, portfolio_id: str) -> Dict[str, Any]:
        """获取绩效归因报告"""
        portfolio = await self._portfolio_service.get_portfolio(portfolio_id)
        if not portfolio:
            raise ValueError(f"组合不存在: {portfolio_id}")

        result = await self._engine.performance_attribution(portfolio)
        result["portfolio_id"] = portfolio_id
        result["portfolio_name"] = portfolio.name
        return result

    # ────────────────────────────────────────────────
    #  定时批量推进
    # ────────────────────────────────────────────────

    async def run_daily_batch(self):
        """定时批量推进所有活跃模拟组合（可接入 scheduler）"""
        results = await self.batch_advance(target_date=date.today())
        total_days = sum(r.get("days_advanced", 0) for r in results)
        total_trades = sum(r.get("trades_generated", 0) for r in results)
        logger.info(
            f"[SimTrade] 每日批量推进完成: "
            f"{len(results)} 个组合, {total_days} 天, {total_trades} 笔成交"
        )
        return results

    # ────────────────────────────────────────────────
    #  格式化辅助
    # ────────────────────────────────────────────────

    @staticmethod
    def _format_trade(doc: Dict) -> Dict:
        """格式化成交记录为前端友好的结构"""
        td = doc.get("trade_date")
        return {
            "id": str(doc.get("_id", "")),
            "portfolio_id": doc.get("portfolio_id", ""),
            "trade_date": td.strftime("%Y-%m-%d") if hasattr(td, "strftime") else str(td),
            "asset_code": doc.get("asset_code", ""),
            "asset_name": doc.get("asset_name", ""),
            "side": doc.get("side", ""),
            "quantity": doc.get("quantity", 0),
            "price": doc.get("price", 0),
            "commission": doc.get("commission", 0),
            "slippage_cost": doc.get("slippage_cost", 0),
            "gross_amount": doc.get("gross_amount", 0),
            "net_amount": doc.get("net_amount", 0),
            "signal_source": doc.get("signal_source", ""),
            "trigger_reason": doc.get("trigger_reason", ""),
            "created_at": doc.get("created_at", datetime.now()).isoformat()
            if hasattr(doc.get("created_at", datetime.now()), "isoformat") else str(doc.get("created_at", "")),
        }

    @staticmethod
    def _format_snapshot(doc: Dict) -> Dict:
        """格式化快照为前端友好的结构"""
        d = doc.get("date")
        positions = []
        for p in doc.get("positions", []):
            positions.append({
                "asset_code": p.get("asset_code", ""),
                "asset_name": p.get("asset_name", ""),
                "weight": p.get("weight", 0),
                "quantity": p.get("quantity", 0),
                "market_value": p.get("market_value", 0),
                "price": p.get("price", 0),
            })
        return {
            "id": str(doc.get("_id", "")),
            "portfolio_id": doc.get("portfolio_id", ""),
            "date": d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d),
            "nav": doc.get("nav", 1.0),
            "total_value": doc.get("total_value", 0),
            "cash": doc.get("cash", 0),
            "holdings_value": doc.get("holdings_value", 0),
            "daily_return": doc.get("daily_return", 0),
            "cumulative_return": doc.get("cumulative_return", 0),
            "positions": positions,
            "is_rebalance_day": doc.get("is_rebalance_day", False),
            "backtest_nav": doc.get("backtest_nav"),
            "tracking_error": doc.get("tracking_error"),
        }
