"""
将 fixtures 中的理财产品样例写入 MongoDB 集合 zysc_ptl_info_records。

用于上游 Hub 502 / 本地无缓存时演示 product_hub_query、整体概况快捷问答等。

用法（在 portfilio-end 目录）:
  python scripts/seed_zysc_ptl_info_demo.py

依赖 .env 中的 MONGODB_URL、DATABASE_NAME（默认库 asset_allocation）。
按 **产品代码** upsert，重复执行幂等。

写入后若 data_query 仍提示集合未注册，启动/重启一次后端，或对话里先执行 data_query discover（会触发 registry 扫描）。
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

COLLECTION = "zysc_ptl_info_records"
PK = "产品代码"
FIXTURE = ROOT / "scripts" / "fixtures" / "zysc_ptl_info_demo_records.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not FIXTURE.is_file():
        raise SystemExit(f"缺少样例文件: {FIXTURE}")

    docs = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if not isinstance(docs, list):
        raise SystemExit(f"{FIXTURE} 须为 JSON 数组")

    ts = _now_iso()
    db = get_sync_db()
    coll = db[COLLECTION]

    n = 0
    for doc in docs:
        code = doc.get(PK)
        if not code:
            print(f"跳过无 {PK} 记录")
            continue
        patch = {**doc, "_imported_at": doc.get("_imported_at") or ts}
        result = coll.update_one({PK: code}, {"$set": patch}, upsert=True)
        tag = "upserted" if result.upserted_id else "matched"
        print(f"[{COLLECTION}] {PK}={code} {tag} modified={result.modified_count}")
        n += 1

    print(
        f"完成，共写入/更新 {n} 条。可用 product_hub_query（建议 skip_upstream_sync=true）"
        f" 或 data_query 查 {COLLECTION}。"
    )
    print("若 data_query 未识别集合：重启后端或先执行 discover。")


if __name__ == "__main__":
    main()
