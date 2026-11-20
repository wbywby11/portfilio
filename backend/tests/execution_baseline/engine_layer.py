# -*- coding: utf-8 -*-
"""引擎层 parity：迁移自 ``tests/execution_parity``，闸门语义不变（abs=0）.

输入构造与比对内核仍由 ``tests.execution_parity.builders`` / ``compare`` 承担——
它们是「夹具生成器」而不是「基线」，把夹具文件与 CLI 收进本包即可完成统一，
无需搬家 700 行输入构造代码（搬会直接威胁零漂移这条唯一不能砍的断言）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

GOLDEN_PATH = HERE / "engine_parity.json"


def canonical(obj: Any) -> str:
    """稳定序列化：键排序、无空白、非 ASCII 原样保留.

    ``json.dumps`` 对 float 走 ``repr``，Python float 往返无损，
    因此夹具不会因序列化削弱 ``abs=0`` 断言。
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build() -> Tuple[Dict[str, Any], str, str]:
    """跑四路径，返回 (基线结构, 规范化文本, SHA256)."""
    from tests.execution_parity.builders import build_baseline

    data = build_baseline()
    text = canonical(data)
    return data, text, sha256_text(text)


def load_golden() -> Tuple[Dict[str, Any], str]:
    """读夹具，返回 (结构, 夹具文件字节的 SHA256)."""
    raw = GOLDEN_PATH.read_text(encoding="utf-8")
    return json.loads(raw), sha256_text(raw)


def write_golden(text: str) -> str:
    GOLDEN_PATH.write_text(text, encoding="utf-8")
    return sha256_text(text)


def check(recorded_sha: str | None = None) -> Dict[str, Any]:
    """比对夹具，返回 {ok, sha, recorded_sha, n_diffs, summary, detail}.

    ``recorded_sha`` 来自 ``fingerprint.json``；与夹具字节 SHA 不一致即视为
    夹具被手改（不接受「改夹具让门禁变绿」）。
    """
    from tests.execution_parity.compare import compare, format_diffs, summarize

    if not GOLDEN_PATH.exists():
        return {
            "ok": False, "sha": "", "recorded_sha": recorded_sha or "",
            "n_diffs": 1, "summary": {}, "detail": f"夹具不存在: {GOLDEN_PATH}",
        }

    golden, file_sha = load_golden()
    _, actual_text, actual_sha = build()
    actual = json.loads(actual_text)
    diffs = compare(golden, actual)

    notes: List[str] = []
    if recorded_sha and recorded_sha != file_sha:
        notes.append(
            f"夹具文件 SHA256 与 fingerprint.json 记录不一致（夹具可能被手改）："
            f"文件={file_sha} 记录={recorded_sha}"
        )

    return {
        "ok": not diffs and not notes,
        "sha": actual_sha,
        "file_sha": file_sha,
        "recorded_sha": recorded_sha or "",
        "n_diffs": len(diffs),
        "summary": summarize(diffs) if diffs else {},
        "detail": "\n".join(notes + ([format_diffs(diffs)] if diffs else [])),
    }
