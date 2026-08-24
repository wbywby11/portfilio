"""app.backtesting 计算引擎边界守卫测试.

验证包级架构契约（见 docs/backtesting计算引擎架构.md）：
  - backtesting 不反向依赖上层模块（api / monitor / portfolio / services）
  - 白名单例外（已定性）仅限指定文件：
      * app.services.market_service  → 仅 data_feed.py（数据源获取）
  - 包级 facade（__all__）符号均可正确解析
  - 引擎唯一构造点：引擎层外禁止直接构造 BacktestEngine/CompositionPipeline，
    必须经 app.backtesting.runner.run_unified（P1 收敛后生效）
  - 组合必须经统一引擎路径：composite_engine 已退役，组合编排
    （app.portfolio.composite_runner）必须经 run_unified + 合成资产价格构建

用 ast 静态扫描 import/构造语句，不执行被测模块代码。
"""

import ast
from pathlib import Path

import pytest

BACKTESTING_DIR = Path(__file__).resolve().parent.parent / "app" / "backtesting"
APP_DIR = Path(__file__).resolve().parent.parent / "app"

# 禁止的依赖方向：backtesting → 上层模块前缀
FORBIDDEN_PREFIXES = (
    "app.api",
    "app.monitor",
    "app.portfolio",
    "app.services",
)

# 白名单例外：(文件名, 允许的上层模块前缀) —— 与架构文档第 3 节一致，
# 新增例外必须先修订文档并经评审，再登记到此处
WHITELIST = {
    "data_feed.py": ("app.services.market_service",),
}


def _iter_imports(source: str):
    """提取源码中所有绝对 import 的模块名（忽略相对导入）."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                yield node.module


def _collect_violations():
    violations = []
    for path in sorted(BACKTESTING_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for module in _iter_imports(source):
            if not any(module.startswith(p) for p in FORBIDDEN_PREFIXES):
                continue
            allowed = WHITELIST.get(path.name, ())
            if any(module.startswith(w) for w in allowed):
                continue
            violations.append(f"{path.name}: import {module}")
    return violations


class TestBacktestingBoundary:
    """计算引擎边界守卫."""

    def test_no_upward_dependency(self):
        """backtesting 不反向依赖 api / monitor / portfolio / services."""
        violations = _collect_violations()
        assert not violations, (
            "app/backtesting 出现禁止的向上依赖（架构契约见 "
            "docs/backtesting计算引擎架构.md 第 3 节）:\n" + "\n".join(violations)
        )

    def test_whitelist_exceptions_still_needed(self):
        """白名单例外仍真实存在（例外消失时应同步清理 WHITELIST 与文档）."""
        expected = {
            ("data_feed.py", "app.services.market_service"),
        }
        found = set()
        for path in sorted(BACKTESTING_DIR.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for module in _iter_imports(source):
                for filename, allowed in WHITELIST.items():
                    if path.name == filename and any(
                        module.startswith(w) for w in allowed
                    ):
                        found.add((filename, module))
        assert expected == found, (
            f"白名单例外与代码现状不一致: 期望 {expected}, 实际 {found}"
        )

    def test_facade_symbols_resolve(self):
        """包级 facade（__all__）符号均可正确解析."""
        import app.backtesting as bt

        for name in bt.__all__:
            assert getattr(bt, name) is not None, f"facade 符号 {name} 解析失败"

    def test_positioning_docstring_present(self):
        """包 docstring 声明了计算引擎定位（防止定位文档被误删）."""
        import app.backtesting as bt

        assert bt.__doc__ is not None
        assert "计算引擎" in bt.__doc__

    @pytest.mark.skipif(
        not (BACKTESTING_DIR / "runner.py").exists(),
        reason="runner.py 尚未引入（P1 引擎入口收敛）",
    )
    def test_single_engine_construction_point(self):
        """引擎唯一构造点：引擎层外禁止直接构造 BacktestEngine/CompositionPipeline.

        所有计算模式（回测/监控/模拟交易/组合）必须经
        app.backtesting.runner 获取引擎运行结果：
        Step2 逐日推演经 run_unified，Step1 权重生成构建块经
        build_pipeline，避免多处构造导致口径分叉。
        """
        violations = []
        for path in sorted(APP_DIR.rglob("*.py")):
            if path.is_relative_to(BACKTESTING_DIR):
                continue
            rel = str(path.relative_to(APP_DIR)).replace("\\", "/")
            source = None
            for enc in ("utf-8", "gbk"):
                try:
                    source = path.read_text(encoding=enc)
                    break
                except (UnicodeDecodeError, OSError):
                    continue
            if source is None:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id == "BacktestEngine":
                        violations.append(f"{rel}:{node.lineno} BacktestEngine(...)")
                    elif node.func.id == "CompositionPipeline":
                        violations.append(f"{rel}:{node.lineno} CompositionPipeline(...)")
        assert not violations, (
            "引擎层外出现直接引擎构造（应改经 runner.run_unified / "
            "runner.build_pipeline，契约见 "
            "docs/backtesting计算引擎架构.md）:\n" + "\n".join(violations)
        )

    def test_composite_engine_retired(self):
        """composite_engine 已退役：组合必须经统一引擎路径.

        守卫三条：
        1. app/backtesting/composite_engine.py 不得复活（NAV 级复合第二套路径）；
        2. 全仓无 composite_engine 导入残留；
        3. 组合编排入口 composite_runner 必须经 run_unified + 合成资产价格构建
           （SyntheticAssetFeed 同构接口），不得绕过唯一引擎入口。
        """
        assert not (BACKTESTING_DIR / "composite_engine.py").exists(), (
            "composite_engine.py 已退役，组合计算必须经统一引擎路径"
        )
        leftovers = []
        for path in sorted(APP_DIR.rglob("*.py")):
            source = None
            for enc in ("utf-8", "gbk"):
                try:
                    source = path.read_text(encoding=enc)
                    break
                except (UnicodeDecodeError, OSError):
                    continue
            if source is None:
                continue
            try:
                modules = list(_iter_imports(source))
            except SyntaxError:
                continue  # 非标准编码/非 Python 源文件不参与扫描
            for module in modules:
                if "composite_engine" in module:
                    rel = str(path.relative_to(APP_DIR)).replace("\\", "/")
                    leftovers.append(f"{rel}: import {module}")
        assert not leftovers, "残留 composite_engine 导入:\n" + "\n".join(leftovers)

        runner_path = APP_DIR / "portfolio" / "composite_runner.py"
        assert runner_path.exists(), "组合编排入口 composite_runner.py 缺失"
        source = runner_path.read_text(encoding="utf-8")
        assert "run_unified" in source, "组合编排必须经 runner.run_unified"
        assert "build_synthetic_prices" in source, (
            "组合编排必须经合成资产价格构建（synthetic_feed）"
        )


if __name__ == "__main__":
    test = TestBacktestingBoundary()
    test.test_no_upward_dependency()
    print("[PASS] test_no_upward_dependency")
    test.test_whitelist_exceptions_still_needed()
    print("[PASS] test_whitelist_exceptions_still_needed")
    test.test_facade_symbols_resolve()
    print("[PASS] test_facade_symbols_resolve")
    test.test_positioning_docstring_present()
    print("[PASS] test_positioning_docstring_present")
    test.test_single_engine_construction_point()
    print("[PASS] test_single_engine_construction_point")
    test.test_composite_engine_retired()
    print("[PASS] test_composite_engine_retired")
    print("\nAll backtesting boundary tests passed!")
