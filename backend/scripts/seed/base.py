# -*- coding: utf-8 -*-
"""
Seed 脚本基类 —— 统一连接管理、批量写入、审计日志、统计输出

所有 seed/import 脚本继承 SeedBase，获得：
- MongoDB 连接（从 settings 或 CLI 参数）
- BulkWrite upsert（每批 ≤ 1000）
- 审计日志写入（_import_audit_log）
- 标准统计输出（total/inserted/updated/skipped/errors）
- --dry-run 模式
- 日期归一化工具

用法：
    class MySeed(SeedBase):
        name = "my_data"
        target_collection = "my_collection"

        def parse(self, file_path: Path) -> list[dict]:
            ...

        def build_ops(self, records: list[dict]) -> list[UpdateOne]:
            ...

    if __name__ == "__main__":
        MySeed.run()
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pymongo import MongoClient, UpdateOne

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import settings  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def normalize_date(value: Any) -> Optional[str]:
    """
    将多种日期格式归一化为 'YYYY-MM-DD' 字符串。
    支持：YYYY-MM-DD、YYYYMMDD、Excel 序列日、datetime、Timestamp。
    返回 None 表示无法解析。
    """
    import pandas as pd

    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        # YYYYMMDD
        if len(value) == 8 and value.isdigit():
            value = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
        try:
            ts = pd.Timestamp(value)
            return ts.strftime("%Y-%m-%d")
        except Exception:
            return None
    if isinstance(value, (int, float)):
        # Excel 序列日
        try:
            ts = pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(value))
            return ts.strftime("%Y-%m-%d")
        except Exception:
            return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    try:
        ts = pd.Timestamp(value)
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 基类
# ─────────────────────────────────────────────────────────────────────────────

class SeedBase:
    """
    生产数据导入脚本基类。

    子类须设置：
        name: str               — 脚本名称（用于日志和审计）
        target_collection: str  — 目标集合名

    子类须实现：
        parse(file_path) -> list[dict]       — 解析文件为记录列表
        build_ops(records) -> list[UpdateOne] — 构建 BulkWrite 操作

    可选覆盖：
        validate(records) -> (valid, errors)  — 校验，返回有效记录和错误列表
        post_import(stats)                    — 导入后钩子
    """

    name: str = "unnamed_seed"
    target_collection: str = ""
    batch_size: int = 1000
    description: str = ""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.dry_run: bool = args.dry_run
        self.mongo_uri: str = args.mongo_uri
        self.db_name: str = args.db
        self._client: Optional[MongoClient] = None
        self._db = None

    # ─── 连接管理 ─────────────────────────────────────────────────────────────

    @property
    def client(self) -> MongoClient:
        if self._client is None:
            self._client = MongoClient(self.mongo_uri)
        return self._client

    @property
    def db(self):
        if self._db is None:
            self._db = self.client[self.db_name]
        return self._db

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
            self._db = None

    # ─── 子类实现 ─────────────────────────────────────────────────────────────

    def parse(self, file_path: Path) -> List[Dict[str, Any]]:
        """解析输入文件，返回记录列表。子类必须实现。"""
        raise NotImplementedError

    def build_ops(self, records: List[Dict[str, Any]]) -> List[UpdateOne]:
        """构建 BulkWrite UpdateOne 操作列表。子类必须实现。"""
        raise NotImplementedError

    def validate(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        校验记录。返回 (valid_records, error_list)。
        默认实现：全部通过。
        """
        return records, []

    def post_import(self, stats: Dict[str, int]) -> None:
        """导入完成后的钩子（如验证、打印抽样）。默认无操作。"""
        pass

    # ─── 审计日志 ─────────────────────────────────────────────────────────────

    def write_audit_log(
        self,
        stats: Dict[str, int],
        source_filename: Optional[str] = None,
        date_range: Optional[str] = None,
        duration_ms: int = 0,
        error_summary: Optional[List[str]] = None,
    ) -> None:
        """写入 _import_audit_log 集合"""
        if self.dry_run:
            return
        try:
            doc = {
                "target_collection": self.target_collection,
                "import_mode": getattr(self.args, "mode", "upsert"),
                "source_type": "script",
                "source_filename": source_filename,
                "operator": f"script:{self.name}",
                "created_at": datetime.now(),
                "stats": stats,
                "error_summary": (error_summary or [])[:10],
                "date_range": date_range,
                "duration_ms": duration_ms,
            }
            self.db["_import_audit_log"].insert_one(doc)
        except Exception as e:
            print(f"  [warn] 审计日志写入失败（不影响主流程）: {e}")

    # ─── 核心执行 ─────────────────────────────────────────────────────────────

    def execute(self, file_path: Path) -> Dict[str, int]:
        """执行完整导入流程，返回统计字典。"""
        t0 = time.time()
        print(f"\n{'='*60}")
        print(f"[{self.name}] 开始 {'(dry-run)' if self.dry_run else ''}")
        print(f"  文件: {file_path}")
        print(f"  目标: {self.db_name}.{self.target_collection}")
        print(f"{'='*60}")

        # ① 解析
        print("  ① 解析文件...")
        records = self.parse(file_path)
        total = len(records)
        print(f"     解析到 {total} 条记录")

        if total == 0:
            print("  [skip] 无数据，退出。")
            return {"total_rows": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": 0}

        # ② 校验
        print("  ② 校验...")
        valid_records, errors = self.validate(records)
        skipped = total - len(valid_records) - len(errors)
        if errors:
            print(f"     错误 {len(errors)} 条（前5条）:")
            for err in errors[:5]:
                print(f"       - {err}")
        if skipped > 0:
            print(f"     跳过 {skipped} 条")

        # ③ 构建操作
        print("  ③ 构建写入操作...")
        ops = self.build_ops(valid_records)
        print(f"     共 {len(ops)} 个 upsert 操作")

        # ④ 写入
        inserted = 0
        updated = 0
        if self.dry_run:
            print("  ④ [dry-run] 跳过写入")
        else:
            print("  ④ 写入 MongoDB...")
            coll = self.db[self.target_collection]
            for i in range(0, len(ops), self.batch_size):
                chunk = ops[i:i + self.batch_size]
                result = coll.bulk_write(chunk, ordered=False)
                inserted += result.upserted_count
                updated += result.modified_count
                done = min(i + self.batch_size, len(ops))
                if len(ops) > self.batch_size:
                    print(f"     进度: {done}/{len(ops)}")

        # ⑤ 统计
        duration_ms = int((time.time() - t0) * 1000)
        stats = {
            "total_rows": total,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "errors": len(errors),
        }

        # ⑥ 审计日志
        self.write_audit_log(
            stats=stats,
            source_filename=file_path.name,
            duration_ms=duration_ms,
            error_summary=[str(e) for e in errors[:10]],
        )

        # ⑦ 输出
        print(f"\n  结果: total={total} inserted={inserted} updated={updated} "
              f"skipped={skipped} errors={len(errors)} ({duration_ms}ms)")

        # ⑧ 钩子
        self.post_import(stats)

        return stats

    # ─── CLI 入口 ─────────────────────────────────────────────────────────────

    @classmethod
    def make_parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description=cls.description or f"{cls.name} 数据导入"
        )
        parser.add_argument(
            "--file", "-f", type=str, required=True,
            help="输入文件路径（Excel/CSV）"
        )
        parser.add_argument(
            "--mongo-uri", type=str, default=settings.MONGODB_URL,
            help=f"MongoDB URI（默认: {settings.MONGODB_URL}）"
        )
        parser.add_argument(
            "--db", type=str, default=settings.DATABASE_NAME,
            help=f"数据库名（默认: {settings.DATABASE_NAME}）"
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="只解析校验，不写库"
        )
        parser.add_argument(
            "--mode", type=str, default="upsert",
            choices=["upsert", "replace", "incremental"],
            help="导入模式（默认: upsert）"
        )
        return parser

    @classmethod
    def run(cls):
        """CLI 入口"""
        parser = cls.make_parser()
        args = parser.parse_args()

        file_path = Path(args.file)
        if not file_path.is_file():
            print(f"错误: 文件不存在 {file_path}")
            sys.exit(1)

        instance = cls(args)
        try:
            stats = instance.execute(file_path)
            if stats["errors"] > 0:
                sys.exit(2)  # 有错误但部分成功
        finally:
            instance.close()
