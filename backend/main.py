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
from app.api.strategy_preset import router as strategy_preset_router
from app.api.strategy_library import router as strategy_library_router  # 策略库只读查询
from app.portfolio import portfolio_router
from app.api.backtests import router as backtests_router  # 新增：回测服务API
from app.api.analysis import router as analysis_router  # 新增：数据分析服务API
from app.api.market import router as market_router  # 行情同步 SSE
from app.api.fx import router as fx_router  # 汇率数据导入
from app.api.trade_calendar import router as trade_calendar_router  # 交易日历
from app.api.factor_panel import router as factor_panel_router  # 因子截面数据
from app.api.macro_series import router as macro_series_router  # 宏观与估值序列
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

    # 上轮进程遗留的监控后台任务：启动时标记为中断（单 worker 部署前提）
    try:
        from app.services.monitor_task_service import mark_stale_interrupted
        _stale = await mark_stale_interrupted()
        if _stale:
            logger.warning("监控后台任务恢复：{} 个未完成任务已标记为中断", _stale)
    except Exception as e:
        logger.warning("监控后台任务恢复失败（不影响启动）: {}", e)

    logger.info("========== 初始化内置策略模板 ==========")
    from app.services.template_init_service import init_builtin_templates
    try:
        result = await init_builtin_templates()
        logger.info(
            "初始化完成: 总数={}, 新创建={}, 已存在={}, 自愈去重={}, 模板列表={}",
            result["total"], result["created"], result["skipped"], result.get("deduped", 0), ", ".join(result["templates"]),
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

    # 资产表索引初始化：tags 为多值字段，策略预设按标签展开资产池需要多键索引
    try:
        from app.services.asset_service import AssetService
        await AssetService().ensure_indexes()
    except Exception as e:
        logger.warning("资产表索引初始化失败（不影响启动）: {}", e)

    # 索引声明表引导：按 app/config/index_specs.py 补齐缺失索引（先比对再建，失败只 warn）
    # 内含批次化存量兼容：补 batch_id="legacy" → 建新唯一索引 → 删旧 {monitor_id} 唯一索引
    try:
        from app.services.index_bootstrap import ensure_all_indexes
        idx = await ensure_all_indexes()
        logger.info(
            "索引引导完成: 集合={}, 新建={}, 已存在={}, 告警={}, 补批次号={}, 删旧索引={}",
            idx.get("collections", 0), idx.get("created", 0),
            idx.get("skipped", 0), idx.get("warned", 0),
            idx.get("backfilled", 0), idx.get("dropped", []),
        )
    except Exception as e:
        logger.warning("索引引导失败（不影响启动）: {}", e)

    # 监控批次存量兼容（幂等，不阻断启动）：
    #   1) 为 batch_id="legacy" 的状态文档补一条 completed 批次记录，
    #      否则存量监控页按批次解析会全部 404；
    #   2) 上轮进程遗留的 pending/running 批次置为 interrupted，
    #      与上面 monitor_tasks 的中断标记保持同步。
    try:
        from app.services.monitor_batch_service import (
            ensure_legacy_batches,
            mark_stale_running_interrupted,
        )
        _legacy = await ensure_legacy_batches()
        _stale_batches = await mark_stale_running_interrupted()
        logger.info(
            "监控批次引导完成: 存量补录={}, 已存在={}, 中断批次={}",
            _legacy.get("created", 0), _legacy.get("skipped", 0), len(_stale_batches),
        )
    except Exception as e:
        logger.warning("监控批次引导失败（不影响启动）: {}", e)

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
# 预设路由先注册：strategy_model_router 有 GET /{model_id}，
# 后注册会让 GET /presets 被当成 model_id="presets" 抢先匹配
app.include_router(
    strategy_preset_router,
    prefix=f"{settings.API_PREFIX}/strategy-models",
    tags=["策略模型"],
)
app.include_router(strategy_model_router, prefix=f"{settings.API_PREFIX}/strategy-models", tags=["策略模型"])
# 兼容部分前端 / OpenAPI 生成代码使用下划线路径（跨系统合并后常见）
app.include_router(
    strategy_preset_router,
    prefix=f"{settings.API_PREFIX}/strategy_models",
    tags=["策略模型(兼容 strategy_models)"],
    include_in_schema=False,
)
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
app.include_router(factor_panel_router, prefix=f"{settings.API_PREFIX}/factor-panel", tags=["因子截面数据"])
app.include_router(macro_series_router, prefix=f"{settings.API_PREFIX}/macro", tags=["宏观与估值序列"])
app.include_router(monitor_router, prefix=f"{settings.API_PREFIX}/monitor", tags=["监控模块"])
app.include_router(subject_risk_router, prefix=f"{settings.API_PREFIX}/subject-risk", tags=["主体观点风险"])
app.include_router(data_hub_router, prefix=f"{settings.API_PREFIX}/data-hub", tags=["通用数据接入"])
app.include_router(data_asset_router, prefix=f"{settings.API_PREFIX}/data-assets", tags=["数据资产管理"])
app.include_router(option_pricing_router, prefix=f"{settings.API_PREFIX}/options", tags=["收益凭证估值"])
app.include_router(option_accounting_router, prefix=f"{settings.API_PREFIX}/options/accounting", tags=["收益凭证会计辅助"])
app.include_router(sim_trade_router, prefix=f"{settings.API_PREFIX}/sim-trade", tags=["模拟交易"])
app.include_router(agent_router, prefix=f"{settings.API_PREFIX}/agent", tags=["AI Agent"])
app.include_router(knowledge_router, prefix=f"{settings.API_PREFIX}/knowledge", tags=["知识库"])
# 策略库只读视图（S16）：档案 / 版本 / 运行台账 / 血缘，与实例级 CRUD 分开挂载
app.include_router(
    strategy_library_router,
    prefix=f"{settings.API_PREFIX}/strategies",
    tags=["策略库"],
)
if __name__ == "__main__":
    import uvicorn

    # 热重载改为白名单：只盯源码目录 app/。
    #
    # 早期用 reload_excludes 枚举目录，但 uvicorn 对 pattern 做 fnmatch 匹配，
    # Windows 下实际路径是反斜杠（logs\_probe.py），正斜杠 pattern（logs/*）
    # 匹配不到，于是放在 logs/、scripts/、根目录的临时 .py 探针仍会触发重载，
    # 把正在跑的组合监控长任务（数分钟）打断成 interrupted。
    # 白名单只监听 app/ 可一次性堵住所有目录；改 main.py 自身仍需手动重启。
    _app_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
        reload_dirs=[_app_dir],
        timeout_keep_alive=600,  # 长连接保活10分钟，支持数据导入等耗时操作
    )