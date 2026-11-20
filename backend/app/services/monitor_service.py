# -*- coding: utf-8 -*-
"""
监控服务层 - 编排日常组合监控调仓流程

职责：
1. 管理组合监控状态（MongoDB）
2. 编排每日监控流程（损益更新、调仓执行、波动率监测）
3. 管理主观调仓指令
4. 提供查询接口（净值历史、持仓、绩效、信号状态）
"""

import asyncio
import uuid
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from loguru import logger
from bson import ObjectId

from app.config.database import Database
from app.models.monitor import (
    MonitorState, SubjectiveOverride,
    OverrideStatus, BatchKind, BatchRunMode, BatchStatus,
)
from app.services import monitor_batch_service
from app.services.monitor_task_service import make_thread_bridge
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
from app.monitor.operation_recorder import OperationRecorderMixin
from app.monitor.risk_alert_recorder import RiskAlertRecorderMixin
from app.services.strategy_model_service import StrategyModelService
from app.services.asset_service import AssetService


def _bson_safe(value: Any) -> Any:
    """递归转成 BSON 可存的基本类型（numpy 标量 / datetime）。

    信号快照等「计算结果直接落库」的产物里会混入 numpy 标量，
    不做转换会在 ``update_one`` 阶段抛 ``InvalidDocument``。
    """
    if isinstance(value, dict):
        return {str(k): _bson_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bson_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:  # noqa: BLE001
            pass
    return value


class MonitorService(
    ManualPresetMixin,
    RebalancePlanningMixin,
    DailyStepperMixin,
    MonitorQueryMixin,
    OperationRecorderMixin,
    RiskAlertRecorderMixin,
):
    """监控服务 - 编排整个日常监控调仓流程

    方法群按职责拆分至 Mixin（app/monitor/ 下）：
    - ManualPresetMixin：主观配置预设调仓步进与观察指标
    - RebalancePlanningMixin：调仓映射构建与权重规划
    - DailyStepperMixin：单日推演（步骤 A-F）
    - MonitorQueryMixin：读取查询接口与日报持久化
    - OperationRecorderMixin：操作指令记录（monitor_operations）
    - RiskAlertRecorderMixin：风险预警计算与落库（monitor_risk_alerts）
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
        # 本次运行使用的发布/实盘版本与快照指纹
        self._config_versions: Optional[Dict[str, Any]] = None
        # 研究员策略代码（sharpe_18 / hybrid_12），用于路由独立引擎
        self._researcher_code: Optional[str] = None
        # 非价格截面面板（按策略 get_extra_panels 声明预加载，注入 adapter pipeline；
        # 与回测通道 DataFeed.panels 同源，无声明时为空、存量策略零影响）
        self._monitor_panels: Dict[str, Any] = {}
        self._monitor_panel_dates: Dict[str, Any] = {}
        # ── 批次上下文（一次运行 = 一个批次，产物按 batch_id 版本化）──
        # 由 run_init / run_daily / run_range / 组合管线在推演开始时写入，
        # 其余落库点统一读取，避免把 batch_id 透传进每一个 Mixin 方法签名。
        # 注意：operation_service / risk_alert_service 是跨 MonitorService 实例共享的
        # 类级单例，对它们的调用仍必须显式传 batch_id。
        self._batch_id: Optional[str] = None
        self._parent_batch_id: Optional[str] = None
        self._batch_started_at: Optional[datetime] = None
        # 本次批次对应的策略模型 ID（组合/系统策略为 source_ref，研究员为 None）
        self._batch_source_model_id: Optional[str] = None
        # 本次批次的配置快照（组合监控写入 sub_strategies），收尾时回写批次文档
        self._batch_config_snapshot: Dict[str, Any] = {}
        # 本次批次模型轨的绩效结果（_save_monitor_backtest_record 产出，供批次摘要复用）
        self._batch_performance: Optional[Dict[str, Any]] = None

    async def _save_risk_alerts_from_result(
        self, monitor_id: str, result: Dict[str, Any]
    ) -> int:
        """落库单个交易日结果中的风险预警（步骤E3 产出）。

        只在实际轨主循环调用：模型轨（_step_model_track_day）不传
        enable_risk_alerts，result 里没有预警，天然不会重复写批。
        """
        alerts = result.get("risk_alerts") if isinstance(result, dict) else None
        if not alerts:
            return 0
        signal_date = str(result.get("date") or "")[:10]
        return await self.save_risk_alerts(
            monitor_id=monitor_id,
            monitor_kind="strategy",
            signal_date=signal_date,
            alerts=alerts,
        )

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
        # 与系统策略同源判定：研究员策略是否启用波动率风控、阈值取哪个键
        from app.monitor.monitor_runtime import resolve_vol_control
        (
            vol_control_enabled,
            vol_trigger,
            vol_threshold_source,
            vol_control_reason,
        ) = resolve_vol_control(params)
        return MonitorRuntimeConfig(
            asset_list=strategy.asset_codes,
            target_vol=params.get("target_vol", 0.05),
            vol_trigger_threshold=(
                vol_trigger if vol_trigger is not None
                else float(params.get("vol_trigger_threshold", 0.06))
            ),
            max_leverage=params.get("max_total_leverage", 4.0),
            weight_caps=strategy.weight_caps or {},
            selector_type=params.get("selector_type"),
            strategy_params=params,
            asset_names=strategy.asset_name_map or None,
            vol_control_enabled=vol_control_enabled,
            vol_threshold_source=vol_threshold_source,
            vol_control_reason=vol_control_reason,
            # 研究员策略 sharpe_18/hybrid_12 复现原型，必须用 Mongo trade_dates
            # 交易所日历（T+2 执行、月末调仓映射依赖完整交易日历）；与系统策略
            # 的资产价格日历口径明确区分，trade_dates 仅在此生效
            calendar_source="trade_dates",
        )

    async def _prepare_monitor_run(
        self, monitor_id: str, load_panels: bool = True
    ) -> None:
        """解析实盘模型运行时配置并配置 PortfolioTracker；无实盘模型时回退全局 config。

        Args:
            monitor_id: 监控实例 ID（策略模型回测即模型 ObjectId）
            load_panels: 是否在 prepare 阶段加载非价格截面面板。run_daily 传 False，
                由调用方在确认「确有新交易日」后再调 ``_load_monitor_panels``，
                避免 no-op 日白做全量面板逐期建表；run_init / run_range 保持 True。
        """
        self._monitor_runtime = None
        self._merged_monitor_params = {}
        self._config_versions = None
        self._engine_adapter = None
        self._monitor_panels = {}
        self._monitor_panel_dates = {}
        self._researcher_code = None
        self._gross_policy_warned = False
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
        snap = getattr(model, "live_snapshot", None) or {}
        if not getattr(model, "live_publish_enabled", False) or not isinstance(snap, dict) or not snap:
            raise ValueError(
                f"策略「{model.name}」未实盘发布或实盘快照缺失，无法运行日常监控"
            )
        # 生命周期准入门禁（S14）：日常监控属于 live 运行态，要求已处于 live 阶段。
        # LIFECYCLE_ENFORCE=False 时零副作用；拒绝时写 rejected 事件并抛错。
        from app.services.strategy_lifecycle_service import StrategyLifecycleService

        await StrategyLifecycleService().enforce(
            "live",
            model,
            action="monitor_run",
            source="monitor",
            require_current=True,
        )
        # 主观策略调仓权重等参数只读实盘快照，不再读取当前文档
        self._merged_monitor_params = merge_parameters_with_top_level_windows(
            None, snap.get("parameters") or {}
        )
        self._config_versions = {
            "template_code": snap.get("template_code"),
            "published_version": model.published_version,
            "live_version": model.live_version,
            "live_published_version": model.live_published_version,
            "config_fingerprint": model.config_fingerprint,
        }
        # 跨通道对齐（S13）：补齐策略身份、配置版本与资产池引用。
        # 只加键、不改既有 5 键；解析失败只 warn，不影响监控启动。
        # 三者皆非空时才能与回测运行按 config_fingerprint 直接对齐。
        try:
            from app.services.strategy_registry_service import StrategyRegistryService
            from app.services.strategy_version_service import StrategyVersionService

            template_code = self._config_versions.get("template_code")
            if template_code:
                entry = await StrategyRegistryService().get_by_template_code(template_code)
                if entry and entry.strategy_id:
                    self._config_versions["strategy_id"] = entry.strategy_id
            version_id = await StrategyVersionService().latest_version_id(monitor_id)
            if version_id:
                self._config_versions["config_version_id"] = version_id
            universe_ref = snap.get("asset_universe_ref")
            if universe_ref:
                self._config_versions["asset_universe_ref"] = str(universe_ref)
        except Exception as exc:  # noqa: BLE001 —— 身份补全失败不得阻断监控
            logger.warning(f"[监控] 运行身份补全失败（不影响监控）: {exc}")
        # 确保 asset_names 已填充（从资产主数据查询）
        await self._ensure_model_asset_names(model)
        rt = monitor_runtime_from_model(model)
        if rt is None:
            raise ValueError(
                f"策略「{model.name}」实盘快照无效，请重新发布后实盘发布"
            )
        self._monitor_runtime = rt
        self.tracker.configure(rt)
        if load_panels:
            await self._load_monitor_panels(rt)

    async def _load_monitor_panels(self, rt) -> None:
        """按策略声明预加载非价格截面面板，供 _get_engine_adapter 注入 pipeline.

        通用、声明驱动：策略未声明 get_extra_panels 时为 no-op（存量策略零影响）；
        与回测通道共用 data_feed.load_strategy_panels，口径单源。加载失败不静默
        兜底——面板置空后由 allocate 运行时抛「未注入面板」明确错误。
        """
        template_code = getattr(rt, "template_code", "") or ""
        if not template_code:
            return
        from app.backtesting.data_feed import load_strategy_panels
        try:
            panels, panel_dates = await load_strategy_panels(template_code, None)
        except Exception as exc:
            logger.warning(f"[监控] {template_code} 截面面板加载失败：{exc}")
            return
        self._monitor_panels = panels or {}
        self._monitor_panel_dates = panel_dates or {}

    def _inject_monitor_panels(self) -> None:
        """把预加载的截面面板注入已构建的 adapter pipeline（通用；无面板时 no-op）."""
        panels = getattr(self, "_monitor_panels", None)
        if not panels or self._engine_adapter is None:
            return
        pipeline = getattr(self._engine_adapter, "pipeline", None)
        if pipeline is not None and hasattr(pipeline, "set_panels"):
            pipeline.set_panels(panels, getattr(self, "_monitor_panel_dates", None))

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
        if not getattr(model, "live_publish_enabled", False) or not isinstance(snap, dict) or not snap:
            raise ValueError(
                f"组合「{model.name}」未实盘发布或实盘快照缺失，无法运行日常监控"
            )
        if not snap.get("sub_strategies"):
            raise ValueError(
                f"组合「{model.name}」实盘快照缺少子策略配置，请重新发布后实盘发布"
            )
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
        progress_cb=None,
    ) -> dict:
        """复用组合回测管线运行组合监控，并将结果落库为 MonitorState。

        监控与回测使用同一引擎与口径，保证二者结果一致（monitor == backtest）。

        Args:
            start_date: YYYY-MM-DD
            end_date: pd.Timestamp / datetime / 'YYYY-MM-DD' / 'YYYYMMDD'
            progress_cb: 后台任务的进度回调（组合路径按「子策略 + 3 阶段」步进上报）
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

        # 组合监控固定零费率（gross）。组合回测的费率另从组合配置取值，
        # 两者不同时两条净值曲线会逐日分叉，因此把本路径实际生效的值
        # 记进 execution_policy，比对时能直接归因到成本口径。
        monitor_commission_rate = 0.0
        monitor_slippage = 0.0
        pipeline = await run_portfolio_monitor_pipeline(
            portfolio_model_id=portfolio_info["model_id"],
            start_date=start_yyyymmdd,
            end_date=end_yyyymmdd,
            initial_nav=portfolio_info["initial_nav"],
            rebalance_freq=portfolio_info["rebalance_freq"],
            commission_rate=monitor_commission_rate,
            slippage=monitor_slippage,
            progress_cb=progress_cb,
        )

        fields = build_monitor_state_fields(
            monitor_id=monitor_id,
            strategy_model_id=portfolio_info["model_id"],
            pipeline=pipeline,
            initial_nav=portfolio_info["initial_nav"],
        )
        fields["config_versions"] = pipeline.get("config_versions")
        self._config_versions = pipeline.get("config_versions")
        # 批次归属：组合状态同样一个批次一条文档（save_state 会再次强制覆盖）
        fields["batch_id"] = self._current_batch_id()

        # ── 策略维度操作指令：组合层 + 各子策略（全量重建，幂等）──
        await self._sync_portfolio_operations(monitor_id, pipeline)

        # ── 子策略模型口径绩效（来源回测管线 sub_results）──
        fields["sub_strategy_performance"] = [
            {
                "model_id": r.model_id,
                "name": r.name,
                "weight": float(r.weight),
                "annual_return": float(r.annual_return),
                "annual_volatility": float(r.annual_volatility),
                "sharpe_ratio": float(r.sharpe_ratio),
                "max_drawdown": float(r.max_drawdown),
                "annual_return_365": getattr(r, "annual_return_365", None),
                "annual_volatility_365": getattr(r, "annual_volatility_365", None),
                "sharpe_ratio_365": getattr(r, "sharpe_ratio_365", None),
            }
            for r in (pipeline.get("sub_results") or [])
        ]

        # ── 双轨：模型口径=管线输出；实际口径=叠加主观调整 ──
        fields["nav_history_model"] = fields["nav_history"]
        actual_history, applied_overrides = await self._build_portfolio_actual_track(
            monitor_id, pipeline, portfolio_info["initial_nav"]
        )
        if actual_history:
            fields["nav_history"] = actual_history
            fields["date"] = actual_history[-1]["date"]
            fields["nav"] = float(actual_history[-1]["nav"])
            fields["day_count"] = len(actual_history)
            fields["trade_day_count"] = len(actual_history)
        # 存在不早于最近系统再平衡日的主观指令时，持仓展示同步为主观权重（含调仓日比例优化）
        if applied_overrides:
            last_override = applied_overrides[-1]
            last_ovr_date = str(last_override.get("execute_date") or "")[:10]
            if last_ovr_date >= str(fields.get("last_rebalance_date") or ""):
                w = {
                    str(k): float(v)
                    for k, v in (last_override.get("weights") or {}).items()
                }
                fields["target_weights"] = w
                fields["positions_cny"] = {
                    k: float(fields["nav"]) * v for k, v in w.items()
                }

        # 本路径不走 _portfolio_state_to_state，执行口径单独记录
        from app.backtesting.config import BacktestConfig
        from app.backtesting.policy import from_backtest_config

        fields["execution_policy"] = from_backtest_config(
            BacktestConfig(
                name="portfolio_monitor",
                thscodes=[],
                start_date=start_yyyymmdd,
                end_date=end_yyyymmdd,
                rebalance_freq=portfolio_info["rebalance_freq"],
                commission_rate=monitor_commission_rate,
                slippage=monitor_slippage,
            ),
        ).to_dict()

        # ── 批次配置快照：组合必须留下子策略构成，否则事后无法复现这次跑批的输入 ──
        # 只存 batch_summary 会对外输出的五个键 + 少量组合参数，避免批次文档膨胀。
        self._batch_config_snapshot = {
            "template_code": "portfolio",
            "config_versions": pipeline.get("config_versions"),
            "execution_policy": fields.get("execution_policy"),
            "asset_codes": sorted((fields.get("target_weights") or {}).keys()),
            "sub_strategies": [
                {
                    "model_id": item.get("model_id"),
                    "name": item.get("name"),
                    "weight": item.get("weight"),
                }
                for item in (fields.get("sub_strategy_performance") or [])
            ],
            "initial_nav": float(portfolio_info["initial_nav"]),
            "rebalance_freq": portfolio_info["rebalance_freq"],
        }

        # ── 风险预警（组合通道）：用穿透后持仓与行情检测，与策略通道同一套函数 ──
        await self.run_portfolio_risk_alerts(monitor_id, fields)

        state = MonitorState(**fields)
        await self.save_state(state)
        # 绩效页缓存：用组合穿透后权重历史生成调仓日持仓快照
        await self._rebuild_performance_cache(
            monitor_id, weight_history=pipeline.get("weight_history") or []
        )

        perf = pipeline.get("performance")
        annual_return = getattr(perf, "annual_return", None) if perf else None
        # 模型轨绩效 → 批次摘要指标（_finalize_batch_from_result 会优先用返回值里的 performance）
        performance: Optional[Dict[str, Any]] = None
        if perf is not None:
            performance = {
                "total_return": getattr(perf, "total_return", None),
                "annual_return": getattr(perf, "annual_return", None),
                "annual_volatility": getattr(perf, "annual_volatility", None),
                "sharpe_ratio": getattr(perf, "sharpe_ratio", None),
                "max_drawdown": getattr(perf, "max_drawdown", None),
                "calmar_ratio": getattr(perf, "calmar_ratio", None),
            }
        self._batch_performance = performance
        logger.info(
            f"[组合监控] 完成: 最终日期={fields['date']}, 净值={fields['nav']:.2f}, "
            f"调仓次数={len(fields['event_log'])}, 批次={self._current_batch_id()}"
        )
        return {
            "monitor_id": monitor_id,
            "date": fields["date"],
            "nav": fields["nav"],
            "day_count": fields["day_count"],
            "rebalance_count": len(fields["event_log"]),
            "annual_return": annual_return,
            "performance": performance,
            "batch_id": self._current_batch_id(),
        }

    async def _sync_portfolio_operations(
        self, monitor_id: str, pipeline: Dict[str, Any]
    ) -> None:
        """组合策略维度指令落库（组合层 + 各子策略；本批次内全量重建，失败不阻断）。

        删除与写入都必须限定当前批次：组合每次跑批都从零重建指令，不限批次会把
        旧批次已封存的指令（含历史主观调仓）一并抹除。
        """
        try:
            from app.monitor.portfolio_dual_track import extract_portfolio_operations
            batch_id = self._current_batch_id()
            ops = extract_portfolio_operations(pipeline)
            await self.operation_service.delete_by_monitor(monitor_id, batch_id=batch_id)
            n = await self.operation_service.bulk_upsert_executed_operations(
                monitor_id, ops, batch_id=batch_id
            )
            logger.info(f"[组合监控] 策略维度操作指令已写入: {n} 条, 批次={batch_id}")
        except Exception as e:
            logger.warning(f"[组合监控] 策略维度操作指令落库失败（不影响监控）: {e}")

    async def _build_portfolio_actual_track(
        self,
        monitor_id: str,
        pipeline: Dict[str, Any],
        initial_nav: float,
    ) -> tuple:
        """构建组合实际口径净值序列（叠加主观调整），并标记区间内已执行指令。

        主观指令取数口径（批次化后）：
            - ``executed``：**不限批次**。已执行的历史调整是实际轨的一部分，
              新批次从原始起点全量重跑时必须把它们重新叠加上去；
            - ``pending``：**只取当前批次**。``_begin_run_batch`` 已把父批次的
              挂单继承进来，再去读父批次会拿到同一条指令的两份副本。

        ``_collect_effective_overrides`` 按对齐后的执行日去重（同日取 created_at 最新），
        继承文档保留原 created_at，因此两类来源合并也不会重复应用。

        Returns:
            (actual_nav_history, applied_override_docs)
        """
        from app.monitor.portfolio_dual_track import build_portfolio_actual_nav
        batch_id = self._current_batch_id()
        cursor = self.overrides_collection.find({
            "monitor_id": monitor_id,
            "$or": [
                {"status": OverrideStatus.EXECUTED.value},
                {
                    "status": OverrideStatus.PENDING.value,
                    "batch_id": batch_id,
                },
            ],
        })
        overrides = [doc async for doc in cursor]
        actual_history, applied = await build_portfolio_actual_nav(
            pipeline, overrides, initial_nav
        )
        for doc in applied:
            if str(doc.get("status")) == OverrideStatus.PENDING.value:
                oid = doc.get("override_id")
                if oid:
                    await self._mark_override_executed(oid, batch_id=batch_id)
                    await self.operation_service.mark_override_executed(
                        oid, batch_id=batch_id
                    )
        return actual_history, applied

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
    # 批次上下文（一次运行 = 一个批次，产物按 batch_id 版本化）
    # ============================================================

    def _current_batch_id(self) -> str:
        """本次运行的批次号；无运行上下文（脚本/测试直调落库）时回落 ``legacy``。"""
        return monitor_batch_service.normalize_batch_id(self._batch_id)

    async def _detect_batch_source(self, monitor_id: str) -> Dict[str, Optional[str]]:
        """判定监控对象类型与来源标识（kind / source_model_id / researcher_code）。

        单一口径在 :func:`monitor_batch_service.detect_source`（异步提交任务的端点
        预建批次时也走它），这里只做转发，避免两侧判定漂移。
        """
        return await monitor_batch_service.detect_source(monitor_id)

    async def _resolve_parent_batch_id(self, monitor_id: str) -> Optional[str]:
        """解析父批次：增量推进从它读 fold 状态、继承 pending 主观指令。

        优先取最新 ``completed`` 批次；无批次记录（存量实例还没跑过批次化流程）
        时回落 ``monitor_states`` 最近更新文档的批次号，保证存量数据不断链。
        """
        try:
            parent = await monitor_batch_service.resolve_batch_id(monitor_id)
            if parent:
                return parent
            doc = await self.states_collection.find_one(
                {"monitor_id": monitor_id},
                sort=[("updated_at", -1)],
                projection={"batch_id": 1},
            )
            if doc and doc.get("batch_id"):
                return str(doc["batch_id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[监控批次] 父批次解析失败，本次按全新批次处理: {exc}")
        return None

    async def _begin_run_batch(
        self,
        monitor_id: str,
        run_mode: str,
        *,
        batch_id: Optional[str] = None,
        start_date: Optional[str] = None,
        data_date: Optional[str] = None,
        task_id: Optional[str] = None,
        config_snapshot: Optional[Dict[str, Any]] = None,
        inherit_overrides: bool = True,
    ) -> str:
        """推演开始时建立批次上下文，返回本次运行使用的 ``batch_id``。

        - 传入 ``batch_id`` 且库中已有该批次（异步任务先建批次再起跑）→ 直接接管；
        - 否则新建批次，父批次取最新 completed；
        - **方案 A**：新批次建立后立刻把父批次 ``pending`` 的主观指令复制过来，
          已执行的随旧批次封存；
        - 台账写入全程失败只告警并回落 ``legacy``：批次记录不可写时，监控本身
          仍必须能跑完并落库（可用性优先于台账完整性）。
        """
        self._batch_started_at = datetime.now()
        self._batch_id = None
        self._parent_batch_id = None
        self._batch_performance = None

        if batch_id:
            existed = None
            try:
                existed = await monitor_batch_service.get_batch(batch_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[监控批次] 批次 {batch_id} 读取失败，按新建处理: {exc}")
            if existed:
                self._batch_id = monitor_batch_service.normalize_batch_id(batch_id)
                self._parent_batch_id = existed.get("parent_batch_id")
                self._batch_source_model_id = existed.get("source_model_id")
                try:
                    if task_id and not existed.get("task_id"):
                        await monitor_batch_service.attach_task(self._batch_id, task_id)
                    await monitor_batch_service.mark_running(
                        self._batch_id, started_at=self._batch_started_at
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"[监控批次] 置 running 失败（不影响跑批）: {exc}")
                return self._batch_id

        parent = await self._resolve_parent_batch_id(monitor_id)
        source = await self._detect_batch_source(monitor_id)
        self._parent_batch_id = parent
        self._batch_source_model_id = source.get("source_model_id")
        try:
            doc = await monitor_batch_service.create_batch(
                monitor_id,
                kind=str(source.get("kind") or BatchKind.STRATEGY.value),
                run_mode=run_mode,
                task_id=task_id,
                source_model_id=source.get("source_model_id"),
                researcher_code=source.get("researcher_code"),
                parent_batch_id=parent,
                start_date=start_date,
                data_date=data_date,
                config_snapshot=config_snapshot,
                status=BatchStatus.RUNNING.value,
            )
            self._batch_id = monitor_batch_service.normalize_batch_id(doc.get("batch_id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[监控批次] 批次创建失败，本次运行按 legacy 落库: {exc}")
            self._batch_id = None
            return self._current_batch_id()

        if inherit_overrides and parent:
            try:
                await monitor_batch_service.inherit_pending_overrides(
                    monitor_id, parent, self._batch_id
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[监控批次] pending 主观指令继承失败（不影响跑批）: {exc}")
        logger.info(
            "[监控批次] 开始 batch_id={} monitor_id={} run_mode={} parent={}",
            self._batch_id, monitor_id, run_mode, parent or "-",
        )
        return self._batch_id

    async def _finish_run_batch(
        self,
        monitor_id: str,
        *,
        state: Optional[MonitorState] = None,
        state_doc: Optional[Dict[str, Any]] = None,
        performance: Optional[Dict[str, Any]] = None,
        paused: bool = False,
        next_date: Optional[str] = None,
        backtest_record_id: Optional[str] = None,
        end_date: Optional[str] = None,
        config_snapshot: Optional[Dict[str, Any]] = None,
        subjective_override_count: Optional[int] = None,
    ) -> None:
        """推演结束收尾批次：写摘要指标并置 ``completed`` / ``paused``。

        只有走到 ``completed``，本批次产物才对展示端点可见；``paused``
        （主观预设步进停住）对展示不可见，页面回落上一个 completed 批次。
        """
        if not self._batch_id:
            return
        try:
            doc = state_doc
            if doc is None and state is not None:
                doc = state.to_dict()
            if doc is None:
                doc = await self.states_collection.find_one(
                    {"monitor_id": monitor_id, "batch_id": self._batch_id}
                )
            metrics = monitor_batch_service.build_metrics(
                doc,
                performance if performance is not None else self._batch_performance,
                subjective_override_count=subjective_override_count,
            )
            final_end = (
                end_date
                or str((doc or {}).get("date") or "")[:10]
                or None
            )
            duration_ms = None
            if self._batch_started_at:
                duration_ms = int(
                    (datetime.now() - self._batch_started_at).total_seconds() * 1000
                )
            if paused:
                await monitor_batch_service.mark_paused(
                    self._batch_id, end_date=final_end, metrics=metrics,
                    next_date=next_date, duration_ms=duration_ms,
                )
            else:
                snapshot = dict(self._batch_config_snapshot or {})
                snapshot.update(config_snapshot or {})
                await monitor_batch_service.mark_completed(
                    self._batch_id, end_date=final_end, metrics=metrics,
                    backtest_record_id=backtest_record_id, duration_ms=duration_ms,
                    config_snapshot=snapshot or None,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[监控批次] 批次收尾失败（不影响已落库产物）: {exc}")

    async def _persist_signal_snapshot(self, monitor_id: str, state: MonitorState) -> None:
        """把信号页数据物化到本批次状态文档（展示端点纯读表的前提）。

        ``/monitor/signals`` 原本每次请求都要回源行情库算波动率与下次调仓日，
        批次化后展示侧不再持有计算组件，改由跑批收尾时算一次并落库。
        失败只告警：读不到快照时端点返 404，不影响已落库的净值与绩效。
        """
        if not self._batch_id:
            return
        try:
            snapshot = await self.get_signal_status(monitor_id)
            if not snapshot:
                return
            now = datetime.now()
            await self.states_collection.update_one(
                {"monitor_id": monitor_id, "batch_id": self._batch_id},
                {"$set": {
                    "signal_snapshot": _bson_safe(snapshot),
                    "signal_snapshot_at": now,
                }},
            )
            # 同步内存对象：_finish_run_batch 会拿 state.to_dict() 组装批次摘要
            state.signal_snapshot = snapshot
            state.signal_snapshot_at = now
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[监控批次] 信号快照物化失败（不影响跑批）: {exc}")

    async def _finalize_batch_from_result(
        self, monitor_id: str, result: Optional[Dict[str, Any]]
    ) -> None:
        """按 ``run_*`` 的返回字典收尾批次（init / daily / range 三个入口共用）。

        模型轨净值写入 ``backtest_records`` 放在这里而不是各 run 主体里：
        主观步进暂停、正常跑完、组合管线三条出口都能统一覆盖。
        """
        result = result or {}
        state = None
        try:
            state = await self.get_state(monitor_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[监控批次] 收尾读取状态失败: {exc}")
        record_id = None
        if state is not None:
            record_id = await self._save_monitor_backtest_record(monitor_id, state)
            await self._persist_signal_snapshot(monitor_id, state)
        performance = result.get("performance")
        if not isinstance(performance, dict):
            performance = self._batch_performance
        await self._finish_run_batch(
            monitor_id,
            state=state,
            performance=performance,
            paused=bool(result.get("paused")),
            next_date=str(result.get("next_preset_date") or "")[:10] or None,
            end_date=str(
                result.get("date") or result.get("final_date") or ""
            )[:10] or None,
            backtest_record_id=record_id,
        )

    async def _fail_run_batch(self, error: Any) -> None:
        """跑批异常时把批次置 ``failed``（由 monitor_task_service 在 except 分支调用）。"""
        if not self._batch_id:
            return
        try:
            await monitor_batch_service.mark_failed(self._batch_id, error)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[监控批次] 失败状态写入异常: {exc}")

    async def _save_monitor_backtest_record(
        self,
        monitor_id: str,
        state: MonitorState,
        model_nav_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """把**模型轨**净值写入 ``backtest_records``（``run_kind=monitor``），返回记录 ID。

        门禁与 ``_append_monitor_run`` 同口径：只对已发布策略模型写，
        ``::model`` 并行轨文档、研究员策略与 ``default`` 实例跳过。

        必须走 ``save_monitor_record`` 而非 ``save_backtest_record``：不改写
        ``strategy_models.latest_backtest_summary``、不计入 ``trial_count``、
        不参与回测记录列表（``list_backtest_records`` 默认过滤 monitor）——
        监控跑批不得污染回测数据。
        """
        try:
            if not self._batch_id:
                return None
            mid = str(getattr(state, "monitor_id", "") or monitor_id or "")
            if not mid or mid.endswith("::model"):
                return None
            if not self._is_strategy_model_monitor_id(mid):
                return None
            versions = state.config_versions or {}
            if not versions.get("config_fingerprint"):
                return None

            rows = list(model_nav_history or state.nav_history_model or [])
            if not rows:
                return None

            from app.analysis.performance import compute_performance
            from app.models.strategy_model import (
                BacktestRecord, BacktestResult, EquityPoint,
            )
            from app.services.backtest_service import BacktestService

            initial_capital = float(state.nav_base or config.BASE_VALUE or 1.0) or 1.0
            dates: List[str] = []
            units: List[float] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                date_text = str(row.get("date") or "")[:10]
                if not date_text:
                    continue
                try:
                    unit_value = float(row.get("nav"))
                except (TypeError, ValueError):
                    continue
                dates.append(date_text)
                units.append(unit_value)
            if len(dates) < 2:
                return None

            base = units[0] or 1.0
            equity_curve = [
                EquityPoint(
                    date=f"{d}T00:00:00",
                    value=round(v * initial_capital, 6),
                    unit_value=round(v / base, 8),
                    cumulative_return=round(v / base - 1.0, 8),
                )
                for d, v in zip(dates, units)
            ]
            series = pd.Series(units, index=pd.to_datetime(dates)).sort_index()
            perf = compute_performance(series)
            self._batch_performance = {
                "total_return": float(perf.total_return),
                "annual_return": float(perf.annual_return),
                "annual_volatility": float(perf.annual_volatility),
                "sharpe_ratio": float(perf.sharpe_ratio),
                "max_drawdown": float(perf.max_drawdown),
            }

            record = BacktestRecord(
                model_id=self._batch_source_model_id or mid,
                start_date=dates[0],
                end_date=dates[-1],
                initial_capital=initial_capital,
                remark=f"监控批次产出（batch_id={self._batch_id}）",
                result=BacktestResult(
                    total_return=float(perf.total_return),
                    annual_return=float(perf.annual_return),
                    annual_volatility=float(perf.annual_volatility),
                    sharpe_ratio=float(perf.sharpe_ratio),
                    max_drawdown=float(perf.max_drawdown),
                    calmar_ratio=float(perf.calmar_ratio),
                    annual_return_365=getattr(perf, "annual_return_365", None),
                    annual_volatility_365=getattr(perf, "annual_volatility_365", None),
                    sharpe_ratio_365=getattr(perf, "sharpe_ratio_365", None),
                    calmar_ratio_365=getattr(perf, "calmar_ratio_365", None),
                    latest_unit_value=float(equity_curve[-1].unit_value or 1.0),
                    equity_curve=equity_curve,
                ),
            )
            record_id = await BacktestService().save_monitor_record(
                record, self._batch_id, mid,
                identity={
                    "strategy_id": versions.get("strategy_id"),
                    "config_version_id": versions.get("config_version_id"),
                },
            )
            logger.info(
                "[监控批次] 模型轨净值已写入 backtest_records: record_id={} batch_id={}",
                record_id, self._batch_id,
            )
            return record_id
        except Exception as exc:  # noqa: BLE001 —— 净值台账不得拖垮监控主流程
            logger.warning(f"[监控批次] 模型轨 backtest_record 写入失败: {exc}")
            return None

    # ============================================================
    # 状态管理
    # ============================================================
    
    async def get_state(
        self, monitor_id: str = "default", batch_id: Optional[str] = None
    ) -> Optional[MonitorState]:
        """从 MongoDB monitor_states 集合获取监控状态（批次维度）。

        批次解析优先级：
            1. 显式传入 ``batch_id``（含 ``"legacy"``）；
            2. 运行上下文 ``self._batch_id`` —— 增量推进中读自己写的那份；
            3. ``monitor_batch_service.resolve_batch_id`` 解析出的展示批次
               （不传时 = 最新 completed）；
            4. 兜底：最近更新的一条（存量未批次化数据、或批次台账缺失时）。

        ``{"batch_id": None}`` 在 Mongo 里同时命中字段缺失与显式 null，
        因此未补齐的存量文档也能被第 4 步读到。
        """
        target = monitor_batch_service.normalize_batch_id(
            batch_id if batch_id is not None else self._batch_id
        )
        if not batch_id and not self._batch_id:
            resolved = None
            try:
                resolved = await monitor_batch_service.resolve_batch_id(monitor_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[监控批次] 展示批次解析失败，回落最新状态文档: {exc}")
            if resolved:
                target = resolved
        doc = await self.states_collection.find_one(
            {"monitor_id": monitor_id, "batch_id": target}
        )
        if not doc:
            doc = await self.states_collection.find_one(
                {"monitor_id": monitor_id}, sort=[("updated_at", -1)]
            )
        if doc:
            return MonitorState.from_dict(doc)
        return None

    async def _load_parent_state(self, monitor_id: str) -> Optional[MonitorState]:
        """增量推进起点：从**父批次**的状态文档读 fold 状态与净值历史。

        不能走 :meth:`get_state`：那时运行上下文已是新批次，新批次的状态文档
        还不存在。父批次缺失（存量实例首次批次化）时回落最近更新的一条，
        行为与批次化前一致。
        """
        parent = self._parent_batch_id
        if parent:
            doc = await self.states_collection.find_one({
                "monitor_id": monitor_id,
                "batch_id": monitor_batch_service.normalize_batch_id(parent),
            })
            if doc:
                return MonitorState.from_dict(doc)
        doc = await self.states_collection.find_one(
            {"monitor_id": monitor_id}, sort=[("updated_at", -1)]
        )
        return MonitorState.from_dict(doc) if doc else None

    async def save_state(self, state: MonitorState) -> None:
        """保存状态到 MongoDB（upsert by ``{monitor_id, batch_id}``）。

        批次号以运行上下文 ``self._batch_id`` 为权威值：``_portfolio_state_to_state``
        在传入 ``original`` 时返回的是被改写的原对象，而原对象来自父批次，
        不覆盖就会把新结果写回父批次文档。
        """
        batch_id = self._current_batch_id()
        state.batch_id = batch_id
        state.updated_at = datetime.now()
        state_dict = state.to_dict()
        state_dict["batch_id"] = batch_id
        await self.states_collection.replace_one(
            {"monitor_id": state.monitor_id, "batch_id": batch_id},
            state_dict,
            upsert=True
        )
        logger.info(
            f"监控状态已保存: {state.monitor_id}, 批次: {batch_id}, "
            f"日期: {state.date}, 净值: {state.nav:.2f}"
        )
        # 运行台账（S13）：主状态写成功后追加一条 strategy_runs，失败只 warn。
        # 挂在 save_state 而非各 run 入口，是因为 run_daily / run_range / run_init /
        # 组合管线 / 主观步进暂停都把「本次运行结束」体现在一次最终状态落库上。
        # ::model 并行轨不写台账（同一次运行会重复），也不写 backtest_records。
        if not str(state.monitor_id or "").endswith("::model"):
            await self._append_monitor_run(state)

    async def _append_monitor_run(self, state: MonitorState) -> None:
        """追加一条 ``run_kind=monitor`` 运行摘要（S13，R3 同口径）.

        只对「已发布策略模型」写入：monitor_id 必须是模型 ObjectId，且
        ``config_versions.config_fingerprint`` 非空。以下一律跳过：
        - ``::model`` 后缀的模型口径并行轨（同一次运行会再落一次库）；
        - ``default`` 全局资产清单与研究员策略（无发布快照指纹）；
        - 未发布 / 快照缺失的模型（config_fingerprint 恒为空）。
        """
        try:
            monitor_id = str(state.monitor_id or "")
            if not monitor_id or monitor_id.endswith("::model"):
                return
            if not self._is_strategy_model_monitor_id(monitor_id):
                return
            versions = state.config_versions or {}
            fingerprint = versions.get("config_fingerprint")
            if not fingerprint:
                return

            nav_base = float(state.nav_base or 0.0)
            metrics: Dict[str, Any] = {}
            if nav_base:
                unit_value = float(state.nav) / nav_base
                metrics["latest_unit_value"] = unit_value
                metrics["total_return"] = unit_value - 1.0

            window_start = None
            if state.nav_history:
                head = state.nav_history[0]
                window_start = head.get("date") if isinstance(head, dict) else head

            from app.config.settings import settings
            from app.services.strategy_run_service import StrategyRunService

            await StrategyRunService().append_run(
                run_kind="monitor",
                model_id=monitor_id,
                strategy_id=versions.get("strategy_id"),
                config_version_id=versions.get("config_version_id"),
                config_fingerprint=fingerprint,
                engine_version=settings.APP_VERSION,
                window_start=window_start,
                window_end=state.date,
                metrics=metrics,
            )
        except Exception as exc:  # noqa: BLE001 —— 台账 append 不得拖垮监控主流程
            logger.warning(f"[strategy_runs] 监控运行记录写入失败: {exc}")
    
    async def create_initial_state(
        self, monitor_id: str = "default", asset_list: Optional[List[str]] = None
    ) -> MonitorState:
        """创建初始状态（空状态，用于 run_init）"""
        assets = list(asset_list) if asset_list else list(config.ASSET_LIST)
        state = MonitorState(
            monitor_id=monitor_id,
            batch_id=self._current_batch_id(),
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
    
    def _current_execution_policy(self) -> Dict[str, Any]:
        """取本次监控运行实际生效的成交口径（落库 + 与回测比对用）。

        通用监控的 ``PortfolioTracker.trading_cost`` 被 ``configure()`` 固定置空，
        因此这里通常得到 gross。gross 本身是有意设计（实盘费率体系未建立前
        不计费），但它与含费回测的净值不可直接比对——首次发现时打一条
        warning，把原本静默的口径差异在运行日志里说清楚（不拒绝启动：拒绝
        只会让人绕过校验，而 gross 监控是当前系统的正常形态）。
        """
        from app.backtesting.policy import COST_BASIS_GROSS, from_monitor_tracker

        policy = from_monitor_tracker(self.tracker)
        if policy.cost_basis == COST_BASIS_GROSS \
                and not getattr(self, "_gross_policy_warned", False):
            self._gross_policy_warned = True
            logger.warning(
                "[监控] 本次运行为 gross 口径（不计交易成本，policy_hash={}）；"
                "若对应策略在回测中声明了费率，两侧净值会逐日分叉，"
                "该差异来自成本口径而非计算逻辑。",
                policy.policy_hash(),
            )
        return policy.to_dict()

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
            # 分段运行的 fold 续接状态（存量文档无该键时取默认值）
            state_version=int(getattr(state, 'state_version', 1) or 1),
            vol_signal_dates=list(getattr(state, 'vol_signal_dates', []) or []),
            vol_execute_dates=list(getattr(state, 'vol_execute_dates', []) or []),
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
            original.custom_metrics = dict(getattr(ps, 'custom_metrics', {}) or {})
            original.state_version = int(getattr(ps, 'state_version', 1) or 1)
            original.vol_signal_dates = list(getattr(ps, 'vol_signal_dates', []) or [])
            original.vol_execute_dates = list(getattr(ps, 'vol_execute_dates', []) or [])
            original.config_versions = self._config_versions
            original.execution_policy = self._current_execution_policy()
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
            custom_metrics=dict(getattr(ps, 'custom_metrics', {}) or {}),
            state_version=int(getattr(ps, 'state_version', 1) or 1),
            vol_signal_dates=list(getattr(ps, 'vol_signal_dates', []) or []),
            vol_execute_dates=list(getattr(ps, 'vol_execute_dates', []) or []),
            config_versions=self._config_versions,
            execution_policy=self._current_execution_policy(),
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
            "live_published_version": model.live_published_version,
            "published_version": model.published_version,
            "config_fingerprint": model.config_fingerprint,
            "live_effective_summary": summary,
            "live_effective_assets": assets,
            "live_effective_asset_labels": labels,
            "live_effective_params": le_params,
            "is_config_baseline": False,
            "captured_at": ts,
            "source": "monitor_init",
            "note": "净值与绩效指标基于最近一次初始化时的实盘快照；重新发布并再次实盘发布后，请重新初始化以对齐最新逻辑。",
        }

    # ============================================================
    # 双轨净值：模型口径并行状态（纯系统信号自动执行，不含主观调整）
    # ============================================================

    @staticmethod
    def _model_track_state_id(monitor_id: str) -> str:
        """模型口径状态文档 ID（与主状态同集合，以 ::model 后缀隔离）"""
        return f"{monitor_id}::model"

    async def _load_model_track(
        self,
        monitor_id: str,
        actual_ps: PortfolioState,
        fresh: bool = False,
    ) -> PortfolioState:
        """加载模型口径并行状态；无存量时与实际口径同步起步（存量实例降级）。

        ``fresh=False``（增量推进）时从**父批次**的 ``::model`` 文档读 fold 状态：
        本批次的模型轨文档此刻还不存在，读当前批次必然落空。

        Args:
            monitor_id: 监控实例 ID（主状态）
            actual_ps: 实际口径当前状态，作为降级起步的克隆源
            fresh: True 表示初始化全新运行，不读取存量模型状态
        """
        if not fresh:
            model_state_id = self._model_track_state_id(monitor_id)
            source_batch = monitor_batch_service.normalize_batch_id(
                self._parent_batch_id or self._batch_id
            )
            doc = await self.states_collection.find_one(
                {"monitor_id": model_state_id, "batch_id": source_batch}
            )
            if not doc:
                # 父批次无模型轨（存量实例首次批次化）→ 回落最近更新的一条
                doc = await self.states_collection.find_one(
                    {"monitor_id": model_state_id}, sort=[("updated_at", -1)]
                )
            if doc:
                return self._state_to_portfolio_state(MonitorState.from_dict(doc))
        model_ps = self._state_to_portfolio_state(actual_ps)
        model_ps.nav_history = list(actual_ps.nav_history)
        return model_ps

    async def _save_model_track(self, monitor_id: str, model_ps: PortfolioState) -> None:
        """持久化模型口径状态（::model 后缀文档，upsert 天然与主状态隔离）"""
        state = self._portfolio_state_to_state(
            model_ps, self._model_track_state_id(monitor_id)
        )
        state.batch_id = self._current_batch_id()
        await self.save_state(state)

    async def _rebuild_performance_cache(
        self,
        monitor_id: str,
        daily_rows: Optional[List[dict]] = None,
        weight_history: Optional[List[dict]] = None,
        prices_df: Optional[pd.DataFrame] = None,
    ) -> None:
        """重建绩效页缓存（monitor_performance_cache）；失败不阻断监控主流程。

        缓存文档按 ``{monitor_id, batch_id}`` 唯一，批次号从运行上下文取。

        Args:
            monitor_id: 监控实例 ID（实盘策略即策略模型 ID）
            daily_rows: 本次推演逐日结果（date/nav/asset_weights/rebalance_executed）
            weight_history: 组合穿透后权重历史（组合监控）
            prices_df: 已加载的价格面板（避免重复回源行情库）
        """
        try:
            from app.monitor.performance_cache import rebuild_performance_cache
            await rebuild_performance_cache(
                self,
                monitor_id,
                daily_rows=daily_rows,
                weight_history=weight_history,
                prices_df=prices_df,
                batch_id=self._current_batch_id(),
            )
        except Exception as e:
            logger.warning(
                f"绩效缓存重建失败（不影响监控）: monitor={monitor_id}, error={e}"
            )

    @staticmethod
    def _fold_dates_to_ts(date_strs) -> set:
        """落库的 YYYY-MM-DD 列表 → 运行时 Timestamp 集合。

        分段运行（run_daily / run_range）用它把上一段落库的信号日/执行日
        还原成本段比较用的集合；存量文档无该键时得到空集，行为与修复前一致。
        """
        return {
            normalize_calendar_timestamp(d)
            for d in (date_strs or [])
            if d
        }

    @staticmethod
    def _remember_fold_date(ps: PortfolioState, attr: str, value) -> None:
        """新产生的信号日/执行日同步写回状态。

        逐日写回而不是循环末尾统一回写，是因为 run_init / run_daily / run_range
        各有「主观步进暂停」和「正常结束」两个 save_state 出口，逐日写回可保证
        任一出口落库的状态都带着完整的 fold 集合。
        """
        if not value:
            return
        date_str = str(value)[:10]
        bucket = getattr(ps, attr, None)
        if bucket is None:
            bucket = []
            setattr(ps, attr, bucket)
        if date_str not in bucket:
            bucket.append(date_str)

    def _step_model_track_day(
        self,
        ps_model: PortfolioState,
        date_str: str,
        date,
        prices_df: pd.DataFrame,
        fx_df: pd.DataFrame,
        trade_dates: List,
        monthly_rebalance_map: dict,
        monthly_rebalance_dates: set,
        vol_reset_execute_dates_model: set,
        vol_signal_dates_model: set,
        prev_nav_model: Optional[float],
        base_date: str,
        shared_operation_events: List[dict],
        monthly_signal_dates: set = None,
    ) -> Optional[float]:
        """模型口径单日并行步进：跳过主观调仓检查，事件写入实际轨共享列表避免重复落库。

        Returns:
            模型轨最新净值（供下日 prev_nav 使用）
        """
        result_model = self._process_single_day(
            ps_model, date_str, prices_df, fx_df, trade_dates,
            monthly_rebalance_map, monthly_rebalance_dates,
            vol_reset_execute_dates_model, [], prev_nav_model,
            base_date=base_date,
            rt=self._monitor_runtime,
            monthly_signal_dates=monthly_signal_dates,
            vol_signal_dates=vol_signal_dates_model,
            operation_events=shared_operation_events,
        )
        if result_model.get('vol_reset_triggered'):
            exec_date_m = result_model.get('vol_reset_execute_date')
            if exec_date_m:
                vol_reset_execute_dates_model.add(
                    normalize_calendar_timestamp(exec_date_m)
                )
                self._remember_fold_date(ps_model, 'vol_execute_dates', exec_date_m)
            vol_signal_dates_model.add(date)
            self._remember_fold_date(ps_model, 'vol_signal_dates', date)
        return ps_model.nav

    # ============================================================
    # 核心运行
    # ============================================================

    async def _emit_run_progress(self, progress_cb, **payload) -> None:
        """后台任务进度回调：回调异常只告警，不影响初始化主流程."""
        if progress_cb is None:
            return
        try:
            await progress_cb(**payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[monitor-progress] 进度写入失败: {exc}")

    def _make_engine_progress_bridge(self, progress_cb):
        """构造「引擎线程 → 主事件循环」的进度桥（供研究员引擎逐日上报）。

        线程调度与百分比去重下沉到
        :func:`monitor_task_service.make_thread_bridge`（回测端点复用同一套），
        这里只负责把进度转成本任务的 ``progress_cb``。

        Returns:
            同步回调 ``(done, total, current_date)``；None 表示不上报。
        """
        if progress_cb is None:
            return None

        async def _dispatch(done: int, total: int, pct: int, date_str) -> None:
            await progress_cb(
                phase="running",
                current=done,
                total=total,
                current_date=date_str,
                message=f"引擎回测 {pct}%（{done}/{total}）",
            )

        return make_thread_bridge(_dispatch)

    async def run_init(
        self,
        monitor_id: str = "default",
        start_date: str = None,
        manual_preset_step: bool = False,
        progress_cb=None,
        batch_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> dict:
        """初始化运行（批次外壳）：建批次 → 推演 → 收尾。

        Args:
            batch_id: 后台任务已预创建的批次号；为空则在此新建。
            task_id: 关联的后台任务号，写入批次文档便于互查。

        其余参数同 :meth:`_run_init_impl`。异常时批次置 ``failed`` 后原样抛出，
        由调用方（任务服务/端点）报错；失败批次对展示不可见。
        """
        actual_start_date = start_date or config.BASE_DATE
        await self._begin_run_batch(
            monitor_id,
            BatchRunMode.INIT.value,
            batch_id=batch_id,
            start_date=str(actual_start_date)[:10],
            task_id=task_id,
        )
        try:
            result = await self._run_init_impl(
                monitor_id=monitor_id,
                start_date=start_date,
                manual_preset_step=manual_preset_step,
                progress_cb=progress_cb,
            )
        except BaseException as exc:
            await self._fail_run_batch(exc)
            raise
        await self._finalize_batch_from_result(monitor_id, result)
        return result

    async def _run_init_impl(
        self,
        monitor_id: str = "default",
        start_date: str = None,
        manual_preset_step: bool = False,
        progress_cb=None,
    ) -> dict:
        """
        初始化运行：从指定日期（默认基日）逐日推演到数据最新日期
        
        Args:
            monitor_id: 监控实例 ID
            start_date: 自定义启动日期，格式 YYYY-MM-DD，默认使用 config.BASE_DATE
            manual_preset_step: 主观配置策略时，在每档预设调仓日当日推演完成后暂停并落库，便于查看绩效后再用「运行监控」续跑
            progress_cb: 可选异步回调，后台任务用于回写阶段/逐日进度；回调异常不影响主流程
        """
        # 确定实际启动日期
        actual_start_date = start_date or config.BASE_DATE
        logger.info(f"初始化模式开始: monitor_id={monitor_id}, start_date={actual_start_date}")
        await self._emit_run_progress(
            progress_cb, phase="preparing",
            message=f"准备初始化（启动日 {actual_start_date}）",
        )

        # ── 组合（portfolio）监控：复用组合回测管线，保证监控与回测一致 ──
        portfolio_info = await self._resolve_portfolio_source(monitor_id)
        if portfolio_info:
            latest_ts = await self.async_provider.get_latest_date()
            await self._emit_run_progress(
                progress_cb, phase="engine",
                message="组合回测引擎启动（子策略逐个回测 + 合成）",
            )
            return await self._run_portfolio_backtest_monitor(
                monitor_id, portfolio_info,
                start_date=str(actual_start_date), end_date=latest_ts,
                progress_cb=progress_cb,
            )

        await self._emit_run_progress(
            progress_cb, phase="loading", message="加载行情、汇率与交易日历",
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
        _cal_src = getattr(self._monitor_runtime, "calendar_source", "prices")
        _raw_td = (
            await self.async_provider.load_trade_dates()
            if _cal_src == "trade_dates" else []
        )
        trade_dates = coerce_trade_dates(_raw_td, prices_df, _cal_src)
        
        if prices_df.empty:
            raise ValueError("价格数据为空，无法初始化")

        # 运行前门禁（数据面）：策略声明的数据契约不满足时拒绝启动监控，
        # 不降级、不跳过资产。未声明契约的策略（含研究员策略）快速通过。
        from app.services.strategy_data_contract_service import enforce_price_contract

        await enforce_price_contract(
            template_code=getattr(self._monitor_runtime, "template_code", None),
            asset_codes=list(self.tracker.asset_list),
            strategy_params=getattr(self._monitor_runtime, "strategy_params", None) or {},
            prices=prices_df,
            strategy_label=f"监控[{monitor_id}]",
        )
        
        # ── 研究员策略独立引擎路径（不走通用 Pipeline / 预计算权重） ──
        if self._researcher_code in ('sharpe_18', 'hybrid_12'):
            # 引擎是整段向量化计算，内部无逐日钩子：不设 current/total，前端据此
            # 走 indeterminate 进度条（流动条纹），而不是停在 0%。
            try:
                _engine_days = len(prices_df.loc[pd.Timestamp(actual_start_date):])
            except Exception:  # noqa: BLE001 —— 仅用于文案，失败不影响主流程
                _engine_days = len(prices_df)
            await self._emit_run_progress(
                progress_cb, phase="engine",
                message=(
                    f"研究员引擎 {self._researcher_code} 回测中"
                    f"（{_engine_days} 个交易日一次性向量化计算，无逐日进度）"
                ),
            )
            if self._researcher_code == 'sharpe_18':
                return await self._run_init_sharpe18_standalone(
                    monitor_id, mongo_state, ps, prices_df, fx_df, trade_dates,
                    backtest_start=actual_start_date, progress_cb=progress_cb,
                )
            return await self._run_init_hybrid12_standalone(
                monitor_id, mongo_state, ps, prices_df, fx_df, trade_dates,
                backtest_start=actual_start_date, progress_cb=progress_cb,
            )

        # 3. 异步加载预计算权重（如果是 sharpe 选择器）
        precomputed_weights = await self._async_load_precomputed_weights(
            prices_df, rt=self._monitor_runtime
        )
        
        # 4. 构建月末调仓映射表（裁剪到本次启动日之后）
        monthly_rebalance_map = self._build_monthly_rebalance_map(
            prices_df,
            trade_dates,
            config.SKIP_EXCLUDED_DATES,
            rt=self._monitor_runtime,
            merged_params=self._merged_monitor_params,
            precomputed_weights=precomputed_weights,
            start_date=actual_start_date,
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

        # 预置月度调仓指令（初始化重跑：先清理自动指令再重建）
        await self._seed_monthly_operations(monitor_id, monthly_rebalance_map, reset=True)

        # 双轨：模型口径并行状态（初始化 = 全新并行运行）
        ps_model = await self._load_model_track(monitor_id, ps, fresh=True)
        vol_reset_execute_dates_model: set = set()
        vol_signal_dates_model: set = set()
        prev_nav_model: Optional[float] = None
        
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
        await self._emit_run_progress(
            progress_cb, phase="running", current=0, total=len(processing_dates),
            message=(
                f"逐日推演 {processing_dates[0].strftime('%Y-%m-%d')} ~ "
                f"{processing_dates[-1].strftime('%Y-%m-%d')}，共 {len(processing_dates)} 个交易日"
            ),
        )
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
        # 全量重放：已执行补录跨批次参与，执行日对齐到本次推演的交易日
        effective_overrides = self._align_overrides_for_dates(
            await self._get_effective_overrides(monitor_id, include_executed=True),
            processing_dates,
        )
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
        # 绩效页缓存原料：逐日持仓权重（调仓日快照由此生成）
        daily_cache_rows: List[dict] = []
        
        for i, date in enumerate(processing_dates):
            date_str = date.strftime('%Y-%m-%d')
            
            result = self._process_single_day(
                ps, date_str, prices_df, fx_df, trade_dates,
                monthly_rebalance_map, monthly_rebalance_dates,
                vol_reset_execute_dates, effective_overrides, prev_nav,
                base_date=aligned_start_date,
                rt=self._monitor_runtime,
                monthly_signal_dates=monthly_signal_dates,
                vol_signal_dates=vol_signal_dates,
                enable_risk_alerts=(i == len(processing_dates) - 1),
            )
            
            # 操作指令落库（执行/触发/取消）
            await self._record_operation_events(monitor_id, result)
            # 风险预警落库（步骤E3 只在本次运行最后一个处理日产出一批）
            await self._save_risk_alerts_from_result(monitor_id, result)
            daily_cache_rows.append({
                'date': result.get('date'),
                'nav': result.get('nav'),
                'asset_weights': result.get('asset_weights'),
                'rebalance_executed': result.get('rebalance_executed'),
            })
            
            # 更新波动率重置执行日期集合
            if result.get('vol_reset_triggered'):
                exec_date = result.get('vol_reset_execute_date')
                if exec_date:
                    vol_reset_execute_dates.add(
                        normalize_calendar_timestamp(exec_date)
                    )
                    self._remember_fold_date(ps, 'vol_execute_dates', exec_date)
                # 记录波动率触发信号日期（用于后续“触发-执行间信号”检查）
                vol_signal_dates.add(date)
                self._remember_fold_date(ps, 'vol_signal_dates', date)
            
            # 模型口径并行步进（跳过主观调仓，事件共享不重复落库）
            prev_nav_model = self._step_model_track_day(
                ps_model, date_str, date, prices_df, fx_df, trade_dates,
                monthly_rebalance_map, monthly_rebalance_dates,
                vol_reset_execute_dates_model, vol_signal_dates_model,
                prev_nav_model, aligned_start_date,
                result['operation_events'],
                monthly_signal_dates=monthly_signal_dates,
            )
            
            # 标记已执行的主观调仓指令（重放路径同样要收口，避免重复应用）
            if result.get('executed_override_id'):
                await self._mark_override_executed(result['executed_override_id'])
            
            prev_nav = ps.nav
            # 日报落库：初始化逐日推演产生的同样是真实的日度运行记录，
            # 与常规步进 / 范围补算口径一致（upsert 幂等，重复初始化不产生重复文档）
            await self._save_daily_report(monitor_id, result)
            
            if (i + 1) % 100 == 0:
                logger.info(f"进度: {i+1}/{len(processing_dates)} ({date_str}) NAV={ps.nav:.2f}")

            if progress_cb is not None:
                _pstep = max(1, len(processing_dates) // 100)
                if (i + 1) % _pstep == 0 or i + 1 == len(processing_dates):
                    await self._emit_run_progress(
                        progress_cb, phase="running",
                        current=i + 1, total=len(processing_dates),
                        current_date=date_str,
                        message=f"逐日推演 {date_str}",
                    )
            
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
                final_state.nav_history_model = list(ps_model.nav_history)
                await self.save_state(final_state)
                await self._save_model_track(monitor_id, ps_model)
                await self._rebuild_performance_cache(
                    monitor_id, daily_rows=daily_cache_rows, prices_df=prices_df
                )
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
        await self._emit_run_progress(
            progress_cb, phase="finalizing",
            current=len(processing_dates), total=len(processing_dates),
            message="保存状态与绩效缓存",
        )
        final_state = self._portfolio_state_to_state(ps, monitor_id, mongo_state)
        final_state.performance_basis = await self._capture_performance_basis_for_monitor(monitor_id)
        self._set_manual_preset_step_flags(final_state, False)
        final_state.nav_history_model = list(ps_model.nav_history)
        await self.save_state(final_state)
        await self._save_model_track(monitor_id, ps_model)
        await self._rebuild_performance_cache(
            monitor_id, daily_rows=daily_cache_rows, prices_df=prices_df
        )
        
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
        progress_cb=None,
        batch_id: Optional[str] = None,
        task_id: Optional[str] = None,
        replay: bool = False,
    ) -> dict:
        """日常运行（批次外壳）：建批次 → 从父批次续接推演 → 收尾。

        一次日常推进 = 一个全新批次：fold 状态从 ``parent_batch_id`` 读，
        结果写入新批次文档，**不覆盖父批次**（旧批次可回溯）。

        ``replay=True``：补录后重算。组合通道本来就全量重跑；单策略通道
        改为从首个净值日重放，否则历史补录永远进不了净值。
        """
        await self._begin_run_batch(
            monitor_id,
            BatchRunMode.DAILY.value,
            batch_id=batch_id,
            data_date=str(target_date or "")[:10] or None,
            task_id=task_id,
        )
        try:
            result = await self._run_daily_impl(
                monitor_id=monitor_id,
                target_date=target_date,
                manual_preset_step=manual_preset_step,
                progress_cb=progress_cb,
                replay=replay,
            )
        except BaseException as exc:
            await self._fail_run_batch(exc)
            raise
        await self._finalize_batch_from_result(monitor_id, result)
        return result

    async def _run_daily_impl(
        self,
        monitor_id: str = "default",
        target_date: str = None,
        manual_preset_step: bool = False,
        progress_cb=None,
        replay: bool = False,
    ) -> dict:
        """
        日常运行：从上次状态续接到目标日期（默认最新）
        对应 run_monitor.py 正常模式
        
        manual_preset_step: 主观配置时，在预设调仓日当日推演完成后暂停（与初始化步进衔接）
        progress_cb: 可选异步回调，后台任务用于回写阶段/逐日进度
        replay: 补录重算，单策略通道改为从首个净值日全量重放
        """
        logger.info(
            f"日常监测模式开始: monitor_id={monitor_id}, batch_id={self._current_batch_id()}"
        )

        # ── 组合（portfolio）监控：从原始起点全量重跑到目标日期（复用回测管线） ──
        portfolio_info = await self._resolve_portfolio_source(monitor_id)
        if portfolio_info:
            existing = await self._load_parent_state(monitor_id)
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
                progress_cb=progress_cb,
            )

        if replay:
            # 补录重算：fold 只处理父状态之后的新日期，历史补录永远落不到，
            # 必须从首个净值日全量重放，让补录指令重新参与逐日推演
            existing = await self._load_parent_state(monitor_id)
            _replay_start = None
            if existing and existing.nav_history:
                _first = existing.nav_history[0]
                _replay_start = _first.get('date') if isinstance(_first, dict) else str(_first)
            logger.info(
                f"[补录重算] 单策略从首个净值日重放: "
                f"start={_replay_start or config.BASE_DATE}"
            )
            return await self._run_init_impl(
                monitor_id=monitor_id,
                start_date=_replay_start or config.BASE_DATE,
                # 重算必须跑到最新行情日，不能停在预设调仓日
                manual_preset_step=False,
                progress_cb=progress_cb,
            )

        await self._prepare_monitor_run(monitor_id, load_panels=False)
        
        # 1. 加载父批次状态（fold 续接起点）
        mongo_state = await self._load_parent_state(monitor_id)
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
        _cal_src = getattr(self._monitor_runtime, "calendar_source", "prices")
        _raw_td = (
            await self.async_provider.load_trade_dates()
            if _cal_src == "trade_dates" else []
        )
        trade_dates = coerce_trade_dates(_raw_td, prices_df, _cal_src)
        
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
                    backtest_start=_bt_start, progress_cb=progress_cb,
                )
            return await self._run_init_hybrid12_standalone(
                monitor_id, mongo_state, ps, prices_df, fx_df, trade_dates,
                backtest_start=_bt_start, progress_cb=progress_cb,
            )

        # 3. 确定处理日期范围。判空必须早于面板加载与调仓图计算：
        #    no-op 日这两项占 run_daily 的七成以上，且结果不会被任何下游消费
        last_date = normalize_calendar_timestamp(ps.date)
        end_date = (
            normalize_calendar_timestamp(target_date)
            if target_date
            else prices_df.index.max()
        )
        processing_dates = [d for d in prices_df.index if last_date < d <= end_date]
        
        if not processing_dates:
            logger.info("没有需要处理的交易日")
            await self._rebuild_performance_cache(monitor_id, prices_df=prices_df)
            self._log_monitor_fx_snapshot(ps.date, fx_df)
            return {
                'monitor_id': monitor_id,
                'date': ps.date,
                'nav': ps.nav,
                'message': '没有新数据需要处理'
            }
        
        # 4. 面板与调仓图：只在确有新交易日时计算（面板必须先于 adapter 构建）
        await self._load_monitor_panels(self._monitor_runtime)
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
            start_date=ps.date,
        )
        monthly_rebalance_dates = set(monthly_rebalance_map.keys())
        # 分段运行续接：执行日集合来自上一段落库状态。从空集起步会让
        # 波动率重置的执行日去重跨段失效。
        vol_reset_execute_dates = self._fold_dates_to_ts(ps.vol_execute_dates)
        
        # 预置月度调仓指令（幂等：刷新目标权重与执行日，保证 T+2 窗口可预展示）
        await self._seed_monthly_operations(monitor_id, monthly_rebalance_map)
        
        # 构建月度调仓信号日期集合（与原型 monthly_signal_dates_set 对齐）
        monthly_signal_dates = {
            normalize_calendar_timestamp(v['calc_date'])
            for v in monthly_rebalance_map.values()
        }
        # 波动率触发信号日期集合：先取落库历史，再在本段循环中继续积累
        vol_signal_dates = self._fold_dates_to_ts(ps.vol_signal_dates)
        # 如果当前状态有 pending vol_reset，将其信号日加入集合
        if ps.pending_rebalance and ps.pending_rebalance.get('rebalance_type') == 'vol_reset':
            sig_d = ps.pending_rebalance.get('signal_date')
            if sig_d:
                vol_signal_dates.add(normalize_calendar_timestamp(sig_d))
        
        # 双轨：加载模型口径并行状态（存量实例无模型轨时与实际轨同步起步）
        ps_model = await self._load_model_track(monitor_id, ps)
        vol_reset_execute_dates_model: set = self._fold_dates_to_ts(ps_model.vol_execute_dates)
        vol_signal_dates_model: set = self._fold_dates_to_ts(ps_model.vol_signal_dates)
        if ps_model.pending_rebalance and ps_model.pending_rebalance.get('rebalance_type') == 'vol_reset':
            _sig_m = ps_model.pending_rebalance.get('signal_date')
            if _sig_m:
                vol_signal_dates_model.add(normalize_calendar_timestamp(_sig_m))
        prev_nav_model = ps_model.nav
        
        logger.info(f"处理日期范围: {processing_dates[0].strftime('%Y-%m-%d')} ~ {processing_dates[-1].strftime('%Y-%m-%d')}, 共 {len(processing_dates)} 个交易日")
        
        # 5. 逐日处理
        prev_nav = ps.nav
        pending_overrides = await self._get_pending_overrides(monitor_id)
        last_result = None
        # 绩效页缓存原料：本次新增的逐日持仓权重（调仓日快照由此生成）
        daily_cache_rows: List[dict] = []
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
                enable_risk_alerts=(i == len(processing_dates) - 1),
            )
            
            # 操作指令落库（执行/触发/取消）
            await self._record_operation_events(monitor_id, result)
            # 风险预警落库（步骤E3 只在本次运行最后一个处理日产出一批）
            await self._save_risk_alerts_from_result(monitor_id, result)
            
            if result.get('vol_reset_triggered'):
                exec_date = result.get('vol_reset_execute_date')
                if exec_date:
                    vol_reset_execute_dates.add(
                        normalize_calendar_timestamp(exec_date)
                    )
                    self._remember_fold_date(ps, 'vol_execute_dates', exec_date)
                # 记录波动率触发信号日期（用于后续"触发-执行间信号"检查）
                vol_signal_dates.add(date)
                self._remember_fold_date(ps, 'vol_signal_dates', date)
            
            # 模型口径并行步进（跳过主观调仓，事件共享不重复落库）
            prev_nav_model = self._step_model_track_day(
                ps_model, date_str, date, prices_df, fx_df, trade_dates,
                monthly_rebalance_map, monthly_rebalance_dates,
                vol_reset_execute_dates_model, vol_signal_dates_model,
                prev_nav_model, config.BASE_DATE,
                result['operation_events'],
                monthly_signal_dates=monthly_signal_dates,
            )
            
            # 标记已执行的主观调仓指令
            if result.get('executed_override_id'):
                await self._mark_override_executed(result['executed_override_id'])
            
            # 保存日报
            await self._save_daily_report(monitor_id, result)
            daily_cache_rows.append({
                'date': result.get('date'),
                'nav': result.get('nav'),
                'asset_weights': result.get('asset_weights'),
                'rebalance_executed': result.get('rebalance_executed'),
            })
            
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
                final_state.nav_history_model = list(ps_model.nav_history)
                await self.save_state(final_state)
                await self._save_model_track(monitor_id, ps_model)
                await self._rebuild_performance_cache(
                    monitor_id, daily_rows=daily_cache_rows, prices_df=prices_df
                )
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
        final_state.nav_history_model = list(ps_model.nav_history)
        await self.save_state(final_state)
        await self._save_model_track(monitor_id, ps_model)
        await self._rebuild_performance_cache(
            monitor_id, daily_rows=daily_cache_rows, prices_df=prices_df
        )
        
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
        progress_cb=None,
        batch_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> dict:
        """区间推演（批次外壳）：建批次 → 推演 → 收尾。"""
        await self._begin_run_batch(
            monitor_id,
            BatchRunMode.RANGE.value,
            batch_id=batch_id,
            start_date=str(from_date or "")[:10] or None,
            data_date=str(to_date or "")[:10] or None,
            task_id=task_id,
        )
        try:
            result = await self._run_range_impl(
                monitor_id=monitor_id,
                from_date=from_date,
                to_date=to_date,
                manual_preset_step=manual_preset_step,
                progress_cb=progress_cb,
            )
        except BaseException as exc:
            await self._fail_run_batch(exc)
            raise
        await self._finalize_batch_from_result(monitor_id, result)
        return result

    async def _run_range_impl(
        self,
        monitor_id: str,
        from_date: str,
        to_date: str,
        manual_preset_step: bool = False,
        progress_cb=None,
    ) -> dict:
        """
        按日期范围运行：从指定日期到指定日期
        对应 run_monitor.py --from --to 模式
        """
        logger.info(
            f"范围运行模式: {from_date} ~ {to_date}, batch_id={self._current_batch_id()}"
        )

        # ── 组合（portfolio）监控：按范围复用回测管线全量重算 ──
        portfolio_info = await self._resolve_portfolio_source(monitor_id)
        if portfolio_info:
            return await self._run_portfolio_backtest_monitor(
                monitor_id, portfolio_info,
                start_date=str(from_date), end_date=to_date,
                progress_cb=progress_cb,
            )

        await self._prepare_monitor_run(monitor_id)
        
        mongo_state = await self._load_parent_state(monitor_id)
        if not mongo_state:
            raise ValueError(f"监控状态不存在: {monitor_id}")
        
        ps = self._state_to_portfolio_state(mongo_state)
        
        prices_df = await self.async_provider.load_prices(
            asset_columns=list(self.tracker.asset_list),
        )
        prices_df = slice_prices_df(prices_df, self._monitor_runtime)
        fx_df = await self.async_provider.load_fx()
        _cal_src = getattr(self._monitor_runtime, "calendar_source", "prices")
        _raw_td = (
            await self.async_provider.load_trade_dates()
            if _cal_src == "trade_dates" else []
        )
        trade_dates = coerce_trade_dates(_raw_td, prices_df, _cal_src)
        
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
            start_date=from_date,
        )
        monthly_rebalance_dates = set(monthly_rebalance_map.keys())
        # 分段运行续接：执行日集合来自上一段落库状态。从空集起步会让
        # 波动率重置的执行日去重跨段失效。
        vol_reset_execute_dates = self._fold_dates_to_ts(ps.vol_execute_dates)
        
        # 预置月度调仓指令（幂等）
        await self._seed_monthly_operations(monitor_id, monthly_rebalance_map)
        
        # 构建月度调仓信号日期集合（与原型 monthly_signal_dates_set 对齐）
        monthly_signal_dates = {
            normalize_calendar_timestamp(v['calc_date'])
            for v in monthly_rebalance_map.values()
        }
        # 波动率触发信号日期集合：先取落库历史，再在本段循环中继续积累
        vol_signal_dates = self._fold_dates_to_ts(ps.vol_signal_dates)
        # 如果当前状态有 pending vol_reset，将其信号日加入集合
        if ps.pending_rebalance and ps.pending_rebalance.get('rebalance_type') == 'vol_reset':
            sig_d = ps.pending_rebalance.get('signal_date')
            if sig_d:
                vol_signal_dates.add(normalize_calendar_timestamp(sig_d))
        
        # 双轨：加载模型口径并行状态（存量实例无模型轨时与实际轨同步起步）
        ps_model = await self._load_model_track(monitor_id, ps)
        vol_reset_execute_dates_model: set = self._fold_dates_to_ts(ps_model.vol_execute_dates)
        vol_signal_dates_model: set = self._fold_dates_to_ts(ps_model.vol_signal_dates)
        if ps_model.pending_rebalance and ps_model.pending_rebalance.get('rebalance_type') == 'vol_reset':
            _sig_m = ps_model.pending_rebalance.get('signal_date')
            if _sig_m:
                vol_signal_dates_model.add(normalize_calendar_timestamp(_sig_m))
        prev_nav_model = ps_model.nav
        
        from_ts = normalize_calendar_timestamp(from_date)
        to_ts = normalize_calendar_timestamp(to_date)
        processing_dates = [d for d in prices_df.index if from_ts <= d <= to_ts]
        
        if not processing_dates:
            self._log_monitor_fx_snapshot(ps.date, fx_df)
            return {'monitor_id': monitor_id, 'message': '指定范围内没有交易日'}
        
        prev_nav = ps.nav
        pending_overrides = await self._get_pending_overrides(monitor_id)
        # 绩效页缓存原料：本次新增的逐日持仓权重（调仓日快照由此生成）
        daily_cache_rows: List[dict] = []
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
                enable_risk_alerts=(i == len(processing_dates) - 1),
            )
            last_range_result = result
            
            # 操作指令落库（执行/触发/取消）
            await self._record_operation_events(monitor_id, result)
            # 风险预警落库（步骤E3 只在本次运行最后一个处理日产出一批）
            await self._save_risk_alerts_from_result(monitor_id, result)
            
            if result.get('vol_reset_triggered'):
                exec_date = result.get('vol_reset_execute_date')
                if exec_date:
                    vol_reset_execute_dates.add(
                        normalize_calendar_timestamp(exec_date)
                    )
                    self._remember_fold_date(ps, 'vol_execute_dates', exec_date)
                # 记录波动率触发信号日期（用于后续"触发-执行间信号"检查）
                vol_signal_dates.add(date)
                self._remember_fold_date(ps, 'vol_signal_dates', date)
            
            # 模型口径并行步进（跳过主观调仓，事件共享不重复落库）
            prev_nav_model = self._step_model_track_day(
                ps_model, date_str, date, prices_df, fx_df, trade_dates,
                monthly_rebalance_map, monthly_rebalance_dates,
                vol_reset_execute_dates_model, vol_signal_dates_model,
                prev_nav_model, config.BASE_DATE,
                result['operation_events'],
                monthly_signal_dates=monthly_signal_dates,
            )
            
            # 标记已执行的主观调仓指令
            if result.get('executed_override_id'):
                await self._mark_override_executed(result['executed_override_id'])
            
            await self._save_daily_report(monitor_id, result)
            daily_cache_rows.append({
                'date': result.get('date'),
                'nav': result.get('nav'),
                'asset_weights': result.get('asset_weights'),
                'rebalance_executed': result.get('rebalance_executed'),
            })
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
                final_state.nav_history_model = list(ps_model.nav_history)
                await self.save_state(final_state)
                await self._save_model_track(monitor_id, ps_model)
                await self._rebuild_performance_cache(
                    monitor_id, daily_rows=daily_cache_rows, prices_df=prices_df
                )
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
        final_state.nav_history_model = list(ps_model.nav_history)
        await self.save_state(final_state)
        await self._save_model_track(monitor_id, ps_model)
        await self._rebuild_performance_cache(
            monitor_id, daily_rows=daily_cache_rows, prices_df=prices_df
        )
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
        progress_cb=None,
    ) -> dict:
        """使用 sharpe_18 独立引擎运行全量回测（自包含 step1+step2+step3）。"""
        from app.monitor.researcher_strategies.sharpe_18.engine import run_backtest as sharpe18_run

        logger.info("sharpe_18 引擎启动，数据: {} ~ {}, backtest_start={}",
                    prices_df.index[0].date(), prices_df.index[-1].date(), backtest_start)
        # 引擎是同步 CPU 密集计算（数千万级 pandas 运算），必须放到工作线程：
        # 直接 await 会冻结 asyncio 事件循环，期间所有轮询/其他 API 请求挂起，
        # 前端轮询超时后只能拿到终态，表现为「进度条直接跳到完成」。
        result = await asyncio.to_thread(
            sharpe18_run, prices_df, fx_df, trade_dates,
            backtest_start=backtest_start,
            progress_cb=self._make_engine_progress_bridge(progress_cb),
        )
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

        # 从事件日志同步操作指令（独立引擎无步进指令事件）
        await self._sync_operations_from_event_log(monitor_id, ps.event_log)

        # 绩效页缓存：持仓快照由已执行指令目标权重兜底
        await self._rebuild_performance_cache(monitor_id, prices_df=prices_df)

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
        progress_cb=None,
    ) -> dict:
        """使用 hybrid_12 独立引擎运行全量回测（自包含 step1+step2+step3）。"""
        from app.monitor.researcher_strategies.hybrid_12.engine import run_backtest as hybrid12_run

        logger.info("hybrid_12 引擎启动，数据: {} ~ {}, backtest_start={}",
                    prices_df.index[0].date(), prices_df.index[-1].date(), backtest_start)
        # 同 sharpe_18：同步引擎放工作线程，避免冻结事件循环
        result = await asyncio.to_thread(
            hybrid12_run, prices_df, fx_df, trade_dates,
            backtest_start=backtest_start,
            progress_cb=self._make_engine_progress_bridge(progress_cb),
        )
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

        # 从事件日志同步操作指令（独立引擎无步进指令事件）
        await self._sync_operations_from_event_log(monitor_id, ps.event_log)

        # 绩效页缓存：持仓快照由已执行指令目标权重兜底
        await self._rebuild_performance_cache(monitor_id, prices_df=prices_df)

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
    
    async def _override_batch_id(
        self, monitor_id: str, batch_id: Optional[str] = None
    ) -> str:
        """主观指令的落库批次：显式传入 > 当前运行批次 > 最新 completed 批次 > ``legacy``。

        页面新增指令时没有运行上下文，必须挂到「下一次跑批的父批次」上：
        :func:`_begin_run_batch` 的 pending 继承只从父批次拉挂单，挂错批次就等于指令丢失。
        """
        text = str(batch_id or "").strip()
        if text:
            return text
        if self._batch_id:
            return self._batch_id
        try:
            resolved = await monitor_batch_service.resolve_batch_id(monitor_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[监控批次] 主观指令批次解析失败，落 legacy: {exc}")
            resolved = None
        return monitor_batch_service.normalize_batch_id(resolved)

    async def _backfill_window(self, monitor_id: str) -> tuple:
        """补录允许的日期窗口：(首个净值日, 最新净值日)。

        只取当前展示批次状态文档的首尾，不拉全量净值历史。
        """
        try:
            batch = await monitor_batch_service.resolve_batch_id(monitor_id)
        except Exception:  # noqa: BLE001 —— 无批次时由调用方报错
            return None, None
        doc = await self.states_collection.find_one(
            {
                "monitor_id": monitor_id,
                "batch_id": monitor_batch_service.normalize_batch_id(batch),
            },
            {"date": 1, "nav_history": {"$slice": 1}},
        )
        if not doc:
            return None, None
        first_day = None
        hist = doc.get("nav_history") or []
        if hist:
            row = hist[0]
            first_day = row.get("date") if isinstance(row, dict) else str(row)
        return (
            str(first_day)[:10] if first_day else None,
            str(doc.get("date") or "")[:10] or None,
        )

    async def _validate_backfill_request(self, monitor_id: str, execute_date: str) -> None:
        """补录前置校验：研究员策略不支持，日期必须落在已有净值区间内。

        早于起点无处叠加，晚于最新净值日则不属于「补录」，应作为待执行指令提交。
        """
        ms_doc = await self._resolve_monitored_strategy(monitor_id)
        if ms_doc and ms_doc.get("source_type") == "researcher":
            raise ValueError(
                "研究员策略不支持补录：该通道没有逐日主观调仓入口，补录指令不会进入净值"
            )
        first_day, last_day = await self._backfill_window(monitor_id)
        if not first_day or not last_day:
            raise ValueError("监控尚未产生净值，无法补录，请先运行初始化")
        day = str(execute_date or "")[:10]
        if day <= first_day:
            raise ValueError(
                f"补录日期需晚于监控起点 {first_day}（起点当日权重由初始化决定）"
            )
        if day > last_day:
            raise ValueError(
                f"补录日期 {day} 晚于当前净值日 {last_day}，请关闭补录按待执行指令提交"
            )

    async def add_subjective_override(self, monitor_id: str, weights: dict,
                                       execute_date: str, description: str = None,
                                       linked_operation_id: str = None,
                                       record_executed: bool = False,
                                       batch_id: Optional[str] = None) -> str:
        """新增主观调仓指令。

        Args:
            linked_operation_id: 挂接的待执行操作指令 ID（调仓日比例优化模式）；
                非空时校验目标指令为同监控实例的 pending 指令，创建后将其标记 superseded。
            record_executed: 补录模式，创建时直接写 executed + executed_at；
                提交后由调用方按执行日重算净值，不得与 linked_operation_id 同时使用。
            batch_id: 所属批次；缺省挂到当前展示批次（最新 completed）。
        """
        rt = await self._runtime_for_reads(monitor_id)
        self._validate_weights(weights, rt)

        if record_executed and linked_operation_id:
            raise ValueError("补录模式不支持挂接待执行指令（补录不是替代）")

        if record_executed:
            await self._validate_backfill_request(monitor_id, execute_date)
        
        # 比例优化模式：校验并替代原待执行指令
        if linked_operation_id:
            op = await self.operation_service.get(linked_operation_id)
            if not op:
                raise ValueError(f"挂接的操作指令不存在: {linked_operation_id}")
            if op.get("monitor_id") != monitor_id:
                raise ValueError("挂接的操作指令不属于当前监控实例")
            if op.get("status") != "pending":
                raise ValueError(f"仅待执行指令可被比例优化替代，当前状态: {op.get('status')}")
        
        override_id = f"sub_{execute_date.replace('-', '')}_{uuid.uuid4().hex[:8]}"
        target_batch = await self._override_batch_id(monitor_id, batch_id)
        
        override = SubjectiveOverride(
            override_id=override_id,
            monitor_id=monitor_id,
            batch_id=target_batch,
            weights=weights,
            execute_date=execute_date,
            status=(OverrideStatus.EXECUTED if record_executed else OverrideStatus.PENDING),
            description=description,
            linked_operation_id=linked_operation_id,
            created_at=datetime.now(),
            executed_at=datetime.now() if record_executed else None,
        )
        
        try:
            await self.overrides_collection.insert_one(override.to_dict())
            
            if linked_operation_id:
                await self.operation_service.supersede(
                    linked_operation_id,
                    reason=f"被主观比例优化替代（{override_id}）",
                )
            # 同步写入操作指令记录（主观维度，供操作面板展示）
            await self.operation_service.create_subjective_operation(
                monitor_id=monitor_id,
                execute_date=execute_date,
                weights=weights,
                override_ref=override_id,
                strategy_name=await self._operation_strategy_display_name(monitor_id),
                linked_operation_id=linked_operation_id,
                description=description,
                record_executed=record_executed,
                batch_id=target_batch,
            )
        except Exception:
            # 写一半失败会留下没有操作记录的孤儿指令，直接清掉重来
            await self.rollback_subjective_override(override_id)
            if linked_operation_id:
                try:
                    await self.operation_service.unsupersede(linked_operation_id)
                except Exception:  # noqa: BLE001
                    pass
            raise
        logger.info(f"主观调仓指令已创建: {override_id}, 执行日期: {execute_date}, 批次: {target_batch}"
                    + (", 补录已执行" if record_executed else "")
                    + (f", 替代指令: {linked_operation_id}" if linked_operation_id else ""))
        
        return override_id

    async def rollback_subjective_override(self, override_id: str) -> None:
        """删除刚写入的补录指令及其操作记录（重算任务提交失败时回滚）。

        指令还没被任何跑批读过，硬删除即可；留 cancelled 记录只会污染列表。
        """
        try:
            await self.overrides_collection.delete_one({"override_id": override_id})
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"回滚补录指令失败: {override_id}, {exc}")
        try:
            await self.operation_service.delete_subjective_operation(override_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"回滚补录操作记录失败: {override_id}, {exc}")

    async def update_operation_remark(self, operation_id: str, remark: str) -> dict:
        """为已执行指令追加/更新补充说明。

        remark 权威存储于 monitor_operation_remarks（按业务键挂靠），
        组合通道全量重建 ops 后仍能回填。
        """
        op = await self.operation_service.get(operation_id)
        if not op:
            raise ValueError(f"操作指令不存在: {operation_id}")
        if op.get("status") != "executed":
            raise ValueError(f"仅已执行指令可补充说明，当前状态: {op.get('status')}")
        text = await self.operation_service.set_remark(operation_id, remark)
        return {"operation_id": operation_id, "remark": text}
    
    async def list_subjective_overrides(self, monitor_id: str,
                                         status: str = None,
                                         batch_id: Optional[str] = None) -> List[dict]:
        """列出主观调仓指令，可按状态筛选。

        ``batch_id=None`` 表示不限批次（历史全量）；展示端点应先经
        ``monitor_batch_service.resolve_batch_id`` 解析出批次号再传入。
        """
        query = {"monitor_id": monitor_id}
        if status:
            query["status"] = status
        if batch_id:
            query["batch_id"] = str(batch_id)
        
        cursor = self.overrides_collection.find(query).sort("created_at", -1)
        result = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            result.append(doc)
        
        return result
    
    async def cancel_subjective_override(self, override_id: str) -> bool:
        """取消主观调仓指令（仅 pending 状态可取消）；若挂接过原指令则恢复其为 pending。"""
        doc = await self.overrides_collection.find_one({"override_id": override_id})
        result = await self.overrides_collection.update_one(
            {"override_id": override_id, "status": OverrideStatus.PENDING.value},
            {"$set": {"status": OverrideStatus.CANCELLED.value}}
        )
        if result.modified_count > 0:
            logger.info(f"主观调仓指令已取消: {override_id}")
            # 同步取消对应的操作指令记录，并恢复被替代的原指令
            try:
                from app.models.monitor import OperationStatus
                await self.operation_service.collection.update_one(
                    {"override_ref": override_id, "status": OperationStatus.PENDING.value},
                    {"$set": {"status": OperationStatus.CANCELLED.value,
                              "updated_at": datetime.now()}},
                )
                linked = (doc or {}).get("linked_operation_id")
                if linked:
                    await self.operation_service.unsupersede(linked)
            except Exception as e:
                logger.warning(f"取消主观指令后同步操作指令失败: {e}")
            return True
        return False
    
    @staticmethod
    def _align_overrides_for_dates(
        overrides: List[dict], processing_dates: List[Any]
    ) -> List[dict]:
        """把指令执行日对齐到本次推演的交易日并去重（非交易日顺延）。"""
        from app.monitor.portfolio_dual_track import align_overrides_to_trade_days
        days = [str(d)[:10] for d in processing_dates]
        return align_overrides_to_trade_days(overrides, days)

    async def _get_effective_overrides(
        self,
        monitor_id: str,
        *,
        include_executed: bool,
        batch_id: Optional[str] = None,
    ) -> List[dict]:
        """取本次推演参与的主观指令（未做交易日对齐）。

        - ``include_executed=True``（初始化 / 补录重算的全量重放）：``executed``
          跨批次 + 当前批次 ``pending``。重放会重新走过历史每一天，补录的已执行
          指令必须重新叠加，否则实际轨会丢掉这笔调仓；
        - ``include_executed=False``（日常 fold 续接 / 区间补算）：只取当前批次
          ``pending``。父批次状态已包含历史 ``executed`` 的持仓结果，再读一次
          会重复调仓。

        调用方随后用 ``align_overrides_to_trade_days`` 把执行日对齐到交易日。
        """
        batch_key = monitor_batch_service.normalize_batch_id(
            batch_id if batch_id is not None else self._batch_id
        )
        if include_executed:
            query: Dict[str, Any] = {
                "monitor_id": monitor_id,
                "$or": [
                    {"status": OverrideStatus.EXECUTED.value},
                    {"status": OverrideStatus.PENDING.value, "batch_id": batch_key},
                ],
            }
        else:
            query = {
                "monitor_id": monitor_id,
                "status": OverrideStatus.PENDING.value,
                "batch_id": batch_key,
            }
        return [doc async for doc in self.overrides_collection.find(query)]

    async def _get_pending_overrides(self, monitor_id: str,
                                     batch_id: Optional[str] = None) -> List[dict]:
        """获取当前批次所有 pending 状态的主观调仓指令。

        只读当前批次：``_begin_run_batch`` 已把父批次的挂单继承进来，再叠加
        父批次会拿到同一条指令的两份副本（override_id 不同，按日匹配会重复执行）。
        """
        cursor = self.overrides_collection.find({
            "monitor_id": monitor_id,
            "status": OverrideStatus.PENDING.value,
            "batch_id": monitor_batch_service.normalize_batch_id(
                batch_id if batch_id is not None else self._batch_id
            ),
        })
        result = []
        async for doc in cursor:
            result.append(doc)
        return result
    
    async def _mark_override_executed(self, override_id: str,
                                      batch_id: Optional[str] = None) -> None:
        """标记指令为已执行（``override_id`` 全局唯一，批次过滤只是双保险）"""
        query: Dict[str, Any] = {"override_id": override_id}
        if batch_id:
            query["batch_id"] = str(batch_id)
        await self.overrides_collection.update_one(
            query,
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
