# -*- coding: utf-8 -*-
"""回归链层：吸收旧 ``tests/regression/snapshot_guard.py`` + ``logs/_known_drifts_S01.json``.

门禁语义（与原守卫一致）
------------------------
``tests/regression/golden_baseline.json`` 冻结于 ``d408639``，HEAD ``a14fa13``
改了回测内核口径但从未 rebase，因此 ``run_regression.py check`` 一直是红灯
（12944 条 diff）。那是既有债务，不是本批次引入的。所以本层不做 rebase，
只把当前红灯的完整形态冻结成快照，门禁是「不允许出现无法归因的新增 diff」。

与旧实现的两点差异
------------------
1. 不再解析日志文本（旧实现要处理 PowerShell ``>`` 的 UTF-16LE BOM），
   而是进程内直接调 ``run_regression`` 的链路函数，拿到 ``compare()`` 的
   diff 字符串列表——少一层解析就少一类假失败。
2. 新 diff 数与消失 diff 数分开报告：新增即失败，消失只告警（可能是修复，
   也可能是链路结构变化，需要人工在 commit message 里说明）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

SNAPSHOT_PATH = HERE / "regression_snapshot.json"
REGRESSION_GOLDEN = BACKEND_ROOT / "tests" / "regression" / "golden_baseline.json"


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return "<MISSING>"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> Dict[str, Any]:
    """跑 regression 全部链路，返回冻结快照结构（含完整 diff 字符串）."""
    from tests.regression import run_regression
    from tests.regression.compare import compare

    results = asyncio.run(run_regression._run_chains())
    golden_path = run_regression.GOLDEN_PATH
    if not golden_path.exists():
        raise RuntimeError(f"regression 黄金基线不存在: {golden_path}")
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    diffs = [str(d) for d in compare(golden, results)]
    return {
        "meta": {
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "regression_golden_file": "tests/regression/golden_baseline.json",
            "regression_golden_sha256": _sha256_file(golden_path),
            "note": (
                "冻结时点的既有红灯（历史债务）。门禁：本集合之外不允许出现新 diff。"
                "归因见 docs/_regression_drift_S01.md。"
            ),
        },
        "total_diffs": len(diffs),
        "diffs": sorted(diffs),
    }


def write_snapshot(snapshot: Dict[str, Any]) -> str:
    text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=1)
    SNAPSHOT_PATH.write_text(text, encoding="utf-8")
    return sha256_text(text)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_snapshot() -> Dict[str, Any] | None:
    if not SNAPSHOT_PATH.exists():
        return None
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def check() -> Dict[str, Any]:
    """跑一次 regression，比对冻结集合。返回 {ok, new, gone, current_total, frozen_total}."""
    frozen = load_snapshot()
    if frozen is None:
        return {
            "ok": False, "new": ["<缺少 regression_snapshot.json>"], "gone": [],
            "current_total": 0, "frozen_total": 0,
        }

    current = build()
    frozen_set = set(frozen["diffs"])
    current_set = set(current["diffs"])
    new = sorted(current_set - frozen_set)
    gone = sorted(frozen_set - current_set)

    golden_sha_changed = (
        (frozen.get("meta") or {}).get("regression_golden_sha256")
        != (current.get("meta") or {}).get("regression_golden_sha256")
    )
    return {
        "ok": not new and not golden_sha_changed,
        "new": new,
        "gone": gone,
        "current_total": current["total_diffs"],
        "frozen_total": frozen["total_diffs"],
        "golden_sha_changed": golden_sha_changed,
    }
