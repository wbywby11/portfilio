"""
资产数据模型

三维度正交分类（对标 Bloomberg / Wind / FactSet）：
- InstrumentType（工具形态）：驱动 TR 计算分支
- AssetClass（资产大类）：用于过滤/分组/风控
- SecurityType（证券细分）：可选细粒度标签

详见 docs/DATA_ARCHITECTURE.md 第八章 8.1-8.3。
"""
from datetime import datetime
from typing import Optional, List, Union
from pydantic import BaseModel, Field, field_validator, field_serializer, model_validator
from enum import Enum
import math


# ─────────────────────────────────────────────────────
# 维度 1：InstrumentType（工具形态）— 驱动 TR 计算分支
# ─────────────────────────────────────────────────────
class InstrumentType(str, Enum):
    """工具形态：决定 TR 计算公式与表单字段。

    对标 Bloomberg Instrument / FpML productType。
    值统一使用 'XX型'（形态表达），不用 'XX类'（类别表达）。
    """
    INDEX_LIKE = "指数型"     # tr.py §2.1 — 直接收盘价累积
    SPOT_LIKE = "现货型"      # tr.py §2.4 — 上市前替代、上市后切换
    FUTURES_LIKE = "期货型"   # tr.py §3.2 — 主力合约展期


# ─────────────────────────────────────────────────────
# 维度 2：AssetClass（资产大类）— 用于过滤/分组/风控
# ─────────────────────────────────────────────────────
class AssetClass(str, Enum):
    """资产大类：对标 Wind 资产大类 / Bloomberg Asset Class。"""
    EQUITY = "权益"
    FIXED_INCOME = "固收"
    COMMODITY = "商品"
    CURRENCY = "货币"
    ALTERNATIVE = "另类"


# ─────────────────────────────────────────────────────
# 维度 3：SecurityType（证券细分，可选）
# ─────────────────────────────────────────────────────
class SecurityType(str, Enum):
    """证券细分：对标 Bloomberg Security Type / FactSet Sec Type。"""
    STOCK = "股票"
    INDEX = "指数"
    ETF = "ETF"
    LOF = "LOF"
    FUND = "基金"
    BOND = "债券"
    FUTURES = "期货"
    CRYPTO = "数字货币"
    DEPOSIT = "存款"


# ─────────────────────────────────────────────────────
# 历史兼容：AssetType（已废弃，仅保留别名供旧代码过渡）
# ─────────────────────────────────────────────────────
class AssetType(str, Enum):
    """[已废弃] 历史遗留的混存枚举。

    保留仅为旧代码过渡使用。新代码应改用 InstrumentType / AssetClass / SecurityType。
    旧 10 个值：股票/债券/商品/货币/基金/指数/数字货币 + 指数类/现货类/期货类。
    """
    # 基础类型（旧维度，对应新 SecurityType + AssetClass）
    STOCK = "股票"
    BOND = "债券"
    COMMODITY = "商品"
    CURRENCY = "货币"
    FUND = "基金"
    INDEX = "指数"
    CRYPTO = "数字货币"

    # 业务分类（旧维度，对应新 InstrumentType）
    INDEX_CATEGORY = "指数类"
    SPOT_CATEGORY = "现货类"
    FUTURES_CATEGORY = "期货类"


# ─────────────────────────────────────────────────────
# 资产主模型
# ─────────────────────────────────────────────────────
# 旧 asset_type → 新维度的回填映射（仅用于存量数据/批量导入的兼容补全）
_LEGACY_TYPE_TO_INSTRUMENT: dict[str, str] = {
    "指数类": InstrumentType.INDEX_LIKE.value,
    "指数型": InstrumentType.INDEX_LIKE.value,
    "现货类": InstrumentType.SPOT_LIKE.value,
    "现货型": InstrumentType.SPOT_LIKE.value,
    "期货类": InstrumentType.FUTURES_LIKE.value,
    "期货型": InstrumentType.FUTURES_LIKE.value,
}

_LEGACY_TYPE_TO_CLASS: dict[str, str] = {
    "股票": AssetClass.EQUITY.value,
    "指数": AssetClass.EQUITY.value,
    "基金": AssetClass.EQUITY.value,
    "债券": AssetClass.FIXED_INCOME.value,
    "商品": AssetClass.COMMODITY.value,
    "货币": AssetClass.CURRENCY.value,
    "数字货币": AssetClass.ALTERNATIVE.value,
}

_LEGACY_TYPE_TO_SECURITY: dict[str, str] = {
    "股票": SecurityType.STOCK.value,
    "指数": SecurityType.INDEX.value,
    "基金": SecurityType.FUND.value,
    "债券": SecurityType.BOND.value,
    "期货": SecurityType.FUTURES.value,
    "数字货币": SecurityType.CRYPTO.value,
}

# 标签分隔符：Excel 一个单元格里可能写多个标签，导入与模型层共用同一套切分口径
TAG_SEPARATORS: tuple[str, ...] = (",", "，", ";", "；", "|", "\n", "\t")


def normalize_tags(value: object) -> list[str]:
    """把标签值归一为去空、去重、保序的字符串列表。

    兼容前端多选（list）、Excel 单元格（逗号/顿号/分号/竖线分隔的字符串）、
    以及历史污染写入的 NaN / 空串。
    """
    if value is None:
        return []
    if isinstance(value, float) and math.isnan(value):
        return []
    if isinstance(value, (list, tuple, set)):
        items = [str(v) for v in value]
    else:
        text = str(value)
        for sep in TAG_SEPARATORS:
            text = text.replace(sep, "\n")
        items = text.split("\n")
    out: list[str] = []
    for item in items:
        tag = item.strip()
        if tag and tag not in out:
            out.append(tag)
    return out


class Asset(BaseModel):
    """资产模型（三维度正交分类）"""
    id: Optional[str] = Field(None, alias="_id")
    code: str = Field(..., description="资产代码（业务主键）")
    name: str = Field(..., description="资产名称")

    # 维度 1：工具形态（驱动 TR 计算，必填）
    instrument_type: InstrumentType = Field(..., description="工具形态：指数型/现货型/期货型")
    # 维度 2：资产大类（过滤/分组/风控，必填）
    asset_class: AssetClass = Field(..., description="资产大类：权益/固收/商品/货币/另类")
    # 维度 3：证券细分（可选细粒度标签）
    security_type: Optional[SecurityType] = Field(None, description="证券细分标签：股票/ETF/指数/基金/...")

    # 业务标签（与三维度分类正交）：策略预设按标签选资产池用
    # 约定前缀：pool:<池名> 资产池成员 / class:<大类> 分组用大类 / market:<市场> 市场归属
    tags: List[str] = Field(
        default_factory=list,
        description="业务标签，如 pool:nous_no_us、class:gold、market:hk",
    )

    # [历史兼容] 旧的混存字段，新代码应改用上面三个维度
    # 存量数据迁移完成前保留；迁移后此字段将移除
    asset_type: Optional[Union[InstrumentType, str]] = Field(
        None,
        description="[已废弃] 旧版混存字段，保留为兼容。新代码使用 instrument_type/asset_class/security_type"
    )

    exchange: Optional[str] = Field(None, description="交易所")
    description: Optional[str] = Field(None, description="资产描述")
    is_active: bool = Field(True, description="是否启用")

    # 期货展期参数（仅 instrument_type == 期货型 时使用）
    rollover_days: Optional[int] = Field(None, description="展期天数 k")
    rollover_threshold: Optional[float] = Field(None, description="持仓量阈值 th")
    rollover_window_p: Optional[int] = Field(None, description="观察窗口起点参数 p（LTD-p）")
    rollover_window_q: Optional[int] = Field(None, description="观察窗口终点参数 q（LTD-q）")
    contract_multiplier: Optional[float] = Field(None, description="合约乘数（期货；指数复现类线性敞口口径下可不设）")
    price_series_kind: Optional[str] = Field(
        None,
        description="价格序列类型：spot=现货/真实成交价；adjusted_continuous=复权连续主力（展期收益已内含于价格序列，引擎不再建模展期）"
    )

    # 现货切换参数（仅 instrument_type == 现货型 时使用）
    substitute_code: Optional[str] = Field(None, description="替代标的代码（上市前使用）")
    switch_date: Optional[str] = Field(None, description="切换日期（YYYYMMDD 或 YYYY-MM-DD）")

    # 动量策略：计价货币与费率（可选覆盖，不设则按默认值）
    currency: Optional[str] = Field(None, description="计价货币 CNH/USD/HKD/EUR")
    trading_cost_rate: Optional[float] = Field(None, description="交易费率（单次调仓）")
    replication_cost_rate: Optional[float] = Field(None, description="复制费率年化")

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="before")
    @classmethod
    def backfill_legacy_dimensions(cls, data):
        """从旧 asset_type 回填缺失的三维度字段。

        存量 MongoDB 数据与批量导入（Excel 资产模板、多资产宽表自动建资产）只带
        asset_type，此处补全 instrument_type/asset_class，避免必填校验直接报错。
        已显式传入的新维度字段不会被覆盖。
        """
        if not isinstance(data, dict):
            return data

        # 历史污染sanitize：旧版导入可能把 pandas NaN / 空字符串写入可选字段，
        # 列表查询 Asset(**doc) 时 pydantic 校验失败导致整页 500，此处统一归一为 None
        for key in ("security_type", "exchange", "description", "asset_type",
                    "substitute_code", "switch_date", "currency"):
            v = data.get(key)
            if v is not None and (
                (isinstance(v, float) and math.isnan(v))
                or (isinstance(v, str) and not v.strip())
            ):
                data[key] = None
        for key in ("rollover_days", "rollover_threshold", "rollover_window_p",
                    "rollover_window_q", "trading_cost_rate", "replication_cost_rate"):
            v = data.get(key)
            if isinstance(v, float) and math.isnan(v):
                data[key] = None

        # 标签归一：存量文档没有该字段、或历史污染写了 NaN/空串，统一为 []
        data["tags"] = normalize_tags(data.get("tags"))

        legacy = data.get("asset_type")
        legacy = str(legacy).strip() if legacy is not None else ""

        if not data.get("instrument_type"):
            # 旧值未命中形态映射时一律视为指数型（直接收盘价累积，最保守的 TR 分支）
            data["instrument_type"] = _LEGACY_TYPE_TO_INSTRUMENT.get(
                legacy, InstrumentType.INDEX_LIKE.value
            )
        if not data.get("asset_class"):
            data["asset_class"] = _LEGACY_TYPE_TO_CLASS.get(legacy, AssetClass.EQUITY.value)
        if not data.get("security_type") and legacy in _LEGACY_TYPE_TO_SECURITY:
            data["security_type"] = _LEGACY_TYPE_TO_SECURITY[legacy]

        return data

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.strftime('%Y-%m-%d') if v else None
        }


class AssetPrice(BaseModel):
    """资产行情数据"""
    id: Optional[str] = Field(None, alias="_id")
    asset_code: str = Field(..., description="资产代码")
    date: str = Field(..., description="日期（格式：YYYY-MM-DD）")
    open: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    close: float = Field(..., description="收盘价")
    price_basis: Optional[str] = Field(
        None,
        description="close 字段的价格基准：close=收盘价（默认） / settle=结算价（期货）；缺失按 close 语义处理"
    )
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    scale: Optional[float] = Field(None, description="规模（如 AUM、份额规模等）")

    @field_validator('date', mode='before')
    @classmethod
    def validate_date(cls, v: Union[str, datetime]) -> str:
        """验证并转换日期格式为 YYYY-MM-DD"""
        if isinstance(v, datetime):
            return v.strftime('%Y-%m-%d')
        elif isinstance(v, str):
            v = v.strip()
            clean_date = v.replace('-', '').replace('/', '')
            if len(clean_date) == 8:
                dt = datetime.strptime(clean_date, '%Y%m%d')
                return dt.strftime('%Y-%m-%d')
            elif len(v) == 10 and (v.count('-') == 2 or v.count('/') == 2):
                dt = datetime.strptime(v.replace('/', '-'), '%Y-%m-%d')
                return dt.strftime('%Y-%m-%d')
            else:
                raise ValueError(f"不支持的日期格式: {v}，请使用 YYYY-MM-DD 或 YYYYMMDD")
        else:
            raise ValueError(f"日期类型必须是字符串或datetime对象")

    class Config:
        populate_by_name = True
