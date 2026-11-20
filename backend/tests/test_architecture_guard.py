"""应用层架构守卫测试.

治理契约（见 plans/应用层架构治理 与 docs/backtesting计算引擎架构.md）：
  1. 行数约束：app/api 与 app/services 单文件 ≤ MAX_API_SERVICE_LINES，
     超标者须登记白名单并限期治理，治理完成后移出白名单；
  2. 依赖方向：backtesting 不反向依赖上层模块（复用
     test_backtesting_boundary.py 的扫描与白名单，避免双份维护）；
  3. 行情读收口：api/services/portfolio/backtesting 中禁止对行情集合的裸
     find/aggregate 读取，必须经 app.data.price_repository（P7 后启用）；
  4. 路由面契约：全量路由（method + path）与基线快照一致——前端协同的
     硬约束，任何端点变化都会在此暴露；合法新增端点时须同步更新基线
     tests/_routes_baseline.txt。

静态 AST 扫描为主，路由面测试会导入应用（秒级）。
"""

import ast
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
APP_DIR = TESTS_DIR.parent / "app"
ROUTES_BASELINE = TESTS_DIR / "_routes_baseline.txt"

# api/services 单文件行数上限
MAX_API_SERVICE_LINES = 1000

# 现状超标的治理目标（每项对应治理阶段，完成后必须移出白名单）：
#   monitor_service.py  → 已完成 Mixin 第一轮，剩余三入口编排待后续治理
# （backtests.py 已于 P8 拆分至 ≤1000 行，移出白名单；
#   strategy_model.py / asset.py 已于 P9 编排下沉至 ≤1000 行，移出白名单）
LINE_WHITELIST = {
    "services/monitor_service.py",
}

# 行情裸查收口的豁免文件：导入引擎的读查与写入流程耦合（按日去重、
# 预览统计），允许保留直查；其余消费方必须经 PriceRepository
PRICE_DIRECT_READ_EXEMPT = {
    "price_importer.py",
}


def _read_source(path: Path):
    for enc in ("utf-8", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, OSError):
            continue
    return None


def _rel(path: Path) -> str:
    return str(path.relative_to(APP_DIR)).replace("\\", "/")


class TestLineBudget:
    """行数预算：api/services 不得新增超大文件."""

    def test_api_services_line_limit(self):
        violations = []
        for sub in ("api", "services"):
            for path in sorted((APP_DIR / sub).glob("*.py")):
                rel = _rel(path)
                if rel in LINE_WHITELIST:
                    continue
                source = _read_source(path)
                if source is None:
                    continue
                lines = source.count("\n") + (0 if source.endswith("\n") else 1)
                if lines > MAX_API_SERVICE_LINES:
                    violations.append(f"{rel}: {lines} 行 > {MAX_API_SERVICE_LINES}")
        assert not violations, (
            "api/services 出现超行数预算的文件（应拆分或登记限期治理白名单）:\n"
            + "\n".join(violations)
        )

    def test_whitelist_files_still_over_budget(self):
        """白名单文件仍真实超标（治理完成后应移出白名单）."""
        stale = []
        for rel in sorted(LINE_WHITELIST):
            path = APP_DIR / rel
            if not path.exists():
                stale.append(f"{rel}: 文件不存在，白名单条目过期")
                continue
            source = _read_source(path)
            lines = source.count("\n") + (0 if source.endswith("\n") else 1)
            if lines <= MAX_API_SERVICE_LINES:
                stale.append(f"{rel}: 已降至 {lines} 行，应移出白名单")
        assert not stale, "行数白名单与现状不一致:\n" + "\n".join(stale)


class TestDependencyDirection:
    """依赖方向：复用边界测试的扫描逻辑（单一真相源）."""

    def test_backtesting_no_upward_dependency(self):
        from test_backtesting_boundary import _collect_violations

        violations = _collect_violations()
        assert not violations, (
            "app/backtesting 出现禁止的向上依赖:\n" + "\n".join(violations)
        )


class TestPriceReadFunnel:
    """行情读收口：禁止绕过 PriceRepository 裸查行情集合."""

    @pytest.mark.skipif(
        not (APP_DIR / "data" / "price_repository.py").exists(),
        reason="PriceRepository 尚未引入（P7 行情读收口）",
    )
    def test_no_raw_price_collection_reads(self):
        violations = []
        for sub in ("api", "services", "portfolio", "backtesting"):
            for path in sorted((APP_DIR / sub).rglob("*.py")):
                if path.name in PRICE_DIRECT_READ_EXEMPT:
                    continue
                source = _read_source(path)
                if source is None:
                    continue
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    # 匹配形如 xxx_price_collection.find( / .aggregate( 的调用
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("find", "aggregate")
                        and isinstance(node.func.value, ast.Attribute)
                        and "price_collection" in node.func.value.attr
                    ):
                        violations.append(
                            f"{_rel(path)}:{node.lineno} "
                            f"{node.func.value.attr}.{node.func.attr}(...)"
                        )
        assert not violations, (
            "出现绕过 PriceRepository 的行情裸查（读端必须经 "
            "app.data.price_repository，写端仅限行情导入链路）:\n"
            + "\n".join(violations)
        )


class TestRouteSurface:
    """路由面契约：method + path 与基线一致（前端协同硬约束）."""

    @staticmethod
    def _iter_flat(routes, prefix=""):
        """展开惰性 include 的路由对象。

        FastAPI >=0.13x 把 include_router 变成惰性的 _IncludedRouter，
        它没有 path/methods 属性，需经 original_router + include_context 递归展开。
        """
        for r in routes or []:
            if hasattr(r, "path"):
                yield prefix + r.path, sorted(getattr(r, "methods", []) or [])
                continue
            ctx = getattr(r, "include_context", None)
            orig = getattr(r, "original_router", None)
            sub_routes = getattr(orig, "routes", None) if orig is not None else None
            if sub_routes is None:
                continue
            yield from TestRouteSurface._iter_flat(
                sub_routes, prefix + (getattr(ctx, "prefix", "") or "")
            )

    def test_route_surface_matches_baseline(self):
        from main import app

        current = sorted(
            f"{','.join(methods)}\t{path}"
            for path, methods in self._iter_flat(app.routes)
        )
        baseline = ROUTES_BASELINE.read_text(encoding="utf-8").splitlines()
        if current != baseline:
            added = sorted(set(current) - set(baseline))
            removed = sorted(set(baseline) - set(current))
            parts = []
            if added:
                parts.append("新增端点:\n" + "\n".join(added))
            if removed:
                parts.append("消失端点:\n" + "\n".join(removed))
            raise AssertionError(
                "路由面与基线不一致（端点变化必须与前端协同确认；合法变化时"
                "重新生成 tests/_routes_baseline.txt）:\n" + "\n".join(parts)
            )


def _iter_app_sources(root: Path):
    """递归产出 (相对路径, AST)；读不出或语法错误的文件跳过."""
    for path in sorted(root.rglob("*.py")):
        source = _read_source(path)
        if source is None:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        yield str(path.relative_to(APP_DIR)).replace("\\", "/"), tree


def _calls_named(tree: ast.AST, name: str):
    """找出名为 ``name`` 的调用（ obj.name(...) 与 name(...) 都算）."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == name:
            yield node
        elif isinstance(func, ast.Name) and func.id == name:
            yield node


def _dict_key_writes(tree: ast.AST, key: str):
    """找出字面量字典写入（{"key": ...}）与属性赋值（obj.key = ...）."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and k.value == key:
                    yield node.lineno
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == key:
                    yield node.lineno


class TestVersionSingleWriter:
    """版本正文单写：published_snapshot 只能由发布链路与版本服务写."""

    ALLOWED = {
        "services/live_publish_service.py",
        "services/strategy_version_service.py",
    }

    def test_published_snapshot_single_writer(self):
        violations = [
            f"{rel}:{lineno}"
            for rel, tree in _iter_app_sources(APP_DIR)
            if rel not in self.ALLOWED
            for lineno in _dict_key_writes(tree, "published_snapshot")
        ]
        assert not violations, (
            "published_snapshot 出现新的写入点（版本链会断裂，新增入口必须经 "
            "live_publish_service / strategy_version_service）:\n" + "\n".join(violations)
        )


class TestRunSinglePersistPath:
    """回测记录单点收口：save_backtest_record 定义 1 处、调用 4 处."""

    TARGET = "save_backtest_record"
    EXPECTED_CALLS = 4

    def test_single_definition_and_four_calls(self):
        definitions, calls = [], []
        for rel, tree in _iter_app_sources(APP_DIR):
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == self.TARGET:
                    definitions.append(f"{rel}:{node.lineno}")
            calls.extend(f"{rel}:{node.lineno}" for node in _calls_named(tree, self.TARGET))
        assert len(definitions) == 1, (
            "save_backtest_record 必须只有 1 处定义（单点收口）:\n" + "\n".join(definitions)
        )
        assert len(calls) == self.EXPECTED_CALLS, (
            f"save_backtest_record 调用点应为 {self.EXPECTED_CALLS} 处（绕开它会丢运行台账）:\n"
            + "\n".join(calls)
        )


class TestLifecycleSingleWriter:
    """研发阶段单写：lifecycle_stage 只能经生命周期服务/档案服务落库."""

    ALLOWED = {
        "services/strategy_lifecycle_service.py",
        "services/strategy_registry_service.py",
    }

    def test_lifecycle_stage_single_writer(self):
        violations = [
            f"{rel}:{lineno}"
            for rel, tree in _iter_app_sources(APP_DIR)
            if rel not in self.ALLOWED
            for lineno in _dict_key_writes(tree, "lifecycle_stage")
        ]
        assert not violations, (
            "lifecycle_stage 出现旁路写入（准入判定会失真）:\n" + "\n".join(violations)
        )


class TestNoRegistryBypass:
    """档案单写：禁止直接往 strategy_registry 插入/覆盖文档."""

    ALLOWED = {"services/strategy_registry_service.py"}
    WRITE_METHODS = ("insert_one", "insert_many", "replace_one", "bulk_write")

    def test_no_direct_registry_insert(self):
        violations = []
        for rel, tree in _iter_app_sources(APP_DIR):
            if rel in self.ALLOWED:
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr not in self.WRITE_METHODS:
                    continue
                try:
                    receiver = ast.unparse(node.func.value)
                except Exception:  # noqa: BLE001
                    continue
                if "COL_STRATEGY_REGISTRY" in receiver or "strategy_registry" in receiver:
                    violations.append(f"{rel}:{node.lineno} {receiver}.{node.func.attr}(...)")
        assert not violations, (
            "出现直接写 strategy_registry 的旁路（新增策略必须经 STRATEGY_MANIFEST，"
            "档案由采集器 upsert）:\n" + "\n".join(violations)
        )


if __name__ == "__main__":
    t1 = TestLineBudget()
    t1.test_api_services_line_limit()
    print("[PASS] test_api_services_line_limit")
    t1.test_whitelist_files_still_over_budget()
    print("[PASS] test_whitelist_files_still_over_budget")
    t2 = TestDependencyDirection()
    t2.test_backtesting_no_upward_dependency()
    print("[PASS] test_backtesting_no_upward_dependency")
    print("\nArchitecture guard tests passed!")
