"""回测服务API - 基于新的 BacktestEngine"""
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import traceback
import math
import logging

logger = logging.getLogger(__name__)

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from bson import ObjectId
from app.schemas.strategy_model import (
    BacktestRecordOut,
    BacktestRequest as ModelBacktestRequest
)
from pydantic import BaseModel, Field, field_validator

from app.schemas.response import Response
from app.services.market_service import MarketService
from app.services.asset_service import AssetService
from app.services.model_template_service import ModelTemplateService
from app.services.strategy_model_service import StrategyModelService
from app.models.strategy_model import (
    BacktestRecord, 
    BacktestResult as ModelBacktestResult,
    EquityPoint,
    ReturnPoint,
    PositionRecord,
    AssetPosition,
    WeightChangePoint
)
from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.engine import BacktestEngine
from app.backtesting.risk import RiskManager, RiskConfig
from app.backtesting.execution import ExecutionEngine
from app.backtesting.strategy_api import StrategiesWrapper
from app.strategies.services.registry import create_strategy_service_from_database
from app.analysis.formulas.drawdown import calculate_drawdown_series
from app.config.zy_document_max_weights import (
    ZY_DOCUMENT_MAX_WEIGHT_BY_ASSET_NAME,
    ZY_DOCUMENT_MAX_WEIGHT_ALIASES,
    ZY_DOCUMENT_MAX_WEIGHT_BY_CODE,
    ZY_DOCUMENT_DEFAULT_MAX_WEIGHT,
    ZY_DOCUMENT_CODE_TO_NAME,
)
from app.config.asset_cost_currency import (
    get_trading_cost,
    get_replication_cost,
    get_currency_for_asset,
)
from app.services.fx_service import FxService

router = APIRouter()


def _is_manual_strategy(strategy_type: str) -> bool:
    """主观策略不应用指数编制规则权重上限；仅动量/量化策略需限制。"""
    _st = (strategy_type or "").strip().lower()
    return _st in ("manual_allocation", "manual_allocation_strategy") or "manual" in _st


async def _build_manual_replication_costs(
    thscodes: List[str],
    asset_service: Optional[AssetService] = None,
) -> Dict[str, float]:
    """主观策略复制费率：与监控引擎 portfolio_tracker._resolve_replication_cost 对齐，
    使主观回测 NAV 计算包含与监控相同的每日复制费用扣减。

    解析顺序（与监控 monitor_runtime._resolve_config_scalar_by_asset_key 保持一致）：
    1) 资产代码直接命中 REPLICATION_COST（兼容代码 key 形式）
    2) 通过 asset_service 取中文名，命中 REPLICATION_COST（监控端原生 key 为中文名）
    3) canonical_price_code 还原后通过 ASSET_CODE_TO_NAME → REPLICATION_COST
    4) 兜底：按 AssetType 默认值（get_replication_cost）

    返回 {asset_code: annual_rate}。任何环节失败均回退到默认费率，确保非空。
    """
    if not thscodes:
        return {}
    try:
        from app.monitor.config import REPLICATION_COST, ASSET_CODE_TO_NAME
    except Exception:
        REPLICATION_COST = {}
        ASSET_CODE_TO_NAME = {}
    try:
        from app.monitor.mongo_asset_codes import canonical_price_code
    except Exception:
        def canonical_price_code(c: str) -> str:
            return c
    from app.models.asset import AssetType

    out: Dict[str, float] = {}
    for code in thscodes:
        rate: Optional[float] = None
        # 1) 代码直接命中（部分配置以 asset_code 为 key）
        if code in (REPLICATION_COST or {}):
            try:
                rate = float(REPLICATION_COST[code])
            except (TypeError, ValueError):
                rate = None
        info = None
        if rate is None and asset_service is not None:
            try:
                info = await asset_service.get_asset_by_code(code)
            except Exception:
                info = None
            # 2) 中文名命中（监控端 REPLICATION_COST 原生 key 为中文名）
            name = getattr(info, "name", None) if info else None
            if name and name in (REPLICATION_COST or {}):
                try:
                    rate = float(REPLICATION_COST[name])
                except (TypeError, ValueError):
                    rate = None
        # 3) canonical_price_code → ASSET_CODE_TO_NAME → REPLICATION_COST
        if rate is None:
            try:
                base = canonical_price_code(code)
            except Exception:
                base = code
            for c in (code, base):
                cn = (ASSET_CODE_TO_NAME or {}).get(c)
                if cn and cn in (REPLICATION_COST or {}):
                    try:
                        rate = float(REPLICATION_COST[cn])
                        break
                    except (TypeError, ValueError):
                        rate = None
        # 4) 兜底：按 AssetType 默认值
        if rate is None:
            try:
                raw = getattr(info, "asset_type", None) if info else None
                atype = raw if isinstance(raw, AssetType) else AssetType(str(raw)) if raw else AssetType.INDEX
            except (ValueError, TypeError):
                atype = AssetType.INDEX
            rc_override = getattr(info, "replication_cost_rate", None) if info else None
            try:
                rate = float(get_replication_cost(atype, rc_override))
            except Exception:
                rate = 0.005
        try:
            out[code] = float(rate) if rate is not None else 0.005
        except (TypeError, ValueError):
            out[code] = 0.005
    logger.info(
        "[主观回测][RC] 注入复制费率（年化） %s",
        {k: round(v, 6) for k, v in out.items()},
    )
    return out


# 极端浮点数上限（用于防止手续费、收益率等异常值导致显示/序列化问题）
_SANITIZE_FLOAT_ABS_MAX = 1e12

# 回测绩效指标合理范围（数据缺失/不一致时避免回撤、收益率、波动率、卡玛等极端值）
_PERF_TOTAL_RETURN_MIN = -1.0
_PERF_TOTAL_RETURN_MAX = 10.0
_PERF_ANNUAL_VOLATILITY_MAX = 5.0
_PERF_MAX_DRAWDOWN_MIN = -1.0
_PERF_MAX_DRAWDOWN_MAX = 0.0
_PERF_RATIO_ABS_MAX = 50.0
_PERF_COMMISSION_ABS_MAX = 1e9  # 单笔手续费绝对值上限


def _sanitize_performance_metrics(perf: Dict[str, Any]) -> Dict[str, Any]:
    """对回测绩效指标做合理范围限制与 nan/inf 清理，避免数据缺失或不一致时出现极端值。"""
    if not perf or not isinstance(perf, dict):
        return perf
    out = dict(perf)
    for key in ("total_return", "annual_return"):
        if key in out and out[key] is not None:
            v = _safe_float_for_json(out[key], 0.0)
            out[key] = max(_PERF_TOTAL_RETURN_MIN, min(_PERF_TOTAL_RETURN_MAX, v))
    for key in ("volatility", "annual_volatility"):
        if key in out and out[key] is not None:
            v = _safe_float_for_json(out[key], 0.0)
            out[key] = max(0.0, min(_PERF_ANNUAL_VOLATILITY_MAX, v))
    if "max_drawdown" in out and out["max_drawdown"] is not None:
        v = _safe_float_for_json(out["max_drawdown"], 0.0)
        out["max_drawdown"] = max(_PERF_MAX_DRAWDOWN_MIN, min(_PERF_MAX_DRAWDOWN_MAX, v))
    for key in ("sharpe_ratio", "calmar_ratio"):
        if key in out and out[key] is not None:
            v = _safe_float_for_json(out[key], 0.0)
            out[key] = max(-_PERF_RATIO_ABS_MAX, min(_PERF_RATIO_ABS_MAX, v))
    return out


def _safe_float_for_json(x: Any, default: float = 0.0) -> float:
    """将 inf/nan 转为有限值，避免 JSON 序列化报错。"""
    if x is None:
        return default
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return default
    except (TypeError, ValueError):
        return default
    return float(x)


def _cap_extreme_float(v: float, default: float = 0.0) -> float:
    """将 inf/nan/极端大数转为合理范围，避免显示异常。"""
    if not math.isfinite(v):
        return default
    if abs(v) > _SANITIZE_FLOAT_ABS_MAX:
        return (_SANITIZE_FLOAT_ABS_MAX if v > 0 else -_SANITIZE_FLOAT_ABS_MAX)
    return v


def _sanitize_dict_for_json(obj: Any, default_float: float = 0.0) -> Any:
    """递归将 dict/list 中的 inf/nan/极端浮点数转为有限值，避免 JSON 序列化及显示异常。支持 numpy 标量。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_dict_for_json(v, default_float) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_dict_for_json(v, default_float) for v in obj]
    # 处理 numpy 标量（np.float64 等，isinstance(x, float) 为 False）
    try:
        import numpy as np
        if isinstance(obj, (np.floating, np.integer)):
            v = float(obj)
            if math.isnan(v) or math.isinf(v):
                return default_float if isinstance(obj, np.floating) else 0
            out = v if isinstance(obj, np.floating) else int(obj)
            return _cap_extreme_float(out, default_float) if isinstance(obj, np.floating) else out
    except (ImportError, TypeError, ValueError):
        pass
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return default_float
        return _cap_extreme_float(obj, default_float)
    return obj


# ==================== 快照聚合（减少响应体积） ====================

def _aggregate_snapshots(snapshots: list, max_points: int = 500) -> dict:
    """对快照列表进行聚合处理，减少返回数据量。
    
    保留策略：
    - 总数 <= max_points 时不做采样，原样返回
    - 超过时：均匀采样 + 保留所有调仓日 + 保留首尾
    """
    total = len(snapshots)
    if total <= max_points:
        return {
            "snapshots": snapshots,
            "total_snapshots": total,
            "aggregated": False,
        }

    import numpy as np

    # 提取调仓日索引
    rebalance_indices = set()
    for i, s in enumerate(snapshots):
        is_reb = s.get("is_rebalance_day") if isinstance(s, dict) else getattr(s, "is_rebalance_day", False)
        if is_reb:
            rebalance_indices.add(i)

    # 均匀采样索引
    uniform_indices = set(np.linspace(0, total - 1, max_points, dtype=int).tolist())

    # 合并索引并排序
    all_indices = sorted(uniform_indices | rebalance_indices | {0, total - 1})

    # 如果合并后仍超过 max_points * 1.5，裁剪非调仓日
    if len(all_indices) > int(max_points * 1.5):
        all_indices = sorted(uniform_indices | rebalance_indices)[:int(max_points * 1.5)]
        all_indices = sorted(set(all_indices) | {0, total - 1})

    sampled = [snapshots[i] for i in all_indices]

    return {
        "snapshots": sampled,
        "total_snapshots": total,
        "aggregated": True,
        "sampled_points": len(sampled),
    }


def _apply_snapshot_aggregation(result_data: dict, max_points: int = 500) -> dict:
    """对回测结果 dict 中的 snapshots 字段应用聚合采样，就地修改并返回。
    
    向响应中注入 _snapshot_meta 字段，告知前端聚合状态：
    - total: 原始快照总数
    - aggregated: 是否做了采样
    - returned: 实际返回的快照数
    """
    if not isinstance(result_data, dict):
        return result_data
    snapshots = result_data.get("snapshots")
    if not snapshots or not isinstance(snapshots, list):
        return result_data
    agg = _aggregate_snapshots(snapshots, max_points=max_points)
    result_data["snapshots"] = agg["snapshots"]
    result_data["_snapshot_meta"] = {
        "total": agg["total_snapshots"],
        "aggregated": agg["aggregated"],
        "returned": len(agg["snapshots"]),
    }
    return result_data


# ==================== Pydantic模型定义 ====================

class ManualWeightAdjustmentItem(BaseModel):
    """单次交互式权重调整（权重可选，不设则到该日由用户选择）"""
    date: str = Field(..., description="调整日期，格式 YYYYMMDD")
    weights: Optional[Dict[str, float]] = Field(None, description="资产代码到权重的映射，可留空")
    auto_normalize: bool = Field(True, description="是否自动归一化权重")


class BacktestRequest(BaseModel):
    """回测请求"""
    name: str = Field(..., description="回测名称")
    strategy_type: str = Field(..., description="策略类型")
    strategy_params: Dict[str, Any] = Field(default_factory=dict, description="策略参数")
    thscodes: List[str] = Field(..., description="资产代码列表")
    start_date: str = Field(..., description="回测开始日期（格式：YYYY-MM-DD）")
    end_date: str = Field(..., description="回测结束日期（格式：YYYY-MM-DD）")
    initial_cash: float = Field(10_000_000.0, description="初始资金")
    rebalance_freq: str = Field("monthly", description="调仓频率（daily/weekly/monthly/month_end/quarterly/yearly，risk_budget_target_vol混合动量时自动用month_end）")
    commission_rate: float = Field(0.0003, description="手续费率")
    slippage: float = Field(0.0005, description="滑点率")
    lookback_days: int = Field(500, description="历史数据预加载天数")
    manual_weight_adjustments: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="交互式权重调整（仅 manual_allocation 策略）：[{date, weights, auto_normalize}, ...]"
    )
    export_hybrid_momentum_files: bool = Field(
        True,
        description="是否导出混合动量编制规则文件（仅 risk_budget_target_vol+混合动量）：资产选择结果.xlsx、权重计算结果.xlsx、回测结果_汇率版_v1.xlsx。默认 True 表示每次运行混合动量策略时自动生成"
    )
    export_output_dir: Optional[str] = Field(
        None,
        description="导出文件目录（export_hybrid_momentum_files=True 时生效，默认 ./backtest_exports）"
    )
    export_reference_weight_path: Optional[str] = Field(
        None,
        description="权重对比用对照文件路径（如 动量策略相关资料/对照_权重计算结果.xlsx），提供则生成 权重对比结果.xlsx"
    )

    @field_validator('start_date', 'end_date', mode='before')
    @classmethod
    def validate_date(cls, v: Any) -> str:
        """验证并规范化日期格式为 YYYYMMDD"""
        if not v:
            return v
        try:
            # 使用 pandas 灵活解析日期
            dt = pd.to_datetime(v)
            return dt.strftime('%Y%m%d')
        except Exception:
            return v  # 如果解析失败，保持原样，让后续逻辑处理


class SnapshotOut(BaseModel):
    """组合快照输出"""
    time: datetime = Field(..., description="时间")
    total_value: float = Field(..., description="组合总市值")
    cash: float = Field(..., description="现金")
    holdings_value: float = Field(..., description="持仓市值")
    weights: Dict[str, float] = Field(..., description="持仓权重")
    is_rebalance_day: bool = Field(False, description="是否为调仓日")
    rebalance_type: Optional[str] = Field(None, description="调仓类型：regular/vol_reset")
    rebalance_reason: Optional[str] = Field(None, description="调仓原因（周期性调仓/条件触发调仓等）")
    portfolio_volatility: Optional[float] = Field(None, description="当日组合波动率")
    drawdown: Optional[float] = Field(None, description="当日回撤")
    monitoring_metrics: Dict[str, Any] = Field(default_factory=dict, description="所有监控指标")


class BacktestStepRequest(BacktestRequest):
    """步进回测请求（主观策略预设调仓日交互式执行）"""
    step_phase: str = Field("start", description="start=运行到首个预设日前暂停; continue=用用户决策继续; run_to_date=从开始跑到 end_date 仅期初建仓")
    step_state: Optional[Dict[str, Any]] = Field(None, description="上一段返回的状态，continue 时必传")
    preset_date_decision: Optional[Dict[str, Any]] = Field(
        None,
        description="当前预设日的用户决策: { date, action: use_preset|custom|skip, weights?, auto_normalize? }"
    )
    accumulated_snapshots: Optional[List[Dict[str, Any]]] = Field(None, description="此前各段快照列表，continue 时传")
    accumulated_trades: Optional[List[Dict[str, Any]]] = Field(None, description="此前各段交易记录，continue 时传，用于最终结果合并")


class BacktestStepPausedOut(BaseModel):
    """步进回测暂停时的响应"""
    phase: str = Field("paused", description="paused")
    snapshots: List[SnapshotOut] = Field(..., description="本段快照（或合并后的历史快照）")
    state: Dict[str, Any] = Field(..., description="可传给下一步的 state")
    next_preset_date: str = Field(..., description="下一个预设调仓日 YYYYMMDD")
    remaining_preset_dates: List[str] = Field(..., description="后续预设日列表")
    current_weights: Dict[str, float] = Field(default_factory=dict, description="当前持仓权重")
    asset_names: Optional[Dict[str, str]] = Field(None, description="资产名称")
    # 当前持仓绩效指标（至暂停日），便于用户根据回测信息选择调仓方式
    current_metrics: Optional[Dict[str, Any]] = Field(
        None,
        description="累计收益率、年化波动率、最大回撤、夏普、卡玛、当前净值等"
    )
    max_weight_dict: Optional[Dict[str, float]] = Field(
        None,
        description="指数编制规则下每类资产权重上限，供前端输入限制与提示"
    )
    # 本段产生的交易记录；continue 时前端需传回 accumulated_trades（此前各段+本段），用于最终结果合并
    trades: Optional[List[Dict[str, Any]]] = Field(None, description="本段交易记录（或截至当前的累计交易，供前端下次 continue 传回）")


def _rebalance_label_for_trade(rebalance_type: Optional[str], rebalance_reason: Optional[str]) -> str:
    """根据调仓类型与原因返回交易明细展示用的调仓类型标签：初始化仓位 / 交互式调仓 / 预设调仓 / 周期性调仓 / 波动率重置"""
    r = (rebalance_reason or "").strip()
    t = (rebalance_type or "").strip()
    if "期初建仓" in r or (t == "manual_adjustment" and ("期初建仓" in r or r == "")):
        return "初始化仓位"
    if t == "manual_adjustment":
        if "交互式" in r or r == "交互式调仓":
            return "交互式调仓"
        return "预设调仓"
    if t == "vol_reset":
        return "波动率重置"
    if t == "regular" or "周期性" in r:
        return "周期性调仓"
    return "周期性调仓"


def _ensure_trades_rebalance_labels(result_data: Dict[str, Any]) -> None:
    """确保 result_data["trades"] 中每条交易都有 rebalance_label（用于单策略回测交易明细展示）。就地修改。"""
    if not isinstance(result_data, dict):
        return
    trades = result_data.get("trades")
    snapshots = result_data.get("snapshots") or []
    if not isinstance(trades, list):
        return
    rebalance_by_date = {}
    for s in snapshots:
        is_reb = s.get("is_rebalance_day") if isinstance(s, dict) else getattr(s, "is_rebalance_day", False)
        if is_reb:
            t = s.get("time") if isinstance(s, dict) else getattr(s, "time", None)
            if t is not None:
                try:
                    key = pd.Timestamp(t).strftime("%Y-%m-%d") if hasattr(pd.Timestamp(t), "strftime") else str(t)[:10]
                    rt = s.get("rebalance_type") if isinstance(s, dict) else getattr(s, "rebalance_type", None)
                    rr = s.get("rebalance_reason") if isinstance(s, dict) else getattr(s, "rebalance_reason", None)
                    rebalance_by_date[key] = (rt, rr)
                except Exception:
                    pass
    for t in trades:
        if isinstance(t, dict) and t.get("rebalance_label") is None:
            tdt = t.get("time")
            key = ""
            if tdt is not None:
                try:
                    key = pd.Timestamp(tdt).strftime("%Y-%m-%d") if hasattr(pd.Timestamp(tdt), "strftime") else str(tdt)[:10]
                except Exception:
                    key = str(tdt)[:10] if tdt else ""
            rt, rr = rebalance_by_date.get(key, (None, None))
            t["rebalance_label"] = _rebalance_label_for_trade(rt, rr)


class TradeOut(BaseModel):
    """交易记录输出"""
    time: datetime = Field(..., description="交易时间")
    thscode: str = Field(..., description="资产代码")
    side: str = Field(..., description="交易方向（buy/sell）")
    quantity: float = Field(..., description="交易数量")
    price: float = Field(..., description="交易价格")
    commission: float = Field(..., description="手续费")
    slippage_cost: float = Field(..., description="滑点成本")
    rebalance_label: Optional[str] = Field(None, description="调仓类型：初始化仓位/主观调仓/周期性调仓/波动率重置")


class BacktestResultOut(BaseModel):
    """回测结果输出"""
    snapshots: List[SnapshotOut] = Field(..., description="组合快照列表")
    trades: List[TradeOut] = Field(..., description="交易记录列表")
    total_return: float = Field(..., description="总收益率")
    annual_return: float = Field(..., description="年化收益率")
    volatility: float = Field(..., description="波动率")
    sharpe_ratio: float = Field(..., description="夏普比率")
    max_drawdown: float = Field(..., description="最大回撤")
    calmar_ratio: float = Field(..., description="卡玛比率")
    asset_names: Optional[Dict[str, str]] = Field(None, description="资产名称字典")
    selected_asset_count: Optional[int] = Field(None, description="动量选择器「选择资产数量」，与持仓权重资产类别数一致")


# ==================== 依赖注入 ====================

def get_market_service() -> MarketService:
    """获取行情服务实例"""
    return MarketService()


def get_asset_service() -> AssetService:
    """获取资产服务实例"""
    return AssetService()


def get_fx_service() -> FxService:
    """获取汇率服务实例"""
    return FxService()


def get_model_service() -> StrategyModelService:
    """获取模型服务实例"""
    return StrategyModelService()


def validate_object_id(id_str: str) -> str:
    """验证ObjectId格式"""
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=400,
            detail=f"无效的ID格式: {id_str}, 必须是24位十六进制字符串"
        )
    return id_str


# ==================== API路由 ====================

@router.post("/run", response_model=Response[BacktestResultOut], summary="运行回测")
async def run_backtest(
    request: BacktestRequest = Body(...),
    market_service: MarketService = Depends(get_market_service),
    asset_service: AssetService = Depends(get_asset_service),
    fx_service: FxService = Depends(get_fx_service),
):
    """
    运行回测（使用新的 BacktestEngine）
    
    流程：
    1. 根据策略类型和参数创建策略实例
    2. 从 MarketService 加载历史行情数据
    3. 创建 DataFeed、RiskManager、ExecutionEngine
    4. 运行 BacktestEngine
    5. 返回回测结果
    
    注意：
    - 日期格式为 YYYYMMDD（如 20230101）
    - 策略参数必须符合该策略的Schema定义
    """
    try:
        # 1. 创建回测配置
        config = BacktestConfig(
            name=request.name,
            thscodes=request.thscodes,
            start_date=request.start_date,
            end_date=request.end_date,
            rebalance_freq=request.rebalance_freq,
            initial_cash=request.initial_cash,
            commission_rate=request.commission_rate,
            slippage=request.slippage
        )
        # 交互式权重调整：转换为 {date_str: {weights?, auto_normalize}}，权重可选（不设则到该日由用户选择）
        if getattr(request, "manual_weight_adjustments", None):
            adj_dict = {}
            for item in request.manual_weight_adjustments:
                if isinstance(item, dict) and item.get("date"):
                    d = str(item["date"]).replace("-", "")[:8]
                    adj_dict[d] = {
                        "weights": dict(item["weights"]) if item.get("weights") is not None else {},
                        "auto_normalize": item.get("auto_normalize", False),
                    }
            config.manual_weight_adjustments = adj_dict if adj_dict else None

        # 量化策略启用指数净值模式（汇率、费率、多币种）
        strategy_type = getattr(request, "strategy_type", "") or ""
        config.use_index_nav = strategy_type not in ("manual_allocation", "manual_allocation_strategy")

        # 主观策略仅按预设日期调仓：至少需一个预设调仓日（权重可到该日再选）
        if strategy_type in ("manual_allocation", "manual_allocation_strategy"):
            config.rebalance_only_on_preset_dates = True
            if not config.manual_weight_adjustments or len(config.manual_weight_adjustments) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="主观配置策略需至少预设一个调仓日期（权重可留空，到该日再选择）。"
                )
            sp = getattr(request, "strategy_params", None) or {}
            max_leverage = float(sp.get("max_leverage", 4))
            if max_leverage < 1:
                max_leverage = 4
            # 期初建仓：使用策略默认权重（或本次回测覆盖的 manual_weights）在首日建仓
            mw = sp.get("manual_weights")
            if mw and isinstance(mw, dict) and len(mw) > 0:
                config.initial_weights = {k: float(v) for k, v in mw.items() if v is not None}
                total = sum(config.initial_weights.values())
                if total > max_leverage:
                    raise HTTPException(
                        status_code=400,
                        detail=f"初始权重总和 {total*100:.2f}% 超过最大杠杆 {max_leverage*100:.0f}%。请调整权重或策略参数「最大杠杆」。"
                    )
            # 预设调仓日权重：总仓位不得超过最大杠杆
            if config.manual_weight_adjustments:
                for d, adj in config.manual_weight_adjustments.items():
                    w = adj.get("weights") or {}
                    if w:
                        total = sum(float(v) for v in w.values() if v is not None)
                        if total > max_leverage:
                            raise HTTPException(
                                status_code=400,
                                detail=f"预设调仓日 {d} 的权重总和 {total*100:.2f}% 超过最大杠杆 {max_leverage*100:.0f}%。请调整权重或策略参数「最大杠杆」。"
                            )
                first_date = min(config.manual_weight_adjustments.keys())
                config.initial_weights_auto_normalize = config.manual_weight_adjustments[first_date].get("auto_normalize", False)

        # 2. 验证资产代码是否存在
        if not request.thscodes:
            raise HTTPException(
                status_code=400,
                detail="资产代码列表为空，请检查策略模型的资产配置"
            )
        
        # 验证资产是否存在
        missing_assets = []
        for code in request.thscodes:
            asset_info = await asset_service.get_asset_by_code(code)
            if not asset_info:
                missing_assets.append(code)
        
        if missing_assets:
            raise HTTPException(
                status_code=400,
                detail=f"以下资产代码不存在或未配置：{', '.join(missing_assets)}。请检查资产库中的资产配置。"
            )

        # 2.5 指数净值模式：注入汇率、交易费率、复制费率
        # risk_budget_target_vol 混合动量策略等量化策略均启用 use_index_nav，
        # 对 request.thscodes 中每类资产按 asset_currency_map 获取计价货币，
        # 非 CNH/CNY 资产（如标普500=USD、德国DAX=EUR、恒生科技=HKD）会应用汇率换算至人民币。
        if config.use_index_nav:
            from app.models.asset import AssetType
            # 若 fx_service 为 Depends 对象（被内部直接调用时未注入），则解析为实际实例
            _fx = fx_service if hasattr(fx_service, "get_fx_series_for_assets") else get_fx_service()
            asset_currency_map = {}
            transaction_costs = {}
            replication_costs = {}
            for code in request.thscodes:
                info = await asset_service.get_asset_by_code(code)
                name = info.name if info else None
                try:
                    raw = getattr(info, "asset_type", None) if info else None
                    atype = raw if isinstance(raw, AssetType) else AssetType(str(raw)) if raw else AssetType.INDEX
                except (ValueError, TypeError):
                    atype = AssetType.INDEX
                currency = get_currency_for_asset(code, name, info.currency if info else None)
                asset_currency_map[code] = currency
                tc_override = info.trading_cost_rate if info else None
                rc_override = info.replication_cost_rate if info else None
                transaction_costs[code] = get_trading_cost(atype, tc_override)
                replication_costs[code] = get_replication_cost(atype, rc_override)
            config.transaction_costs = transaction_costs
            config.replication_costs = replication_costs
            # 汇率序列（若有 fx_rates 数据）
            start_ymd = str(request.start_date).replace("-", "")[:8]
            end_ymd = str(request.end_date).replace("-", "")[:8]
            fx_series = await _fx.get_fx_series_for_assets(
                asset_currency_map, start_ymd, end_ymd
            )
            config.fx_rates = fx_series if fx_series else {}
        
        # 2.6 主观策略：注入与监控对齐的复制费率（key=asset_code）
        # 仅当 strategy_type 为 manual_allocation 时生效，不影响量化/动量等其他策略。
        # 监控引擎每日按 abs(positions_local) * (rc/365) * days_between 扣除复制费，
        # 此处使回测使用同一费率集，避免两端 NAV 出现系统性偏离。
        if strategy_type in ("manual_allocation", "manual_allocation_strategy"):
            manual_rc = await _build_manual_replication_costs(request.thscodes, asset_service)
            if manual_rc:
                config.replication_costs = manual_rc
                logger.info(
                    "[主观回测][RC] config.replication_costs 注入成功，资产数=%d",
                    len(manual_rc),
                )
        
        # 3. 创建数据源
        # reference_engine / min_history_days>=260 需至少 400 日历天预加载（确保 260 交易日 + 缓冲）
        effective_lookback = request.lookback_days
        sp = request.strategy_params or {}
        sel = sp.get("selection_info") or sp
        if (
            sel.get("use_reference_engine")
            or sel.get("selector_type") == "reference_engine"
            or int(sp.get("min_history_days", 0)) >= 260
        ):
            effective_lookback = max(effective_lookback, 400)
        data_feed = await DataFeed.from_market_service(
            market_service=market_service,
            config=config,
            lookback_days=effective_lookback
        )
        
        if data_feed.prices.empty:
            # 提供更详细的错误信息
            start_str = (request.start_date or "")[:8]
            end_str = (request.end_date or "")[:8]
            hint = ""
            try:
                from datetime import datetime as dt
                today = dt.now().strftime("%Y%m%d")
                if start_str >= today or end_str >= today:
                    hint = "提示：当前日期范围包含今日或未来日期，历史行情可能尚未产生或尚未入库。请使用已过去的日期区间。\n"
            except Exception:
                pass
            error_msg = (
                f"无法获取历史行情数据。\n"
                f"资产代码：{', '.join(request.thscodes)}\n"
                f"日期范围：{request.start_date} 至 {request.end_date}\n"
                f"{hint}"
                f"可能原因：\n"
                f"1. 资产代码格式不正确（如多写、少写字符）\n"
                f"2. 指定日期范围内没有行情数据\n"
                f"3. 资产尚未导入行情数据\n"
                f"请检查资产库中的资产配置和行情数据导入情况。"
            )
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )
        
        # 预设调仓日校验：须在回测区间内，且为有数据的交易日
        if config.manual_weight_adjustments:
            start_ymd = str(request.start_date).replace("-", "")[:8]
            end_ymd = str(request.end_date).replace("-", "")[:8]
            preset_keys = list(config.manual_weight_adjustments.keys())
            out_of_range = [d for d in preset_keys if d < start_ymd or d > end_ymd]
            if out_of_range:
                raise HTTPException(
                    status_code=400,
                    detail=f"调仓日不可超出回测时间区间。以下日期超出区间 [{start_ymd}, {end_ymd}]：{', '.join(sorted(out_of_range))}。请重新设置调仓日。"
                )
            trading_days = set(pd.Series(data_feed.prices.index).dt.strftime("%Y%m%d").astype(str).tolist())
            invalid_preset = [d for d in preset_keys if d not in trading_days]
            if invalid_preset:
                raise HTTPException(
                    status_code=400,
                    detail=f"以下调仓日在回测区间内无行情数据或为非交易日，请重新设置调仓日：{', '.join(sorted(invalid_preset))}"
                )
        
        # 检查是否有部分资产没有数据
        available_assets = list(data_feed.prices.columns)
        missing_data_assets = [code for code in request.thscodes if code not in available_assets]
        if missing_data_assets:
            import warnings
            warnings.warn(
                f"以下资产在指定日期范围内没有数据：{', '.join(missing_data_assets)}。"
                f"将使用有数据的资产进行回测。"
            )

        # 3.5 动量混合策略独立回测：仅 risk_budget_target_vol + 混合动量 使用专用全链路引擎（step1/step2/step3）
        # 不应用于其他任何策略，其他策略使用通用 BacktestEngine
        # 编制规则：执行日=月末后第2个交易日，与 BacktestEngine 的 month_end（月末当日）不同
        # 优先使用原先文档路径（hybrid_momentum_engine + step1/step2/step3），失败时回退到 risk_budget_special
        sp = request.strategy_params or {}
        use_standalone_hybrid = (
            request.strategy_type == "risk_budget_target_vol"
            and (
                sp.get("enable_momentum_selection")
                or sp.get("asset_selection_count") is not None
                or sp.get("selector_type") == "reference_engine"
            )
            and sp.get("use_reference_engine", True)
        )
        if use_standalone_hybrid:
            import logging
            _log_hm = logging.getLogger(__name__)

            def _build_hm_config():
                """构建混合动量配置（两套引擎共用）"""
                from app.backtesting.hybrid_momentum_engine import HybridMomentumConfig
                base_date = pd.Timestamp(str(request.start_date)[:10])
                # 资产选择/权重计算从 selection_start_date（默认 2014-01-31）起，用于初始化仓位
                selection_start = pd.Timestamp(sp.get("selection_start_date", "2014-01-31")[:10])
                return HybridMomentumConfig(
                    base_date=base_date,
                    selection_start_date=selection_start,
                    base_value=config.index_nav_initial,
                    target_vol=float(request.strategy_params.get("target_vol", 0.05)),
                    vol_trigger_threshold=float(request.strategy_params.get("vol_reset_threshold", 0.06)),
                    max_leverage=float(request.strategy_params.get("max_total_leverage", 4.0)),
                    min_history_days=int(request.strategy_params.get("min_history_days", 260)),
                    top_momentum=int(request.strategy_params.get("n_momentum", 7)),
                    weight_caps=request.strategy_params.get("max_weight_dict") or {},
                    transaction_costs=config.transaction_costs or {},
                    replication_costs=config.replication_costs or {},
                    fx_rates=config.fx_rates or {},
                    enable_vol_control=bool(request.strategy_params.get("enable_vol_reset", False)),
                    enable_costs=config.use_index_nav,
                    enable_fx=bool(config.fx_rates),
                    fx_pnl_exclude_fx_yesterday=bool(request.strategy_params.get("fx_pnl_exclude_fx_yesterday", True)),
                    risk_budget_both=float(request.strategy_params["risk_budget_both"]) if "risk_budget_both" in request.strategy_params else None,
                    risk_budget_single=float(request.strategy_params["risk_budget_single"]) if "risk_budget_single" in request.strategy_params else None,
                )

            hm_config = _build_hm_config()
            hm_result = None
            _used_fallback = False

            # 优先：原先文档路径（hybrid_momentum_engine + step1/step2/step3）
            try:
                from app.backtesting.hybrid_momentum_engine import run_hybrid_momentum_backtest
                hm_result = run_hybrid_momentum_backtest(
                    prices=data_feed.prices,
                    config=hm_config,
                )
                _log_hm.info("[混合动量] 使用原先文档路径 (hybrid_momentum_engine + step1/step2/step3)")
            except Exception as e:
                _log_hm.warning("[混合动量] 原先文档路径失败，回退到 risk_budget_special: %s", e)
                _used_fallback = True

            # 回退：risk_budget_special
            if hm_result is None:
                try:
                    from app.risk_budget_special.backtest_api import (
                        run_hybrid_momentum_backtest as run_hybrid_fallback,
                        HybridMomentumConfig as FallbackConfig,
                    )
                    fallback_config = FallbackConfig(
                        base_date=pd.Timestamp(str(request.start_date)[:10]),
                        base_value=config.index_nav_initial,
                        target_vol=float(request.strategy_params.get("target_vol", 0.05)),
                        vol_trigger_threshold=float(request.strategy_params.get("vol_reset_threshold", 0.06)),
                        max_leverage=float(request.strategy_params.get("max_total_leverage", 4.0)),
                        min_history_days=int(request.strategy_params.get("min_history_days", 260)),
                        top_momentum=int(request.strategy_params.get("n_momentum", 7)),
                        weight_caps=request.strategy_params.get("max_weight_dict") or {},
                        transaction_costs=config.transaction_costs or {},
                        replication_costs=config.replication_costs or {},
                        fx_rates=config.fx_rates or {},
                        enable_vol_control=bool(request.strategy_params.get("enable_vol_reset", False)),
                        enable_costs=config.use_index_nav,
                        enable_fx=bool(config.fx_rates),
                        fx_pnl_exclude_fx_yesterday=bool(request.strategy_params.get("fx_pnl_exclude_fx_yesterday", True)),
                    )
                    hm_result = run_hybrid_fallback(
                        prices=data_feed.prices,
                        config=fallback_config,
                    )
                    _log_hm.info("[混合动量] 已回退到 risk_budget_special 路径")
                except Exception as e2:
                    _log_hm.exception("[混合动量] 原先文档路径与 risk_budget_special 回退均失败")
                    raise HTTPException(
                        status_code=500,
                        detail=f"混合动量回测失败：原先文档路径与回退路径均不可用。\n原先路径错误: {e}\n回退路径错误: {e2}"
                    ) from e2

            if hm_result is not None:
                # 构建资产名称
                asset_names_hm = {}
                for code in request.thscodes:
                    info = await asset_service.get_asset_by_code(code)
                    asset_names_hm[code] = (info.name if info else None) or ZY_DOCUMENT_CODE_TO_NAME.get(code, code)
                # 计算回撤序列
                total_values_hm = pd.Series([s.total_value for s in hm_result["snapshots"]])
                drawdown_series_hm = calculate_drawdown_series(total_values_hm) if not total_values_hm.empty else pd.Series()

                def _weights_for_resp(wd):
                    if not wd:
                        return wd
                    return {k: float(v) for k, v in wd.items() if v is not None}

                # 波动率重置执行日集合（YYYY-MM-DD），用于兜底：该日调仓一律标为波动率重置，避免误标为周期性调仓
                vol_reset_exec_dates = set()
                for e in hm_result.get("vol_reset_events") or []:
                    d = e.get("执行日期") or e.get("execute_date")
                    if d is not None:
                        vol_reset_exec_dates.add(pd.Timestamp(d).strftime("%Y-%m-%d"))
                snapshots_hm = [
                    SnapshotOut(
                        time=s.time,
                        total_value=s.total_value,
                        cash=s.cash,
                        holdings_value=s.holdings_value,
                        weights=_weights_for_resp(s.weights),
                        is_rebalance_day=s.is_rebalance_day,
                        rebalance_type=("vol_reset" if (pd.Timestamp(s.time).strftime("%Y-%m-%d") in vol_reset_exec_dates) else getattr(s, "rebalance_type", None)),
                        rebalance_reason=("波动率触发重置" if (pd.Timestamp(s.time).strftime("%Y-%m-%d") in vol_reset_exec_dates) else getattr(s, "rebalance_reason", None)),
                        portfolio_volatility=getattr(s, "portfolio_volatility", None),
                        drawdown=float(drawdown_series_hm.iloc[i]) if i < len(drawdown_series_hm) else 0.0,
                        monitoring_metrics=getattr(s, "monitoring_metrics", {}),
                    )
                    for i, s in enumerate(hm_result["snapshots"])
                ]
                rebalance_by_date_hm = {}
                for s in hm_result["snapshots"]:
                    if getattr(s, "is_rebalance_day", False):
                        t = getattr(s, "time", None)
                        if t is not None:
                            key = pd.Timestamp(t).strftime("%Y-%m-%d")
                            rt = "vol_reset" if key in vol_reset_exec_dates else getattr(s, "rebalance_type", None)
                            rr = "波动率触发重置" if key in vol_reset_exec_dates else getattr(s, "rebalance_reason", None)
                            rebalance_by_date_hm[key] = (rt, rr)
                trades_hm = []
                for t in hm_result["trades"]:
                    tdt = getattr(t, "time", None)
                    key = pd.Timestamp(tdt).strftime("%Y-%m-%d") if tdt is not None and hasattr(pd.Timestamp(tdt), "strftime") else (str(tdt)[:10] if tdt else "")
                    rt, rr = rebalance_by_date_hm.get(key, (None, None))
                    trades_hm.append(
                        TradeOut(
                            time=t.time,
                            thscode=t.thscode,
                            side=t.side,
                            quantity=t.quantity,
                            price=t.price,
                            commission=t.commission,
                            slippage_cost=t.slippage_cost,
                            rebalance_label=_rebalance_label_for_trade(rt, rr),
                        )
                    )
                perf = _sanitize_performance_metrics(hm_result["performance"] or {})
                backtest_result_hm = BacktestResultOut(
                    snapshots=snapshots_hm,
                    trades=trades_hm,
                    total_return=perf.get("total_return", 0),
                    annual_return=perf.get("annual_return", 0),
                    volatility=perf.get("volatility", 0),
                    sharpe_ratio=perf.get("sharpe_ratio", 0),
                    max_drawdown=perf.get("max_drawdown", 0),
                    calmar_ratio=perf.get("calmar_ratio", 0),
                    asset_names=asset_names_hm,
                    selected_asset_count=8,  # 7+1
                )
                _ensure_trades_rebalance_labels({"snapshots": snapshots_hm, "trades": trades_hm})
                # 混合动量独立引擎：打印返回前端的调仓资产与权重
                _log_hm.info("[混合动量-返回前端] snapshots=%d trades=%d", len(snapshots_hm), len(trades_hm))
                for s in snapshots_hm:
                    if getattr(s, "is_rebalance_day", False):
                        dt = getattr(s, "time", None)
                        dt_str = pd.Timestamp(dt).strftime("%Y-%m-%d") if dt is not None else ""
                        w = getattr(s, "weights", None) or {}
                        nonzero = [(c, v) for c, v in w.items() if v is not None and float(v) > 1e-9]
                        names = asset_names_hm or {}
                        lines = [f"[混合动量-返回前端] 调仓日 {dt_str} 资产与权重:"]
                        for code, val in sorted(nonzero, key=lambda x: -x[1]):
                            name = names.get(code, code)
                            lines.append(f"  ・ {code} ({name}): {(float(val)*100):.2f}%")
                        if not nonzero:
                            lines.append("  （无权重>0的资产）")
                        _log_hm.info("\n".join(lines))
                # 混合动量导出：使用 hybrid_momentum_export（含完整权重详情、错误处理、文件占用时备用路径）
                export_paths_result = None
                if getattr(request, "export_hybrid_momentum_files", True):
                    import os
                    try:
                        from app.backtesting.hybrid_momentum_export import export_all, _resolve_reference_weight_path
                        out_dir = getattr(request, "export_output_dir", None) or "./backtest_exports"
                        out_dir = os.path.abspath(os.path.expanduser(str(out_dir)))
                        ref_path = getattr(request, "export_reference_weight_path", None) or _resolve_reference_weight_path()
                        perf_export = {
                            "start_date": str(request.start_date)[:10],
                            "end_date": str(request.end_date)[:10],
                            "initial_nav": snapshots_hm[0].total_value if snapshots_hm else 0,
                            "final_nav": snapshots_hm[-1].total_value if snapshots_hm else 0,
                            "total_return": perf.get("total_return"),
                            "annual_return": perf.get("annual_return"),
                            "volatility": perf.get("volatility"),
                            "max_drawdown": perf.get("max_drawdown"),
                            "sharpe_ratio": perf.get("sharpe_ratio"),
                        }
                        export_paths_result = export_all(
                            output_dir=out_dir,
                            selection_records=hm_result["selection_records"],
                            weight_records=hm_result["weight_records"],
                            snapshots=hm_result["snapshots"],
                            vol_reset_events=hm_result["vol_reset_events"],
                            performance=perf_export,
                            all_assets=list(data_feed.prices.columns),
                            asset_names=asset_names_hm,
                            reference_weight_path=ref_path,
                            trade_dates_set=hm_result.get("trade_dates_set"),
                        )
                        _log_hm.info("[混合动量导出] 已保存 权重计算结果.xlsx 等 -> %s", out_dir)
                    except Exception as ex:
                        _log_hm.exception("[混合动量导出] 失败: %s", ex)
                # 返回结果，附带导出路径（对整包做 nan/inf/极端值清理，避免前端显示异常）
                result_data = backtest_result_hm.model_dump() if hasattr(backtest_result_hm, "model_dump") else backtest_result_hm
                if export_paths_result:
                    _out_dir = getattr(request, "export_output_dir", None) or "./backtest_exports"
                    result_data["export_paths"] = {"output_dir": os.path.abspath(os.path.expanduser(str(_out_dir))), "files": list(export_paths_result.values())}
                return Response(data=_sanitize_dict_for_json(result_data))

        # 4. 创建策略实例（从数据库加载模板）
        strategy_service = await create_strategy_service_from_database(
            market_service=market_service
        )
        
        try:
            strategy_cls = strategy_service.get_strategy_class(request.strategy_type)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"策略类型不存在: {request.strategy_type}"
            )
        
        # 实例化策略模型
        try:
            strategy_impl = strategy_cls()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"策略实例化失败: {str(e)}\n"
                    f"策略类型: {request.strategy_type}\n"
                    f"请检查策略类的实现是否正确。"
                )
            )
        
        # 验证策略是否有 allocate 方法
        if not hasattr(strategy_impl, 'allocate'):
            raise HTTPException(
                status_code=500,
                detail=(
                    f"策略类 {strategy_cls.__name__} 没有实现 allocate 方法。\n"
                    f"策略必须实现 allocate(prices: DataFrame, **params) -> Series 接口。"
                )
            )
        
        # 检查是否启用资产选择（动量选择器参数「选择资产数量」与回测使用资产数一致）
        enable_selection = (
            request.strategy_params.get("enable_momentum_selection", False)
            or request.strategy_params.get("asset_selection_count") is not None
        )
        selection_info = {}
        
        selected_asset_count: Optional[int] = None
        if enable_selection:
            raw_selector_type = request.strategy_params.get("selector_type", "momentum")
            n_momentum = int(request.strategy_params.get("n_momentum", 7))
            n_reversal = int(request.strategy_params.get("n_reversal", 1))
            # risk_budget_target_vol 混合动量：以 step1/step2 为核心计算引擎（与对照文件完全一致）
            use_reference_engine = request.strategy_params.get("use_reference_engine", True)
            if request.strategy_type == "risk_budget_target_vol" and use_reference_engine:
                selector_type = "reference_engine"
                n_assets = n_momentum + n_reversal  # 7+1
                selected_asset_count = n_assets
                selection_params = {
                    "min_history_days": request.strategy_params.get("min_history_days", 260),
                    "n_momentum": n_momentum,
                    "n_reversal": n_reversal,
                }
            # 混合动量：hybrid / momentum_reversal / reversal → momentum_reversal（7+1，与指数编制规则一致）
            elif raw_selector_type in ("reversal", "momentum_reversal", "hybrid"):
                selector_type = "momentum_reversal"
                n_assets = n_momentum + n_reversal  # 7+1，选择器产出 7～8 个资产
                selected_asset_count = n_assets
                selection_params = {
                    "min_history_days": request.strategy_params.get("min_history_days", 260),
                    "momentum_windows": request.strategy_params.get("momentum_windows", "20,60,120,250"),
                    "macd_windows": request.strategy_params.get("macd_windows", "40,80,120,160"),
                    "reversal_windows": request.strategy_params.get("reversal_windows", "10,22"),
                    "n_momentum": n_momentum,
                    "n_reversal": n_reversal,
                }
                # risk_budget_target_vol 混合动量（momentum_reversal）：动量平局按平均排名（≤7 都入选，>7 都不入选）；反转平局都入选
                if request.strategy_type == "risk_budget_target_vol":
                    selection_params["use_price_skew"] = True
                    selection_params["min_history_reversal"] = 22
            else:
                selector_type = raw_selector_type
                _raw = request.strategy_params.get("asset_selection_count")
                n_assets = int(_raw) if _raw is not None else len(request.thscodes)
                selected_asset_count = n_assets
                selection_params = {
                    "min_history_days": request.strategy_params.get("min_history_days", 260),
                    "momentum_windows": request.strategy_params.get("momentum_windows", "20,60,120,250"),
                    "tie_break_window": request.strategy_params.get("tie_break_window", 22),
                }
            selection_info = {
                "selector_type": selector_type,
                "n_assets": n_assets,
                "selection_params": selection_params,
                "use_reference_engine": selector_type == "reference_engine",
            }
            # 混合动量导出：注入收集器（仅 risk_budget_target_vol + 导出开关）
            export_files = getattr(request, "export_hybrid_momentum_files", False)
            if export_files and request.strategy_type == "risk_budget_target_vol":
                selection_info["_selection_collector"] = []
                selection_info["_weight_collector"] = []
            n_for_alloc = request.strategy_params.get("n_assets_for_allocation")
            if n_for_alloc is not None and selector_type not in ("momentum_reversal", "reference_engine"):
                try:
                    selection_info["n_assets_for_allocation"] = int(n_for_alloc)
                except (TypeError, ValueError):
                    pass
        
        # 单资产最大权重：仅动量/量化策略按浙银理财编制规则限制；主观策略不限制
        doc_max_by_code = {}
        if not _is_manual_strategy(request.strategy_type):
            for code in request.thscodes:
                info = await asset_service.get_asset_by_code(code)
                name = info.name if info else code
                max_w = (
                    ZY_DOCUMENT_MAX_WEIGHT_BY_CODE.get(code)
                    or ZY_DOCUMENT_MAX_WEIGHT_BY_ASSET_NAME.get(name)
                    or ZY_DOCUMENT_MAX_WEIGHT_ALIASES.get(name)
                    or ZY_DOCUMENT_DEFAULT_MAX_WEIGHT
                )
                doc_max_by_code[code] = max_w
            request.strategy_params["max_weight_dict"] = dict(doc_max_by_code)
        else:
            request.strategy_params["max_weight_dict"] = {}

        # risk_budget_target_vol 混合动量：按编制规则使用月末最后一个交易日（与 step1/step2/trade_dates 一致）
        if request.strategy_type == "risk_budget_target_vol" and enable_selection:
            config.rebalance_freq = "month_end"

        # 使用 StrategiesWrapper 包装基础策略
        try:
            base_strategy = StrategiesWrapper(
                strategy_impl=strategy_impl,
                params=request.strategy_params
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"策略包装失败: {str(e)}\n"
                    f"策略类型: {request.strategy_type}\n"
                    f"策略参数: {request.strategy_params}\n"
                    f"请检查策略参数配置是否正确。"
                )
            )
        
        # 如果启用资产选择，使用 StrategyAdapterWithSelection
        if enable_selection:
            from app.backtesting.strategy_api import StrategyAdapterWithSelection
            strategy = StrategyAdapterWithSelection(
                base_strategy=base_strategy,
                thscodes=request.thscodes,
                enable_selection=True,
                selection_info=selection_info
            )
        else:
            strategy = base_strategy
        
        # 5. 创建风控和执行引擎（支持最大杠杆>1 时权重和大于1，不强制归一化为和1）
        max_total_leverage = request.strategy_params.get("max_total_leverage") or request.strategy_params.get("max_leverage")
        if max_total_leverage is not None:
            try:
                max_total_leverage = float(max_total_leverage)
            except (TypeError, ValueError):
                max_total_leverage = None
        max_weight_dict = request.strategy_params.get("max_weight_dict")
        if not isinstance(max_weight_dict, dict):
            max_weight_dict = None
        try:
            risk_config = RiskConfig(
                max_total_leverage=max_total_leverage,
                max_weight_dict=max_weight_dict,
            )
        except TypeError:
            # 兼容移植环境：若当前加载的 RiskConfig 无 max_total_leverage 参数（旧版或缓存），则使用无参构造
            risk_config = RiskConfig()
        risk_manager = RiskManager(config=risk_config)
        execution_engine = ExecutionEngine(config=config)
        
        # 混合动量导出：注入波动率重置收集器
        export_files = getattr(request, "export_hybrid_momentum_files", False)
        if export_files and request.strategy_type == "risk_budget_target_vol" and enable_selection:
            config.vol_reset_events_collector = []

        # 6. 创建并运行回测引擎
        engine = BacktestEngine(
            config=config,
            data_feed=data_feed,
            strategy=strategy,
            risk_manager=risk_manager,
            execution_engine=execution_engine
        )
        
        result = engine.run()
        
        # 7. 获取资产名称（资产库未配置时用编制规则回退，确保国债等12类资产均有标注）
        asset_names = {}
        for code in request.thscodes:
            asset_info = await asset_service.get_asset_by_code(code)
            if asset_info and asset_info.name:
                asset_names[code] = asset_info.name
            else:
                asset_names[code] = ZY_DOCUMENT_CODE_TO_NAME.get(code, code)
        
        # 8. 构建响应数据
        # 计算回撤序列
        total_values_series = pd.Series([s.total_value for s in result.snapshots])
        drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()
        
        # 返回权重：保留 0（未选资产），仅剔除 None，以便图注/图表展示全部候选资产（含 0 权重）
        def _weights_for_response(weights_dict):
            if not weights_dict:
                return weights_dict
            return {k: float(v) for k, v in weights_dict.items() if v is not None}
        
        snapshots_out = [
            SnapshotOut(
                time=s.time,
                total_value=s.total_value,
                cash=s.cash,
                holdings_value=s.holdings_value,
                weights=_weights_for_response(s.weights),
                is_rebalance_day=s.is_rebalance_day,
                rebalance_type=getattr(s, "rebalance_type", None),
                rebalance_reason=getattr(s, "rebalance_reason", None),
                portfolio_volatility=getattr(s, "portfolio_volatility", None),
                drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0,
                monitoring_metrics=getattr(s, "monitoring_metrics", {})
            )
            for i, s in enumerate(result.snapshots)
        ]
        
        rebalance_by_date = {}
        for s in result.snapshots:
            if getattr(s, "is_rebalance_day", False):
                dt = getattr(s, "time", None)
                if dt is not None:
                    key = pd.Timestamp(dt).strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                    rebalance_by_date[key] = (getattr(s, "rebalance_type", None), getattr(s, "rebalance_reason", None))
        trades_out = []
        for t in result.trades:
            tdt = getattr(t, "time", None)
            key = pd.Timestamp(tdt).strftime("%Y-%m-%d") if tdt is not None and hasattr(pd.Timestamp(tdt), "strftime") else (str(tdt)[:10] if tdt else "")
            rt, rr = rebalance_by_date.get(key, (None, None))
            trades_out.append(
                TradeOut(
                    time=t.time,
                    thscode=t.thscode,
                    side=t.side,
                    quantity=t.quantity,
                    price=t.price,
                    commission=t.commission,
                    slippage_cost=t.slippage_cost,
                    rebalance_label=_rebalance_label_for_trade(rt, rr)
                )
            )
        
        # 计算绩效指标
        from app.backtesting.analytics import PerformanceAnalyzer
        
        analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
        performance = analyzer.from_results(result.snapshots, result.trades)
        
        backtest_result = BacktestResultOut(
            snapshots=snapshots_out,
            trades=trades_out,
            total_return=performance.total_return,
            annual_return=performance.annual_return,
            volatility=performance.annual_volatility,
            sharpe_ratio=performance.sharpe_ratio,
            max_drawdown=performance.max_drawdown,
            calmar_ratio=performance.calmar_ratio,
            asset_names=asset_names,
            selected_asset_count=selected_asset_count
        )
        
        _snap = backtest_result.snapshots if hasattr(backtest_result, "snapshots") else []
        print(f"[回测] 返回回测完成数据 snapshots={len(_snap)} trades={len(getattr(backtest_result, 'trades', None) or [])}")
        # 动量资产选择模式下，打印返回前端的调仓资产和权重
        if request.strategy_params.get("enable_momentum_selection"):
            import logging
            _log = logging.getLogger(__name__)
            for s in _snap:
                is_reb = getattr(s, "is_rebalance_day", False)
                if is_reb:
                    dt = getattr(s, "time", None)
                    dt_str = pd.Timestamp(dt).strftime("%Y-%m-%d") if dt is not None else ""
                    w = getattr(s, "weights", None) or {}
                    nonzero = [(c, v) for c, v in w.items() if v is not None and float(v) > 1e-9]
                    names = asset_names or {}
                    lines = [f"[动量选择-返回前端] 调仓日 {dt_str} 资产与权重:"]
                    for code, val in sorted(nonzero, key=lambda x: -x[1]):
                        name = names.get(code, code)
                        lines.append(f"  ・ {code} ({name}): {(float(val)*100):.2f}%")
                    if not nonzero:
                        lines.append("  （无权重>0的资产）")
                    _log.info("\n".join(lines))
        # 混合动量导出：生成编制规则文件
        export_paths_result = None
        if export_files and request.strategy_type == "risk_budget_target_vol" and enable_selection:
            sel_collector = selection_info.get("_selection_collector")
            weight_collector = selection_info.get("_weight_collector")
            vol_collector = getattr(config, "vol_reset_events_collector", None)
            if sel_collector is not None and weight_collector is not None:
                out_dir = getattr(request, "export_output_dir", None) or "./backtest_exports"
                import os
                out_dir = os.path.abspath(os.path.expanduser(str(out_dir)))
                snap_list = backtest_result.snapshots if hasattr(backtest_result, "snapshots") else result.snapshots
                perf = {
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                    "initial_nav": snap_list[0].total_value if snap_list else 0,
                    "final_nav": snap_list[-1].total_value if snap_list else 0,
                    "total_return": performance.total_return,
                    "annual_return": performance.annual_return,
                    "volatility": getattr(performance, "annual_volatility", None) or getattr(performance, "volatility", 0),
                    "max_drawdown": performance.max_drawdown,
                    "sharpe_ratio": performance.sharpe_ratio,
                }
                try:
                    from app.risk_budget_special.backtest_api import export_all, _resolve_reference_weight_path
                    ref_path = getattr(request, "export_reference_weight_path", None) or _resolve_reference_weight_path()
                    export_paths_result = export_all(
                        output_dir=out_dir,
                        selection_records=sel_collector,
                        weight_records=weight_collector,
                        snapshots=result.snapshots,
                        vol_reset_events=vol_collector or [],
                        performance=perf,
                        all_assets=request.thscodes,
                        asset_names=asset_names,
                        reference_weight_path=ref_path,
                    )
                    _log = __import__("logging", fromlist=["getLogger"]).getLogger(__name__)
                    _log.info("[混合动量导出] 已生成: %s", export_paths_result)
                except Exception as ex:
                    traceback.print_exc()
                    _log = __import__("logging", fromlist=["getLogger"]).getLogger(__name__)
                    _log.warning("[混合动量导出] 失败: %s", ex)

        _data = backtest_result.model_dump() if hasattr(backtest_result, "model_dump") else backtest_result
        if export_paths_result:
            _data["export_paths"] = {"output_dir": os.path.dirname(list(export_paths_result.values())[0]), "files": list(export_paths_result.values())}
        _apply_snapshot_aggregation(_data)
        return Response.success(data=_sanitize_dict_for_json(_data), message="回测完成")
        
    except ValueError as e:
        traceback.print_exc()
        # ValueError 通常是参数验证错误，返回400状态码
        # 如果错误信息包含换行符，保持格式以便前端正确显示
        error_detail = str(e)
        raise HTTPException(status_code=400, detail=error_detail)
    except RuntimeError as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"回测执行失败: {str(e)}")


def _snapshots_to_out(snapshots: list, _weights_for_response) -> list:
    """将引擎快照转为 SnapshotOut 并计算回撤"""
    if not snapshots:
        return []
    total_values_series = pd.Series([s.total_value for s in snapshots])
    drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()
    return [
        SnapshotOut(
            time=s.time,
            total_value=s.total_value,
            cash=s.cash,
            holdings_value=s.holdings_value,
            weights=_weights_for_response(s.weights),
            is_rebalance_day=s.is_rebalance_day,
            rebalance_type=getattr(s, "rebalance_type", None),
            rebalance_reason=getattr(s, "rebalance_reason", None),
            portfolio_volatility=getattr(s, "portfolio_volatility", None),
            drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0,
            monitoring_metrics=getattr(s, "monitoring_metrics", {}),
        )
        for i, s in enumerate(snapshots)
    ]


def _trade_to_dict(t: Any) -> Dict[str, Any]:
    """将引擎 Trade 转为可序列化 dict，用于步进回测累计交易列表."""
    return {
        "time": getattr(t, "time", None),
        "thscode": getattr(t, "thscode", ""),
        "side": getattr(t, "side", ""),
        "quantity": float(getattr(t, "quantity", 0) or 0),
        "price": float(getattr(t, "price", 0) or 0),
        "commission": float(getattr(t, "commission", 0) or 0),
        "slippage_cost": float(getattr(t, "slippage_cost", 0) or 0),
    }


def _compute_paused_metrics(snapshots: list, trades: list = None) -> Dict[str, Any]:
    """根据至暂停日的快照计算当前绩效指标，供交互对话框展示。失败时返回占位 dict，保证前端始终收到对象."""
    placeholder = {
        "total_return": None,
        "annual_return": None,
        "volatility": None,
        "max_drawdown": None,
        "sharpe_ratio": None,
        "calmar_ratio": None,
        "current_nav": None,
        "initial_nav": None,
    }
    if not snapshots:
        return placeholder
    from app.backtesting.analytics import PerformanceAnalyzer
    from app.backtesting.types import PortfolioSnapshot
    try:
        if hasattr(snapshots[0], "total_value") and hasattr(snapshots[0], "is_rebalance_day"):
            snap_list = snapshots
        else:
            snap_list = [
                PortfolioSnapshot(
                    time=pd.Timestamp(x["time"]) if not isinstance(x.get("time"), pd.Timestamp) else x["time"],
                    total_value=float(x.get("total_value", 0)),
                    cash=float(x.get("cash", 0)),
                    holdings_value=float(x.get("holdings_value", 0)),
                    weights=x.get("weights") or {},
                    is_rebalance_day=bool(x.get("is_rebalance_day", False)),
                    rebalance_type=x.get("rebalance_type"),
                    rebalance_reason=x.get("rebalance_reason"),
                    portfolio_volatility=x.get("portfolio_volatility"),
                    monitoring_metrics=x.get("monitoring_metrics", {}),
                )
                for x in snapshots
            ]
        analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
        perf = analyzer.from_results(snap_list, trades or [])
        return {
            "total_return": perf.total_return,
            "annual_return": perf.annual_return,
            "volatility": perf.annual_volatility,
            "max_drawdown": perf.max_drawdown,
            "sharpe_ratio": perf.sharpe_ratio,
            "calmar_ratio": perf.calmar_ratio,
            "current_nav": float(snap_list[-1].total_value) if snap_list else 0,
            "initial_nav": float(snap_list[0].total_value) if snap_list else 0,
        }
    except Exception as e:
        traceback.print_exc()
        return placeholder


@router.post("/run-step", response_model=Response[Any], summary="步进回测（主观策略预设调仓日交互）")
async def run_backtest_step(
    request: BacktestStepRequest = Body(...),
    market_service: MarketService = Depends(get_market_service),
    asset_service: AssetService = Depends(get_asset_service),
):
    """
    主观策略预设调仓日步进执行：运行到首个预设日前暂停，返回状态与当前权重；
    前端展示对话框由用户选择「使用预设权重/实时输入/不调仓」后携带 decision 与 state 再调本接口继续，
    直到所有预设日处理完毕返回完整回测结果。
    仅支持传统市值模式（未启用指数净值）。
    """
    from app.backtesting.analytics import PerformanceAnalyzer

    _st = (request.strategy_type or "").strip().lower()
    if _st not in ("manual_allocation", "manual_allocation_strategy") and "manual" not in _st:
        raise HTTPException(status_code=400, detail="步进回测仅支持主观配置策略")
    run_to_date_mode = (getattr(request, "step_phase", None) or "").strip().lower() == "run_to_date"
    if not run_to_date_mode and (not getattr(request, "manual_weight_adjustments", None) or len(request.manual_weight_adjustments) == 0):
        raise HTTPException(status_code=400, detail="请至少预设一个调仓日期")

    config = BacktestConfig(
        name=request.name,
        thscodes=request.thscodes,
        start_date=request.start_date,
        end_date=request.end_date,
        rebalance_freq=request.rebalance_freq,
        initial_cash=request.initial_cash,
        commission_rate=request.commission_rate,
        slippage=request.slippage,
        use_index_nav=False,
    )
    adj_dict = {}
    for item in request.manual_weight_adjustments:
        if isinstance(item, dict) and item.get("date"):
            d = str(item["date"]).replace("-", "")[:8]
            adj_dict[d] = {
                "weights": dict(item["weights"]) if item.get("weights") is not None else {},
                "auto_normalize": item.get("auto_normalize", True),
            }
    config.manual_weight_adjustments = adj_dict
    config.rebalance_only_on_preset_dates = True
    # 主观策略步进回测：注入与监控对齐的复制费率（key=asset_code）
    # 使传统市值模式下 NAV 亦受每日复制费拖拽，与监控引擎一致。
    manual_rc_step = await _build_manual_replication_costs(request.thscodes, asset_service)
    if manual_rc_step:
        config.replication_costs = manual_rc_step
        logger.info(
            "[主观步进回测][RC] config.replication_costs 注入成功，资产数=%d",
            len(manual_rc_step),
        )
    sp_step = getattr(request, "strategy_params", None) or {}
    max_lev_step = float(sp_step.get("max_leverage", 4))
    if max_lev_step < 1:
        max_lev_step = 4
    mw = sp_step.get("manual_weights")
    if mw and isinstance(mw, dict) and len(mw) > 0:
        config.initial_weights = {k: float(v) for k, v in mw.items() if v is not None}
        total_i = sum(config.initial_weights.values())
        if total_i > max_lev_step:
            raise HTTPException(
                status_code=400,
                detail=f"初始权重总和 {total_i*100:.2f}% 超过最大杠杆 {max_lev_step*100:.0f}%。请调整权重或策略参数「最大杠杆」。"
            )
    for d, adj in config.manual_weight_adjustments.items():
        w = adj.get("weights") or {}
        if w:
            total_d = sum(float(v) for v in w.values() if v is not None)
            if total_d > max_lev_step:
                raise HTTPException(
                    status_code=400,
                    detail=f"预设调仓日 {d} 的权重总和 {total_d*100:.2f}% 超过最大杠杆 {max_lev_step*100:.0f}%。请调整权重或策略参数「最大杠杆」。"
                )
    preset_dates = sorted(config.manual_weight_adjustments.keys())
    if preset_dates and config.initial_weights:
        config.initial_weights_auto_normalize = config.manual_weight_adjustments[preset_dates[0]].get("auto_normalize", False)
    data_feed = await DataFeed.from_market_service(
        market_service=market_service, config=config, lookback_days=request.lookback_days
    )
    if data_feed.prices.empty:
        raise HTTPException(status_code=400, detail="无法获取历史行情数据")
    # 预设调仓日校验：须在回测区间内，且为有数据的交易日（run_to_date 模式无预设日则跳过）
    if preset_dates:
        start_ymd = str(request.start_date).replace("-", "")[:8]
        end_ymd = str(request.end_date).replace("-", "")[:8]
        out_of_range = [d for d in preset_dates if d < start_ymd or d > end_ymd]
        if out_of_range:
            raise HTTPException(
                status_code=400,
                detail=f"调仓日不可超出回测时间区间。以下日期超出区间 [{start_ymd}, {end_ymd}]：{', '.join(sorted(out_of_range))}。请重新设置调仓日。"
            )
        trading_days = set(pd.Series(data_feed.prices.index).dt.strftime("%Y%m%d").astype(str).tolist())
        invalid_preset = [d for d in preset_dates if d not in trading_days]
        if invalid_preset:
            raise HTTPException(
                status_code=400,
                detail=f"以下调仓日在回测区间内无行情数据或为非交易日，请重新设置调仓日：{', '.join(sorted(invalid_preset))}"
            )

    strategy_service = await create_strategy_service_from_database(market_service=market_service)
    try:
        strategy_cls = strategy_service.get_strategy_class(request.strategy_type)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"策略类型不存在: {request.strategy_type}")
    strategy_impl = strategy_cls()
    if not hasattr(strategy_impl, "allocate"):
        raise HTTPException(status_code=500, detail="策略未实现 allocate 方法")

    enable_selection = (
        request.strategy_params.get("enable_momentum_selection", False)
        or request.strategy_params.get("asset_selection_count") is not None
    )
    selection_info = {}
    if enable_selection:
        raw_selector_type = request.strategy_params.get("selector_type", "momentum")
        if raw_selector_type in ("reversal", "momentum_reversal", "hybrid"):
            selector_type = "momentum_reversal"
            n_momentum = int(request.strategy_params.get("n_momentum", 7))
            n_reversal = int(request.strategy_params.get("n_reversal", 1))
            n_assets = n_momentum + n_reversal
            selection_params = {
                "min_history_days": request.strategy_params.get("min_history_days", 260),
                "momentum_windows": request.strategy_params.get("momentum_windows", "20,60,120,250"),
                "macd_windows": request.strategy_params.get("macd_windows", "40,80,120,160"),
                "reversal_windows": request.strategy_params.get("reversal_windows", "10,22"),
                "n_momentum": n_momentum,
                "n_reversal": n_reversal,
            }
        else:
            selector_type = raw_selector_type
            n_assets = int(request.strategy_params.get("asset_selection_count") or len(request.thscodes))
            selection_params = {
                "min_history_days": request.strategy_params.get("min_history_days", 260),
                "momentum_windows": request.strategy_params.get("momentum_windows", "20,60,120,250"),
                "tie_break_window": request.strategy_params.get("tie_break_window", 22),
            }
        selection_info = {"selector_type": selector_type, "n_assets": n_assets, "selection_params": selection_params}
    # 步进回测仅支持主观策略，主观策略不应用指数编制规则权重上限
    request.strategy_params["max_weight_dict"] = {}

    base_strategy = StrategiesWrapper(strategy_impl=strategy_impl, params=request.strategy_params)
    if enable_selection:
        from app.backtesting.strategy_api import StrategyAdapterWithSelection
        strategy = StrategyAdapterWithSelection(
            base_strategy=base_strategy, thscodes=request.thscodes, enable_selection=True, selection_info=selection_info
        )
    else:
        strategy = base_strategy

    max_total_lev = request.strategy_params.get("max_total_leverage") or request.strategy_params.get("max_leverage")
    if max_total_lev is not None:
        try:
            max_total_lev = float(max_total_lev)
        except (TypeError, ValueError):
            max_total_lev = None
    max_w_dict = request.strategy_params.get("max_weight_dict")
    if not isinstance(max_w_dict, dict):
        max_w_dict = None
    try:
        risk_config = RiskConfig(
            max_total_leverage=max_total_lev,
            max_weight_dict=max_w_dict,
        )
    except TypeError:
        risk_config = RiskConfig()
    risk_manager = RiskManager(config=risk_config)
    execution_engine = ExecutionEngine(config=config)
    engine = BacktestEngine(
        config=config,
        data_feed=data_feed,
        strategy=strategy,
        risk_manager=risk_manager,
        execution_engine=execution_engine,
    )

    def _weights_for_response(weights_dict):
        if not weights_dict:
            return weights_dict
        return {k: float(v) for k, v in weights_dict.items() if v is not None}

    asset_names = {}
    for code in request.thscodes:
        info = await asset_service.get_asset_by_code(code)
        if info and info.name:
            asset_names[code] = info.name
        else:
            asset_names[code] = ZY_DOCUMENT_CODE_TO_NAME.get(code, code)

    # run_to_date：从开始跑到 end_date，仅期初建仓，用于多策略时间线「当前调仓日」对比
    if run_to_date_mode:
        try:
            snapshots, trades, state, stopped_at = engine.run_step(stop_before_date=None)
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"run_to_date 执行失败: {type(e).__name__}: {str(e)}")
        total_values_series = pd.Series([s.total_value for s in snapshots])
        drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()
        snapshots_out = []
        for i, s in enumerate(snapshots):
            snapshots_out.append(
                SnapshotOut(
                    time=s.time,
                    total_value=s.total_value,
                    cash=s.cash,
                    holdings_value=s.holdings_value,
                    weights=_weights_for_response(s.weights or {}),
                    is_rebalance_day=s.is_rebalance_day,
                    rebalance_type=getattr(s, "rebalance_type", None),
                    rebalance_reason=getattr(s, "rebalance_reason", None),
                    portfolio_volatility=getattr(s, "portfolio_volatility", None),
                    drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0,
                    monitoring_metrics=getattr(s, "monitoring_metrics", {}),
                )
            )
        analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
        performance = analyzer.from_results(snapshots, trades)
        trades_out = [
            TradeOut(
                time=getattr(t, "time", None),
                thscode=getattr(t, "thscode", ""),
                side=getattr(t, "side", ""),
                quantity=float(getattr(t, "quantity", 0) or 0),
                price=float(getattr(t, "price", 0) or 0),
                commission=float(getattr(t, "commission", 0) or 0),
                slippage_cost=float(getattr(t, "slippage_cost", 0) or 0),
                rebalance_label="期初建仓" if getattr(t, "time", None) and snapshots and getattr(snapshots[0], "time", None) and getattr(t, "time", None) == getattr(snapshots[0], "time", None) else None,
            )
            for t in trades
        ]
        backtest_result = BacktestResultOut(
            snapshots=snapshots_out,
            trades=trades_out,
            total_return=performance.total_return,
            annual_return=performance.annual_return,
            volatility=performance.annual_volatility,
            sharpe_ratio=performance.sharpe_ratio,
            max_drawdown=performance.max_drawdown,
            calmar_ratio=performance.calmar_ratio,
            asset_names=asset_names,
            selected_asset_count=request.strategy_params.get("selected_asset_count"),
        )
        _data = backtest_result.model_dump()
        _apply_snapshot_aggregation(_data)
        return Response.success(data=_sanitize_dict_for_json(_data), message="run_to_date 完成")

    if request.step_phase == "start":
        if not preset_dates:
            raise HTTPException(status_code=400, detail="无预设调仓日")
        stop_before = preset_dates[0]
        try:
            snapshots, trades, state, stopped_at = engine.run_step(stop_before_date=stop_before)
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"步进回测(首段)执行失败: {type(e).__name__}: {str(e)}")
        if stopped_at is None:
            raise HTTPException(status_code=500, detail="步进回测未在预设日前暂停")
        snapshots_out = _snapshots_to_out(snapshots, _weights_for_response)
        remaining = preset_dates[1:]
        current_weights = (state.get("weights") or {}) if state else {}
        current_metrics = _compute_paused_metrics(snapshots, trades)
        segment_trades = [_trade_to_dict(t) for t in trades]
        paused = BacktestStepPausedOut(
            phase="paused",
            snapshots=snapshots_out,
            state=state or {},
            next_preset_date=stop_before,
            remaining_preset_dates=remaining,
            current_weights=current_weights,
            asset_names=asset_names,
            current_metrics=current_metrics,
            max_weight_dict={},  # 主观策略不限制权重上限
            trades=segment_trades,
        )
        _data = paused.model_dump()
        return Response.success(data=_sanitize_dict_for_json(_data), message="已暂停，请选择该调仓日的操作")

    if request.step_phase != "continue" or not request.step_state or not request.preset_date_decision:
        raise HTTPException(status_code=400, detail="continue 阶段需提供 step_state 与 preset_date_decision")

    decision = request.preset_date_decision
    decision_date = str(decision.get("date", "")).replace("-", "")[:8]
    action = decision.get("action", "skip")
    if action not in ("use_preset", "custom", "skip"):
        raise HTTPException(status_code=400, detail="preset_date_decision.action 须为 use_preset / custom / skip")

    if action == "skip":
        override_decision = {"date": decision_date, "action": "skip"}
    else:
        if action == "custom":
            weights = decision.get("weights")
        else:
            # use_preset: 优先使用请求里传来的 weights（前端已按预设日匹配并填入），避免 config 与 decision_date 格式不一致导致未调仓
            weights = decision.get("weights") if decision.get("weights") else (config.manual_weight_adjustments.get(decision_date) or {}).get("weights")
        if action == "use_preset" and not weights:
            weights = None
        # 统一转为 float，避免前端传字符串导致引擎 sum(weights_dict.values()) 报错
        weights_clean = {}
        if weights and isinstance(weights, dict):
            for k, v in weights.items():
                try:
                    weights_clean[k] = float(v) if v is not None else 0.0
                except (TypeError, ValueError):
                    weights_clean[k] = 0.0
        # 步进调仓权重总和不允许超过最大杠杆
        if weights_clean:
            max_lev = float((getattr(request, "strategy_params", None) or {}).get("max_leverage", 4))
            if max_lev < 1:
                max_lev = 4
            total_w = sum(weights_clean.values())
            if total_w > max_lev:
                raise HTTPException(
                    status_code=400,
                    detail=f"步进调仓权重总和 {total_w*100:.2f}% 超过最大杠杆 {max_lev*100:.0f}%。请调整权重或策略参数「最大杠杆」。"
                )
        has_nonzero = bool(weights_clean and any(v != 0 for v in weights_clean.values()))
        override_decision = {
            "date": decision_date,
            "action": "rebalance" if has_nonzero else "skip",
            "weights": weights_clean,
            "auto_normalize": decision.get("auto_normalize", False),
        }

    next_preset = None
    remaining = list(request.step_state.get("remaining_preset_dates") or [])
    if remaining:
        next_preset = remaining[0]
        remaining = remaining[1:]

    try:
        snapshots, trades, state, stopped_at = engine.run_step(
            initial_state=request.step_state.get("state"),
            override_decision=override_decision,
            stop_before_date=next_preset,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"步进回测(继续)执行失败: {type(e).__name__}: {str(e)}")

    accumulated = list(request.accumulated_snapshots or [])
    accumulated_trades = list(request.accumulated_trades or [])
    for t in trades:
        accumulated_trades.append(_trade_to_dict(t))
    from app.backtesting.types import PortfolioSnapshot
    for s in snapshots:
        accumulated.append({
            "time": s.time,
            "total_value": s.total_value,
            "cash": s.cash,
            "holdings_value": s.holdings_value,
            "weights": s.weights,
            "is_rebalance_day": s.is_rebalance_day,
            "rebalance_type": getattr(s, "rebalance_type", None),
            "rebalance_reason": getattr(s, "rebalance_reason", None),
            "portfolio_volatility": getattr(s, "portfolio_volatility", None),
            "monitoring_metrics": getattr(s, "monitoring_metrics", {}),
        })

    if stopped_at is None and not remaining:
        total_values_series = pd.Series([x["total_value"] for x in accumulated])
        drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()
        snapshots_out = []
        for i, x in enumerate(accumulated):
            snapshots_out.append(
                SnapshotOut(
                    time=x["time"],
                    total_value=x["total_value"],
                    cash=x["cash"],
                    holdings_value=x["holdings_value"],
                    weights=_weights_for_response(x.get("weights") or {}),
                    is_rebalance_day=x.get("is_rebalance_day", False),
                    rebalance_type=x.get("rebalance_type"),
                    rebalance_reason=x.get("rebalance_reason"),
                    portfolio_volatility=x.get("portfolio_volatility"),
                    drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0,
                    monitoring_metrics=x.get("monitoring_metrics", {}),
                )
            )
        rebalance_by_date = {}
        for x in accumulated:
            if x.get("is_rebalance_day"):
                dt = x.get("time")
                if dt is not None:
                    key = pd.Timestamp(dt).strftime("%Y-%m-%d") if hasattr(pd.Timestamp(dt), "strftime") else str(dt)[:10]
                    rebalance_by_date[key] = (x.get("rebalance_type"), x.get("rebalance_reason"))
        all_trades = []
        for t in accumulated_trades:
            tdt = t.get("time")
            key = pd.Timestamp(tdt).strftime("%Y-%m-%d") if tdt is not None and hasattr(pd.Timestamp(tdt), "strftime") else (str(tdt)[:10] if tdt else "")
            rt, rr = rebalance_by_date.get(key, (None, None))
            all_trades.append(
                TradeOut(
                    time=pd.Timestamp(t["time"]) if t.get("time") is not None else t.get("time"),
                    thscode=t.get("thscode", ""),
                    side=t.get("side", ""),
                    quantity=float(t.get("quantity", 0) or 0),
                    price=float(t.get("price", 0) or 0),
                    commission=float(t.get("commission", 0) or 0),
                    slippage_cost=float(t.get("slippage_cost", 0) or 0),
                    rebalance_label=_rebalance_label_for_trade(rt, rr)
                )
            )
        analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
        performance = analyzer.from_results(
            [PortfolioSnapshot(time=pd.Timestamp(x["time"]), total_value=x["total_value"], cash=x["cash"], holdings_value=x["holdings_value"], weights=x.get("weights") or {}, is_rebalance_day=x.get("is_rebalance_day", False), rebalance_type=x.get("rebalance_type"), rebalance_reason=x.get("rebalance_reason"), portfolio_volatility=x.get("portfolio_volatility"), monitoring_metrics=x.get("monitoring_metrics", {})) for x in accumulated],
            trades,
        )
        selected_asset_count = (getattr(request, "strategy_params", None) or {}).get("selected_asset_count") or (getattr(request, "strategy_params", None) or {}).get("asset_selection_count")
        backtest_result = BacktestResultOut(
            snapshots=snapshots_out,
            trades=all_trades,
            total_return=performance.total_return,
            annual_return=performance.annual_return,
            volatility=performance.annual_volatility,
            sharpe_ratio=performance.sharpe_ratio,
            max_drawdown=performance.max_drawdown,
            calmar_ratio=performance.calmar_ratio,
            asset_names=asset_names,
            selected_asset_count=selected_asset_count,
        )
        _dump = backtest_result.model_dump()
        _s = _dump.get("snapshots") or []
        print(f"[回测] 返回主观策略续跑完成数据 snapshots={len(_s)} trades={len(_dump.get('trades') or [])}")
        # 供多策略对比时"延续至当前对比日"使用：前端可据此再次调用 step continue 跑到 target end_date
        _dump["step_state_at_end"] = {
            "state": state if isinstance(state, dict) else {},
            "remaining_preset_dates": [],
        }
        _apply_snapshot_aggregation(_dump)
        return Response.success(data=_sanitize_dict_for_json(_dump), message="回测完成")
    else:
        total_values_series = pd.Series([x["total_value"] for x in accumulated])
        drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()
        snapshots_out = []
        for i, x in enumerate(accumulated):
            snapshots_out.append(
                SnapshotOut(
                    time=x["time"],
                    total_value=x["total_value"],
                    cash=x["cash"],
                    holdings_value=x["holdings_value"],
                    weights=_weights_for_response(x.get("weights") or {}),
                    is_rebalance_day=x.get("is_rebalance_day", False),
                    rebalance_type=x.get("rebalance_type"),
                    rebalance_reason=x.get("rebalance_reason"),
                    portfolio_volatility=x.get("portfolio_volatility"),
                    drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0,
                    monitoring_metrics=x.get("monitoring_metrics", {}),
                )
            )
        current_metrics = _compute_paused_metrics(accumulated, trades)
        paused = BacktestStepPausedOut(
            phase="paused",
            snapshots=snapshots_out,
            state=state or {},
            next_preset_date=next_preset or "",
            remaining_preset_dates=remaining,
            current_weights=(state.get("weights") or {}) if state else {},
            asset_names=asset_names,
            current_metrics=current_metrics,
            max_weight_dict={},  # 主观策略不限制权重上限
            trades=accumulated_trades,
        )
    _data = paused.model_dump()
    return Response.success(data=_sanitize_dict_for_json(_data), message="已暂停，请选择下一调仓日操作")


@router.get("/max-weights", response_model=Response[Dict[str, float]], summary="按指数编制规则返回资产权重上限")
async def get_max_weights_by_codes(
    thscodes: str = Query(..., description="资产代码，逗号分隔"),
    asset_service: AssetService = Depends(get_asset_service),
):
    """根据浙银理财指数编制规则返回每类资产的权重上限，供前端权重输入限制与提示。"""
    codes = [c.strip() for c in thscodes.split(",") if c.strip()]
    if not codes:
        return Response.success(data={}, message="无资产代码")
    doc_max_by_code = {}
    for code in codes:
        info = await asset_service.get_asset_by_code(code)
        name = info.name if info else code
        max_w = (
            ZY_DOCUMENT_MAX_WEIGHT_BY_CODE.get(code)
            or ZY_DOCUMENT_MAX_WEIGHT_BY_ASSET_NAME.get(name)
            or ZY_DOCUMENT_MAX_WEIGHT_ALIASES.get(name)
            or ZY_DOCUMENT_DEFAULT_MAX_WEIGHT
        )
        doc_max_by_code[code] = float(max_w)
    return Response.success(data=doc_max_by_code, message="ok")


class ComputeMetricsFromSnapshotsRequest(BaseModel):
    """基于快照切片计算绩效指标（用于多策略步进对比，保证与净值曲线数据源一致）"""
    snapshots: List[Dict[str, Any]] = Field(..., description="组合快照列表，含 time/total_value/is_rebalance_day 等")
    cutoff_date: str = Field(..., description="截止日期 YYYYMMDD，只使用 time<=cutoff_date 的快照")


@router.post("/compute-metrics-from-snapshots", response_model=Response[Dict[str, Any]], summary="基于快照切片计算绩效指标")
async def compute_metrics_from_snapshots(request: ComputeMetricsFromSnapshotsRequest = Body(...)):
    """
    根据已有快照按截止日期切片后计算绩效指标。
    用于多策略步进时「其他策略截至本调仓日绩效」与最终净值曲线保持同一数据源，避免 run_to_date（仅期初建仓）导致的指标与净值曲线不一致。
    """
    cutoff = str(request.cutoff_date).replace("-", "")[:8]
    if not cutoff or len(cutoff) != 8:
        raise HTTPException(status_code=400, detail="cutoff_date 须为 YYYYMMDD 格式")
    sliced = []
    for s in request.snapshots:
        t = s.get("time")
        if t is None:
            continue
        try:
            ts = pd.Timestamp(t)
            ds = ts.strftime("%Y%m%d") if hasattr(ts, "strftime") else str(t).replace("-", "")[:8]
            if ds <= cutoff:
                sliced.append(s)
        except Exception:
            continue
    if not sliced:
        return Response.success(data={
            "total_return": 0.0,
            "annual_return": 0.0,
            "volatility": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "calmar_ratio": 0.0,
        }, message="无有效快照")
    metrics = _compute_paused_metrics(sliced, None)
    return Response.success(data={
        "total_return": metrics.get("total_return") or 0.0,
        "annual_return": metrics.get("annual_return") or 0.0,
        "volatility": metrics.get("volatility") or 0.0,
        "max_drawdown": metrics.get("max_drawdown") or 0.0,
        "sharpe_ratio": metrics.get("sharpe_ratio") or 0.0,
        "calmar_ratio": metrics.get("calmar_ratio") or 0.0,
    }, message="ok")


@router.post("/quick-test", response_model=Response[Dict[str, Any]], summary="快速回测（仅返回关键指标）")
async def quick_backtest(
    request: BacktestRequest = Body(...),
    market_service: MarketService = Depends(get_market_service),
    asset_service: AssetService = Depends(get_asset_service),
    fx_service: FxService = Depends(get_fx_service),
):
    """
    快速回测接口，仅返回关键绩效指标，不返回详细的快照和交易记录
    
    适用于：
    - 参数调优时的快速验证
    - 批量回测比较
    - 只关心结果不关心过程的场景
    """
    try:
        # 复用完整回测逻辑
        full_result = await run_backtest(request, market_service, asset_service, fx_service)
        
        # 只提取关键指标
        result_data = full_result.data
        quick_result = {
            "total_return": result_data.total_return,
            "annual_return": result_data.annual_return,
            "volatility": result_data.volatility,
            "sharpe_ratio": result_data.sharpe_ratio,
            "max_drawdown": result_data.max_drawdown,
            "calmar_ratio": result_data.calmar_ratio,
            "total_trades": len(result_data.trades),
            "total_days": len(result_data.snapshots)
        }
        
        return Response.success(data=_sanitize_dict_for_json(quick_result), message="快速回测完成")
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"快速回测失败: {str(e)}")


@router.get("/{record_id}", response_model=Response[BacktestRecordOut], summary="获取回测详情")
async def get_backtest_detail(
    record_id: str,
    service: StrategyModelService = Depends(get_model_service),
    asset_service: AssetService = Depends(get_asset_service)
):
    """
    根据记录ID获取数据库中的回测详情
    """
    validate_object_id(record_id)
    record = await service.get_backtest_record(record_id)
    
    if not record:
        raise HTTPException(status_code=404, detail=f"回测记录不存在: {record_id}")
        
    # 填充缺失的资产名称（兜底处理）
    if not record.result.asset_names:
        asset_names = {}
        # 从持仓记录中提取资产代码
        codes = set()
        for pos_rec in record.result.positions:
            for pos in pos_rec.positions:
                codes.add(pos.asset_code)
        
        for code in codes:
            info = await asset_service.get_asset_by_code(code)
            if info:
                asset_names[code] = info.name
        record.result.asset_names = asset_names
        
    # 确保每个持仓点都有资产名称
    for pos_rec in record.result.positions:
        for pos in pos_rec.positions:
            if not pos.asset_name:
                pos.asset_name = record.result.asset_names.get(pos.asset_code)

    _data = record.model_dump() if hasattr(record, "model_dump") else record
    return Response.success(data=_sanitize_dict_for_json(_data))


class BacktestByModelRequest(BaseModel):
    """根据策略模型回测的请求参数"""
    start_date: str = Field(..., description="回测开始日期（格式：YYYYMMDD）")
    end_date: str = Field(..., description="回测结束日期（格式：YYYYMMDD）")
    initial_cash: float = Field(10_000_000.0, description="初始资金")
    rebalance_freq: Optional[str] = Field(None, description="调仓频率（覆盖模型配置，daily/weekly/monthly/quarterly/yearly）")
    commission_rate: Optional[float] = Field(None, description="手续费率（覆盖模型配置）")
    slippage: Optional[float] = Field(None, description="滑点率（覆盖模型配置）")
    lookback_days: int = Field(500, description="历史数据预加载天数")
    
    # 手动选择资产：前端指定具体要用于回测的资产列表（优先级最高，跳过动量选择器）
    selected_asset_codes: Optional[List[str]] = Field(None, description="手动选择的资产代码列表（优先使用，跳过动量选择）")
    
    # 动量选择器参数（可选，如果策略启用了选择器，这些参数会覆盖数据库中的配置）
    enable_momentum_selection: Optional[bool] = Field(None, description="是否启用动量资产选择（覆盖模型配置）")
    selector_type: Optional[str] = Field(None, description="选择器类型（momentum/momentum_reversal，覆盖模型配置）")
    asset_selection_count: Optional[int] = Field(None, description="选择资产数量（覆盖模型配置）")
    min_history_days: Optional[int] = Field(None, description="最小历史数据要求（覆盖模型配置）")
    momentum_windows: Optional[str] = Field(None, description="动量窗口(MOM/POSI/SMOM)，格式：20,60,120,250（覆盖模型配置）")
    tie_break_window: Optional[int] = Field(None, description="并列决胜窗口（覆盖模型配置）")
    
    # 波动率阈值重置（仅对 risk_budget_target_vol 生效，覆盖模型配置）
    enable_vol_reset: Optional[bool] = Field(None, description="是否启用波动率阈值重置（覆盖模型配置）")
    vol_reset_threshold: Optional[float] = Field(None, description="波动率重置阈值，如 0.06 表示 6%（覆盖模型配置）")

    # 交互式权重调整（仅 manual_allocation 策略）：指定日期使用用户预设的权重
    manual_weight_adjustments: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="[{date: YYYYMMDD, weights: {code: w}, auto_normalize: bool}, ...]"
    )
    # 默认权重（仅 manual_allocation 策略）：本次回测覆盖模型的 manual_weights，避免模型未配置时报错
    manual_weights: Optional[Dict[str, float]] = Field(
        None,
        description="资产代码到权重的映射，覆盖策略模型中的默认权重（仅主观配置策略）"
    )

    # 步进回测（仅主观策略预设调仓日交互）
    step_phase: Optional[str] = Field(None, description="start | continue | run_to_date（多策略时间线：从开始跑到 end_date 仅期初建仓）")
    step_state: Optional[Dict[str, Any]] = Field(None, description="上一段返回的 state/remaining_preset_dates 等")
    preset_date_decision: Optional[Dict[str, Any]] = Field(None, description="当前预设日用户决策")
    accumulated_snapshots: Optional[List[Dict[str, Any]]] = Field(None, description="此前各段快照")
    accumulated_trades: Optional[List[Dict[str, Any]]] = Field(None, description="此前各段交易记录，continue 时传")

    # 回测结果备注（保存到策略回测记录，可在回测记录列表中展示与编辑）
    remark: Optional[str] = Field(None, description="备注信息")

    # 杠杆倍数限制（本次回测覆盖模型配置，如 4 表示 400%，初始化/预设调仓日/步进调仓权重和均不得超过此值）
    max_leverage: Optional[float] = Field(None, description="杠杆倍数限制，覆盖策略模型中的最大杠杆（如 4 表示 400%）")

    # 多策略时间线对比：从开始跑到该日仅期初建仓，返回该日绩效（与 step_phase=run_to_date 配合）
    run_to_date: Optional[str] = Field(None, description="YYYYMMDD，与 step_phase=run_to_date 同时传时生效")

    @field_validator('start_date', 'end_date', mode='before')
    @classmethod
    def validate_date(cls, v: Any) -> str:
        """验证并规范化日期格式为 YYYYMMDD"""
        if not v:
            return v
        try:
            dt = pd.to_datetime(v)
            return dt.strftime('%Y%m%d')
        except Exception:
            return v


@router.post("/run-by-model/{model_id}", response_model=Response[Union[BacktestResultOut, BacktestStepPausedOut]], summary="根据策略模型快捷回测")
async def run_backtest_by_model(
    model_id: str,
    request: BacktestByModelRequest = Body(...),
    market_service: MarketService = Depends(get_market_service),
    asset_service: AssetService = Depends(get_asset_service),
    fx_service: FxService = Depends(get_fx_service),
):
    """
    根据策略模型快捷回测
    
    自动从策略模型中获取：
    - 策略类型（template_code）
    - 策略参数（parameters）
    - 资产池（asset_codes）
    - 调仓频率（rebalance_frequency）
    
    只需指定：
    - 回测日期区间
    - 初始资金（可选）
    
    适用场景：
    - 模型开发后快速验证
    - 模型参数调优
    - 不同时间区间比较
    
    示例：
    ```
    POST /api/v1/backtests/run-by-model/6789abc123def456
    {
        "start_date": "20230101",
        "end_date": "20231231",
        "initial_cash": 5000000
    }
    ```
    """
    try:
        # 1. 获取策略模型
        model_service = StrategyModelService()
        model = await model_service.get_model(model_id)
        
        if not model:
            raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")
        
        # 2. 从模型生成回测请求（支持参数覆盖）
        overrides = {
            "initial_cash": request.initial_cash,
            "lookback_days": request.lookback_days
        }
        if request.rebalance_freq:
            overrides["rebalance_freq"] = request.rebalance_freq
        if request.commission_rate is not None:
            overrides["commission_rate"] = request.commission_rate
        if request.slippage is not None:
            overrides["slippage"] = request.slippage
        
        request_data = model_service.to_backtest_request(
            model=model,
            start_date=request.start_date,
            end_date=request.end_date,
            **overrides
        )
        
        # 检查模型是否启用了资产选择（从数据库直接获取，因为可能不在StrategyModel模型中）
        from bson import ObjectId
        model_data = await model_service.collection.find_one({"_id": ObjectId(model_id)})
        
        model_asset_count = len(model.asset_codes)
        model_asset_set = set(model.asset_codes)
        
        # ========== 手动选择资产（作为候选池） ==========
        raw_selector_for_manual = (
            request.selector_type or (model_data and model_data.get("selector_type")) or "momentum"
        )
        is_hybrid = raw_selector_for_manual in ("reversal", "momentum_reversal", "hybrid")

        if request.selected_asset_codes is not None and len(request.selected_asset_codes) > 0:
            selected_codes = request.selected_asset_codes
            n_selected = len(selected_codes)

            invalid_codes = [c for c in selected_codes if c not in model_asset_set]
            if invalid_codes:
                raise HTTPException(
                    status_code=400,
                    detail=f"以下资产不在模型资产池中：{', '.join(invalid_codes)}。模型资产池：{', '.join(model.asset_codes)}"
                )

            # 混合动量：手动选择作为候选池，仍跑 7+1 筛选；其余逻辑不要求 asset_selection_count == n_selected
            if is_hybrid:
                request_data["thscodes"] = selected_codes
                request_data["strategy_params"]["enable_momentum_selection"] = True
                request_data["strategy_params"]["selector_type"] = "momentum_reversal"
                n_mom = int((model_data and model_data.get("n_momentum")) or 7)
                n_rev = int((model_data and model_data.get("n_reversal")) or 1)
                request_data["strategy_params"]["n_momentum"] = n_mom
                request_data["strategy_params"]["n_reversal"] = n_rev
                request_data["strategy_params"]["reversal_windows"] = (
                    (model_data and model_data.get("reversal_windows")) or "10,22"
                )
                request_data["strategy_params"]["asset_selection_count"] = n_mom + n_rev
                request_data["strategy_params"]["min_history_days"] = (
                    request.min_history_days
                    if request.min_history_days is not None
                    else (model_data.get("min_history_days", 260) if model_data else 260)
                )
                request_data["strategy_params"]["momentum_windows"] = (
                    request.momentum_windows or (model_data and model_data.get("momentum_windows")) or "20,60,120,250"
                )
                request_data["strategy_params"]["macd_windows"] = (
                    getattr(request, "macd_windows", None) or (model_data and model_data.get("macd_windows")) or "40,80,120,160"
                )
                request_data["strategy_params"]["tie_break_window"] = (
                    request.tie_break_window
                    if request.tie_break_window is not None
                    else (model_data.get("tie_break_window", 22) if model_data else 22)
                )
            else:
                if request.asset_selection_count is not None:
                    expected = int(request.asset_selection_count)
                    if n_selected != expected:
                        raise HTTPException(
                            status_code=400,
                            detail=f"选择资产数量（{expected}）与实际勾选的资产数量（{n_selected}）不一致，请检查。"
                        )
                request_data["thscodes"] = selected_codes
                request_data["strategy_params"]["enable_momentum_selection"] = False
                request_data["strategy_params"]["asset_selection_count"] = n_selected
        else:
            # ========== 未手动选择资产时，走原有动量选择器逻辑 ==========
            use_frontend_count = request.asset_selection_count is not None
            
            if use_frontend_count:
                n_assets = int(request.asset_selection_count)
                if n_assets < 1:
                    raise HTTPException(status_code=400, detail="选择资产数量必须大于 0")
                if n_assets > model_asset_count:
                    raise HTTPException(
                        status_code=400,
                        detail=f"选择资产数量（{n_assets}）不能大于模型资产池数量（{model_asset_count}）。请调整前端「选择资产数量」或模型资产配置。"
                    )
            
            enable_selection = bool(
                request.enable_momentum_selection is True
                or use_frontend_count
                or (request.selector_type is not None or request.min_history_days is not None
                    or request.momentum_windows is not None or request.tie_break_window is not None)
                or (model_data and model_data.get("enable_momentum_selection", False))
            )
            
            if enable_selection:
                request_data["strategy_params"]["enable_momentum_selection"] = True
                raw_selector_type = (
                    request.selector_type
                    or (model_data and model_data.get("selector_type")) or "momentum"
                )
                # 混合动量：hybrid / momentum_reversal / reversal → momentum_reversal（7+1，与指数编制规则一致）
                if raw_selector_type in ("reversal", "momentum_reversal", "hybrid"):
                    request_data["strategy_params"]["selector_type"] = "momentum_reversal"
                    n_momentum = int((model_data and model_data.get("n_momentum")) or 7)
                    n_reversal = int((model_data and model_data.get("n_reversal")) or 1)
                    request_data["strategy_params"]["n_momentum"] = n_momentum
                    request_data["strategy_params"]["n_reversal"] = n_reversal
                    request_data["strategy_params"]["reversal_windows"] = (
                        (model_data and model_data.get("reversal_windows")) or "10,22"
                    )
                    # 7+1 选择器产出 7～8 个资产，asset_selection_count 取 8；前端/模型可覆盖
                    n_from_request = int(request.asset_selection_count) if request.asset_selection_count is not None else None
                    n_from_model = model_data.get("asset_selection_count") if model_data else None
                    if n_from_request is not None:
                        n_selected = n_from_request
                    elif n_from_model is not None:
                        n_selected = int(n_from_model)
                    else:
                        n_selected = min(n_momentum + n_reversal, model_asset_count)
                    request_data["strategy_params"]["asset_selection_count"] = n_selected
                else:
                    request_data["strategy_params"]["selector_type"] = raw_selector_type
                    n_from_request = int(request.asset_selection_count) if request.asset_selection_count is not None else None
                    n_from_model = model_data.get("asset_selection_count") if model_data else None
                    if n_from_request is not None:
                        n_selected = n_from_request
                    elif n_from_model is not None:
                        n_selected = int(n_from_model)
                    else:
                        template_code = getattr(model, "template_code", None) or (model_data.get("template_code") if model_data else None)
                        n_selected = min(8, model_asset_count) if template_code == "risk_budget_target_vol" else model_asset_count
                    request_data["strategy_params"]["asset_selection_count"] = n_selected
                request_data["strategy_params"]["min_history_days"] = (
                    request.min_history_days
                    if request.min_history_days is not None
                    else (model_data.get("min_history_days", 260) if model_data else 260)
                )
                request_data["strategy_params"]["momentum_windows"] = (
                    request.momentum_windows or (model_data and model_data.get("momentum_windows")) or "20,60,120,250"
                )
                request_data["strategy_params"]["macd_windows"] = (
                    getattr(request, "macd_windows", None) or (model_data and model_data.get("macd_windows")) or "40,80,120,160"
                )
                request_data["strategy_params"]["tie_break_window"] = (
                    request.tie_break_window
                    if request.tie_break_window is not None
                    else (model_data.get("tie_break_window", 22) if model_data else 22)
                )
                if raw_selector_type not in ("reversal", "momentum_reversal", "hybrid") and model_data and model_data.get("n_assets_for_allocation") is not None:
                    request_data["strategy_params"]["n_assets_for_allocation"] = int(
                        model_data["n_assets_for_allocation"]
                    )
        
        # 3.5 按浙银理财编制规则填充每类资产最大权重：仅动量/量化策略；主观策略不限制
        strategy_type_unified = request_data.get("strategy_type") or ""
        if not _is_manual_strategy(strategy_type_unified):
            doc_max_by_code = {}
            for code in request_data["thscodes"]:
                info = await asset_service.get_asset_by_code(code)
                name = info.name if info else code
                max_w = (
                    ZY_DOCUMENT_MAX_WEIGHT_BY_CODE.get(code)
                    or ZY_DOCUMENT_MAX_WEIGHT_BY_ASSET_NAME.get(name)
                    or ZY_DOCUMENT_MAX_WEIGHT_ALIASES.get(name)
                    or ZY_DOCUMENT_DEFAULT_MAX_WEIGHT
                )
                doc_max_by_code[code] = max_w
            request_data["strategy_params"]["max_weight_dict"] = dict(doc_max_by_code)
        else:
            request_data["strategy_params"]["max_weight_dict"] = {}

        # 3.6 波动率阈值重置覆盖（所有策略均可传入；仅目标波动率类策略在引擎中会实际执行）
        if request.enable_vol_reset is not None:
            request_data["strategy_params"]["enable_vol_reset"] = request.enable_vol_reset
        # 波动率阈值：优先请求体，其次模型 parameters，最后默认 0.06；确保始终传入，避免引擎使用写死默认值
        vol_thresh = None
        if request.vol_reset_threshold is not None:
            vol_thresh = float(request.vol_reset_threshold)
        elif model_data:
            params = model_data.get("parameters") or {}
            v = model_data.get("vol_reset_threshold") or params.get("vol_reset_threshold") or params.get("vol_trigger_threshold")
            if v is not None:
                try:
                    vol_thresh = float(v)
                except (TypeError, ValueError):
                    vol_thresh = 0.06
        if vol_thresh is None:
            sp = request_data.get("strategy_params") or {}
            v = sp.get("vol_reset_threshold") or sp.get("vol_trigger_threshold")
            vol_thresh = float(v) if v is not None else 0.06
        request_data["strategy_params"]["vol_reset_threshold"] = vol_thresh

        # 3.7 交互式权重调整（仅 manual_allocation 策略）
        if request.manual_weight_adjustments is not None and len(request.manual_weight_adjustments) > 0:
            request_data["manual_weight_adjustments"] = request.manual_weight_adjustments

        # 3.8 默认权重覆盖（仅 manual_allocation 策略）：本次回测覆盖模型的 manual_weights
        if request.manual_weights is not None and len(request.manual_weights) > 0:
            request_data["strategy_params"]["manual_weights"] = dict(request.manual_weights)

        # 3.9 杠杆倍数限制（本次回测覆盖模型配置，用于动态限制初始化/预设调仓日/步进调仓权重和）
        if getattr(request, "max_leverage", None) is not None:
            try:
                lev = float(request.max_leverage)
                if lev >= 1:
                    request_data["strategy_params"]["max_leverage"] = lev
            except (TypeError, ValueError):
                pass

        # 4. 步进回测（主观策略预设调仓日交互）或 run_to_date（多策略时间线：跑至某日仅期初建仓）
        if getattr(request, "run_to_date", None):
            request_data["end_date"] = request.run_to_date
            request_data["manual_weight_adjustments"] = []
            if getattr(request, "step_phase", None) != "run_to_date":
                request_data["step_phase"] = "run_to_date"
        if getattr(request, "step_phase", None) in ("start", "continue", "run_to_date"):
            try:
                # 只传入 BacktestStepRequest 支持的字段，避免 Pydantic 校验报错
                step_body = {k: request_data[k] for k in (
                    "name", "strategy_type", "strategy_params", "thscodes",
                    "start_date", "end_date", "initial_cash", "rebalance_freq",
                    "commission_rate", "slippage", "lookback_days", "manual_weight_adjustments"
                ) if k in request_data}
                step_request = BacktestStepRequest(
                    **step_body,
                    step_phase=request.step_phase,
                    step_state=getattr(request, "step_state", None),
                    preset_date_decision=getattr(request, "preset_date_decision", None),
                    accumulated_snapshots=getattr(request, "accumulated_snapshots", None),
                    accumulated_trades=getattr(request, "accumulated_trades", None),
                )
                step_result = await run_backtest_step(step_request, market_service, asset_service)
                if getattr(request, "step_phase", None) == "run_to_date":
                    return step_result
                # 步进完成（非暂停）时保存回测记录并返回 record_id，使结果出现在策略回测记录中
                step_data = step_result.data if hasattr(step_result, "data") else step_result
                phase = step_data.get("phase") if isinstance(step_data, dict) else getattr(step_data, "phase", None)
                has_snapshots = (step_data.get("snapshots") if isinstance(step_data, dict) else getattr(step_data, "snapshots", None))
                if step_data and has_snapshots and phase != "paused":
                    backtest_data = step_data
                    snapshots = backtest_data.get("snapshots") or []
                    if snapshots:
                        initial_val = snapshots[0].get("total_value") if isinstance(snapshots[0], dict) else getattr(snapshots[0], "total_value", None) or request.initial_cash
                        equity_curve = [
                            EquityPoint(
                                date=s.get("time") if isinstance(s, dict) else s.time,
                                value=s.get("total_value") if isinstance(s, dict) else s.total_value,
                                unit_value=(s.get("total_value") or 0) / initial_val if initial_val else 1.0,
                                cumulative_return=((s.get("total_value") or 0) / initial_val - 1) if initial_val else 0.0,
                                portfolio_volatility=s.get("portfolio_volatility") if isinstance(s, dict) else getattr(s, "portfolio_volatility", None),
                                drawdown=s.get("drawdown") if isinstance(s, dict) else getattr(s, "drawdown", None),
                                rebalance_type=s.get("rebalance_type") if isinstance(s, dict) else getattr(s, "rebalance_type", None)
                            )
                            for s in snapshots
                        ]
                        return_curve = [
                            ReturnPoint(
                                date=s.get("time") if isinstance(s, dict) else s.time,
                                daily_return=0.0,
                                cumulative_return=((s.get("total_value") or 0) / initial_val - 1) if initial_val else 0.0
                            )
                            for s in snapshots
                        ]
                        positions_record = [
                            PositionRecord(
                                date=s.get("time") if isinstance(s, dict) else s.time,
                                portfolio_value=s.get("total_value") if isinstance(s, dict) else s.total_value,
                                cash=s.get("cash") if isinstance(s, dict) else s.cash,
                                rebalance_reason=s.get("rebalance_reason") if isinstance(s, dict) else getattr(s, "rebalance_reason", None),
                                positions=[
                                    AssetPosition(
                                        asset_code=code,
                                        asset_name=backtest_data.get("asset_names", {}).get(code) if isinstance(backtest_data.get("asset_names"), dict) else None,
                                        weight=weight,
                                        market_value=(s.get("total_value") if isinstance(s, dict) else s.total_value) * weight
                                    )
                                    for code, weight in (s.get("weights", {}) if isinstance(s, dict) else s.weights).items()
                                ]
                            )
                            for s in snapshots if (s.get("is_rebalance_day") if isinstance(s, dict) else getattr(s, "is_rebalance_day", False))
                        ]
                        weight_changes = [
                            WeightChangePoint(
                                date=(s.get("time") if isinstance(s, dict) else s.time).strftime("%Y-%m-%d") if hasattr((s.get("time") if isinstance(s, dict) else s.time), "strftime") else str((s.get("time") if isinstance(s, dict) else s.time))[:10],
                                weights=s.get("weights") if isinstance(s, dict) else s.weights
                            )
                            for s in snapshots if (s.get("is_rebalance_day") if isinstance(s, dict) else getattr(s, "is_rebalance_day", False))
                        ]
                        model_result = ModelBacktestResult(
                            total_return=backtest_data.get("total_return", 0),
                            annual_return=backtest_data.get("annual_return", 0),
                            annual_volatility=backtest_data.get("volatility", 0),
                            sharpe_ratio=backtest_data.get("sharpe_ratio"),
                            max_drawdown=backtest_data.get("max_drawdown", 0),
                            calmar_ratio=backtest_data.get("calmar_ratio"),
                            equity_curve=equity_curve,
                            return_curve=return_curve,
                            positions=positions_record,
                            weight_changes=weight_changes,
                            asset_names=backtest_data.get("asset_names"),
                            selected_asset_count=backtest_data.get("selected_asset_count")
                        )
                        start_dt = pd.to_datetime(request.start_date)
                        end_dt = pd.to_datetime(request.end_date)
                        backtest_record = BacktestRecord(
                            model_id=model_id,
                            start_date=start_dt,
                            end_date=end_dt,
                            initial_capital=request.initial_cash,
                            result=model_result,
                            remark=getattr(request, "remark", None) or None
                        )
                        record_id = await model_service.save_backtest_record(backtest_record)
                        step_data_out = step_data.model_dump() if hasattr(step_data, "model_dump") else (step_data if isinstance(step_data, dict) else {})
                        if not isinstance(step_data_out, dict):
                            step_data_out = {}
                        step_data_out["record_id"] = record_id
                        step_data_out["remark"] = getattr(request, "remark", None) or ""
                        step_data_out = _sanitize_dict_for_json(step_data_out)
                        _apply_snapshot_aggregation(step_data_out)
                        _snap = step_data_out.get("snapshots") or []
                        _trades = step_data_out.get("trades")
                        print(f"[回测] 返回主观策略回测数据 model_id={model_id} record_id={record_id} snapshots={len(_snap)} has_trades={_trades is not None and len(_trades) > 0}")
                        return Response.success(data=step_data_out, message="回测完成")
                return step_result
            except HTTPException:
                raise
            except Exception as e:
                traceback.print_exc()
                raise HTTPException(
                    status_code=500,
                    detail=f"步进回测失败: {type(e).__name__}: {str(e)}"
                )

        # 4. 构造 BacktestRequest
        backtest_request = BacktestRequest(**request_data)
        
        # 5. 执行回测
        try:
            result = await run_backtest(backtest_request, market_service, asset_service, fx_service)
        except HTTPException as he:
            # 原样重新抛出，保证客户端收到正确的 4xx 状态码（如 400 无法获取行情数据）
            raise he
        except Exception as e:
            # 包装 run_backtest 的错误，提供更多上下文
            error_type = type(e).__name__
            error_msg = str(e)
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=(
                    f"回测引擎执行失败 ({error_type}): {error_msg}\n\n"
                    f"策略模型: {model.name} ({model.template_code})\n"
                    f"资产池: {', '.join(model.asset_codes)}\n"
                    f"日期范围: {request.start_date} 至 {request.end_date}\n\n"
                    f"请检查策略参数配置和资产数据。"
                )
            )
        
        # 5. 保存回测记录
        if result.code == 200 and result.data:
            try:
                backtest_data = result.data
                # run_backtest 返回的 data 为 dict（model_dump），需兼容
                snapshots = backtest_data.get("snapshots", []) if isinstance(backtest_data, dict) else getattr(backtest_data, "snapshots", [])

                def _get(obj, key, default=None):
                    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

                if snapshots:
                    initial_val = _get(snapshots[0], "total_value") or request.initial_cash
                    asset_names_map = _get(backtest_data, "asset_names") or {}

                    # 转换净值曲线
                    equity_curve = [
                        EquityPoint(
                            date=_get(s, "time"),
                            value=_get(s, "total_value"),
                            unit_value=(_get(s, "total_value") or 0) / initial_val if initial_val != 0 else 1.0,
                            cumulative_return=((_get(s, "total_value") or 0) / initial_val - 1) if initial_val != 0 else 0.0,
                            portfolio_volatility=_get(s, "portfolio_volatility"),
                            drawdown=_get(s, "drawdown"),
                            rebalance_type=_get(s, "rebalance_type")
                        )
                        for s in snapshots
                    ]

                    # 转换收益率曲线
                    return_curve = [
                        ReturnPoint(
                            date=_get(s, "time"),
                            daily_return=0.0,
                            cumulative_return=((_get(s, "total_value") or 0) / initial_val - 1) if initial_val != 0 else 0.0
                        )
                        for s in snapshots
                    ]

                    # 转换持仓记录 (只记录调仓日)
                    positions_record = [
                        PositionRecord(
                            date=_get(s, "time"),
                            portfolio_value=_get(s, "total_value"),
                            cash=_get(s, "cash"),
                            rebalance_reason=_get(s, "rebalance_reason"),
                            positions=[
                                AssetPosition(
                                    asset_code=code,
                                    asset_name=asset_names_map.get(code) if asset_names_map else None,
                                    weight=weight,
                                    market_value=(_get(s, "total_value") or 0) * weight
                                )
                                for code, weight in (_get(s, "weights") or {}).items()
                            ]
                        )
                        for s in snapshots if _get(s, "is_rebalance_day")
                    ]

                    # 权重变化记录
                    weight_changes = [
                        WeightChangePoint(
                            date=(_get(s, "time").strftime('%Y-%m-%d') if hasattr(_get(s, "time"), "strftime") else str(_get(s, "time"))[:10]),
                            weights=_get(s, "weights") or {}
                        )
                        for s in snapshots if _get(s, "is_rebalance_day")
                    ]

                    model_result = ModelBacktestResult(
                        total_return=_get(backtest_data, "total_return", 0.0) or 0.0,
                        annual_return=_get(backtest_data, "annual_return", 0.0) or 0.0,
                        annual_volatility=_get(backtest_data, "volatility", 0.0) or 0.0,
                        sharpe_ratio=_get(backtest_data, "sharpe_ratio", 0.0) or 0.0,
                        max_drawdown=_get(backtest_data, "max_drawdown", 0.0) or 0.0,
                        calmar_ratio=_get(backtest_data, "calmar_ratio"),
                        equity_curve=equity_curve,
                        return_curve=return_curve,
                        positions=positions_record,
                        weight_changes=weight_changes,
                        asset_names=asset_names_map,
                        selected_asset_count=_get(backtest_data, "selected_asset_count")
                    )
                    
                    # 转换日期格式
                    start_dt = pd.to_datetime(request.start_date)
                    end_dt = pd.to_datetime(request.end_date)
                    
                    backtest_record = BacktestRecord(
                        model_id=model_id,
                        start_date=start_dt,
                        end_date=end_dt,
                        initial_capital=request.initial_cash,
                        result=model_result,
                        remark=getattr(request, "remark", None) or None
                    )
                    
                    record_id = await model_service.save_backtest_record(backtest_record)
                    # 在响应中返回 record_id 与 remark，便于前端在回测结果区展示分析与记录笔记
                    result_data = result.data.model_dump() if hasattr(result.data, "model_dump") else (result.data if isinstance(result.data, dict) else {})
                    if isinstance(result_data, dict):
                        _ensure_trades_rebalance_labels(result_data)
                        result_data["record_id"] = str(record_id)
                        result_data["remark"] = getattr(request, "remark", None) or ""
                        result_data = _sanitize_dict_for_json(result_data)
                        _apply_snapshot_aggregation(result_data)
                        print(f"[BacktestRecord] 回测记录已保存 model_id={model_id} record_id={record_id} 响应payload_keys={list(result_data.keys())[:15]}")
                        return Response.success(data=result_data, message="回测完成")
                else:
                    # 无 snapshots 时也保存一条最小记录，保证前端始终有 record_id 可编辑备注
                    start_dt = pd.to_datetime(request.start_date)
                    end_dt = pd.to_datetime(request.end_date)
                    _bd = result.data
                    model_result = ModelBacktestResult(
                        total_return=_get(_bd, "total_return", 0.0) or 0.0,
                        annual_return=_get(_bd, "annual_return", 0.0) or 0.0,
                        annual_volatility=_get(_bd, "volatility", 0.0) or 0.0,
                        sharpe_ratio=_get(_bd, "sharpe_ratio", 0.0) or 0.0,
                        max_drawdown=_get(_bd, "max_drawdown", 0.0) or 0.0,
                        calmar_ratio=_get(_bd, "calmar_ratio", None),
                        equity_curve=[],
                        return_curve=[],
                        positions=[],
                        weight_changes=[],
                        asset_names=_get(_bd, "asset_names"),
                        selected_asset_count=_get(_bd, "selected_asset_count"),
                    )
                    backtest_record = BacktestRecord(
                        model_id=model_id,
                        start_date=start_dt,
                        end_date=end_dt,
                        initial_capital=request.initial_cash,
                        result=model_result,
                        remark=getattr(request, "remark", None) or None,
                    )
                    record_id = await model_service.save_backtest_record(backtest_record)
                    result_data = result.data.model_dump() if hasattr(result.data, "model_dump") else (result.data if isinstance(result.data, dict) else {})
                    if isinstance(result_data, dict):
                        _ensure_trades_rebalance_labels(result_data)
                        result_data["record_id"] = str(record_id)
                        result_data["remark"] = getattr(request, "remark", None) or ""
                        result_data = _sanitize_dict_for_json(result_data)
                        _apply_snapshot_aggregation(result_data)
                        print(f"[BacktestRecord] 无snapshots时已保存最小记录 model_id={model_id} record_id={record_id}")
                        return Response.success(data=result_data, message="回测完成")
            except Exception as e:
                # 保存失败时尝试保存一条最小记录，保证前端有关联的 record_id 可编辑备注
                print(f"保存回测记录失败: {str(e)}")
                _out = result.data.model_dump() if hasattr(result.data, "model_dump") else (result.data if isinstance(result.data, dict) else {})
                if isinstance(_out, dict):
                    _ensure_trades_rebalance_labels(_out)
                    _record_id = None
                    try:
                        start_dt = pd.to_datetime(request.start_date)
                        end_dt = pd.to_datetime(request.end_date)
                        _bd = result.data
                        _g = lambda o, k, d=None: o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)
                        minimal_result = ModelBacktestResult(
                            total_return=_g(_bd, "total_return", 0.0) or 0.0,
                            annual_return=_g(_bd, "annual_return", 0.0) or 0.0,
                            annual_volatility=_g(_bd, "volatility", 0.0) or 0.0,
                            sharpe_ratio=_g(_bd, "sharpe_ratio", 0.0) or 0.0,
                            max_drawdown=_g(_bd, "max_drawdown", 0.0) or 0.0,
                            calmar_ratio=_g(_bd, "calmar_ratio", None),
                            equity_curve=[],
                            return_curve=[],
                            positions=[],
                            weight_changes=[],
                            asset_names=_g(_bd, "asset_names"),
                            selected_asset_count=_g(_bd, "selected_asset_count"),
                        )
                        minimal_record = BacktestRecord(
                            model_id=model_id,
                            start_date=start_dt,
                            end_date=end_dt,
                            initial_capital=request.initial_cash,
                            result=minimal_result,
                            remark=getattr(request, "remark", None) or None,
                        )
                        _record_id = await model_service.save_backtest_record(minimal_record)
                        _record_id = str(_record_id) if _record_id else None
                    except Exception as e2:
                        print(f"保存最小回测记录也失败: {str(e2)}")
                    _out["record_id"] = _record_id
                    _out["remark"] = getattr(request, "remark", None) or ""
                    _out = _sanitize_dict_for_json(_out)
                    _apply_snapshot_aggregation(_out)
                    print(f"[BacktestRecord] 保存失败后尝试最小记录 model_id={model_id} record_id={_record_id}")
                    return Response.success(data=_out, message="回测完成")
        # 无 snapshot 或 result 结构不同时，统一返回带 record_id 的 payload，避免前端“未关联回测记录”
        if result and getattr(result, "data", None) is not None:
            result_data = result.data.model_dump() if hasattr(result.data, "model_dump") else (result.data if isinstance(result.data, dict) else {})
            if isinstance(result_data, dict):
                _ensure_trades_rebalance_labels(result_data)
                result_data["record_id"] = None
                result_data["remark"] = getattr(request, "remark", None) or ""
                result_data = _sanitize_dict_for_json(result_data)
                _apply_snapshot_aggregation(result_data)
                print(f"[BacktestRecord] 无snapshot/result分支返回 record_id=None")
                return Response.success(data=result_data, message="回测完成")
        return result
        
    except HTTPException as he:
        raise he
    except ValueError as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"参数错误: {str(e)}")
    except KeyError as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=400, 
            detail=f"策略配置错误: 缺少必需的参数或字段 - {str(e)}"
        )
    except AttributeError as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"策略执行错误: {str(e)}。可能是策略参数配置不正确或策略类实现有问题。"
        )
    except Exception as e:
        traceback.print_exc()
        error_type = type(e).__name__
        error_msg = str(e)
        
        # 提供更详细的错误信息
        detail_msg = (
            f"回测执行失败 ({error_type}): {error_msg}\n\n"
            f"可能的原因：\n"
            f"1. 策略参数配置错误\n"
            f"2. 策略算法实现问题\n"
            f"3. 数据格式不匹配\n"
            f"4. 内存不足或计算超时\n\n"
            f"请检查：\n"
            f"- 策略模型的参数配置是否正确\n"
            f"- 资产代码和日期范围是否有效\n"
            f"- 后端日志中的详细错误堆栈"
        )
        
        raise HTTPException(status_code=500, detail=detail_msg)
