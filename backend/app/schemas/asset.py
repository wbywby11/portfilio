"""资产相关API请求/响应模型"""
import math
from datetime import datetime, timedelta
from typing import Any, Optional, List, Union
import pandas as pd
from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator
from app.models.asset import AssetType, InstrumentType, AssetClass, SecurityType
from app.schemas.field_mappings import PRICE_COLUMN_MAPPING, PRICE_ALLOWED_FIELDS


# 多资产 analyze / Excel 导出等常见列名 → PriceDataPoint 字段名（小写）
# 唯一来源：app/schemas/field_mappings.py
_PRICE_IMPORT_ROW_KEY_CN: dict[str, str] = PRICE_COLUMN_MAPPING
_PRICE_IMPORT_ALLOWED = PRICE_ALLOWED_FIELDS


def normalize_price_import_row_list(v: Any) -> Any:
    """
    将行情行 dict 的键规范为 PriceDataPoint 字段名。
    解决 JSON 里常见 ``Date``/``OPEN`` 等与模型 ``date``/``open`` 不一致导致的 422。
    """
    if not isinstance(v, list):
        return v
    out: List[Any] = []
    for raw in v:
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        row: dict[str, Any] = {}
        for k_raw, val in raw.items():
            if k_raw is None:
                continue
            k = str(k_raw).strip()
            if k in _PRICE_IMPORT_ROW_KEY_CN:
                nk = _PRICE_IMPORT_ROW_KEY_CN[k]
            elif k.isascii():
                nk = k.lower()
            else:
                continue
            if nk in _PRICE_IMPORT_ALLOWED:
                row[nk] = val
        out.append(row if row else raw)
    return out


def _coerce_optional_float(v: Any) -> Any:
    """将空串、千分位、常见占位转为 None；其余尽量转为 float。"""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("，", "")
        if not s or s.lower() in ("nan", "null", "-", "--", "na", "n/a"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv
    return None


class AssetOption(BaseModel):
    """资产下拉选项"""
    id: str = Field(..., description="资产ID")
    code: str = Field(..., description="资产代码")
    name: str = Field(..., description="资产名称")


class AssetCreate(BaseModel):
    """创建资产请求（三维度正交分类）"""
    code: str = Field(..., description="资产代码")
    name: str = Field(..., description="资产名称")

    # 三维度正交分类（新字段，必填）
    instrument_type: InstrumentType = Field(..., description="工具形态：指数型/现货型/期货型")
    asset_class: AssetClass = Field(..., description="资产大类：权益/固收/商品/货币/另类")
    security_type: Optional[SecurityType] = Field(None, description="证券细分（可选）")

    # 业务标签：策略预设按标签选资产池，前缀约定 pool:/class:/market:
    tags: List[str] = Field(default_factory=list, description="业务标签，如 pool:nous_no_us、class:gold")

    # [已废弃] 旧字段兼容，前端不再发送，后端不再强制
    asset_type: Optional[str] = Field(None, description="[已废弃] 旧版混存字段")

    exchange: Optional[str] = Field(None, description="交易所")
    description: Optional[str] = Field(None, description="资产描述")
    
    # 期货展期参数（仅期货类资产需要）
    rollover_days: Optional[int] = Field(None, description="展期天数 k")
    rollover_threshold: Optional[float] = Field(None, description="持仓量阈值 th")
    rollover_window_p: Optional[int] = Field(None, description="观察窗口起点参数 p（LTD-p）")
    rollover_window_q: Optional[int] = Field(None, description="观察窗口终点参数 q（LTD-q）")
    
    # 现货切换参数（仅现货/ETF类资产需要）
    substitute_code: Optional[str] = Field(None, description="替代标的代码（上市前使用）")
    switch_date: Optional[str] = Field(None, description="切换日期（YYYYMMDD）")

    # 动量策略：计价货币与费率（可选覆盖）
    currency: Optional[str] = Field(None, description="计价货币 CNH/USD/HKD/EUR")
    trading_cost_rate: Optional[float] = Field(None, description="交易费率（单次调仓）")
    replication_cost_rate: Optional[float] = Field(None, description="复制费率年化")


class AssetUpdate(BaseModel):
    """更新资产请求（三维度正交分类）"""
    code: Optional[str] = Field(None, description="资产代码")
    name: Optional[str] = Field(None, description="资产名称")

    # 三维度正交分类（新字段）
    instrument_type: Optional[InstrumentType] = Field(None, description="工具形态：指数型/现货型/期货型")
    asset_class: Optional[AssetClass] = Field(None, description="资产大类：权益/固收/商品/货币/另类")
    security_type: Optional[SecurityType] = Field(None, description="证券细分（可选）")

    # 业务标签：传空列表表示清空全部标签，不传表示不修改
    tags: Optional[List[str]] = Field(None, description="业务标签，如 pool:nous_no_us、class:gold")

    # [已废弃] 旧字段兼容
    asset_type: Optional[str] = Field(None, description="[已废弃] 旧版混存字段")

    exchange: Optional[str] = Field(None, description="交易所")
    description: Optional[str] = Field(None, description="资产描述")
    is_active: Optional[bool] = Field(None, description="是否启用")
    
    # 期货展期参数（仅期货类资产需要）
    rollover_days: Optional[int] = Field(None, description="展期天数 k")
    rollover_threshold: Optional[float] = Field(None, description="持仓量阈值 th")
    rollover_window_p: Optional[int] = Field(None, description="观察窗口起点参数 p（LTD-p）")
    rollover_window_q: Optional[int] = Field(None, description="观察窗口终点参数 q（LTD-q）")
    
    # 现货切换参数（仅现货/ETF类资产需要）
    substitute_code: Optional[str] = Field(None, description="替代标的代码（上市前使用）")
    switch_date: Optional[str] = Field(None, description="切换日期（YYYYMMDD）")

    # 动量策略：计价货币与费率（可选覆盖）
    currency: Optional[str] = Field(None, description="计价货币 CNH/USD/HKD/EUR")
    trading_cost_rate: Optional[float] = Field(None, description="交易费率（单次调仓）")
    replication_cost_rate: Optional[float] = Field(None, description="复制费率年化")


class AssetOut(BaseModel):
    """资产返回模型（三维度正交分类）"""
    id: str = Field(..., description="资产ID")
    code: str = Field(..., description="资产代码")
    name: str = Field(..., description="资产名称")

    # 三维度正交分类（新字段）
    instrument_type: Optional[str] = Field(None, description="工具形态：指数型/现货型/期货型")
    asset_class: Optional[str] = Field(None, description="资产大类：权益/固收/商品/货币/另类")
    security_type: Optional[str] = Field(None, description="证券细分")

    # 业务标签：策略预设按标签选资产池
    tags: List[str] = Field(default_factory=list, description="业务标签")

    # [已废弃] 旧字段兼容（迁移完成后可移除）
    asset_type: Optional[str] = Field(None, description="[已废弃] 旧版混存字段")

    exchange: Optional[str] = Field(None, description="交易所")
    description: Optional[str] = Field(None, description="资产描述")
    is_active: bool = Field(..., description="是否启用")
    
    # 期货展期参数（仅期货类资产需要）
    rollover_days: Optional[int] = Field(None, description="展期天数 k")
    rollover_threshold: Optional[float] = Field(None, description="持仓量阈值 th")
    rollover_window_p: Optional[int] = Field(None, description="观察窗口起点参数 p（LTD-p）")
    rollover_window_q: Optional[int] = Field(None, description="观察窗口终点参数 q（LTD-q）")
    
    # 现货切换参数（仅现货/ETF类资产需要）
    substitute_code: Optional[str] = Field(None, description="替代标的代码（上市前使用）")
    switch_date: Optional[str] = Field(None, description="切换日期（YYYYMMDD）")

    # 动量策略：计价货币与费率（可选覆盖）
    currency: Optional[str] = Field(None, description="计价货币 CNH/USD/HKD/EUR")
    trading_cost_rate: Optional[float] = Field(None, description="交易费率（单次调仓）")
    replication_cost_rate: Optional[float] = Field(None, description="复制费率年化")

    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    
    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime) -> str:
        """序列化 datetime 为 YYYY-MM-DD 格式"""
        return dt.strftime('%Y-%m-%d') if dt else None


class KlineQuery(BaseModel):
    """K线查询条件(备用,当前接口使用query参数)"""
    start_date: Optional[datetime] = Field(None, description="开始日期")
    end_date: Optional[datetime] = Field(None, description="结束日期")


class KlinePoint(BaseModel):
    """K线数据点"""
    date: Union[str, datetime] = Field(..., description="日期")
    open: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    close: float = Field(..., description="收盘价")
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    scale: Optional[float] = Field(None, description="规模")
    
    @field_validator('date', mode='before')
    @classmethod
    def validate_date(cls, v: Union[str, datetime]) -> str:
        """验证并转换日期为 YYYY-MM-DD 字符串格式"""
        if isinstance(v, datetime):
            return v.strftime('%Y-%m-%d')
        elif isinstance(v, str):
            # 如果已经是字符串，验证格式
            v = v.strip()
            # 移除分隔符
            clean_date = v.replace('-', '').replace('/', '')
            if len(clean_date) == 8:
                # YYYYMMDD 格式
                dt = datetime.strptime(clean_date, '%Y%m%d')
                return dt.strftime('%Y-%m-%d')
            elif len(v) == 10 and (v.count('-') == 2 or v.count('/') == 2):
                # YYYY-MM-DD 或 YYYY/MM/DD 格式
                dt = datetime.strptime(v.replace('/', '-'), '%Y-%m-%d')
                return dt.strftime('%Y-%m-%d')
            else:
                raise ValueError(f"不支持的日期格式: {v}，请使用 YYYY-MM-DD 或 YYYYMMDD")
        else:
            raise ValueError(f"日期类型必须是字符串或datetime对象")


class PriceDataPoint(BaseModel):
    """单条价格数据（用于导入）"""
    date: Union[str, datetime, int, float] = Field(
        ...,
        description="日期：YYYY-MM-DD / YYYYMMDD / ISO 字符串；也兼容 JSON 数字（Excel 序列日约 3万～6 万）",
    )
    open: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    close: Optional[float] = Field(
        None,
        description="收盘价；可与其它字段组合。按日合并时：新交易日须在本行提供大于 0 的收盘价；仅补充规模/成交额等时对应日期须在库中已有有效收盘价",
    )
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    scale: Optional[float] = Field(None, description="规模")

    @field_validator("date", mode="before")
    @classmethod
    def normalize_price_date(cls, v: Any) -> str:
        if v is None:
            raise ValueError("日期不能为空")
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            fv = float(v)
            # Excel 序列日（常见区间）；避免把 20200101 等误当年份序列
            if 30000 <= fv <= 60000:
                base = datetime(1899, 12, 30)
                try:
                    return (base + timedelta(days=int(fv))).strftime("%Y-%m-%d")
                except (OverflowError, ValueError) as e:
                    raise ValueError(f"无法解析 Excel 序列日期: {v}") from e
            if abs(fv - int(fv)) < 1e-9:
                s = str(int(fv))
                if len(s) == 8 and s.isdigit():
                    return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
            raise ValueError(f"不支持的日期数值: {v}")
        if isinstance(v, str):
            s0 = v.strip()
            if not s0:
                raise ValueError("日期不能为空")
            ds = s0.replace("-", "").replace("/", "").strip()
            if len(ds) == 8 and ds.isdigit():
                return datetime.strptime(ds, "%Y%m%d").strftime("%Y-%m-%d")
            try:
                return datetime.strptime(s0.replace("/", "-")[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                pass
            try:
                return datetime.fromisoformat(s0.replace("Z", "+00:00")[:19]).strftime("%Y-%m-%d")
            except ValueError:
                pass
            ts = pd.to_datetime(s0, errors="coerce")
            if not pd.isna(ts):
                return pd.Timestamp(ts).strftime("%Y-%m-%d")
            raise ValueError(f"不支持的日期格式: {v}")
        raise ValueError(f"日期类型不支持: {type(v)}")

    @field_validator("open", "high", "low", "volume", "amount", "scale", mode="before")
    @classmethod
    def coerce_optional_metrics(cls, v: Any) -> Any:
        return _coerce_optional_float(v)

    @field_validator("close", mode="before")
    @classmethod
    def coerce_close(cls, v: Any) -> Any:
        """空串/千分位先规范化；0 视为未填收盘价（与宽表补字段一致）。"""
        v2 = _coerce_optional_float(v)
        if v2 is None:
            return None
        try:
            fv = float(v2)
        except (TypeError, ValueError):
            return v2
        if fv == 0:
            return None
        return fv

    @model_validator(mode="after")
    def require_some_metric(self) -> "PriceDataPoint":
        vals = [self.open, self.high, self.low, self.close, self.volume, self.amount, self.scale]
        if all(v is None for v in vals):
            raise ValueError("须至少提供开盘价、最高价、最低价、收盘价、成交量、成交额、规模之一")
        if self.close is not None and self.close <= 0:
            raise ValueError("收盘价须大于 0")
        return self


class PriceImportRequest(BaseModel):
    """行情数据导入请求"""
    asset_code: str = Field(..., description="资产代码")
    prices: List[PriceDataPoint] = Field(..., description="价格数据列表")
    replace_existing: bool = Field(
        False,
        description="false：按日期 upsert（同日更新、新日插入）；true：先删除该资产全部行情再写入本次请求中的数据",
    )
    only_missing_dates: bool = Field(
        False,
        description="true 且 replace_existing=false：仅插入库中尚不存在的交易日，已有日期跳过",
    )

    @field_validator("prices", mode="before")
    @classmethod
    def normalize_prices_keys(cls, v: Any) -> Any:
        return normalize_price_import_row_list(v)

    @model_validator(mode="after")
    def price_import_only_missing(self) -> "PriceImportRequest":
        if self.replace_existing:
            self.only_missing_dates = False
        return self


class MultiAssetSingleImportRequest(BaseModel):
    """单资产导入请求（用于多资产逐条导入）"""
    code: str = Field(..., description="资产代码")
    name: str = Field(..., description="资产名称")
    prices: List[PriceDataPoint] = Field(..., description="价格数据列表")
    overwrite_name: bool = Field(False, description="是否覆盖已有名称")
    replace_existing: bool = Field(
        False,
        description="false：按日期 upsert；true：先删该资产全部行情再写入文件中的行",
    )
    only_missing_dates: bool = Field(
        False,
        description="true 且 replace_existing=false：仅插入库中尚不存在的交易日，已有日期跳过",
    )
    import_as_code: Optional[str] = Field(
        None,
        description="若填写，行情导入到该代码对应资产（Excel 中 code 可与之不同，用于名称匹配绑定）",
    )
    create_new_asset: bool = Field(
        False,
        description="仅代码与系统一致但名称不一致时：为 true 则按 new_asset_code 新建资产并写入行情，不修改原代码资产",
    )
    new_asset_code: Optional[str] = Field(
        None,
        description="与 create_new_asset 联用：新建资产的代码，须为系统中尚不存在的代码",
    )
    progress_id: Optional[str] = Field(
        None,
        description="前端生成的唯一 id，用于轮询 GET /assets/prices/import/progress 展示本条导入进度",
    )
    import_metric: Optional[str] = Field(
        None,
        description="与宽表列含义一致：close/open/high/low/amount/volume/scale，用于进度中文说明",
    )

    @field_validator("prices", mode="before")
    @classmethod
    def normalize_multi_prices_keys(cls, v: Any) -> Any:
        return normalize_price_import_row_list(v)

    @field_validator("overwrite_name", "replace_existing", "only_missing_dates", "create_new_asset", mode="before")
    @classmethod
    def coerce_bool_like(cls, v: Any) -> Any:
        """兼容部分客户端把布尔写成字符串/0/1。"""
        if v is None or isinstance(v, bool):
            return v
        if isinstance(v, str):
            s = v.strip().lower()
            if s in ("true", "1", "yes", "on"):
                return True
            if s in ("false", "0", "no", "off", ""):
                return False
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if int(v) == 1:
                return True
            if int(v) == 0:
                return False
        return v

    @field_validator("import_metric", mode="before")
    @classmethod
    def coerce_import_metric(cls, v: Any) -> Any:
        if v is None or isinstance(v, bool):
            return None
        s = str(v).strip().lower()
        return s or None

    @field_validator("progress_id", mode="before")
    @classmethod
    def coerce_progress_id(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, (list, dict)):
            raise ValueError("progress_id 须为字符串")
        s = str(v).strip()
        return s or None

    @model_validator(mode="after")
    def validate_multi_asset_single_request(self) -> "MultiAssetSingleImportRequest":
        self.code = (self.code or "").strip()
        self.name = (self.name or "").strip()
        if self.progress_id is not None:
            self.progress_id = (self.progress_id or "").strip() or None
        if self.import_metric is not None:
            self.import_metric = (self.import_metric or "").strip().lower() or None
        if not self.code:
            raise ValueError("资产代码不能为空")
        if not self.name:
            raise ValueError("资产名称不能为空")
        if self.create_new_asset:
            nc = (self.new_asset_code or "").strip()
            if not nc:
                raise ValueError("选择新建资产时须填写 new_asset_code")
            self.new_asset_code = nc
        if self.replace_existing:
            self.only_missing_dates = False
        return self


class MultiAssetRowPreviewStatsRequest(BaseModel):
    """多资产导入单行：按目标代码刷新「库内区间 / 导入影响」预览"""

    target_code: str = Field(..., description="写入行情的目标资产代码")
    prices: List[PriceDataPoint] = Field(
        ...,
        description="与 analyze 接口返回的单条 assets[].prices 结构一致",
    )

    @field_validator("prices", mode="before")
    @classmethod
    def normalize_row_preview_prices_keys(cls, v: Any) -> Any:
        return normalize_price_import_row_list(v)


class PriceImportResponse(BaseModel):
    """行情数据导入响应"""
    asset_code: str = Field(..., description="资产代码")
    total_count: int = Field(..., description="总数据条数")
    inserted_count: int = Field(..., description="新增数据条数")
    updated_count: int = Field(..., description="更新数据条数")
    skipped_count: int = Field(..., description="跳过数据条数")
    skipped_non_trade_days: int = Field(
        0,
        description="保留字段（向后兼容）：价格导入已取消按交易日历过滤，所有自然日价格均落库，本字段恒为 0",
    )
    error_count: int = Field(..., description="错误数据条数")
    errors: List[str] = Field(default_factory=list, description="错误信息列表")


class PriceCoverageResponse(BaseModel):
    """区间内相对交易日历的行情缺失情况（用于补数提示）"""
    asset_code: str
    start_date: str
    end_date: str
    calendar_mode: str = Field(
        ...,
        description="asset_calendar：资产行情日期并集；business_days：无资产日历时用工作日近似",
    )
    expected_trade_days: int
    existing_days: int
    missing_dates: List[str] = Field(default_factory=list)
    first_missing: Optional[str] = Field(None, description="按时间顺序首个缺失交易日")
    last_missing: Optional[str] = Field(
        None, description="区间内时间顺序最后一个缺失交易日（通常作为补录默认日）"
    )
