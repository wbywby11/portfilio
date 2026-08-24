"""回归 fixture：创建 / 清理 `_regr_` 前缀测试数据（幂等）。

创建内容（全部走生产服务层代码，不手写内部结构）：
- 4 个策略模型：risk_parity / mean_variance / manual_allocation(等权) / trend_cross_sectional
- 2 个组合模型（is_portfolio=True）：固定权重、四象限（quadrant）
- 1 个组合文档（portfolios 集合）：引用 2 个模型，固定权重
- 1 个监控实例：risk_parity 模型实盘发布（生产 live_publish_model 生成
  live_snapshot）后 run_init（固定 init 日期）

日期区间写死，保证后续行情追加不影响回测链路基线数值。
参数一律取 model_templates 集合中模板声明的默认值，不手写参数结构。
"""
from __future__ import annotations

from typing import Any, Dict, List

from loguru import logger

PREFIX = "_regr_"

# 回测区间（YYYYMMDD，与回测请求格式一致）——写死，行情追加不影响基线
START = "20240102"
END = "20250630"

# 监控 run_init 固定启动日；推演终点为行情最新日期，
# 因此 C4 读端中"最新状态"类输出在行情追加后需要 rebase（见 chains.py 注释）
MONITOR_INIT_START = "2025-01-02"

# C4 读端固定切片日期（保证净值历史 / 归因基线不随行情追加漂移）
NAV_END_DATE = "2025-06-30"
ATTRIBUTION_DATE = "2025-06-30"

# 资产宇宙：均已核实在 2024-01-02 ~ 2025-06-30 有完整行情（390 行）
# 沪深300 行情存储代码为 000300.SH（与 monitor/config.py 中两个研究员策略的
# 资产代码映射一致；旧的 SH000300 形态已随行情重导统一，asset_prices 内不再存在）
ASSETS_RP = ["000300.SH", "ZQGZ10", "GLD", "SHCU"]
ASSETS_MV = ["SPX", "UST10", "GLD", "HSTECH"]
ASSETS_EQ = ["000300.SH", "ZQGZ10", "GLD"]
ASSETS_TC = ["000300.SH", "SPX", "GLD", "SHCU", "ZQGZ10"]

# 四象限信号标的：库内默认 600905.SH 在基线区间无行情，须显式指定有数据的标的
QUADRANT_SIGNAL_CODE = "000300.SH"


async def _template_defaults(template_code: str) -> Dict[str, Any]:
    """从 model_templates 集合读取模板参数默认值（勿手写参数结构）。

    Raises:
        ValueError: 模板不存在（直接失败，不降级）
    """
    from app.config.database import Database

    db = Database.get_database()
    tpl = await db.model_templates.find_one(
        {"code": template_code}, {"parameters": 1}
    )
    if not tpl:
        raise ValueError(f"模板不存在: {template_code}，无法构建回归 fixture")
    params = tpl.get("parameters") or []
    # 仅写入有默认值的参数：写入 None 会让策略内 params.get(key, 兜底值) 取到 None
    return {
        p["name"]: p["default"]
        for p in params
        if isinstance(p, dict) and p.get("default") is not None
    }


async def _regr_model_ids() -> List[str]:
    """查询库内全部 `_regr_` 前缀策略模型 id（含组合模型）。"""
    from app.config.database import Database

    db = Database.get_database()
    cursor = db.strategy_models.find({"name": {"$regex": f"^{PREFIX}"}}, {"_id": 1})
    return [str(doc["_id"]) async for doc in cursor]


async def cleanup() -> None:
    """按前缀幂等清理全部回归测试文档（六个集合）。"""
    from app.config.database import Database

    db = Database.get_database()
    model_ids = await _regr_model_ids()
    portfolio_ids = [
        str(doc["_id"])
        async for doc in db.portfolios.find(
            {"name": {"$regex": f"^{PREFIX}"}}, {"_id": 1}
        )
    ]
    ref_ids = model_ids + portfolio_ids
    await db.backtest_records.delete_many(
        {"$or": [
            {"model_id": {"$in": ref_ids}},
            {"name": {"$regex": PREFIX}},
        ]}
    )
    await db.strategy_live_change_logs.delete_many({"model_id": {"$in": model_ids}})
    await db.monitor_states.delete_many({"monitor_id": {"$in": model_ids}})
    await db.strategy_param_versions.delete_many({"model_id": {"$in": model_ids}})
    await db.portfolios.delete_many({"name": {"$regex": f"^{PREFIX}"}})
    await db.strategy_models.delete_many({"name": {"$regex": f"^{PREFIX}"}})
    logger.info(
        "[regression] cleanup 完成: 模型 {} 个 / 组合文档 {} 个",
        len(model_ids), len(portfolio_ids),
    )


async def _create_strategy_model(
    name: str,
    template_code: str,
    asset_codes: List[str],
    extra_params: Dict[str, Any] | None = None,
) -> str:
    """按模板默认参数创建单个策略模型，返回 model_id。"""
    from app.models.strategy_model import StrategyModel
    from app.services.strategy_model_service import StrategyModelService

    params = await _template_defaults(template_code)
    if extra_params:
        params.update(extra_params)
    model = StrategyModel(
        name=name,
        template_code=template_code,
        description="回归基线 fixture（自动创建，勿手动修改）",
        asset_codes=asset_codes,
        parameters=params,
        rebalance_frequency="monthly",
    )
    return await StrategyModelService().create_model(model)


async def _create_portfolio_model(
    name: str,
    sub_entries: List[Dict[str, Any]],
    weight_model_type: str | None = None,
    weight_model_params: Dict[str, Any] | None = None,
) -> str:
    """创建组合模型（is_portfolio=True），返回 model_id。"""
    from app.models.strategy_model import StrategyModel
    from app.services.strategy_model_service import StrategyModelService

    model = StrategyModel(
        name=name,
        template_code="portfolio_composite",
        description="回归基线 fixture 组合模型（自动创建，勿手动修改）",
        asset_codes=[],  # create_model 自动计算子策略资产并集
        parameters={},
        rebalance_frequency="monthly",
        is_portfolio=True,
        sub_strategies=sub_entries,
        weight_model_type=weight_model_type,
        weight_model_params=weight_model_params or {},
    )
    return await StrategyModelService().create_model(model)


async def create() -> Dict[str, str]:
    """创建全部回归 fixture，返回 id 映射。

    Returns:
        {
            "m_risk_parity": ..., "m_mean_variance": ..., "m_manual_equal": ...,
            "m_trend_cs": ..., "portfolio_fixed": ..., "portfolio_quadrant": ...,
            "portfolio_doc": ...,
        }
    """
    from app.portfolio.models import Portfolio, PortfolioSource, SubStrategyAllocation
    from app.portfolio.portfolio_service import PortfolioService
    from app.services.live_publish_service import LivePublishService
    from app.services.monitor_service import MonitorService

    await cleanup()

    # ---- 4 个策略模型 ----
    m_rp = await _create_strategy_model(
        f"{PREFIX}risk_parity", "risk_parity", ASSETS_RP
    )
    m_mv = await _create_strategy_model(
        f"{PREFIX}mean_variance", "mean_variance", ASSETS_MV
    )
    equal_w = round(1.0 / len(ASSETS_EQ), 10)
    m_eq = await _create_strategy_model(
        f"{PREFIX}manual_equal", "manual_allocation", ASSETS_EQ,
        extra_params={"manual_weights": {code: equal_w for code in ASSETS_EQ}},
    )
    m_tc = await _create_strategy_model(
        f"{PREFIX}trend_cs", "trend_cross_sectional", ASSETS_TC
    )

    # ---- 2 个组合模型 ----
    p_fixed = await _create_portfolio_model(
        f"{PREFIX}portfolio_fixed",
        [
            {"model_id": m_rp, "name": f"{PREFIX}risk_parity", "weight": 0.6},
            {"model_id": m_mv, "name": f"{PREFIX}mean_variance", "weight": 0.4},
        ],
    )
    p_quadrant = await _create_portfolio_model(
        f"{PREFIX}portfolio_quadrant",
        [
            {"model_id": m_rp, "name": f"{PREFIX}risk_parity", "weight": 0.5},
            {"model_id": m_eq, "name": f"{PREFIX}manual_equal", "weight": 0.5},
        ],
        weight_model_type="quadrant",
        weight_model_params={
            "signal_code": QUADRANT_SIGNAL_CODE,
            "rebalance_mode": "signal_driven",
            # 象限→侧重子策略：值须为子策略 model_id（sub_navs 的 key）
            "quadrant_strategy_map": {
                "up_low_vol": m_eq,
                "up_high_vol": m_rp,
                "down_low_vol": m_eq,
                "down_high_vol": m_rp,
            },
        },
    )

    # ---- 1 个组合文档（portfolios 集合，固定权重）----
    portfolio_doc = Portfolio(
        name=f"{PREFIX}portfolio_doc",
        source=PortfolioSource.PORTFOLIO_MODEL,
        description="回归基线 fixture 组合文档（自动创建，勿手动修改）",
        sub_strategies=[
            SubStrategyAllocation(
                model_id=m_rp, name=f"{PREFIX}risk_parity",
                weight=0.6, template_code="risk_parity",
            ),
            SubStrategyAllocation(
                model_id=m_mv, name=f"{PREFIX}mean_variance",
                weight=0.4, template_code="mean_variance",
            ),
        ],
        weight_method="custom",
    )
    pf_doc_id = await PortfolioService().create_portfolio(portfolio_doc)

    # ---- 监控实例：实盘发布（生产代码生成 live_snapshot）+ run_init ----
    published = await LivePublishService().live_publish_model(
        m_rp, source="strategy", operator="regression"
    )
    if not published:
        raise RuntimeError(f"回归 fixture 实盘发布失败: model_id={m_rp}")
    await MonitorService().run_init(monitor_id=m_rp, start_date=MONITOR_INIT_START)

    ids = {
        "m_risk_parity": m_rp,
        "m_mean_variance": m_mv,
        "m_manual_equal": m_eq,
        "m_trend_cs": m_tc,
        "portfolio_fixed": p_fixed,
        "portfolio_quadrant": p_quadrant,
        "portfolio_doc": pf_doc_id,
    }
    logger.info("[regression] fixture 创建完成: {}", ids)
    return ids
