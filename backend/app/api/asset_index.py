# -*- coding: utf-8 -*-
"""
大类资产指数 API

拆分 risk budget vol + 混合动量资产选择策略的回测部分，构建独立的大类资产指数界面。
- 波动率阈值固定选项：0.04, 0.06, 0.08, 0.10
- 开始日期固定：2014-02-10
- 结束日期默认：2026-02-27
- 0.06 对应对照组结果数据，<= 2026-02-27 时直接使用 data/ 下对照开头的结果文件
- 超出 2026-02-27 则在对照组基础上继续跑
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas.response import Response

router = APIRouter()
_log = logging.getLogger(__name__)

# 固定参数
ASSET_INDEX_START_DATE = "2014-02-10"
ASSET_INDEX_END_DATE_DEFAULT = "2026-02-27"
VOL_THRESHOLD_OPTIONS = [0.04, 0.06, 0.08, 0.10]

# 资产名称 -> 代码 映射（对照文件用中文名）
NAME_TO_CODE = {
    "沪深300": "SH000300", "创业板指": "SZ399006", "红利低波": "ZZ000001",
    "恒生科技": "HSTECH", "标普500": "SPX", "德国DAX": "GDAXI",
    "中国10年国债": "ZQGZ10", "中国2年国债": "ZQGZ2",
    "布伦特原油": "B00Y", "黄金": "GLD", "铁矿石": "IRON", "中国有色金属": "YSJS",
}

RISK_FREE_RATE = 0.02


# 绩效指标合理范围（数据缺失/不一致时避免极端值）
_NAV_PERF_RETURN_MIN, _NAV_PERF_RETURN_MAX = -1.0, 10.0
_NAV_PERF_VOL_MAX = 5.0
_NAV_PERF_DD_MIN, _NAV_PERF_DD_MAX = -1.0, 0.0
_NAV_PERF_RATIO_ABS_MAX = 50.0


def _compute_performance_from_nav(nav_history: List[Dict], risk_free: float = RISK_FREE_RATE) -> Dict[str, Any]:
    """
    根据 nav_history（至 end_date 的当日净值）计算绩效指标，而非使用对照文件中的固定绩效。
    对缺失/异常净值做清理，并将收益率、回撤、波动率、卡玛等限制在合理范围内。
    """
    if not nav_history or len(nav_history) < 2:
        return {}
    raw_navs = []
    for r in nav_history:
        v = r.get("nav", 0) or 0
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = 0.0
        if not (np.isnan(x) or np.isinf(x) or x < 0):
            raw_navs.append(x)
        else:
            raw_navs.append(0.0)
    navs = pd.Series(raw_navs).replace(0.0, float("nan")).ffill().bfill().fillna(1.0).tolist()
    if len(navs) < 2:
        return {}
    start_val = navs[0]
    end_val = navs[-1]
    if start_val <= 0 or not np.isfinite(start_val):
        return {}
    total_return = (end_val / start_val) - 1.0
    total_return = max(_NAV_PERF_RETURN_MIN, min(_NAV_PERF_RETURN_MAX, total_return))
    days = len(nav_history)
    years = max(days / 252.0, 1e-6)
    annual_return = (1.0 + total_return) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    annual_return = max(_NAV_PERF_RETURN_MIN, min(_NAV_PERF_RETURN_MAX, annual_return))

    returns = []
    for i in range(1, len(navs)):
        if navs[i - 1] > 1e-12:
            r = (navs[i] - navs[i - 1]) / navs[i - 1]
            if np.isfinite(r):
                returns.append(r)
            else:
                returns.append(0.0)
        else:
            returns.append(0.0)
    if not returns:
        return {}
    ret_series = pd.Series(returns)
    vol_daily = float(ret_series.std())
    annual_vol = vol_daily * (252 ** 0.5) if vol_daily > 0 else 0.0
    annual_vol = min(_NAV_PERF_VOL_MAX, annual_vol)

    cummax = np.maximum.accumulate(navs)
    drawdowns = [(navs[i] - cummax[i]) / cummax[i] if cummax[i] > 0 else 0.0 for i in range(len(navs))]
    max_drawdown = float(min(drawdowns)) if drawdowns else 0.0
    max_drawdown = max(_NAV_PERF_DD_MIN, min(_NAV_PERF_DD_MAX, max_drawdown))

    sharpe = (annual_return - risk_free) / annual_vol if annual_vol > 1e-12 else 0.0
    sharpe = max(-_NAV_PERF_RATIO_ABS_MAX, min(_NAV_PERF_RATIO_ABS_MAX, sharpe))
    calmar = annual_return / abs(max_drawdown) if max_drawdown and abs(max_drawdown) > 1e-12 else 0.0
    calmar = max(-_NAV_PERF_RATIO_ABS_MAX, min(_NAV_PERF_RATIO_ABS_MAX, calmar))

    return {
        "start_date": nav_history[0].get("date", ""),
        "end_date": nav_history[-1].get("date", ""),
        "initial_nav": start_val,
        "final_nav": end_val,
        "total_return": total_return,
        "annual_return": annual_return,
        "volatility": annual_vol,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "calmar_ratio": calmar,
    }


def _normalize_vol_reset_event(e: Dict) -> Dict:
    """将波动率重置事件标准化为统一字段名，兼容 Excel 中英文列名"""
    def get_val(*keys):
        for k in keys:
            v = e.get(k)
            if v is not None and (not (isinstance(v, float) and pd.isna(v))):
                return v
        return None

    signal = get_val("信号日期", "signal_date")
    execute = get_val("执行日期", "execute_date")
    vol_trigger = get_val("VolTrigger", "vol_trigger", "波动率触发")
    scale_factor = get_val("缩放因子", "scale_factor")
    out = {
        "signal_date": str(pd.Timestamp(signal).date()) if signal is not None else "",
        "execute_date": str(pd.Timestamp(execute).date()) if execute is not None else "",
        "vol_trigger": float(vol_trigger) if vol_trigger is not None else None,
        "scale_factor": float(scale_factor) if scale_factor is not None else None,
    }
    # 保留其他列供前端展示
    for k, v in e.items():
        if k not in ("信号日期", "signal_date", "执行日期", "execute_date", "VolTrigger", "vol_trigger", "波动率触发", "缩放因子", "scale_factor"):
            if v is not None and (not (isinstance(v, float) and pd.isna(v))):
                out[k] = v
    return out


def _resolve_control_data_dir() -> Optional[str]:
    """解析对照数据目录，优先 data/ 下对照开头的文件所在目录"""
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates = [
        os.path.join(_root, "data"),
        os.path.join(_root, "动量策略相关资料"),
        os.path.join(os.path.dirname(_root), "动量策略相关资料"),
        os.path.join(os.path.dirname(_root), "data"),
    ]
    for d in candidates:
        if not os.path.isdir(d):
            continue
        # 检查是否有对照开头的回测结果文件
        for f in os.listdir(d) if os.path.isdir(d) else []:
            if f.startswith("对照") and "回测" in f and f.endswith(".xlsx"):
                return d
    return None


def _list_nav_files_with_first_date() -> List[Dict[str, str]]:
    """
    扫描 data 目录下净值文件，提取每个文件的第一日作为可选开始日期。
    返回 [{"start_date": "20170210", "label": "2017-02-10", "path": "..."}, ...]，按日期排序。
    """
    data_dir = _resolve_control_data_dir()
    if not data_dir:
        return []
    result = []
    for f in os.listdir(data_dir):
        if not (f.endswith(".xlsx") and ("回测" in f or "净值" in f.lower())):
            continue
        path = os.path.join(data_dir, f)
        if not os.path.isfile(path):
            continue
        try:
            nav_df = pd.read_excel(path, sheet_name="每日净值", index_col=None)
            if nav_df.empty:
                continue
            date_col = "日期" if "日期" in nav_df.columns else nav_df.columns[0]
            nav_df[date_col] = pd.to_datetime(nav_df[date_col]).dt.normalize()
            first_dt = nav_df[date_col].min()
            if pd.isna(first_dt):
                continue
            ymd = first_dt.strftime("%Y%m%d")
            label = first_dt.strftime("%Y-%m-%d")
            result.append({"start_date": ymd, "label": label, "path": path})
        except Exception:
            continue
    result.sort(key=lambda x: x["start_date"])
    return result


def _resolve_control_backtest_path(vol_threshold: float, start_date: Optional[str] = None) -> Optional[str]:
    """
    解析对照回测结果文件路径。
    start_date: YYYYMMDD，若提供则从 _list_nav_files_with_first_date 中匹配首日相同的文件。
    """
    if start_date:
        for item in _list_nav_files_with_first_date():
            if item["start_date"] == start_date:
                return item["path"]
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    base_name = "对照_回测结果_汇率版_v1"
    if abs(vol_threshold - 0.06) < 1e-6:
        fname = f"{base_name}.xlsx"
    else:
        fname = f"{base_name}_{vol_threshold:.2f}.xlsx"

    candidates = [
        os.path.join(_root, "data", fname),
        os.path.join(_root, "data", base_name + ".xlsx"),
        os.path.join(os.path.dirname(_root), "data", fname),
        os.path.join(os.path.dirname(_root), "data", base_name + ".xlsx"),
        os.path.join(_root, "动量策略相关资料", fname),
        os.path.join(_root, "动量策略相关资料", base_name + ".xlsx"),
        os.path.join(os.path.dirname(_root), "动量策略相关资料", fname),
        os.path.join(os.path.dirname(_root), "动量策略相关资料", base_name + ".xlsx"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _load_control_backtest(
    vol_threshold: float,
    end_date: pd.Timestamp,
    start_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    加载对照回测结果，截取 [start_date, end_date]。
    start_date: YYYYMMDD，若提供则优先匹配首日相同的净值文件。
    """
    path = _resolve_control_backtest_path(vol_threshold, start_date)
    if not path or not os.path.isfile(path):
        return None

    try:
        nav_df = pd.read_excel(path, sheet_name="每日净值", index_col=None)
    except Exception as e:
        _log.warning("[大类资产指数] 读取对照回测文件失败: %s", e)
        return None

    if nav_df.empty:
        return None

    # 日期列（可能为列名或索引）
    if "日期" in nav_df.columns:
        date_col = "日期"
    elif nav_df.index.name == "日期" or (isinstance(nav_df.index, pd.DatetimeIndex)):
        nav_df = nav_df.reset_index()
        date_col = nav_df.columns[0]
    else:
        date_col = nav_df.columns[0]
    nav_df[date_col] = pd.to_datetime(nav_df[date_col]).dt.normalize()
    nav_df = nav_df[nav_df[date_col] <= end_date].copy()
    if start_date:
        start_ts = pd.Timestamp(start_date[:4] + "-" + start_date[4:6] + "-" + start_date[6:8])
        nav_df = nav_df[nav_df[date_col] >= start_ts].copy()
    nav_df = nav_df.sort_values(date_col).reset_index(drop=True)

    if nav_df.empty:
        return None

    # 净值列
    nav_col = "净值" if "净值" in nav_df.columns else nav_df.columns[1]

    # 权重列（排除 日期、净值、总杠杆、波动率、调仓日 等）
    exclude_cols = {"日期", "净值", "总杠杆", "波动率", "调仓日"}
    weight_cols = [c for c in nav_df.columns if c not in exclude_cols and c != date_col]
    weight_cols = [c for c in weight_cols if c in NAME_TO_CODE or c in NAME_TO_CODE.values()]

    # 波动率重置事件（对照文件 sheet 页内容，标准化列名供前端展示）
    vol_events = []
    vol_reset_exec_dates = set()
    try:
        events_df = pd.read_excel(path, sheet_name="波动率重置事件")
        if events_df is not None and not events_df.empty:
            exec_col = "执行日期" if "执行日期" in events_df.columns else (
                "execute_date" if "execute_date" in events_df.columns else None
            )
            if exec_col:
                events_df[exec_col] = pd.to_datetime(events_df[exec_col]).dt.normalize()
                events_df = events_df[events_df[exec_col] <= end_date]
                raw_events = events_df.to_dict("records")
                vol_reset_exec_dates = {str(pd.Timestamp(e.get(exec_col)).date()) for e in raw_events}
                # 标准化为统一字段名，兼容中英文列名
                for e in raw_events:
                    vol_events.append(_normalize_vol_reset_event(e))
    except Exception:
        pass

    # 波动率列
    vol_col = "波动率" if "波动率" in nav_df.columns else None
    rebal_col = "调仓日" if "调仓日" in nav_df.columns else None

    # 构建 nav_history（含权重、波动率、调仓日、rebalance_type）
    nav_history = []
    navs_raw = []
    for _, row in nav_df.iterrows():
        dt = row[date_col]
        dt_str = str(pd.Timestamp(dt).date())
        nav_val = float(row.get(nav_col, 0))
        navs_raw.append(nav_val)

        is_reb = False
        if rebal_col is not None:
            rb_val = row.get(rebal_col)
            is_reb = rb_val == "是" or rb_val is True or (isinstance(rb_val, str) and "是" in str(rb_val))

        reb_type = None
        reb_reason = None
        if is_reb:
            if dt_str in vol_reset_exec_dates:
                reb_type = "vol_reset"
                reb_reason = "波动率触发重置"
            else:
                reb_type = "regular"
                reb_reason = "周期性调仓"

        vol_val = None
        if vol_col is not None:
            v = row.get(vol_col)
            if pd.notna(v) and v is not None:
                try:
                    vol_val = float(v)
                except (TypeError, ValueError):
                    pass

        rec = {
            "date": dt_str,
            "nav": nav_val,
            "weights": {},
            "volatility": vol_val,
            "is_rebalance_day": is_reb,
            "rebalance_type": reb_type,
            "rebalance_reason": reb_reason,
        }
        for c in weight_cols:
            rec["weights"][c] = float(row.get(c, 0) or 0)
        nav_history.append(rec)

    # 计算回撤序列（根据当日净值）
    cummax = np.maximum.accumulate(navs_raw) if navs_raw else []
    for i, rec in enumerate(nav_history):
        if i < len(cummax) and cummax[i] > 0:
            rec["drawdown"] = (navs_raw[i] - cummax[i]) / cummax[i]
        else:
            rec["drawdown"] = 0.0

    # 波动率缺失时按净值序列计算滚动年化波动率（21 日窗口）
    has_vol = sum(1 for r in nav_history if r.get("volatility") is not None and (r.get("volatility") or 0) != 0)
    if has_vol < len(nav_history) * 0.5:
        roll_window = 21
        navs = np.array(navs_raw, dtype=float)
        for i, rec in enumerate(nav_history):
            start = max(0, i - roll_window)
            slice_navs = navs[start : i + 1]
            if len(slice_navs) >= 2:
                rets = np.diff(slice_navs) / slice_navs[:-1]
                ann_vol = float(np.std(rets)) * (252 ** 0.5) if len(rets) > 0 else 0.0
                rec["volatility"] = ann_vol
            else:
                rec["volatility"] = 0.0

    # 绩效指标：按当日净值计算，而非使用对照文件中的固定绩效
    perf_dict = _compute_performance_from_nav(nav_history)

    return {
        "nav_history": nav_history,
        "performance": perf_dict,
        "vol_reset_events": vol_events,
        "from_control_file": True,
    }


async def _run_engine_backtest(
    vol_threshold: float,
    start_date: str,
    end_date: str,
) -> Dict[str, Any]:
    """
    使用混合动量引擎运行回测（用于非 0.06 或扩展 2026-02-27 之后）
    """
    from app.backtesting.config import BacktestConfig
    from app.backtesting.data_feed import DataFeed
    from app.services.market_service import MarketService
    from app.services.fx_service import FxService
    from app.config.zy_document_max_weights import ZY_DOCUMENT_CODE_TO_NAME
    from app.config.asset_cost_currency import ASSET_CURRENCY_BY_CODE, get_trading_cost, get_replication_cost
    from app.models.asset import AssetType
    from app.risk_budget_special.backtest_api import run_hybrid_momentum_backtest, HybridMomentumConfig

    asset_codes = list(ZY_DOCUMENT_CODE_TO_NAME.keys())
    market_service = MarketService()
    fx_service = FxService()

    config = BacktestConfig(
        name="asset_index",
        thscodes=asset_codes,
        start_date=start_date,
        end_date=end_date,
    )
    data_feed = await DataFeed.from_market_service(
        market_service=market_service,
        config=config,
        lookback_days=500,
    )
    if data_feed.prices is None or data_feed.prices.empty:
        raise HTTPException(status_code=400, detail="价格数据为空，无法运行回测")

    prices = data_feed.prices
    prices = prices[prices.index >= pd.Timestamp(start_date)]
    if prices.empty:
        raise HTTPException(status_code=400, detail="起始日期后无价格数据")

    asset_currency_map = {c: ASSET_CURRENCY_BY_CODE.get(c, "CNH") for c in asset_codes}
    fx_rates = await fx_service.get_fx_series_for_assets(
        asset_currency_map, start_date, end_date
    )
    transaction_costs = {c: get_trading_cost(AssetType.INDEX, None) for c in asset_codes}
    replication_costs = {c: get_replication_cost(AssetType.INDEX, None) for c in asset_codes}
    weight_caps = {
        "沪深300": 0.10, "创业板指": 0.10, "红利低波": 0.10, "恒生科技": 0.10,
        "标普500": 0.15, "德国DAX": 0.10, "中国10年国债": 0.60, "中国2年国债": 0.90,
        "布伦特原油": 0.10, "黄金": 0.10, "铁矿石": 0.10, "中国有色金属": 0.10,
    }
    code_to_name = ZY_DOCUMENT_CODE_TO_NAME
    weight_caps_by_code = {c: weight_caps.get(code_to_name.get(c, c), 0.10) for c in asset_codes}

    cfg = HybridMomentumConfig(
        base_date=pd.Timestamp(start_date),
        vol_trigger_threshold=vol_threshold,
        enable_vol_control=False,
        enable_costs=True,
        enable_fx=True,
        fx_rates=fx_rates or {},
        transaction_costs=transaction_costs,
        replication_costs=replication_costs,
        weight_caps=weight_caps_by_code,
    )
    result = run_hybrid_momentum_backtest(prices=prices, config=cfg)

    nav_series = result.get("nav_series", pd.Series())
    snapshots = result.get("snapshots", [])
    perf = result.get("performance", {})
    vol_events = result.get("vol_reset_events", [])

    nav_history = []
    for s in snapshots:
        t = getattr(s, "time", None)
        tv = getattr(s, "total_value", 0)
        w = getattr(s, "weights", {}) or {}
        rec = {
            "date": str(pd.Timestamp(t).date()) if t else "",
            "nav": float(tv),
            "weights": {code_to_name.get(a, a): float(w.get(a, 0)) for a in w},
            "volatility": getattr(s, "portfolio_volatility", None),
            "is_rebalance_day": getattr(s, "is_rebalance_day", False),
            "rebalance_type": getattr(s, "rebalance_type", None),
            "rebalance_reason": getattr(s, "rebalance_reason", None),
        }
        nav_history.append(rec)

    # 计算回撤
    navs_raw = [r["nav"] for r in nav_history]
    cummax = np.maximum.accumulate(navs_raw) if navs_raw else []
    for i, rec in enumerate(nav_history):
        rec["drawdown"] = (navs_raw[i] - cummax[i]) / cummax[i] if i < len(cummax) and cummax[i] > 0 else 0.0

    # 波动率缺失时按净值序列计算滚动年化波动率（21 日窗口）
    has_vol = sum(1 for r in nav_history if r.get("volatility") is not None and (r.get("volatility") or 0) != 0)
    if has_vol < len(nav_history) * 0.5:
        roll_window = 21
        navs_arr = np.array(navs_raw, dtype=float)
        for i, rec in enumerate(nav_history):
            start = max(0, i - roll_window)
            slice_navs = navs_arr[start : i + 1]
            if len(slice_navs) >= 2:
                rets = np.diff(slice_navs) / slice_navs[:-1]
                ann_vol = float(np.std(rets)) * (252 ** 0.5) if len(rets) > 0 else 0.0
                rec["volatility"] = ann_vol
            else:
                rec["volatility"] = 0.0

    # 绩效按 nav_history 计算（与对照逻辑一致）
    perf = _compute_performance_from_nav(nav_history)

    return {
        "nav_history": nav_history,
        "performance": perf,
        "vol_reset_events": [
            {
                "signal_date": str(e.get("signal_date", "")),
                "execute_date": str(e.get("execute_date", "")),
                "vol_trigger": e.get("vol_trigger"),
                "scale_factor": e.get("scale_factor"),
            }
            for e in vol_events
        ],
        "from_control_file": False,
    }


@router.get(
    "/asset-index/start-dates",
    summary="获取可选开始日期列表",
    description="从 data 目录下净值文件提取每个文件的第一日，作为可选开始日期。",
)
async def asset_index_start_dates() -> Response:
    """返回可选开始日期列表，供前端下拉选择"""
    items = _list_nav_files_with_first_date()
    if not items:
        # 无多文件时，返回默认 2014-02-10
        return Response.success(data=[{"start_date": "20140210", "label": "2014-02-10"}])
    return Response.success(data=items)


@router.get(
    "/asset-index/backtest",
    summary="大类资产指数回测",
    description="基于 risk budget vol + 混合动量资产选择策略，展示大类资产指数的权重和净值。"
    "波动率阈值 0.06 对应对照组数据，<= 2026-02-27 时直接使用对照文件；其他阈值或超出日期则运行引擎。",
)
async def asset_index_backtest(
    vol_threshold: float = Query(0.06, description="波动率阈值，固定 0.06"),
    start_date: str = Query("20140210", description="开始日期 YYYYMMDD，对应净值文件首日"),
    end_date: str = Query("20260227", description="结束日期 YYYYMMDD，默认 2026-02-27"),
) -> Response:
    if abs(vol_threshold - 0.06) > 1e-6:
        vol_threshold = 0.06
    end_ts = pd.Timestamp(end_date[:4] + "-" + end_date[4:6] + "-" + end_date[6:8])
    control_end = pd.Timestamp(ASSET_INDEX_END_DATE_DEFAULT)

    result = None
    from_control = False

    # 0.06：优先使用对照文件。按 start_date 匹配净值文件，截取至 end_date
    if abs(vol_threshold - 0.06) < 1e-6:
        load_end = control_end if end_ts > control_end else end_ts
        result = _load_control_backtest(vol_threshold, load_end, start_date)
        if result:
            from_control = True

    # 若无对照数据，运行引擎
    start_date_str = start_date
    if result is None:
        try:
            result = await _run_engine_backtest(vol_threshold, start_date_str, end_date)
        except HTTPException:
            raise
        except Exception as e:
            _log.exception("[大类资产指数] 引擎回测失败: %s", e)
            raise HTTPException(status_code=500, detail=f"回测失败: {str(e)}")

    # 若 0.06 且 end_date > 2026-02-27：在 2026-02-27 持仓下继续，扩展段净值缩放衔接并重算绩效
    if abs(vol_threshold - 0.06) < 1e-6 and end_ts > control_end and from_control:
        try:
            ext_result = await _run_engine_backtest(vol_threshold, "20260228", end_date)
            cutoff = ASSET_INDEX_END_DATE_DEFAULT
            ext_history = [r for r in ext_result.get("nav_history", []) if r.get("date", "") > cutoff]
            if ext_history:
                last_ctrl = result["nav_history"][-1] if result["nav_history"] else None
                first_ext_nav = ext_history[0].get("nav") or 0
                if last_ctrl and first_ext_nav > 0:
                    scale = float(last_ctrl.get("nav", 0)) / first_ext_nav
                    for r in ext_history:
                        r["nav"] = (r.get("nav") or 0) * scale
                    navs_ext = [r["nav"] for r in ext_history]
                    cummax = np.maximum.accumulate(navs_ext)
                    for i, r in enumerate(ext_history):
                        r["drawdown"] = (navs_ext[i] - cummax[i]) / cummax[i] if cummax[i] > 0 else 0.0
                result["nav_history"].extend(ext_history)
                result["vol_reset_events"].extend(ext_result.get("vol_reset_events", []))
                result["performance"] = _compute_performance_from_nav(result["nav_history"])
        except Exception as e:
            _log.warning("[大类资产指数] 扩展 2026-02-27 之后失败: %s", e)

    return Response.success(data=result)
