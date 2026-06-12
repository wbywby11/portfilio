"""模拟组合服务层"""
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from bson import ObjectId
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger("uvicorn.error")

from app.config.database import Database
from app.models.portfolio import Portfolio, RebalanceRecord, Position, PortfolioType, RebalanceAction
from app.models.strategy_model import BacktestResult as ModelBacktestResult
from app.services.asset_service import AssetService
from app.services.strategy_model_service import StrategyModelService
from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.engine import BacktestEngine
from app.backtesting.risk import RiskManager, RiskConfig
from app.backtesting.execution import ExecutionEngine
from app.backtesting.strategy_api import StrategiesWrapper
from app.strategies.services.registry import create_strategy_service_from_database
from app.backtesting.analytics import PerformanceAnalyzer
from app.backtesting.strategy_api import IStrategy
from app.backtesting.signal import TargetWeightSignal

class SignalTrackingStrategy:
    """
    信号追踪策略：根据给定的历史调仓记录产生信号
    用于在回测引擎中精准复现手工调仓或已发生的调仓历史
    """
    def __init__(self, records: List[RebalanceRecord], initial_positions: List[Position] = None):
        # 将调仓记录按日期组织，方便查找
        self.signals = {
            r.rebalance_date.date(): pd.Series({p.asset_code: p.weight for p in r.positions_after})
            for r in records
        }
        # 初始权重状态
        self.current_weights = pd.Series(dtype=float)
        if initial_positions:
            self.current_weights = pd.Series({p.asset_code: p.weight for p in initial_positions})

    def allocate(self, history_prices: pd.DataFrame, **params) -> pd.Series:
        """
        满足 StrategiesWrapper 要求的接口
        """
        as_of_date = history_prices.index[-1].date()
        # 如果当前日期有记录，则更新并返回新权重
        if as_of_date in self.signals:
            self.current_weights = self.signals[as_of_date]
        
        # 返回当前持有的权重（维持不变或更新后的）
        return self.current_weights


class PortfolioService:
    """模拟组合服务"""

    def __init__(self):
        self._db = None
        self._collection = None
        self._rebalance_collection = None
        self.asset_service = AssetService()

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.db["portfolios"]
        return self._collection

    @property
    def rebalance_collection(self):
        if self._rebalance_collection is None:
            self._rebalance_collection = self.db["rebalance_records"]
        return self._rebalance_collection

    async def create_portfolio(self, portfolio: Portfolio) -> str:
        data = portfolio.dict(by_alias=True, exclude={"id"})
        result = await self.collection.insert_one(data)
        return str(result.inserted_id)

    async def get_portfolio(self, portfolio_id: str) -> Optional[Portfolio]:
        data = await self.collection.find_one({"_id": ObjectId(portfolio_id)})
        if not data:
            return None
        data["_id"] = str(data["_id"])
        return Portfolio(**data)

    async def list_portfolios(self, skip: int = 0, limit: int = 100) -> List[Portfolio]:
        cursor = self.collection.find({}).skip(skip).limit(limit).sort("created_at", -1)
        result: List[Portfolio] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            result.append(Portfolio(**doc))
        return result

    async def add_rebalance_record(self, record: RebalanceRecord) -> str:
        data = record.dict(by_alias=True, exclude={"id"})
        result = await self.rebalance_collection.insert_one(data)
        return str(result.inserted_id)

    async def list_rebalance_records(self, portfolio_id: str) -> List[RebalanceRecord]:
        cursor = self.rebalance_collection.find({"portfolio_id": portfolio_id}).sort("rebalance_date", 1)
        result: List[RebalanceRecord] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            result.append(RebalanceRecord(**doc))
        return result

    async def delete_portfolio(self, portfolio_id: str) -> bool:
        """删除模拟组合及其相关的调仓记录"""
        # 1. 删除调仓记录
        await self.rebalance_collection.delete_many({"portfolio_id": portfolio_id})
        # 2. 删除组合
        result = await self.collection.delete_one({"_id": ObjectId(portfolio_id)})
        return result.deleted_count > 0

    async def compute_performance(self, portfolio_id: str) -> ModelBacktestResult:
        """
        使用回测引擎重新计算组合业绩及净值曲线，确保与回测系统逻辑完全一致
        """
        portfolio = await self.get_portfolio(portfolio_id)
        if not portfolio:
            raise ValueError("组合不存在")

        # 1. 收集调仓记录作为信号源
        rebalance_records = await self.list_rebalance_records(portfolio_id)
        
        # 2. 确定时间区间
        start_date = portfolio.inception_date
        end_date = datetime.now()
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        # 2.1 校验日期区间：建仓日不能晚于今天
        if start_date.date() > end_date.date():
            logger.warning(
                f"追溯回测 [{portfolio.name}]: 建仓日 {start_date_str} 晚于今天 {end_date_str}，"
                "组合尚未开始运作，无法计算业绩。请检查组合建仓日期。"
            )
            return ModelBacktestResult(
                total_return=0, annual_return=0, annual_volatility=0,
                sharpe_ratio=0, max_drawdown=0
            )

        # 3. 构造回测配置
        asset_codes = {p.asset_code for p in portfolio.positions}
        for r in rebalance_records:
            for p in r.positions_after:
                asset_codes.add(p.asset_code)
        
        if not asset_codes:
            return ModelBacktestResult(
                total_return=0, annual_return=0, annual_volatility=0,
                sharpe_ratio=0, max_drawdown=0
            )

        config = BacktestConfig(
            name=f"perf_{portfolio.name}",
            thscodes=sorted(list(asset_codes)),
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            rebalance_freq="daily", # 设为daily，依靠策略内部判断信号
            initial_cash=portfolio.initial_capital
        )

        # 4. 运行回测引擎
        from app.services.market_service import MarketService
        market_service = MarketService()
        data_feed = await DataFeed.from_market_service(market_service, config, lookback_days=500)

        # 4.1 校验行情数据：无数据则无法回测
        if data_feed.prices.empty or len(data_feed.prices) == 0:
            logger.warning(
                f"追溯回测 [{portfolio.name}]: 资产 {config.thscodes} 在 {start_date_str} 至 {end_date_str} 期间无行情数据，"
                "无法计算业绩。请检查资产代码、数据源及日期范围（是否超出数据覆盖范围）。"
            )
            return ModelBacktestResult(
                total_return=0, annual_return=0, annual_volatility=0,
                sharpe_ratio=0, max_drawdown=0
            )

        # 4.2 无数据时以最后有数据的日期作为回测终点：若请求区间与数据无交集，则用数据实际范围
        prices_idx = data_feed.prices.index
        data_min_dt = pd.Timestamp(prices_idx.min())
        data_max_dt = pd.Timestamp(prices_idx.max())
        req_start_dt = pd.to_datetime(config.start_date)
        req_end_dt = pd.to_datetime(config.end_date)
        # 有效区间 = 请求区间与数据区间的交集
        effective_start_dt = max(req_start_dt, data_min_dt)
        effective_end_dt = min(req_end_dt, data_max_dt)
        if effective_start_dt <= effective_end_dt:
            # 有交集：用数据最后日期作为终点（若请求终点超出数据）
            if effective_end_dt < req_end_dt:
                config.end_date = effective_end_dt.strftime("%Y%m%d")
                logger.info(
                    f"追溯回测 [{portfolio.name}]: 请求终点 {end_date_str} 超出数据范围，"
                    f"已用数据最后日期 {config.end_date} 作为回测终点"
                )
            if effective_start_dt > req_start_dt:
                config.start_date = effective_start_dt.strftime("%Y%m%d")
                logger.info(
                    f"追溯回测 [{portfolio.name}]: 建仓日 {start_date_str} 早于数据起始，"
                    f"已用数据首日 {config.start_date} 作为回测起点"
                )
        else:
            # 无交集：建仓日晚于数据最后日期，无法回测
            logger.warning(
                f"追溯回测 [{portfolio.name}]: 建仓日 {start_date_str} 晚于数据最后日期 {data_max_dt.strftime('%Y-%m-%d')}，"
                "回测区间与行情数据无交集，无法计算业绩。"
            )
            return ModelBacktestResult(
                total_return=0, annual_return=0, annual_volatility=0,
                sharpe_ratio=0, max_drawdown=0
            )

        # 使用信号追踪策略复现历史
        strategy_impl = SignalTrackingStrategy(rebalance_records, initial_positions=portfolio.positions)
        strategy = StrategiesWrapper(strategy_impl=strategy_impl, params={})
        
        engine = BacktestEngine(
            config=config,
            data_feed=data_feed,
            strategy=strategy,
            risk_manager=RiskManager(RiskConfig()),
            execution_engine=ExecutionEngine(config)
        )
        
        backtest_result = engine.run()
        snapshots = backtest_result.snapshots

        # 实际使用的回测区间（可能已按数据范围调整）
        actual_start_str = f"{config.start_date[:4]}-{config.start_date[4:6]}-{config.start_date[6:8]}"
        actual_end_str = f"{config.end_date[:4]}-{config.end_date[4:6]}-{config.end_date[6:8]}"

        # 增加日志：打印回测生成的基础结果
        logger.info(f"--- 追溯回测完成 [{portfolio.name}] ---")
        logger.info(f"回测期间: {actual_start_str} 至 {actual_end_str}")
        logger.info(f"总交易日: {len(snapshots)}")
        logger.info(f"总交易笔数: {len(backtest_result.trades)}")
        
        # 增加日志：打印每个快照的详细内容
        logger.info("--- Snapshots 详情 ---")
        for i, s in enumerate(snapshots):
            rebalance_mark = "[调仓日]" if s.is_rebalance_day else ""
            logger.info(f"[{i:03d}] 日期: {s.time.strftime('%Y-%m-%d')} | 总市值: {s.total_value:,.2f} | 现金: {s.cash:,.2f} {rebalance_mark}")
            if s.is_rebalance_day:
                logger.info(f"      权重: {s.weights}")
        
        if snapshots:
            logger.info(f"期末总市值: {snapshots[-1].total_value:.2f}")

        if not snapshots:
            logger.warning(
                f"追溯回测 [{portfolio.name}]: 回测无数据（快照数=0）。可能原因："
                "1) 回测区间内无有效交易日；2) 行情数据在区间内全为空；3) 日期区间配置异常。请核查。"
            )
            return ModelBacktestResult(
                total_return=0, annual_return=0, annual_volatility=0,
                sharpe_ratio=0, max_drawdown=0
            )

        # 5. 计算标准化指标并构造结果对象 (完全复用回测分析模块)
        analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
        
        # 获取资产名称映射
        asset_names = {}
        for code in asset_codes:
            asset_info = await self.asset_service.get_asset_by_code(code)
            if asset_info:
                asset_names[code] = asset_info.name

        return analyzer.create_model_result(
            snapshots=snapshots,
            trades=backtest_result.trades,
            asset_names=asset_names,
            initial_capital=portfolio.initial_capital
        )

    async def update_performance(self, portfolio_id: str, performance: ModelBacktestResult) -> bool:
        """
        更新组合业绩表现。注意：这里存储的是 ModelBacktestResult 转换后的字典
        """
        result = await self.collection.update_one(
            {"_id": ObjectId(portfolio_id)},
            {"$set": {"performance": performance.dict(), "updated_at": datetime.now()}},
        )
        return result.modified_count > 0

    async def create_from_model(self, model_id: str, inception_date: datetime, name: str, initial_capital: float = 10_000_000.0) -> str:
        """
        从策略模型创建模拟组合，并追溯生成历史持仓和业绩
        """
        model_service = StrategyModelService()
        model = await model_service.get_model(model_id)
        if not model:
            raise ValueError(f"策略模型不存在: {model_id}")

        # 1. 配置回测引擎 (从建仓日到当前)
        end_date = datetime.now()
        if inception_date.date() > end_date.date():
            raise ValueError(
                f"建仓日 {inception_date.strftime('%Y-%m-%d')} 晚于今天 {end_date.strftime('%Y-%m-%d')}，"
                "无法创建组合。请选择今天或之前的日期作为建仓日。"
            )
        start_date_str = inception_date.strftime("%Y%m%d")
        end_date_str = end_date.strftime("%Y%m%d")

        config = BacktestConfig(
            name=f"init_{name}",
            thscodes=model.asset_codes,
            start_date=start_date_str,
            end_date=end_date_str,
            rebalance_freq=model.rebalance_frequency,
            initial_cash=initial_capital
        )

        # 2. 运行回测生成历史数据
        from app.services.market_service import MarketService
        market_service = MarketService()
        data_feed = await DataFeed.from_market_service(market_service, config, lookback_days=500)
        if data_feed.prices.empty or len(data_feed.prices) == 0:
            raise ValueError(
                f"资产 {model.asset_codes} 在 {start_date_str} 至 {end_date_str} 期间无行情数据，"
                "无法创建组合。请检查资产配置及数据源。"
            )

        strategy_service = await create_strategy_service_from_database(market_service)
        strategy_cls = strategy_service.get_strategy_class(model.template_code)
        strategy = StrategiesWrapper(strategy_impl=strategy_cls(), params=model.parameters)
        
        engine = BacktestEngine(
            config=config,
            data_feed=data_feed,
            strategy=strategy,
            risk_manager=RiskManager(RiskConfig()),
            execution_engine=ExecutionEngine(config)
        )
        
        backtest_result = engine.run()
        snapshots = backtest_result.snapshots
        if not snapshots:
            raise ValueError(
                f"回测未生成任何快照。资产 {model.asset_codes} 在 {start_date_str} 至 {end_date_str} 期间可能无有效行情数据，"
                "或日期区间与数据无交集。请检查资产配置及数据源。"
            )

        # 3. 计算业绩指标并构造结果对象 (复用分析模块)
        analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
        
        # 获取资产名称映射
        asset_names = {}
        for code in model.asset_codes:
            asset_info = await self.asset_service.get_asset_by_code(code)
            if asset_info:
                asset_names[code] = asset_info.name

        performance = analyzer.create_model_result(
            snapshots=snapshots,
            trades=backtest_result.trades,
            asset_names=asset_names,
            initial_capital=initial_capital
        )

        # 增加日志：打印核心业绩指标
        logger.info(f"--- 核心业绩指标 ---")
        logger.info(f"累计收益率: {performance.total_return:.4%}")
        logger.info(f"年化收益率: {performance.annual_return:.4%}")
        logger.info(f"最大回撤: {performance.max_drawdown:.4%}")
        logger.info(f"夏普比率: {performance.sharpe_ratio:.4f}")
        logger.info(f"最新单位净值: {performance.latest_unit_value:.4f}")
        logger.info(f"--------------------------------")

        # 7. 创建组合文档
        portfolio = Portfolio(
            name=name,
            portfolio_type=PortfolioType.MODEL_DRIVEN,
            model_id=model_id,
            rebalance_frequency=model.rebalance_frequency, # 同步调仓频率
            initial_capital=initial_capital,
            current_capital=snapshots[-1].total_value if snapshots else initial_capital,
            positions=[
                Position(
                    asset_code=code,
                    asset_name=asset_names.get(code, code),
                    weight=weight,
                    market_value=snapshots[-1].total_value * weight,
                    price=0.0
                )
                for code, weight in snapshots[-1].weights.items()
            ] if snapshots else [],
            performance=performance,
            inception_date=inception_date
        )
        
        portfolio_id = await self.create_portfolio(portfolio)

        # 8. 追溯生成调仓记录 (仅记录调仓日)
        rebalance_records = []
        prev_snapshot = None
        for s in snapshots:
            if s.is_rebalance_day:
                # 构造调仓前持仓
                pos_before = []
                if prev_snapshot:
                    for c, w in prev_snapshot.weights.items():
                        pos_before.append(Position(asset_code=c, asset_name=asset_names.get(c, c), weight=w))
                
                # 构造调仓后持仓
                pos_after = []
                for c, w in s.weights.items():
                    pos_after.append(Position(asset_code=c, asset_name=asset_names.get(c, c), weight=w))
                
                record = RebalanceRecord(
                    portfolio_id=portfolio_id,
                    rebalance_date=s.time,
                    action=RebalanceAction.ADJUST,
                    positions_before=pos_before,
                    positions_after=pos_after,
                    reason=getattr(s, 'rebalance_reason', "模型自动触发")
                )
                await self.add_rebalance_record(record)
            prev_snapshot = s

        return portfolio_id

    async def run_daily_batch_maintenance(self):
        """
        批量维护所有模拟组合：
        1. 检查模型驱动的组合是否需要调仓
        2. 更新所有组合的最新业绩表现
        """
        # 获取所有组合
        cursor = self.collection.find({})
        async for doc in cursor:
            portfolio_id = str(doc["_id"])
            portfolio = await self.get_portfolio(portfolio_id)
            
            # 1. 处理调仓 (如果是模型驱动)
            if portfolio.portfolio_type == PortfolioType.MODEL_DRIVEN and portfolio.model_id:
                await self._check_and_execute_rebalance(portfolio)
            
            # 2. 更新业绩表现
            perf = await self.compute_performance(portfolio_id)
            await self.update_performance(portfolio_id, perf)

    async def _check_and_execute_rebalance(self, portfolio: Portfolio):
        """检查并执行关联模型的调仓"""
        model_service = StrategyModelService()
        model = await model_service.get_model(portfolio.model_id)
        if not model:
            return

        today = datetime.now()
        # 这里需要判断今天是否是调仓日或触发了事件
        # 逻辑：获取最近的数据，运行策略的 should_rebalance 逻辑
        # 由于 BacktestEngine 已经封装了该逻辑，我们可以模拟一个极短时间的回测或直接调用接口
        
        # 简化版实现：获取最近两天的价格，检查是否触发
        asset_codes = model.asset_codes
        prices = await self.asset_service.get_price_dataframe(asset_codes, today - pd.Timedelta(days=500), today)
        if prices.empty:
            return

        # 创建策略实例
        from app.services.market_service import MarketService
        market_service = MarketService()
        strategy_service = await create_strategy_service_from_database(market_service)
        strategy_cls = strategy_service.get_strategy_class(model.template_code)
        strategy_impl = strategy_cls()
        
        # 检查触发原因
        current_weights_series = pd.Series({p.asset_code: p.weight for p in portfolio.positions})
        
        # 1. 检查是否是周期调仓日
        from app.backtesting.config import BacktestConfig
        
        # 调仓频率映射
        freq_mapping = {
            "日": "daily", "周": "weekly", "月": "monthly", "季": "quarterly", "年": "yearly",
            "daily": "daily", "weekly": "weekly", "monthly": "monthly", "quarterly": "quarterly", "yearly": "yearly"
        }
        rebalance_freq = freq_mapping.get(portfolio.rebalance_frequency or model.rebalance_frequency, "monthly")

        tmp_config = BacktestConfig(
            name="temp", thscodes=asset_codes, 
            start_date=today.strftime("%Y%m%d"), 
            end_date=today.strftime("%Y%m%d"),
            rebalance_freq=rebalance_freq
        )
        
        engine = BacktestEngine(tmp_config, None, None, None, None)
        is_periodic = engine._should_rebalance(pd.Timestamp(today.date()))
        
        # 2. 检查事件触发 (波动率等)
        is_event = False
        event_reason = None
        if hasattr(strategy_impl, 'check_volatility_trigger'):
            is_event, vol_val = strategy_impl.check_volatility_trigger(
                current_weights=current_weights_series,
                prices=prices,
                **model.parameters
            )
            if is_event:
                event_reason = f"波动率重置触发(当前波动率:{vol_val:.4%})" if vol_val is not None else "波动率重置触发"

        if is_periodic or is_event:
            # 执行调仓
            strategy = StrategiesWrapper(strategy_impl=strategy_impl, params=model.parameters)
            target_signal = strategy.generate_target_weights(prices, as_of=today)
            new_weights = target_signal.target_weights
            
            # 记录调仓
            asset_names = {p.asset_code: p.asset_name for p in portfolio.positions}
            pos_after = []
            for code, w in new_weights.items():
                if code not in asset_names:
                    info = await self.asset_service.get_asset_by_code(code)
                    asset_names[code] = info.name if info else code
                
                pos_after.append(Position(
                    asset_code=code,
                    asset_name=asset_names[code],
                    weight=w,
                    market_value=portfolio.current_capital * w
                ))
            
            record = RebalanceRecord(
                portfolio_id=str(portfolio.id),
                rebalance_date=today,
                action=RebalanceAction.ADJUST,
                positions_before=portfolio.positions,
                positions_after=pos_after,
                reason=event_reason if is_event else "周期性调仓"
            )
            await self.add_rebalance_record(record)
            
            # 更新组合当前持仓
            await self.collection.update_one(
                {"_id": ObjectId(portfolio.id)},
                {"$set": {"positions": [p.dict() for p in pos_after], "updated_at": datetime.now()}}
            )
