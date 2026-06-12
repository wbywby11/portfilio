"""
将 fixtures 中的主体舆情样例写入 MongoDB collection subject_risk_records。

用法（在 portfilio-end 目录）:
  python scripts/seed_subject_risk_demo.py

优先读取 scripts/fixtures/subject_risk_demo_records.json（数组）；
若不存在则回退 single subject_risk_demo_record.json。

依赖 .env / 环境变量中的 MONGODB_URL、DATABASE_NAME。
按 risk_id upsert，重复执行幂等。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.database import get_sync_db  # noqa: E402

COLLECTION = "subject_risk_records"
FIXTURE_MULTI = ROOT / "scripts" / "fixtures" / "subject_risk_demo_records.json"
FIXTURE_SINGLE = ROOT / "scripts" / "fixtures" / "subject_risk_demo_record.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_docs() -> list[dict]:
    if FIXTURE_MULTI.is_file():
        data = json.loads(FIXTURE_MULTI.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"{FIXTURE_MULTI} 须为 JSON 数组")
        return data
    if not FIXTURE_SINGLE.is_file():
        raise SystemExit(f"缺少样例文件: {FIXTURE_MULTI} 或 {FIXTURE_SINGLE}")
    doc = json.loads(FIXTURE_SINGLE.read_text(encoding="utf-8"))
    if not doc.get("risk_id"):
        raise SystemExit("单文件 fixture 缺少 risk_id")
    return [doc]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    docs = load_docs()
    ts = _now_iso()
    db = get_sync_db()
    coll = db[COLLECTION]

    n = 0
    for doc in docs:
        rid = doc.get("risk_id")
        if not rid:
            print(f"跳过无 risk_id 记录: {doc.get('subject_name')}")
            continue
        patch = {**doc, "_imported_at": doc.get("_imported_at") or ts}
        result = coll.update_one({"risk_id": rid}, {"$set": patch}, upsert=True)
        tag = "upserted" if result.upserted_id else "matched"
        print(f"[{COLLECTION}] risk_id={rid} {tag} modified={result.modified_count}")
        n += 1
    print(f"完成，共写入/更新 {n} 条。可用 subject_risk_search 或 data_query 查 {COLLECTION}。")


if __name__ == "__main__":
    main()
