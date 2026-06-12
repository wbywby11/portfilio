"""
策略类工具 — 原子能力层

提供 6 个策略相关 BaseTool：
- list_strategy_types     列出已注册策略类型
- create_strategy_model   创建策略模型（入库）
- execute_backtest        执行回测并返回净值/权重/波动率三图
- compare_strategies      批量回测对比
- recommend_strategy      基于资产特征推荐策略（启发式）
- compute_weights         单次权重计算（不跑完整回测）

设计规范：
- 仅调用 Service/Engine 层，不做深度业务编排
- 所有工具通过 StrategyModelService / PortfolioService / BacktestEngine
- 文件总行数控制在 1000 行以内（BACKEND 规则）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.chart_builder import ChartBuilder
from app.agent.tools.chart_labels import batch_asset_display_labels
from app.agent.tools.data_analyze_tool import _fetch_price_matrix, _parse_date
from app.agent.tools.validators.data_validator import DataValidator
from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.engine import BacktestEngine, BacktestResult as EngineBacktestResult
from app.backtesting.execution import ExecutionEngine
from app.backtesting.risk import RiskConfig, RiskManager
from app.backtesting.strategy_api import StrategiesWrapper
from app.models.strategy_model import (
    ModelStatus,
    RebalanceFrequency,
    StrategyModel,
)
from app.services.market_service import MarketService
from app.services.strategy_model_service import StrategyModelService
from app.strategies.services.registry import create_strategy_service_from_database

_market_service = MarketService()
_model_service = StrategyModelService()
_data_validator = DataValidator()


# ═══════════════════════════════════════════════════════════════
#  策略元数据（已注册内置策略的中文说明）
# ═══════════════════════════════════════════════════════════════

_STRATEGY_CATALOG: List[Dict[str, Any]] = [
    {
        "template_code": "risk_parity",
        "name": "风险平价",
        "category": "大类资产配置",
        "description": "让各资产对组合风险的贡献相等，适合多资产分散配置。",
        "suitable_assets": "3 只及以上低相关度资产",
        "default_params": {"lookback_days": 260},
    },
    {
        "template_code": "cso",
        "name": "协方差-夏普优化",
        "category": "大类资产配置",
        "description": "以夏普比率最大化为目标的协方差优化，兼顾收益与波动。",
        "suitable_assets": "3-8 只有稳定预期收益的资产",
        "default_params": {"lookback_days": 260},
    },
    {
        "template_code": "risk_budget",
        "name": "风险预算",
        "category": "大类资产配置",
        "description": "按用户设定的风险预算分配权重，强调主观风险分配。",
        "suitable_assets": "2-6 只资产，需配合自定义预算",
        "default_params": {"lookback_days": 260},
    },
    {
        "template_code": "risk_budget_target_vol",
        "name": "风险预算-目标波动率",
        "category": "大类资产配置",
        "description": "风险预算基础上追加目标波动率约束，并支持波动率重置触发。",
        "suitable_assets": "4-8 只资产，适合稳健型组合",
        "default_params": {"lookback_days": 260, "target_vol": 0.08, "vol_reset_threshold": 0.06},
    },
    {
        "template_code": "factor_rp",
        "name": "因子风险平价",
        "category": "大类资产配置",
        "description": "基于因子暴露度的风险平价，适合风格因子组合。",
        "suitable_assets": "风格/行业因子类资产",
        "default_params": {"lookback_days": 260},
    },
    {
        "template_code": "mean_variance",
        "name": "均值方差优化",
        "category": "大类资产配置",
        "description": "经典 Markowitz 有效前沿组合，最大化给定风险下收益。",
        "suitable_assets": "3-10 只资产，要求历史数据充足",
        "default_params": {"lookback_days": 260},
    },
    {
        "template_code": "manual_allocation",
        "name": "主观配置",
        "category": "大类资产配置",
        "description": "按用户预设权重配置，支持指定调仓日。",
        "suitable_assets": "任意资产，需人工输入权重",
        "default_params": {},
    },
    {
        "template_code": "etf_cycle_rotation",
        "name": "ETF 周期轮动",
        "category": "ETF 策略",
        "description": (
            "ETF 行业/风格轮动，支持四种子策略："
            "volatility(波动率)/return_deviation(收益+乖离率)/hybrid(混合因子)/breakout(强势突破)。"
        ),
        "suitable_assets": "10 只以上 ETF（基金类资产）",
        "default_params": {"sub_strategy": "volatility", "top_n": 5},
    },
]

_STRATEGY_CODES = {s["template_code"] for s in _STRATEGY_CATALOG}


def _strategy_display_name(template_code: str) -> str:
    """策略 template_code → 中文名（图表系列/表格展示）。"""
    for row in _STRATEGY_CATALOG:
        if row["template_code"] == template_code:
            return row["name"]
    return template_code


# ═══════════════════════════════════════════════════════════════
#  共享辅助：运行一次回测（供 execute_backtest / compare_strategies 复用）
# ═══════════════════════════════════════════════════════════════

async def _run_single_backtest(
    *,
    name: str,
    asset_codes: List[str],
    template_code: str,
    start_date: str,
    end_date: str,
    initial_cash: float,
    rebalance_freq: str,
    strategy_params: Optional[Dict[str, Any]] = None,
    lookback_days: int = 500,
) -> EngineBacktestResult:
    """组装 BacktestEngine 并执行一次回测，返回原生 BacktestResult。"""
    config = BacktestConfig(
        name=name,
        thscodes=list(asset_codes),
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        rebalance_freq=rebalance_freq,
        initial_cash=float(initial_cash),
    )

    data_feed = await DataFeed.from_market_service(
        _market_service, config, lookback_days=lookback_days,
    )

    strategy_service = await create_strategy_service_from_database(_market_service)
    strategy_cls = strategy_service.get_strategy_class(template_code)
    strategy = StrategiesWrapper(
        strategy_impl=strategy_cls(),
        params=strategy_params or {},
    )

    risk_manager = RiskManager(RiskConfig())
    execution_engine = ExecutionEngine(config)
    engine = BacktestEngine(config, data_feed, strategy, risk_manager, execution_engine)
    return engine.run()


def _summarize_snapshots(
    snapshots: list, initial_cash: float,
) -> Dict[str, Any]:
    """从 snapshots 计算核心指标。"""
    if not snapshots:
        return {
            "total_return": 0.0, "annual_return": 0.0,
            "annual_volatility": 0.0, "sharpe": 0.0, "max_drawdown": 0.0,
        }

    values = pd.Series(
        [s.total_value for s in snapshots],
        index=[pd.Timestamp(s.time) for s in snapshots],
    )
    unit_nav = values / float(initial_cash)
    daily_ret = unit_nav.pct_change().dropna()

    total_return = float(unit_nav.iloc[-1] - 1.0)
    n_days = max(len(unit_nav) - 1, 1)
    annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0.0
    annual_vol = float(daily_ret.std() * (252 ** 0.5)) if len(daily_ret) else 0.0
    sharpe = float(annual_return / annual_vol) if annual_vol > 1e-8 else 0.0

    peak = unit_nav.cummax()
    drawdown = (unit_nav - peak) / peak
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    return {
        "total_return": round(total_return, 6),
        "annual_return": round(float(annual_return), 6),
        "annual_volatility": round(annual_vol, 6),
        "sharpe": round(sharpe, 6),
        "max_drawdown": round(max_drawdown, 6),
    }


def _downsample_chart_data(data_points: list, max_points: int = 500) -> tuple:
    """对图表数据点进行均匀降采样，保留首尾。"""
    if len(data_points) <= max_points:
        return data_points, False
    import numpy as np
    indices = np.linspace(0, len(data_points) - 1, max_points, dtype=int)
    sampled = [data_points[int(i)] for i in indices]
    return sampled, True


def _build_backtest_charts(
    title_prefix: str,
    snapshots: list,
    initial_cash: float,
    code_labels: Optional[Dict[str, str]] = None,
    max_chart_points: int = 500,
) -> tuple:
    """根据 snapshots 构建三图：净值 / 权重堆叠面积 / 滚动波动率。

    Returns:
        (charts, truncated, original_points)
    """
    charts: List[Dict[str, Any]] = []
    code_labels = code_labels or {}
    if not snapshots:
        return charts, False, 0

    original_points = len(snapshots)
    dates = [pd.Timestamp(s.time).strftime("%Y-%m-%d") for s in snapshots]

    # 降采样：先计算统一的采样索引，对所有序列复用
    truncated = False
    if len(dates) > max_chart_points:
        import numpy as np
        indices = np.linspace(0, len(dates) - 1, max_chart_points, dtype=int).tolist()
        truncated = True
    else:
        indices = list(range(len(dates)))

    dates = [dates[i] for i in indices]

    # 1) 净值曲线
    unit_nav = [round(s.total_value / float(initial_cash), 6) for s in snapshots]
    unit_nav = [unit_nav[i] for i in indices]
    charts.append(ChartBuilder.build_line(
        title=f"{title_prefix} - 净值曲线",
        dates=dates,
        series_list=[{"name": "单位净值", "data": unit_nav}],
        y_name="净值",
    ))

    # 2) 权重堆叠面积图（所有资产）：图例用「资产名称（代码）」
    asset_codes: List[str] = []
    for snap in snapshots:
        for code in snap.weights.keys():
            if code not in asset_codes:
                asset_codes.append(code)
    weight_series = []
    for code in asset_codes:
        data = [round(float(s.weights.get(code, 0.0)) * 100.0, 4) for s in snapshots]
        data = [data[i] for i in indices]
        lbl = code_labels.get(code, code)
        weight_series.append({"name": lbl, "data": data})
    if weight_series:
        charts.append(ChartBuilder.build_area_stack(
            title=f"{title_prefix} - 持仓权重变化",
            dates=dates,
            series_list=weight_series,
            y_max=100,
        ))

    # 3) 滚动波动率（portfolio_volatility）
    vol_data = [
        round(float(s.portfolio_volatility), 6) if s.portfolio_volatility is not None else None
        for s in snapshots
    ]
    vol_data = [vol_data[i] for i in indices]
    if any(v is not None for v in vol_data):
        charts.append(ChartBuilder.build_line(
            title=f"{title_prefix} - 滚动波动率监控",
            dates=dates,
            series_list=[{"name": "组合波动率", "data": vol_data}],
            y_name="年化波动率",
        ))

    return charts, truncated, original_points


# ═══════════════════════════════════════════════════════════════
#  Tool 1: list_strategy_types
# ═══════════════════════════════════════════════════════════════

class ListStrategyTypesTool(BaseTool):
    """列出系统可用的策略类型。"""

    name = "list_strategy_types"
    description = (
        "列出系统中所有已注册的策略类型，返回每个策略的代码(template_code)、"
        "中文名、分类、适用场景、默认参数。用户询问'有哪些策略'时调用。"
    )
    category = "strategy"
    tags = ["策略", "目录", "查询"]
    parameters = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "筛选分类：大类资产配置 / ETF策略。不传返回全部。",
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs) -> dict:
        category = kwargs.get("category")
        items = _STRATEGY_CATALOG
        if category:
            items = [s for s in items if s["category"] == category]
        summary = f"共 {len(items)} 种策略可用。"
        result = ToolResult.success(
            data={"strategies": items},
            summary=summary,
            record_count=len(items),
        )
        return self.attach_lineage(
            result,
            tables=["<static_catalog>"],
            domains=["strategy"],
            fields={"<static_catalog>": ["template_code", "category", "name", "default_params"]},
            records_returned=len(items),
            query_operation="list_strategy_types",
            note="本工具返回静态策略目录，不访问业务表",
        )


# ═══════════════════════════════════════════════════════════════
#  Tool 2: create_strategy_model
# ═══════════════════════════════════════════════════════════════

class CreateStrategyModelTool(BaseTool):
    """创建策略模型并持久化。"""

    name = "create_strategy_model"
    description = (
        "创建一个策略模型并保存到系统。需要指定策略类型(template_code)、"
        "资产代码列表、调仓频率、策略参数。返回 model_id 用于后续回测或组合创建。"
    )
    category = "strategy"
    tags = ["策略", "模型", "创建"]
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "模型名称"},
            "template_code": {
                "type": "string",
                "description": "策略模板代码：risk_parity / cso / risk_budget / "
                               "risk_budget_target_vol / factor_rp / mean_variance / "
                               "manual_allocation / etf_cycle_rotation",
            },
            "asset_codes": {
                "type": "array", "items": {"type": "string"},
                "description": "资产代码列表，如 ['SH000300','SPX','GLD']",
            },
            "rebalance_frequency": {
                "type": "string",
                "description": "调仓频率：日/周/月/季/年，默认'月'",
            },
            "parameters": {
                "type": "object",
                "description": "策略参数字典，不同策略参数不同",
            },
            "description": {"type": "string", "description": "模型描述（可选）"},
        },
        "required": ["name", "template_code", "asset_codes"],
    }

    async def execute(self, **kwargs) -> dict:
        name = kwargs.get("name", "").strip()
        template_code = kwargs.get("template_code", "").strip()
        asset_codes = kwargs.get("asset_codes") or []
        if not name or not template_code or not asset_codes:
            return ToolResult.error("必须提供 name / template_code / asset_codes")
        if template_code not in _STRATEGY_CODES:
            return ToolResult.error(
                f"未知策略类型: {template_code}，请先调用 list_strategy_types 查看可用策略"
            )

        rebal = kwargs.get("rebalance_frequency") or "月"
        params = kwargs.get("parameters") or {}

        try:
            model = StrategyModel(
                name=name,
                template_code=template_code,
                description=kwargs.get("description"),
                asset_codes=list(asset_codes),
                parameters=params,
                rebalance_frequency=rebal,
                status=ModelStatus.DRAFT,
            )
            model_id = await _model_service.create_model(model)
            return ToolResult.success(
                data={
                    "model_id": model_id,
                    "name": name,
                    "template_code": template_code,
                    "asset_codes": list(asset_codes),
                    "rebalance_frequency": rebal,
                },
                summary=f"策略模型 '{name}' 创建成功，model_id={model_id}",
                record_count=1,
            )
        except Exception as e:
            logger.error("[CreateStrategyModelTool] 创建失败: {}", e)
            return ToolResult.error(f"创建策略模型失败: {e}")


# ═══════════════════════════════════════════════════════════════
#  Tool 3: execute_backtest
# ═══════════════════════════════════════════════════════════════

_FREQ_MAP = {
    "日": "daily", "周": "weekly", "月": "monthly",
    "季": "quarterly", "年": "yearly",
    "daily": "daily", "weekly": "weekly", "monthly": "monthly",
    "quarterly": "quarterly", "yearly": "yearly", "month_end": "month_end",
}


class ExecuteBacktestTool(BaseTool):
    """执行策略回测，返回净值/权重/波动率三图与核心指标。"""

    name = "execute_backtest"
    description = (
        "执行策略回测。可通过 model_id 使用已有策略模型，或直接传入 template_code+asset_codes。"
        "返回核心绩效指标（年化收益、波动率、夏普、最大回撤）以及三张图："
        "净值曲线、持仓权重变化（堆叠面积图）、滚动波动率监控。"
    )
    category = "backtest"
    tags = ["策略", "回测", "净值", "权重", "波动率"]
    parameters = {
        "type": "object",
        "properties": {
            "model_id": {"type": "string", "description": "已有策略模型 ID（优先使用）"},
            "template_code": {"type": "string", "description": "策略模板代码（未提供 model_id 时必填）"},
            "asset_codes": {
                "type": "array", "items": {"type": "string"},
                "description": "资产代码列表（未提供 model_id 时必填）",
            },
            "start_date": {"type": "string", "description": "回测开始日期 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "回测结束日期 YYYY-MM-DD"},
            "initial_capital": {"type": "number", "description": "初始资金，默认 1000 万"},
            "rebalance_frequency": {"type": "string", "description": "调仓频率：日/周/月/季/年"},
            "strategy_params": {"type": "object", "description": "策略参数（覆盖模型默认参数）"},
        },
        "required": [],
    }

    async def execute(self, **kwargs) -> dict:
        try:
            cfg = await self._resolve_config(kwargs)
            if isinstance(cfg, dict) and "error" in cfg:
                return ToolResult.error(cfg["error"])

            result = await _run_single_backtest(
                name=cfg["name"],
                asset_codes=cfg["asset_codes"],
                template_code=cfg["template_code"],
                start_date=cfg["start_date"],
                end_date=cfg["end_date"],
                initial_cash=cfg["initial_cash"],
                rebalance_freq=cfg["rebalance_freq"],
                strategy_params=cfg["strategy_params"],
            )

            metrics = _summarize_snapshots(result.snapshots, cfg["initial_cash"])
            label_codes: list[str] = list(dict.fromkeys(list(cfg["asset_codes"]) or []))
            for s in result.snapshots:
                for k in getattr(s, "weights", {}).keys():
                    if k not in label_codes:
                        label_codes.append(k)
            chart_labels_map = await batch_asset_display_labels(label_codes)
            charts, chart_truncated, original_chart_points = _build_backtest_charts(
                title_prefix=cfg["name"],
                snapshots=result.snapshots,
                initial_cash=cfg["initial_cash"],
                code_labels=chart_labels_map,
            )

            metrics_table = (
                "| 指标 | 数值 |\n"
                "| --- | --- |\n"
                f"| 累计收益 | {metrics['total_return']*100:.2f}% |\n"
                f"| 年化收益 | {metrics['annual_return']*100:.2f}% |\n"
                f"| 年化波动 | {metrics['annual_volatility']*100:.2f}% |\n"
                f"| 夏普比率 | {metrics['sharpe']:.2f} |\n"
                f"| 最大回撤 | {metrics['max_drawdown']*100:.2f}% |"
            )
            period_desc = f"{cfg['start_date']} ~ {cfg['end_date']}"
            assets_desc = "、".join(
                chart_labels_map.get(c, c) for c in cfg["asset_codes"]
            )
            summary_text = (
                f"**{cfg['name']}** 回测完成\n\n"
                f"- 区间：{period_desc}\n"
                f"- 资产：{assets_desc}\n"
                f"- 初始资金：{cfg['initial_cash']:,.0f}\n\n"
                f"**核心绩效指标**\n\n{metrics_table}"
            )
            result_data = {
                    "name": cfg["name"],
                    "template_code": cfg["template_code"],
                    "asset_codes": cfg["asset_codes"],
                    "start_date": cfg["start_date"],
                    "end_date": cfg["end_date"],
                    "initial_capital": cfg["initial_cash"],
                    "metrics": metrics,
                    "metrics_table": metrics_table,
                    "snapshot_count": len(result.snapshots),
                    "trade_count": len(result.trades),
            }
            if chart_truncated:
                result_data["_truncated"] = True
                result_data["_original_points"] = original_chart_points

            # 溯源标记：构建 traceable_assets
            try:
                traceable_assets = []
                for code in cfg["asset_codes"]:
                    info = await _data_validator.validate_asset_exists(code)
                    if info.get("exists"):
                        traceable_assets.append({"code": code, "name": info.get("name", code), "has_kline": True})
                    else:
                        traceable_assets.append({"code": code, "name": code, "has_kline": False})
                result_data["traceable_assets"] = traceable_assets
            except Exception as te:
                logger.warning("[ExecuteBacktestTool] traceable_assets 构建失败(non-blocking): {}", te)

            return ToolResult.success(
                data=result_data,
                charts=charts,
                summary=summary_text,
                record_count=len(result.snapshots),
            )
        except Exception as e:
            logger.error("[ExecuteBacktestTool] 回测失败: {}", e)
            return ToolResult.error(f"回测执行失败: {e}")

    async def _resolve_config(self, kwargs: dict) -> dict:
        """整合参数：优先 model_id，否则使用内联配置。"""
        model_id = kwargs.get("model_id")
        if model_id:
            model = await _model_service.get_model(model_id)
            if not model:
                return {"error": f"未找到策略模型: {model_id}"}
            name = f"{model.name}_回测"
            template_code = model.template_code
            asset_codes = list(model.asset_codes)
            rebal = _FREQ_MAP.get(model.rebalance_frequency, "monthly")
            strategy_params = dict(model.parameters or {})
            if kwargs.get("strategy_params"):
                strategy_params.update(kwargs["strategy_params"])
        else:
            template_code = (kwargs.get("template_code") or "").strip()
            asset_codes = kwargs.get("asset_codes") or []
            if not template_code or not asset_codes:
                return {"error": "必须提供 model_id 或 (template_code + asset_codes)"}
            if template_code not in _STRATEGY_CODES:
                return {"error": f"未知策略类型: {template_code}"}
            name = kwargs.get("name") or f"{template_code}_回测"
            rebal = _FREQ_MAP.get(
                kwargs.get("rebalance_frequency") or "月", "monthly",
            )
            strategy_params = kwargs.get("strategy_params") or {}

        end_date = kwargs.get("end_date") or datetime.now().strftime("%Y-%m-%d")
        # 默认回测区间：近3年
        if kwargs.get("start_date"):
            start_date = kwargs["start_date"]
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_date = end_dt.replace(year=end_dt.year - 3).strftime("%Y-%m-%d")

        return {
            "name": name,
            "template_code": template_code,
            "asset_codes": asset_codes,
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": float(kwargs.get("initial_capital") or 10_000_000.0),
            "rebalance_freq": rebal,
            "strategy_params": strategy_params,
        }


# ═══════════════════════════════════════════════════════════════
#  Tool 4: compare_strategies
# ═══════════════════════════════════════════════════════════════

class CompareStrategiesTool(BaseTool):
    """批量回测多个策略并对比核心指标。"""

    name = "compare_strategies"
    description = (
        "对同一组资产运行多个策略并对比核心指标。返回对比表格（Markdown）"
        "和净值叠加图。适合用户要求'策略对比'或'哪个策略最好'的场景。"
    )
    category = "backtest"
    tags = ["策略", "对比", "回测"]
    parameters = {
        "type": "object",
        "properties": {
            "asset_codes": {
                "type": "array", "items": {"type": "string"},
                "description": "资产代码列表（所有策略共用）",
            },
            "template_codes": {
                "type": "array", "items": {"type": "string"},
                "description": "待对比的策略模板代码列表，如 ['risk_parity','mean_variance']",
            },
            "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
            "initial_capital": {"type": "number", "description": "初始资金，默认 1000 万"},
            "rebalance_frequency": {"type": "string", "description": "调仓频率，默认'月'"},
        },
        "required": ["asset_codes", "template_codes"],
    }

    async def execute(self, **kwargs) -> dict:
        asset_codes = kwargs.get("asset_codes") or []
        template_codes = kwargs.get("template_codes") or []
        if not asset_codes or not template_codes:
            return ToolResult.error("必须提供 asset_codes 和 template_codes")
        unknown = [c for c in template_codes if c not in _STRATEGY_CODES]
        if unknown:
            return ToolResult.error(f"未知策略类型: {unknown}")

        initial_cash = float(kwargs.get("initial_capital") or 10_000_000.0)
        rebal = _FREQ_MAP.get(kwargs.get("rebalance_frequency") or "月", "monthly")
        end_date = kwargs.get("end_date") or datetime.now().strftime("%Y-%m-%d")
        if kwargs.get("start_date"):
            start_date = kwargs["start_date"]
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_date = end_dt.replace(year=end_dt.year - 3).strftime("%Y-%m-%d")

        rows: List[Dict[str, Any]] = []
        nav_series_list: List[Dict[str, Any]] = []
        all_dates: List[str] = []

        for tpl in template_codes:
            try:
                result = await _run_single_backtest(
                    name=f"{tpl}_对比",
                    asset_codes=asset_codes,
                    template_code=tpl,
                    start_date=start_date,
                    end_date=end_date,
                    initial_cash=initial_cash,
                    rebalance_freq=rebal,
                    strategy_params=None,
                )
                metrics = _summarize_snapshots(result.snapshots, initial_cash)
                dates = [pd.Timestamp(s.time).strftime("%Y-%m-%d") for s in result.snapshots]
                if len(dates) > len(all_dates):
                    all_dates = dates
                nav_data = [
                    round(s.total_value / initial_cash, 6) for s in result.snapshots
                ]
                nav_series_list.append({"name": _strategy_display_name(tpl), "data": nav_data})
                rows.append({"template_code": tpl, **metrics})
            except Exception as e:
                logger.error("[CompareStrategiesTool] {} 回测失败: {}", tpl, e)
                rows.append({"template_code": tpl, "error": str(e)})

        # 构造对比表格
        table_lines = [
            "| 策略 | 累计收益 | 年化收益 | 年化波动 | 夏普 | 最大回撤 |",
            "|------|----------|----------|----------|------|----------|",
        ]
        for r in rows:
            if "error" in r:
                table_lines.append(
                    f"| {_strategy_display_name(r['template_code'])} | 失败 | - | - | - | - |"
                )
            else:
                table_lines.append(
                    f"| {_strategy_display_name(r['template_code'])} "
                    f"| {r['total_return']*100:.2f}% "
                    f"| {r['annual_return']*100:.2f}% "
                    f"| {r['annual_volatility']*100:.2f}% "
                    f"| {r['sharpe']:.2f} "
                    f"| {r['max_drawdown']*100:.2f}% |"
                )
        comparison_table = "\n".join(table_lines)

        # 确定最优策略：基于夏普比率排序（排除失败的策略）
        best_strategy: Optional[Dict[str, str]] = None
        valid_rows = [r for r in rows if "error" not in r]
        if valid_rows:
            best_row = max(valid_rows, key=lambda r: r.get("sharpe", float("-inf")))
            best_strategy = {
                "strategy_type": best_row["template_code"],
                "reason": f"夏普比率最高（{best_row['sharpe']:.2f}）",
            }

        # 降采样图表数据
        compare_truncated = False
        original_compare_points = len(all_dates)
        if all_dates and len(all_dates) > 500:
            all_dates, compare_truncated = _downsample_chart_data(all_dates, 500)
            for series in nav_series_list:
                series["data"], _ = _downsample_chart_data(series["data"], 500)

        charts = []
        if nav_series_list and all_dates:
            charts.append(ChartBuilder.build_line(
                title="策略净值对比",
                dates=all_dates,
                series_list=nav_series_list,
                y_name="单位净值",
            ))

        result_data: Dict[str, Any] = {
            "comparison_table": comparison_table,
            "rows": rows,
            "asset_codes": asset_codes,
            "start_date": start_date,
            "end_date": end_date,
        }
        if best_strategy:
            result_data["best_strategy"] = best_strategy
        if compare_truncated:
            result_data["_truncated"] = True
            result_data["_original_points"] = original_compare_points

        # 溯源标记：构建 traceable_assets
        try:
            traceable_assets = []
            for code in asset_codes:
                info = await _data_validator.validate_asset_exists(code)
                if info.get("exists"):
                    traceable_assets.append({"code": code, "name": info.get("name", code), "has_kline": True})
                else:
                    traceable_assets.append({"code": code, "name": code, "has_kline": False})
            result_data["traceable_assets"] = traceable_assets
        except Exception as te:
            logger.warning("[CompareStrategiesTool] traceable_assets 构建失败(non-blocking): {}", te)

        return ToolResult.success(
            data=result_data,
            charts=charts,
            summary=f"已对比 {len(template_codes)} 个策略。",
            record_count=len(rows),
        )


# ═══════════════════════════════════════════════════════════════
#  Tool 5: recommend_strategy
# ═══════════════════════════════════════════════════════════════

class RecommendStrategyTool(BaseTool):
    """根据资产特征推荐合适的策略。"""

    name = "recommend_strategy"
    description = (
        "基于资产数量、平均相关度等特征推荐合适的策略类型。"
        "返回推荐列表和 next_step.suggested_params（可直接喂给 compare_strategies）。"
    )
    category = "strategy"
    tags = ["策略", "推荐"]
    parameters = {
        "type": "object",
        "properties": {
            "asset_codes": {
                "type": "array", "items": {"type": "string"},
                "description": "候选资产代码列表",
            },
            "start_date": {"type": "string", "description": "用于评估相关度的起始日 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "用于评估相关度的结束日 YYYY-MM-DD"},
        },
        "required": ["asset_codes"],
    }

    async def execute(self, **kwargs) -> dict:
        asset_codes = kwargs.get("asset_codes") or []
        if not asset_codes:
            return ToolResult.error("必须提供 asset_codes")

        # 启发式：基于资产数量 + 平均相关性 + 是否基金类
        n = len(asset_codes)
        avg_corr: Optional[float] = None
        try:
            prices = await _fetch_price_matrix(
                asset_codes,
                kwargs.get("start_date"),
                kwargs.get("end_date"),
            )
            if not prices.empty and prices.shape[1] >= 2:
                rets = prices.pct_change().dropna()
                corr = rets.corr()
                # 提取上三角（不含对角）的均值
                import numpy as np
                mask = np.triu(np.ones(corr.shape, dtype=bool), k=1)
                vals = corr.values[mask]
                if vals.size > 0:
                    avg_corr = float(np.nanmean(vals))
        except Exception as e:
            logger.warning("[RecommendStrategyTool] 相关性评估失败，降级推荐: {}", e)

        recommendations: List[Dict[str, Any]] = []
        if n >= 10:
            # ETF 类资产较多，倾向 ETF 轮动
            recommendations.append({
                "template_code": "etf_cycle_rotation",
                "reason": f"资产数 {n}≥10，适合 ETF 周期轮动",
            })
        if n >= 3:
            if avg_corr is not None and avg_corr < 0.5:
                recommendations.append({
                    "template_code": "risk_parity",
                    "reason": f"平均相关度 {avg_corr:.2f}<0.5，风险平价效果稳健",
                })
            recommendations.append({
                "template_code": "risk_budget_target_vol",
                "reason": "目标波动率约束，适合稳健组合",
            })
            recommendations.append({
                "template_code": "mean_variance",
                "reason": "均值方差优化，历史数据充足时表现良好",
            })
        if n < 3 or not recommendations:
            recommendations.append({
                "template_code": "manual_allocation",
                "reason": f"资产数 {n} 偏少，建议主观配置",
            })

        # 去重保留顺序
        seen = set()
        uniq: List[Dict[str, Any]] = []
        for r in recommendations:
            if r["template_code"] not in seen:
                seen.add(r["template_code"])
                uniq.append(r)
        recommendations = uniq[:4]

        # 下一步建议：自动喂给 compare_strategies
        next_step = {
            "action": "compare_strategies",
            "suggested_params": {
                "asset_codes": asset_codes,
                "template_codes": [r["template_code"] for r in recommendations],
                "start_date": kwargs.get("start_date"),
                "end_date": kwargs.get("end_date"),
            },
        }

        summary = f"基于 {n} 只资产"
        if avg_corr is not None:
            summary += f"（平均相关度 {avg_corr:.2f}）"
        summary += f"，推荐 {len(recommendations)} 个候选策略。"

        return ToolResult.success(
            data={
                "asset_count": n,
                "avg_correlation": round(avg_corr, 4) if avg_corr is not None else None,
                "recommendations": recommendations,
                "next_step": next_step,
            },
            summary=summary,
            record_count=len(recommendations),
        )


# ═══════════════════════════════════════════════════════════════
#  Tool 6: compute_weights
# ═══════════════════════════════════════════════════════════════

class ComputeWeightsTool(BaseTool):
    """计算策略在指定截面日的目标权重（不跑完整回测）。"""

    name = "compute_weights"
    description = (
        "在指定截面日基于历史价格数据计算策略目标权重（单次计算，不跑回测）。"
        "适合'当前应该持有什么权重'、'给出某日目标仓位'类问题。"
    )
    category = "strategy"
    tags = ["策略", "权重", "截面"]
    parameters = {
        "type": "object",
        "properties": {
            "template_code": {"type": "string", "description": "策略模板代码"},
            "asset_codes": {
                "type": "array", "items": {"type": "string"},
                "description": "资产代码列表",
            },
            "as_of_date": {"type": "string", "description": "截面日期 YYYY-MM-DD，默认今天"},
            "lookback_days": {"type": "integer", "description": "历史数据窗口，默认 260（约1年）"},
            "strategy_params": {"type": "object", "description": "策略参数"},
        },
        "required": ["template_code", "asset_codes"],
    }

    async def execute(self, **kwargs) -> dict:
        template_code = (kwargs.get("template_code") or "").strip()
        asset_codes = kwargs.get("asset_codes") or []
        if not template_code or not asset_codes:
            return ToolResult.error("必须提供 template_code 和 asset_codes")
        if template_code not in _STRATEGY_CODES:
            return ToolResult.error(f"未知策略类型: {template_code}")

        lookback_days = int(kwargs.get("lookback_days") or 260)
        as_of_str = kwargs.get("as_of_date") or datetime.now().strftime("%Y-%m-%d")
        try:
            as_of = pd.Timestamp(as_of_str)
        except Exception:
            return ToolResult.error(f"as_of_date 格式错误: {as_of_str}")

        start_dt = as_of - pd.Timedelta(days=int(lookback_days * 1.5) + 30)
        start_str = start_dt.strftime("%Y-%m-%d")

        prices = await _fetch_price_matrix(asset_codes, start_str, as_of_str)
        if prices.empty:
            return ToolResult.error("未获取到价格数据")

        try:
            strategy_service = await create_strategy_service_from_database(_market_service)
            strategy_cls = strategy_service.get_strategy_class(template_code)
            wrapper = StrategiesWrapper(
                strategy_impl=strategy_cls(),
                params=kwargs.get("strategy_params") or {},
            )
            signal = wrapper.generate_target_weights(prices, as_of)
            weights = {
                code: round(float(w), 6)
                for code, w in signal.target_weights.items()
                if abs(float(w)) > 1e-8
            }
        except Exception as e:
            logger.error("[ComputeWeightsTool] 权重计算失败: {}", e)
            return ToolResult.error(f"权重计算失败: {e}")

        w_labels = await batch_asset_display_labels(list(weights.keys()))
        charts = [ChartBuilder.build_pie(
            title=f"{_strategy_display_name(template_code)} @ {as_of_str} 权重分配",
            data_items=[
                {"name": w_labels.get(code, code), "value": round(w * 100, 4)}
                for code, w in weights.items()
            ],
        )]

        return ToolResult.success(
            data={
                "template_code": template_code,
                "as_of_date": as_of_str,
                "weights": weights,
                "weight_sum": round(sum(weights.values()), 6),
            },
            charts=charts,
            summary=f"在 {as_of_str} 计算得到 {len(weights)} 项权重。",
            record_count=len(weights),
        )
