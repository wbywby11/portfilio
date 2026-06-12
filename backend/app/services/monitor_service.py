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
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from loguru import logger
from bson import ObjectId

from app.config.database import Database
from app.models.monitor import (
    MonitorState, SubjectiveOverride, MonitorDailyReport,
    OverrideStatus
)
from app.monitor import config
from app.monitor.types import PortfolioState, DailyResult
from app.monitor.data_provider import MongoDataProvider, SyncDataProvider
from app.monitor.portfolio_tracker import PortfolioTracker
from app.monitor.strategy_engine import StrategyEngine
from app.monitor.signal_detector import SignalDetector

# 跳过波动率重置监测的策略模板集合
_SKIP_VOL_RESET_TEMPLATES = {
    "manual_allocation", "manual_allocation_strategy",
    "etf_cycle_rotation", "risk_parity",
}
from app.monitor.report_generator import ReportGenerator
from app.monitor.volatility_calculator import VolatilityCalculator
from app.monitor.mongo_asset_codes import stored_price_code, canonical_price_code
from app.monitor.time_norm import normalize_calendar_timestamp
from app.monitor.monitor_runtime import (
    MonitorRuntimeConfig,
    monitor_runtime_from_model,
    resolve_asset_class_for_monitor,
    resolve_asset_currency_for_monitor,
    resolve_monitor_asset_display_label,
    slice_prices_df,
    live_effective_structured_params,
    normalize_strategy_asset_codes,
    live_effective_display_bundle,
    live_effective_asset_display_labels,
    config_baseline_eligible_strategy_dict,
)
from app.monitor.live_publish_log_scope import merge_parameters_with_top_level_windows
from app.services.strategy_model_service import StrategyModelService
from app.services.asset_service import AssetService


class MonitorService:
    """监控服务 - 编排整个日常监控调仓流程"""
    
    def __init__(self):
        self._db = None
        # 核心组件
        self.tracker = PortfolioTracker()
        self.engine = StrategyEngine()
        self.detector = SignalDetector()
        self.reporter = ReportGenerator()
        self.vol_calculator = VolatilityCalculator()
        # 数据提供者
        self._async_provider = None
        self._sync_provider = None
        # 单次请求内实盘策略监控的运行时参数（由 monitor_id 对应模型解析）
        self._monitor_runtime: Optional[MonitorRuntimeConfig] = None
        self._merged_monitor_params: Dict[str, Any] = {}

    def _manual_preset_step_active(
        self, manual_preset_step: bool, rt: Optional[MonitorRuntimeConfig]
    ) -> bool:
        """主观配置策略下，是否启用预设调仓日步进暂停（每处理完一个调仓日当周停一次，便于查看绩效）。"""
        return bool(
            manual_preset_step
            and rt is not None
            and getattr(rt, "manual_allocation_mode", False)
        )

    @staticmethod
    def _should_pause_after_manual_preset_day(
        day_index: int,
        processing_dates: List,
        monthly_rebalance_dates: set,
    ) -> bool:
        """当日为预设调仓日且本日已推演完毕时，在当日结束后暂停（暂停日=调仓日当日）。"""
        if day_index < 0 or day_index >= len(processing_dates):
            return False
        return processing_dates[day_index] in monthly_rebalance_dates

    @staticmethod
    def _first_future_manual_preset_index(
        processing_dates: List,
        monthly_rebalance_dates: set,
        after_index: int,
    ) -> Optional[int]:
        for j in range(after_index + 1, len(processing_dates)):
            if processing_dates[j] in monthly_rebalance_dates:
                return j
        return None

    @staticmethod
    def _manual_preset_step_pending_after_pause(
        day_index: int,
        processing_dates: List,
    ) -> bool:
        """暂停后若行情上仍有更晚的交易日未推演，则需要「继续执行」续跑。"""
        return day_index < len(processing_dates) - 1

    @staticmethod
    def _pause_payload_as_of_date(ps: PortfolioState) -> str:
        d = ps.date
        if d is None:
            return ""
        if hasattr(d, "strftime"):
            return d.strftime("%Y-%m-%d")
        s = str(d)
        return s[:10] if len(s) >= 10 else s

    @staticmethod
    def _set_manual_preset_step_flags(
        state: MonitorState,
        pending: bool,
        next_preset_yyyy_mm_dd: Optional[str] = None,
    ) -> None:
        state.manual_preset_step_pending = bool(pending)
        state.manual_preset_next_date = (
            next_preset_yyyy_mm_dd if pending else None
        )

    def _manual_preset_step_pause_payload(
        self,
        ps: PortfolioState,
        processing_dates: List,
        monthly_rebalance_dates: set,
        day_index: int,
        last_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        next_j = self._first_future_manual_preset_index(
            processing_dates, monthly_rebalance_dates, day_index
        )
        next_preset_date = (
            processing_dates[next_j].strftime("%Y-%m-%d") if next_j is not None else ""
        )
        remaining: List[str] = []
        for j in range(day_index + 1, len(processing_dates)):
            if processing_dates[j] in monthly_rebalance_dates:
                remaining.append(processing_dates[j].strftime("%Y-%m-%d"))
        perf = self.reporter.calc_performance(ps)
        calmar = (
            perf.annual_return / abs(perf.max_drawdown)
            if perf.max_drawdown != 0
            else 0.0
        )
        nav_hist = ps.nav_history or []
        init_only = bool(
            last_result and last_result.get("rebalance_type") == "init"
        )
        tw = ps.target_weights or {}
        current_target_weights = {
            str(k): float(v) for k, v in tw.items() if v is not None
        }
        return {
            "paused": True,
            "manual_preset_step": True,
            "as_of_date": self._pause_payload_as_of_date(ps),
            "next_preset_date": next_preset_date,
            "remaining_preset_dates": remaining,
            "init_only_before_next_preset": init_only,
            "nav_history_length": len(nav_hist),
            "base_nav": float(config.BASE_VALUE),
            "current_target_weights": current_target_weights,
            "performance": {
                "cumulative_return": perf.cumulative_return,
                "annual_return": perf.annual_return,
                "annual_volatility": perf.annual_vol,
                "max_drawdown": perf.max_drawdown,
                "sharpe_ratio": perf.sharpe_ratio,
                "calmar_ratio": calmar,
            },
            "nav": float(ps.nav) if ps.nav is not None else 0.0,
            "day_count": ps.day_count,
        }

    @staticmethod
    def _coerce_trade_dates(trade_dates: List, prices_df: pd.DataFrame) -> List:
        """规范化交易日；仅在 Mongo 与 data/trade_dates.xlsx 均无数据时回退为价格索引。"""
        if trade_dates:
            return [normalize_calendar_timestamp(d) for d in trade_dates]
        if prices_df is not None and not prices_df.empty:
            logger.warning(
                "交易日历仍为空（请检查 Mongo trade_dates 集合或 data/trade_dates.xlsx），"
                "暂用价格数据的日期索引作为交易日列表"
            )
            return sorted(prices_df.index.tolist())
        return []

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

    async def _prepare_monitor_run(self, monitor_id: str) -> None:
        """解析实盘模型运行时配置并配置 PortfolioTracker；无实盘模型时回退全局 config。"""
        self._monitor_runtime = None
        self._merged_monitor_params = {}
        self.tracker.configure(None)
        if not self._is_strategy_model_monitor_id(monitor_id):
            return
        svc = StrategyModelService()
        model = await svc.get_model(monitor_id)
        if not model:
            return
        self._merged_monitor_params = merge_parameters_with_top_level_windows(
            model, model.parameters or {}
        )
        rt = monitor_runtime_from_model(model)
        if rt is None:
            return
        self._monitor_runtime = rt
        self.tracker.configure(rt)

    async def _runtime_for_reads(self, monitor_id: str) -> Optional[MonitorRuntimeConfig]:
        """读接口（持仓/信号等）按 monitor_id 解析运行时参数，无缓存。"""
        if not self._is_strategy_model_monitor_id(monitor_id):
            return None
        svc = StrategyModelService()
        model = await svc.get_model(monitor_id)
        if not model:
            return None
        return monitor_runtime_from_model(model)

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
        return self.db['monitor_states']
    
    @property
    def overrides_collection(self):
        return self.db['subjective_overrides']
    
    @property
    def reports_collection(self):
        return self.db['monitor_daily_reports']
    
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
            target_weights=dict(state.target_weights),
            last_rebalance_date=state.last_rebalance_date or state.date,
            last_rebalance_fx=dict(state.last_rebalance_fx),
            pending_rebalance=dict(state.pending_rebalance) if state.pending_rebalance else None,
            nav_history=list(state.nav_history),
            total_trading_cost=state.total_trading_cost,
            total_replication_cost=state.total_replication_cost,
            vol_reset_count=state.vol_reset_count,
            day_count=state.day_count,
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
                logger.warning(
                    "检测到遗留资产持仓（不在当前策略 asset_list 中）：{} 个资产={}；将继续参与 NAV 计算并于下次调仓时被清算。",
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
            original.target_weights = ps.target_weights
            original.last_rebalance_date = ps.last_rebalance_date
            original.last_rebalance_fx = ps.last_rebalance_fx
            original.pending_rebalance = ps.pending_rebalance
            original.nav_history = ps.nav_history
            original.total_trading_cost = ps.total_trading_cost
            original.total_replication_cost = ps.total_replication_cost
            original.vol_reset_count = ps.vol_reset_count
            original.day_count = ps.day_count
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
            positions_cny=ps.positions_cny,
            positions_local=ps.positions_local,
            apl_local=ps.apl_local,
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
        fx_df = await self.async_provider.load_fx()
        trade_dates = await self.async_provider.load_trade_dates()
        trade_dates = self._coerce_trade_dates(trade_dates, prices_df)
        
        if prices_df.empty:
            raise ValueError("价格数据为空，无法初始化")
        
        # 3. 构建月末调仓映射表
        monthly_rebalance_map = self._build_monthly_rebalance_map(
            prices_df,
            trade_dates,
            config.SKIP_EXCLUDED_DATES,
            rt=self._monitor_runtime,
            merged_params=self._merged_monitor_params,
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
        
        for i, date in enumerate(processing_dates):
            date_str = date.strftime('%Y-%m-%d')
            
            result = self._process_single_day(
                ps, date_str, prices_df, fx_df, trade_dates,
                monthly_rebalance_map, monthly_rebalance_dates,
                vol_reset_execute_dates, pending_overrides, prev_nav,
                base_date=aligned_start_date,
                rt=self._monitor_runtime,
            )
            
            # 更新波动率重置执行日期集合
            if result.get('vol_reset_triggered'):
                exec_date = result.get('vol_reset_execute_date')
                if exec_date:
                    vol_reset_execute_dates.add(
                        normalize_calendar_timestamp(exec_date)
                    )
            
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
        fx_df = await self.async_provider.load_fx()
        trade_dates = await self.async_provider.load_trade_dates()
        trade_dates = self._coerce_trade_dates(trade_dates, prices_df)
        
        if prices_df.empty:
            self._log_monitor_fx_snapshot(ps.date, fx_df)
            raise ValueError(
                "价格数据为空，无法运行日常监控；请检查 Mongo 行情是否存在、"
                "策略底层资产代码是否与 asset_prices.asset_code 一致（含 MONGO_ASSET_CODE_SUFFIX）。"
            )
        
        # 3. 构建调仓映射
        monthly_rebalance_map = self._build_monthly_rebalance_map(
            prices_df,
            trade_dates,
            config.SKIP_EXCLUDED_DATES,
            rt=self._monitor_runtime,
            merged_params=self._merged_monitor_params,
        )
        monthly_rebalance_dates = set(monthly_rebalance_map.keys())
        vol_reset_execute_dates = set()
        
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
            )
            
            if result.get('vol_reset_triggered'):
                exec_date = result.get('vol_reset_execute_date')
                if exec_date:
                    vol_reset_execute_dates.add(
                        normalize_calendar_timestamp(exec_date)
                    )
            
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
        trade_dates = self._coerce_trade_dates(trade_dates, prices_df)
        
        if prices_df.empty:
            self._log_monitor_fx_snapshot(ps.date, fx_df)
            raise ValueError(
                "价格数据为空，无法按范围运行监控；请检查 Mongo 行情与策略资产代码是否一致。"
            )
        
        monthly_rebalance_map = self._build_monthly_rebalance_map(
            prices_df,
            trade_dates,
            config.SKIP_EXCLUDED_DATES,
            rt=self._monitor_runtime,
            merged_params=self._merged_monitor_params,
        )
        monthly_rebalance_dates = set(monthly_rebalance_map.keys())
        vol_reset_execute_dates = set()
        
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
            )
            last_range_result = result
            
            if result.get('vol_reset_triggered'):
                exec_date = result.get('vol_reset_execute_date')
                if exec_date:
                    vol_reset_execute_dates.add(
                        normalize_calendar_timestamp(exec_date)
                    )
            
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
    # 每日流程编排
    # ============================================================
    
    def _process_single_day(self, state: PortfolioState, date_str: str,
                            prices_df: pd.DataFrame, fx_df: pd.DataFrame,
                            trade_dates: List, monthly_rebalance_map: dict,
                            monthly_rebalance_dates: set,
                            vol_reset_execute_dates: set,
                            subjective_overrides: List[dict],
                            prev_nav: float,
                            base_date: str = None,
                            rt: Optional[MonitorRuntimeConfig] = None) -> dict:
        """
        处理单个交易日（对应 run_monitor.py 的步骤 A-F）
        
        Args:
            base_date: 基日，用于判断是否是初始化第一天，默认使用 config.BASE_DATE
        
        严格按以下顺序执行：
        步骤A: 初始日处理（如果是基日）
        步骤B: 每日损益更新 (portfolio_tracker.process_day)
        步骤B2: 主观调仓检查（优先级最高）
        步骤C: 执行 Pending 波动率重置调仓
        步骤D: 月度调仓检查（T+2 执行）
        步骤E: 波动率重置监测
        步骤F: 生成日报数据
        """
        date = normalize_calendar_timestamp(pd.Timestamp(date_str))
        actual_base_ts = normalize_calendar_timestamp(
            base_date or config.BASE_DATE
        )
        al = list(self.tracker.asset_list)
        merged_params = getattr(self, "_merged_monitor_params", None) or {}
        
        # 获取价格
        prices_today = self._get_prices_for_date(prices_df, date)
        prev_dates = prices_df.index[prices_df.index < date]
        if len(prev_dates) > 0:
            prev_date = prev_dates[-1]
            prices_yesterday = self._get_prices_for_date(prices_df, prev_date)
        else:
            prices_yesterday = prices_today.copy()
        
        # 获取汇率
        fx_rates = self.tracker.get_all_fx_rates(date, fx_df)
        fx_rates_asset = self.tracker.get_all_asset_fx_rates(date, fx_df)
        
        is_rebalance_day = False
        rebalance_signal = None
        vol_reset_signal = None
        rebalance_type = None
        trading_cost = 0.0
        vol_reset_triggered = False
        vol_reset_execute_date = None
        executed_override_id = None  # 已执行的主观调仓指令ID
        
        # ================================================================
        # 步骤A: 初始日处理
        # ================================================================
        if date == actual_base_ts:
            if date in monthly_rebalance_map:
                initial_weights = monthly_rebalance_map[date]['weights']
            elif rt is not None and getattr(rt, "manual_allocation_mode", False):
                initial_weights = self._initial_manual_weights_from_params(al, merged_params)
            else:
                try:
                    selection = self.engine.run_asset_selection(prices_df, date, rt=rt)
                    weight_result = self.engine.run_weight_calculation(
                        prices_df, selection, date, rt=rt
                    )
                    initial_weights = {a: weight_result.weights.get(a, 0.0) for a in al}
                except Exception as e:
                    logger.warning(f"基日权重计算失败: {e}，使用等权重")
                    initial_weights = {a: 1.0 / len(al) for a in al} if al else {}
            
            self.tracker.initialize_positions(
                state, initial_weights, fx_rates, prices_today=prices_today
            )
            state.target_weights = initial_weights.copy()
            state.last_rebalance_date = date_str
            state.last_rebalance_fx = fx_rates_asset.copy()
            state.day_count = 1
            state.date = date_str
            
            zero_weights = {a: 0.0 for a in al}
            state.event_log.append({
                'date': date_str,
                'type': 'init',
                'description': f'策略初始化，初始净值 {state.nav:.2f}',
                'trading_cost': 0.0,
                'old_weights': dict(zero_weights),
                'new_weights': dict(initial_weights),
            })
            state.nav_history.append({'date': date_str, 'nav': state.nav, 'daily_return': 0.0})  # 初始日无涨跌
            
            init_result = self._build_daily_result(state, date_str, 0.0, True, 'init', 0.0, 0.0)
            self._attach_manual_rebalance_observation(
                state, date_str, prices_df, rt, True, init_result
            )
            return init_result
        
        # ================================================================
        # 步骤B: 每日损益更新
        # ================================================================
        if prev_nav is None:
            prev_nav = state.nav
        
        daily_result = self.tracker.process_day(
            state, date_str, prices_today, prices_yesterday, fx_df, trade_dates
        )
        
        # ================================================================
        # 步骤B2: 主观调仓检查
        # ================================================================
        override = self._get_override_for_date(subjective_overrides, date_str)
        if override is not None:
            old_weights = {}
            if state.nav > 0:
                for asset in al:
                    old_weights[asset] = state.positions_cny.get(asset, 0) / state.nav
            
            new_weights = override['weights']
            trading_cost = self.tracker.execute_rebalance(
                state, new_weights, fx_rates, 'subjective', prev_nav,
                prices_today=prices_today,
            )
            
            state.last_rebalance_date = date_str
            state.last_rebalance_fx = {
                asset: fx_rates.get(resolve_asset_currency_for_monitor(asset), 1.0)
                for asset in al
            }
            state.target_weights = new_weights.copy()
            
            state.event_log.append({
                'date': date_str,
                'type': 'subjective',  # 统一事件类型名称
                'description': f"执行主观调仓，交易费用 {trading_cost:.2f}",
                'trading_cost': trading_cost,
                'old_weights': old_weights,
                'new_weights': dict(new_weights),
                'override_id': override.get('override_id'),
            })
                    
            is_rebalance_day = True
            rebalance_type = 'subjective'
            # 记录已执行的 override_id，供调用方标记状态
            executed_override_id = override.get('override_id')
        
        # ================================================================
        # 步骤C: 执行 Pending 波动率重置调仓
        # ================================================================
        if not is_rebalance_day and state.pending_rebalance is not None:
            pending_exec_date = normalize_calendar_timestamp(
                state.pending_rebalance.get('execute_date')
            )
            if date == pending_exec_date:
                pending_weights = state.pending_rebalance.get('weights', {})
                old_weights = dict(state.target_weights)
                trading_cost = self.tracker.execute_rebalance(
                    state, pending_weights, fx_rates, 'vol_reset', prev_nav,
                    prices_today=prices_today,
                )
                new_weights = dict(state.target_weights)
                state.last_rebalance_date = date_str
                
                state.event_log.append({
                    'date': date_str,
                    'type': 'vol_reset',  # 统一事件类型名称
                    'stage': 'execute',   # 通过 stage 区分触发/执行
                    'description': f'执行波动率重置调仓，交易费用 {trading_cost:.2f}',
                    'trading_cost': trading_cost,
                    'old_weights': old_weights,
                    'new_weights': new_weights,
                })
                
                is_rebalance_day = True
                rebalance_type = 'vol_reset'
        
        # ================================================================
        # 步骤D: 月度调仓检查
        # ================================================================
        if not is_rebalance_day:
            rebalance_signal = self.detector.check_monthly_rebalance_execute(
                date, prices_df, trade_dates, monthly_rebalance_map
            )
            if rebalance_signal:
                old_weights = dict(state.target_weights)
                trading_cost = self.tracker.execute_rebalance(
                    state, rebalance_signal.new_weights, fx_rates, 'monthly', prev_nav,
                    prices_today=prices_today,
                )
                new_weights = dict(state.target_weights)
                state.last_rebalance_date = date_str
                state.pending_rebalance = None
                
                calc_date = rebalance_signal.signal_date
                state.event_log.append({
                    'date': date_str,
                    'type': 'monthly',  # 统一事件类型名称
                    'description': f'执行月度调仓（计算日 {calc_date}），交易费用 {trading_cost:.2f}',
                    'calc_date': calc_date,
                    'trading_cost': trading_cost,
                    'old_weights': old_weights,
                    'new_weights': new_weights,
                })
                
                is_rebalance_day = True
                rebalance_type = 'monthly'
        
        # ================================================================
        # 步骤E: 波动率监测
        # ================================================================
        if (
            not is_rebalance_day
            and state.pending_rebalance is None
            and not (rt is not None and (
                getattr(rt, "manual_allocation_mode", False)
                or getattr(rt, "template_code", "") in _SKIP_VOL_RESET_TEMPLATES
            ))
        ):
            vol_reset_signal = self.detector.check_volatility_reset(
                state, state.nav_history, trade_dates, date,
                monthly_rebalance_dates, prices_df, vol_reset_execute_dates,
                rt=rt,
            )
            if vol_reset_signal:
                state.pending_rebalance = {
                    'signal_date': vol_reset_signal.signal_date,
                    'execute_date': vol_reset_signal.execute_date,
                    'weights': vol_reset_signal.new_weights,
                    'rebalance_type': 'vol_reset',
                    'vol_trigger': vol_reset_signal.vol_trigger,
                    'scale_factor': vol_reset_signal.scale_factor,
                }
                state.vol_reset_count += 1
                vol_reset_triggered = True
                vol_reset_execute_date = vol_reset_signal.execute_date
                
                state.event_log.append({
                    'date': date_str,
                    'type': 'vol_reset',  # 统一事件类型名称
                    'stage': 'trigger',   # 通过 stage 区分触发/执行
                    'description': f'波动率触发重置，realized_vol={vol_reset_signal.vol_trigger:.4f}，'
                                   f'scale_factor={vol_reset_signal.scale_factor:.4f}，'
                                   f'执行日 {vol_reset_signal.execute_date}',
                    'vol_trigger': vol_reset_signal.vol_trigger,
                    'scale_factor': vol_reset_signal.scale_factor,
                    'execute_date': vol_reset_signal.execute_date,
                })
        
        # ================================================================
        # 步骤F: 构建结果
        # ================================================================
        # 调仓日：用扣费后的 state.nav 重新计算当日涨跌幅，与回测调仓日快照口径一致
        nav_change_pct_final = daily_result.nav_change_pct
        if is_rebalance_day and prev_nav is not None and prev_nav > 0:
            nav_change_pct_final = (state.nav / prev_nav - 1) * 100
        
        result = self._build_daily_result(
            state, date_str, nav_change_pct_final,
            is_rebalance_day, rebalance_type, trading_cost,
            daily_result.replication_cost
        )
        result['vol_reset_triggered'] = vol_reset_triggered
        result['vol_reset_execute_date'] = vol_reset_execute_date
        result['executed_override_id'] = executed_override_id  # 返回已执行的主观调仓指令ID
        result['asset_returns_local'] = daily_result.asset_returns_local
        result['asset_returns_cny'] = daily_result.asset_returns_cny

        self._attach_manual_rebalance_observation(
            state, date_str, prices_df, rt, is_rebalance_day, result
        )

        return result
    
    def _build_daily_result(self, state: PortfolioState, date_str: str,
                            nav_change_pct: float, rebalance_executed: bool,
                            rebalance_type: Optional[str], trading_cost: float,
                            replication_cost: float) -> dict:
        """构建每日处理结果字典"""
        asset_weights = self.tracker.calc_current_weights(state)
        total_leverage = sum(asset_weights.values())
        
        return {
            'date': date_str,
            'nav': state.nav,
            'nav_change_pct': nav_change_pct,
            'total_leverage': total_leverage,
            'asset_weights': asset_weights,
            'rebalance_executed': rebalance_executed,
            'rebalance_type': rebalance_type,
            'trading_cost': trading_cost,
            'replication_cost': replication_cost,
            'day_count': state.day_count,
        }

    def _manual_allocation_rebalance_observation(
        self,
        prices_df: pd.DataFrame,
        date_str: str,
        target_weights: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        主观策略调仓日：与回测调仓后一致，用「调仓后目标权重」在历史价上计算组合/单资产波动率等观察指标。
        口径与 StrategyEngine._calc_portfolio_volatility / _calc_asset_volatility 一致（VOL_WINDOWS 多窗取 max）。
        """
        out: Dict[str, Any] = {}
        try:
            if prices_df is None or getattr(prices_df, "empty", True):
                return out
            dt = normalize_calendar_timestamp(pd.Timestamp(str(date_str)[:10]))
            if dt not in prices_df.index:
                return out
            idx = prices_df.index.get_loc(dt)
            if isinstance(idx, slice):
                return out
            min_rows = int(config.VOL_WINDOWS[0]) if config.VOL_WINDOWS else 22
            if idx < min_rows - 1:
                return out
            w_raw = {str(k).strip(): float(v or 0) for k, v in (target_weights or {}).items()}
            w_pos = {k: v for k, v in w_raw.items() if v > 0 and k in prices_df.columns}
            if not w_pos:
                return out
            port_vol_raw = self.engine._calc_portfolio_volatility(prices_df, w_pos, dt)
            try:
                port_vol = float(port_vol_raw)
            except (TypeError, ValueError):
                port_vol = None
            if port_vol is not None and (np.isnan(port_vol) or np.isinf(port_vol)):
                port_vol = None
            asset_vols = self.engine._calc_asset_volatility(prices_df, dt)
            av_clean: Dict[str, float] = {}
            if isinstance(asset_vols, dict):
                for code in w_pos:
                    val = asset_vols.get(code)
                    if val is None:
                        continue
                    try:
                        fv = float(val)
                    except (TypeError, ValueError):
                        continue
                    if np.isnan(fv) or np.isinf(fv):
                        continue
                    av_clean[code] = fv
            mm = {
                "portfolio_volatility": port_vol,
                "asset_volatility": av_clean,
            }
            out["portfolio_volatility"] = port_vol
            out["monitoring_metrics"] = mm
            return out
        except Exception as e:
            logger.warning(f"主观策略调仓日观察指标计算失败 {date_str}: {e}")
            return {}

    def _attach_manual_rebalance_observation(
        self,
        state: PortfolioState,
        date_str: str,
        prices_df: pd.DataFrame,
        rt: Optional[MonitorRuntimeConfig],
        is_rebalance_day: bool,
        result: Dict[str, Any],
    ) -> None:
        if rt is None or not getattr(rt, "manual_allocation_mode", False) or not is_rebalance_day:
            return
        obs = self._manual_allocation_rebalance_observation(
            prices_df, date_str, dict(state.target_weights or {})
        )
        if not obs:
            return
        result["rebalance_observation"] = obs
        for ev in reversed(state.event_log):
            if ev.get("date") != date_str:
                continue
            et = ev.get("type", "") or ev.get("event_type", "")
            st = ev.get("stage", "")
            if et == "init":
                ev["rebalance_observation"] = obs
                break
            if et == "subjective":
                ev["rebalance_observation"] = obs
                break
            if et == "monthly":
                ev["rebalance_observation"] = obs
                break
            if et == "vol_reset" and st == "execute":
                ev["rebalance_observation"] = obs
                break
    
    @staticmethod
    def _first_trade_on_or_after(
        preset_date_str: str, price_index: pd.Index
    ) -> Optional[pd.Timestamp]:
        try:
            d = normalize_calendar_timestamp(pd.Timestamp(str(preset_date_str)[:10]))
        except Exception:
            return None
        idx = price_index[price_index >= d]
        if len(idx) == 0:
            return None
        return normalize_calendar_timestamp(idx[0])

    def _normalize_manual_weight_row(
        self,
        weights_raw: Any,
        asset_cols: List[str],
        auto_normalize: bool,
    ) -> Dict[str, float]:
        out: Dict[str, float] = {a: 0.0 for a in asset_cols}
        if isinstance(weights_raw, dict):
            for k, v in weights_raw.items():
                ks = str(k).strip()
                if ks not in out:
                    continue
                try:
                    out[ks] = float(v)
                except (TypeError, ValueError):
                    out[ks] = 0.0
        # 对齐回测引擎 (app/backtesting/engine.py 第440-455行) 的权重处理逻辑：
        # 仅当 auto_normalize=True 时归一化；auto_normalize=False 时保持原始权重，
        # 支持杠杆配置（权重和可大于 1.0），避免与回测端结果不一致。
        if auto_normalize:
            tot = sum(out.values())
            if tot > 0:
                out = {a: out[a] / tot for a in asset_cols}
        return out

    def _initial_manual_weights_from_params(
        self, asset_cols: List[str], merged_params: Dict[str, Any]
    ) -> Dict[str, float]:
        mw = merged_params.get("manual_weights")
        first_auto = False
        raw_adj = merged_params.get("manual_weight_adjustments")
        if isinstance(raw_adj, list) and raw_adj:
            first = raw_adj[0]
            if isinstance(first, dict):
                first_auto = bool(first.get("auto_normalize", False))
        w = self._normalize_manual_weight_row(
            mw if isinstance(mw, dict) else {}, asset_cols, first_auto
        )
        if sum(w.values()) <= 0 and asset_cols:
            return {a: 1.0 / len(asset_cols) for a in asset_cols}
        return w

    def _build_manual_preset_rebalance_map(
        self,
        prices_df: pd.DataFrame,
        trade_dates: List,
        skip_excluded_dates: List[str],
        merged_params: Dict[str, Any],
        rt: MonitorRuntimeConfig,
    ) -> dict:
        """主观配置：按 parameters.manual_weight_adjustments 在交易日执行调仓（与回测 preset 日对齐）。"""
        excluded = {
            normalize_calendar_timestamp(d) for d in skip_excluded_dates
        }
        rebalance_map: Dict[Any, Any] = {}
        raw = merged_params.get("manual_weight_adjustments")
        entries: List[dict] = []
        if isinstance(raw, list):
            entries = [x for x in raw if isinstance(x, dict) and x.get("date")]
        asset_cols = list(rt.asset_list) if rt else list(prices_df.columns)
        price_index = prices_df.index
        for item in entries:
            wraw = item.get("weights")
            if not isinstance(wraw, dict):
                continue
            nonzero = False
            for v in wraw.values():
                try:
                    if float(v or 0) != 0:
                        nonzero = True
                        break
                except (TypeError, ValueError):
                    nonzero = True
                    break
            if not nonzero:
                continue
            exec_ts = self._first_trade_on_or_after(str(item["date"]), price_index)
            if exec_ts is None:
                logger.warning(f"主观预设调仓日无可用交易日: {item.get('date')}")
                continue
            while exec_ts in excluded:
                nxt = price_index[price_index > exec_ts]
                if len(nxt) == 0:
                    exec_ts = None
                    break
                exec_ts = normalize_calendar_timestamp(nxt[0])
            if exec_ts is None:
                continue
            auto_norm = bool(item.get("auto_normalize", False))
            w = self._normalize_manual_weight_row(wraw, asset_cols, auto_norm)
            preset_label = str(item.get("date"))[:10]
            rebalance_map[exec_ts] = {"weights": w, "calc_date": preset_label}
        return rebalance_map

    def _build_monthly_rebalance_map(
        self,
        prices_df: pd.DataFrame,
        trade_dates: List,
        skip_excluded_dates: List[str],
        rt: Optional[MonitorRuntimeConfig] = None,
        merged_params: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """混合动量：月末 T+2；主观配置：预设调仓日。"""
        merged_params = merged_params or {}
        if prices_df is None or getattr(prices_df, "empty", True):
            logger.warning("月度调仓映射跳过：价格数据为空")
            return {}
        if rt is not None and getattr(rt, "manual_allocation_mode", False):
            return self._build_manual_preset_rebalance_map(
                prices_df, trade_dates, skip_excluded_dates, merged_params, rt
            )
        trade_dates_ts = [normalize_calendar_timestamp(d) for d in trade_dates]
        excluded = {
            normalize_calendar_timestamp(d) for d in skip_excluded_dates
        }
        
        all_dates = prices_df.index[prices_df.index <= prices_df.index[-1]]
        
        month_end_dates = []
        date_series = pd.Series(all_dates, index=all_dates)
        for (year, month), group in date_series.groupby([date_series.index.year, date_series.index.month]):
            month_end = normalize_calendar_timestamp(group.index[-1])
            month_end_dates.append(month_end)
        
        month_end_dates.sort()
        
        rebalance_map = {}
        
        for calc_date in month_end_dates:
            try:
                selection_result = self.engine.run_asset_selection(
                    prices_df, calc_date, rt=rt
                )
                weight_result = self.engine.run_weight_calculation(
                    prices_df, selection_result, calc_date, rt=rt
                )
                asset_cols = list(prices_df.columns)
                weight_dict = {
                    asset: weight_result.weights.get(asset, 0.0) for asset in asset_cols
                }
            except Exception as e:
                logger.warning(f"{calc_date.strftime('%Y-%m-%d')} 权重计算失败: {e}")
                continue
            
            future_dates = [d for d in trade_dates_ts if d > calc_date]
            if len(future_dates) >= 2:
                execute_date = future_dates[1]
            elif len(future_dates) == 1:
                execute_date = future_dates[0]
            else:
                continue
            
            while execute_date in excluded:
                idx = trade_dates_ts.index(execute_date)
                if idx + 1 < len(trade_dates_ts):
                    execute_date = trade_dates_ts[idx + 1]
                else:
                    break
            
            rebalance_map[execute_date] = {
                'weights': weight_dict,
                'calc_date': calc_date.strftime('%Y-%m-%d'),
            }
        
        return rebalance_map
    
    def _get_prices_for_date(self, prices_df: pd.DataFrame, date: pd.Timestamp) -> dict:
        """获取指定日期的价格数据"""
        if date in prices_df.index:
            return prices_df.loc[date].to_dict()
        return {}
    
    def _get_override_for_date(self, overrides: List[dict], date_str: str) -> Optional[dict]:
        """获取指定日期的 pending 主观调仓指令"""
        pending = [o for o in overrides if o.get('status') == 'pending' and o.get('execute_date') == date_str]
        if not pending:
            return None
        pending.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return pending[0]

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

    # ============================================================
    # 查询接口
    # ============================================================
    
    async def get_nav_history(self, monitor_id: str,
                               start_date: str = None, end_date: str = None) -> List[dict]:
        """获取净值历史，支持日期范围筛选"""
        state = await self.get_state(monitor_id)
        if not state:
            return []
        
        history = state.nav_history
        
        if start_date:
            history = [h for h in history if h['date'] >= start_date]
        if end_date:
            history = [h for h in history if h['date'] <= end_date]
        
        return history
    
    async def get_events(self, monitor_id: str,
                          event_type: str = None, limit: int = 50) -> List[dict]:
        """获取事件日志，支持类型筛选
        
        事件类型：
        - init: 初始化
        - monthly: 月度调仓
        - vol_reset: 波动率重置（通过 stage 字段区分 trigger/execute）
        - subjective: 主观调仓
        """
        state = await self.get_state(monitor_id)
        if not state:
            return []
        
        events = state.event_log
        
        if event_type:
            # 支持新的统一类型名和旧类型名的兼容筛选
            type_mapping = {
                'monthly_rebalance': 'monthly',
                'vol_reset_trigger': 'vol_reset',
                'vol_reset_execute': 'vol_reset',
                'subjective_rebalance': 'subjective',
            }
            # 将旧类型名转换为新类型名
            normalized_type = type_mapping.get(event_type, event_type)
            events = [e for e in events if e.get('type') == normalized_type]
        
        events = sorted(events, key=lambda x: x.get('date', ''), reverse=True)
        
        return events[:limit]
    
    async def get_performance(self, monitor_id: str) -> dict:
        """计算并返回绩效指标"""
        state = await self.get_state(monitor_id)
        if not state:
            return {}
        
        ps = self._state_to_portfolio_state(state)
        perf = self.reporter.calc_performance(ps)
        
        return {
            'cumulative_return': perf.cumulative_return,
            'annual_return': perf.annual_return,
            'annual_volatility': perf.annual_vol,
            'max_drawdown': perf.max_drawdown,
            'sharpe_ratio': perf.sharpe_ratio,
            'calmar_ratio': perf.annual_return / abs(perf.max_drawdown) if perf.max_drawdown != 0 else 0,
            'day_count': state.day_count,
            'total_trading_cost': state.total_trading_cost,
            'total_replication_cost': state.total_replication_cost,
            'vol_reset_count': state.vol_reset_count,
        }
    
    async def get_daily_report(self, monitor_id: str, date: str) -> Optional[dict]:
        """获取指定日期的日报数据"""
        doc = await self.reports_collection.find_one({
            "monitor_id": monitor_id,
            "date": date
        })
        if doc:
            doc['_id'] = str(doc['_id'])
            return doc
        return None
    
    async def get_report_list(self, monitor_id: str, skip: int = 0, limit: int = 30) -> List[dict]:
        """获取日报列表"""
        cursor = self.reports_collection.find(
            {"monitor_id": monitor_id}
        ).sort("date", -1).skip(skip).limit(limit)
        
        result = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            result.append(doc)
        
        return result
    
    async def get_signal_status(self, monitor_id: str) -> dict:
        """获取当前信号状态
        
        返回数据结构：
        - monthly_rebalance: 月度调仓信息（next_date, days_until, last_date）
        - vol_reset: 波动率重置信息（threshold, current_volatility, status, distance_to_trigger, vol_windows）
        - pending_rebalance: 待执行调仓（如有）
        - volatility_history: 波动率历史（用于趋势图）
        """
        state = await self.get_state(monitor_id)
        if not state:
            return {}

        rt = await self._runtime_for_reads(monitor_id)
        price_cols = list(rt.asset_list) if rt else None
        prices_df = await self.async_provider.load_prices(asset_columns=price_cols)
        prices_df = slice_prices_df(prices_df, rt)
        trade_dates = await self.async_provider.load_trade_dates()
        trade_dates = self._coerce_trade_dates(trade_dates, prices_df)
        current_date = normalize_calendar_timestamp(state.date)
        asset_list = list(rt.asset_list) if rt else list(config.ASSET_LIST)
        
        # ===== 月度调仓信息 =====
        next_monthly = self.detector.get_next_rebalance_date(current_date, trade_dates)
        
        # 查找上次调仓执行日期（从 event_log 中查找，包括所有类型的调仓执行）
        # 兼容新旧事件格式
        last_rebalance_date = None
        if state.event_log:
            for event in reversed(state.event_log):
                event_type = event.get('type', '') or event.get('event_type', '')
                stage = event.get('stage', '')
                
                # 判断是否为调仓执行事件（不仅限于月度）
                is_rebalance_execute = False
                # 旧格式
                if event_type in ('monthly_rebalance', 'vol_reset_execute', 'subjective_rebalance'):
                    is_rebalance_execute = True
                # 新格式
                elif event_type == 'monthly':
                    is_rebalance_execute = True
                elif event_type == 'vol_reset' and stage == 'execute':
                    is_rebalance_execute = True
                elif event_type == 'subjective':
                    is_rebalance_execute = True
                elif event_type == 'init':
                    is_rebalance_execute = True
                
                if is_rebalance_execute:
                    last_rebalance_date = event.get('date')
                    break
        
        # 如果有 pending_rebalance，其 execute_date 也是候选
        next_pending = None
        if state.pending_rebalance:
            next_pending = state.pending_rebalance.get('execute_date')
        
        # 取所有候选日期中最近的一个作为"下次调仓日"
        candidates = []
        if next_monthly:
            candidates.append(next_monthly)
        if next_pending:
            candidates.append(next_pending)
        next_rebal = min(candidates) if candidates else None
        
        # 计算距下次调仓天数
        days_until = None
        if next_rebal:
            next_rebal_ts = normalize_calendar_timestamp(next_rebal)
            trade_dates_ts = list(trade_dates)
            if current_date in trade_dates_ts and next_rebal_ts in trade_dates_ts:
                current_idx = trade_dates_ts.index(current_date)
                next_idx = trade_dates_ts.index(next_rebal_ts)
                days_until = next_idx - current_idx
            else:
                # 使用自然日计算
                days_until = (next_rebal_ts - current_date).days
        
        # ===== 波动率信息 =====
        threshold = (
            float(rt.vol_trigger_threshold) * 100
            if rt
            else float(config.VOL_TRIGGER_THRESHOLD) * 100
        )
        
        # 1. 当前实时波动率（使用当前权重）
        current_volatility, vol_windows = self.vol_calculator.calc_current_volatility(
            prices_df,
            dict(state.positions_local),
            dict(state.last_rebalance_fx),
            state.nav,
            state.date,
            asset_list=asset_list,
        )
        
        # 2. 波动率历史趋势（使用每个日期实际生效的权重）
        volatility_history = self.vol_calculator.calc_volatility_history(
            prices_df,
            list(state.event_log),
            state.date,
            asset_list=asset_list,
        )
        
        # 3. 状态判断
        status, distance_to_trigger = self.vol_calculator.calc_status(
            current_volatility, threshold_pct=threshold
        )
        
        # ===== 从 event_log 提取调仓历史 =====
        rebalance_history = []
        if state.event_log:
            for event in state.event_log:
                event_type = event.get('type', '') or event.get('event_type', '')
                stage = event.get('stage', '')
                
                # 判断是否为调仓执行事件
                is_rebalance = False
                unified_type = ''
                
                # 旧格式
                if event_type == 'monthly_rebalance':
                    is_rebalance = True
                    unified_type = 'monthly'
                elif event_type == 'vol_reset_execute':
                    is_rebalance = True
                    unified_type = 'vol_reset'
                elif event_type == 'subjective_rebalance':
                    is_rebalance = True
                    unified_type = 'subjective'
                # 新格式
                elif event_type == 'monthly':
                    is_rebalance = True
                    unified_type = 'monthly'
                elif event_type == 'vol_reset' and stage == 'execute':
                    is_rebalance = True
                    unified_type = 'vol_reset'
                elif event_type == 'subjective':
                    is_rebalance = True
                    unified_type = 'subjective'
                elif event_type == 'init':
                    is_rebalance = True
                    unified_type = 'init'
                
                if is_rebalance:
                    rebalance_history.append({
                        'date': event.get('date', ''),
                        'type': unified_type,
                        'description': event.get('description', ''),
                        'old_weights': event.get('old_weights', None),
                        'new_weights': event.get('new_weights', None),
                        'trading_cost': event.get('trading_cost', 0),
                        'scale_factor': event.get('scale_factor', None),
                        'rebalance_observation': event.get('rebalance_observation'),
                    })
            
            # 按日期倒序排列（最近的在前）
            rebalance_history.sort(key=lambda x: x['date'], reverse=True)
        
        # ===== 构建返回结果 =====
        # 优先使用 state.last_rebalance_date，若无则使用从 event_log 提取的
        final_last_rebalance_date = state.last_rebalance_date or last_rebalance_date
        
        result = {
            'monthly_rebalance': {
                'next_date': next_rebal or '无',
                'days_until': days_until,
                'last_date': final_last_rebalance_date,
            },
            'vol_reset': {
                'threshold': threshold,
                'current_volatility': current_volatility,  # 百分比形式
                'status': status,
                'distance_to_trigger': distance_to_trigger,
                'vol_windows': vol_windows,
            },
            'pending_rebalance': None,
            'volatility_history': volatility_history,
            'rebalance_history': rebalance_history,
            'last_rebalance_date': final_last_rebalance_date,
        }
        
        if state.pending_rebalance:
            result['pending_rebalance'] = {
                'type': state.pending_rebalance.get('rebalance_type'),
                'execute_date': state.pending_rebalance.get('execute_date'),
                'description': '月度调仓' if state.pending_rebalance.get('rebalance_type') == 'monthly' else '波动率重置',
            }
        
        return result
    
    async def get_positions(self, monitor_id: str) -> dict:
        """获取当前持仓明细
        
        返回重新设计的字段：
        - name: 资产名称
        - code: 资产代码
        - asset_class: 资产类别（权益/固定收益/大宗商品）
        - current_weight: 当前权重%（基于市值）
        - daily_change: 当日涨跌%（底层资产价格变动）
        - currency: 计价货币
        """
        state = await self.get_state(monitor_id)
        if not state or state.nav <= 0:
            return {'positions': [], 'total_leverage': 0}

        rt = await self._runtime_for_reads(monitor_id)
        base_al = list(rt.asset_list) if rt else list(config.ASSET_LIST)
        al = self._asset_keys_for_positions_attribution(
            base_al, state.positions_cny, state.target_weights
        )

        model = None
        if self._is_strategy_model_monitor_id(monitor_id):
            model = await StrategyModelService().get_model(monitor_id)
        names_lookup = await self._asset_master_names_by_code(model, al)
        
        # 获取所有资产的 daily_change
        daily_changes = await self._get_asset_daily_changes(state.date, asset_names=al)
        
        positions = []
        for asset in al:
            pos_cny = float(state.positions_cny.get(asset, 0.0) or 0.0)
            current_w = pos_cny / state.nav if state.nav else 0.0
            display_name = resolve_monitor_asset_display_label(asset, names_lookup)
            positions.append({
                'name': display_name,
                'code': asset,
                'asset_class': resolve_asset_class_for_monitor(asset),
                'current_weight': round(current_w * 100, 2),
                'value_cnh': round(pos_cny, 2),
                'daily_change': daily_changes.get(asset),
                'currency': resolve_asset_currency_for_monitor(asset),
            })
        
        total_leverage = sum(p['current_weight'] for p in positions) / 100
        
        return {
            'positions': positions,
            'total_leverage': round(total_leverage, 4),
            'nav': state.nav,
            'date': state.date,
        }
    
    async def get_daily_attribution(self, monitor_id: str, date: str = None) -> dict:
        """获取指定日期的损益归因数据
        
        每个资产贡献 = 该资产持仓权重 × 该资产当日收益率 × 前一日组合净值
        
        Args:
            monitor_id: 监控实例 ID
            date: 目标日期 YYYY-MM-DD，默认使用 state.date（最新日期）
            
        Returns:
            {
                "date": "YYYY-MM-DD",
                "attributions": [{name, code, asset_class, weight, daily_change, contribution, currency}, ...],
                "total_pnl": float,
                "prev_nav": float,
                "current_nav": float
            }
        """
        state = await self.get_state(monitor_id)
        if not state or not state.nav_history or len(state.nav_history) < 2:
            return {"date": None, "attributions": [], "total_pnl": 0, "prev_nav": 0, "current_nav": 0}
        
        # 确定目标日期
        target_date = date or state.date
        
        # 找到目标日期和前一日的 nav_history 记录
        history = state.nav_history
        target_record = None
        prev_record = None
        
        for i, rec in enumerate(history):
            if rec.get('date') == target_date:
                target_record = rec
                if i > 0:
                    prev_record = history[i - 1]
                break
        
        if not target_record or not prev_record:
            # 如果找不到精确日期，使用最后两条记录
            target_record = history[-1]
            prev_record = history[-2]
            target_date = target_record.get('date', state.date)
        
        prev_nav = prev_record.get('nav', 1000)
        current_nav = target_record.get('nav', prev_nav)
        total_pnl = current_nav - prev_nav
        
        # 获取各资产的当日权重（使用 target_weights 或 positions_cny/nav 计算）
        # 注意：target_weights 是小数形式（如 0.10 表示 10%）
        weights = state.target_weights or {}

        rt = await self._runtime_for_reads(monitor_id)
        base_al = list(rt.asset_list) if rt else list(config.ASSET_LIST)
        al = self._asset_keys_for_positions_attribution(
            base_al, state.positions_cny, state.target_weights
        )

        model = None
        if self._is_strategy_model_monitor_id(monitor_id):
            model = await StrategyModelService().get_model(monitor_id)
        names_lookup = await self._asset_master_names_by_code(model, al)
        
        # 获取各资产的日收益率
        daily_changes = await self._get_asset_daily_changes(target_date, asset_names=al)
        
        attributions = []
        
        nav_live = float(state.nav or 0.0)
        for asset_name in al:
            try:
                weight = float(weights.get(asset_name, 0) or 0)
            except (TypeError, ValueError):
                weight = 0.0
            if abs(weight) < 1e-15 and nav_live > 0:
                weight = float(state.positions_cny.get(asset_name, 0) or 0) / nav_live
            
            daily_change = daily_changes.get(asset_name)
            if daily_change is None:
                daily_change = 0.0
            
            contribution = weight * daily_change / 100 * prev_nav
            
            ac = resolve_asset_class_for_monitor(asset_name)
            asset_class = ac if ac else '其他'
            currency = resolve_asset_currency_for_monitor(asset_name)
            display_name = resolve_monitor_asset_display_label(asset_name, names_lookup)
            
            attributions.append({
                "name": display_name,
                "code": asset_name,
                "asset_class": asset_class,
                "weight": round(weight * 100, 4),
                "daily_change": round(daily_change, 4),
                "contribution": round(contribution, 2),
                "currency": currency
            })
        
        # 按贡献绝对值降序排列
        attributions.sort(key=lambda x: abs(x['contribution']), reverse=True)
        
        return {
            "date": target_date,
            "attributions": attributions,
            "total_pnl": round(total_pnl, 2),
            "prev_nav": round(prev_nav, 2),
            "current_nav": round(current_nav, 2)
        }

    async def _get_asset_daily_changes(
        self, as_of_date: str, asset_names: Optional[List[str]] = None
    ) -> Dict[str, Optional[float]]:
        """从 asset_prices 集合查询资产的日涨跌幅。
        
        Args:
            as_of_date: 截止日期（YYYY-MM-DD）
            asset_names: 与持仓/行情一致的资产键；默认 config.ASSET_LIST（中文名，全量模式）
            
        Returns:
            {资产键: daily_change_pct}；键与 positions 中使用的标识一致
        """
        result = {}
        prices_collection = self.db[config.MONGO_COLLECTIONS['prices']]
        names = list(asset_names) if asset_names else list(config.ASSET_LIST)
        
        for aid in names:
            if aid in config.ASSET_NAME_TO_CODE:
                stored = stored_price_code(config.ASSET_NAME_TO_CODE[aid])
            else:
                stored = str(aid).strip()

            cursor = prices_collection.find(
                {
                    'asset_code': stored,
                    'date': {'$lte': as_of_date}
                },
                {'date': 1, 'close': 1}
            ).sort('date', -1).limit(2)
            
            prices = await cursor.to_list(length=2)
            
            if len(prices) >= 2:
                latest_close = prices[0].get('close')
                prev_close = prices[1].get('close')
                if latest_close and prev_close and prev_close != 0:
                    daily_change = (latest_close / prev_close - 1) * 100
                    result[aid] = round(daily_change, 2)
                else:
                    result[aid] = None
            else:
                result[aid] = None
        
        return result

    # ============================================================
    # 日报持久化
    # ============================================================
    
    async def _save_daily_report(self, monitor_id: str, report_data: dict) -> None:
        """保存日报到 MongoDB monitor_daily_reports 集合"""
        perf: Dict[str, Any] = {}
        ro = report_data.get("rebalance_observation")
        if isinstance(ro, dict) and ro:
            perf["rebalance_observation"] = ro

        report = MonitorDailyReport(
            monitor_id=monitor_id,
            date=report_data['date'],
            nav=report_data['nav'],
            daily_return=report_data.get('nav_change_pct', 0.0),
            total_leverage=report_data.get('total_leverage', 1.0),
            positions=[
                {'asset': asset, 'weight': w}
                for asset, w in report_data.get('asset_weights', {}).items()
            ],
            signals={
                'rebalance_executed': report_data.get('rebalance_executed', False),
                'rebalance_type': report_data.get('rebalance_type'),
                'vol_reset_triggered': report_data.get('vol_reset_triggered', False),
            },
            performance=perf,
            created_at=datetime.now()
        )
        
        await self.reports_collection.replace_one(
            {"monitor_id": monitor_id, "date": report_data['date']},
            report.to_dict(),
            upsert=True
        )
