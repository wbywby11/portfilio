# -*- coding: utf-8 -*-
"""
集中字段映射 —— 所有导入路径的唯一映射来源

DATA_ARCHITECTURE.md §3.3 规定：
  所有导入路径（前端 API、Agent Tool、脚本）必须引用同一份映射，
  禁止在各导入文件中硬编码列名映射。

使用方式：
    from app.schemas.field_mappings import (
        PRICE_COLUMN_MAPPING,
        ASSET_COLUMN_MAPPING,
        TRADE_DATES_COLUMN_MAPPING,
        FACTOR_DATASETS,
        FACTOR_PANEL_COLUMN_MAPPING,
        FACTOR_NAME_MAPPING_BY_DATASET,
        FACTOR_CATEGORICAL_KEYS_BY_DATASET,
        factor_name_mapping_for,
        categorical_factor_keys_for,
    )
"""

# ─────────────────────────────────────────────────────────────────────────────
# 行情字段映射（asset_prices 导入）
# Excel/JSON 列名 → PriceDataPoint 标准字段名
# ─────────────────────────────────────────────────────────────────────────────
PRICE_COLUMN_MAPPING: dict[str, str] = {
    # 日期
    "日期": "date",
    "日期*": "date",
    "交易日期": "date",
    "trade_date": "date",
    "Date": "date",
    "DATE": "date",
    "date": "date",
    # 开盘价
    "开盘价": "open",
    "开盘价*": "open",
    "Open": "open",
    "OPEN": "open",
    "open": "open",
    # 最高价
    "最高价": "high",
    "最高价*": "high",
    "High": "high",
    "HIGH": "high",
    "high": "high",
    # 最低价
    "最低价": "low",
    "最低价*": "low",
    "Low": "low",
    "LOW": "low",
    "low": "low",
    # 收盘价
    "收盘价": "close",
    "收盘价*": "close",
    "收盘": "close",
    "Close": "close",
    "CLOSE": "close",
    "close": "close",
    # 成交量
    "成交量": "volume",
    "成交量*": "volume",
    "Volume": "volume",
    "VOLUME": "volume",
    "volume": "volume",
    # 成交额
    "成交额": "amount",
    "成交额*": "amount",
    "Amount": "amount",
    "AMOUNT": "amount",
    "amount": "amount",
    # 规模
    "规模": "scale",
    "规模*": "scale",
    "基金规模": "scale",
    "Scale": "scale",
    "SCALE": "scale",
    "scale": "scale",
}

# 行情导入允许的标准字段名集合
PRICE_ALLOWED_FIELDS: frozenset = frozenset(
    {"date", "open", "high", "low", "close", "volume", "amount", "scale"}
)


# ─────────────────────────────────────────────────────────────────────────────
# 资产主数据映射（assets 导入）
# Excel 列名 → Asset 模型字段名
# ─────────────────────────────────────────────────────────────────────────────
ASSET_COLUMN_MAPPING: dict[str, str] = {
    "资产代码*": "code",
    "资产代码": "code",
    "资产名称*": "name",
    "资产名称": "name",
    "资产类型*": "asset_type",
    "资产类型": "asset_type",
    # 三维度正交分类（新字段，导入时优先采用，缺失则由 Asset 模型 backfill）
    "工具形态*": "instrument_type",
    "工具形态": "instrument_type",
    "instrument_type*": "instrument_type",
    "instrument_type": "instrument_type",
    "资产大类*": "asset_class",
    "资产大类": "asset_class",
    "asset_class*": "asset_class",
    "asset_class": "asset_class",
    "证券细分*": "security_type",
    "证券细分": "security_type",
    "security_type*": "security_type",
    "security_type": "security_type",
    # 业务标签：策略预设按标签选资产池，单元格内多个标签用逗号/顿号/分号/竖线分隔
    "标签*": "tags",
    "标签": "tags",
    "tags*": "tags",
    "tags": "tags",
    "交易所": "exchange",
    "资产描述": "description",
    "展期天数(k)": "rollover_days",
    "持仓量阈值(th)": "rollover_threshold",
    "观察窗口起点(p)": "rollover_window_p",
    "观察窗口终点(q)": "rollover_window_q",
    "替代标的代码": "substitute_code",
    "切换日期(YYYYMMDD)": "switch_date",
}


# ─────────────────────────────────────────────────────────────────────────────
# 交易日历映射（trade_dates 导入）
# Excel 列名 → 标准字段名 "date"
# ─────────────────────────────────────────────────────────────────────────────
TRADE_DATES_COLUMN_MAPPING: dict[str, str] = {
    "交易日": "date",
    "交易日期": "date",
    "交易日期*": "date",
    "trade_dates": "date",
    "trade_date": "date",
    "TradeDate": "date",
    "TRADE_DATE": "date",
    "TRADE_DATES": "date",
    "日期": "date",
    "日期*": "date",
    "Date": "date",
    "DATE": "date",
    "date": "date",
}


# ─────────────────────────────────────────────────────────────────────────────
# 因子截面映射（factor_panel 导入）
# Excel 列名 → FactorPanel 模型字段名
#
# 只登记「固定列」。凡不在本表中的数值列一律进 factors dict（开放结构，
# 换因子不改表结构），键名再经 FACTOR_NAME_MAPPING 转英文。
# ─────────────────────────────────────────────────────────────────────────────
FACTOR_PANEL_COLUMN_MAPPING: dict[str, str] = {
    # 权重生效日（业务主键之一，驱动调仓）
    "日期*": "as_of_date",
    "日期": "as_of_date",
    "权重生效日*": "as_of_date",
    "权重生效日": "as_of_date",
    "调仓日": "as_of_date",
    "生效日期": "as_of_date",
    "as_of_date": "as_of_date",
    # 因子取数日（仅留痕核对，缺省等于 as_of_date）
    "因子取数日": "data_date",
    "数据日期": "data_date",
    "财报日": "data_date",
    "报告期": "data_date",
    "data_date": "data_date",
    "reference_date": "data_date",
    # 证券代码（业务主键之一，须与 assets.code 完全一致）
    "代码*": "code",
    "代码": "code",
    "股票代码": "code",
    "证券代码": "code",
    "债券代码": "code",
    "code": "code",
    "thscode": "code",
    "wind_code": "code",
    # 简称（冗余，便于人工核对，不参与计算）
    "简称": "name",
    "股票简称": "name",
    "证券简称": "name",
    "债券简称": "name",
    "名称": "name",
    "name": "name",
    # 行业（行业分组键，行业内限额按此列分组）
    "行业*": "industry",
    "行业": "industry",
    "所属行业": "industry",
    "中证三级行业": "industry",
    "申万行业": "industry",
    "券池": "industry",
    "券池*": "industry",
    "industry": "industry",
    # 总市值（单位统一为元，亿元列由 FACTOR_PANEL_MV_UNIT_BY_COLUMN 换算）
    "总市值(元)": "total_mv",
    "总市值（元）": "total_mv",
    "总市值": "total_mv",
    "市值": "total_mv",
    "total_mv": "total_mv",
    "总市值(亿元)": "total_mv",
    "总市值（亿元）": "total_mv",
    # 自由流通市值（为其他加权口径留位）
    "自由流通市值(元)": "free_float_mv",
    "自由流通市值（元）": "free_float_mv",
    "自由流通市值": "free_float_mv",
    "free_float_mv": "free_float_mv",
    # 数据来源
    "数据来源": "source",
    "来源": "source",
    "source": "source",
}

# 市值列单位倍率：列名 → 乘多少得到「元」。
# 未登记的列名按「已是元」处理。登记在此处而非 service 内做隐式判断，
# 保证单位换算是显式可查的（DATA_IMPORT_SPEC Layer 1）。
FACTOR_PANEL_MV_UNIT_BY_COLUMN: dict[str, float] = {
    "总市值(亿元)": 1e8,
    "总市值（亿元）": 1e8,
    "自由流通市值(亿元)": 1e8,
    "自由流通市值（亿元）": 1e8,
}

# ─────────────────────────────────────────────────────────────────────────
# 因子截面数据集清单（dataset 受控值）
#
# factor_panel 集合被多个策略共用，dataset 把不同来源/产品的截面隔开。
# 导入时 dataset 必须取自本清单——不在清单内直接报错，不静默接受任意字符串。
# 策略侧经 get_panel_datasets() 声明自己读哪个 dataset，加载层据此过滤。
# 命名口径：按数据产品/指数命名，不按策略命名，同一份数据可被多个策略共用。
# ─────────────────────────────────────────────────────────────────────────
FACTOR_DATASETS: dict[str, str] = {
    "bond_phoenix50": (
        "中证浙江凤凰行动50指数债券券池季度截面："
        "券池分组 + 发行规模/主体规模/修正久期"
    ),
    "equity_quality_growth": (
        "A股质量成长因子季度截面："
        "营收与扣非净利增速、扣非PE、股息率TTM"
    ),
    "index_enhance_stock": (
        "指数增强个股月末截面："
        "市净率 PB + 月末收盘价 + 所属行业（行业落固定列 industry）"
    ),
}

# 中文因子列名 → factors dict 内的英文键，按 dataset 分组。
# 必须带 dataset 维度：同一中文列名在不同数据集里可以指不同含义，
# 共用一张扁平表会让两个数据集的因子键互相串味。
# 本表没有的列名直接用原列名作键（不报错，保持开放结构）。
FACTOR_NAME_MAPPING_BY_DATASET: dict[str, dict[str, str]] = {
    "equity_quality_growth": {
        "单季度营收同比增速": "revenue_yoy_sq",
        "营收同比增速": "revenue_yoy_sq",
        "营业收入同比增速": "revenue_yoy_sq",
        "单季度扣非净利润同比增速": "profit_yoy_sq_dn",
        "扣非净利润同比增速": "profit_yoy_sq_dn",
        "扣非PE": "pe_ttm_dn",
        "扣非市盈率": "pe_ttm_dn",
        "PE(TTM,扣非)": "pe_ttm_dn",
        "股息率TTM": "dividend_yield_ttm",
        "股息率": "dividend_yield_ttm",
    },
    # 债券券池因子（类别因子允许文本值，见 FactorPanel.factors）
    "bond_phoenix50": {
        "债务主体": "issuer",
        "发行人": "issuer",
        "债券发行规模": "issue_size",
        "主体发行规模": "issuer_size",
        "修正久期": "modified_duration",
    },
    # 指数增强个股截面：PB 与月末收盘价都是 factors 里的数值因子
    # （收盘价不进固定列：个股不进 assets / asset_prices，价格只能从截面拿）
    "index_enhance_stock": {
        "市净率": "pb",
        "市净率PB": "pb",
        "PB": "pb",
        "pb": "pb",
        "PB(MRQ)": "pb",
        "市净率(MRQ)": "pb",
        "月末收盘价": "close",
        "收盘价": "close",
        "close": "close",
        "Close": "close",
    },
}


def _merge_factor_name_mappings() -> dict[str, str]:
    """合并各 dataset 的列名映射为兜底并集；同名列映射到不同键即报错。

    兜底并集只用于不知道 dataset 的只读场景（如展示库内已出现过的因子键）。
    导入路径一律按 dataset 取分组表（factor_name_mapping_for），不走本并集。
    冲突在模块导入时即暴露，不等到运行期静默覆盖。
    """
    merged: dict[str, str] = {}
    for ds, group in FACTOR_NAME_MAPPING_BY_DATASET.items():
        for column, key in group.items():
            existing = merged.get(column)
            if existing is not None and existing != key:
                raise ValueError(
                    f"FACTOR_NAME_MAPPING_BY_DATASET 冲突：列名 {column!r} 在 dataset "
                    f"{ds!r} 映射到 {key!r}，此前已映射到 {existing!r}。"
                    f"跨 dataset 的同名列必须映射到同一英文键，否则兜底并集不成立"
                )
            merged[column] = key
    return merged


# 兜底并集（仅供不知道 dataset 的只读场景；构建时已做冲突校验）
FACTOR_NAME_MAPPING: dict[str, str] = _merge_factor_name_mappings()


def _known_dataset(dataset: str) -> str:
    """校验 dataset 在受控清单内并原样返回（两处取表函数共用，避免口径漂移）。"""
    if dataset not in FACTOR_DATASETS:
        raise ValueError(
            f"未知的因子数据集 dataset={dataset!r}，可选："
            f"{'、'.join(sorted(FACTOR_DATASETS))}"
        )
    return dataset


def factor_name_mapping_for(dataset: str) -> dict[str, str]:
    """取指定 dataset 的列名映射表（导入路径用）。

    Args:
        dataset: 数据集标识，必须在 FACTOR_DATASETS 受控清单内

    Returns:
        该数据集的「中文列名 → 英文因子键」映射；未登记时返回空 dict
        （列名直接作键，保持开放结构）

    Raises:
        ValueError: dataset 不在受控清单内
    """
    _known_dataset(dataset)
    return FACTOR_NAME_MAPPING_BY_DATASET.get(dataset, {})


# ─────────────────────────────────────────────────────────────────
# 类别因子键（按 dataset）
#
# factors 的值类型是 Union[float, str]：数值因子供打分/加权，类别因子供
# 分组/限额。哪些键是类别因子必须在此显式登记：不登记的话导入会把文本值
# 当数值解析（失败→置空），策略侧读不到该键直接报错，形成「按报错提示
# 补了列仍然失败」的死循环。反向也成立：未登记的键一律按数值解析，避免把
# 「亏损」这类文本混进数值因子。
# ─────────────────────────────────────────────────────────────────
FACTOR_CATEGORICAL_KEYS_BY_DATASET: dict[str, frozenset[str]] = {
    # 单发行人限额按 issuer 归并同一主体的多只券（源列：债务主体 / 发行人）
    "bond_phoenix50": frozenset({"issuer"}),
    "equity_quality_growth": frozenset(),
    # 行业与简称走固定列 industry / name（不进 factors），此处无需登记；
    # 本数据集的因子只有 pb 与 close 两个数值因子
    "index_enhance_stock": frozenset(),
}


def categorical_factor_keys_for(dataset: str) -> frozenset[str]:
    """取指定 dataset 的类别因子键集合（导入路径用）。

    Args:
        dataset: 数据集标识，必须在 FACTOR_DATASETS 受控清单内

    Returns:
        该数据集按文本保留的因子键；未登记时返回空集合（全部按数值解析）

    Raises:
        ValueError: dataset 不在受控清单内
    """
    _known_dataset(dataset)
    return FACTOR_CATEGORICAL_KEYS_BY_DATASET.get(dataset, frozenset())


# factor_panel 必填字段（缺失即整行拒绝，不静默补默认值）
# dataset 不在此列：它不是 Excel 列，而由导入接口的 dataset 参数整文件指定
FACTOR_PANEL_REQUIRED_FIELDS: frozenset = frozenset({"as_of_date", "code", "industry"})


# ─────────────────────────────────────────────────────────────────────────────
# 宏观与估值序列映射（macro_series 导入）
#
# 长表存储：一条记录 = 一个序列在一个日期的一个取值
#   {code, date, value, series_type, unit, source}，业务主键 (code, date)
# 与 asset_prices 的区别：这些序列不是可交易资产，不进 assets / asset_prices，
# 只作为策略面板（PANEL_LOADERS["macro_series"]）与前端展示的数据源。
#
# 导入文件两种形态，服务层自动识别：
#   宽表：第一列日期，后续每列列名即序列代码（官方模板形态，逐列展开成长表）
#   长表：列包含 code 与 value（及可选的 date/series_type/unit/source）
# 可选的「序列说明」工作表给出每个序列的 series_type / unit / source，
# 缺该表时按 other / 空单位写入——不从代码名猜测类型（PE/PB 后缀不是契约）。
# ─────────────────────────────────────────────────────────────────────────────
MACRO_SERIES_COLUMN_MAPPING: dict[str, str] = {
    # 宽表：日期列。其余列名即序列代码，不进本映射
    "日期": "date",
    "日期*": "date",
    "交易日期": "date",
    "date": "date",
    "Date": "date",
    "DATE": "date",
    # 长表 / 序列说明表
    "序列代码": "code",
    "序列代码*": "code",
    "代码": "code",
    "代码*": "code",
    "code": "code",
    "数值": "value",
    "值": "value",
    "value": "value",
    "序列类型": "series_type",
    "类型": "series_type",
    "series_type": "series_type",
    "单位": "unit",
    "unit": "unit",
    "来源": "source",
    "数据来源": "source",
    "source": "source",
}

# 序列说明表的默认工作表名（可选；缺失则按 other 归类）
MACRO_SERIES_META_SHEET = "序列说明"

# series_type 受控词表（导入时校验；不在表内直接报错，不静默接受任意字符串）
MACRO_SERIES_TYPES: dict[str, str] = {
    "valuation": "指数估值（PE / PB / 股息率等）",
    "bond_yield": "债券收益率",
    "credit_spread": "信用利差",
    "erp": "股权风险溢价及其分量",
    "macro": "宏观指标（增长 / 通胀 / 货币等）",
    "other": "其他（未分类，缺说明表时的缺省值）",
}

# 未提供序列说明表时的缺省归类：不猜测，统一落 other 并在导入结果里报告数量
MACRO_SERIES_DEFAULT_TYPE = "other"
