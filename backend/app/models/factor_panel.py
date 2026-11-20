# -*- coding: utf-8 -*-
"""
因子截面面板数据模型

对应集合: factor_panel（业务主键 (dataset, as_of_date, code)，一期一股一行）

写入来源: FactorPanelService（app/services/factor_panel_service.py）
- 导入时指定 dataset（受控清单见 field_mappings.FACTOR_DATASETS）
- 一个文件可含任意期数，靠 as_of_date 列区分

被消费方: 截面因子类独立策略（经 DataFeed 面板通道注入 allocate）
- 策略按 as_of 定位当期截面，取 industry / factors / total_mv 完成
  选样与定权；不消费价格矩阵以外的任何库内数据

设计要点:
- dataset 把「不同来源/不同产品的截面」隔开在同一集合内。多个策略共用本集合时，
  每个策略声明自己读哪个 dataset（get_panel_datasets），加载层按 dataset 过滤。
  不做过滤会导致两个后果：同期日不同域的行混入同一截面（名次打分分母 N 被污染）；
  以及覆盖导入按期日整片删除时跨 dataset 误删。
- factors 是开放 dict，不写死因子列名。换一套因子只改导入文件与策略参数，
  不改表结构、不改本模型。
- 日期一律 "YYYY-MM-DD" 字符串（DATA_IMPORT_SPEC 全局约定）。
"""
import re
from datetime import datetime
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# 紧凑格式与带分隔符格式分开匹配：否则「2026-09」这类残缺输入会被误拆成
# year/month/day，报出「month must be in 1..12」这种看不懂的提示。
# 分隔符可为 - / . 或年月日，末尾「日」与时间部分可选；月日允许不补零（2026-9-30），
# 这类写法在 Excel 里手输极为常见，固定长度 10 的旧校验会把正常数据判成 400。
_DATE_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DATE_SEPARATED = re.compile(
    r"^(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?$"
)


def normalize_date_str(value: Any) -> Optional[str]:
    """将日期值规范化为 YYYY-MM-DD 字符串。

    兼容 YYYYMMDD、YYYY/MM/DD、YYYY-MM-D、YYYY.M.D、YYYY年M月D日、
    带时间部分的日期字符串、datetime、pandas Timestamp；空值返回 None。
    模型校验与 URL 路径参数共用本函数，避免两处口径漂移。

    Args:
        value: 原始日期值

    Returns:
        "YYYY-MM-DD" 字符串，输入为空时返回 None

    Raises:
        ValueError: 无法识别的日期格式，或月日越界（如 2026-02-30）
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "strftime"):  # pandas Timestamp / date
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text or text.lower() in ("nan", "nat", "none"):
        return None
    # 「2026-09-30 00:00:00」这类带时间的字符串只取日期段
    head = text.split()[0] if text.split() else text
    match = _DATE_COMPACT.match(head) or _DATE_SEPARATED.match(head)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"日期不存在: {value}（{exc}）") from exc
    raise ValueError(
        f"不支持的日期格式: {value}，请使用 YYYY-MM-DD / YYYYMMDD / YYYY-M-D"
    )


class FactorPanel(BaseModel):
    """因子截面面板条目 (factor_panel 集合)

    一个数据集（dataset）的一期（as_of_date）一股（code）一行。
    因子值全部放在 factors dict 内。
    """

    id: Optional[str] = Field(None, alias="_id")
    dataset: str = Field(
        ..., description="数据集标识，区分同一集合内不同来源/产品的截面；"
        "业务主键之一，取值须在 field_mappings.FACTOR_DATASETS 清单内"
    )
    as_of_date: str = Field(
        ..., description="决策日（信号日）YYYY-MM-DD，驱动调仓；业务主键之一。"
        "T 日收盘用该截面计算权重，收益自 T+1 起；若源文件给的是持仓生效日"
        " startdate，导入前应换算为生效日前一交易日"
    )
    data_date: Optional[str] = Field(
        None, description="因子取数日 YYYY-MM-DD，仅留痕核对；缺省等于 as_of_date；"
        "晚于 as_of_date 即前视，模型直接拒绝"
    )
    code: str = Field(
        ..., description="证券代码（带交易所后缀），须与 assets.code 完全一致；业务主键之一"
    )
    name: Optional[str] = Field(None, description="证券简称，冗余存储便于人工核对，不参与计算")
    industry: str = Field(..., description="行业分组键，行业内限额按此字段分组")
    factors: Dict[str, Union[float, str]] = Field(
        default_factory=dict,
        description="因子值集合 {因子英文键: 数值或类别值}；键名由策略参数引用，开放结构。"
        "数值因子供打分/加权，类别因子（如发行人、入选标记等文本）供分组/限额",
    )
    total_mv: Optional[float] = Field(
        None, description="总市值，单位元；weight_method=market_cap 时必需且须 > 0"
    )
    free_float_mv: Optional[float] = Field(
        None, description="自由流通市值，单位元；为其他加权口径预留"
    )
    source: Optional[str] = Field(None, description="数据来源：ifind / wind / manual")
    imported_at: Optional[datetime] = Field(
        None, description="导入时间，由 service 层写入"
    )

    @field_validator("as_of_date", "data_date", mode="before")
    @classmethod
    def normalize_date(cls, v: Any) -> Optional[str]:
        """将日期字段规范化为 YYYY-MM-DD（实现见 normalize_date_str）。"""
        return normalize_date_str(v)

    @field_validator("dataset", "code", "industry", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Optional[str]:
        """去除文本字段首尾空白（代码含空格会导致与 assets.code 匹配失败）。"""
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @model_validator(mode="after")
    def check_data_date_not_after_as_of(self) -> "FactorPanel":
        """因子取数日不得晚于决策日：晚于即“用了决策日之后才披露的数据”.

        两者均为 YYYY-MM-DD，字符串序与日期序一致，直接比较即可。
        缺省（None）不比较——缺省值由 service 层补为 as_of_date。
        """
        if self.data_date and self.as_of_date and self.data_date > self.as_of_date:
            raise ValueError(
                f"因子取数日 data_date={self.data_date} 晚于决策日"
                f" as_of_date={self.as_of_date}：截面只能用决策日及之前已披露的数据"
            )
        return self

    @field_validator("total_mv", "free_float_mv", mode="before")
    @classmethod
    def coerce_mv(cls, v: Any) -> Optional[float]:
        """市值字段转 float；空值/无法解析返回 None（不静默当 0）。"""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            if not s or s.lower() in ("nan", "none", "-"):
                return None
            try:
                v = float(s)
            except ValueError:
                raise ValueError(f"市值不是有效数值: {v!r}")
        f = float(v)
        if f != f:  # NaN
            return None
        return f

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}
