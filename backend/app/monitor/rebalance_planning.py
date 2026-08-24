# -*- coding: utf-8 -*-
"""
监控服务 Mixin：调仓计划构建（月末 T+2 / 主观预设日）与权重规划

自 monitor_service.py 平移而来，方法体保持不变，仅按职责归组：
1. 月度调仓映射（混合动量月末 T+2；主观配置预设调仓日）
2. sharpe 选择器预计算权重加载
3. 三层引擎适配器获取与手工权重归一化
"""

import pandas as pd
from typing import Dict, List, Optional, Any
from loguru import logger

from app.monitor.engine_adapter import MonitorEngineAdapter
from app.monitor.time_norm import normalize_calendar_timestamp


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
                return self._engine_adapter
            except Exception as e:
                logger.warning(f"构建三层引擎适配器失败，回退旧引擎: {e}")
                return None

        return None

    def _build_monthly_rebalance_map(
        self,
        prices_df: pd.DataFrame,
        trade_dates: List,
        skip_excluded_dates: List[str],
        rt=None,
        merged_params: Optional[Dict[str, Any]] = None,
        precomputed_weights: Optional[Dict[str, Dict[str, float]]] = None,
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
        
        rebalance_map = {}
        
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
                    logger.warning(f"{calc_date_str} 权重计算失败: {e}")
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
                'calc_date': calc_date_str,
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
