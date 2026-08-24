"""
Portfolio Backend - FastAPI 主程序入口
"""

import os
from contextlib import asynccontextmanager

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from app.config.logging_config import setup_logging

setup_logging()

# OpenAI SDK 底层 httpx：打印 HTTP 层调试。
# 开启：DEBUG_HTTPX=1（PowerShell: $env:DEBUG_HTTPX='1' ，等号旁不要多余空格）
#
# 注意：httpx 对「每次请求/连接」用的是自定义级别 TRACE（数值 5），低于 DEBUG(10)。
# 若只把 logger 设为 DEBUG，TRACE 会被过滤，看起来像「没有任何输出」。
if os.environ.get("DEBUG_HTTPX", "").strip().lower() in ("1", "true", "yes", "on"):
    import logging
    import sys

    _TRACE = 5
    logging.addLevelName(_TRACE, "TRACE")

    _fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    _h = logging.StreamHandler(sys.stderr)
    _h.setLevel(_TRACE)
    _h.setFormatter(_fmt)
    for _name in ("httpx", "httpcore", "openai"):
        _lg = logging.getLogger(_name)
        _lg.setLevel(_TRACE)
        _lg.addHandler(_h)
        _lg.propagate = False

    print("[DEBUG_HTTPX] httpx/httpcore/openai logging enabled (TRACE+)", file=sys.stderr, flush=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config.settings import settings
from app.config.database import Database
from app.api.asset import router as asset_router
from app.api.model_template import router as model_template_router
from app.api.strategy_model import router as strategy_model_router
from app.portfolio import portfolio_router
from app.api.backtests import router as backtests_router  # 新增：回测服务API
from app.api.analysis import router as analysis_router  # 新增：数据分析服务API
from app.api.market import router as market_router  # 行情同步 SSE
from app.api.fx import router as fx_router  # 汇率数据导入
from app.api.trade_calendar import router as trade_calendar_router  # 交易日历
from app.api.monitor import router as monitor_router  # 监控模块
from app.api.subject_risk import router as subject_risk_router  # 主体观点风险
from app.api.data_hub import router as data_hub_router  # 通用数据接入 Hub
from app.api.api_data_asset import router as data_asset_router  # 数据资产管理
from app.api.option_pricing import router as option_pricing_router  # 收益凭证估值
from app.api.option_accounting import router as option_accounting_router  # 收益凭证会计辅助
from app.portfolio import sim_trade_router as sim_trade_router  # 模拟交易
from app.agent.api.agent_router import router as agent_router  # AI Agent
from app.agent.api.knowledge_router import router as knowledge_router  # 知识库
from app.api.exception_handlers import (
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动 / 关闭事件（替代废弃的 on_event）。"""
    # ── startup ──
    from loguru import logger
    Database.connect()

    logger.info("========== 初始化内置策略模板 ==========")
    from app.services.template_init_service import init_builtin_templates
    try:
        result = await init_builtin_templates()
        logger.info(
            "初始化完成: 总数={}, 新创建={}, 已存在={}, 模板列表={}",
            result["total"], result["created"], result["skipped"], ", ".join(result["templates"]),
        )
        logger.info("应用启动成功 - {} v{} 已就绪，可接受请求", settings.APP_NAME, settings.APP_VERSION)
    except Exception as e:
        logger.exception("初始化内置模板失败: {}", e)
        logger.error("应用启动失败，请检查上述错误后重启")

    # 数据资产扫描（幂等，不阻塞启动）
    try:
        from app.services.api_data_asset_service import ApiDataAssetService
        asset_service = ApiDataAssetService()
        scan_result = await asset_service.scan_database()
        logger.info(
            "数据资产扫描完成: {} 个集合, {} 条记录",
            scan_result.get("total", 0),
            scan_result.get("total_records", 0),
        )
    except Exception as e:
        logger.warning("数据资产扫描失败（不影响启动）: {}", e)

    # 知识库索引初始化（幂等，不阻塞启动）
    try:
        from app.agent.knowledge import KnowledgeStore
        await KnowledgeStore().ensure_indexes()
    except Exception as e:
        logger.warning("知识库索引初始化失败（不影响启动）: {}", e)

    logger.info("========================================")

    yield

    # ── shutdown ──
    Database.close()
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    swagger_ui_use_local_assets=True,
    lifespan=lifespan,
)

# 注册全局异常处理器
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# 跨域配置,开发阶段允许所有源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 挂载各业务模块路由

app.include_router(asset_router, prefix=f"{settings.API_PREFIX}/assets", tags=["资产池管理"])
app.include_router(model_template_router, prefix=f"{settings.API_PREFIX}/model-templates", tags=["模型模板"])
app.include_router(strategy_model_router, prefix=f"{settings.API_PREFIX}/strategy-models", tags=["策略模型"])
# 兼容部分前端 / OpenAPI 生成代码使用下划线路径（跨系统合并后常见）
app.include_router(
    strategy_model_router,
    prefix=f"{settings.API_PREFIX}/strategy_models",
    tags=["策略模型(兼容 strategy_models)"],
    include_in_schema=False,
)
app.include_router(portfolio_router, prefix=f"{settings.API_PREFIX}/portfolios", tags=["模拟组合"])

# 新增：回测服务和数据分析服务API
app.include_router(backtests_router, prefix=f"{settings.API_PREFIX}/backtests", tags=["回测服务"])
app.include_router(analysis_router, prefix=f"{settings.API_PREFIX}/analysis", tags=["数据分析"])
app.include_router(market_router, prefix=f"{settings.API_PREFIX}/market", tags=["行情同步"])
app.include_router(fx_router, prefix=f"{settings.API_PREFIX}/fx", tags=["汇率数据"])
app.include_router(trade_calendar_router, prefix=f"{settings.API_PREFIX}/trade-calendar", tags=["交易日历"])
app.include_router(monitor_router, prefix=f"{settings.API_PREFIX}/monitor", tags=["监控模块"])
app.include_router(subject_risk_router, prefix=f"{settings.API_PREFIX}/subject-risk", tags=["主体观点风险"])
app.include_router(data_hub_router, prefix=f"{settings.API_PREFIX}/data-hub", tags=["通用数据接入"])
app.include_router(data_asset_router, prefix=f"{settings.API_PREFIX}/data-assets", tags=["数据资产管理"])
app.include_router(option_pricing_router, prefix=f"{settings.API_PREFIX}/options", tags=["收益凭证估值"])
app.include_router(option_accounting_router, prefix=f"{settings.API_PREFIX}/options/accounting", tags=["收益凭证会计辅助"])
app.include_router(sim_trade_router, prefix=f"{settings.API_PREFIX}/sim-trade", tags=["模拟交易"])
app.include_router(agent_router, prefix=f"{settings.API_PREFIX}/agent", tags=["AI Agent"])
app.include_router(knowledge_router, prefix=f"{settings.API_PREFIX}/knowledge", tags=["知识库"])
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
        reload_excludes=["scripts/*", "tests/*"],
        timeout_keep_alive=600,  # 长连接保活10分钟，支持数据导入等耗时操作
    )