# -*- coding: utf-8 -*-
"""统一基线 CLI：``check`` / ``rebase`` / ``report`` 三模式，覆盖 engine/model/regression 三层.

    py tests\\execution_baseline\\run_baseline.py check                     # 三层全跑（最终门禁）
    py tests\\execution_baseline\\run_baseline.py check --layer engine      # 每步快跑（零漂移闸门）
    py tests\\execution_baseline\\run_baseline.py check --layer engine,model
    py tests\\execution_baseline\\run_baseline.py rebase --layer engine     # 首次建立 / 显式授权改动
    py tests\\execution_baseline\\run_baseline.py report                    # 诊断：不判失败，只出差异

容差
----
- ``engine``     : ``abs = 0``（float 精确相等）。这是唯一不能砍的闸门。
- ``model``      : ``rel ≤ 1e-9``，零值附近兜底 ``abs ≤ 1e-12``。
- ``regression`` : diff 集合不新增。历史红灯是既有债务，冻结不改。

末行标记（退出码 0/1）
----------------------
    BASELINE OK 3/3
    BASELINE FAIL engine=0 model=1 regression=1

⚠ Windows/PowerShell：loguru 输出到 stderr 会让 ``$LASTEXITCODE`` 呈现假失败，
  以末行标记为准；运行命令统一用 ``py``。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

FINGERPRINT_PATH = HERE / "fingerprint.json"
LAYERS = ("engine", "model", "regression")


# ----------------------------------------------------------------------
#  fingerprint：代码提交 + 数据版本 + 参数
# ----------------------------------------------------------------------

def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(BACKEND_ROOT),
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - git 不可用不阻断基线
        return "<unknown>"


def _global_data_version() -> Dict[str, Any]:
    """集合级数据版本标记：条数 + 最新日期（不落任何写操作）."""
    try:
        from app.services.market_service import MarketService  # noqa: F401
        from app.config.collections import COL_ASSET_PRICES
        from app.config.database import Database
        import asyncio

        Database.connect()

        async def _probe() -> Dict[str, Any]:
            db = Database.get_database()
            col = db[COL_ASSET_PRICES]
            n = await col.count_documents({})
            last = await col.find_one({}, {"date": 1}, sort=[("date", -1)])
            return {"asset_prices_count": int(n),
                    "asset_prices_last_date": str((last or {}).get("date", ""))}

        try:
            return asyncio.run(_probe())
        finally:
            Database.close()
    except Exception as exc:  # noqa: BLE001 - 数据版本是辅助信息，不阻断闸门
        return {"asset_prices_count": -1, "asset_prices_last_date": f"<error: {exc}>"}


def load_fingerprint() -> Dict[str, Any]:
    if not FINGERPRINT_PATH.exists():
        return {}
    return json.loads(FINGERPRINT_PATH.read_text(encoding="utf-8"))


def write_fingerprint(fp: Dict[str, Any]) -> None:
    FINGERPRINT_PATH.write_text(
        json.dumps(fp, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8",
    )


def _layer_fingerprints(existing: Dict[str, Any]) -> Dict[str, Any]:
    """按夹具文件现状重算每一层的 fingerprint 段。

    不跟“本次 rebase 了哪几层”挂钩：fingerprint 描述的是目录里那套夹具的
    当前形态，任何一次 rebase 后都应该整体自洽（否则会留下上次 rebase 的
    残段，比如只有 model 层而 engine 层缺失）。
    """
    from tests.execution_baseline import engine_layer, model_layer, regression_layer

    out: Dict[str, Any] = {}
    if engine_layer.GOLDEN_PATH.exists():
        _, file_sha = engine_layer.load_golden()
        out["engine"] = {
            "file": "tests/execution_baseline/engine_parity.json",
            "sha256": file_sha,
            "tolerance": "abs=0",
        }
    per: Dict[str, Any] = {}
    for spec in model_layer.MODELS:
        golden = model_layer.load_golden(spec.label)
        if golden is None:
            continue
        data = golden.get("data") or {}
        per[spec.label] = {
            "model_id": spec.model_id,
            "kind": spec.kind,
            "file": f"tests/execution_baseline/model_golden/{spec.label}.json",
            "window": [spec.start_date, spec.end_date],
            "n_snapshots": golden.get("n_snapshots"),
            "n_trades": golden.get("n_trades"),
            "data": {
                "first_date": data.get("first_date", ""),
                "last_date": data.get("last_date", ""),
                "n_rows": data.get("n_rows"),
                "close_sha256": data.get("close_sha256", ""),
            },
        }
    if per:
        out["model"] = {
            "dir": "tests/execution_baseline/model_golden",
            "tolerance": "rel<=1e-9 (abs<=1e-12 floor)",
            "models": per,
        }
    if regression_layer.SNAPSHOT_PATH.exists():
        snap = regression_layer.load_snapshot() or {}
        out["regression"] = {
            "file": "tests/execution_baseline/regression_snapshot.json",
            "tolerance": "no-new-diffs",
            "total_diffs": snap.get("total_diffs"),
            "regression_golden_sha256": (snap.get("meta") or {}).get(
                "regression_golden_sha256"
            ),
        }
    return out


# ----------------------------------------------------------------------
#  rebase
# ----------------------------------------------------------------------

def do_rebase(layers: List[str]) -> int:
    from tests.execution_baseline import engine_layer, model_layer, regression_layer

    fp = load_fingerprint()

    if "engine" in layers:
        _, text, sha = engine_layer.build()
        path_sha = engine_layer.write_golden(text)
        print(f"[engine] engine_parity.json 已写入，SHA256={path_sha}")

    if "model" in layers:
        built = model_layer.build()
        for label, payload in built.items():
            sha = model_layer.write_golden(label, payload)
            print(
                f"[model ] {label}: snapshots={payload.get('n_snapshots')} "
                f"trades={payload.get('n_trades')} sha={sha[:16]}"
            )

    if "regression" in layers:
        snap = regression_layer.build()
        sha = regression_layer.write_snapshot(snap)
        print(f"[regress] regression_snapshot.json 已写入，diffs={snap['total_diffs']} sha={sha[:16]}")

    fp.update({
        "schema": 1,
        "rebuilt_at": datetime.now().isoformat(timespec="seconds"),
        "git": {
            "head": _git("rev-parse", "HEAD"),
            "head_short": _git("rev-parse", "--short", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_paths": len([p for p in _git("status", "--porcelain").splitlines() if p]),
        },
        "data_version": _global_data_version(),
        "params": {
            "engine": {
                "price_seed": 20261106, "n_days": 300, "n_assets": 5,
                "start_date": "2022-01-03", "warmup": 60,
                "initial_cash": 10_000_000.0,
            },
            "model": {
                "start_date": model_layer.START_DATE,
                "end_date": model_layer.END_DATE,
                "initial_cash": model_layer.INITIAL_CASH,
                "initial_nav": model_layer.INITIAL_NAV,
                "rtol": model_layer.RTOL, "atol": model_layer.ATOL,
                "models": [
                    {
                        "model_id": m.model_id, "label": m.label, "kind": m.kind,
                        "window": [m.start_date, m.end_date], "why": m.why,
                    }
                    for m in model_layer.MODELS
                ],
            },
        },
        "layers": _layer_fingerprints(fp),
    })
    write_fingerprint(fp)
    print(f"fingerprint.json 已更新: {FINGERPRINT_PATH}")
    print("BASELINE REBASED")
    return 0


# ----------------------------------------------------------------------
#  check
# ----------------------------------------------------------------------

def do_check(layers: List[str]) -> int:
    from tests.execution_baseline import engine_layer, model_layer, regression_layer

    fp = load_fingerprint()
    fp_layers = fp.get("layers") or {}
    verdict: Dict[str, bool] = {}

    if "engine" in layers:
        recorded = (fp_layers.get("engine") or {}).get("sha256")
        res = engine_layer.check(recorded)
        verdict["engine"] = res["ok"]
        print("=" * 72)
        if res["ok"]:
            print(f"[engine] PARITY IDENTICAL  abs=0  sha={res['sha']}")
        else:
            print(f"[engine] PARITY DIFFS: {res['n_diffs']}  sha={res.get('sha')}")
            print(f"[engine] 摘要: {res.get('summary')}")
            if res.get("detail"):
                print(res["detail"])

    if "model" in layers:
        res = model_layer.check()
        verdict["model"] = res["ok"]
        print("=" * 72)
        for label, r in res["per_model"].items():
            if r.get("error"):
                print(f"[model ] {label}: FAIL {r['error']}")
                continue
            flag = "OK  " if r["ok"] else "DRIFT"
            data_note = "  数据已换版(close_sha 变化)" if r.get("data_changed") else ""
            print(
                f"[model ] {label}: {flag} diffs={r['n_diffs']} "
                f"max_rel={r['max_rel']:.3e}{data_note}"
            )
            for d in r["diffs"][:10]:
                extra = f" rel={d['rel']:.3e}" if d.get("rel") is not None else ""
                print(f"           {d['path']}: golden={d['golden']!r} actual={d['actual']!r}{extra}")
        print(f"[model ] {sum(1 for r in res['per_model'].values() if r.get('ok'))}/"
              f"{len(res['per_model'])} 模型在 rel≤{model_layer.RTOL:g} 内")

    if "regression" in layers:
        res = regression_layer.check()
        verdict["regression"] = res["ok"]
        print("=" * 72)
        print(f"[regress] 冻结 diff={res.get('frozen_total')} 本次 diff={res.get('current_total')} "
              f"新增={len(res.get('new') or [])} 消失={len(res.get('gone') or [])}")
        if res.get("golden_sha_changed"):
            print("[regress] regression golden_baseline.json 本身被改动 → 快照失效")
        for d in (res.get("new") or [])[:20]:
            print(f"  + {d}")
        if len(res.get("new") or []) > 20:
            print(f"  ... 另有 {len(res['new']) - 20} 条新增")
        for d in (res.get("gone") or [])[:10]:
            print(f"  - {d}（消失，需在 commit message 说明）")

    print("=" * 72)
    n_ok = sum(1 for v in verdict.values() if v)
    if n_ok == len(verdict):
        print(f"BASELINE OK {n_ok}/{len(verdict)}")
        return 0
    bad = " ".join(f"{k}={'0' if v else '1'}" for k, v in verdict.items())
    print(f"BASELINE FAIL {bad}")
    return 1


# ----------------------------------------------------------------------
#  report
# ----------------------------------------------------------------------

def do_report(layers: List[str]) -> int:
    """诊断模式：跑一遍并把差异全打出来，不判失败（退出码恒 0，除非异常）."""
    from tests.execution_baseline import engine_layer, model_layer, regression_layer

    fp = load_fingerprint()
    print("=" * 72)
    print("统一基线报告")
    print("=" * 72)
    print(f"fingerprint : {FINGERPRINT_PATH}")
    print(f"  rebuilt_at: {fp.get('rebuilt_at')}")
    git = fp.get("git") or {}
    print(f"  git head  : {git.get('head_short')} ({git.get('branch')})  dirty={git.get('dirty_paths')}")
    print(f"  data ver  : {fp.get('data_version')}")
    layers_fp = fp.get("layers") or {}
    for name in LAYERS:
        if name in layers_fp:
            print(f"  layer[{name}]: {json.dumps(layers_fp[name], ensure_ascii=False)[:300]}")
    print(f"  当前 HEAD : {_git('rev-parse', '--short', 'HEAD')}")
    print("-" * 72)

    if "engine" in layers:
        recorded = (layers_fp.get("engine") or {}).get("sha256")
        res = engine_layer.check(recorded)
        print(f"[engine] ok={res['ok']} diffs={res['n_diffs']} sha={res.get('sha')}")
        if res.get("detail"):
            print(res["detail"])

    if "model" in layers:
        res = model_layer.check()
        for label, r in res["per_model"].items():
            if r.get("error"):
                print(f"[model ] {label}: {r['error']}")
                continue
            print(f"[model ] {label}: ok={r['ok']} diffs={r['n_diffs']} max_rel={r['max_rel']:.3e}")
            for d in r["diffs"][:20]:
                print(f"           {d['path']}: {d['golden']!r} -> {d['actual']!r}"
                      f"{' rel=%.3e' % d['rel'] if d.get('rel') is not None else ''}")

    if "regression" in layers:
        res = regression_layer.check()
        print(f"[regress] ok={res['ok']} frozen={res.get('frozen_total')} "
              f"current={res.get('current_total')} new={len(res.get('new') or [])} "
              f"gone={len(res.get('gone') or [])}")
        for d in (res.get("new") or [])[:30]:
            print(f"  + {d}")

    print("-" * 72)
    print("BASELINE REPORT DONE")
    return 0


# ----------------------------------------------------------------------
#  main
# ----------------------------------------------------------------------

def _parse_layers(argv: List[str]) -> List[str]:
    for i, a in enumerate(argv):
        if a == "--layer" and i + 1 < len(argv):
            raw = argv[i + 1]
        elif a.startswith("--layer="):
            raw = a.split("=", 1)[1]
        else:
            continue
        if raw == "all":
            return list(LAYERS)
        picked = [x.strip() for x in raw.split(",") if x.strip()]
        unknown = [x for x in picked if x not in LAYERS]
        if unknown:
            raise SystemExit(f"未知层: {unknown}（可选: {', '.join(LAYERS)},all）")
        return picked
    return list(LAYERS)


def main() -> int:
    import logging

    logging.getLogger().setLevel(logging.WARNING)
    argv = sys.argv[1:]
    mode = argv[0] if argv else ""
    if mode not in ("check", "rebase", "report"):
        print("用法: py tests\\execution_baseline\\run_baseline.py "
              "[check|rebase|report] [--layer engine|model|regression|all]")
        return 2
    layers = _parse_layers(argv[1:])
    if mode == "rebase":
        return do_rebase(layers)
    if mode == "report":
        return do_report(layers)
    return do_check(layers)


if __name__ == "__main__":
    sys.exit(main())
