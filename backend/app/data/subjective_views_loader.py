# -*- coding: utf-8 -*-
"""
解析 data/subjective_views.xlsx（主观观点矩阵模板）。

工作簿结构（与现用 Excel 一致）：
- 填写说明 / 评分标准：说明性内容，导入时忽略
- 观点矩阵：列「观点日期」+ 各资产中文名，单元格为观点分数 -2~2
- 置信度矩阵：同上结构，单元格为置信度约 0.5~1.5
- 观点依据：同上结构，单元格为文字说明（按字符串读取，避免空单元格被解析成日期）

输出为按「观点日期」一条记录，供写入 MongoDB 集合 subjective_views，供回测/策略扩展读取。
主观调仓指令（subjective_overrides）仍为「指定目标权重 + 执行日」，与本文件格式不同。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from app.monitor import config

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_PATH = _PROJECT_ROOT / "data" / "subjective_views.xlsx"

_SHEET_SCORES = "观点矩阵"
_SHEET_CONFIDENCE = "置信度矩阵"
_SHEET_RATIONALE = "观点依据"
_DATE_COL = "观点日期"


def _non_date_columns(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if str(c).strip() != _DATE_COL]


def _norm_date_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d")


def load_subjective_view_matrix(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    读取三个矩阵工作表，按观点日期合并。

    Returns:
        [{ view_date, scores: {资产: int}, confidence: {资产: float}, rationale: {资产: str|None} }, ...]
    """
    p = path or _DEFAULT_PATH
    if not p.exists():
        return []

    try:
        ds = pd.read_excel(p, sheet_name=_SHEET_SCORES)
        dc = pd.read_excel(p, sheet_name=_SHEET_CONFIDENCE)
        dr = pd.read_excel(p, sheet_name=_SHEET_RATIONALE, dtype=object)
    except ValueError as e:
        # 工作表名不匹配时尝试按位置（说明、标准、观点、置信度、依据）
        try:
            xl = pd.ExcelFile(p)
            names = xl.sheet_names
            if len(names) < 5:
                return []
            ds = pd.read_excel(xl, sheet_name=names[2])
            dc = pd.read_excel(xl, sheet_name=names[3])
            dr = pd.read_excel(xl, sheet_name=names[4], dtype=object)
        except Exception:
            raise e from None

    if _DATE_COL not in ds.columns:
        return []

    ds = ds.copy()
    dc = dc.copy()
    dr = dr.copy()
    ds[_DATE_COL] = _norm_date_series(ds[_DATE_COL])
    dc[_DATE_COL] = _norm_date_series(dc[_DATE_COL])
    dr[_DATE_COL] = _norm_date_series(dr[_DATE_COL])

    ds = ds.dropna(subset=[_DATE_COL])
    conf_by_date = {row[_DATE_COL]: row for _, row in dc.dropna(subset=[_DATE_COL]).iterrows()}
    rat_by_date = {row[_DATE_COL]: row for _, row in dr.dropna(subset=[_DATE_COL]).iterrows()}

    records: List[Dict[str, Any]] = []
    for _, row_s in ds.iterrows():
        d = row_s[_DATE_COL]
        if not d or pd.isna(d):
            continue
        date_str = str(d)[:10]
        row_c = conf_by_date.get(date_str)
        row_r = rat_by_date.get(date_str)

        scores: Dict[str, int] = {}
        confidence: Dict[str, float] = {}
        rationale: Dict[str, Optional[str]] = {}

        for col in _non_date_columns(ds):
            key = _resolve_asset_key(str(col))
            if key is None:
                continue
            v = row_s.get(col)
            if pd.notna(v):
                try:
                    scores[key] = int(float(v))
                except (TypeError, ValueError):
                    scores[key] = 0
            else:
                scores[key] = 0

            if row_c is not None and col in row_c.index:
                vc = row_c.get(col)
                if pd.notna(vc):
                    try:
                        confidence[key] = float(vc)
                    except (TypeError, ValueError):
                        confidence[key] = 1.0
                else:
                    confidence[key] = 1.0
            else:
                confidence[key] = 1.0

            if row_r is not None and col in row_r.index:
                vr = row_r.get(col)
                if pd.isna(vr) or vr is None:
                    rationale[key] = None
                else:
                    s = str(vr).strip()
                    rationale[key] = s if s and s.lower() not in ("nan", "nat") else None
            else:
                rationale[key] = None

        # 补全 ASSET_LIST 中未出现在表中的资产
        for a in config.ASSET_LIST:
            if a not in scores:
                scores[a] = 0
            if a not in confidence:
                confidence[a] = 1.0
            if a not in rationale:
                rationale[a] = None

        records.append(
            {
                "view_date": date_str,
                "scores": scores,
                "confidence": confidence,
                "rationale": rationale,
            }
        )

    records.sort(key=lambda x: x["view_date"])
    return records


def _resolve_asset_key(col_name: str) -> Optional[str]:
    c = str(col_name).strip()
    if not c or c == _DATE_COL:
        return None
    if c in config.ASSET_LIST:
        return c
    if c in config.ASSET_CODE_TO_NAME:
        return config.ASSET_CODE_TO_NAME[c]
    if c in config.ASSET_NAME_TO_CODE:
        return c
    return None
