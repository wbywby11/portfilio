"""四链路执行器：直调 API / 服务层函数（import FastAPI 依赖树，不起 HTTP）。

| 链路 | 内容 | 直调入口 |
|------|------|---------|
| C1a  | 组合回测（portfolios 集合文档） | run_portfolio_backtest_by_id |
| C1b  | 组合回测（组合模型，固定权重） | run_portfolio_backtest_api |
| C2   | 模型快捷回测 | run_backtest_by_model |
| C3   | 四象限组合回测 + get_param_schema | run_portfolio_backtest_api / QuadrantWeightModel |
| C4   | 监控五读端 | MonitorService.get_nav_history / get_performance /
|      |          | get_signal_status / get_positions / get_daily_attribution |
| C4b  | 实盘互通 | eligible-for-monitor 端点函数 + get_model（含 live 字段） |

口径说明：
- C4 中 get_performance / get_signal_status / get_positions 基于监控推演的
  「最新数据日期」状态——导入新行情后这三项会真实变化，属预期行为，
  需重新 rebase（不做切片伪装稳定）；
- get_nav_history 按固定 end_date 切片、get_daily_attribution 取固定日期，
  行情追加不影响；
- C4b 仅保留 `_regr_` 前缀条目，生产模型的增减不影响基线。
"""
from __future__ import annotations

from typing import Any, Dict

from tests.regression import fixture


async def boot() -> None:
    """复现 main.py lifespan 的直调前提：连库 + 初始化内置模板。"""
    from app.config.database import Database
    from app.services.template_init_service import init_builtin_templates

    Database.connect()
    await init_builtin_templates()


async def run_all(ids: Dict[str, str]) -> Dict[str, Any]:
    """依次执行 C1~C4b 全部链路，输出统一为 jsonable dict。

    Args:
        ids: fixture.create() 返回的 id 映射

    Returns:
        {链路名: jsonable 输出} 字典
    """
    from fastapi.encoders import jsonable_encoder

    from app.api.backtests import (
        BacktestByModelRequest,
        PortfolioBacktestRequest,
        PortfolioByIdBacktestRequest,
        get_asset_service,
        get_market_service,
        run_backtest_by_model,
        run_portfolio_backtest_api,
        run_portfolio_backtest_by_id,
    )

    out: Dict[str, Any] = {}

    # ---- C1a：组合回测（portfolios 文档，固定权重）----
    resp = await run_portfolio_backtest_by_id(
        ids["portfolio_doc"],
        PortfolioByIdBacktestRequest(start_date=fixture.START, end_date=fixture.END),
    )
    out["C1a_portfolio_by_id"] = jsonable_encoder(resp)

    # ---- C1b：组合回测（组合模型，固定权重）----
    resp = await run_portfolio_backtest_api(
        ids["portfolio_fixed"],
        PortfolioBacktestRequest(start_date=fixture.START, end_date=fixture.END),
    )
    out["C1b_portfolio_by_model"] = jsonable_encoder(resp)

    # ---- C2：模型快捷回测（risk_parity）----
    resp = await run_backtest_by_model(
        ids["m_risk_parity"],
        BacktestByModelRequest(start_date=fixture.START, end_date=fixture.END),
        market_service=get_market_service(),
        asset_service=get_asset_service(),
    )
    out["C2_run_by_model"] = jsonable_encoder(resp)

    # ---- C2b：模型快捷回测（trend_cross_sectional，覆盖动量类模板）----
    resp = await run_backtest_by_model(
        ids["m_trend_cs"],
        BacktestByModelRequest(start_date=fixture.START, end_date=fixture.END),
        market_service=get_market_service(),
        asset_service=get_asset_service(),
    )
    out["C2b_run_by_model_trend"] = jsonable_encoder(resp)

    # ---- C3：四象限组合回测 + 参数 schema ----
    resp = await run_portfolio_backtest_api(
        ids["portfolio_quadrant"],
        PortfolioBacktestRequest(start_date=fixture.START, end_date=fixture.END),
    )
    out["C3a_quadrant_backtest"] = jsonable_encoder(resp)

    from app.portfolio.weight_models import QuadrantWeightModel

    out["C3b_quadrant_schema"] = jsonable_encoder(
        QuadrantWeightModel.get_param_schema()
    )

    # ---- C4：监控五读端 ----
    from app.services.monitor_service import MonitorService

    monitor_id = ids["m_risk_parity"]
    ms = MonitorService()
    out["C4_nav_history"] = jsonable_encoder(
        await ms.get_nav_history(monitor_id, end_date=fixture.NAV_END_DATE)
    )
    # 以下三项基于监控最新推演日状态，导入新行情后需 rebase
    out["C4_performance"] = jsonable_encoder(await ms.get_performance(monitor_id))
    out["C4_signal_status"] = jsonable_encoder(await ms.get_signal_status(monitor_id))
    out["C4_positions"] = jsonable_encoder(await ms.get_positions(monitor_id))
    out["C4_attribution"] = jsonable_encoder(
        await ms.get_daily_attribution(monitor_id, date=fixture.ATTRIBUTION_DATE)
    )

    # ---- C4b：实盘互通（eligible-for-monitor + get_model 实盘字段）----
    from app.api.strategy_model import (
        get_asset_service as get_sm_asset_service,
        get_live_publish_service,
    )
    from app.api.strategy_model import list_live_eligible_monitor_models

    resp = await list_live_eligible_monitor_models(
        skip=0,
        limit=500,
        live_service=get_live_publish_service(),
        asset_service=get_sm_asset_service(),
    )
    eligible = jsonable_encoder(resp)
    strategies = (eligible.get("data") or {}).get("strategies") or []
    out["C4b_eligible"] = [
        s for s in strategies if str(s.get("name", "")).startswith(fixture.PREFIX)
    ]

    from app.services.strategy_model_service import StrategyModelService

    model = await StrategyModelService().get_model(monitor_id)
    if model is None:
        raise RuntimeError(f"C4b get_model 失败: {monitor_id}")
    out["C4b_model_live"] = jsonable_encoder(model)

    return out
