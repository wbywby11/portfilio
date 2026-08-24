"""
工具诊断脚本 — 逐个验证 Agent 工具的可用性。

检测维度：
1. import 是否成功
2. 类实例化是否成功
3. execute() 方法签名是否合法
4. 最小参数调用是否可到达 service 层（预期会因缺少 DB/参数报错，但不应是 import 错误）
"""
import sys
import os
import asyncio
import inspect
import traceback

# 确保项目根目录在 sys.path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("ENV", "development")

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")


def phase1_import_and_registry():
    """Phase 1: 检测工具导入和注册"""
    print("=" * 60)
    print("Phase 1: 工具导入 & 注册检查")
    print("=" * 60)

    try:
        from app.agent.tools import auto_discover_tools, tool_registry
        print(f"[OK] 工具自动发现模块导入成功")
    except Exception as e:
        print(f"[FAIL] 工具自动发现模块导入失败: {e}")
        traceback.print_exc()
        return {}, None

    # 已注册工具
    all_tools = tool_registry.get_all_tools()
    print(f"[OK] 已注册工具数: {len(all_tools)}")
    return {t.name: t for t in all_tools}, tool_registry


def phase2_inspect_tools(tools: dict):
    """Phase 2: 检查每个工具的 execute 方法签名"""
    print(f"\n{'=' * 60}")
    print("Phase 2: execute() 方法签名检查")
    print("=" * 60)

    results = {}
    for name, tool in sorted(tools.items()):
        try:
            sig = inspect.signature(tool.execute)
            params = list(sig.parameters.keys())
            results[name] = {
                "class": type(tool).__name__,
                "module": type(tool).__module__,
                "params": params,
                "has_execute": True,
            }
            print(f"  [OK] {name:30s} | {type(tool).__name__:30s} | params={params[:5]}...")
        except Exception as e:
            results[name] = {"error": str(e), "has_execute": False}
            print(f"  [FAIL] {name:30s} | {e}")

    return results


async def phase3_minimal_invoke(tools: dict):
    """Phase 3: 最小参数调用每个工具，分类错误类型"""
    print(f"\n{'=' * 60}")
    print("Phase 3: 最小参数调用测试")
    print("=" * 60)

    # A 级工具
    A_TOOLS = ["data_query", "data_analyze", "query_assets", "query_asset_prices", "compute_metrics"]
    # B 级工具
    B_TOOLS = ["create_strategy_model", "execute_backtest", "compare_strategies",
                "compute_weights", "create_portfolio", "get_portfolio"]
    # C 级 - 其余所有

    results = {"A": {}, "B": {}, "C": {}}

    for name, tool in sorted(tools.items()):
        if name in A_TOOLS:
            level = "A"
        elif name in B_TOOLS:
            level = "B"
        else:
            level = "C"

        try:
            # 使用超时保护
            result = await asyncio.wait_for(tool.execute(), timeout=10.0)
            status = "OK"
            error_type = None
            error_msg = None
            # 检查返回值结构
            if isinstance(result, dict):
                success = result.get("success", None)
                if success is False:
                    status = "BIZ_ERROR"
                    error_msg = result.get("error", "")[:80]
                elif success is True:
                    status = "OK"
            print(f"  [{level}][{status:10s}] {name:30s} | {str(result)[:80]}")
        except asyncio.TimeoutError:
            status = "TIMEOUT"
            error_msg = "执行超时(10s)"
            print(f"  [{level}][TIMEOUT   ] {name:30s} | 执行超时")
        except TypeError as e:
            # 通常是缺少必需参数 — 这是预期的（最小调用不带参数）
            status = "MISSING_PARAM"
            error_msg = str(e)[:80]
            print(f"  [{level}][MISS_PARAM ] {name:30s} | {error_msg}")
        except ImportError as e:
            status = "IMPORT_ERROR"
            error_msg = str(e)[:80]
            print(f"  [{level}][IMPORT_ERR] {name:30s} | {error_msg}")
        except ConnectionError as e:
            status = "CONN_ERROR"
            error_msg = str(e)[:80]
            print(f"  [{level}][CONN_ERR  ] {name:30s} | {error_msg}")
        except Exception as e:
            status = "RUNTIME_ERROR"
            error_msg = f"{type(e).__name__}: {str(e)[:60]}"
            print(f"  [{level}][RUNTIME_ERR] {name:30s} | {error_msg}")
            traceback.print_exc()

        results[level][name] = {
            "status": status,
            "error_type": error_msg,
            "class": type(tool).__name__,
            "module": type(tool).__module__,
        }

    return results


def print_summary(results: dict):
    """打印诊断总结"""
    print(f"\n{'=' * 60}")
    print("诊断总结")
    print("=" * 60)

    for level in ["A", "B", "C"]:
        level_results = results.get(level, {})
        if not level_results:
            continue
        ok_count = sum(1 for v in level_results.values() if v["status"] == "OK")
        total = len(level_results)
        print(f"\n  {level} 级工具: {ok_count}/{total} 可用")
        for name, info in sorted(level_results.items()):
            status = info["status"]
            icon = "+" if status == "OK" else "-" if status == "MISSING_PARAM" else "!"
            print(f"    [{icon}] {name:30s} | {status:15s} | {(info.get('error_type') or '')[:60]}")


async def main():
    tools, registry = phase1_import_and_registry()
    if not tools:
        print("没有发现任何工具，退出")
        return

    inspect_results = phase2_inspect_tools(tools)
    invoke_results = await phase3_minimal_invoke(tools)
    print_summary(invoke_results)


if __name__ == "__main__":
    asyncio.run(main())
