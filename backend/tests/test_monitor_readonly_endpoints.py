# -*- coding: utf-8 -*-
"""监控展示端点「纯读表」守卫 —— AST 静态断言.

批次化改造把监控拆成两侧：写入侧（跑批产出版本化快照）与读取侧（展示端点
投影快照）。读取侧一旦回退成「请求里现算」，就会重新出现页面请求触发推演、
请求触发缓存重建、请求回源行情库三类事故，而这些在 code review 里很难被发现
——函数名看起来都像是「查询」。本测试用 AST 把边界钉死：

  1. ``app/api/monitor*.py`` 中每个 ``@router.get`` 处理函数体内，不得出现
     计算/写入侧入口的名字（``run_*`` / ``*_performance_cache`` / ``save_*`` /
     ``create_batch`` ...），也不得注入 ``MonitorService``；
  2. 同批文件不得 import 任何计算组件模块（tracker / stepper / adapter /
     detector / reporter / 组合管线 / backtesting）；
  3. ``app/services/monitor_query_service.py`` 不得 import 计算组件，也不得
     调用缓存重建与行情加载；
  4. 按实例维度展示数据的 GET 端点必须接受 ``batch_id`` 参数（批次口径不可回退）。

纯静态断言：不连数据库、不起服务、不导入被测应用。
"""

import ast
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
APP_DIR = TESTS_DIR.parent / "app"

#: 参与扫描的监控 API 路由模块（monitor.py 拆分后的三件 + 共享依赖）
API_FILES = (
    "api/monitor.py",
    "api/monitor_batches.py",
    "api/monitor_strategies.py",
    "api/monitor_deps.py",
)

#: 只读查询服务（展示端点的唯一数据入口）
QUERY_SERVICE_FILE = "services/monitor_query_service.py"

# ---------------------------------------------------------------------------
# 禁止清单
# ---------------------------------------------------------------------------

#: GET 处理函数体内禁止出现的「计算 / 写入侧」入口名（方法名或函数名）
FORBIDDEN_IN_GET = {
    # 推演入口
    "run_init", "run_daily", "run_range", "run_backtest",
    "_begin_run_batch", "_finish_run_batch", "_run_portfolio_backtest_monitor",
    # 绩效缓存重建（展示侧只读，缺失就 404）
    "rebuild_performance_cache", "ensure_performance_cache", "get_performance_panel",
    # 指标现算（注意：get_performance / get_positions / get_nav_history / get_events /
    # get_daily_attribution / get_dual_performance 这些同名方法在 MonitorQueryService
    # 上是纯读表实现，属于合法调用，因此不在此清单里；端点是否误用了
    # MonitorService 由 test_get_handlers_do_not_inject_monitor_service 守住）
    "compute_performance", "calc_performance_api_dict", "calc_daily_attribution",
    "get_signal_status",
    # 落库
    "save_state", "save_monitor_record", "_save_daily_report", "_save_risk_alerts",
    "_record_operation_events", "_persist_signal_snapshot",
    # 批次生命周期（写入侧动作）
    "create_batch", "mark_running", "mark_completed", "mark_failed",
    "mark_paused", "mark_interrupted", "inherit_pending_overrides",
    # 行情回源
    "load_prices",
}

#: GET 处理函数禁止依赖的写入侧服务（名字出现在签名/注解/体内即违规）
FORBIDDEN_SERVICE_NAMES = {"MonitorService", "get_monitor_service"}

#: API 层与只读服务都禁止 import 的计算组件模块前缀
FORBIDDEN_IMPORT_PREFIXES = (
    "app.monitor.portfolio_tracker",
    "app.monitor.daily_stepper",
    "app.monitor.engine_adapter",
    "app.monitor.signal_detector",
    "app.monitor.volatility_calculator",
    "app.monitor.report_generator",
    "app.monitor.portfolio_backtest_monitor",
    "app.monitor.portfolio_dual_track",
    "app.monitor.risk_alert_detector",
    "app.monitor.monitor_runtime",
    "app.monitor.monitor_query",
    "app.monitor.data_provider",
    "app.monitor.rebalance_planning",
    "app.monitor.manual_preset",
    "app.monitor.operation_recorder",
    "app.monitor.risk_alert_recorder",
    "app.backtesting",
)

#: 只读服务额外禁止 import 的写入侧服务
FORBIDDEN_QUERY_IMPORTS = FORBIDDEN_IMPORT_PREFIXES + (
    "app.services.monitor_service",
    "app.services.backtest_service",
)

#: 按实例维度展示跑批产物的 GET 端点，必须接受可选 batch_id
BATCH_SCOPED_GET_PATHS = {
    "/state",
    "/nav-history",
    "/events",
    "/positions",
    "/daily-attribution",
    "/performance",
    "/performance-panel",
    "/performance-dual",
    "/operations",
    "/signals",
    "/risk-alerts",
    "/reports/{date}",
    "/reports",
    "/subjective",
}


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _read(rel: str) -> str:
    path = APP_DIR / rel
    assert path.is_file(), f"被测文件不存在: {path}"
    return path.read_text(encoding="utf-8")


def _parse(rel: str) -> ast.Module:
    return ast.parse(_read(rel), filename=rel)


def _route_paths(func: ast.AST) -> list:
    """取出处理函数上 ``@router.<method>("path")`` 的 (method, path) 列表."""
    out = []
    for dec in getattr(func, "decorator_list", []):
        if not isinstance(dec, ast.Call):
            continue
        target = dec.func
        if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
            continue
        if target.value.id != "router":
            continue
        path = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else None
        if isinstance(path, str):
            out.append((target.attr.upper(), path))
    return out


def _called_names(func: ast.AST) -> set:
    """函数体内被调用的名字（含属性调用的属性名）."""
    names = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _referenced_names(func: ast.AST) -> set:
    """函数体内出现过的全部标识符（含注解里的字符串形式）."""
    names = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


def _imported_modules(tree: ast.Module) -> set:
    """文件内所有 import 的模块名（含函数体内的惰性 import）."""
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def _get_handlers(rel: str):
    """产出 (path, 函数节点)：仅 @router.get 的处理函数."""
    tree = _parse(rel)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for method, path in _route_paths(node):
            if method == "GET":
                yield path, node
                break


# ---------------------------------------------------------------------------
# 断言 1：GET 处理函数内不得出现计算 / 写入侧调用
# ---------------------------------------------------------------------------

def test_get_handlers_have_no_computation_calls():
    violations = []
    for rel in API_FILES:
        for path, func in _get_handlers(rel):
            hit = sorted(_called_names(func) & FORBIDDEN_IN_GET)
            if hit:
                violations.append(f"{rel}::{func.name} (GET {path}) 调用了 {hit}")
    assert not violations, "GET 端点必须纯读表，发现计算/写入侧调用:\n" + "\n".join(violations)


def test_get_handlers_do_not_inject_monitor_service():
    violations = []
    for rel in API_FILES:
        for path, func in _get_handlers(rel):
            hit = sorted(_referenced_names(func) & FORBIDDEN_SERVICE_NAMES)
            if hit:
                violations.append(f"{rel}::{func.name} (GET {path}) 引用了 {hit}")
    assert not violations, (
        "GET 端点只能注入 MonitorQueryService，发现写入侧服务:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 断言 2：API 层不得 import 计算组件
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", API_FILES)
def test_api_files_do_not_import_computation_modules(rel):
    mods = _imported_modules(_parse(rel))
    bad = sorted(
        m for m in mods
        if any(m == p or m.startswith(p + ".") for p in FORBIDDEN_IMPORT_PREFIXES)
    )
    assert not bad, f"{rel} 不得 import 计算组件模块，发现: {bad}"


# ---------------------------------------------------------------------------
# 断言 3：只读查询服务的依赖与调用面
# ---------------------------------------------------------------------------

def test_query_service_imports_no_computation_modules():
    mods = _imported_modules(_parse(QUERY_SERVICE_FILE))
    bad = sorted(
        m for m in mods
        if any(m == p or m.startswith(p + ".") for p in FORBIDDEN_QUERY_IMPORTS)
    )
    assert not bad, f"{QUERY_SERVICE_FILE} 必须只持 DB 句柄，发现计算/写入侧 import: {bad}"


def test_query_service_never_rebuilds_cache_or_loads_prices():
    tree = _parse(QUERY_SERVICE_FILE)
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                called.add(target.id)
            elif isinstance(target, ast.Attribute):
                called.add(target.attr)
    bad = sorted(called & {"rebuild_performance_cache", "ensure_performance_cache",
                           "get_performance_panel", "load_prices"})
    assert not bad, f"只读服务不得重建缓存或回源行情，发现调用: {bad}"


# ---------------------------------------------------------------------------
# 断言 4：实例维度展示端点必须支持 batch_id
# ---------------------------------------------------------------------------

def test_batch_scoped_get_endpoints_accept_batch_id():
    found = {}
    for rel in API_FILES:
        for path, func in _get_handlers(rel):
            args = {a.arg for a in func.args.args + func.args.kwonlyargs}
            found[path] = (rel, func.name, args)

    missing_endpoint = sorted(BATCH_SCOPED_GET_PATHS - set(found))
    assert not missing_endpoint, (
        f"这些展示端点已从路由面消失（批次口径被绕过？）: {missing_endpoint}"
    )

    missing_param = [
        f"{found[p][0]}::{found[p][1]} (GET {p})"
        for p in sorted(BATCH_SCOPED_GET_PATHS)
        if "batch_id" not in found[p][2]
    ]
    assert not missing_param, (
        "以下展示端点缺少 batch_id 参数，无法按批次读取快照:\n" + "\n".join(missing_param)
    )


def test_batch_id_defaults_to_latest_completed_batch():
    """``batch_id`` 必须默认 None（= 最新 completed 批次），不得硬编码默认批次号."""
    offenders = []
    for rel in API_FILES:
        for path, func in _get_handlers(rel):
            if path not in BATCH_SCOPED_GET_PATHS:
                continue
            for arg, default in zip(reversed(func.args.args), reversed(func.args.defaults)):
                if arg.arg != "batch_id" or not isinstance(default, ast.Call):
                    continue
                # 形如 Query(None, description=...)：首参必须是 None
                if not (default.args and isinstance(default.args[0], ast.Constant)
                        and default.args[0].value is None):
                    offenders.append(f"{rel}::{func.name} (GET {path})")
    assert not offenders, (
        "batch_id 的默认值必须是 None（解析到最新 completed 批次），发现硬编码默认值:\n"
        + "\n".join(offenders)
    )
