# -*- coding: utf-8 -*-
"""
监控服务层 - 编排日常组合监控调仓流程

职责：
1. 管理组合监控状态（MongoDB）
2. 编排每日监控流程（损益更新、调仓执行、波动率监测）
3. 管理主观调仓指令
4. 提供查询接口（净值历史、持仓、绩效、信号状态）
"""

import uuid
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from loguru import logger
from bson import ObjectId

from app.config.database import Database
from app.models.monitor import (
    MonitorState, SubjectiveOverride,
    OverrideStatus
)
from app.monitor import config
from app.monitor.types import PortfolioState
from app.monitor.data_provider import MongoDataProvider, SyncDataProvider
from app.monitor.portfolio_tracker import PortfolioTracker
from app.monitor.engine_adapter import MonitorEngineAdapter
from app.monitor.signal_detector import SignalDetector
from app.monitor.report_generator import ReportGenerator
from app.monitor.volatility_calculator import VolatilityCalculator
from app.monitor.mongo_asset_codes import stored_price_code, canonical_price_code
from app.monitor.time_norm import normalize_calendar_timestamp, coerce_trade_dates
from app.monitor.monitor_runtime import (
    MonitorRuntimeConfig,
    monitor_runtime_from_model,
    resolve_asset_currency_for_monitor,
    slice_prices_df,
    live_effective_structured_params,
    normalize_strategy_asset_codes,
    live_effective_display_bundle,
    live_effective_asset_display_labels,
    config_baseline_eligible_strategy_dict,
)
from app.monitor.live_publish_log_scope import merge_parameters_with_top_level_windows
from app.monitor.manual_preset import ManualPresetMixin
from app.monitor.rebalance_planning import RebalancePlanningMixin
from app.monitor.daily_stepper import DailyStepperMixin
from app.monitor.monitor_query import MonitorQueryMixin
from app.services.strategy_model_service import StrategyModelService
from app.services.asset_service import AssetService


class MonitorService(
    ManualPresetMixin,
    RebalancePlanningMixin,
    DailyStepperMixin,
    MonitorQueryMixin,
):
    """监控服务 - 编排整个日常监控调仓流程

    方法群按职责拆分至 Mixin（app/monitor/ 下）：
    - ManualPresetMixin：主观配置预设调仓步进与观察指标
    - RebalancePlanningMixin：调仓映射构建与权重规划
    - DailyStepperMixin：单日推演（步骤 A-F）
    - MonitorQueryMixin：读取查询接口与日报持久化
    """
    
    def __init__(self):
        self._db = None
        # 核心组件
        self.tracker = PortfolioTracker()
        self.detector = SignalDetector()
        self.reporter = ReportGenerator()
        self.vol_calculator = VolatilityCalculator()
        # 三层引擎适配器（新路径，与回测一致）
        self._engine_adapter: Optional[MonitorEngineAdapter] = None
        # 数据提供者
        self._async_provider = None
        self._sync_provider = None
        # 单次请求内实盘策略监控的运行时参数（由 monitor_id 对应模型解析）
        self._monitor_runtime: Optional[MonitorRuntimeConfig] = None
        self._merged_monitor_params: Dict[str, Any] = {}
        # 研究员策略代码（sharpe_18 / hybrid_12），用于路由独立引擎
        self._researcher_code: Optional[str] = None

    def _log_monitor_fx_snapshot(self, as_of_date: str, fx_df: pd.DataFrame) -> None:
        """
        监控一次运行结束后打印：各资产标准代码、（若配置后缀）Mongo 资产码、计价币种、
        与 PortfolioTracker.get_asset_fx_rate 一致的当日使用汇率（含向前查找最近有效日）。
        """
        if fx_df is None or fx_df.empty:
            logger.warning("监控汇率快照跳过：fx_df 为空 as_of={}", as_of_date)
            return
        d = str(as_of_date)[:10]
        logger.info("========== 监控汇率快照 as_of={} ==========", d)
        logger.info(
            "列说明: 币种=计价货币; 汇率=当日选用的外汇报价(与 fx_rates / fx.xlsx 一致); CNH=1.0"
        )
        for asset in self.tracker.asset_list:
            canon = config.ASSET_NAME_TO_CODE.get(asset, "")
            stored = stored_price_code(canon) if canon else canon
            ccy = resolve_asset_currency_for_monitor(asset)
            rate = self.tracker.get_asset_fx_rate(asset, d, fx_df)
            if stored and stored != canon:
                logger.info(
                    "  资产={} | 标准码={} | Mongo码={} | 币种={} | 汇率={}",
                    asset,
                    canon,
                    stored,
                    ccy,
                    rate,
                )
            else:
                logger.info(
                    "  资产={} | 代码={} | 币种={} | 汇率={}",
                    asset,
                    canon,
                    ccy,
                    rate,
                )
        logger.info("========== 监控汇率快照 结束 ==========")

    @staticmethod
    def _is_strategy_model_monitor_id(monitor_id: str) -> bool:
        try:
            ObjectId(monitor_id)
        except Exception:
            return False
        return True

    def _log_asset_data_quality(self, prices_df, label: str = "监控") -> None:
        """打印各资产的代码、名称、有效行情区间，用于校验数据完整性。"""
        if prices_df is None or getattr(prices_df, "empty", True):
            logger.warning(f"[{label}] 行情 DataFrame 为空")
            return

        asset_list = list(self.tracker.asset_list)
        rt = self._monitor_runtime
        # 获取 code→name 映射
        asset_names = {}
        if rt and getattr(rt, "asset_names", None):
            asset_names = dict(rt.asset_names)

        logger.info(f"[{label}] 资产行情数据校验（共 {len(asset_list)} 个资产）：")
        logger.info(f"  {'代码':<16} {'名称':<12} {'有效起始':<12} {'有效结束':<12} {'非空天数':>8}")
        logger.info(f"  {'-'*16} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")

        for code in asset_list:
            # 解析名称
            name = asset_names.get(code, "")
            if not name:
                name = config.ASSET_CODE_TO_NAME.get(code, "")
            if not name:
                name = config.SHARPE_CODE_TO_NAME.get(code, "")
            if not name:
                name = "(未映射)"

            # 行情数据区间
            if code in prices_df.columns:
                series = prices_df[code].dropna()
                if len(series) > 0:
                    first_date = str(series.index[0])[:10]
                    last_date = str(series.index[-1])[:10]
                    count = len(series)
                else:
                    first_date = "(全空)"
                    last_date = "(全空)"
                    count = 0
            else:
                first_date = "(列缺失)"
                last_date = "(列缺失)"
                count = 0

            logger.info(f"  {code:<16} {name:<12} {first_date:<12} {last_date:<12} {count:>8}")

    async def _resolve_monitored_strategy(self, monitor_id: str) -> Optional[Dict[str, Any]]:
        """尝试从 monitored_strategies 集合解析 monitor_id。"""
        if not self._is_strategy_model_monitor_id(monitor_id):
            return None
        from app.services.monitored_strategy_service import MonitoredStrategyService
        svc = MonitoredStrategyService()
        return await svc.get(monitor_id)

    def _build_rt_from_researcher(self, code: str) -> Optional["MonitorRuntimeConfig"]:
        """从研究员策略构建最小 MonitorRuntimeConfig（供 tracker.configure 使用）。"""
        from app.monitor.researcher_strategies import get_researcher_strategy
        strategy = get_researcher_strategy(code)
        if strategy is None:
            return None
        from app.monitor.monitor_runtime import MonitorRuntimeConfig
        params = strategy.strategy_params or {}
        return MonitorRuntimeConfig(
            asset_list=strategy.asset_codes,
            target_vol=params.get("target_vol", 0.05),
            vol_trigger_threshold=params.get("vol_trigger_threshold", 0.06),
            max_leverage=params.get("max_total_leverage", 4.0),
            weight_caps=strategy.weight_caps or {},
            selector_type=params.get("selector_type"),
            strategy_params=params,
            asset_names=strategy.asset_name_map or None,
        )

    async def _prepare_monitor_run(self, monitor_id: str) -> None:
        """解析实盘模型运行时配置并配置 PortfolioTracker；无实盘模型时回退全局 config。"""
        self._monitor_runtime = None
        self._merged_monitor_params = {}
        self._engine_adapter = None
        self._researcher_code = None
        self.tracker.configure(None)

        # 优先从 monitored_strategies 解析
        ms_doc = await self._resolve_monitored_strategy(monitor_id)
        if ms_doc:
            source_type = ms_doc.get("source_type")
            source_ref = ms_doc.get("source_ref", "")
            if source_type == "researcher":
                rt = self._build_rt_from_researcher(source_ref)
                if rt:
                    self._monitor_runtime = rt
                    self._researcher_code = source_ref
                    self.tracker.configure(rt)
                    self._engine_adapter = MonitorEngineAdapter.from_researcher_strategy(source_ref)
                return
            elif source_type in ("system_strategy", "portfolio"):
                # source_ref 是 strategy_models._id
                monitor_id = source_ref
            # 其他来源回退

        if not self._is_strategy_model_monitor_id(monitor_id):
            return
        svc = StrategyModelService()
        model = await svc.get_model(monitor_id)
        if not model:
            return
        self._merged_monitor_params = merge_parameters_with_top_level_windows(
            model, model.parameters or {}
        )
        # 确保 asset_names 已填充（从资产主数据查询）
        await self._ensure_model_asset_names(model)
        rt = monitor_runtime_from_model(model)
        if rt is None:
            return
        self._monitor_runtime = rt
        self.tracker.configure(rt)

    # ============================================================
    # 组合监控：复用回测管线（t8）
    # ============================================================

    async def _resolve_portfolio_source(self, monitor_id: str) -> Optional[Dict[str, Any]]:
        """若 monitor_id 对应 source_type=portfolio 的监测策略，返回组合配置；否则 None。

        Returns:
            {'model_id': 组合模型ID, 'initial_nav': float, 'rebalance_freq': str} 或 None
        """
        ms_doc = await self._resolve_monitored_strategy(monitor_id)
        if not ms_doc or ms_doc.get("source_type") != "portfolio":
            return None
        model_id = ms_doc.get("source_ref", "")
        if not model_id:
            return None
        svc = StrategyModelService()
        model = await svc.get_model(model_id)
        if not model or not getattr(model, "is_portfolio", False):
            return None
        snap = getattr(model, "live_snapshot", None) or {}
        return {
            "model_id": model_id,
            "initial_nav": float(snap.get("initial_nav") or config.BASE_VALUE),
            "rebalance_freq": snap.get("rebalance_frequency") or "monthly",
        }

    async def _run_portfolio_backtest_monitor(
        self,
        monitor_id: str,
        portfolio_info: Dict[str, Any],
        start_date: str,
        end_date,
    ) -> dict:
        """复用组合回测管线运行组合监控，并将结果落库为 MonitorState。

        监控与回测使用同一引擎与口径，保证二者结果一致（monitor == backtest）。

        Args:
            start_date: YYYY-MM-DD
            end_date: pd.Timestamp / datetime / 'YYYY-MM-DD' / 'YYYYMMDD'
        """
        from app.monitor.portfolio_backtest_monitor import (
            run_portfolio_monitor_pipeline,
            build_monitor_state_fields,
        )
        from app.models.monitor import MonitorState

        start_yyyymmdd = str(start_date).strip()[:10].replace("-", "")
        end_ts = pd.Timestamp(end_date)
        end_yyyymmdd = end_ts.strftime("%Y%m%d")

        logger.info(
            f"[组合监控] 复用回测管线: model={portfolio_info['model_id']}, "
            f"{start_yyyymmdd} ~ {end_yyyymmdd}, initial_nav={portfolio_info['initial_nav']}"
        )

        pipeline = await run_portfolio_monitor_pipeline(
            portfolio_model_id=portfolio_info["model_id"],
            start_date=start_yyyymmdd,
            end_date=end_yyyymmdd,
            initial_nav=portfolio_info["initial_nav"],
            rebalance_freq=portfolio_info["rebalance_freq"],
            commission_rate=0.0,
            slippage=0.0,
        )

        fields = build_monitor_state_fields(
            monitor_id=monitor_id,
            strategy_model_id=portfolio_info["model_id"],
            pipeline=pipeline,
            initial_nav=portfolio_info["initial_nav"],
        )
        state = MonitorState(**fields)
        await self.save_state(state)

        perf = pipeline.get("performance")
        annual_return = getattr(perf, "annual_return", None) if perf else None
        logger.info(
            f"[组合监控] 完成: 最终日期={fields['date']}, 净值={fields['nav']:.2f}, "
            f"调仓次数={len(fields['event_log'])}"
        )
        return {
            "monitor_id": monitor_id,
            "date": fields["date"],
            "nav": fields["nav"],
            "day_count": fields["day_count"],
            "rebalance_count": len(fields["event_log"]),
            "annual_return": annual_return,
        }

    async def _runtime_for_reads(self, monitor_id: str) -> Optional[MonitorRuntimeConfig]:
        """读接口（持仓/信号等）按 monitor_id 解析运行时参数，无缓存。"""
        # 优先从 monitored_strategies 解析
        ms_doc = await self._resolve_monitored_strategy(monitor_id)
        if ms_doc:
            source_type = ms_doc.get("source_type")
            source_ref = ms_doc.get("source_ref", "")
            if source_type == "researcher":
                return self._build_rt_from_researcher(source_ref)
            elif source_type in ("system_strategy", "portfolio"):
                monitor_id = source_ref

        if not self._is_strategy_model_monitor_id(monitor_id):
            return None
        svc = StrategyModelService()
        model = await svc.get_model(monitor_id)
        if not model:
            return None
        # 确保 asset_names 已填充（从资产主数据查询）
        await self._ensure_model_asset_names(model)
        return monitor_runtime_from_model(model)

    async def _ensure_model_asset_names(self, model: Any) -> None:
        """确保模型的 asset_names 已填充；若为空则从 assets 主数据查询 code→name 映射。"""
        an = getattr(model, "asset_names", None)
        if isinstance(an, dict) and an:
            return  # 已有名称映射
        codes = getattr(model, "asset_codes", None) or []
        if not codes:
            return
        from app.services.asset_service import AssetService
        svc = AssetService()
        names: Dict[str, str] = {}
        for code in codes:
            if code is None:
                continue
            s = str(code).strip()
            if not s:
                continue
            info = await svc.get_asset_by_code(s)
            if info:
                names[s] = info.name
        model.asset_names = names

    async def _asset_master_names_by_code(
        self, model: Optional[Any], position_keys: List[str]
    ) -> Dict[str, str]:
        """资产主数据 code -> name，含 position 键及 canonical 去后缀键，供展示名解析。"""
        from app.services.asset_service import AssetService

        svc = AssetService()
        codes: set[str] = set()
        if model is not None:
            for c in getattr(model, "asset_codes", None) or []:
                if c is None:
                    continue
                s = str(c).strip()
                if s:
                    codes.add(s)
                    codes.add(canonical_price_code(s))
        for k in position_keys:
            if k is None:
                continue
            s = str(k).strip()
            if not s:
                continue
            codes.add(s)
            codes.add(canonical_price_code(s))
        out: Dict[str, str] = {}
        for c in codes:
            if not c:
                continue
            info = await svc.get_asset_by_code(c)
            if info is not None and getattr(info, "name", None):
                out[c] = info.name
        return out

    @staticmethod
    def _asset_keys_for_positions_attribution(
        runtime_list: List[str],
        positions_cny: Optional[Dict[str, Any]],
        target_weights: Optional[Dict[str, Any]],
    ) -> List[str]:
        """
        合并「运行时资产列」与状态中实际有持仓/权重的键。
        解决 Mongo 里 positions_cny、target_weights 仍为旧键（如中文名）而 runtime 为行情 code 时，
        读接口权重全 0、饼图与归因无数据的问题。
        """
        pc = positions_cny or {}
        tw = target_weights or {}

        def _f(v: Any) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        def _alive(k: str) -> bool:
            return abs(_f(pc.get(k, 0.0))) > 1e-12 or abs(_f(tw.get(k, 0.0))) > 1e-12

        seen: set[str] = set()
        out: List[str] = []
        for a in runtime_list:
            s = str(a).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        for k in list(pc.keys()) + list(tw.keys()):
            if k is None:
                continue
            sk = str(k).strip()
            if not sk or sk in seen:
                continue
            if _alive(sk):
                seen.add(sk)
                out.append(sk)
        return out
    
    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db
    
    @property
    def states_collection(self):
        from app.config.collections import COL_MONITOR_STATES
        return self.db[COL_MONITOR_STATES]
    
    @property
    def overrides_collection(self):
        from app.config.collections import COL_SUBJECTIVE_OVERRIDES
        return self.db[COL_SUBJECTIVE_OVERRIDES]
    
    @property
    def reports_collection(self):
        from app.config.collections import COL_MONITOR_DAILY_REPORTS
        return self.db[COL_MONITOR_DAILY_REPORTS]
    
    @property
    def async_provider(self):
        if self._async_provider is None:
            self._async_provider = MongoDataProvider()
        return self._async_provider
    
    @property
    def sync_provider(self):
        if self._sync_provider is None:
            self._sync_provider = SyncDataProvider()
        return self._sync_provider

    # ============================================================
    # 状态管理
    # ============================================================
    
    async def get_state(self, monitor_id: str = "default") -> Optional[MonitorState]:
        """从 MongoDB monitor_states 集合获取当前监控状态"""
        doc = await self.states_collection.find_one({"monitor_id": monitor_id})
        if doc:
            return MonitorState.from_dict(doc)
        return None
    
    async def save_state(self, state: MonitorState) -> None:
        """保存状态到 MongoDB（upsert by monitor_id）"""
        state.updated_at = datetime.now()
        state_dict = state.to_dict()
        await self.states_collection.replace_one(
            {"monitor_id": state.monitor_id},
            state_dict,
            upsert=True
        )
        logger.info(f"监控状态已保存: {state.monitor_id}, 日期: {state.date}, 净值: {state.nav:.2f}")
    
    async def create_initial_state(
        self, monitor_id: str = "default", asset_list: Optional[List[str]] = None
    ) -> MonitorState:
        """创建初始状态（空状态，用于 run_init）"""
        assets = list(asset_list) if asset_list else list(config.ASSET_LIST)
        state = MonitorState(
            monitor_id=monitor_id,
            date=config.BASE_DATE,
            nav=config.BASE_VALUE,
            nav_base=config.BASE_VALUE,
            day_count=0,
            positions_cny={asset: 0.0 for asset in assets},
            positions_local={asset: 0.0 for asset in assets},
            apl_local={asset: 0.0 for asset in assets},
            target_weights={asset: 0.0 for asset in assets},
            last_rebalance_fx={asset: 1.0 for asset in assets},
            # 传统持仓模型字段（任务#11）：主观策略首日全现金起步。
            cash=float(config.BASE_VALUE),
            quantities={},
            last_prices={},
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        return state
    
    def _state_to_portfolio_state(self, state: MonitorState) -> PortfolioState:
        """将 MonitorState (Pydantic) 转换为 PortfolioState (dataclass)"""
        ps = PortfolioState(
            date=state.date,
            nav=state.nav,
            nav_base=state.nav_base,
            positions_cny=dict(state.positions_cny),
            positions_local=dict(state.positions_local),
            apl_local=dict(state.apl_local),
            positions_cny_base=dict(getattr(state, 'positions_cny_base', {}) or {}),
            target_weights=dict(state.target_weights),
            last_rebalance_date=state.last_rebalance_date or state.date,
            last_rebalance_fx=dict(state.last_rebalance_fx),
            pending_rebalance=dict(state.pending_rebalance) if state.pending_rebalance else None,
            nav_history=list(state.nav_history),
            total_trading_cost=state.total_trading_cost,
            total_replication_cost=state.total_replication_cost,
            vol_reset_count=state.vol_reset_count,
            day_count=state.day_count,
            trade_day_count=int(getattr(state, 'trade_day_count', 0) or 0),
            event_log=list(state.event_log),
            # 传统持仓模型字段（任务#11/#12）
            cash=float(getattr(state, 'cash', 0.0) or 0.0),
            quantities=dict(getattr(state, 'quantities', {}) or {}),
            last_prices=dict(getattr(state, 'last_prices', {}) or {}),
        )
        # 诊断日志：识别遗留资产（state 中非零但不在当前 tracker.asset_list 中）
        # 后续 PortfolioTracker 会通过 _active_assets 覆盖这些资产进入 NAV / 调仓清算，
        # 在下一次调仓日被清零。
        try:
            current_universe = set(self.tracker.asset_list or [])
            stale = []
            for a, v in (ps.positions_cny or {}).items():
                try:
                    if abs(float(v)) > 1e-9 and a not in current_universe:
                        stale.append(a)
                except (TypeError, ValueError):
                    continue
            if stale:
                logger.debug(
                    "检测到遗留资产持仓（不在当前策略 asset_list 中）：{} 个资产={}；继续参与 NAV 计算，调仓日自动清算。",
                    len(stale), stale
                )
        except Exception as exc:
            logger.debug("遗留资产诊断跳过：{}", exc)
        return ps
    
    def _portfolio_state_to_state(self, ps: PortfolioState, monitor_id: str, 
                                   original: Optional[MonitorState] = None) -> MonitorState:
        """将 PortfolioState (dataclass) 转换为 MonitorState (Pydantic)"""
        if original:
            original.date = ps.date
            original.nav = ps.nav
            original.nav_base = ps.nav_base
            original.positions_cny = ps.positions_cny
            original.positions_local = ps.positions_local
            original.apl_local = ps.apl_local
            original.positions_cny_base = dict(getattr(ps, 'positions_cny_base', {}) or {})
            original.target_weights = ps.target_weights
            original.last_rebalance_date = ps.last_rebalance_date
            original.last_rebalance_fx = ps.last_rebalance_fx
            original.pending_rebalance = ps.pending_rebalance
            original.nav_history = ps.nav_history
            original.total_trading_cost = ps.total_trading_cost
            original.total_replication_cost = ps.total_replication_cost
            original.vol_reset_count = ps.vol_reset_count
            original.day_count = ps.day_count
            original.trade_day_count = int(getattr(ps, 'trade_day_count', 0) or 0)
            original.event_log = ps.event_log
            # 传统持仓模型字段（任务#11/#12）
            original.cash = float(getattr(ps, 'cash', 0.0) or 0.0)
            original.quantities = dict(getattr(ps, 'quantities', {}) or {})
            original.last_prices = dict(getattr(ps, 'last_prices', {}) or {})
            original.updated_at = datetime.now()
            return original
        
        return MonitorState(
            monitor_id=monitor_id,
            date=ps.date,
            nav=ps.nav,
            nav_base=ps.nav_base,
            day_count=ps.day_count,
            trade_day_count=int(getattr(ps, 'trade_day_count', 0) or 0),
            positions_cny=ps.positions_cny,
            positions_local=ps.positions_local,
            apl_local=ps.apl_local,
            positions_cny_base=dict(getattr(ps, 'positions_cny_base', {}) or {}),
            target_weights=ps.target_weights,
            last_rebalance_date=ps.last_rebalance_date,
            last_rebalance_fx=ps.last_rebalance_fx,
            pending_rebalance=ps.pending_rebalance,
            total_trading_cost=ps.total_trading_cost,
            total_replication_cost=ps.total_replication_cost,
            vol_reset_count=ps.vol_reset_count,
            nav_history=ps.nav_history,
            event_log=ps.event_log,
            # 传统持仓模型字段（任务#11/#12）
            cash=float(getattr(ps, 'cash', 0.0) or 0.0),
            quantities=dict(getattr(ps, 'quantities', {}) or {}),
            last_prices=dict(getattr(ps, 'last_prices', {}) or {}),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

    async def _capture_performance_basis_for_monitor(self, monitor_id: str) -> Optional[Dict[str, Any]]:
        """
        初始化完成时写入 monitor_states.performance_basis：
        与「准入策略」接口同口径，用于解释下方净值/绩效对应的实盘配置。
        """
        ts = datetime.now(timezone.utc).isoformat()
        if not self._is_strategy_model_monitor_id(monitor_id):
            asset_svc = AssetService()
            baseline_asset_names: Dict[str, str] = {}
            for nm in config.ASSET_LIST:
                code = config.ASSET_NAME_TO_CODE.get(nm)
                if not code:
                    continue
                info = await asset_svc.get_asset_by_code(code)
                baseline_asset_names[code] = info.name if info else code
            d = config_baseline_eligible_strategy_dict(baseline_asset_names)
            d["captured_at"] = ts
            d["source"] = "monitor_init"
            d["note"] = "与 app/monitor/config.py 及 monitor_id=default 一致"
            return d

        svc = StrategyModelService()
        model = await svc.get_model(monitor_id)
        if not model:
            return None
        asset_svc = AssetService()
        asset_names: Dict[str, str] = {}
        for code in model.asset_codes or []:
            if code is None:
                continue
            s = str(code).strip()
            if not s:
                continue
            info = await asset_svc.get_asset_by_code(s)
            if info:
                asset_names[s] = info.name
        codes_list = normalize_strategy_asset_codes(getattr(model, "asset_codes", None))
        summary, assets = live_effective_display_bundle(
            model.live_publish_enabled,
            model.live_snapshot or {},
            model.live_volatility_threshold,
            current_parameters=model.parameters,
            current_asset_codes=codes_list,
            asset_names=asset_names,
            published_only=True,
        )
        labels = live_effective_asset_display_labels(assets, asset_names)
        le_params = live_effective_structured_params(
            model.live_publish_enabled,
            model.live_snapshot or {},
            model.live_volatility_threshold,
            current_parameters=model.parameters,
            current_asset_codes=codes_list,
            model_for_selection=model,
            published_only=True,
        )
        return {
            "live_version": model.live_version,
            "live_effective_summary": summary,
            "live_effective_assets": assets,
            "live_effective_asset_labels": labels,
            "live_effective_params": le_params,
            "is_config_baseline": False,
            "captured_at": ts,
            "source": "monitor_init",
            "note": "净值与绩效指标基于「最近一次初始化」时的策略与实盘快照；若之后已改参或再次实盘发布但未重新初始化，可能与页面顶部当前实盘生效参数不一致。",
        }

    # ============================================================
    # 核心运行
    # ============================================================
    
    async def run_init(
        self,
        monitor_id: str = "default",
        start_date: str = None,
        manual_preset_step: bool = False,
    ) -> dict:
        """
        初始化运行：从指定日期（默认基日）逐日推演到数据最新日期
        
        Args:
            monitor_id: 监控实例 ID
            start_date: 自定义启动日期，格式 YYYY-MM-DD，默认使用 config.BASE_DATE
            manual_preset_step: 主观配置策略时，在每档预设调仓日当日推演完成后暂停并落库，便于查看绩效后再用「运行监控」续跑
        """
        # 确定实际启动日期
        actual_start_date = start_date or config.BASE_DATE
        logger.info(f"初始化模式开始: monitor_id={monitor_id}, start_date={actual_start_date}")

        # ── 组合（portfolio）监控：复用组合回测管线，保证监控与回测一致 ──
        portfolio_info = await self._resolve_portfolio_source(monitor_id)
        if portfolio_info:
            latest_ts = await self.async_provider.get_latest_date()
            return await self._run_portfolio_backtest_monitor(
                monitor_id, portfolio_info,
                start_date=str(actual_start_date), end_date=latest_ts,
            )

        await self._prepare_monitor_run(monitor_id)
        
        # 1. 创建初始状态
        mongo_state = await self.create_initial_state(
            monitor_id, asset_list=list(self.tracker.asset_list)
        )
        ps = self._state_to_portfolio_state(mongo_state)
        
        # 2. 加载全部数据（按当前策略运行时资产宇宙，可为 12 类的真子集）
        prices_df = await self.async_provider.load_prices(
            asset_columns=list(self.tracker.asset_list),
        )
        prices_df = slice_prices_df(prices_df, self._monitor_runtime)
        self._log_asset_data_quality(prices_df, label="初始化")
        fx_df = await self.async_provider.load_fx()
        trade_dates = await self.async_provider.load_trade_dates()
        trade_dates = coerce_trade_dates(trade_dates, prices_df)
        
        if prices_df.empty:
            raise ValueError("价格数据为空，无法初始化")
        
        # ── 研究员策略独立引擎路径（不走通用 Pipeline / 预计算权重） ──
        if self._researcher_code in ('sharpe_18', 'hybrid_12'):
            if self._researcher_code == 'sharpe_18':
                return await self._run_init_sharpe18_standalone(
                    monitor_id, mongo_state, ps, prices_df, fx_df, trade_dates,
                    backtest_start=actual_start_date,
                )
            return await self._run_init_hybrid12_standalone(
                monitor_id, mongo_state, ps, prices_df, fx_df, trade_dates,
                backtest_start=actual_start_date,
            )

        # 3. 异步加载预计算权重（如果是 sharpe 选择器）
        precomputed_weights = await self._async_load_precomputed_weights(
            prices_df, rt=self._monitor_runtime
        )
        
        # 4. 构建月末调仓映射表
        monthly_rebalance_map = self._build_monthly_rebalance_map(
            prices_df,
            trade_dates,
            config.SKIP_EXCLUDED_DATES,
            rt=self._monitor_runtime,
            merged_params=self._merged_monitor_params,
            precomputed_weights=precomputed_weights,
        )
        monthly_rebalance_dates = set(monthly_rebalance_map.keys())
        vol_reset_execute_dates = set()
        
        logger.info(
            f"调仓执行日映射: {len(monthly_rebalance_dates)} 个"
            + (
                "（主观预设日）"
                if self._monitor_runtime
                and getattr(self._monitor_runtime, "manual_allocation_mode", False)
                else "（混合动量月末 T+2）"
            )
        )
        
        # 4. 确定处理日期范围（使用实际启动日期）
        base_date_ts = normalize_calendar_timestamp(actual_start_date)
        latest_date = prices_df.index.max()
        processing_dates = prices_df.index[prices_df.index >= base_date_ts].tolist()
        if not processing_dates:
            raise ValueError(
                f"启动日 {actual_start_date} 之后无可用交易日（行情截止 "
                f"{latest_date.strftime('%Y-%m-%d') if hasattr(latest_date, 'strftime') else latest_date}）"
            )
        # 与回测一致：若启动日非交易日，首个处理日才触发步骤A（初始化持仓），否则会出现全程无持仓、净值恒为基准
        aligned_start_date = processing_dates[0].strftime("%Y-%m-%d")
        if aligned_start_date != str(actual_start_date).strip()[:10]:
            logger.info(
                f"启动日已对齐到首个交易日: 请求={actual_start_date}, 策略初始化日={aligned_start_date}"
            )

        logger.info(
            f"处理日期范围: {processing_dates[0].strftime('%Y-%m-%d')} ~ "
            f"{processing_dates[-1].strftime('%Y-%m-%d')}, 共 {len(processing_dates)} 个交易日"
        )
        
        # 5. 逐日处理
        prev_nav = None
        pending_overrides = await self._get_pending_overrides(monitor_id)
        step_mode = self._manual_preset_step_active(
            manual_preset_step, self._monitor_runtime
        )
        
        # 构建月度调仓信号日期集合（与原型 monthly_signal_dates_set 对齐）
        monthly_signal_dates = {
            normalize_calendar_timestamp(v['calc_date'])
            for v in monthly_rebalance_map.values()
        }
        # 波动率触发信号日期集合（在主循环中逐步积累）
        vol_signal_dates = set()
        
        for i, date in enumerate(processing_dates):
            date_str = date.strftime('%Y-%m-%d')
            
            result = self._process_single_day(
                ps, date_str, prices_df, fx_df, trade_dates,
                monthly_rebalance_map, monthly_rebalance_dates,
                vol_reset_execute_dates, pending_overrides, prev_nav,
                base_date=aligned_start_date,
                rt=self._monitor_runtime,
                monthly_signal_dates=monthly_signal_dates,
                vol_signal_dates=vol_signal_dates,
            )
            
            # 更新波动率重置执行日期集合
            if result.get('vol_reset_triggered'):
                exec_date = result.get('vol_reset_execute_date')
                if exec_date:
                    vol_reset_execute_dates.add(
                        normalize_calendar_timestamp(exec_date)
                    )
                # 记录波动率触发信号日期（用于后续“触发-执行间信号”检查）
                vol_signal_dates.add(date)
            
            prev_nav = ps.nav
            if step_mode:
                await self._save_daily_report(monitor_id, result)
            
            if (i + 1) % 100 == 0:
                logger.info(f"进度: {i+1}/{len(processing_dates)} ({date_str}) NAV={ps.nav:.2f}")
            
            if step_mode and self._should_pause_after_manual_preset_day(
                i, processing_dates, monthly_rebalance_dates
            ):
                final_state = self._portfolio_state_to_state(ps, monitor_id, mongo_state)
                final_state.performance_basis = await self._capture_performance_basis_for_monitor(
                    monitor_id
                )
                next_j = self._first_future_manual_preset_index(
                    processing_dates, monthly_rebalance_dates, i
                )
                next_preset_str = (
                    processing_dates[next_j].strftime("%Y-%m-%d")
                    if next_j is not None
                    else None
                )
                has_more = self._manual_preset_step_pending_after_pause(i, processing_dates)
                self._set_manual_preset_step_flags(final_state, has_more, next_preset_str)
                await self.save_state(final_state)
                self._log_monitor_fx_snapshot(final_state.date, fx_df)
                logger.info(
                    f"初始化主观步进暂停: 调仓日当日已推演截至={final_state.date}, "
                    f"下一预设调仓日={next_preset_str or '（区间内无）'}"
                )
                out = self._manual_preset_step_pause_payload(
                    ps, processing_dates, monthly_rebalance_dates, i, result
                )
                out.update(
                    {
                        "monitor_id": monitor_id,
                        "message": "主观预设调仓步进：已完成本档调仓日当日推演，请查看绩效后使用「运行监控」或「继续执行」续跑",
                    }
                )
                return out
        
        # 6. 保存最终状态（附带绩效解释：初始化时刻的实盘参数快照）
        final_state = self._portfolio_state_to_state(ps, monitor_id, mongo_state)
        final_state.performance_basis = await self._capture_performance_basis_for_monitor(monitor_id)
        self._set_manual_preset_step_flags(final_state, False)
        await self.save_state(final_state)
        
        logger.info(f"初始化完成: 最终日期={final_state.date}, 净值={final_state.nav:.2f}")
        self._log_monitor_fx_snapshot(final_state.date, fx_df)
        
        return {
            'monitor_id': monitor_id,
            'date': final_state.date,
            'nav': final_state.nav,
            'day_count': final_state.day_count,
            'vol_reset_count': final_state.vol_reset_count,
            'total_trading_cost': final_state.total_trading_cost,
            'total_replication_cost': final_state.total_replication_cost,
        }
    
    async def run_daily(
        self,
        monitor_id: str = "default",
        target_date: str = None,
        manual_preset_step: bool = False,
    ) -> dict:
        """
        日常运行：从上次状态续接到目标日期（默认最新）
        对应 run_monitor.py 正常模式
        
        manual_preset_step: 主观配置时，在预设调仓日当日推演完成后暂停（与初始化步进衔接）
        """
        logger.info(f"日常监测模式开始: monitor_id={monitor_id}")

        # ── 组合（portfolio）监控：从原始起点全量重跑到目标日期（复用回测管线） ──
        portfolio_info = await self._resolve_portfolio_source(monitor_id)
        if portfolio_info:
            existing = await self.get_state(monitor_id)
            _bt_start = None
            if existing and existing.nav_history:
                _first = existing.nav_history[0]
                _bt_start = _first.get('date') if isinstance(_first, dict) else str(_first)
            if not _bt_start:
                _bt_start = config.BASE_DATE
            target_ts = (
                normalize_calendar_timestamp(target_date)
                if target_date
                else await self.async_provider.get_latest_date()
            )
            return await self._run_portfolio_backtest_monitor(
                monitor_id, portfolio_info,
                start_date=str(_bt_start), end_date=target_ts,
            )

        await self._prepare_monitor_run(monitor_id)
        
        # 1. 加载当前状态
        mongo_state = await self.get_state(monitor_id)
        if not mongo_state:
            raise ValueError(f"监控状态不存在: {monitor_id}，请先运行初始化")
        
        ps = self._state_to_portfolio_state(mongo_state)
        logger.info(f"上次状态日期: {ps.date}, 净值: {ps.nav:.2f}")
        
        # 2. 加载数据
        prices_df = await self.async_provider.load_prices(
            asset_columns=list(self.tracker.asset_list),
        )
        prices_df = slice_prices_df(prices_df, self._monitor_runtime)
        self._log_asset_data_quality(prices_df, label="日常")
        fx_df = await self.async_provider.load_fx()
        trade_dates = await self.async_provider.load_trade_dates()
        trade_dates = coerce_trade_dates(trade_dates, prices_df)
        
        if prices_df.empty:
            self._log_monitor_fx_snapshot(ps.date, fx_df)
            raise ValueError(
                "价格数据为空，无法运行日常监控；请检查 Mongo 行情是否存在、"
                "策略底层资产代码是否与 asset_prices.asset_code 一致（含 MONGO_ASSET_CODE_SUFFIX）。"
            )
        
        # ── 研究员策略独立引擎路径（全量重算到最新日期） ──
        if self._researcher_code in ('sharpe_18', 'hybrid_12'):
            # 从已有 nav_history 提取原始回测起始日，确保重算与 init 一致
            _bt_start = None
            if ps.nav_history:
                _bt_start = ps.nav_history[0].get('date') if isinstance(ps.nav_history[0], dict) else str(ps.nav_history[0])
            if self._researcher_code == 'sharpe_18':
                return await self._run_init_sharpe18_standalone(
                    monitor_id, mongo_state, ps, prices_df, fx_df, trade_dates,
                    backtest_start=_bt_start,
                )
            return await self._run_init_hybrid12_standalone(
                monitor_id, mongo_state, ps, prices_df, fx_df, trade_dates,
                backtest_start=_bt_start,
            )

        # 3. 加载预计算权重并构建调仓映射
        precomputed_weights = await self._async_load_precomputed_weights(
            prices_df, rt=self._monitor_runtime
        )
        monthly_rebalance_map = self._build_monthly_rebalance_map(
            prices_df,
            trade_dates,
            config.SKIP_EXCLUDED_DATES,
            rt=self._monitor_runtime,
            merged_params=self._merged_monitor_params,
            precomputed_weights=precomputed_weights,
        )
        monthly_rebalance_dates = set(monthly_rebalance_map.keys())
        vol_reset_execute_dates = set()
        
        # 构建月度调仓信号日期集合（与原型 monthly_signal_dates_set 对齐）
        monthly_signal_dates = {
            normalize_calendar_timestamp(v['calc_date'])
            for v in monthly_rebalance_map.values()
        }
        # 波动率触发信号日期集合（在循环中逐步积累）
        vol_signal_dates = set()
        # 如果当前状态有 pending vol_reset，将其信号日加入集合
        if ps.pending_rebalance and ps.pending_rebalance.get('rebalance_type') == 'vol_reset':
            sig_d = ps.pending_rebalance.get('signal_date')
            if sig_d:
                vol_signal_dates.add(normalize_calendar_timestamp(sig_d))
        
        # 4. 确定处理日期范围
        last_date = normalize_calendar_timestamp(ps.date)
        end_date = (
            normalize_calendar_timestamp(target_date)
            if target_date
            else prices_df.index.max()
        )
        processing_dates = [d for d in prices_df.index if last_date < d <= end_date]
        
        if not processing_dates:
            logger.info("没有需要处理的交易日")
            self._log_monitor_fx_snapshot(ps.date, fx_df)
            return {
                'monitor_id': monitor_id,
                'date': ps.date,
                'nav': ps.nav,
                'message': '没有新数据需要处理'
            }
        
        logger.info(f"处理日期范围: {processing_dates[0].strftime('%Y-%m-%d')} ~ {processing_dates[-1].strftime('%Y-%m-%d')}, 共 {len(processing_dates)} 个交易日")
        
        # 5. 逐日处理
        prev_nav = ps.nav
        pending_overrides = await self._get_pending_overrides(monitor_id)
        last_result = None
        step_mode = self._manual_preset_step_active(
            manual_preset_step, self._monitor_runtime
        )
        
        for i, date in enumerate(processing_dates):
            date_str = date.strftime('%Y-%m-%d')
            
            result = self._process_single_day(
                ps, date_str, prices_df, fx_df, trade_dates,
                monthly_rebalance_map, monthly_rebalance_dates,
                vol_reset_execute_dates, pending_overrides, prev_nav,
                base_date=config.BASE_DATE,
                rt=self._monitor_runtime,
                monthly_signal_dates=monthly_signal_dates,
                vol_signal_dates=vol_signal_dates,
            )
            
            if result.get('vol_reset_triggered'):
                exec_date = result.get('vol_reset_execute_date')
                if exec_date:
                    vol_reset_execute_dates.add(
                        normalize_calendar_timestamp(exec_date)
                    )
                # 记录波动率触发信号日期（用于后续"触发-执行间信号"检查）
                vol_signal_dates.add(date)
            
            # 标记已执行的主观调仓指令
            if result.get('executed_override_id'):
                await self._mark_override_executed(result['executed_override_id'])
            
            # 保存日报
            await self._save_daily_report(monitor_id, result)
            
            prev_nav = ps.nav
            last_result = result
            
            if step_mode and self._should_pause_after_manual_preset_day(
                i, processing_dates, monthly_rebalance_dates
            ):
                final_state = self._portfolio_state_to_state(ps, monitor_id, mongo_state)
                final_state.performance_basis = await self._capture_performance_basis_for_monitor(
                    monitor_id
                )
                next_j = self._first_future_manual_preset_index(
                    processing_dates, monthly_rebalance_dates, i
                )
                next_preset_str = (
                    processing_dates[next_j].strftime("%Y-%m-%d")
                    if next_j is not None
                    else None
                )
                has_more = self._manual_preset_step_pending_after_pause(i, processing_dates)
                self._set_manual_preset_step_flags(final_state, has_more, next_preset_str)
                await self.save_state(final_state)
                self._log_monitor_fx_snapshot(final_state.date, fx_df)
                logger.info(
                    f"日常监测主观步进暂停: 调仓日当日已推演截至={final_state.date}, "
                    f"下一预设调仓日={next_preset_str or '（区间内无）'}"
                )
                out = self._manual_preset_step_pause_payload(
                    ps, processing_dates, monthly_rebalance_dates, i, result
                )
                out.update(
                    {
                        "monitor_id": monitor_id,
                        "daily_return": result.get("nav_change_pct") or 0,
                        "rebalance_executed": result.get("rebalance_executed", False),
                        "message": "主观预设调仓步进：已完成本档调仓日当日推演，请查看绩效后「继续执行」或再次「运行监控」",
                    }
                )
                return out
        
        # 6. 保存最终状态
        final_state = self._portfolio_state_to_state(ps, monitor_id, mongo_state)
        self._set_manual_preset_step_flags(final_state, False)
        await self.save_state(final_state)
        
        logger.info(f"日常监测完成: 最终日期={final_state.date}, 净值={final_state.nav:.2f}")
        self._log_monitor_fx_snapshot(final_state.date, fx_df)
        
        return {
            'monitor_id': monitor_id,
            'date': final_state.date,
            'nav': final_state.nav,
            'day_count': final_state.day_count,
            'daily_return': last_result.get('nav_change_pct') if last_result else 0,
            'rebalance_executed': last_result.get('rebalance_executed', False) if last_result else False,
        }
    
    async def run_range(
        self,
        monitor_id: str,
        from_date: str,
        to_date: str,
        manual_preset_step: bool = False,
    ) -> dict:
        """
        按日期范围运行：从指定日期到指定日期
        对应 run_monitor.py --from --to 模式
        """
        logger.info(f"范围运行模式: {from_date} ~ {to_date}")

        # ── 组合（portfolio）监控：按范围复用回测管线全量重算 ──
        portfolio_info = await self._resolve_portfolio_source(monitor_id)
        if portfolio_info:
            return await self._run_portfolio_backtest_monitor(
                monitor_id, portfolio_info,
                start_date=str(from_date), end_date=to_date,
            )

        await self._prepare_monitor_run(monitor_id)
        
        mongo_state = await self.get_state(monitor_id)
        if not mongo_state:
            raise ValueError(f"监控状态不存在: {monitor_id}")
        
        ps = self._state_to_portfolio_state(mongo_state)
        
        prices_df = await self.async_provider.load_prices(
            asset_columns=list(self.tracker.asset_list),
        )
        prices_df = slice_prices_df(prices_df, self._monitor_runtime)
        fx_df = await self.async_provider.load_fx()
        trade_dates = await self.async_provider.load_trade_dates()
        trade_dates = coerce_trade_dates(trade_dates, prices_df)
        
        if prices_df.empty:
            self._log_monitor_fx_snapshot(ps.date, fx_df)
            raise ValueError(
                "价格数据为空，无法按范围运行监控；请检查 Mongo 行情与策略资产代码是否一致。"
            )
        
        precomputed_weights = await self._async_load_precomputed_weights(
            prices_df, rt=self._monitor_runtime
        )
        monthly_rebalance_map = self._build_monthly_rebalance_map(
            prices_df,
            trade_dates,
            config.SKIP_EXCLUDED_DATES,
            rt=self._monitor_runtime,
            merged_params=self._merged_monitor_params,
            precomputed_weights=precomputed_weights,
        )
        monthly_rebalance_dates = set(monthly_rebalance_map.keys())
        vol_reset_execute_dates = set()
        
        # 构建月度调仓信号日期集合（与原型 monthly_signal_dates_set 对齐）
        monthly_signal_dates = {
            normalize_calendar_timestamp(v['calc_date'])
            for v in monthly_rebalance_map.values()
        }
        # 波动率触发信号日期集合（在循环中逐步积累）
        vol_signal_dates = set()
        # 如果当前状态有 pending vol_reset，将其信号日加入集合
        if ps.pending_rebalance and ps.pending_rebalance.get('rebalance_type') == 'vol_reset':
            sig_d = ps.pending_rebalance.get('signal_date')
            if sig_d:
                vol_signal_dates.add(normalize_calendar_timestamp(sig_d))
        
        from_ts = normalize_calendar_timestamp(from_date)
        to_ts = normalize_calendar_timestamp(to_date)
        processing_dates = [d for d in prices_df.index if from_ts <= d <= to_ts]
        
        if not processing_dates:
            self._log_monitor_fx_snapshot(ps.date, fx_df)
            return {'monitor_id': monitor_id, 'message': '指定范围内没有交易日'}
        
        prev_nav = ps.nav
        pending_overrides = await self._get_pending_overrides(monitor_id)
        step_mode = self._manual_preset_step_active(
            manual_preset_step, self._monitor_runtime
        )
        last_range_result = None
        
        for i, date in enumerate(processing_dates):
            date_str = date.strftime('%Y-%m-%d')
            result = self._process_single_day(
                ps, date_str, prices_df, fx_df, trade_dates,
                monthly_rebalance_map, monthly_rebalance_dates,
                vol_reset_execute_dates, pending_overrides, prev_nav,
                base_date=config.BASE_DATE,
                rt=self._monitor_runtime,
                monthly_signal_dates=monthly_signal_dates,
                vol_signal_dates=vol_signal_dates,
            )
            last_range_result = result
            
            if result.get('vol_reset_triggered'):
                exec_date = result.get('vol_reset_execute_date')
                if exec_date:
                    vol_reset_execute_dates.add(
                        normalize_calendar_timestamp(exec_date)
                    )
                # 记录波动率触发信号日期（用于后续"触发-执行间信号"检查）
                vol_signal_dates.add(date)
            
            # 标记已执行的主观调仓指令
            if result.get('executed_override_id'):
                await self._mark_override_executed(result['executed_override_id'])
            
            await self._save_daily_report(monitor_id, result)
            prev_nav = ps.nav
            
            if step_mode and self._should_pause_after_manual_preset_day(
                i, processing_dates, monthly_rebalance_dates
            ):
                final_state = self._portfolio_state_to_state(ps, monitor_id, mongo_state)
                final_state.performance_basis = await self._capture_performance_basis_for_monitor(
                    monitor_id
                )
                next_j = self._first_future_manual_preset_index(
                    processing_dates, monthly_rebalance_dates, i
                )
                next_preset_str = (
                    processing_dates[next_j].strftime("%Y-%m-%d")
                    if next_j is not None
                    else None
                )
                has_more = self._manual_preset_step_pending_after_pause(i, processing_dates)
                self._set_manual_preset_step_flags(final_state, has_more, next_preset_str)
                await self.save_state(final_state)
                self._log_monitor_fx_snapshot(final_state.date, fx_df)
                out = self._manual_preset_step_pause_payload(
                    ps, processing_dates, monthly_rebalance_dates, i, last_range_result
                )
                out.update(
                    {
                        "monitor_id": monitor_id,
                        "from_date": from_date,
                        "to_date": to_date,
                        "processed_in_this_request": i + 1,
                        "message": "主观预设调仓步进：范围运行已暂停，请再次调用范围运行或改用「运行监控」续跑",
                    }
                )
                return out
        
        final_state = self._portfolio_state_to_state(ps, monitor_id, mongo_state)
        self._set_manual_preset_step_flags(final_state, False)
        await self.save_state(final_state)
        self._log_monitor_fx_snapshot(final_state.date, fx_df)
        
        return {
            'monitor_id': monitor_id,
            'from_date': from_date,
            'to_date': to_date,
            'processed_days': len(processing_dates),
            'final_date': final_state.date,
            'final_nav': final_state.nav,
        }

    # ============================================================
    # sharpe_18 独立引擎
    # ============================================================

    async def _run_init_sharpe18_standalone(
        self,
        monitor_id: str,
        mongo_state,
        ps: PortfolioState,
        prices_df: pd.DataFrame,
        fx_df: pd.DataFrame,
        trade_dates: List,
        backtest_start: str = None,
    ) -> dict:
        """使用 sharpe_18 独立引擎运行全量回测（自包含 step1+step2+step3）。"""
        from app.monitor.researcher_strategies.sharpe_18.engine import run_backtest as sharpe18_run

        logger.info("sharpe_18 引擎启动，数据: {} ~ {}, backtest_start={}",
                    prices_df.index[0].date(), prices_df.index[-1].date(), backtest_start)
        result = sharpe18_run(prices_df, fx_df, trade_dates, backtest_start=backtest_start)
        logger.info("sharpe_18 引擎完成: 日期={}, NAV={:.2f}", result['final_date'], result['final_nav'])

        # 填充 PortfolioState
        ps.date = result['final_date']
        ps.nav = result['final_nav']
        ps.nav_base = result['final_nav']  # 简化：最终 nav_base = nav
        ps.positions_cny = result['positions_cny']
        ps.positions_local = result['positions_local']
        ps.apl_local = result['apl_local']
        ps.positions_cny_base = result['positions_cny_base']
        ps.target_weights = result['target_weights']
        ps.last_rebalance_date = result['last_rebalance_date']
        ps.last_rebalance_fx = result['last_rebalance_fx']
        ps.pending_rebalance = result['pending_rebalance']
        ps.nav_history = result['nav_history']
        ps.total_trading_cost = result['total_trading_cost']
        ps.total_replication_cost = result['total_replication_cost']
        ps.vol_reset_count = result['vol_reset_count']
        ps.day_count = result['day_count']
        ps.trade_day_count = result['trade_day_count']
        ps.event_log = result['event_log']

        # 保存状态
        final_state = self._portfolio_state_to_state(ps, monitor_id, mongo_state)
        final_state.performance_basis = await self._capture_performance_basis_for_monitor(monitor_id)
        self._set_manual_preset_step_flags(final_state, False)
        await self.save_state(final_state)
        self._log_monitor_fx_snapshot(final_state.date, fx_df)

        return {
            'monitor_id': monitor_id,
            'date': final_state.date,
            'nav': final_state.nav,
            'day_count': final_state.day_count,
            'vol_reset_count': final_state.vol_reset_count,
            'total_trading_cost': final_state.total_trading_cost,
            'total_replication_cost': final_state.total_replication_cost,
        }

    async def _run_init_hybrid12_standalone(
        self,
        monitor_id: str,
        mongo_state,
        ps: PortfolioState,
        prices_df: pd.DataFrame,
        fx_df: pd.DataFrame,
        trade_dates: List,
        backtest_start: str = None,
    ) -> dict:
        """使用 hybrid_12 独立引擎运行全量回测（自包含 step1+step2+step3）。"""
        from app.monitor.researcher_strategies.hybrid_12.engine import run_backtest as hybrid12_run

        logger.info("hybrid_12 引擎启动，数据: {} ~ {}, backtest_start={}",
                    prices_df.index[0].date(), prices_df.index[-1].date(), backtest_start)
        result = hybrid12_run(prices_df, fx_df, trade_dates, backtest_start=backtest_start)
        logger.info("hybrid_12 引擎完成: 日期={}, NAV={:.2f}", result['final_date'], result['final_nav'])

        # 填充 PortfolioState
        ps.date = result['final_date']
        ps.nav = result['final_nav']
        ps.nav_base = result['final_nav']
        ps.positions_cny = result['positions_cny']
        ps.positions_local = result['positions_local']
        ps.apl_local = result['apl_local']
        ps.target_weights = result['target_weights']
        ps.last_rebalance_fx = result['last_rebalance_fx']
        ps.pending_rebalance = result['pending_rebalance']
        ps.nav_history = result['nav_history']
        ps.total_trading_cost = result['total_trading_cost']
        ps.total_replication_cost = result['total_replication_cost']
        ps.vol_reset_count = result['vol_reset_count']
        ps.day_count = result['day_count']
        ps.event_log = result['event_log']

        # 保存状态
        final_state = self._portfolio_state_to_state(ps, monitor_id, mongo_state)
        final_state.performance_basis = await self._capture_performance_basis_for_monitor(monitor_id)
        self._set_manual_preset_step_flags(final_state, False)
        await self.save_state(final_state)
        self._log_monitor_fx_snapshot(final_state.date, fx_df)

        return {
            'monitor_id': monitor_id,
            'date': final_state.date,
            'nav': final_state.nav,
            'day_count': final_state.day_count,
            'vol_reset_count': final_state.vol_reset_count,
            'total_trading_cost': final_state.total_trading_cost,
            'total_replication_cost': final_state.total_replication_cost,
        }

    # ============================================================
    # 主观调仓管理
    # ============================================================
    
    async def add_subjective_override(self, monitor_id: str, weights: dict,
                                       execute_date: str, description: str = None) -> str:
        """新增主观调仓指令"""
        rt = await self._runtime_for_reads(monitor_id)
        self._validate_weights(weights, rt)
        
        override_id = f"sub_{execute_date.replace('-', '')}_{uuid.uuid4().hex[:8]}"
        
        override = SubjectiveOverride(
            override_id=override_id,
            monitor_id=monitor_id,
            weights=weights,
            execute_date=execute_date,
            status=OverrideStatus.PENDING,
            description=description,
            created_at=datetime.now()
        )
        
        await self.overrides_collection.insert_one(override.to_dict())
        logger.info(f"主观调仓指令已创建: {override_id}, 执行日期: {execute_date}")
        
        return override_id
    
    async def list_subjective_overrides(self, monitor_id: str,
                                         status: str = None) -> List[dict]:
        """列出主观调仓指令，可按状态筛选"""
        query = {"monitor_id": monitor_id}
        if status:
            query["status"] = status
        
        cursor = self.overrides_collection.find(query).sort("created_at", -1)
        result = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            result.append(doc)
        
        return result
    
    async def cancel_subjective_override(self, override_id: str) -> bool:
        """取消主观调仓指令（仅 pending 状态可取消）"""
        result = await self.overrides_collection.update_one(
            {"override_id": override_id, "status": OverrideStatus.PENDING.value},
            {"$set": {"status": OverrideStatus.CANCELLED.value}}
        )
        if result.modified_count > 0:
            logger.info(f"主观调仓指令已取消: {override_id}")
            return True
        return False
    
    async def _get_pending_overrides(self, monitor_id: str) -> List[dict]:
        """获取所有 pending 状态的主观调仓指令"""
        cursor = self.overrides_collection.find({
            "monitor_id": monitor_id,
            "status": OverrideStatus.PENDING.value
        })
        result = []
        async for doc in cursor:
            result.append(doc)
        return result
    
    async def _mark_override_executed(self, override_id: str) -> None:
        """标记指令为已执行"""
        await self.overrides_collection.update_one(
            {"override_id": override_id},
            {"$set": {"status": OverrideStatus.EXECUTED.value, "executed_at": datetime.now()}}
        )
    
    def _validate_weights(self, weights: dict, rt: Optional[MonitorRuntimeConfig] = None):
        """校验权重合法性"""
        asset_list = list(rt.asset_list) if rt else list(config.ASSET_LIST)
        caps = dict(rt.weight_caps) if rt else dict(config.WEIGHT_CAPS)
        max_lev = float(rt.max_leverage) if rt else float(config.MAX_LEVERAGE)
        for asset in asset_list:
            if asset not in weights:
                raise ValueError(f"缺少资产 {asset} 的权重")
        
        for asset, w in weights.items():
            if w < 0:
                raise ValueError(f"{asset} 权重不能为负: {w}")
        
        for asset, w in weights.items():
            cap = caps.get(asset, config.WEIGHT_CAPS.get(asset, 1.0))
            if w > cap:
                raise ValueError(f"{asset} 权重 {w:.2%} 超过上限 {cap:.2%}")
        
        total_weight = sum(weights.values())
        if total_weight > max_lev:
            raise ValueError(f"总权重 {total_weight:.2f} 超过杠杆上限 {max_lev}")
