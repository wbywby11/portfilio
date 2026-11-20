"""DataFeed：行情矩阵供给与清洗（计算内核层，模式无关）.

向引擎提供价格矩阵与价格日历（``data_feed.prices.index`` 即完整行情交易日），
含异常值清洗（sanitize_prices / strip_invalid_values）与技术列构建。
数据源可由 MarketService 或上游注入，引擎不感知来源。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from typing import Dict, Iterator, List, Optional, Tuple

import pandas as pd
import numpy as np

from app.services.market_service import MarketService
from app.backtesting.config import BacktestConfig
from app.backtesting.types import Bar

logger = logging.getLogger(__name__)

# 单资产单日涨跌幅超过此阈值视为异常，用前一日价格填充，避免异常导致净值/年化收益/波动率失真
_MAX_DAILY_PRICE_CHANGE = 0.5  # 50%


# ─────────────────────────────────────────────────────────────────
# 非价格截面面板加载（按策略声明驱动，新增面板只注册加载器）
# ─────────────────────────────────────────────────────────────────

def _period_panels(
    frame: pd.DataFrame,
    period_col: str,
    index_col: str,
    columns: List[str],
    null_fill_cols: Tuple[str, ...] = (),
) -> Dict[pd.Timestamp, pd.DataFrame]:
    """整表按 ``period_col`` 切片成 {期日: DataFrame(index=index_col)}.

    逐期 ``pd.DataFrame(list_of_dict)`` 会按「行数 × 期数」重复建表；整表只
    建一次后按期切片，每期仅复制列数组的连续片段。期日键为
    ``pd.Timestamp``，期序按期的升序，期内行序保持原表顺序。

    Args:
        frame: 已清洗好的整表（需包含 ``period_col`` / ``index_col`` / ``columns``）
        period_col: 分期列（datetime64）
        index_col: 每期面板的索引列
        columns: 每期保留的数据列，顺序即面板列顺序
        null_fill_cols: 这些列在某期内全为空时，旧逐行建表会得到 object
            dtype（None），整表建表则是 float64（NaN）。两者数值等价，
            此处按旧语义回填 object/None 以保持面板逐位一致。

    Returns:
        期日 → 截面 DataFrame
    """
    ordered = frame.sort_values(period_col, kind="mergesort")
    group_ids, keys = pd.factorize(
        ordered[period_col], sort=False, use_na_sentinel=False
    )
    bounds = np.concatenate(
        ([0], np.cumsum(np.bincount(group_ids, minlength=len(keys))))
    ).astype(int)
    index_values = ordered[index_col].to_numpy(dtype=object)
    arrays = {col: ordered[col].to_numpy() for col in columns}
    all_null = {}
    for col in null_fill_cols:
        present = np.bincount(
            group_ids,
            weights=(~pd.isna(arrays[col])).astype(float),
            minlength=len(keys),
        )
        all_null[col] = present == 0

    panels: Dict[pd.Timestamp, pd.DataFrame] = {}
    for i, key in enumerate(keys):
        pos = slice(bounds[i], bounds[i + 1])
        panel = pd.DataFrame(
            {col: arrays[col][pos] for col in columns},
            index=pd.Index(index_values[pos], name=index_col),
        )
        for col in null_fill_cols:
            if all_null[col][i]:
                panel[col] = pd.Series(None, index=panel.index, dtype=object)
        panels[pd.Timestamp(key)] = panel
    return panels

async def _load_factor_panel(
    config: BacktestConfig, dataset: str
) -> Dict[pd.Timestamp, pd.DataFrame]:
    """从 factor_panel 集合加载指定数据集的全部期截面，按 as_of_date 分组。

    每期构建一个 DataFrame：index=code，列含 industry / total_mv /
    free_float_mv / data_date / name 与全部因子键（factors dict 展平为列）。
    策略在 allocate 内按 as_of 取「≤ as_of 的最近一期」，此处不做期筛选。

    Args:
        config: 回测配置（本加载器不消费，保留形参以统一加载器签名）
        dataset: 数据集标识，必填。本集合被多个数据集共用，不带 dataset 会把
            其他数据集同一期日的行并进同一截面

    Raises:
        ValueError: dataset 为空
    """
    from collections import defaultdict

    from app.config.collections import COL_FACTOR_PANEL
    from app.config.database import Database

    name = str(dataset or "").strip()
    if not name:
        raise ValueError(
            "factor_panel 加载必须指定 dataset：集合被多个数据集共用，全表加载"
            "会把其他数据集同一期日的行混进截面。请在策略类的 "
            "get_panel_datasets() 中声明，可选值见 field_mappings.FACTOR_DATASETS"
        )

    db = Database.get_database()
    collection = db[COL_FACTOR_PANEL]
    docs = await collection.find({"dataset": name}, {"_id": 0}).to_list(length=None)
    if not docs:
        return {}

    # 截面建表改为一次性构造 + 按期数组切片：逐期 pd.DataFrame(list_of_dict)
    # 会按期数重复建表（实测 4812+3342+22 次）。
    raw = pd.DataFrame(docs)
    base_cols = ["code", "industry", "total_mv", "free_float_mv", "data_date", "name"]
    for col in base_cols:
        if col not in raw.columns:
            raw[col] = None
    base = raw[base_cols]
    raw_factors = raw["factors"] if "factors" in raw.columns else [{}] * len(raw)
    factors = pd.DataFrame(list(raw_factors))
    # 因子键与固定列同名时因子值优先（与逐行 row.update 同义），
    # 但列位置保留在固定列处，列顺序与逐行版本一致
    overlap = [col for col in factors.columns if col in base_cols]
    new_factor_cols = [col for col in factors.columns if col not in base_cols]
    combined = pd.concat([base, factors[new_factor_cols]], axis=1)
    for col in overlap:
        combined[col] = factors[col]
    combined["_as_of"] = pd.to_datetime(raw["as_of_date"])
    data_cols = [col for col in combined.columns if col not in ("_as_of", "code")]
    return _period_panels(combined, "_as_of", "code", data_cols)


async def _load_macro_series(
    config: BacktestConfig, dataset: str
) -> Dict[pd.Timestamp, pd.DataFrame]:
    """从 macro_series 集合加载宏观/估值序列，按日期分组。

    每期构建一个 DataFrame：index=序列代码（已转大写），列含 value /
    series_type / unit。策略在 allocate 内按 ``_as_of`` 回看已注入的期日取
    分位数或阈值，此处不做日期筛选。

    不做日期裁剪的理由：回测需要回看窗口（如 PE 三年分位需 750 个期日），
    而加载器拿不到策略声明的窗口长度；监控通道 config 为 None，裁剪会让两条
    通道拿到的历史长度不同。序列总量级为「序列数 × 交易日数」（十条序列
    十年约 2.5 万条），全量加载的代价远小于两通道取数口径分叉。

    Args:
        config: 回测配置（本加载器不消费，保留形参以统一加载器签名）
        dataset: 忽略——macro_series 一个集合装多条序列，用 code 区分而非 dataset
    """
    from app.config.collections import COL_MACRO_SERIES
    from app.config.database import Database

    db = Database.get_database()
    collection = db[COL_MACRO_SERIES]
    docs = await collection.find(
        {}, {"_id": 0, "code": 1, "date": 1, "value": 1, "series_type": 1, "unit": 1}
    ).sort([("date", 1), ("code", 1)]).to_list(length=None)
    if not docs:
        return {}

    # 整表只建一次，再按期切片：逐期 pd.DataFrame(list_of_dict) 是 4812 次
    # 重复建表（实测占面板加载的绝大部分）。
    frame = pd.DataFrame(docs)
    if "date" not in frame.columns or "value" not in frame.columns:
        return {}

    # 原实现逐条 float() 后丢弃 None / 非数值 / NaN / inf，此处等价地下推给 pandas
    value = pd.to_numeric(frame["value"], errors="coerce")
    keep = value.notna() & np.isfinite(value)
    if not keep.any():
        return {}
    frame = frame.loc[keep].copy()
    frame["value"] = value.loc[keep].astype(float)
    frame["code"] = frame["code"].fillna("").astype(str).str.strip().str.upper()
    frame["_period"] = pd.to_datetime(frame["date"])
    for col in ("series_type", "unit"):
        if col not in frame.columns:
            frame[col] = None

    return _period_panels(frame, "_period", "code", ["value", "series_type", "unit"])


async def _load_asset_metrics(
    config: BacktestConfig, dataset: str
) -> Dict[pd.Timestamp, pd.DataFrame]:
    """从 asset_prices 加载 OHLC/成交额辅助面板，按日期分组。

    价格矩阵只承载收盘价，但部分原型信号依赖日内高低点与成交额（如 ATR
    型形态识别、成交额占比）。本加载器把 ``asset_prices`` 里已导入的
    ``high`` / ``low`` / ``amount`` 按「日期 → 截面」供给策略，index 为
    ``asset_code``，列固定为 ``high`` / ``low`` / ``amount``（缺失为 NaN）。

    只取三项任一非空的记录：纯收盘价的资产不进面板，避免把全库几百万条
    价格记录物化进内存。不做日期裁剪的理由与 ``_load_macro_series`` 一致：
    策略需要回看窗口，监控通道拿不到窗口声明。

    Args:
        config: 回测配置（本加载器不消费，保留形参以统一加载器签名）
        dataset: 忽略——一个集合装全部资产的 OHLC，用 code 区分而非 dataset
    """
    from app.config.collections import COL_ASSET_PRICES
    from app.config.database import Database

    db = Database.get_database()
    collection = db[COL_ASSET_PRICES]
    docs = await collection.find(
        {
            "$or": [
                {"high": {"$ne": None}},
                {"low": {"$ne": None}},
                {"amount": {"$ne": None}},
            ]
        },
        {"_id": 0, "asset_code": 1, "date": 1, "high": 1, "low": 1, "amount": 1},
    ).to_list(length=None)
    if not docs:
        return {}

    # 整表只建一次，再按期切片：逐期 pd.DataFrame(list_of_dict) 是 3342 次
    # 重复建表。
    frame = pd.DataFrame(docs)
    if "date" not in frame.columns:
        return {}
    data_cols = ["high", "low", "amount"]
    for col in ["asset_code"] + data_cols:
        if col not in frame.columns:
            frame[col] = None
    frame["_period"] = pd.to_datetime(frame["date"]).dt.normalize()

    return _period_panels(
        frame, "_period", "asset_code", data_cols, null_fill_cols=tuple(data_cols)
    )


# 面板名 → 加载器。新增非价格截面数据只在此注册，不动行情链路。
# 加载器签名统一为 (config, dataset)；不按数据集分区的面板忽略 dataset 形参即可。
PANEL_LOADERS = {
    "factor_panel": _load_factor_panel,
    "macro_series": _load_macro_series,
    "asset_metrics": _load_asset_metrics,
}

# 必须按 dataset 分区加载的面板：策略须在 get_panel_datasets() 声明读哪个数据集。
# 缺声明即报错，不退化成全表加载（理由见 _load_factor_panel docstring）。
DATASET_SCOPED_PANELS = frozenset({"factor_panel"})


def _resolve_panel_declarations(
    strategy_type: str,
) -> Tuple[List[str], Dict[str, str]]:
    """按 strategy_type 静态解析 allocator 类声明的面板名与面板数据集（不实例化）.

    取值顺序（契约单源，S08）：
        1. ``get_data_contract().panels`` 已声明 → 直接用契约（唯一权威）；
        2. 契约未声明 → 回退到类方法 ``get_extra_panels()/get_panel_datasets()``
           （6 个 standalone 的历史声明位置）；
        3. 两者都无 → ([], {})，不加载任何面板。

    Returns:
        (面板名列表, {面板名: dataset})；类既无契约声明也无类方法声明时返回 ([], {})

    Raises:
        ValueError: 策略码未在 STRATEGY_MANIFEST 注册，或类路径无法导入——
            两者都意味着「面板声明无从解析」，必须显式失败，不能静默退化成空面板
    """
    from importlib import import_module

    from app.allocation.strategy_manifest import get_class_paths
    from app.backtesting.data_contract import DataContract, read_class_panel_declarations

    class_path = get_class_paths().get(strategy_type)
    if not class_path:
        raise ValueError(
            f"策略码 '{strategy_type}' 未在 STRATEGY_MANIFEST 注册，无法解析面板声明；"
            "请确认策略已入库并在清单中登记"
        )
    mod_path, cls_name = class_path.rsplit(".", 1)
    try:
        cls = getattr(import_module(mod_path), cls_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"策略 {strategy_type} 的类路径 {class_path} 无法导入：{exc}；"
            "面板声明解析失败，不能静默跳过面板加载"
        ) from exc

    contract_getter = getattr(cls, "get_data_contract", None)
    if callable(contract_getter):
        try:
            contract = contract_getter()
        except Exception:  # noqa: BLE001 —— 契约反射失败按未声明处理，回退类方法
            contract = None
        if isinstance(contract, DataContract) and contract.panels:
            return sorted(contract.panels), dict(contract.panels)
    return read_class_panel_declarations(cls)


async def load_strategy_panels(
    strategy_type: str,
    config: Optional[BacktestConfig] = None,
) -> Tuple[Dict[str, Dict[pd.Timestamp, pd.DataFrame]], Dict[str, List[pd.Timestamp]]]:
    """按策略声明加载非价格截面面板。

    Args:
        strategy_type: 策略码（必填）；未声明 extra_panels 的策略返回空面板
        config: 回测配置（传给加载器）；监控通道无 BacktestConfig 时传 None，
            不依赖 config 的加载器（如 factor_panel）正常工作

    Returns:
        (panels, panel_dates)

    Raises:
        ValueError: strategy_type 为空、策略码未注册、类路径不可导入，或策略
            声明了未注册的面板名 / 声明了按 dataset 分区的面板却未在
            get_panel_datasets() 给出数据集。缺少策略码不再静默返回空面板——
            那会让依赖面板的策略在引擎首日拿到空截面，错误延迟到策略内部才炸
    """
    code = str(strategy_type or "").strip()
    if not code:
        raise ValueError(
            "load_strategy_panels 缺少 strategy_type：面板声明按策略码静态解析，"
            "不能为空。纯价格数据源请显式使用 DataFeed.from_prices_only()"
        )
    extra, datasets = _resolve_panel_declarations(code)
    if not extra:
        return {}, {}
    panels: Dict[str, Dict[pd.Timestamp, pd.DataFrame]] = {}
    panel_dates: Dict[str, List[pd.Timestamp]] = {}
    for name in extra:
        loader = PANEL_LOADERS.get(name)
        if loader is None:
            raise ValueError(
                f"策略 {code} 声明了未注册的面板 '{name}'，"
                f"已注册加载器：{sorted(PANEL_LOADERS)}"
            )
        dataset = datasets.get(name)
        if name in DATASET_SCOPED_PANELS and not str(dataset or "").strip():
            raise ValueError(
                f"策略 {code} 声明了面板 '{name}' 但未在 get_panel_datasets() "
                "中声明数据集。该面板按 dataset 分区存储，缺声明就无法确定读哪一份；"
                "可选数据集见 field_mappings.FACTOR_DATASETS"
            )
        loaded = await loader(config, dataset)
        panels[name] = loaded
        panel_dates[name] = sorted(loaded.keys())
    return panels, panel_dates


def _schema_min_history_days(strategy_type: Optional[str]) -> int:
    """读取策略类 schema 中 ``min_history_days`` 的声明默认值（交易日）；不可得返回 0.

    模型 ``parameters`` 只保存表单提交过的键，模板后续新增参数的默认值不会
    自动进入存量模型。只读参数字典会让「模板声明」对预加载失效：策略按新
    默认窗口计算，预加载量却停在请求默认，首段调仓因历史不足被拒。
    """
    if not strategy_type:
        return 0
    try:
        from app.allocation.strategy_manifest import resolve_class_safe

        cls = resolve_class_safe(strategy_type)
        if cls is None:
            return 0
        for spec in cls.get_param_schema().params:
            if spec.name == "min_history_days":
                return max(int(spec.default or 0), 0)
    except Exception as exc:  # 元信息读取失败不阻断回测，退回请求默认
        logger.debug("读取 %s 的 min_history_days 声明失败：%s", strategy_type, exc)
    return 0


def resolve_lookback_days(
    strategy_params: Optional[Dict],
    default: int = 500,
    strategy_type: Optional[str] = None,
) -> int:
    """按策略声明的 ``min_history_days``（交易日）反推需预加载的自然日数。

    策略声明的窗口都以交易日计（756 日协方差、250 日 AR 等），而
    ``lookback_days`` 是自然日。252/365 ≈ 0.69，取 1.6 留出节假日与
    窗口取整余量；声明值小于 default 覆盖范围时返回 default。

    参数里没有该键时回退到策略类 schema 的默认值：存量模型的 ``parameters``
    不含模板后加的键，只读参数会让模板默认值对预加载不生效。

    Args:
        strategy_params: 策略参数字典（含前端可改的 min_history_days）
        default: 请求已指定的预加载天数，作为下界
        strategy_type: 策略码，用于回退读取 schema 默认值

    Returns:
        放大后的自然日数，不小于 default
    """
    try:
        need = int((strategy_params or {}).get("min_history_days") or 0)
    except (TypeError, ValueError):
        need = 0
    if need <= 0:
        need = _schema_min_history_days(strategy_type)
    if need <= 0:
        return int(default)
    return max(int(default), int(round(need * 1.6)) + 5)


def strip_invalid_values(prices: pd.DataFrame) -> pd.DataFrame:
    """仅将 inf/-inf 置为 NaN，保留缺日 NaN（不做前向填充）。

    用于构建保真价格矩阵 strategy_prices：原型口径中品种缺日在并集日历上为 NaN，
    收益率/动量/波动率计算自然传播 NaN（缺日附近窗口失效），
    与 sanitize_prices 的 ffill 填平缺日语义不同。
    """
    if prices is None or prices.empty:
        return prices
    return prices.replace([float("inf"), float("-inf")], float("nan"))


def sanitize_prices(prices: pd.DataFrame, max_daily_pct_change: float = _MAX_DAILY_PRICE_CHANGE) -> pd.DataFrame:
    """对价格矩阵做异常填充：nan/inf 用前向填充；单日涨跌幅超过阈值时用前一日价格填充。返回新 DataFrame。

    注意：各列首个有效观测点之前的日期保持 NaN（不做后向填充）——
    否则上市/首个数据日之前的区间会被未来价格回填成「恒定价格」，
    制造零波动率/零动量的假数据，污染选择与定权（原型口径中未上市区间为 NaN 不参与）。
    """
    if prices is None or prices.empty:
        return prices
    out = prices.copy()
    # 先按列处理 nan/inf
    out = out.replace([float("inf"), float("-inf")], float("nan"))
    # 记录各列首个有效观测点，用于禁止上市前后向回填
    first_valid = {col: out[col].first_valid_index() for col in out.columns}
    out = out.ffill()
    # 按列：单日涨跌幅超过阈值则用前一日价格填充
    for col in out.columns:
        prev = out[col].shift(1)
        pct = out[col].pct_change(fill_method=None)
        abnormal = (prev > 1e-12) & (pct.abs() > max_daily_pct_change)
        if abnormal.any():
            out.loc[abnormal, col] = prev[abnormal]
    out = out.ffill()
    # 首个有效观测点之前的回填值置回 NaN（防前视）
    for col, fv in first_valid.items():
        if fv is not None:
            out.loc[out.index < fv, col] = float("nan")
    return out


@dataclass
class DataFeed:
    """回测使用的行情数据提供器.

    prices 是主价格矩阵（close + 附加指标列），index 为 DatetimeIndex。
    extra_prices 承载额外的价格维度（如 vwap），供 iter_bars() 填充到 Bar.extra，
    使 ExecutionEngine 可按优先级取价（vwap → close），所有策略自动受益。
    """

    prices: pd.DataFrame
    config: BacktestConfig
    extra_prices: Dict[str, pd.DataFrame] = field(default_factory=dict)
    # 缺日保真矩阵：保留品种缺日 NaN（仅清理 inf），供声明了缺日保真的策略信号计算使用；
    # 引擎逐日估值始终用 prices（ffill 后）。None 时回退 prices。
    strategy_prices: Optional[pd.DataFrame] = None
    # 非价格截面面板：{面板名: {期日 Timestamp: 截面 DataFrame(index=code)}}，
    # 由 load_strategy_panels 按策略声明加载，引擎经 set_panels 注入 Pipeline
    panels: Dict[str, Dict[pd.Timestamp, pd.DataFrame]] = field(default_factory=dict)
    # 各面板的期日清单：{面板名: [期日 Timestamp]}，供调度派生 event_dates
    panel_dates: Dict[str, List[pd.Timestamp]] = field(default_factory=dict)

    @classmethod
    async def _load_price_matrices(
        cls,
        market_service: MarketService,
        config: BacktestConfig,
        lookback_days: int,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """加载价格矩阵：返回 (引擎价格[清洗后], 缺日保真价格[仅清 inf])."""
        prices = await market_service.get_price_matrix_with_lookback(
            thscodes=config.thscodes,
            start_date=config.start_date,
            end_date=config.end_date,
            lookback_days=lookback_days,
        )
        # 缺日保真矩阵：sanitize 前的原始矩阵（仅清理 inf），是否消费由策略声明决定
        return sanitize_prices(prices), strip_invalid_values(prices)

    @classmethod
    async def from_market_service(
        cls,
        market_service: MarketService,
        config: BacktestConfig,
        lookback_days: int = 252,  # 默认252天（约1年交易日），预留足够的历史数据缓冲
        *,
        strategy_type: str,
    ) -> "DataFeed":
        """从 MarketService 构造 DataFeed（含策略声明的非价格截面面板）.

        为了避免前视偏差，需要在 start_date 之前预留足够的历史数据。
        lookback_days参数为数据预加载缓冲，默认500天确保覆盖各类策略需求。

        strategy_type 必填：面板按策略码静态解析（get_data_contract().panels
        优先，类方法 get_extra_panels / get_panel_datasets 回退）。缺少策略码
        在入口即抛 ValueError，不再静默返回空面板——那会让依赖面板的策略在
        引擎首日拿到空截面，错误延迟到策略内部才炸。纯价格数据源（无策略码）
        请显式使用 ``from_prices_only``。
        """
        code = str(strategy_type or "").strip()
        if not code:
            raise ValueError(
                "DataFeed.from_market_service 缺少 strategy_type：策略声明的截面面板"
                "（如 factor_panel）按策略码解析，缺省会让策略拿到空截面。"
                "纯价格数据源请显式使用 DataFeed.from_prices_only()"
            )
        prices, strategy_prices = await cls._load_price_matrices(
            market_service, config, lookback_days
        )
        panels, panel_dates = await load_strategy_panels(code, config)
        return cls(
            prices=prices,
            config=config,
            strategy_prices=strategy_prices,
            panels=panels,
            panel_dates=panel_dates,
        )

    @classmethod
    async def from_prices_only(
        cls,
        market_service: MarketService,
        config: BacktestConfig,
        lookback_days: int = 252,
    ) -> "DataFeed":
        """纯价格数据源：不加载任何策略截面面板（显式无策略码入口）.

        仅供不按策略码执行的通道使用（如按已记录调仓信号回放绩效的
        _SignalTrackingStrategy）。真实策略回测/监控必须走
        ``from_market_service(strategy_type=...)``，否则策略声明的面板不会加载。
        """
        prices, strategy_prices = await cls._load_price_matrices(
            market_service, config, lookback_days
        )
        return cls(prices=prices, config=config, strategy_prices=strategy_prices)

    def with_scenario_shocks(
        self,
        shocks: Dict[str, float],
        shock_date: Optional[pd.Timestamp] = None,
    ) -> "DataFeed":
        """返回价格矩阵经情景冲击后的新 DataFeed（不修改自身）。

        冲击口径：在 ``shock_date`` 收盘对指定资产价格乘以 ``(1 + shock)``，
        该日之后保持原价格路径——等价于一次性冲击后按原收益率演进。
        默认冲击日取回测起始日之后的第一个交易日：引擎首日先期初建仓，
        冲击落在次一交易日才能被持仓真正承受。

        Args:
            shocks: {资产代码: 冲击幅度}，如 ``{"SH000300": -0.10}`` 表示跌 10%
            shock_date: 冲击交易日，须存在于 ``prices.index``；None 用默认日

        Returns:
            冲击后的新 DataFeed（prices / strategy_prices / extra_prices 同步调整）

        Raises:
            ValueError: 冲击幅度非法、资产不在价格矩阵、或回测区间不足两个交易日
        """
        if not shocks:
            return self
        if self.prices is None or self.prices.empty:
            raise ValueError("价格矩阵为空，无法施加情景冲击")

        factors: Dict[str, float] = {}
        for code, shock in shocks.items():
            try:
                value = float(shock)
            except (TypeError, ValueError):
                raise ValueError(f"情景冲击幅度不是数值: {code}={shock!r}")
            if not math.isfinite(value) or value <= -1.0:
                raise ValueError(
                    f"情景冲击幅度非法: {code}={value}（须为有限值且大于 -1）"
                )
            if code not in self.prices.columns:
                raise ValueError(
                    f"情景冲击资产不在价格矩阵中: {code}；"
                    f"可选资产: {list(self.prices.columns)}"
                )
            factors[code] = 1.0 + value

        target = self._resolve_shock_date(shock_date)
        return replace(
            self,
            prices=self._shock_prices(self.prices, factors, target),
            strategy_prices=self._shock_prices(self.strategy_prices, factors, target),
            extra_prices={
                name: self._shock_prices(df, factors, target)
                for name, df in self.extra_prices.items()
            },
        )

    def _resolve_shock_date(self, shock_date: Optional[pd.Timestamp]) -> pd.Timestamp:
        """解析冲击日：显式传入须为行情交易日，默认取起始日之后的首个交易日。"""
        if shock_date is not None:
            target = pd.Timestamp(shock_date).normalize()
            if target not in self.prices.index:
                raise ValueError(f"情景冲击日不是行情交易日: {target.date()}")
            return target
        start = pd.Timestamp(self.config.start_date).normalize()
        candidates = self.prices.index[self.prices.index > start]
        if len(candidates) == 0:
            raise ValueError("情景冲击需要回测区间至少两个交易日（首日用于期初建仓）")
        return pd.Timestamp(candidates[0]).normalize()

    @staticmethod
    def _shock_prices(
        prices: Optional[pd.DataFrame],
        factors: Dict[str, float],
        shock_date: pd.Timestamp,
    ) -> Optional[pd.DataFrame]:
        """对冲击日及之后的指定列乘以冲击因子，返回新 DataFrame。"""
        if prices is None or prices.empty:
            return prices
        codes = [c for c in factors if c in prices.columns]
        if not codes:
            return prices
        out = prices.copy()
        mask = out.index >= shock_date
        for code in codes:
            out.loc[mask, code] = out.loc[mask, code] * factors[code]
        return out

    def iter_bars(self) -> Iterator[Tuple[pd.Timestamp, Bar]]:
        """按时间顺序逐行输出 Bar 数据，为回测引擎驱动时间提供基础.

        若 extra_prices 非空（如 vwap 宽表），自动填充到 Bar.extra，
        使下游 ExecutionEngine 通过 Bar.get_price() 按优先级取价。
        """
        for time, row in self.prices.iterrows():
            # 确保 close 是字典格式
            try:
                close_dict = row.to_dict()
            except Exception:
                close_dict = {col: row[col] for col in self.prices.columns}

            if not isinstance(close_dict, dict):
                if isinstance(row, pd.Series):
                    close_dict = row.to_dict()
                else:
                    close_dict = {col: getattr(row, col, None) for col in self.prices.columns}

            # 确保所有值都是浮点数，过滤掉 NaN 和无效值
            close_dict = {
                code: float(price)
                for code, price in close_dict.items()
                if pd.notna(price) and isinstance(price, (int, float, str))
            }

            if not isinstance(close_dict, dict):
                raise ValueError(
                    f"无法将价格数据转换为字典格式。"
                    f"时间: {time}, 数据类型: {type(close_dict)}, 值: {close_dict}"
                )

            # 构建 Bar.extra：从 extra_prices 提取当日数据
            extra: Optional[Dict[str, Dict[str, float]]] = None
            if self.extra_prices:
                extra = {}
                for source_name, source_df in self.extra_prices.items():
                    if time in source_df.index:
                        src_row = source_df.loc[time]
                        extra[source_name] = {
                            code: float(val)
                            for code, val in (src_row.to_dict() if isinstance(src_row, pd.Series) else {}).items()
                            if pd.notna(val) and isinstance(val, (int, float))
                        }

            yield time, Bar(time=time, close=close_dict, extra=extra if extra else None)

    def get_history_window(
        self,
        current_time: pd.Timestamp,
    ) -> pd.DataFrame:
        """返回当前时点之前的全部历史数据,用于策略计算.

        注意: 只包含 current_time 之前的数据（不含 current_time），避免前视偏差。
        即在 T 日调仓时，只能使用 T-1 及之前的数据。
        
        lookback截断由策略内部根据自身参数处理。
        """
        # 返回 current_time 之前的所有数据
        window = self.prices.loc[self.prices.index < current_time]
        return window
