"""策略监控与权重变化编排（自 app/api/strategy_model.py 平移，P9 治理）.

承接两条只读监控链路的编排主体：
- get_model_monitoring_core：已发布策略从建仓日至今的监控回测
  （复用回测引擎与绩效分析，不落库）；
- get_weight_changes_core：最新回测记录的权重变化曲线组装。

依赖方向：本模块只依赖 app.backtesting / app.schemas / app.models，
不 import app.api。路由层保留参数校验与薄委托。
"""
import pandas as pd
from fastapi import HTTPException

from app.schemas.response import Response
from app.schemas.strategy_model import BacktestRecordOut, WeightChangesOut, AssetWeight
from app.models.strategy_model import (
    ModelStatus,
    EquityPoint,
    ReturnPoint,
    WeightChangePoint,
    BacktestResult as ModelBacktestResult,
    BacktestRecord,
    AssetPosition,
    PositionRecord,
    TodayNav,
    TodayPlannedRebalance,
)
from app.backtesting.config import BacktestConfig
from app.backtesting.data_feed import DataFeed
from app.backtesting.runner import RunSpec, run_unified
from app.backtesting.analytics import PerformanceAnalyzer
from app.allocation.services.registry import create_strategy_service_from_database


async def get_model_monitoring_core(
    model_id: str,
    service,
    market_service,
    asset_service,
    use_live_snapshot: bool = False,
):
    """获取已发布策略从建仓日到当前的表现监控信息.

    指标包括：组合净值曲线、累计收益率、年化波动率、最大回撤、夏普比率、资产权重、持仓调整记录等。
    内部复用回测引擎和绩效分析逻辑，仅不落库。
    use_live_snapshot: 实盘监控时使用 live_snapshot 配置，不触发实盘发布。
    """
    # 1. 获取并校验模型
    model = await service.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"策略模型不存在: {model_id}")

    if model.status != ModelStatus.PUBLISHED and not model.live_publish_enabled:
        raise HTTPException(status_code=400, detail="仅支持对已发布或已实盘发布的策略进行监控")

    # 2. 确定建仓日与结束日；实盘监控时使用 live_snapshot 配置
    from datetime import datetime

    if use_live_snapshot and model.live_publish_enabled and model.live_snapshot:
        snap = model.live_snapshot
        asset_codes = snap.get("asset_codes") or model.asset_codes
        parameters = snap.get("parameters") or model.parameters
        rebalance_frequency = snap.get("rebalance_frequency") or model.rebalance_frequency
        if model.live_effective_date:
            start_dt = model.live_effective_date
        else:
            start_dt = model.inception_date or model.published_at or model.created_at
    else:
        asset_codes = model.asset_codes
        parameters = model.parameters
        rebalance_frequency = model.rebalance_frequency
        if model.inception_date:
            start_dt = model.inception_date
        elif model.published_at:
            start_dt = model.published_at
        else:
            start_dt = model.created_at

    start_date_str = start_dt.strftime("%Y%m%d")
    end_dt = datetime.now()
    end_date_str = end_dt.strftime("%Y%m%d")

    # 3. 构造回测配置（尽量复用现有回测逻辑）
    config = BacktestConfig(
        name=f"monitoring_{model_id}",
        thscodes=asset_codes,
        start_date=start_date_str,
        end_date=end_date_str,
        rebalance_freq=rebalance_frequency,
        initial_cash=10_000_000.0,
    )

    # 4. 创建数据源
    data_feed = await DataFeed.from_market_service(
        market_service=market_service,
        config=config,
        lookback_days=500,
        # 面板按 strategy_type 静态解析；不传则策略声明的 get_extra_panels
        # 不生效，依赖面板的策略会拿到空截面
        strategy_type=model.template_code,
    )
    if data_feed.prices.empty:
        raise HTTPException(status_code=400, detail="无法获取历史行情数据，请检查资产代码和日期范围")

    # 5. 创建策略实例（从数据库模板加载）
    strategy_service = await create_strategy_service_from_database(market_service=market_service)
    try:
        strategy_cls = strategy_service.get_strategy_class(model.template_code)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"策略类型不存在: {model.template_code}")

    from app.allocation.builtin_templates import COMPOSITION_DEFAULTS
    strategy_impl = strategy_cls()
    composition = COMPOSITION_DEFAULTS.get(model.template_code, {
        "selector": None, "allocator": model.template_code, "controller": None
    })

    # 6/7. 经唯一引擎入口运行回测引擎（监控视角，默认风控口径）
    result = run_unified(RunSpec(
        config=config,
        data_feed=data_feed,
        allocator=strategy_impl,
        thscodes=asset_codes,
        composition=composition,
        strategy_params=parameters,
    ))

    # 8. 计算绩效指标
    analyzer = PerformanceAnalyzer(risk_free_rate=0.02)
    _model_max_lev = parameters.get("max_leverage") or parameters.get("max_total_leverage")
    _model_max_lev = float(_model_max_lev) if _model_max_lev is not None else None
    performance = analyzer.from_results(result.snapshots, result.trades, max_leverage=_model_max_lev)

    # 9. 构造 BacktestResult 模型（用于输出）
    snapshots = result.snapshots
    if not snapshots:
        raise HTTPException(status_code=400, detail="监控期间无有效交易日")

    initial_val = snapshots[0].total_value or config.initial_cash

    # 计算回撤序列
    from app.analysis.formulas.drawdown import calculate_drawdown_series
    total_values_series = pd.Series([s.total_value for s in snapshots])
    drawdown_series = calculate_drawdown_series(total_values_series) if not total_values_series.empty else pd.Series()

    # 净值曲线
    equity_curve = [
        EquityPoint(
            date=s.time,
            value=s.total_value,
            unit_value=s.total_value / initial_val if initial_val != 0 else 1.0,
            cumulative_return=(s.total_value / initial_val - 1) if initial_val != 0 else 0.0,
            portfolio_volatility=getattr(s, "portfolio_volatility", None),
            drawdown=float(drawdown_series.iloc[i]) if i < len(drawdown_series) else 0.0
        )
        for i, s in enumerate(snapshots)
    ]

    # 收益率曲线（简化：累计收益）
    return_curve = [
        ReturnPoint(
            date=s.time,
            daily_return=0.0,
            cumulative_return=(s.total_value / initial_val - 1) if initial_val != 0 else 0.0,
        )
        for s in snapshots
    ]

    # 持仓记录：只保留调仓日
    positions_record = [
        PositionRecord(
            date=s.time,
            portfolio_value=s.total_value,
            cash=s.cash,
            rebalance_reason=getattr(s, "rebalance_reason", None),
            positions=[
                AssetPosition(
                    asset_code=code,
                    asset_name=None,  # 监控场景下名称可选，如需可通过 asset_service 补全
                    weight=weight,
                    market_value=s.total_value * weight,
                )
                for code, weight in s.weights.items()
            ],
        )
        for s in snapshots
        if s.is_rebalance_day
    ]

    # 权重变化记录
    weight_changes = [
        WeightChangePoint(
            date=s.time.strftime("%Y-%m-%d"),
            weights=s.weights,
        )
        for s in snapshots
        if s.is_rebalance_day
    ]

    # 资产名称映射
    asset_names = {}
    for code in asset_codes:
        info = await asset_service.get_asset_by_code(code)
        if info:
            asset_names[code] = info.name

    # 当日净值、权重、计划调仓
    last_snap = snapshots[-1]
    date_str = last_snap.time.strftime("%Y-%m-%d")
    today_nav = TodayNav(
        date=date_str,
        unit_value=last_snap.total_value / initial_val if initial_val != 0 else 1.0,
        total_value=last_snap.total_value,
    )
    today_weights = dict(last_snap.weights) if last_snap.weights else {}
    today_planned_rebalance = None
    if last_snap.is_rebalance_day and len(snapshots) >= 2:
        prev_snap = snapshots[-2]
        prev_weights = prev_snap.weights or {}
        target_weights = last_snap.weights or {}
        all_codes = set(prev_weights.keys()) | set(target_weights.keys())
        weight_deltas = {c: target_weights.get(c, 0) - prev_weights.get(c, 0) for c in all_codes}
        today_planned_rebalance = TodayPlannedRebalance(
            date=date_str,
            is_rebalance_day=True,
            current_weights=dict(prev_weights),
            target_weights=dict(target_weights),
            weight_deltas={c: d for c, d in weight_deltas.items() if abs(d) > 1e-8},
        )

    model_result = ModelBacktestResult(
        total_return=performance.total_return,
        annual_return=performance.annual_return,
        annual_volatility=performance.annual_volatility,
        sharpe_ratio=performance.sharpe_ratio,
        max_drawdown=performance.max_drawdown,
        calmar_ratio=performance.calmar_ratio,
        annual_return_365=performance.annual_return_365,
        annual_volatility_365=performance.annual_volatility_365,
        sharpe_ratio_365=performance.sharpe_ratio_365,
        calmar_ratio_365=performance.calmar_ratio_365,
        equity_curve=equity_curve,
        return_curve=return_curve,
        positions=positions_record,
        weight_changes=weight_changes,
        asset_names=asset_names,
        today_nav=today_nav,
        today_weights=today_weights,
        today_planned_rebalance=today_planned_rebalance,
    )

    monitor_record = BacktestRecord(
        model_id=model_id,
        start_date=start_dt,
        end_date=end_dt,
        initial_capital=config.initial_cash,
        result=model_result,
    )

    # 构造输出模型（不落库，id 使用占位）
    monitor_out = BacktestRecordOut(
        id="monitoring",
        model_id=model_id,
        start_date=start_dt,
        end_date=end_dt,
        initial_capital=config.initial_cash,
        result=model_result,
        created_at=end_dt,
    )

    return Response.success(data=monitor_out, message="策略监控数据生成成功")


async def get_weight_changes_core(
    model_id: str,
    backtest_service,
    asset_service,
):
    """
    获取模型的权重变化曲线数据
    
    返回数据说明：
    - date: 日期 (YYYY-MM-DD格式)
    - weights: 各资产权重列表
      - asset_code: 资产代码 (如 AAPL, GOOGL)
      - weight: 权重值 (0-1之间的浮点数，表示该资产在组合中的占比)
    
    示例返回：
    [
      {
        "date": "2023-01-01",
        "weights": [
          {
            "asset_code": "AAPL",
            "weight": 0.3
          },
          {
            "asset_code": "GOOGL",
            "weight": 0.4
          },
          {
            "asset_code": "MSFT",
            "weight": 0.3
          }
        ]
      },
      {
        "date": "2023-02-01",
        "weights": [
          {
            "asset_code": "AAPL",
            "weight": 0.25
          },
          {
            "asset_code": "GOOGL",
            "weight": 0.45
          },
          {
            "asset_code": "MSFT",
            "weight": 0.3
          }
        ]
      }
    ]
    """
    # 获取最新的回测记录
    records = await backtest_service.list_backtest_records(model_id=model_id, skip=0, limit=1)
    
    if not records:
        raise HTTPException(status_code=404, detail="未找到回测记录")
    
    latest_record = records[0]
    # 由于BacktestResultOut中的weight_changes是WeightChangePoint格式，我们需要转换为WeightChangesOut格式
    weight_changes_raw = latest_record.result.weight_changes
    
    # 获取资产名称映射，以便填充权重变化中的名称
    asset_names_map = getattr(latest_record.result, 'asset_names', {})
    if not asset_names_map:
        # 如果记录里没有，尝试从资产服务获取（兜底）
        all_codes = set()
        for item in weight_changes_raw:
            if hasattr(item, 'weights'):
                all_codes.update(item.weights.keys())
            elif isinstance(item, dict):
                all_codes.update(item.get('weights', {}).keys())
        
        asset_names_map = {}
        for code in all_codes:
            info = await asset_service.get_asset_by_code(code)
            if info:
                asset_names_map[code] = info.name
    
    # 转换数据格式：从WeightChangePoint对象转换为WeightChangesOut对象
    weight_changes_formatted = []
    for item in weight_changes_raw:
        # 处理兼容性：item 可能是 WeightChangePoint 对象
        if hasattr(item, 'date') and hasattr(item, 'weights'):
            # WeightChangePoint 对象
            date = item.date
            weights_dict = item.weights
        elif isinstance(item, dict):
            # 字典格式（兼容旧数据）
            date = item.get('date', '')
            weights_dict = item.get('weights', {})
        else:
            # 其他格式，跳过
            continue
        
        weights_list = [
            AssetWeight(
                asset_code=code, 
                asset_name=asset_names_map.get(code),
                weight=weight
            )
            for code, weight in weights_dict.items()
        ]
        weight_changes_formatted.append(WeightChangesOut(date=date, weights=weights_list))
    
    return Response.success(data=weight_changes_formatted)
