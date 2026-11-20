# -*- coding: utf-8 -*-
"""监控服务 Mixin：风险预警计算与落库（monitor_risk_alerts）

两条通道共用同一套检测函数（``app.monitor.risk_alert_detector``）：
- 策略通道：``daily_stepper._process_single_day`` 步骤 E3 调
  ``compute_risk_alerts``（同步纯计算），结果挂在 ``result['risk_alerts']``，
  由主循环随后调 ``save_risk_alerts`` 落库；
- 组合通道：``_run_portfolio_backtest_monitor`` 保存状态前调
  ``run_portfolio_risk_alerts``（加载穿透持仓行情 + 检测 + 落库）。

研究员通道（sharpe_18 / hybrid_12）本期不覆盖：独立引擎不走
``_process_single_day``、也不走组合管线，这两条路径不会写入预警记录。

依赖宿主（MonitorService）属性：async_provider、_runtime_for_reads。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from app.monitor.mongo_asset_codes import canonical_price_code
from app.monitor.risk_alert_detector import (
    DEFAULT_ALERT_CONFIG,
    RiskAlert,
    build_returns_matrix,
    detect_corr_reversal_alerts,
    detect_vol_compare_alerts,
)
from app.services.monitor_risk_alert_service import MonitorRiskAlertService


class RiskAlertRecorderMixin:
    """风险预警计算与落库方法群。"""

    _risk_alert_service: Optional[MonitorRiskAlertService] = None

    @property
    def risk_alert_service(self) -> MonitorRiskAlertService:
        """风险预警记录服务（懒加载单例）。"""
        if RiskAlertRecorderMixin._risk_alert_service is None:
            RiskAlertRecorderMixin._risk_alert_service = MonitorRiskAlertService()
        return RiskAlertRecorderMixin._risk_alert_service

    def _alert_batch_id(self) -> Optional[str]:
        """当前运行批次号（由宿主 MonitorService 的批次上下文提供）。

        ``risk_alert_service`` 是跨 MonitorService 实例共享的**类级单例**，
        因此批次号必须逐调用显式传入，不能挂在服务实例上。
        """
        getter = getattr(self, "_current_batch_id", None)
        if not callable(getter):
            return None
        try:
            return getter() or None
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 计算（同步，便于在 _process_single_day 内调用）
    # ------------------------------------------------------------------

    def compute_risk_alerts(
        self,
        weights: Dict[str, float],
        prices_df: pd.DataFrame,
        as_of=None,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """按持仓权重与价格面板计算风险预警（同步纯计算，不落库）。

        Args:
            weights: 持仓权重 {资产键: 权重}；仅取权重大于 0 的资产，按权重降序。
            prices_df: 价格面板（index=交易日，columns=资产键）。
            as_of: 截止日（Timestamp / str）；传了就只用到该日为止的行情。
            config: 阈值覆盖（默认 DEFAULT_ALERT_CONFIG）。

        Returns:
            ``RiskAlert.to_dict()`` 列表；行情不足或空持仓时返回空列表。
        """
        if not weights or prices_df is None or prices_df.empty:
            return []
        cfg = dict(DEFAULT_ALERT_CONFIG)
        cfg.update(config or {})

        ordered_pairs = sorted(
            ((str(k), float(v or 0.0)) for k, v in weights.items()),
            key=lambda kv: -kv[1],
        )
        ordered: List[str] = [k for k, v in ordered_pairs if v > 0 and k != "CASH"]
        if not ordered:
            return []

        prices = prices_df
        if as_of is not None:
            try:
                prices = prices.loc[:pd.Timestamp(as_of)]
            except (TypeError, ValueError):
                prices = prices_df

        # 资产键对齐：穿透权重键可能带存储后缀，价格列名为标准码
        column_map: Dict[str, str] = {}
        available = set(prices.columns)
        for key in ordered:
            if key in available:
                column_map[key] = key
            else:
                canon = canonical_price_code(key)
                if canon in available:
                    column_map[key] = canon
        aligned = [column_map[k] for k in ordered if k in column_map]
        if not aligned:
            logger.warning(
                f"[风险预警] 持仓资产与行情列无交集，跳过检测: "
                f"assets={ordered[:5]}..., price_cols={list(prices.columns)[:5]}..."
            )
            return []

        # 行情新鲜度过滤：剔除最后有效日期明显早于面板最新日的资产（停更 / 退市）。
        # 不过滤的话，dropna 会把相关性窗口悄悄截停在停更日，用陈旧历史冒充当前信号。
        last_dates: Dict[str, pd.Timestamp] = {}
        for col in aligned:
            series = prices[col].dropna()
            if not series.empty:
                last_dates[col] = series.index.max()
        if not last_dates:
            return []
        anchor = max(last_dates.values())
        stale_cutoff = anchor - pd.Timedelta(days=int(cfg["price_stale_days"]))
        fresh = [c for c in aligned if last_dates.get(c) is not None and last_dates[c] >= stale_cutoff]
        if not fresh:
            return []
        dropped = [c for c in aligned if c not in fresh]
        if dropped:
            logger.info(
                f"[风险预警] 跳过行情停更资产: date={as_of}, "
                f"stale={dropped[:5]}... (共 {len(dropped)}/{len(aligned)})"
            )

        window = max(
            int(cfg["corr_baseline_window"]),
            int(cfg["vol_long_window"]),
            int(cfg["corr_window"]),
        )
        returns_matrix = build_returns_matrix(prices, fresh, window)
        if returns_matrix.empty:
            return []

        # 检测函数按列顺序取前 N 大持仓，这里保持权重降序
        alerts = detect_vol_compare_alerts(
            returns_matrix,
            vol_windows={
                "short": int(cfg["vol_short_window"]),
                "long": int(cfg["vol_long_window"]),
            },
            config=cfg,
        )
        alerts += detect_corr_reversal_alerts(
            returns_matrix,
            corr_window=int(cfg["corr_window"]),
            config=cfg,
        )
        # 停更跳过提示：让「为什么某资产没有预警」在页面上可见，不静默丢弃
        if dropped:
            alerts.append(RiskAlert(
                signal_type="stale_skip",
                severity="info",
                trigger_value=float(len(dropped)),
                threshold=float(cfg["price_stale_days"]),
                window_pair={},
                asset_codes=list(dropped),
                detail={
                    "stale_count": len(dropped),
                    "checked_count": len(aligned),
                    "stale_days_threshold": int(cfg["price_stale_days"]),
                    "last_price_dates": {
                        c: str(last_dates[c].date()) for c in dropped if c in last_dates
                    },
                },
            ))
        return [a.to_dict() for a in alerts]

    # ------------------------------------------------------------------
    # 落库
    # ------------------------------------------------------------------

    async def save_risk_alerts(
        self,
        monitor_id: str,
        monitor_kind: str,
        signal_date: str,
        alerts: List[Dict[str, Any]],
    ) -> int:
        """落库一批预警（按 monitor_id + batch_id + signal_date 覆盖，失败不阻断推演）。"""
        if not alerts:
            return 0
        batch_id = self._alert_batch_id()
        try:
            written = await self.risk_alert_service.replace_for_signal_date(
                monitor_id=monitor_id,
                monitor_kind=monitor_kind,
                signal_date=signal_date,
                alerts=alerts,
                batch_id=batch_id,
            )
            counts: Dict[str, int] = {}
            for a in alerts:
                sev = a.get("severity") or ""
                counts[sev] = counts.get(sev, 0) + 1
            logger.info(
                f"[风险预警] 写入完成: monitor={monitor_id}, kind={monitor_kind}, "
                f"batch={batch_id}, date={signal_date}, count={written}, severity={counts}"
            )
            return written
        except Exception as e:
            logger.warning(f"[风险预警] 落库失败（不影响监控）: monitor={monitor_id}, error={e}")
            return 0

    # ------------------------------------------------------------------
    # 组合通道：穿透持仓 → 行情 → 检测 → 落库
    # ------------------------------------------------------------------

    async def run_portfolio_risk_alerts(
        self,
        monitor_id: str,
        state_fields: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> int:
        """组合通道预警：从穿透后持仓金额加载行情并落库。

        Args:
            monitor_id: 监控实例 ID
            state_fields: ``build_monitor_state_fields`` 组装的状态字段
                （需含 ``positions_cny`` 与 ``date``）

        Returns:
            写入条数
        """
        positions = state_fields.get("positions_cny") or {}
        signal_date = str(state_fields.get("date") or "")[:10]
        if not positions or not signal_date:
            return 0

        # 只取权重大于 0 的穿透资产，按金额降序（决定相关性配对优先级）
        ordered = [
            (str(k), float(v or 0.0))
            for k, v in sorted(positions.items(), key=lambda kv: -float(kv[1] or 0.0))
            if float(v or 0.0) > 0
        ]
        cfg = dict(DEFAULT_ALERT_CONFIG)
        cfg.update(config or {})
        limit = max(int(cfg["vol_max_assets"]), int(cfg["corr_max_assets"]))
        probe = []
        for key, _ in ordered[:limit]:
            canon = canonical_price_code(key)
            if canon not in probe:
                probe.append(canon)
        if not probe:
            return 0

        try:
            prices = await self.async_provider.load_prices(asset_columns=probe)
        except Exception as e:
            logger.warning(f"[风险预警] 组合行情加载失败，跳过预警: monitor={monitor_id}, error={e}")
            return 0
        if prices is None or prices.empty:
            logger.warning(f"[风险预警] 组合穿透资产无行情，跳过预警: monitor={monitor_id}, probe={probe[:5]}")
            return 0

        alerts = self.compute_risk_alerts(
            {k: v for k, v in ordered}, prices, as_of=signal_date, config=cfg
        )
        return await self.save_risk_alerts(
            monitor_id=monitor_id,
            monitor_kind="portfolio",
            signal_date=signal_date,
            alerts=alerts,
        )
