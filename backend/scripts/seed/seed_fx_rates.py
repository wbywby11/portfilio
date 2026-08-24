# -*- coding: utf-8 -*-
"""
汇率数据初始化 / 增量导入

目标集合: fx_rates
幂等键:   date（字符串 'YYYY-MM-DD'，唯一）
输入格式: Excel，第一列为日期，后续列为币种（EUR/USD/HKD/JPY/CNH）

Excel 模板：
  日期       | EUR    | USD    | HKD    | JPY    | CNH
  2024-01-02 | 7.8521 | 7.0892 | 0.9078 | 0.0486 | 1.0
  2024-01-03 | 7.8455 | 7.0876 | 0.9075 | 0.0485 | 1.0
  ...

说明：
  - 汇率为各币种兑人民币汇率
  - CNH（离岸人民币）通常为 1.0
  - 增量模式（默认）：不覆盖已有数值，仅填补空缺
  - upsert 模式：覆盖已有数值

用法：
    python -m scripts.seed.seed_fx_rates --file data/seed/fx_rates.xlsx
    python -m scripts.seed.seed_fx_rates --file data/seed/fx_rates.xlsx --dry-run
    python -m scripts.seed.seed_fx_rates --file data/seed/fx_rates.xlsx --mode upsert
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from pymongo import UpdateOne

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.seed.base import SeedBase, normalize_date  # noqa: E402

# 支持的币种列（与 FxService.FX_COLUMNS 一致）
FX_COLUMNS = ["EUR", "USD", "HKD", "JPY", "CNH"]

# 日期列映射
_DATE_MAPPING = {
    "日期": "date",
    "日期*": "date",
    "Date": "date",
    "DATE": "date",
    "date": "date",
    "交易日期": "date",
}


class SeedFxRates(SeedBase):
    name = "seed_fx_rates"
    target_collection = "fx_rates"
    description = "汇率数据导入（fx_rates 集合）"

    def parse(self, file_path: Path) -> List[Dict[str, Any]]:
        df = pd.read_excel(file_path)
        df.columns = df.columns.astype(str).str.strip()

        # 映射日期列
        df.rename(columns=_DATE_MAPPING, inplace=True)
        if "date" not in df.columns:
            raise ValueError("缺少必须列: 日期（date）")

        # 标准化币种列名（大写）
        rename_map = {}
        for col in df.columns:
            upper = col.upper().strip()
            if upper in FX_COLUMNS:
                rename_map[col] = upper
        df.rename(columns=rename_map, inplace=True)

        # 检查至少有一个币种列
        present = [c for c in FX_COLUMNS if c in df.columns]
        if not present:
            raise ValueError(f"缺少币种列，须至少包含 {FX_COLUMNS} 之一")

        # 日期归一化
        df["date"] = df["date"].apply(normalize_date)
        df = df.dropna(subset=["date"])
        df = df[df["date"].notna() & (df["date"] != "")]
        df = df.drop_duplicates(subset=["date"], keep="first")

        # 只保留需要的列
        cols = ["date"] + present
        return df[cols].to_dict("records")

    def validate(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        valid = []
        errors = []
        for i, rec in enumerate(records):
            date_str = rec.get("date", "")
            if not date_str:
                errors.append(f"行{i}: 日期为空")
                continue

            # 至少有一个有效汇率值
            has_value = False
            for col in FX_COLUMNS:
                v = rec.get(col)
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    try:
                        fv = float(v)
                        if fv > 0:
                            has_value = True
                            rec[col] = fv
                        else:
                            rec[col] = None
                    except (TypeError, ValueError):
                        rec[col] = None
                else:
                    rec[col] = None

            if not has_value:
                errors.append(f"行{i} [{date_str}]: 无任何有效汇率值")
                continue

            valid.append(rec)
        return valid, errors

    def build_ops(self, records: List[Dict[str, Any]]) -> List[UpdateOne]:
        ops = []
        mode = getattr(self.args, "mode", "upsert")

        for rec in records:
            date_str = rec["date"]
            # 构建 $set 文档（仅含非 None 值）
            set_doc = {"date": date_str}
            for col in FX_COLUMNS:
                v = rec.get(col)
                if v is not None:
                    set_doc[col] = v

            if mode == "incremental":
                # 增量模式：仅填补空缺，不覆盖已有值
                # 使用 $setOnInsert 只在文档不存在时写入
                ops.append(UpdateOne(
                    {"date": date_str},
                    {"$setOnInsert": set_doc},
                    upsert=True,
                ))
            else:
                # upsert 模式：覆盖已有值
                ops.append(UpdateOne(
                    {"date": date_str},
                    {"$set": set_doc},
                    upsert=True,
                ))
        return ops

    def post_import(self, stats: Dict[str, int]) -> None:
        if self.dry_run:
            return
        total = self.db[self.target_collection].count_documents({})
        # 抽样最新 3 条
        samples = list(
            self.db[self.target_collection].find().sort("date", -1).limit(3)
        )
        print(f"  [verify] fx_rates 集合当前共 {total} 条")
        if samples:
            print("  [verify] 最新 3 条:")
            for s in samples:
                parts = [f"{c}={s.get(c, '-')}" for c in FX_COLUMNS if s.get(c)]
                print(f"    {s['date']}: {', '.join(parts)}")


if __name__ == "__main__":
    SeedFxRates.run()
