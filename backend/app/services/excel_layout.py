# -*- coding: utf-8 -*-
"""
资产服务 Mixin：多资产宽表 Excel 布局推断与解析

自 asset_service.py 平移而来，方法体保持不变，仅按职责归组：
1. 单元格类型判定（日期串 / 证券码 / 名称行）
2. 宽表布局推断（Wind 拐角签名、基金/证券双行表头、连续日期推断、3/4/5 回退）
3. 多资产宽表解析为 {code, name, prices} 列表
"""

import io
import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Set, Any

import pandas as pd

from app.services.price_importer import _is_blank_val

MAX_MULTI_ASSET_COLUMNS_PER_SHEET = 512


class ExcelLayoutMixin:
    """Excel 宽表布局推断与解析方法群。

    依赖宿主（AssetService）：无（纯解析逻辑）。
    """

    @staticmethod
    def _cell_as_date_string(val: Any) -> Optional[str]:
        if _is_blank_val(val):
            return None
        if hasattr(val, "strftime"):
            try:
                return val.strftime("%Y-%m-%d")
            except Exception:
                return None
        # Excel 序列日期（A 列为数值）
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            fv = float(val)
            if 20000 < fv < 80000:
                try:
                    base = datetime(1899, 12, 30)
                    return (base + timedelta(days=fv)).strftime("%Y-%m-%d")
                except (OverflowError, ValueError, OSError):
                    pass
        s = str(val).strip()
        if not s:
            return None
        digits = s.replace("-", "").replace("/", "").replace(".", "")[:8]
        if len(digits) == 8 and digits.isdigit():
            try:
                return datetime.strptime(digits, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                return None
        try:
            ts = pd.to_datetime(s, errors="coerce")
            if not pd.isna(ts):
                return pd.Timestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            pass
        return None

    @staticmethod
    def _code_cell_plausible_for_wide_header(val: Any) -> bool:
        """宽表「资产代码」行：排除 Date、纯价格小数、8 位日期串等误识别。"""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return False
        if isinstance(val, float) and val == int(val) and abs(val) < 1e12:
            cs = str(int(val))
        else:
            cs = str(val).strip()
        if re.fullmatch(r"\d+\.0+", cs):
            cs = cs.split(".")[0]
        if not cs or len(cs) < 3:
            return False
        low = cs.lower()
        if low in ("date", "日期", "datetime", "时间"):
            return False
        if re.fullmatch(r"\d{8}", cs):
            return False
        if re.fullmatch(r"\d{1,6}\.\d{2,6}", cs) and not any(
            suf in cs for suf in (".SH", ".SZ", ".CS", ".IB", ".WI", ".OF", ".HK")
        ):
            return False
        # 以中文为主的长串多为资产展示名，不应当作「代码行」判定（避免 Wind 双行表误判为 code_on_row0）
        cjk_n = sum(1 for ch in cs if "\u4e00" <= ch <= "\u9fff")
        if cjk_n >= 4:
            return False
        return True

    @staticmethod
    def _looks_like_exchange_or_wind_symbol(val: Any) -> bool:
        """是否像交易所/Wind 证券码（用于判断双行表头是 code-on-row0 还是 code-on-row1）。"""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return False
        if isinstance(val, float) and val == int(val) and abs(val) < 1e15:
            cs = str(int(val))
        else:
            cs = str(val).strip()
            if re.fullmatch(r"\d+\.0+", cs):
                cs = cs.split(".")[0]
        if not cs:
            return False
        up = cs.upper()
        if any(up.endswith(sfx) for sfx in (".SH", ".SZ", ".CS", ".IB", ".WI", ".OF", ".HK")):
            return True
        if re.fullmatch(r"\d{6}", cs):
            return True
        if re.match(r"^[A-Z]{2,8}\d[A-Z0-9.]*", up):
            return True
        return False

    @staticmethod
    def _name_cell_plausible_for_wide_header(name_val: Any, code_val: Any) -> bool:
        """宽表「资产名称」行：排除 Date、与代码同为价格型数值等。"""
        if name_val is None or (isinstance(name_val, float) and pd.isna(name_val)):
            return False
        ns = str(name_val).strip()
        if not ns or ns in ("Date", "日期") or ns.lower() == "date":
            return False
        c_raw = code_val
        if c_raw is not None and not (isinstance(c_raw, float) and pd.isna(c_raw)):
            cs = str(c_raw).strip()
            try:
                fn = float(ns.replace(",", ""))
                fc = float(cs.replace(",", ""))
                if fn > 50 and fc > 50 and abs(fn - fc) / max(fn, fc) < 0.02:
                    return False
            except ValueError:
                pass
        return True

    @classmethod
    def _wide_layout_has_asset_columns(
        cls, df: "pd.DataFrame", names_row: int, codes_row: int
    ) -> bool:
        """在指定名称行/代码行上是否至少有一列像资产（用于选择固定布局 vs 自动探测）。"""
        if df.shape[0] <= max(names_row, codes_row) or df.shape[1] < 2:
            return False
        max_j = min(df.shape[1], 128)
        for j in range(1, max_j):
            code_cell = df.iloc[codes_row, j]
            if not cls._code_cell_plausible_for_wide_header(code_cell):
                continue
            name_cell = df.iloc[names_row, j]
            if not cls._name_cell_plausible_for_wide_header(name_cell, code_cell):
                continue
            return True
        return False

    def _detect_wide_sheet_layout(self, df: "pd.DataFrame") -> Optional[Tuple[int, int, int]]:
        """
        根据 A 列连续日期行推断「名称行、代码行、数据起始行」。
        成功返回 (names_row_idx, codes_row_idx, data_start_row)；失败返回 None（调用方回退到 3/4/5）。
        """
        max_r = min(len(df), 28)
        for dr in range(max_r - 1):
            d0 = self._cell_as_date_string(df.iloc[dr, 0])
            d1 = self._cell_as_date_string(df.iloc[dr + 1, 0])
            if d0 and d1 and dr >= 2:
                return dr - 2, dr - 1, dr
        return None

    @staticmethod
    def _norm_header_a0(val: Any) -> str:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        return str(val).strip()

    @staticmethod
    def _header_row_contains_keyword(df: "pd.DataFrame", row_idx: int, keys: Tuple[str, ...]) -> bool:
        """表头可能在 A1，也可能因合并单元格落在 B1/C1 等。"""
        if row_idx < 0 or row_idx >= len(df):
            return False
        max_c = min(df.shape[1], 8)
        for col in range(max_c):
            s = ExcelLayoutMixin._norm_header_a0(df.iloc[row_idx, col])
            if any(kw in s for kw in keys):
                return True
        return False

    def _first_data_row_in_column_a(self, df: "pd.DataFrame", from_row: int = 2) -> Optional[int]:
        """自 from_row 起在 A 列找连续两行均为日期的起始行；否则找首个单日。"""
        lim = min(len(df) - 1, from_row + 200)
        for r in range(from_row, lim):
            if self._cell_as_date_string(df.iloc[r, 0]) and self._cell_as_date_string(df.iloc[r + 1, 0]):
                return r
        for r in range(from_row, min(len(df), from_row + 200)):
            if self._cell_as_date_string(df.iloc[r, 0]):
                return r
        return None

    def _try_fund_signature_rows_0_1_col_b(
        self, df: "pd.DataFrame"
    ) -> Optional[Tuple[int, int, int]]:
        """
        图3 等表：首行各列为代码、次行为名称；数据区从 A 列首次出现连续日期行开始（可跳过「日期」表头行）。
        不依赖 A1 是否为「基金代码」（合并后 A1 常为空）。
        """
        if df.shape[0] < 3 or df.shape[1] < 2:
            return None
        data_start = self._first_data_row_in_column_a(df, 2)
        if data_start is None:
            return None
        # 若多数列在「下一行」更像证券码、而首行不像，则不是「首行代码·次行名称」模板（常见于：首行中文名、次行 Wind 码）
        t0 = t1 = 0
        for j in range(1, min(df.shape[1], 64)):
            if self._looks_like_exchange_or_wind_symbol(df.iloc[0, j]):
                t0 += 1
            if self._looks_like_exchange_or_wind_symbol(df.iloc[1, j]):
                t1 += 1
        if t1 >= 2 and t1 > t0:
            return None
        ok = 0
        for j in range(1, min(df.shape[1], 64)):
            c0 = df.iloc[0, j]
            n1 = df.iloc[1, j]
            if self._code_cell_plausible_for_wide_header(c0) and self._name_cell_plausible_for_wide_header(
                n1, c0
            ):
                ok += 1
        if ok < 2:
            return None
        if self._wide_layout_has_asset_columns(df, 1, 0):
            return 1, 0, data_start
        return None

    def _try_date_corner_cn_name_wind_code_rows_0_1(
        self, df: "pd.DataFrame"
    ) -> Optional[Tuple[int, int, int]]:
        """
        Wind/通用导出：A1 为「日期」、A2 为「Date」，第 0 行中文资产名、第 1 行 Wind/交易所代码，自第 3 行起为时间序列。
        （如：大类资产底层数据上传版本.xlsx）
        """
        if df.shape[0] < 3 or df.shape[1] < 2:
            return None
        a0 = self._norm_header_a0(df.iloc[0, 0])
        a1 = self._norm_header_a0(df.iloc[1, 0])
        if "日期" not in a0 and a0 != "日期":
            return None
        if a1.strip().lower() != "date":
            return None
        if not self._wide_layout_has_asset_columns(df, 0, 1):
            return None
        data_start = self._first_data_row_in_column_a(df, 2)
        if data_start is None:
            return None
        return 0, 1, data_start

    def _try_fund_or_security_two_row_header_layout(
        self, df: "pd.DataFrame"
    ) -> Optional[Tuple[int, int, int]]:
        """
        新宽表：前两行表头，A 列（或首几列）为「基金代码/基金名称」等，
        自第 3 行（index 2）起为日期 + 各列行情。返回 (names_row_idx, codes_row_idx, data_start_row)。
        """
        if df.shape[0] < 3 or df.shape[1] < 2:
            return None
        code_like = ("基金代码", "证券代码", "资产代码")
        name_like = ("基金名称", "证券名称", "资产名称")

        # 1) 结构签名：首行代码 + 次行名称 + 第3行 A 为日期（解决 A1 合并为空）
        sig = self._try_fund_signature_rows_0_1_col_b(df)
        if sig:
            return sig

        a0 = self._norm_header_a0(df.iloc[0, 0])
        a1 = self._norm_header_a0(df.iloc[1, 0])

        def has_any(s: str, keys: tuple) -> bool:
            return any(k in s for k in keys)

        # 2) A1/A2 文案（或首行前几列）含基金/证券代码、名称
        row0_kw = has_any(a0, code_like) or self._header_row_contains_keyword(df, 0, code_like)
        row1_kw = has_any(a1, name_like) or self._header_row_contains_keyword(df, 1, name_like)
        if row0_kw and row1_kw:
            dr = self._first_data_row_in_column_a(df, 2)
            if dr is None:
                return None
            names_row, codes_row, data_start = 1, 0, dr
            if self._wide_layout_has_asset_columns(df, names_row, codes_row):
                return names_row, codes_row, data_start

        row0_name = has_any(a0, name_like) or self._header_row_contains_keyword(df, 0, name_like)
        row1_code = has_any(a1, code_like) or self._header_row_contains_keyword(df, 1, code_like)
        if row0_name and row1_code:
            dr = self._first_data_row_in_column_a(df, 2)
            if dr is None:
                return None
            names_row, codes_row, data_start = 0, 1, dr
            if self._wide_layout_has_asset_columns(df, names_row, codes_row):
                return names_row, codes_row, data_start
        return None

    def _resolve_multi_asset_wide_layout(self, df: "pd.DataFrame") -> Tuple[int, int, int]:
        """
        多模板兼容（优先级）：
        1) Wind 导出：行0中文名·行1代码，A1「日期」+ A2「Date」拐角签名
        2) 基金/证券 两行表头 + 第3行起数据（含：首行代码·次行名称等）
        3) Wind 类：名称/代码在 3、4 行，数据自第6行起
        4) A 列连续日期推断 + 名称/代码行校验
        5) 回退 3/4/5
        """
        corner = self._try_date_corner_cn_name_wind_code_rows_0_1(df)
        if corner:
            return corner
        fund = self._try_fund_or_security_two_row_header_layout(df)
        if fund:
            return fund
        if self._wide_layout_has_asset_columns(df, 3, 4):
            return 3, 4, 5
        layout = self._detect_wide_sheet_layout(df)
        if layout:
            nr, cr, dr = layout
            if self._wide_layout_has_asset_columns(df, nr, cr):
                return nr, cr, dr
        return 3, 4, 5

    def _parse_multi_asset_excel(self, contents: bytes, metric: str = "close") -> List[dict]:
        """
        解析多资产宽表 Excel（兼容：Wind「日期/Date」拐角 + 行0中文名·行1 Wind 码；
        Wind 类第4～6行布局；基金/证券代码+名称两行表头自第3行起等）。
        metric：列内数值写入 close / open / high / low / amount / volume / scale。
        """
        metric = (metric or "close").strip().lower()
        allowed_m = {"close", "open", "high", "low", "amount", "volume", "scale"}
        if metric not in allowed_m:
            metric = "close"
        value_key = metric

        buf = io.BytesIO(contents)
        xl_file = pd.ExcelFile(buf)
        sheets = [s for s in xl_file.sheet_names if s]
        assets_with_prices: List[dict] = []
        seen_codes: Set[str] = set()

        _header_tokens_skip = frozenset(
            (
                "date",
                "日期",
                "基金代码",
                "基金名称",
                "证券代码",
                "证券名称",
                "资产代码",
                "资产名称",
            )
        )

        for sheet_name in sheets:
            df = xl_file.parse(sheet_name=sheet_name, header=None)
            if df.shape[0] < 3 or df.shape[1] < 2:
                continue
            names_row_idx, codes_row_idx, data_start_row = self._resolve_multi_asset_wide_layout(df)
            names = df.iloc[names_row_idx].tolist()
            codes = df.iloc[codes_row_idx].tolist()
            dates = df.iloc[data_start_row:, 0].values
            max_col = max(len(names), len(codes))

            for col_idx in range(1, max_col):
                name = names[col_idx] if col_idx < len(names) else None
                code = codes[col_idx] if col_idx < len(codes) else None
                if pd.isna(name) or str(name).strip() == "" or str(name) == "Date":
                    continue
                code_str = str(code).strip() if code is not None and not pd.isna(code) else ""
                name_str = str(name).strip()
                low_name = name_str.lower()
                if low_name in _header_tokens_skip or name_str in _header_tokens_skip:
                    continue
                if not code_str or code_str == "Date" or code_str.lower() in _header_tokens_skip:
                    continue
                if code_str in seen_codes:
                    continue
                values = df.iloc[data_start_row:, col_idx].values
                valid_mask = pd.notna(values) & (values != "")
                if not valid_mask.any():
                    continue
                seen_codes.add(code_str)

                prices = []
                for d, v in zip(dates, values):
                    if pd.isna(v) or v == "":
                        continue
                    try:
                        num_val = float(v)
                    except (TypeError, ValueError):
                        continue
                    date_str = self._to_iso_date(d)
                    rec = {
                        "date": date_str,
                        "open": None,
                        "high": None,
                        "low": None,
                        "close": None,
                        "volume": None,
                        "amount": None,
                        "scale": None,
                    }
                    if value_key == "volume":
                        rec[value_key] = int(round(num_val))
                    else:
                        rec[value_key] = num_val
                    prices.append(rec)
                if prices:
                    assets_with_prices.append({
                        "code": code_str,
                        "name": name_str,
                        "prices": prices,
                        "price_count": len(prices),
                    })
                    if len(assets_with_prices) >= MAX_MULTI_ASSET_COLUMNS_PER_SHEET:
                        break
            if len(assets_with_prices) >= MAX_MULTI_ASSET_COLUMNS_PER_SHEET:
                break
        return assets_with_prices

    @staticmethod
    def _to_iso_date(dt) -> str:
        if _is_blank_val(dt):
            return ""
        if hasattr(dt, "strftime"):
            try:
                return pd.Timestamp(dt).strftime("%Y-%m-%d")
            except Exception:
                try:
                    return dt.strftime("%Y-%m-%d")
                except Exception:
                    return str(dt)[:10]
        if isinstance(dt, str):
            s = dt.strip()
            if s:
                ts = pd.to_datetime(s, errors="coerce")
                if not pd.isna(ts):
                    return ts.strftime("%Y-%m-%d")
            s2 = dt.replace("-", "").replace("/", "").strip()
            if len(s2) == 8 and s2.isdigit():
                return f"{s2[:4]}-{s2[4:6]}-{s2[6:8]}"
        return str(dt)[:10]

