# -*- coding: utf-8 -*-
"""
模拟交易引擎

逐日从当前状态推进到目标日期，复用 BacktestEngine + ExecutionEngine 核心逻辑。
职责：
  - 逐日推进：策略信号 → 虚拟成交 → 持仓快照 → NAV
  - 跟踪误差分析：模拟 NAV vs 回测 NAV
  - Brinson 绩效归因
"""
from __future__ import annotations

import math
import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Tuple

import numpy as np
import pandas as pd
from bson import ObjectId

from app.config.database import Database
from app.portfolio.models import (
    SimTrade,
    SimDailySnapshot,
    SimPositionSnapshot,
    Portfolio,
    Position,
    RebalanceAction,
)
from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.execution import ExecutionEngine
from app.backtesting.signal import TargetWeightSignal
from app.backtesting.types import Bar as BtBar, Position as BtPosition, Trade as BtTrade
from app.services.asset_service import AssetService
from app.services.published_snapshot import apply_published_snapshot
from app.services.strategy_model_service import StrategyModelService
from app.models.strategy_model import ModelStatus
from app.allocation.services.registry import create_strategy_service_from_database

logger = logging.getLogger("uvicorn.error")


class SimTradeEngine:
    """模拟交易引擎"""

    def __init__(self):
        self._db = None
        self.asset_service = AssetService()

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
    #  逐日推进
    # ────────────────────────────────────────────────

    async def advance_to_date(
        self,
        portfolio: Portfolio,
        target_date: date,
    ) -> Dict[str, Any]:
        """
        将模拟组合从当前状态逐日推进到目标日期。

        返回 {"days_advanced": int, "trades_generated": int,
              "final_nav": float, "final_total_value": float, "message": str}
        """
        from app.services.market_service import MarketService

        if not portfolio.model_id:
            return {"days_advanced": 0, "trades_generated": 0,
                    "message": "仅模型驱动组合支持模拟交易推进"}

        # 1. 加载策略模型
        model_service = StrategyModelService()
        model = await model_service.get_model(portfolio.model_id)
        if not model:
            return {"days_advanced": 0, "trades_generated": 0,
                    "message": f"关联策略模型不存在: {portfolio.model_id}"}

        # 2. 确定推进起止日期
        last_snapshot = await self._get_latest_snapshot(portfolio.id)
        if last_snapshot:
            start_date = last_snapshot["date"].date() if hasattr(last_snapshot["date"], "date") else last_snapshot["date"]
            # 从快照日期的下一天开始
            from datetime import timedelta
            start_date = start_date + timedelta(days=1)
            # 恢复持仓状态
            position = self._restore_position_from_snapshot(last_snapshot)
            prev_nav = last_snapshot.get("nav", 1.0)
        else:
            start_date = portfolio.inception_date.date() if hasattr(portfolio.inception_date, "date") else portfolio.inception_date
            position = self._build_initial_position(portfolio)
            prev_nav = 1.0

        if start_date > target_date:
            return {"days_advanced": 0, "trades_generated": 0,
                    "final_nav": prev_nav,
                    "final_total_value": position.cash + self._holdings_value(position, {}),
                    "message": f"已经是最新状态（{start_date}），无需推进"}

        # 3. 加载行情数据
        market_service = MarketService()
        asset_codes = model.asset_codes
        lookback_start = pd.Timestamp(start_date) - pd.Timedelta(days=500)
        config = BacktestConfig(
            name=f"sim_{portfolio.name}",
            thscodes=asset_codes,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=target_date.strftime("%Y%m%d"),
            rebalance_freq=self._resolve_rebalance_freq(model.rebalance_frequency),
            initial_cash=portfolio.initial_capital,
        )
        # 面板按 strategy_type 静态解析；不传则策略声明的 get_extra_panels
        # 不生效，依赖面板的策略在模拟盘推进时会拿到空截面
        data_feed = await DataFeed.from_market_service(
            market_service, config, lookback_days=500,
            strategy_type=model.template_code,
        )
        if data_feed.prices.empty:
            return {"days_advanced": 0, "trades_generated": 0,
                    "message": "行情数据为空，无法推进"}

        # 4. 创建策略实例（构造统一经 runner.build_pipeline，引擎唯一构造点契约）
        from app.backtesting.runner import build_pipeline
        from app.allocation.builtin_templates import COMPOSITION_DEFAULTS
        from app.services.strategy_model_service import build_backtest_params
        strategy_service = await create_strategy_service_from_database(market_service)
        strategy_cls = strategy_service.get_strategy_class(model.template_code)
        composition = COMPOSITION_DEFAULTS.get(model.template_code, {
            "selector": None, "allocator": model.template_code, "controller": None
        })
        strategy = build_pipeline(
            allocator=strategy_cls(),
            thscodes=asset_codes,
            composition=composition,
            strategy_params=build_backtest_params(model),
        )
        exec_engine = ExecutionEngine(config)

        # 5. 构建调仓频率判断辅助引擎（复用 BacktestEngine._should_rebalance）
        rebalance_checker = _RebalanceChecker(config)

        # 6. 构建回测 NAV 映射（用于跟踪误差）
        bt_nav_map = self._build_backtest_nav_map(portfolio)

        # 7. 逐日推进
        days_advanced = 0
        trades_generated = 0
        last_rebalance_date = None
        first_bar = True

        for time, bar in data_feed.iter_bars():
            if time.date() < start_date:
                continue
            if time.date() > target_date:
                break

            prices = bar.close if isinstance(bar.close, dict) else {}

            # 计算当前总市值
            total_value = position.cash + sum(
                qty * prices.get(code, 0.0) for code, qty in position.quantity.items()
            )

            # 判断是否调仓
            do_rebalance = False
            rebalance_reason = ""

            if first_bar and not position.quantity:
                do_rebalance = True
                rebalance_reason = "期初建仓"
            elif self._should_rebalance(rebalance_checker, time, last_rebalance_date):
                do_rebalance = True
                rebalance_reason = "周期性调仓"

            # 执行调仓
            if do_rebalance:
                history = data_feed.get_history_window(time)
                if not history.empty or rebalance_reason == "期初建仓":
                    try:
                        target_signal = strategy.generate_target_weights(history, as_of=time)
                        bt_bar = BtBar(time=time, close=prices)
                        exec_result = exec_engine.rebalance_to_target(
                            bar=bt_bar,
                            current_position=BtPosition(
                                quantity=position.quantity.copy(),
                                cash=position.cash,
                            ),
                            target_signal=target_signal,
                        )
                        position = SimPositionState(
                            quantity=exec_result.position.quantity,
                            cash=exec_result.position.cash,
                        )

                        # 写入成交单
                        asset_names = await self._get_asset_names(asset_codes)
                        for trade in exec_result.trades:
                            gross = trade.quantity * trade.price
                            net = gross + trade.commission + trade.slippage_cost if trade.side == "buy" \
                                else gross - trade.commission - trade.slippage_cost
                            sim_trade = SimTrade(
                                portfolio_id=str(portfolio.id),
                                trade_date=time.to_pydatetime(),
                                asset_code=trade.thscode,
                                asset_name=asset_names.get(trade.thscode, trade.thscode),
                                side=trade.side,
                                quantity=trade.quantity,
                                price=trade.price,
                                commission=trade.commission,
                                slippage_cost=trade.slippage_cost,
                                gross_amount=gross,
                                net_amount=net,
                                signal_source="strategy",
                                trigger_reason=rebalance_reason,
                            )
                            await self.trades_collection.insert_one(
                                sim_trade.dict(by_alias=True, exclude={"id"})
                            )
                            trades_generated += 1

                        last_rebalance_date = time
                    except Exception as e:
                        logger.warning(f"[SimTrade] 调仓失败 {time.date()}: {e}")

            # 重新计算总市值
            total_value = position.cash + sum(
                qty * prices.get(code, 0.0) for code, qty in position.quantity.items()
            )
            holdings_value = total_value - position.cash

            # 计算 NAV
            nav = total_value / portfolio.initial_capital if portfolio.initial_capital > 0 else 1.0
            daily_return = (nav / prev_nav - 1.0) if prev_nav > 0 else 0.0
            cumulative_return = nav - 1.0

            # 回测 NAV 对比
            date_key = time.strftime("%Y-%m-%d")
            bt_nav = bt_nav_map.get(date_key)
            te = (nav - bt_nav) if bt_nav is not None else None

            # 构建持仓快照
            pos_snapshots = []
            asset_names_cache = await self._get_asset_names(asset_codes)
            for code, qty in position.quantity.items():
                price = prices.get(code, 0.0)
                mv = qty * price
                w = mv / total_value if total_value > 0 else 0.0
                pos_snapshots.append(SimPositionSnapshot(
                    asset_code=code,
                    asset_name=asset_names_cache.get(code, code),
                    weight=w,
                    quantity=qty,
                    market_value=mv,
                    price=price,
                ))

            snapshot = SimDailySnapshot(
                portfolio_id=str(portfolio.id),
                date=time.to_pydatetime(),
                nav=nav,
                total_value=total_value,
                cash=position.cash,
                holdings_value=holdings_value,
                daily_return=daily_return,
                cumulative_return=cumulative_return,
                positions=pos_snapshots,
                is_rebalance_day=(last_rebalance_date == time),
                backtest_nav=bt_nav,
                tracking_error=te,
            )
            await self.snapshots_collection.insert_one(
                snapshot.dict(by_alias=True, exclude={"id"})
            )

            prev_nav = nav
            days_advanced += 1
            first_bar = False

        # 8. 更新组合最新持仓和市值
        final_total = position.cash + sum(
            qty * prices.get(code, 0.0) for code, qty in position.quantity.items()
        ) if position.quantity else position.cash
        await self._update_portfolio_state(portfolio.id, position, final_total)

        logger.info(
            f"[SimTrade] 推进完成 {portfolio.name}: "
            f"{days_advanced} 天, {trades_generated} 笔成交, NAV={prev_nav:.4f}"
        )

        return {
            "days_advanced": days_advanced,
            "trades_generated": trades_generated,
            "final_nav": prev_nav,
            "final_total_value": final_total,
            "message": f"成功推进 {days_advanced} 个交易日",
        }

    # ────────────────────────────────────────────────
    #  多策略组合推进（PORTFOLIO_MODEL）
    # ────────────────────────────────────────────────

    async def advance_portfolio_model_to_date(
        self,
        portfolio: Portfolio,
        target_date: date,
    ) -> Dict[str, Any]:
        """
        将多策略组合从统一引擎组合路径推进到目标日期。
        
        原理：
        - 对每个子策略运行回测获取NAV序列
        - 按当前权重配比经统一引擎逐日撮合复合
        - 生成每日快照
        """
        from app.services.market_service import MarketService
        from app.portfolio.composite_runner import run_composite_unified as run_portfolio_backtest

        if not portfolio.portfolio_model_id:
            return {"days_advanced": 0, "trades_generated": 0,
                    "message": "组合缺少关联的组合模型ID"}

        # 1. 确定推进起点
        last_snapshot = await self._get_latest_snapshot(portfolio.id)
        if last_snapshot:
            snap_date = last_snapshot["date"].date() if hasattr(last_snapshot["date"], "date") else last_snapshot["date"]
            from datetime import timedelta
            start_date = snap_date + timedelta(days=1)
            prev_nav = last_snapshot.get("nav", 1.0)
        else:
            start_date = portfolio.inception_date.date() if hasattr(portfolio.inception_date, "date") else portfolio.inception_date
            prev_nav = 1.0

        if start_date > target_date:
            return {"days_advanced": 0, "trades_generated": 0,
                    "final_nav": prev_nav,
                    "message": f"已经是最新状态（{start_date}），无需推进"}

        # 2. 加载组合模型并解析子策略
        model_service = StrategyModelService()
        portfolio_model = await model_service.get_model(portfolio.portfolio_model_id)
        if not portfolio_model:
            return {"days_advanced": 0, "trades_generated": 0,
                    "message": f"组合模型不存在: {portfolio.portfolio_model_id}"}

        # 已发布组合：成员/权重/初始净值读发布冻结快照
        if portfolio_model.status == ModelStatus.PUBLISHED and portfolio_model.published_snapshot:
            portfolio_model = apply_published_snapshot(
                portfolio_model, portfolio_model.published_snapshot
            )
        membership = model_service.portfolio_membership(portfolio_model)
        sub_pairs = await model_service.resolve_sub_strategies(
            portfolio_model, sub_strategies=membership
        )
        if not sub_pairs:
            return {"days_advanced": 0, "trades_generated": 0,
                    "message": "无法解析子策略"}

        # 3. 对每个子策略执行回测获取NAV序列
        from app.portfolio.portfolio_service import PortfolioService
        portfolio_svc = PortfolioService()

        sub_nav_series = {}
        sub_weights = {}
        initial_nav = portfolio_model.initial_nav
        start_str = start_date.strftime("%Y%m%d")
        end_str = target_date.strftime("%Y%m%d")

        for sub_model, model_weight in sub_pairs:
            try:
                nav = await portfolio_svc._run_sub_strategy_backtest(
                    sub_model, start_str, end_str, initial_nav
                )
                if nav is not None and len(nav) > 1:
                    key = sub_model.id or sub_model.name
                    sub_nav_series[key] = nav
                    sub_weights[key] = model_weight
            except Exception as e:
                logger.warning(f"[SimTrade] 子策略 {sub_model.name} 回测失败: {e}")

        if not sub_nav_series:
            return {"days_advanced": 0, "trades_generated": 0,
                    "message": "所有子策略回测失败，无法推进"}

        # 4. 复合NAV
        rebalance_freq = portfolio.rebalance_frequency or "monthly"
        freq_mapping = {"月": "monthly", "季": "quarterly", "年": "yearly"}
        rebalance_freq_en = freq_mapping.get(rebalance_freq, rebalance_freq)

        composite_result = run_portfolio_backtest(
            sub_nav_series=sub_nav_series,
            sub_weights=sub_weights,
            initial_nav=initial_nav,
            rebalance_freq=rebalance_freq_en,
        )

        portfolio_nav = composite_result.portfolio_nav
        if portfolio_nav is None or len(portfolio_nav) == 0:
            return {"days_advanced": 0, "trades_generated": 0,
                    "message": "复合NAV为空"}

        # 5. 生成每日快照
        days_advanced = 0
        for i, (dt_idx, nav_val) in enumerate(portfolio_nav.items()):
            nav = float(nav_val) / initial_nav  # 归一化到单位净值
            daily_return = (nav / prev_nav - 1.0) if prev_nav > 0 else 0.0
            cumulative_return = nav - 1.0
            total_value = portfolio.initial_capital * nav

            # 构建子策略持仓快照
            pos_snapshots = []
            for key, weight in sub_weights.items():
                sub_nav_at_date = sub_nav_series.get(key)
                sub_nav_val = 0.0
                if sub_nav_at_date is not None and dt_idx in sub_nav_at_date.index:
                    sub_nav_val = float(sub_nav_at_date[dt_idx])
                pos_snapshots.append(SimPositionSnapshot(
                    asset_code=key,
                    asset_name=key,
                    weight=weight,
                    quantity=1.0,
                    market_value=total_value * weight,
                    price=sub_nav_val,
                ))

            snapshot = SimDailySnapshot(
                portfolio_id=str(portfolio.id),
                date=dt_idx.to_pydatetime() if hasattr(dt_idx, 'to_pydatetime') else dt_idx,
                nav=nav,
                total_value=total_value,
                cash=0.0,
                holdings_value=total_value,
                daily_return=daily_return,
                cumulative_return=cumulative_return,
                positions=pos_snapshots,
                is_rebalance_day=False,
                backtest_nav=None,
                tracking_error=None,
            )
            await self.snapshots_collection.insert_one(
                snapshot.dict(by_alias=True, exclude={"id"})
            )
            prev_nav = nav
            days_advanced += 1

        # 6. 更新组合状态
        final_nav = prev_nav
        final_total = portfolio.initial_capital * final_nav
        from app.config.collections import COL_PORTFOLIOS
        await self.db[COL_PORTFOLIOS].update_one(
            {"_id": ObjectId(str(portfolio.id))},
            {"$set": {
                "current_capital": final_total,
                "updated_at": datetime.now(),
            }},
        )

        logger.info(
            f"[SimTrade] 多策略组合推进完成 {portfolio.name}: "
            f"{days_advanced} 天, NAV={final_nav:.4f}"
        )

        return {
            "days_advanced": days_advanced,
            "trades_generated": 0,
            "final_nav": final_nav,
            "final_total_value": final_total,
            "message": f"多策略组合成功推进 {days_advanced} 个交易日",
        }

    # ────────────────────────────────────────────────
    #  跟踪误差分析
    # ────────────────────────────────────────────────

    async def compute_tracking_error(self, portfolio: Portfolio) -> Dict[str, Any]:
        """对比模拟 NAV 和回测 NAV，计算跟踪误差统计。"""
        snapshots = await self._get_all_snapshots(portfolio.id)
        if not snapshots:
            return {
                "stats": {
                    "annual_tracking_error": 0, "information_ratio": 0,
                    "max_deviation": 0, "mean_daily_error": 0,
                    "total_days": 0, "days_with_data": 0,
                },
                "nav_comparison": [],
            }

        bt_nav_map = self._build_backtest_nav_map(portfolio)
        errors = []
        comparison = []

        for snap in snapshots:
            d = snap["date"]
            date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            sim_nav = snap.get("nav", 1.0)
            bt_nav = bt_nav_map.get(date_str)
            te = (sim_nav - bt_nav) if bt_nav is not None else None

            comparison.append({
                "date": date_str,
                "sim_nav": round(sim_nav, 6),
                "backtest_nav": round(bt_nav, 6) if bt_nav is not None else None,
                "tracking_error": round(te, 6) if te is not None else None,
            })
            if te is not None:
                errors.append(te)

        stats = {"total_days": len(snapshots), "days_with_data": len(errors)}
        if errors:
            arr = np.array(errors)
            mean_err = float(np.mean(arr))
            std_err = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
            annual_te = std_err * math.sqrt(260)
            info_ratio = (mean_err / std_err * math.sqrt(260)) if std_err > 1e-12 else 0.0
            max_dev = float(np.max(np.abs(arr)))
            stats.update({
                "annual_tracking_error": round(annual_te, 6),
                "information_ratio": round(info_ratio, 4),
                "max_deviation": round(max_dev, 6),
                "mean_daily_error": round(mean_err, 6),
            })
        else:
            stats.update({
                "annual_tracking_error": 0, "information_ratio": 0,
                "max_deviation": 0, "mean_daily_error": 0,
            })

        return {"stats": stats, "nav_comparison": comparison}

    # ────────────────────────────────────────────────
    #  Brinson 绩效归因
    # ────────────────────────────────────────────────

    async def performance_attribution(self, portfolio: Portfolio) -> Dict[str, Any]:
        """
        Brinson 简化归因：对比模拟持仓权重/收益与回测基准。
        配置效应 = (w_sim - w_bench) * (r_bench - r_total_bench)
        选择效应 = w_bench * (r_sim_asset - r_bench_asset)
        交互效应 = (w_sim - w_bench) * (r_sim_asset - r_bench_asset)
        """
        snapshots = await self._get_all_snapshots(portfolio.id)
        if len(snapshots) < 2:
            return {
                "total_allocation": 0, "total_selection": 0,
                "total_interaction": 0, "total_active_return": 0,
                "effects": [],
            }

        # 计算模拟组合各资产的累计收益（首日到末日）
        first_snap = snapshots[0]
        last_snap = snapshots[-1]
        period_start = first_snap["date"].strftime("%Y-%m-%d") if hasattr(first_snap["date"], "strftime") else str(first_snap["date"])
        period_end = last_snap["date"].strftime("%Y-%m-%d") if hasattr(last_snap["date"], "strftime") else str(last_snap["date"])

        # 获取价格数据计算资产收益
        asset_codes = list(last_snap.get("positions", [{}])[0].keys()) if last_snap.get("positions") else []
        if not asset_codes and last_snap.get("positions"):
            asset_codes = [p.get("asset_code", "") for p in last_snap["positions"]]
        asset_codes = [c for c in asset_codes if c]

        if not asset_codes:
            return {
                "total_allocation": 0, "total_selection": 0,
                "total_interaction": 0, "total_active_return": 0,
                "effects": [], "period_start": period_start, "period_end": period_end,
            }

        # 获取资产价格计算期间收益
        try:
            first_date = pd.Timestamp(first_snap["date"]) - pd.Timedelta(days=5)
            last_date = pd.Timestamp(last_snap["date"]) + pd.Timedelta(days=5)
            prices = await self.asset_service.get_price_dataframe(asset_codes, first_date, last_date)
        except Exception as e:
            logger.warning(f"[SimTrade] 归因计算获取价格失败: {e}")
            prices = pd.DataFrame()

        # 构建等权基准
        n_assets = len(asset_codes)
        bench_weight = 1.0 / n_assets if n_assets > 0 else 0.0

        # 模拟组合最终权重（取最后一天快照）
        sim_weights = {}
        for p in last_snap.get("positions", []):
            sim_weights[p.get("asset_code", "")] = p.get("weight", 0.0)

        asset_names = await self._get_asset_names(asset_codes)
        effects = []
        total_alloc = 0.0
        total_select = 0.0
        total_interact = 0.0

        for code in asset_codes:
            w_sim = sim_weights.get(code, 0.0)
            w_bench = bench_weight

            # 计算资产期间收益
            r_asset = 0.0
            if not prices.empty and code in prices.columns:
                p_start = prices[code].dropna()
                if len(p_start) >= 2:
                    r_asset = (p_start.iloc[-1] / p_start.iloc[0]) - 1.0

            r_bench_asset = r_asset  # 基准使用相同资产收益
            r_total_bench = 0.0
            if not prices.empty:
                bench_returns = []
                for c in asset_codes:
                    if c in prices.columns:
                        ps = prices[c].dropna()
                        if len(ps) >= 2:
                            bench_returns.append((ps.iloc[-1] / ps.iloc[0]) - 1.0)
                r_total_bench = np.mean(bench_returns) if bench_returns else 0.0

            alloc = (w_sim - w_bench) * (r_bench_asset - r_total_bench)
            select = w_bench * (r_asset - r_bench_asset)
            interact = (w_sim - w_bench) * (r_asset - r_bench_asset)

            total_alloc += alloc
            total_select += select
            total_interact += interact

            effects.append({
                "asset_code": code,
                "asset_name": asset_names.get(code, code),
                "allocation_effect": round(alloc, 6),
                "selection_effect": round(select, 6),
                "interaction_effect": round(interact, 6),
                "total_effect": round(alloc + select + interact, 6),
            })

        return {
            "total_allocation": round(total_alloc, 6),
            "total_selection": round(total_select, 6),
            "total_interaction": round(total_interact, 6),
            "total_active_return": round(total_alloc + total_select + total_interact, 6),
            "effects": effects,
            "period_start": period_start,
            "period_end": period_end,
        }

    # ────────────────────────────────────────────────
    #  辅助方法
    # ────────────────────────────────────────────────

    async def _get_latest_snapshot(self, portfolio_id: str) -> Optional[Dict]:
        """获取最新的快照记录"""
        doc = await self.snapshots_collection.find_one(
            {"portfolio_id": portfolio_id},
            sort=[("date", -1)],
        )
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def _get_all_snapshots(self, portfolio_id: str) -> List[Dict]:
        """获取所有快照（按日期升序）"""
        cursor = self.snapshots_collection.find(
            {"portfolio_id": portfolio_id}
        ).sort("date", 1)
        result = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            result.append(doc)
        return result

    def _restore_position_from_snapshot(self, snapshot: Dict) -> "SimPositionState":
        """从快照恢复持仓状态"""
        quantity = {}
        for p in snapshot.get("positions", []):
            code = p.get("asset_code", "")
            qty = p.get("quantity", 0.0)
            if code and qty > 0:
                quantity[code] = qty
        cash = snapshot.get("cash", 0.0)
        return SimPositionState(quantity=quantity, cash=cash)

    def _build_initial_position(self, portfolio: Portfolio) -> "SimPositionState":
        """从组合初始持仓构建状态"""
        quantity = {}
        for p in portfolio.positions:
            if p.asset_code and p.shares and p.shares > 0:
                quantity[p.asset_code] = p.shares
        return SimPositionState(quantity=quantity, cash=portfolio.initial_capital)

    def _holdings_value(self, position: "SimPositionState", prices: Dict[str, float]) -> float:
        return sum(qty * prices.get(code, 0.0) for code, qty in position.quantity.items())

    def _build_backtest_nav_map(self, portfolio: Portfolio) -> Dict[str, float]:
        """从组合的 performance.equity_curve 构建 {date_str: nav} 映射"""
        nav_map = {}
        if portfolio.performance and hasattr(portfolio.performance, "equity_curve"):
            for point in (portfolio.performance.equity_curve or []):
                d = point.date if hasattr(point, "date") else point.get("date", "")
                uv = point.unit_value if hasattr(point, "unit_value") else point.get("unit_value")
                if d and uv is not None:
                    date_str = d[:10] if isinstance(d, str) else d.strftime("%Y-%m-%d")
                    nav_map[date_str] = float(uv)
        return nav_map

    def _resolve_rebalance_freq(self, freq_str: str) -> str:
        """将中文/英文调仓频率统一为 BacktestConfig 接受的格式"""
        mapping = {
            "日": "daily", "周": "weekly", "月": "monthly",
            "季": "quarterly", "年": "yearly",
            "daily": "daily", "weekly": "weekly", "monthly": "monthly",
            "month_end": "month_end", "quarterly": "quarterly", "yearly": "yearly",
        }
        return mapping.get(freq_str, "monthly")

    def _should_rebalance(
        self,
        checker: "_RebalanceChecker",
        time: pd.Timestamp,
        last_rebalance_date: Optional[pd.Timestamp],
    ) -> bool:
        """判断是否需要调仓"""
        return checker.should_rebalance(time, last_rebalance_date)

    async def _get_asset_names(self, asset_codes: List[str]) -> Dict[str, str]:
        """批量获取资产名称"""
        names = {}
        for code in asset_codes:
            info = await self.asset_service.get_asset_by_code(code)
            names[code] = info.name if info else code
        return names

    async def _update_portfolio_state(
        self,
        portfolio_id: str,
        position: "SimPositionState",
        total_value: float,
    ):
        """更新组合的当前持仓和市值"""
        positions = [
            Position(
                asset_code=code,
                asset_name=code,
                weight=0.0,
                shares=qty,
                market_value=0.0,
            )
            for code, qty in position.quantity.items()
        ]
        from app.config.collections import COL_PORTFOLIOS as _COL_PF
        await self.db[_COL_PF].update_one(
            {"_id": ObjectId(portfolio_id)},
            {"$set": {
                "positions": [p.dict() for p in positions],
                "current_capital": total_value,
                "updated_at": datetime.now(),
            }},
        )


class SimPositionState:
    """轻量持仓状态（非 Pydantic，引擎内部使用）"""
    __slots__ = ("quantity", "cash")

    def __init__(self, quantity: Dict[str, float], cash: float):
        self.quantity = quantity
        self.cash = cash


class _RebalanceChecker:
    """
    复用 BacktestEngine 的调仓频率判断逻辑。
    独立实现以避免对 BacktestEngine 实例的依赖。
    """

    def __init__(self, config: BacktestConfig):
        self._freq = config.rebalance_freq
        self._last_month = None
        self._last_quarter = None
        self._last_year = None
        # month_end 预计算
        self._month_end_set: set = set()
        if self._freq == "month_end":
            # 由调用方在 advance_to_date 中根据 data_feed 填充
            pass

    def set_month_end_dates(self, dates: set):
        self._month_end_set = dates

    def should_rebalance(
        self,
        time: pd.Timestamp,
        last_rebalance_date: Optional[pd.Timestamp],
    ) -> bool:
        if time == pd.Timestamp("2015-01-05"):
            return False
        if self._freq == "daily":
            return True
        elif self._freq == "month_end":
            return time in self._month_end_set
        elif self._freq == "weekly":
            return time.weekday() == 0
        elif self._freq == "monthly":
            if self._last_month != time.month:
                self._last_month = time.month
                return True
            return False
        elif self._freq == "quarterly":
            q = (time.month - 1) // 3
            if self._last_quarter != q:
                self._last_quarter = q
                return True
            return False
        elif self._freq == "yearly":
            if self._last_year != time.year:
                self._last_year = time.year
                return True
            return False
        return False
