# -*- coding: utf-8 -*-
"""策略可复现性指纹 —— 纯函数集合，无 IO、无状态、无数据库.

统一序列化口径（与 ``published_snapshot.compute_config_fingerprint`` 对齐）：
    ``json.dumps(..., ensure_ascii=False, sort_keys=True, default=str)`` + sha256。

剔除易变键（``frozen_at`` / ``created_at`` / ``updated_at`` / ``published_at`` /
``generated_at``）：同一份配置在两次发布之间只有时间戳不同，若参与计算，
指纹必然漂移，就失去「同配置 ⇒ 同指纹」的判定能力。

``data_digest_v2`` 与旧 ``data_fingerprint``（``backtest_service.py:204-216``）
**两套算法共存，互不替换**：
    - 旧算法只 hash「资产列表 + 起止日期」，与行情数值无关，能检测「换了资产/区间」；
    - 新算法 hash 矩阵内 ``(code, date, close)`` 三元组，能检测「同区间数据被修正」；
    - 旧字段 ``data_fingerprint`` 的算法与写入路径完全不动（B2-1）。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import fields, is_dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "normalize_codes",
    "normalize_fingerprint_payload",
    "pool_hash",
    "contract_hash",
    "param_hash",
    "hash_payload",
    "data_digest_v2",
    "reproducibility_fingerprint",
]

# 易变时间键：参与指纹会让「同一配置」永远算出不同值
_VOLATILE_KEYS = frozenset(
    {
        "frozen_at",
        "created_at",
        "updated_at",
        "published_at",
        "live_published_at",
        "generated_at",
        "digest_computed_at",
    }
)

# data_digest_v2 的 schema 版本，进指纹正文，将来换口径时旧摘要仍可识别
_DATA_DIGEST_SCHEMA = "data_digest_v2"


def _digest_text(text: str) -> str:
    """对一段文本取 sha256（内部摘要用）."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pandas_descriptor(value: Any) -> Dict[str, Any]:
    """pandas 对象 → 稳定描述（类型/形状/列名/索引摘要/数值摘要）.

    不用 ``str(df)`` 作指纹正文：它按显示设置截断行列，两个不同的
    DataFrame 可能得到同一段文本。这里按完整索引与数值取摘要。
    """
    desc: Dict[str, Any] = {
        "__type__": type(value).__name__,
        "shape": [int(size) for size in getattr(value, "shape", ())],
    }
    columns = getattr(value, "columns", None)
    if columns is not None:
        desc["columns"] = [str(col) for col in columns]
    desc["index_digest"] = _digest_text("\n".join(str(idx) for idx in value.index))
    values = value.to_numpy().ravel().tolist() if hasattr(value, "to_numpy") else list(value)
    desc["values_digest"] = _digest_text("\n".join(repr(item) for item in values))
    return desc


def normalize_fingerprint_payload(value: Any) -> Any:
    """递归归一会破坏 JSON 序列化的对象，返回可稳定序列化的结构.

    只处理影响序列化稳定性的类型：pandas DataFrame/Series 转描述字典、
    dataclass 按字段展开，其余原样返回（最终仍由 ``default=str`` 兜底）。
    对不含这些类型的载荷，归一化不改变任何字节，因此不改动既有指纹值。
    """
    if isinstance(value, dict):
        return {str(k): normalize_fingerprint_payload(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_fingerprint_payload(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((normalize_fingerprint_payload(item) for item in value), key=repr)
    if (type(value).__module__ or "").startswith("pandas"):
        return _pandas_descriptor(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field_obj.name: normalize_fingerprint_payload(getattr(value, field_obj.name))
            for field_obj in fields(value)
        }
    return value


def _canonical(payload: Any) -> str:
    """稳定序列化：键排序 + 类型归一 + 非 JSON 类型降级为 str（与发布指纹同口径）."""
    return json.dumps(
        normalize_fingerprint_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def hash_payload(payload: Any) -> str:
    """对任意 JSON 可序列化结构取 sha256（返回 64 位十六进制）."""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def normalize_codes(asset_codes: Optional[Iterable[Any]]) -> List[str]:
    """资产代码归一：去空、去首尾空白、统一大写、排序去重.

    资产池指纹只关心「池子里有谁」，不关心传入顺序，也不关心大小写写法；
    归一后再 hash 才能做到「同一池子、任意输入顺序 ⇒ 同指纹」。
    """
    if not asset_codes:
        return []
    if isinstance(asset_codes, str):
        asset_codes = [asset_codes]
    out = set()
    for raw in asset_codes:
        code = str(raw or "").strip().upper()
        if code:
            out.add(code)
    return sorted(out)


def pool_hash(asset_codes: Optional[Iterable[Any]]) -> Optional[str]:
    """资产池指纹；空池返回 None（「没有池子」与「池子哈希」是两件事）."""
    codes = normalize_codes(asset_codes)
    if not codes:
        return None
    return hash_payload({"schema": "asset_pool_v1", "asset_codes": codes})


def contract_hash(contract: Any) -> Optional[str]:
    """数据契约指纹.

    接受 ``DataContract``（frozen dataclass）或等价的 plain dict；
    其余类型一律返回 None —— 契约不可序列化时宁可留空，也不拼一个
    似是而非的字符串冒充指纹。
    """
    if contract is None:
        return None
    if is_dataclass(contract) and not isinstance(contract, type):
        payload: Dict[str, Any] = {f.name: getattr(contract, f.name) for f in fields(contract)}
    elif isinstance(contract, dict):
        payload = dict(contract)
    else:
        return None
    payload = {k: v for k, v in payload.items() if k not in _VOLATILE_KEYS}
    if not payload:
        return None
    return hash_payload({"schema": "data_contract_v1", "contract": payload})


def param_hash(parameters: Optional[Dict[str, Any]]) -> Optional[str]:
    """参数指纹；空参数返回 None.

    回测试错计数（S17）按本指纹去重：同参数不同区间算同一次尝试。
    """
    if not parameters:
        return None
    payload = {k: v for k, v in dict(parameters).items() if k not in _VOLATILE_KEYS}
    if not payload:
        return None
    return hash_payload({"schema": "param_v1", "parameters": payload})


# ---------------------------------------------------------------------------
# 行情矩阵摘要（S10）
# ---------------------------------------------------------------------------


def _close_series(frame: Any) -> Any:
    """从 DataFrame 里取收盘价序列；取不到返回 None."""
    if frame is None:
        return None
    if hasattr(frame, "columns"):
        cols = list(frame.columns)
        lowered = {str(c).strip().lower(): c for c in cols}
        for key in ("close", "closeprice", "adj_close"):
            if key in lowered:
                return frame[lowered[key]]
        return None
    # 已是 Series
    return frame if hasattr(frame, "index") else None


def _to_date_str(value: Any) -> Optional[str]:
    """索引值转 ``YYYY-MM-DD``；失败返回 None（该行跳过，不污染摘要）."""
    try:
        import pandas as pd

        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001 —— 单行日期异常不该拖垮整份摘要
        text = str(value or "")[:10]
        return text or None


def _iter_price_series(prices: Any) -> Iterable[Tuple[str, Any]]:
    """把价格入参归一为 ``(asset_code, 收盘价序列)`` 迭代.

    支持两种实际存在的形态：

    - **宽表 DataFrame**（index=日期，columns=资产代码）：``DataFeed.strategy_prices``
      的真实形态，逐列取序列；
    - ``{asset_code: DataFrame|Series}``：DataFrame 取 close 列，Series 直接用。

    Raises:
        TypeError: 入参不是上述两种形态。宁可显式报错（调用方转为告警），
            也不静默返回空摘要冒充「数据已对齐」。
    """
    if hasattr(prices, "columns") and hasattr(prices, "__getitem__"):
        for col in list(prices.columns):
            code = str(col if col is not None else "").strip().upper()
            if code:
                yield code, prices[col]
        return
    if isinstance(prices, dict):
        for raw_code, frame in prices.items():
            code = str(raw_code if raw_code is not None else "").strip().upper()
            if not code:
                continue
            series = _close_series(frame)
            if series is not None:
                yield code, series
        return
    raise TypeError(f"data_digest_v2 不支持的价格形态: {type(prices).__name__}")


def data_digest_v2(
    prices: Any,
    start_date: Any = None,
    end_date: Any = None,
) -> Optional[str]:
    """行情矩阵摘要：hash ``strategy_prices`` 在回测区间内（**不含 lookback**）的
    ``(asset_code, date, close)`` 稳定序列.

    Args:
        prices: 宽表 DataFrame（index=日期，columns=资产代码，即
            ``DataFeed.strategy_prices`` 的形态），也接受
            ``{asset_code: DataFrame|Series}``。
        start_date / end_date: 回测区间端点（含端点）；为 None 表示不截断。

    Returns:
        64 位十六进制摘要；矩阵为空或无收盘价列时返回 None。
    """
    if prices is None or len(prices) == 0:
        return None
    start = _to_date_str(start_date) if start_date is not None else None
    end = _to_date_str(end_date) if end_date is not None else None

    rows: List[Tuple[str, str, float]] = []
    for code, series in _iter_price_series(prices):
        if series is None:
            continue
        try:
            index = list(getattr(series, "index", []))
            values = list(getattr(series, "values", []))
        except Exception:  # noqa: BLE001
            continue
        for idx_value, close in zip(index, values):
            date_str = _to_date_str(idx_value)
            if not date_str:
                continue
            if start and date_str < start:
                continue
            if end and date_str > end:
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if math.isnan(close_f) or math.isinf(close_f):
                continue
            # 保留 6 位小数：消除 float 展开形式差异，又不丢价格精度
            rows.append((code, date_str, round(close_f, 6)))
    if not rows:
        return None
    rows.sort(key=lambda r: (r[0], r[1]))
    return hash_payload(
        {
            "schema": _DATA_DIGEST_SCHEMA,
            "window": {"start": start, "end": end},
            "rows": [[c, d, v] for c, d, v in rows],
        }
    )


def reproducibility_fingerprint(
    config_fingerprint: Optional[str],
    pool_hash_value: Optional[str] = None,
    contract_hash_value: Optional[str] = None,
    param_hash_value: Optional[str] = None,
    engine_version: Optional[str] = None,
    data_digest: Optional[str] = None,
) -> Optional[str]:
    """可复现性指纹：把「配置 + 池子 + 契约 + 参数 + 引擎版本 + 数据摘要」串成一把钥匙.

    六个键**始终全部出现**（缺项写 None），这样「缺引擎版本」与「引擎版本是
    空串」不会算出同一个指纹；只有配置指纹本身缺失时才返回 None（没有配置
    版本就无从谈复现）。
    """
    if not config_fingerprint:
        return None
    return hash_payload(
        {
            "schema": "reproducibility_v1",
            "config_fingerprint": config_fingerprint,
            "asset_pool_hash": pool_hash_value,
            "contract_hash": contract_hash_value,
            "param_hash": param_hash_value,
            "engine_version": engine_version,
            "data_digest": data_digest,
        }
    )
