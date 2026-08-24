# -*- coding: utf-8 -*-
"""
投资组合服务

支持三种组合来源的创建、查询和绩效计算：
- MANUAL: 手工创建（按持仓配置）
- SINGLE_STRATEGY: 从单策略模型创建（复用回测引擎追溯）
- PORTFOLIO_MODEL: 从组合模型创建（多策略NAV层复合）

⚠️ 本文件已超 1000 行，职责过重（组合CRUD/绩效计算/调仓记录/净值回溯）。
   后续新增功能请勿继续往本文件添加，应按职责拆分到独立服务。
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import pandas as pd
from bson import ObjectId
from loguru import logger

from app.config.database import Database
from app.portfolio.models import (
    Portfolio,
    PortfolioSource,
    PortfolioStatus,
    Position,
    SubStrategyAllocation,
    RebalanceRecord,
    RebalanceAction,
)
from app.models.strategy_model import BacktestResult as ModelBacktestResult, StrategyModel, ModelStatus
from app.services.strategy_model_service import StrategyModelService
from app.services.asset_service import AssetService


def _build_risk_config_from_params(strategy_params: Dict[str, Any] | None):
    """根据策略参数构造 RiskConfig，与 API 层回测口径一致。

    关键点：策略声明 allow_short=True 时（如趋势-截面复合 GCMI 的多空权重），
    风控层不得将负权重截断为 0，否则空头敞口被抹掉、回测与原型严重偏离。
    """
    from app.backtesting.risk import RiskConfig

    params = strategy_params or {}
    allow_negative = bool(params.get("allow_short", False))
    max_weight_dict = params.get("weight_caps", params.get("max_weight_dict"))
    if not isinstance(max_weight_dict, dict) or not max_weight_dict:
        max_weight_dict = None
    max_total_leverage = params.get("max_total_leverage", params.get("max_leverage"))
    try:
        max_total_leverage = float(max_total_leverage) if max_total_leverage is not None else None
    except (TypeError, ValueError):
        max_total_leverage = None
    return RiskConfig(
        max_total_leverage=max_total_leverage,
        max_weight_dict=max_weight_dict,
        allow_negative_weights=allow_negative,
    )


class PortfolioService:
    """投资组合服务"""

    def __init__(self):
        self._db = None
        self._collection = None
        self._rebalance_collection = None
        self.asset_service = AssetService()
        self.strategy_model_service = StrategyModelService()

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            from app.config.collections import COL_PORTFOLIOS
            self._collection = self.db[COL_PORTFOLIOS]
        return self._collection

    @property
    def rebalance_collection(self):
        if self._rebalance_collection is None:
            from app.config.collections import COL_REBALANCE_RECORDS
            self._rebalance_collection = self.db[COL_REBALANCE_RECORDS]
        return self._rebalance_collection

    # ============================================================
    # CRUD
    # ============================================================

    async def create_portfolio(self, portfolio: Portfolio) -> str:
        """创建组合文档"""
        # 自动提取预期绩效
        model_id = portfolio.model_id or portfolio.portfolio_model_id
        if model_id and not portfolio.expected_metrics:
            try:
                model = await self.strategy_model_service.get_model(model_id)
                if model and getattr(model, "latest_backtest_summary", None):
                    portfolio.expected_metrics = model.latest_backtest_summary
                    logger.info(
                        "[组合创建] 自动提取预期绩效 model_id=%s sharpe=%s",
                        model_id, model.latest_backtest_summary.get("sharpe"),
                    )
            except Exception as e:
                logger.warning("[组合创建] 提取预期绩效失败: %s", e)

        data = portfolio.dict(by_alias=True, exclude={"id"})
        result = await self.collection.insert_one(data)
        return str(result.inserted_id)

    async def ensure_portfolio_model(self, portfolio_id: str) -> Optional[str]:
        """确保组合拥有对应的组合模型（is_portfolio=True 的 StrategyModel）。

        组合与策略统一管理：每个组合自动注册一个组合模型文档，
        用于实盘发布、日常监控、参数版本等能力。

        Returns:
            portfolio_model_id，失败时返回 None
        """
        portfolio = await self.get_portfolio(portfolio_id)
        if not portfolio:
            return None

        # 已有关联模型：同步产品层配置（监控从 strategy_models 读取，
        # 保证组合文档与组合模型的产品层口径一致），然后直接返回
        if portfolio.portfolio_model_id:
            pl = (portfolio.weight_model_params or {}).get("product_layer")
            if pl is not None:
                try:
                    await self.strategy_model_service.collection.update_one(
                        {"_id": ObjectId(portfolio.portfolio_model_id)},
                        {"$set": {"weight_model_params.product_layer": pl}},
                    )
                except Exception as sync_err:
                    logger.warning("[组合模型] 同步产品层配置失败 portfolio=%s: %s", portfolio_id, sync_err)
            return portfolio.portfolio_model_id

        # 构建子策略配置
        sub_strategies = [
            {
                "model_id": s.model_id or "",
                "name": s.name or "",
                "weight": s.weight or 0,
                "template_code": s.template_code or "",
            }
            for s in (portfolio.sub_strategies or [])
        ]

        # 单策略组合：将关联策略作为子策略
        if not sub_strategies and portfolio.model_id:
            try:
                linked = await self.strategy_model_service.get_model(portfolio.model_id)
                if linked:
                    sub_strategies = [{
                        "model_id": portfolio.model_id,
                        "name": linked.name,
                        "weight": 1.0,
                        "template_code": linked.template_code or "",
                    }]
            except Exception:
                pass

        try:
            model = StrategyModel(
                name=portfolio.name,
                template_code="portfolio_composite",
                description=f"组合模型（自动创建于组合管理）",
                asset_codes=[],  # create_model 会自动计算子策略资产并集
                parameters={},
                rebalance_frequency=portfolio.rebalance_frequency or "monthly",
                is_portfolio=True,
                sub_strategies=sub_strategies,
                status=ModelStatus.PUBLISHED,
                initial_nav=1000.0,
                inception_date=portfolio.inception_date,
                weight_model_type=portfolio.weight_method if portfolio.weight_method == "quadrant" else None,
                weight_model_params=portfolio.weight_model_params or {},
            )
            model_id = await self.strategy_model_service.create_model(model)
            # 回写组合文档
            await self.collection.update_one(
                {"_id": ObjectId(portfolio_id)},
                {"$set": {"portfolio_model_id": model_id, "updated_at": datetime.now()}},
            )
            logger.info(
                "[组合模型] 自动创建组合模型: portfolio=%s model=%s 子策略数=%d",
                portfolio.name, model_id, len(sub_strategies),
            )
            return model_id
        except Exception as e:
            logger.warning("[组合模型] 自动创建组合模型失败 portfolio=%s: %s", portfolio_id, e)
            return None

    async def get_portfolio(self, portfolio_id: str) -> Optional[Portfolio]:
        """获取单个组合"""
        data = await self.collection.find_one({"_id": ObjectId(portfolio_id)})
        if data:
            data["_id"] = str(data["_id"])
            return Portfolio(**data)
        return None

    async def list_portfolios(self, status: Optional[str] = None) -> List[Portfolio]:
        """组合列表"""
        query = {}
        if status:
            query["status"] = status
        cursor = self.collection.find(query).sort("updated_at", -1)
        portfolios = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            try:
                portfolios.append(Portfolio(**doc))
            except Exception:
                continue
        return portfolios

    async def delete_portfolio(self, portfolio_id: str) -> bool:
        """删除组合及关联数据.

        除组合文档与调仓记录外，同步处理关联的组合模型与监控条目，
        否则组合模型仍带 live_publish_enabled=True，监控列表加载时
        sync_live_published 会将已归档的监控条目重新激活（幽灵监控）。
        """
        # 先读取组合文档，获取关联的组合模型 ID
        doc = await self.collection.find_one({"_id": ObjectId(portfolio_id)})
        model_id = doc.get("portfolio_model_id") if doc else None

        result = await self.collection.delete_one({"_id": ObjectId(portfolio_id)})
        await self.rebalance_collection.delete_many({"portfolio_id": portfolio_id})

        # 级联清理：归档监控条目 + 取消关联组合模型的实盘标记
        if result.deleted_count > 0 and model_id and ObjectId.is_valid(str(model_id)):
            try:
                db = self.collection.database
                # 1. 归档监控条目（软删除，保留历史；source_ref 兼容 str/ObjectId）
                mon_result = await db["monitored_strategies"].update_many(
                    {
                        "source_type": "portfolio",
                        "source_ref": {"$in": [str(model_id), ObjectId(str(model_id))]},
                    },
                    {"$set": {"status": "archived", "updated_at": datetime.now()}},
                )
                # 2. 取消组合模型实盘标记，防止 sync_live_published 重新激活
                await db["strategy_models"].update_one(
                    {"_id": ObjectId(str(model_id))},
                    {"$set": {"live_publish_enabled": False, "updated_at": datetime.now()}},
                )
                logger.info(
                    "[组合删除] 级联清理完成: portfolio=%s model=%s 归档监控条目=%d",
                    portfolio_id, model_id, mon_result.modified_count,
                )
            except Exception as e:
                logger.warning("[组合删除] 级联清理监控/模型失败 portfolio=%s: %s", portfolio_id, e)
        return result.deleted_count > 0

    async def update_portfolio(self, portfolio_id: str, update_data: Dict[str, Any]) -> bool:
        """更新组合"""
        update_data["updated_at"] = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(portfolio_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0

    # ============================================================
    # 调仓记录
    # ============================================================

    async def add_rebalance_record(self, record: RebalanceRecord) -> str:
        """添加调仓记录"""
        data = record.dict(by_alias=True, exclude={"id"})
        result = await self.rebalance_collection.insert_one(data)
        return str(result.inserted_id)

    async def list_rebalance_records(self, portfolio_id: str) -> List[RebalanceRecord]:
        """查询调仓记录"""
        cursor = self.rebalance_collection.find(
            {"portfolio_id": portfolio_id}
        ).sort("rebalance_date", 1)
        records = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            records.append(RebalanceRecord(**doc))
        return records

    # ============================================================
    # 从单策略模型创建组合（保持已有功能兼容）
    # ============================================================

    async def create_from_single_model(
        self,
        model_id: str,
        inception_date: Optional[datetime],
        name: str,
        initial_capital: float = 10_000_000.0,
    ) -> str:
        """从单策略模型创建模拟组合，追溯生成历史持仓和业绩"""
        from app.backtesting.config import BacktestConfig
        from app.backtesting.data_feed import DataFeed
        from app.backtesting.runner import RunSpec, run_unified
        from app.backtesting.analytics import PerformanceAnalyzer
        from app.allocation.services.registry import create_strategy_service_from_database
        from app.services.market_service import MarketService

        model = await self.strategy_model_service.get_model(model_id)
        if not model:
            raise ValueError(f"策略模型不存在: {model_id}")

        end_date = datetime.now()
        # inception_date 可选，留空则默认从1年前开始回测
        if inception_date is None:
            from datetime import timedelta
            inception_date = end_date - timedelta(days=365)
        if inception_date.date() > end_date.date():
            raise ValueError(f"建仓日晚于今天，无法创建组合")

        config = BacktestConfig(
            name=f"init_{name}",
            thscodes=model.asset_codes,
            start_date=inception_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            rebalance_freq=model.rebalance_frequency,
            initial_cash=initial_capital,
        )

        market_service = MarketService()
        data_feed = await DataFeed.from_market_service(market_service, config, lookback_days=500)
        if data_feed.prices.empty:
            raise ValueError(f"资产在指定期间无行情数据")

        from app.allocation.builtin_templates import COMPOSITION_DEFAULTS
        from app.services.strategy_model_service import build_backtest_params
        strategy_service = await create_strategy_service_from_database(market_service)
        strategy_cls = strategy_service.get_strategy_class(model.template_code)
        composition = COMPOSITION_DEFAULTS.get(model.template_code, {
            "selector": None, "allocator": model.template_code, "controller": None
        })
        # 获取原始 MongoDB 文档，确保所有字段都能被 build_backtest_params 正确读取
        model_data = await self.strategy_model_service.collection.find_one({"_id": ObjectId(model_id)}) if model_id else None
        strategy_params = build_backtest_params(model, model_data=model_data)

        # 经唯一引擎入口运行
        backtest_result = run_unified(RunSpec(
            config=config,
            data_feed=data_feed,
            allocator=strategy_cls(),
            thscodes=model.asset_codes,
            composition=composition,
            strategy_params=strategy_params,
            risk_config=_build_risk_config_from_params(strategy_params),
        ))
        snapshots = backtest_result.snapshots
        if not snapshots:
            raise ValueError("回测未生成任何快照")

        # 计算业绩
        analyzer = PerformanceAnalyzer(risk_free_rate=0.02)
        asset_names = {}
        for code in model.asset_codes:
            info = await self.asset_service.get_asset_by_code(code)
            if info:
                asset_names[code] = info.name

        _ml = (model.parameters or {}).get("max_leverage") or (model.parameters or {}).get("max_total_leverage")
        _ml = float(_ml) if _ml is not None else None
        performance = analyzer.create_model_result(
            snapshots=snapshots,
            trades=backtest_result.trades,
            asset_names=asset_names,
            initial_capital=initial_capital,
            max_leverage=_ml,
        )

        # 创建组合
        portfolio = Portfolio(
            name=name,
            source=PortfolioSource.SINGLE_STRATEGY,
            model_id=model_id,
            rebalance_frequency=model.rebalance_frequency,
            initial_capital=initial_capital,
            current_capital=snapshots[-1].total_value if snapshots else initial_capital,
            positions=[
                Position(
                    asset_code=code,
                    asset_name=asset_names.get(code, code),
                    weight=weight,
                    market_value=snapshots[-1].total_value * weight,
                )
                for code, weight in snapshots[-1].weights.items()
            ] if snapshots else [],
            performance=performance,
            inception_date=inception_date,
        )
        portfolio_id = await self.create_portfolio(portfolio)

        # 追溯调仓记录
        prev_snapshot = None
        for s in snapshots:
            if s.is_rebalance_day:
                pos_before = []
                if prev_snapshot:
                    for c, w in prev_snapshot.weights.items():
                        pos_before.append(Position(asset_code=c, asset_name=asset_names.get(c, c), weight=w))
                pos_after = [
                    Position(asset_code=c, asset_name=asset_names.get(c, c), weight=w)
                    for c, w in s.weights.items()
                ]
                record = RebalanceRecord(
                    portfolio_id=portfolio_id,
                    rebalance_date=s.time,
                    action=RebalanceAction.ADJUST,
                    positions_before=pos_before,
                    positions_after=pos_after,
                    reason="模型自动触发",
                )
                await self.add_rebalance_record(record)
            prev_snapshot = s

        logger.info(f"[组合创建] 单策略 → 组合完成: {name}, 收益率={performance.total_return:.4%}")
        return portfolio_id

    # ============================================================
    # 从多个已发布策略直接组合 —— 仅建记录，不跑回测
    # ============================================================

    async def create_from_strategies(
        self,
        strategy_ids: List[str],
        name: str,
        initial_capital: float = 10_000_000.0,
        weight_method: str = "custom",
        weight_model_params: Optional[Dict[str, Any]] = None,
        sub_strategy_weights: Optional[List[dict]] = None,
        vol_target: Optional[float] = None,
        vol_lookback_short: Optional[int] = None,
        vol_lookback_long: Optional[int] = None,
        vol_method: Optional[str] = None,
        vol_annualize_factor: Optional[int] = None,
        vol_leverage_min: Optional[float] = None,
        vol_leverage_max: Optional[float] = None,
    ) -> str:
        """
        从用户选择的多个已发布策略直接组合创建模拟组合。

        流程：
        1. 加载每个策略模型
        2. 构建子策略权重配置
        3. 创建 Portfolio 文档（不执行回测）
        """
        if not strategy_ids:
            raise ValueError("请至少选择一个策略")

        # 1. 加载策略模型
        strategy_models = []
        for sid in strategy_ids:
            model = await self.strategy_model_service.get_model(sid)
            if not model:
                raise ValueError(f"策略模型不存在: {sid}")
            strategy_models.append(model)

        # 2. 构建权重映射和子策略配置
        weight_map = {}
        if sub_strategy_weights:
            weight_map = {w["model_id"]: w["weight"] for w in sub_strategy_weights}

        default_weight = 1.0 / len(strategy_models)
        sub_alloc_list: List[SubStrategyAllocation] = []
        for model in strategy_models:
            key = model.id or model.name
            weight = weight_map.get(key, default_weight)
            sub_alloc_list.append(SubStrategyAllocation(
                model_id=model.id or "",
                name=model.name,
                weight=weight,
                template_code=model.template_code,
            ))

        # 3. 创建 Portfolio 文档（仅记录，不跑回测）
        # source=MANUAL：此路径是用户手动选择多个策略直接组合，没有关联的组合模型 (portfolio_model_id=None)，
        # 若设为 PORTFOLIO_MODEL 则后续 compute_performance 会因缺少 portfolio_model_id 而无法计算绩效。
        portfolio = Portfolio(
            name=name,
            source=PortfolioSource.MANUAL,
            sub_strategies=sub_alloc_list,
            weight_method=weight_method,
            weight_model_params=weight_model_params or {},
            vol_target=vol_target,
            vol_lookback_short=vol_lookback_short if vol_target else None,
            vol_lookback_long=vol_lookback_long if vol_target else None,
            vol_method=vol_method if vol_target else None,
            vol_annualize_factor=vol_annualize_factor if vol_target else None,
            vol_leverage_min=vol_leverage_min if vol_target else None,
            vol_leverage_max=vol_leverage_max if vol_target else None,
            initial_capital=initial_capital,
            current_capital=initial_capital,
            performance=None,
            inception_date=datetime.now(),
        )
        portfolio_id = await self.create_portfolio(portfolio)

        logger.info(f"[组合创建] 多策略组合已创建: {name}, 策略数={len(sub_alloc_list)}")
        return portfolio_id

    # ============================================================
    # 从组合模型（多策略）创建组合 —— 核心新能力
    # ============================================================

    async def create_from_portfolio_model(
        self,
        portfolio_model_id: str,
        inception_date: Optional[datetime],
        name: str,
        initial_capital: float = 10_000_000.0,
        weight_method: str = "custom",
        sub_strategy_weights: Optional[List[dict]] = None,
        vol_target: Optional[float] = None,
        vol_lookback_short: int = 20,
        vol_lookback_long: int = 60,
        vol_method: Optional[str] = None,
        vol_annualize_factor: Optional[int] = None,
        vol_leverage_min: Optional[float] = None,
        vol_leverage_max: Optional[float] = None,
        rebalance_frequency: Optional[str] = None,
    ) -> str:
        """
        从组合模型（is_portfolio=True）创建模拟组合。

        流程：
        1. 读取组合模型，解析子策略列表
        2. 对每个子策略执行回测，得到 NAV 序列
        3. 根据 weight_method 计算权重（或使用自定义权重）
        4. 调用统一引擎组合路径复合为组合 NAV（含波动率控制）
        5. 创建 Portfolio 文档
        6. 追溯权重变化记录
        """
        from app.portfolio.composite_runner import run_composite_unified as run_portfolio_backtest
        from app.backtesting.analytics import PerformanceAnalyzer

        # 1. 读取组合模型
        portfolio_model = await self.strategy_model_service.get_model(portfolio_model_id)
        if not portfolio_model:
            raise ValueError(f"组合模型不存在: {portfolio_model_id}")
        if not portfolio_model.is_portfolio:
            raise ValueError(f"模型 {portfolio_model_id} 不是投资组合类型")
        if not portfolio_model.sub_strategies:
            raise ValueError("组合模型未配置子策略")

        end_date = datetime.now()
        # inception_date 可选，留空则默认从1年前开始回测
        if inception_date is None:
            from datetime import timedelta
            inception_date = end_date - timedelta(days=365)
        if inception_date.date() > end_date.date():
            raise ValueError("建仓日晚于今天，无法创建组合")

        # 2. 解析子策略并回测
        sub_pairs = await self.strategy_model_service.resolve_sub_strategies(portfolio_model)
        if not sub_pairs:
            raise ValueError("无法解析子策略")

        sub_nav_series: Dict[str, pd.Series] = {}
        sub_weights: Dict[str, float] = {}
        sub_alloc_list: List[SubStrategyAllocation] = []

        start_date_str = inception_date.strftime("%Y%m%d")
        end_date_str = end_date.strftime("%Y%m%d")

        for sub_model, weight in sub_pairs:
            # 如果是自定义权重且用户提供了权重配置，使用用户的权重
            if weight_method == "custom" and sub_strategy_weights:
                user_weight_map = {w["model_id"]: w["weight"] for w in sub_strategy_weights}
                sub_model_id = sub_model.id or sub_model.name
                weight = user_weight_map.get(sub_model_id, weight)
            try:
                nav_series = await self._run_sub_strategy_backtest(
                    sub_model, start_date_str, end_date_str, portfolio_model.initial_nav
                )
                if nav_series is not None and len(nav_series) > 1:
                    key = sub_model.id or sub_model.name
                    sub_nav_series[key] = nav_series
                    sub_weights[key] = weight
                    sub_alloc_list.append(SubStrategyAllocation(
                        model_id=sub_model.id or "",
                        name=sub_model.name,
                        weight=weight,
                        template_code=sub_model.template_code,
                    ))
            except Exception as e:
                logger.warning(f"[组合创建] 子策略 {sub_model.name} 回测失败: {e}")
                continue

        if not sub_nav_series:
            raise ValueError("所有子策略回测失败，无法构建组合")

        # 3. 根据 weight_method 计算权重
        if weight_method != "custom":
            from app.portfolio.weight_builder import PortfolioWeightBuilder
            computed_weights = PortfolioWeightBuilder.compute_weights(
                sub_nav_series=sub_nav_series,
                method=weight_method,
                lookback_days=252,
            )
            # 更新 sub_weights 和 sub_alloc_list 中的权重
            sub_weights = computed_weights
            for alloc in sub_alloc_list:
                key = alloc.model_id or alloc.name
                if key in computed_weights:
                    alloc.weight = computed_weights[key]
        # 否则使用 sub_strategies 中的原始权重（已在上方赋值）

        # 4. 复合（含波动率控制）
        rebalance_freq = rebalance_frequency or portfolio_model.rebalance_frequency or "monthly"
        # 将中文频率映射为英文
        freq_mapping = {"月": "monthly", "季": "quarterly", "年": "yearly"}
        rebalance_freq_en = freq_mapping.get(rebalance_freq, rebalance_freq)

        portfolio_result = run_portfolio_backtest(
            sub_nav_series=sub_nav_series,
            sub_weights=sub_weights,
            initial_nav=portfolio_model.initial_nav,
            rebalance_freq=rebalance_freq_en,
            mother_vol_target=vol_target,
            mother_vol_short=vol_lookback_short,
            mother_vol_long=vol_lookback_long,
            mother_vol_method=vol_method or "rolling",
            mother_annualize_factor=vol_annualize_factor,
            mother_leverage_min=vol_leverage_min,
            mother_leverage_max=vol_leverage_max,
        )

        # 4. 构造绩效
        perf = portfolio_result.performance
        nav_series = portfolio_result.portfolio_nav
        latest_nav = float(nav_series.iloc[-1]) if len(nav_series) > 0 else portfolio_model.initial_nav

        performance = ModelBacktestResult(
            total_return=perf.total_return,
            annual_return=perf.annual_return,
            annual_volatility=perf.annual_volatility,
            sharpe_ratio=perf.sharpe_ratio,
            max_drawdown=perf.max_drawdown,
            calmar_ratio=perf.calmar_ratio,
            latest_unit_value=round(latest_nav / portfolio_model.initial_nav, 4),
            sub_strategies=[
                {
                    "model_id": alloc.model_id,
                    "name": alloc.name,
                    "weight": alloc.weight,
                }
                for alloc in sub_alloc_list
            ],
        )

        # 5. 创建 Portfolio 文档
        portfolio = Portfolio(
            name=name,
            source=PortfolioSource.PORTFOLIO_MODEL,
            portfolio_model_id=portfolio_model_id,
            sub_strategies=sub_alloc_list,
            rebalance_frequency=rebalance_freq,
            weight_method=weight_method,
            vol_target=vol_target,
            vol_lookback_short=vol_lookback_short if vol_target else None,
            vol_lookback_long=vol_lookback_long if vol_target else None,
            vol_method=vol_method if vol_target else None,
            vol_annualize_factor=vol_annualize_factor if vol_target else None,
            vol_leverage_min=vol_leverage_min if vol_target else None,
            vol_leverage_max=vol_leverage_max if vol_target else None,
            initial_capital=initial_capital,
            current_capital=initial_capital * (1 + perf.total_return),
            performance=performance,
            inception_date=inception_date,
        )
        portfolio_id = await self.create_portfolio(portfolio)

        # 6. 追溯权重变化记录
        if not portfolio_result.weight_history.empty:
            wh = portfolio_result.weight_history
            prev_weights = None
            for dt_idx, row in wh.iterrows():
                current_weights = {k: round(float(v), 6) for k, v in row.items()}
                # 检测是否为再平衡日（权重重置）
                if prev_weights is not None:
                    drift = sum(abs(current_weights.get(k, 0) - prev_weights.get(k, 0)) for k in current_weights)
                    if drift > 0.01:  # 权重变化超过1%视为调仓
                        record = RebalanceRecord(
                            portfolio_id=portfolio_id,
                            rebalance_date=dt_idx.to_pydatetime(),
                            action=RebalanceAction.WEIGHT_CHANGE,
                            weights_before=prev_weights,
                            weights_after=current_weights,
                            reason="组合再平衡",
                        )
                        await self.add_rebalance_record(record)
                prev_weights = current_weights

        logger.info(
            f"[组合创建] 多策略组合完成: {name}, "
            f"子策略数={len(sub_alloc_list)}, 收益率={perf.total_return:.4%}, "
            f"夏普={perf.sharpe_ratio:.4f}"
        )

        # 7. 记录配置版本快照（复用策略参数版本系统）
        try:
            from app.services.param_version_service import ParamVersionService
            await ParamVersionService().create_param_version(
                model_id=portfolio_model_id,
                model=portfolio_model,
                change_summary=f"组合创建: {name} (权重方式={weight_method})",
            )
        except Exception as e:
            logger.warning(f"[组合创建] 记录配置版本失败: {e}")

        return portfolio_id

    # ============================================================
    # 子策略权重调整
    # ============================================================

    async def update_sub_strategy_weights(
        self,
        portfolio_id: str,
        new_weights: List[Dict[str, Any]],
        reason: Optional[str] = None,
    ) -> bool:
        """
        手动调整组合内子策略权重。

        Args:
            portfolio_id: 组合ID
            new_weights: [{model_id, weight}]
            reason: 调整原因
        """
        portfolio = await self.get_portfolio(portfolio_id)
        if not portfolio:
            raise ValueError(f"组合不存在: {portfolio_id}")
        if portfolio.source != PortfolioSource.PORTFOLIO_MODEL:
            raise ValueError("仅投资组合模型驱动的组合支持子策略权重调整")

        # 验证权重总和
        total = sum(w.get("weight", 0) for w in new_weights)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"子策略权重总和必须为1，当前: {total:.4f}")

        # 记录变更前的权重
        weights_before = {s.model_id: s.weight for s in portfolio.sub_strategies}

        # 更新子策略权重
        updated_subs = []
        weights_after = {}
        for sub in portfolio.sub_strategies:
            new_w = next((w for w in new_weights if w.get("model_id") == sub.model_id), None)
            if new_w:
                sub.weight = new_w["weight"]
            updated_subs.append(sub.dict())
            weights_after[sub.model_id] = sub.weight

        # 记录调仓
        record = RebalanceRecord(
            portfolio_id=portfolio_id,
            rebalance_date=datetime.now(),
            action=RebalanceAction.WEIGHT_CHANGE,
            weights_before=weights_before,
            weights_after=weights_after,
            reason=reason or "手动调整子策略权重",
        )
        await self.add_rebalance_record(record)

        # 更新组合文档
        await self.update_portfolio(portfolio_id, {"sub_strategies": updated_subs})

        # 记录配置版本快照（复用策略参数版本系统）
        if portfolio.portfolio_model_id:
            try:
                portfolio_model = await self.strategy_model_service.get_model(portfolio.portfolio_model_id)
                if portfolio_model:
                    weight_change_summary = ", ".join(
                        f"{w.get('model_id', '?')}:{w.get('weight', 0):.1%}" for w in new_weights
                    )
                    from app.services.param_version_service import ParamVersionService
                    await ParamVersionService().create_param_version(
                        model_id=portfolio.portfolio_model_id,
                        model=portfolio_model,
                        change_summary=f"权重调整: {weight_change_summary}" + (f" ({reason})" if reason else ""),
                    )
            except Exception as e:
                logger.warning(f"[权重调整] 记录配置版本失败: {e}")

        return True

    # ============================================================
    # 绩效计算
    # ============================================================

    async def compute_performance(self, portfolio_id: str) -> Optional[ModelBacktestResult]:
        """
        计算组合最新绩效。

        根据 source 类型分路处理：
        - PORTFOLIO_MODEL: 重新跑统一引擎组合路径
        - SINGLE_STRATEGY: 使用信号追踪策略
        - MANUAL: 基于调仓记录回测
        """
        portfolio = await self.get_portfolio(portfolio_id)
        if not portfolio:
            return None

        if portfolio.source == PortfolioSource.PORTFOLIO_MODEL:
            return await self._compute_portfolio_model_performance(portfolio)
        elif portfolio.source == PortfolioSource.SINGLE_STRATEGY:
            return await self._compute_single_strategy_performance(portfolio)
        else:
            return await self._compute_manual_performance(portfolio)

    async def _compute_portfolio_model_performance(self, portfolio: Portfolio) -> ModelBacktestResult:
        """组合模型绩效：复合各子策略NAV"""
        from app.models.strategy_model import EquityPoint

        result = await self._run_all_sub_strategies(portfolio)
        if result is None:
            return self._empty_result()

        portfolio_model, sub_pairs, sub_nav_series, sub_weights = result

        composite_result = await self._run_composite(
            portfolio, sub_nav_series, sub_weights, portfolio_model.initial_nav,
            start_date=portfolio.inception_date.strftime("%Y%m%d"),
            end_date=datetime.now().strftime("%Y%m%d"),
        )

        perf = composite_result.performance
        nav = composite_result.portfolio_nav
        latest_nav = float(nav.iloc[-1]) if len(nav) > 0 else portfolio_model.initial_nav

        # 构造净值曲线
        equity_curve = [
            EquityPoint(
                date=d.strftime("%Y-%m-%d"),
                unit_value=round(float(v) / portfolio_model.initial_nav, 6),
                cumulative_return=round(float(v) / portfolio_model.initial_nav - 1, 6),
            )
            for d, v in zip(nav.index, nav.values)
        ]

        return ModelBacktestResult(
            total_return=perf.total_return,
            annual_return=perf.annual_return,
            annual_volatility=perf.annual_volatility,
            sharpe_ratio=perf.sharpe_ratio,
            max_drawdown=perf.max_drawdown,
            calmar_ratio=perf.calmar_ratio,
            latest_unit_value=round(latest_nav / portfolio_model.initial_nav, 4),
            equity_curve=equity_curve,
        )

    async def _compute_single_strategy_performance(self, portfolio: Portfolio) -> ModelBacktestResult:
        """单策略组合绩效：使用信号追踪"""
        from app.backtesting.config import BacktestConfig
        from app.backtesting.data_feed import DataFeed
        from app.backtesting.risk import RiskConfig
        from app.backtesting.runner import RunSpec, run_unified
        from app.backtesting.analytics import PerformanceAnalyzer
        from app.services.market_service import MarketService

        rebalance_records = await self.list_rebalance_records(str(portfolio.id))
        start_date = portfolio.inception_date
        end_date = datetime.now()

        if start_date.date() > end_date.date():
            return self._empty_result()

        asset_codes = {p.asset_code for p in portfolio.positions}
        for r in rebalance_records:
            for p in r.positions_after:
                asset_codes.add(p.asset_code)

        if not asset_codes:
            return self._empty_result()

        config = BacktestConfig(
            name=f"perf_{portfolio.name}",
            thscodes=sorted(list(asset_codes)),
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            rebalance_freq="daily",
            initial_cash=portfolio.initial_capital,
        )

        market_service = MarketService()
        data_feed = await DataFeed.from_market_service(market_service, config, lookback_days=500)
        if data_feed.prices.empty:
            return self._empty_result()

        strategy_impl = _SignalTrackingStrategy(rebalance_records, portfolio.positions)

        # 信号追踪回放已记录的调仓权重：权重可能含空头（负值），
        # 风控层不得截断，否则绩效回放失真；经唯一引擎入口运行
        result = run_unified(RunSpec(
            config=config,
            data_feed=data_feed,
            allocator=strategy_impl,
            thscodes=sorted(list(asset_codes)),
            composition={"selector": None, "allocator": "signal_tracking", "controller": None},
            risk_config=RiskConfig(allow_negative_weights=True),
        ))
        if not result.snapshots:
            return self._empty_result()

        analyzer = PerformanceAnalyzer(risk_free_rate=0.02)
        asset_names = {}
        for code in asset_codes:
            info = await self.asset_service.get_asset_by_code(code)
            if info:
                asset_names[code] = info.name

        return analyzer.create_model_result(
            snapshots=result.snapshots,
            trades=result.trades,
            asset_names=asset_names,
            initial_capital=portfolio.initial_capital,
        )

    async def _compute_manual_performance(self, portfolio: Portfolio) -> ModelBacktestResult:
        """手工组合绩效：同单策略逻辑"""
        return await self._compute_single_strategy_performance(portfolio)

    # ============================================================
    # 辅助方法
    # ============================================================

    async def _run_all_sub_strategies(
        self,
        portfolio: Portfolio,
    ) -> Optional[Tuple[Any, List[Tuple], Dict[str, pd.Series], Dict[str, float]]]:
        """公共子策略执行函数：解析子策略 → 逐个回测 → 收集 NAV 和权重。

        消除 _compute_portfolio_model_performance / compute_drawdown_series /
        _compute_sub_strategy_analysis 三处重复的子策略执行逻辑。

        Returns:
            (portfolio_model, sub_pairs, sub_nav_series, sub_weights) 元组，
            失败时返回 None。
        """
        if not portfolio.portfolio_model_id:
            return None

        portfolio_model = await self.strategy_model_service.get_model(portfolio.portfolio_model_id)
        if not portfolio_model:
            return None

        sub_pairs = await self.strategy_model_service.resolve_sub_strategies(portfolio_model)
        if not sub_pairs:
            return None

        start_date_str = portfolio.inception_date.strftime("%Y%m%d")
        end_date_str = datetime.now().strftime("%Y%m%d")

        sub_nav_series: Dict[str, pd.Series] = {}
        sub_weights: Dict[str, float] = {}

        for sub_model, weight in sub_pairs:
            # 使用组合当前配置的权重（可能已被手动修改）
            actual_weight = weight
            for alloc in portfolio.sub_strategies:
                if alloc.model_id == sub_model.id:
                    actual_weight = alloc.weight
                    break

            try:
                nav = await self._run_sub_strategy_backtest(
                    sub_model, start_date_str, end_date_str, portfolio_model.initial_nav
                )
                if nav is not None and len(nav) > 1:
                    key = sub_model.id or sub_model.name
                    sub_nav_series[key] = nav
                    sub_weights[key] = actual_weight
            except Exception as e:
                logger.warning(f"[子策略执行] {sub_model.name} 回测失败: {e}")

        if not sub_nav_series:
            return None

        return portfolio_model, sub_pairs, sub_nav_series, sub_weights

    async def _run_composite(
        self,
        portfolio: Portfolio,
        sub_nav_series: Dict[str, pd.Series],
        sub_weights: Dict[str, float],
        initial_nav: float,
        start_date: str,
        end_date: str,
    ):
        """公共复合函数：调用统一引擎组合路径生成组合 NAV。

        统一处理频率映射和母层波动率控制参数；四象限调权组合
        （weight_method == 'quadrant'）经组合层共享构建块组装权重模型，
        与回测 API 同一参数口径（避免绩效/回撤链路断点）。

        Returns:
            PortfolioBacktestResult
        """
        from app.portfolio.composite_runner import run_composite_unified as run_portfolio_backtest

        rebalance_freq = portfolio.rebalance_frequency or "monthly"
        freq_mapping = {"月": "monthly", "季": "quarterly", "年": "yearly"}
        rebalance_freq_en = freq_mapping.get(rebalance_freq, rebalance_freq)

        # 四象限调权：组装权重模型 + 再平衡信号 + 执行调度（与回测 API 同源）
        weight_model = None
        rebalance_signal = None
        execution_schedule = None
        weight_drift = True
        if portfolio.weight_method == "quadrant":
            from app.portfolio.quadrant_components import build_quadrant_weight_components

            try:
                weight_model, rebalance_signal, execution_schedule, weight_drift = (
                    await build_quadrant_weight_components(
                        portfolio.weight_model_params or {}, start_date, end_date,
                    )
                )
            except ValueError as exc:
                logger.warning("[组合复合] 四象限组件组装失败，退回固定权重复合: %s", exc)

        return run_portfolio_backtest(
            sub_nav_series=sub_nav_series,
            sub_weights=sub_weights,
            initial_nav=initial_nav,
            rebalance_freq=rebalance_freq_en,
            mother_vol_target=portfolio.vol_target,
            mother_vol_short=portfolio.vol_lookback_short or 20,
            mother_vol_long=portfolio.vol_lookback_long or 60,
            mother_vol_method=portfolio.vol_method or "rolling",
            mother_annualize_factor=portfolio.vol_annualize_factor,
            mother_leverage_min=portfolio.vol_leverage_min,
            mother_leverage_max=portfolio.vol_leverage_max,
            weight_model=weight_model,
            rebalance_signal=rebalance_signal,
            execution_schedule=execution_schedule,
            weight_drift=weight_drift,
        )

    async def _run_sub_strategy_backtest(
        self,
        sub_model,
        start_date: str,
        end_date: str,
        initial_nav: float,
        commission_rate: Optional[float] = None,
        slippage: Optional[float] = None,
    ) -> Optional[pd.Series]:
        """运行单个子策略回测，返回归一化 NAV 序列

        费率口径：子策略 NAV 用于母组合 NAV 层复合，默认零成本（指数口径，
        与 GMSI 2.0 原型一致）；显式传入 commission_rate/slippage 时按传入值扣费。
        """
        from app.backtesting.config import BacktestConfig
        from app.backtesting.data_feed import DataFeed
        from app.backtesting.runner import RunSpec, run_unified
        from app.allocation.services.registry import create_strategy_service_from_database
        from app.services.market_service import MarketService
        from app.backtesting.composition_builder import build_strategy_composition
        from app.services.strategy_model_service import build_backtest_params
        from bson import ObjectId as _ObjId

        # 获取原始 MongoDB 文档，确保选择器等字段都能被正确读取
        sub_model_data = await self.strategy_model_service.collection.find_one({"_id": _ObjId(sub_model.id)}) if sub_model.id else None
        strategy_params = build_backtest_params(sub_model, model_data=sub_model_data)

        # 统一 composition 推导（含模型级 controller_code 覆盖与选择器接入）
        spec = build_strategy_composition(
            sub_model.template_code, sub_model.asset_codes, strategy_params,
        )

        rebalance_freq = sub_model.rebalance_frequency or "monthly"
        if spec.force_month_end:
            rebalance_freq = "month_end"

        config = BacktestConfig(
            name=f"sub_{sub_model.name}",
            thscodes=sub_model.asset_codes,
            start_date=start_date,
            end_date=end_date,
            rebalance_freq=rebalance_freq,
            initial_cash=10_000_000,
            commission_rate=0.0 if commission_rate is None else float(commission_rate),
            slippage=0.0 if slippage is None else float(slippage),
        )

        # 模型级期初建仓声明：指数类策略从基日起满仓运行（如原型首次执行前
        # 权重 = fillna(1/n) 等权），用模型参数 inception_weights 声明而非留空仓
        init_w = strategy_params.get("inception_weights")
        if isinstance(init_w, dict) and init_w:
            config.initial_weights = {str(k): float(v) for k, v in init_w.items()}
            config.initial_weights_auto_normalize = bool(
                strategy_params.get("inception_weights_auto_normalize", False)
            )

        market_service = MarketService()
        data_feed = await DataFeed.from_market_service(market_service, config, lookback_days=500)
        if data_feed.prices.empty:
            return None

        strategy_service = await create_strategy_service_from_database(market_service)
        strategy_cls = strategy_service.get_strategy_class(sub_model.template_code)

        # 经唯一引擎入口运行
        result = run_unified(RunSpec(
            config=config,
            data_feed=data_feed,
            allocator=strategy_cls(),
            thscodes=sub_model.asset_codes,
            composition=spec.composition,
            strategy_params=strategy_params,
            risk_config=_build_risk_config_from_params(strategy_params),
        ))
        if not result.snapshots:
            return None

        # 构造 NAV 序列，归一化到 initial_nav
        nav_data = {s.time: s.total_value for s in result.snapshots}
        series = pd.Series(nav_data).sort_index()
        if len(series) > 0 and series.iloc[0] != 0:
            series = series / series.iloc[0] * initial_nav
        return series

    @staticmethod
    def _empty_result() -> ModelBacktestResult:
        return ModelBacktestResult(
            total_return=0, annual_return=0, annual_volatility=0,
            sharpe_ratio=0, max_drawdown=0,
        )

    async def update_performance(self, portfolio_id: str, performance: ModelBacktestResult) -> bool:
        """更新组合绩效"""
        perf_dict = performance.dict()
        return await self.update_portfolio(portfolio_id, {"performance": perf_dict})

    async def compute_drawdown_series(self, portfolio_id: str) -> List[Dict]:
        """
        计算组合回撤序列。

        Returns:
            List[Dict]: [{"date": "YYYY-MM-DD", "drawdown": float}, ...]
        """
        portfolio = await self.get_portfolio(portfolio_id)
        if not portfolio:
            return []

        if portfolio.source == PortfolioSource.PORTFOLIO_MODEL and portfolio.portfolio_model_id:
            result = await self._run_all_sub_strategies(portfolio)
            if result is None:
                return []

            portfolio_model, sub_pairs, sub_nav_series, sub_weights = result

            composite_result = await self._run_composite(
                portfolio, sub_nav_series, sub_weights, portfolio_model.initial_nav,
                start_date=portfolio.inception_date.strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
            )

            nav = composite_result.portfolio_nav
            if len(nav) < 2:
                return []

            # 计算回撤序列
            cummax = nav.cummax()
            drawdown = (nav - cummax) / cummax
            return [
                {"date": d.strftime("%Y-%m-%d"), "drawdown": round(float(v), 6)}
                for d, v in zip(drawdown.index, drawdown.values)
            ]

        return []


class _SignalTrackingStrategy:
    """信号追踪策略：根据历史调仓记录产生权重信号"""

    def __init__(self, records: List[RebalanceRecord], initial_positions: List[Position] = None):
        self.signals = {}
        for r in records:
            if r.positions_after:
                self.signals[r.rebalance_date.date()] = pd.Series(
                    {p.asset_code: p.weight for p in r.positions_after if p.weight}
                )
        self.current_weights = pd.Series(dtype=float)
        if initial_positions:
            self.current_weights = pd.Series(
                {p.asset_code: p.weight for p in initial_positions if p.weight}
            )

    def allocate(self, history_prices: pd.DataFrame, **params) -> pd.Series:
        as_of_date = history_prices.index[-1].date()
        if as_of_date in self.signals:
            self.current_weights = self.signals[as_of_date]
        return self.current_weights
