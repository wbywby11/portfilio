# -*- coding: utf-8 -*-
"""
监控服务 Mixin：调仓计划构建（月末声明延迟 / 主观预设日）与权重规划

自 monitor_service.py 平移而来，方法体保持不变，仅按职责归组：
1. 月度调仓映射（月末信号 + 策略声明的执行延迟；主观配置预设调仓日）
2. sharpe 选择器预计算权重加载
3. 三层引擎适配器获取与手工权重归一化

同源性约定：执行延迟一律读策略 `get_execution_schedule()` 的声明，与回测
`ScheduleResolver` 同一口径；策略未声明时月末路径缺省 T+2（与改造前一致）。
"""

import pandas as pd
from typing import Dict, List, Optional, Any
from loguru import logger

from app.monitor.engine_adapter import MonitorEngineAdapter
from app.monitor.time_norm import normalize_calendar_timestamp


# 自然频率：只在这些频率下允许跳过月末/事件驱动路径，按自然频率推演信号日
_NATURAL_FREQS = frozenset({"daily", "weekly"})

# 月末路径在策略未声明 execution_delay 时的缺省延迟（交易日）
_DEFAULT_MONTH_END_DELAY = 2


class RebalancePlanningMixin:
    """调仓映射构建与权重规划辅助方法。

    依赖宿主（MonitorService）属性：db、_engine_adapter。
    """

    async def _async_load_precomputed_weights(
        self,
        prices_df: pd.DataFrame,
        rt=None,
    ) -> Dict[str, Dict[str, float]]:
        """异步加载原型预计算权重（仅 selector_type=sharpe 的策略）
        
        预计算权重使用中文资产名作为键（如'沪深300'），而 prices_df.columns 使用资产代码（如'000300.SH'），
        因此需要将中文键名转换为资产代码，确保权重能被正确匹配。
        """
        selector_type = getattr(rt, 'selector_type', '') if rt else ''
        if selector_type != 'sharpe':
            return {}
        
        try:
            # 构建月末日期列表
            month_end_dates = []
            ym_series = pd.Series(prices_df.index, index=prices_df.index)
            for (year, month), group in ym_series.groupby([ym_series.index.year, ym_series.index.month]):
                month_end = normalize_calendar_timestamp(group.index[-1])
                month_end_dates.append(month_end)
            
            calc_date_strs = [d.strftime('%Y-%m-%d') for d in month_end_dates]
            if not calc_date_strs:
                return {}
            
            from app.config.collections import COL_SHARPE_REBALANCE_WEIGHTS
            coll = self.db[COL_SHARPE_REBALANCE_WEIGHTS]
            cursor = coll.find({"calc_date": {"$in": calc_date_strs}})
            docs = await cursor.to_list(length=500)
            
            # 中文资产名 → 资产代码映射表（与原型 step1/step2 的资产命名一致）
            SHARPE_NAME_TO_CODE = {
                '沪深300': '000300.SH', '中证500': 'ZZ000905', '创业板指': 'SZ399006',
                '标普500': 'SPX', '纳斯达克100': 'NDX', '日经225': 'N225',
                '中国10年国债': 'ZQGZ10', '中国5年国债': 'ZQGZ5', '中国2年国债': 'ZQGZ2',
                '美国10年国债': 'UST10', '美国2年国债': 'UST2',
                '可转债': 'CVTBND', '黄金': 'GLD', '布伦特原油': 'B00Y',
                '沪铜': 'SHCU', '沪铝': 'SHAL', '沪锡': 'SHSN', '豆粕': 'DM',
            }
            
            precomputed = {}
            for doc in docs:
                weights_cn = doc.get('weights', {})
                # 将中文键名转换为资产代码
                weights_code = {}
                for cn_name, weight in weights_cn.items():
                    asset_code = SHARPE_NAME_TO_CODE.get(cn_name, cn_name)  # 如未找到映射则保留原键
                    weights_code[asset_code] = weight
                precomputed[doc['calc_date']] = weights_code
            
            logger.info(
                f"加载原型预计算权重: {len(precomputed)}/{len(calc_date_strs)} 个月末日"
            )
            return precomputed
        except Exception as e:
            logger.warning(f"加载预计算权重失败，将回退到实时计算: {e}")
            return {}

    def _get_engine_adapter(self, rt=None) -> Optional[MonitorEngineAdapter]:
        """获取三层引擎适配器。

        优先使用已缓存的适配器；否则根据 rt 构建。
        主观配置模式（manual_allocation_mode）不使用适配器（走旧路径）。
        """
        # 主观配置模式不走三层引擎
        if rt is not None and getattr(rt, "manual_allocation_mode", False):
            return None

        # 已缓存的适配器
        if self._engine_adapter is not None:
            return self._engine_adapter

        # 根据 rt 构建
        if rt is not None:
            try:
                self._engine_adapter = MonitorEngineAdapter.from_runtime_config(rt)
                self._inject_monitor_panels()
                return self._engine_adapter
            except Exception as e:
                logger.warning(f"构建三层引擎适配器失败，回退旧引擎: {e}")
                return None

        return None

    def _resolve_declared_execution_delay(
        self,
        rt=None,
        default: int = _DEFAULT_MONTH_END_DELAY,
    ) -> int:
        """读策略声明的执行延迟（交易日），与回测 ScheduleResolver 同源.

        解析链：`adapter.pipeline.get_execution_schedule()["execution_delay"]`，
        已含模型级参数覆盖（CompositionPipeline 会先用模型参数覆盖 allocator 声明）。

        Args:
            rt: 监控运行时配置；None 或适配器不可用时返回 default
            default: 策略未声明时采用的延迟（月末路径缺省 2，与改造前硬编码一致）

        Returns:
            非负整数延迟；声明为负数或非整数时回落 default 并告警
        """
        adapter = self._get_engine_adapter(rt)
        if adapter is None:
            return default
        pipeline = getattr(adapter, "pipeline", None)
        if pipeline is None or not hasattr(pipeline, "get_execution_schedule"):
            return default
        try:
            sched = pipeline.get_execution_schedule() or {}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取执行调度声明失败，月末路径按缺省 T+{default}: {e}")
            return default
        raw = sched.get("execution_delay")
        if raw is None:
            return default
        try:
            delay = int(raw)
        except (TypeError, ValueError):
            logger.warning(
                f"execution_delay 声明非整数 {raw!r}，月末路径按缺省 T+{default}"
            )
            return default
        if delay < 0:
            logger.warning(
                f"execution_delay 声明为负数 {delay}，月末路径按缺省 T+{default}"
            )
            return default
        return delay

    def _build_event_driven_rebalance_map(
        self,
        prices_df: pd.DataFrame,
        trade_dates: List,
        skip_excluded_dates: List[str],
        rt=None,
        start_date: Optional[str] = None,
    ) -> Optional[dict]:
        """事件驱动/自然频率调仓映射，与回测通道同源（composition_pipeline.
        get_execution_schedule → ScheduleResolver，同 runner.generate_targets）。

        两种命中方式：
        1. 声明 `event_dates`（面板期日）：信号日=期日；
        2. 声明 `natural_frequency=True` 且 `rebalance_freq in {daily, weekly}`：
           信号日按 ScheduleResolver 的自然频率规则识别（weekly=每周第一个交易日）。
           该开关默认关闭：存量策略中存在声明 daily、但监控一直按月末推演的
           既有偏差（trend_cross_sectional / snowball_delta_hedge），默认开启会让
           其监控调仓日从每月一次突变到每交易日一次，故只允许策略显式声明。

        系统策略 calendar_source 恒为 prices，trade_dates=prices_df.index，
        与回测 ScheduleResolver 所用日历一致；execution_delay=0 时信号日=执行日。

        Returns:
            dict: 命中时的 {执行日: {weights, calc_date}}（可为空）；
            None: 未命中（无 event_dates 且未声明自然频率 / 无适配器 / 无日历），
                  调用方回退月末路径，存量策略零影响。
        """
        adapter = self._get_engine_adapter(rt)
        if adapter is None:
            return None
        pipeline = getattr(adapter, "pipeline", None)
        if pipeline is None or not hasattr(pipeline, "get_execution_schedule"):
            return None
        sched_dict = pipeline.get_execution_schedule() or {}
        raw_events = sched_dict.get("event_dates")
        freq_norm = str(sched_dict.get("rebalance_freq") or "").strip().lower()
        if not raw_events:
            if freq_norm not in _NATURAL_FREQS:
                return None
            if not bool(sched_dict.get("natural_frequency")):
                return None

        trade_dates_ts = [normalize_calendar_timestamp(d) for d in trade_dates]
        if not trade_dates_ts:
            return None

        from app.backtesting.schedule import (
            ExecutionSchedule,
            ScheduleResolver,
            _coerce_calendar_dates,
        )

        schedule = ExecutionSchedule(
            rebalance_freq=freq_norm or "daily",
            execution_delay=int(sched_dict.get("execution_delay", 0) or 0),
            skip_dates={str(d) for d in (skip_excluded_dates or [])},
            event_dates=_coerce_calendar_dates(raw_events),
        )
        resolver = ScheduleResolver(schedule, trade_dates_ts)
        signal_map = resolver.build_signal_to_execute_map(
            trade_dates_ts[0], trade_dates_ts[-1]
        )

        cut_ts = None
        if start_date:
            try:
                cut_ts = normalize_calendar_timestamp(
                    pd.Timestamp(str(start_date)[:10])
                )
            except (TypeError, ValueError):
                cut_ts = None

        # 先裁剪再算权重：daily/weekly 自然频率下全日历信号日可达数千个，
        # 逐个 compute_weights 会重算整段历史（每次一次完整 allocate）。
        # 执行日早于 start_date 的信号日对本轮监控无用，直接跳过。
        rebalance_map: dict = {}
        for sig in sorted(signal_map.keys()):
            exec_ts = signal_map[sig]
            if cut_ts is not None and exec_ts < cut_ts:
                continue
            try:
                weight_dict = adapter.compute_weights(prices_df, sig)
            except Exception as e:
                # 调仓日算不出权重属数据/配置缺口，必须让本轮初始化失败暴露；
                # 跳过该日会让它不建仓、净值静默走平（与不降级原则冲突）。
                raise ValueError(
                    f"事件驱动调仓 {sig.strftime('%Y-%m-%d')}"
                    f"（执行日 {exec_ts.strftime('%Y-%m-%d')}）权重计算失败：{e}"
                ) from e
            rebalance_map[exec_ts] = {
                "weights": weight_dict,
                "calc_date": sig.strftime("%Y-%m-%d"),
            }

        logger.info(
            f"事件驱动/自然频率调仓映射: {len(rebalance_map)} 个执行日"
            f"（rebalance_freq={schedule.rebalance_freq}，"
            f"信号日来源={'面板期日' if raw_events else '自然频率'}，"
            f"execution_delay={schedule.execution_delay}）"
        )
        return rebalance_map

    def _build_monthly_rebalance_map(
        self,
        prices_df: pd.DataFrame,
        trade_dates: List,
        skip_excluded_dates: List[str],
        rt=None,
        merged_params: Optional[Dict[str, Any]] = None,
        precomputed_weights: Optional[Dict[str, Dict[str, float]]] = None,
        start_date: Optional[str] = None,
    ) -> dict:
        """调仓映射构建，按策略声明分流（同源回测）：
        - 事件驱动（声明 event_dates / 面板期日）或自然频率（声明
          natural_frequency 的 daily/weekly）：信号日由 ScheduleResolver 识别；
        - 主观配置（manual_allocation_mode）：预设调仓日；
        - 其余（混合动量等月末策略）：月末信号 + 声明的 execution_delay
          （未声明时缺省 T+2，与改造前硬编码一致）。

        start_date：运行区间起点。给出时只计算该起点之后的信号日，
        及其之前最近的一个信号日（其执行日可能落在起点之后）。
        """
        merged_params = merged_params or {}
        if prices_df is None or getattr(prices_df, "empty", True):
            logger.warning("月度调仓映射跳过：价格数据为空")
            return {}
        if rt is not None and getattr(rt, "manual_allocation_mode", False):
            return self._build_manual_preset_rebalance_map(
                prices_df, trade_dates, skip_excluded_dates, merged_params, rt
            )

        # 事件驱动调仓（策略声明 event_dates / 面板期日）：与回测同源解析，
        # 命中则直接返回；未命中（存量月末策略）回退下方月末 T+2 路径
        event_map = self._build_event_driven_rebalance_map(
            prices_df, trade_dates, skip_excluded_dates, rt, start_date
        )
        if event_map is not None:
            return event_map

        trade_dates_ts = [normalize_calendar_timestamp(d) for d in trade_dates]
        excluded = {
            normalize_calendar_timestamp(d) for d in skip_excluded_dates
        }
        
        # 使用 prices_df.index 确定月末日期（与原型 step1 完全一致）
        # 原型 step1_asset_selection.py 使用:
        #   nav.groupby('year_month').apply(lambda x: x.index[-1])
        # 即按 prices.index 分组取每月最后一个日期。
        # 注意：prices_df.index 可能包含非中国交易日的国际交易日（如 11-28 周五
        # 美股开市但A股休市），这些日期在 trade_dates 中不存在但在 prices 中存在。
        # 原型正是使用这些日期作为月末计算日，因此监测也必须如此。
        month_end_dates = []
        ym_series = pd.Series(prices_df.index, index=prices_df.index)
        for (year, month), group in ym_series.groupby([ym_series.index.year, ym_series.index.month]):
            month_end = normalize_calendar_timestamp(group.index[-1])
            month_end_dates.append(month_end)
        
        month_end_dates.sort()

        # 区间裁剪：启动日之前的历史月份执行日早已过去，计算它们既浪费算力，
        # 又会在数据起点尚不足 min_history_days 的早期月份刷出无意义的告警。
        # 保留启动日前最近的一个月末信号：其 T+2 执行日可能正好落在启动日之后。
        cut_ts = None
        if start_date:
            try:
                cut_ts = normalize_calendar_timestamp(
                    pd.Timestamp(str(start_date)[:10])
                )
            except (TypeError, ValueError):
                cut_ts = None
            if cut_ts is not None:
                before_cut = [d for d in month_end_dates if d < cut_ts]
                month_end_dates = ([before_cut[-1]] if before_cut else []) + [
                    d for d in month_end_dates if d >= cut_ts
                ]
                logger.info(
                    f"调仓映射区间裁剪: 起点={cut_ts.strftime('%Y-%m-%d')}, "
                    f"参与计算信号月数={len(month_end_dates)}"
                )

        rebalance_map = {}

        # 执行延迟读策略声明（与回测 ScheduleResolver 同源）；未声明时缺省 T+2。
        exec_delay = self._resolve_declared_execution_delay(rt)
        trade_date_set = set(trade_dates_ts)

        # precomputed_weights 由调用方异步加载后传入（解决 motor cursor 不能在同步方法中使用的问题）
        precomputed_weights = precomputed_weights or {}
        
        for calc_date in month_end_dates:
            calc_date_str = calc_date.strftime('%Y-%m-%d')
            
            # 优先使用预计算权重
            if calc_date_str in precomputed_weights:
                pw = precomputed_weights[calc_date_str]
                asset_cols = list(prices_df.columns)
                weight_dict = {asset: pw.get(asset, 0.0) for asset in asset_cols}
            else:
                # 回退到实时计算（使用三层引擎适配器）
                try:
                    adapter = self._get_engine_adapter(rt)
                    if adapter is None and rt is not None:
                        adapter = MonitorEngineAdapter.from_runtime_config(rt)
                    if adapter is not None:
                        weight_dict = adapter.compute_weights(prices_df, calc_date)
                    else:
                        asset_cols = list(prices_df.columns)
                        weight_dict = {asset: 1.0 / len(asset_cols) for asset in asset_cols} if asset_cols else {}
                except Exception as e:
                    raise ValueError(
                        f"月末调仓 {calc_date_str} 权重计算失败：{e}"
                    ) from e
            
            if exec_delay <= 0:
                # T+0：执行日=信号日。月末信号取自 prices 轴，可能是非行情交易日
                # （多市场交易日），此时顺延到其后第一个行情交易日。
                execute_date = calc_date
                if execute_date not in trade_date_set:
                    future_dates = [d for d in trade_dates_ts if d > calc_date]
                    if not future_dates:
                        continue
                    execute_date = future_dates[0]
            else:
                future_dates = [d for d in trade_dates_ts if d > calc_date]
                if len(future_dates) >= exec_delay:
                    execute_date = future_dates[exec_delay - 1]
                elif future_dates:
                    # 历史末端信号不足声明延迟时，取最后一个交易日（与旧逻辑一致）
                    execute_date = future_dates[-1]
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
                'calc_date': calc_date_str,
            }

        # 跨启动日保留的那个月末信号，若其执行日仍早于启动日，
        # 则永远不会被执行；剔除后可避免操作列表出现永不失效的 pending 指令。
        if cut_ts is not None:
            rebalance_map = {
                exec_ts: info
                for exec_ts, info in rebalance_map.items()
                if exec_ts >= cut_ts
            }

        return rebalance_map

    # ============================================================
    # 主观配置预设调仓映射
    # ============================================================

    def _build_manual_preset_rebalance_map(
        self,
        prices_df: pd.DataFrame,
        trade_dates: List,
        skip_excluded_dates: List[str],
        merged_params: Dict[str, Any],
        rt,
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
