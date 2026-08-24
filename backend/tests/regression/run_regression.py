"""回归 CLI 入口：rebase / check 两模式。

    py tests\\regression\\run_regression.py rebase   # fixture→链路→写黄金基线→cleanup
    py tests\\regression\\run_regression.py check    # fixture→链路→对比黄金基线→cleanup→报告

check 末行输出明确标记（exit code 0/1）：
    REGRESSION IDENTICAL      完全一致
    REGRESSION DIFFS: <n>     存在 n 处差异（逐条打印路径）

⚠ Windows/PowerShell：loguru 输出到 stderr 会让 $LASTEXITCODE 呈现假失败，
  以末行标记为准；运行命令统一用 py（非 python）。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

GOLDEN_PATH = HERE / "golden_baseline.json"


async def _run_chains() -> Dict[str, Any]:
    """boot → cleanup → fixture → 链路 → cleanup（异常也清理），返回归一化结果。"""
    from tests.regression import chains, fixture

    await chains.boot()
    ids = await fixture.create()  # create 内部先 cleanup，幂等
    try:
        results = await chains.run_all(ids)
    finally:
        await fixture.cleanup()
    return _normalize(results, ids)


def _normalize(results: Dict[str, Any], ids: Dict[str, str]) -> Dict[str, Any]:
    """归一化：fixture 动态 ObjectId → 稳定别名，再做 JSON round-trip。

    attribution / correlation_matrix 等输出以子策略 model_id 作字典**键**，
    而 model_id 每次重建 fixture 都变。此处只把不稳定的 id 字面量换成
    别名（如 `<id:m_risk_parity>`），对应的归因/相关数值仍然逐项参与比对，
    不造成断言放宽。round-trip 同时保证与 golden 加载后的类型形态一致（tuple→list 等）。
    """
    text = json.dumps(results, sort_keys=True, ensure_ascii=False)
    for alias, oid in sorted(ids.items()):
        text = text.replace(oid, f"<id:{alias}>")
    return json.loads(text)


def _rebase(results: Dict[str, Any]) -> None:
    GOLDEN_PATH.write_text(
        json.dumps(results, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"golden_baseline.json 已写入: {GOLDEN_PATH}")
    print("REGRESSION REBASED")


def _check(results: Dict[str, Any]) -> int:
    from tests.regression.compare import compare

    if not GOLDEN_PATH.exists():
        print(f"黄金基线不存在: {GOLDEN_PATH}，请先执行 rebase")
        print("REGRESSION DIFFS: 1")
        return 1
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    diffs = compare(golden, results)
    for d in diffs:
        print(f"DIFF {d}")
    if diffs:
        print(f"REGRESSION DIFFS: {len(diffs)}")
        return 1
    print("REGRESSION IDENTICAL")
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("rebase", "check"):
        print("用法: py tests\\regression\\run_regression.py [rebase|check]")
        return 2
    results = asyncio.run(_run_chains())
    if mode == "rebase":
        _rebase(results)
        return 0
    return _check(results)


if __name__ == "__main__":
    sys.exit(main())
