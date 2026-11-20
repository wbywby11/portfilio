"""ERP 择时指数增强（打包独立形态）.

**做什么**：月末信号、次一交易日成交。用「股息率 / 十年国债 / 美债 / 汇率 / 中长期贷款」
五条序列合成改进版股债性价比 ERP2 的 920 日滚动分位，经 sigmoid 归一得到权益战略中枢；
再用三个战术信号（市场成交活跃度、行业成交集中度、高/低 PB 组月度收益差）做 ±1/±2/±3
档比例偏离；权益端在场内增强基金池（增强 ETF / 增强 LOF，不含场外基金）内按 8 因子
（超额、信息比率、稳定性、alpha、月度胜率、月度 t 值、跟踪误差贴近度、风格暴露）
做赛道内相对打分，取 Top N 且单赛道不超上限，等权买入；剩余权重全部进债券腿。

**数据来源**（全部来自引擎注入的面板，策略包不读文件、不查库）：
- ``macro_series``：DIV（中证全指股息率）、Y_CN10Y、Y_US10Y_RAW、FX_CFETS、LOAN_MLT
- ``asset_metrics``：中证全指与 31 个申万一级行业的日频成交额（三个战术信号）
- ``factor_panel`` / ``index_enhance_stock``：个股月末截面（PB + 月末收盘 + 行业）

**口径与边界**（对账时必须明示，不做静默处理）：
1. ERP2：``DIV2 = DIV × (1 + Δ(yoy_loan, 2月)/10)``，月度数据次月 15 日生效；
   ``Y2 = (1−w_us)×Y_cn + w_us×Y_us``，``w_us = clip(0.30 + 0.40×rolling_pct(FX,252)/100,
   0.30, 0.70)``；美债原始值 > 5.7 视为汇率串位，剔除后前向填充。
2. 战略中枢月度化：取「上一个月末」的 ERP2 分位，月内恒定（与原型一致），
   当日分位不参与当期决策。
3. 三个战术信号：sig1 = 中证全指成交额 MA20 的 20 日 Min-Max 高于/低于 0.5；
   sig2 = 前 10 行业成交额占比 MA15 的 30 日 Min-Max；sig3 = 月末 PB 截面按分位取
   高/低两组，比两组 ``retwin`` 期收益中位数。三者**全部有值**才计入合成信号，
   任一缺失时 S 置 0（与原型 ``nan_to_num`` 同口径），不退化成部分信号。
4. sig3 口径近似：原型用个股 20 个交易日收益逐日重算，本实现用月末到月末收盘比价
   （``retwin`` 为交易日语义，按 ``max(1, round(retwin/20))`` 期折合），期内恒定。
5. 赛道：原型用研究员标注的基金类型，系统侧无该字段，改为「与 ``track_codes`` 中
   跟踪误差最小的那只基准」由数据决定，不写死分类表；``track_codes`` 留空时回退到
   六个巨潮风格指数。``max_per_track`` 即限制同一赛道入选数。
   赛道粒度必须足够细：若只拿六个风格指数或中证全指划分，宽基指数增强基金会被
   同一只基准吸走，单赛道上限会反过来逼着选低分基金（真实验证中曾出现 247/330
   只基金归入同一赛道）。建议把沪深300/中证500/中证1000/A500/创业板/科创50/
   上证50 等跟踪标的都填进``track_codes``。
6. 赛道基线（8 因子的 mu/sd）：原型默认 ``base_mode="hist"`` 用全历史指标，存在前视；
   本实现按 ``train_months`` 窗口内同类基金现算，无前视。
7. 换手阈值带未实现：``allocate`` 是纯函数、引擎无跳期换手带，本版等价于原型
   ``--thresh 0``；1pp 阈值带列为后续（需跳期状态方案）。故不声明该参数，
   避免前端出现一个不生效的控件。
8. 成本：``cost_bp`` 显式声明为分资产费率（基金/指数/债券同一费率），默认 0 与原型一致；
   回测与监控共用同一份参数。

红线：``allocate`` 为纯函数，同输入同输出；历史不足、面板缺失、参数不自洽一律报错，
不兜底成等权、不跳过资产、不放宽断言。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.allocation.models.base import BaseStrategyModel

_TAG = "erp_timing_enhance"
_log = logging.getLogger(__name__)

# 面板名（与 data_feed.PANEL_LOADERS 注册键、get_extra_panels 声明一致）
_PANEL_MACRO = "macro_series"
_PANEL_METRICS = "asset_metrics"
_PANEL_FACTOR = "factor_panel"
_FACTOR_DATASET = "index_enhance_stock"

# 分组参数名 → 包内组键
GROUP_PARAM_TO_KEY: Dict[str, str] = {
    "fund_codes": "FUND",
    "style_codes": "STYLE",
    "bench_codes": "BENCH",
    "bond_codes": "BOND",
    "track_codes": "TRACK",
}
GROUP_KEYS: Tuple[str, ...] = ("FUND", "STYLE", "BENCH", "BOND", "TRACK")
# 允许留空的分组：留空时赛道回退到六个风格指数（与原型 STYLE_CODES 同一份）
OPTIONAL_GROUPS: Tuple[str, ...] = ("TRACK",)

# 6 个巨潮风格指数在 style_codes 中的顺序（决定 SMB/HML 的计算口径）
_STYLE_KEYS: Tuple[str, ...] = ("LG", "LV", "MG", "MV", "SG", "SV")
_STYLE_LABELS: Tuple[str, ...] = (
    "大盘成长", "大盘价值", "中盘成长", "中盘价值", "小盘成长", "小盘价值",
)

# macro_series 五条序列在 series_codes 中的顺序
_SERIES_KEYS: Tuple[str, ...] = ("DIV", "Y_CN10Y", "Y_US10Y_RAW", "FX_CFETS", "LOAN_MLT")

_FACTOR_NAMES: Tuple[str, ...] = (
    "excess", "ir", "stab", "alpha", "win", "t", "te", "style",
)

_TOL = 1e-12
_DEFAULT_ANN_DAYS = 252


# ----------------------------------------------------------------------
# 参数解析与数值工具
# ----------------------------------------------------------------------

def _as_float(value: Any, default: float, name: str) -> float:
    if value is None or value == "":
        return float(default)
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"[{_TAG}] 参数 {name} 必须是数值，收到 {value!r}")
    if not np.isfinite(out):
        raise ValueError(f"[{_TAG}] 参数 {name} 必须是有限数值，收到 {value!r}")
    return out


def _as_int(value: Any, default: int, name: str, minimum: int = 1) -> int:
    out = int(round(_as_float(value, float(default), name)))
    if out < minimum:
        raise ValueError(f"[{_TAG}] 参数 {name} 必须 >= {minimum}，收到 {out}")
    return out


def _parse_weight_map(raw: Any, default: Dict[str, float]) -> Dict[str, float]:
    """把 ``key=w,key=w`` 文本解析为权重字典；缺失项取默认值，未知键报错."""
    text = str(raw or "").strip()
    weights = dict(default)
    if text:
        weights = {}
        for chunk in text.replace(";", ",").split(","):
            part = chunk.strip()
            if not part:
                continue
            if "=" not in part and ":" not in part:
                raise ValueError(
                    f"[{_TAG}] factor_weights 片段 {part!r} 缺少 '='，应形如 excess=0.22"
                )
            key, _, val = part.replace(":", "=").partition("=")
            key = key.strip()
            if key not in _FACTOR_NAMES:
                raise ValueError(
                    f"[{_TAG}] factor_weights 含未知因子 {key!r}，可选：{list(_FACTOR_NAMES)}"
                )
            weights[key] = _as_float(val, 0.0, f"factor_weights[{key}]")
    missing = [k for k in _FACTOR_NAMES if k not in weights]
    if missing:
        raise ValueError(
            f"[{_TAG}] factor_weights 缺因子 {missing}，八项因子必须全部给出权重"
        )
    if all(abs(w) <= _TOL for w in weights.values()):
        raise ValueError(f"[{_TAG}] factor_weights 全为 0，无法排序")
    return weights


def _rolling_pct(values: np.ndarray, window: int) -> np.ndarray:
    """滚动分位（含当日），窗口不足为 NaN，取值 0~100（与原型同实现）.

    分母是整窗口长度：窗口内的 NaN 参与比较且结果为 False（与原型
    ``(sw <= sw[:, -1][:, None]).mean(axis=1)`` 逐位一致，不改用有效值分母）。
    """
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan)
    if window <= 0 or len(arr) < window:
        return out
    view = np.lib.stride_tricks.sliding_window_view(arr, window)
    last = view[:, -1]
    ratio = (view <= last[:, None]).mean(axis=1)
    out[window - 1:] = np.where(np.isfinite(last), ratio * 100.0, np.nan)
    return out


def _sigmoid_norm(q: np.ndarray, a: float) -> np.ndarray:
    """g(q) = [s(q)-s(0)] / [s(1)-s(0)]，s(x)=1/(1+e^(-a(x-0.5)))（与原型同实现）."""

    def s(z: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-a * (z - 0.5)))

    return (s(q) - s(0.0)) / (s(1.0) - s(0.0))


def _ann_ret(rets: pd.Series, ann_days: int) -> float:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if len(r) < 20:
        return float("nan")
    total = float(np.prod(1.0 + r.values))
    if total <= 0:
        return float("nan")
    return float(total ** (ann_days / len(r)) - 1.0)


def _max_dd(nav: pd.Series) -> float:
    v = pd.to_numeric(nav, errors="coerce").dropna()
    if len(v) < 2:
        return float("nan")
    return float((v / v.cummax() - 1.0).min())


def _autocorr1(values: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce").dropna()
    if len(v) < 4:
        return float("nan")
    a, b = v.values[:-1], v.values[1:]
    if a.std() < 1e-12 or b.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _robust_std(values: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce").dropna()
    if len(v) < 3:
        return float("nan")
    mad = float(np.median(np.abs(v - np.median(v))))
    sd = 1.4826 * mad
    return float(sd) if sd > 1e-9 else float(v.std(ddof=1))


def _z_abs(x: pd.Series, mu: float, sd: float, clip: float = 2.5) -> pd.Series:
    v = pd.to_numeric(x, errors="coerce")
    if not np.isfinite(mu) or not np.isfinite(sd) or sd < 1e-9:
        return pd.Series(np.nan, index=v.index)
    return ((v - mu) / sd).clip(-clip, clip)


def _z_intra(x: pd.Series, min_n: int) -> pd.Series:
    """赛道内分位映射到 [-1.6, 1.6]（与原型 ``(rank_pct-0.5)×3.2`` 同口径）."""
    v = pd.to_numeric(x, errors="coerce")
    if int(v.notna().sum()) < min_n:
        return pd.Series(np.nan, index=v.index)
    return (v.rank(pct=True) - 0.5) * 3.2


def _winsor_z(x: pd.Series, clip: float = 2.5) -> pd.Series:
    v = pd.to_numeric(x, errors="coerce")
    if int(v.notna().sum()) < 4:
        return pd.Series(np.nan, index=v.index)
    sd = float(v.std(ddof=0))
    if not np.isfinite(sd) or sd < 1e-12:
        return pd.Series(0.0, index=v.index)
    return ((v - v.mean()) / sd).clip(-clip, clip)


def _model_level_params(execution_delay: int) -> List[Any]:
    """通用模型级参数组，并把 ``execution_delay`` 的默认值对齐本策略调度声明.

    通用组的默认值为 0；本策略缺省 T+1 执行，若沿用 0 则前端按默认值提交后会把
    :meth:`get_execution_schedule` 声明的 1 覆盖成 0（Pipeline 以模型参数为准）。
    延迟塑成 0 后信号日=执行日，而回测引擎的历史窗口恒为「严格早于执行日」、
    监控适配器为「含信号日」，两者差一根 bar，选样会在名次边界上分岔。

    ``preserve_price_gaps`` 不对外：本策略的 ``min_cov`` 依赖「未 ffill 的净值列」
    才能识别停更/清盘，属算法必需的数据源口径（见 ``get_data_feed_options``），
    一旦落成模型参数默认 False 就会反向覆盖声明。
    """
    from dataclasses import replace

    from app.allocation.models.param_schema import model_level_param_group

    out: List[Any] = []
    for param in model_level_param_group():
        if param.name == "preserve_price_gaps":
            continue
        if param.name == "execution_delay":
            param = replace(
                param,
                default=int(execution_delay),
                min_value=1,
                description=(
                    "信号日到成交日的交易日延迟；本策略为月末信号、次一交易日成交（T+1），"
                    "不得低于 1"
                ),
            )
        out.append(param)
    return out


class ErpTimingEnhanceStrategy(BaseStrategyModel):
    """ERP 分位定权益中枢 + 三战术信号偏离 + 基金赛道内八因子优选（打包独立形态）."""

    # ------------------------------------------------------------------
    # 参数 Schema
    # ------------------------------------------------------------------

    @classmethod
    def get_param_schema(cls):
        from app.allocation.models.param_schema import (
            ParamSchema, StrategyParamSchema,
        )

        return StrategyParamSchema(
            strategy_type=_TAG,
            display_name="ERP 择时指数增强",
            description=(
                "月末信号、次一交易日成交：用股息率、十年国债、美债、汇率与中长期贷款合成"
                "改进版 ERP2，取 920 日滚动分位经 sigmoid 映射为权益战略中枢；再用市场成交"
                "活跃度、行业成交集中度、高低 PB 组收益差三个信号做比例偏离；权益端在"
                "场内增强基金池（只买交易所可交易的增强 ETF/LOF，不含场外基金）内按超额、"
                "信息比率、稳定性、alpha、胜率、t 值、跟踪误差贴近度与风格暴露八项"
                "因子做赛道内相对打分，取前若干只且单赛道设上限后等权买入，剩余权重进债券腿。"
                "选样/赋权/偏离/成本全部在策略包内"
            ),
            composition={
                "selector": None,
                "allocator": _TAG,
                "controller": None,
                "schedule": {"rebalance_freq": "month_end", "execution_delay": 1},
            },
            # 权重合计恒为 1（债券腿承接剩余），Pipeline 不再做杠杆缩放
            internal_leverage=True,
            params=[
                # ━━━ 资产分组（core）━━━
                ParamSchema(
                    name="fund_codes", label="场内增强基金池", type="text", default="",
                    description=(
                        "场内指数增强 ETF/LOF 候选池，逗号分隔；模型只买交易所可交易品种，"
                        "场外基金代码不应入池（回测与实盘同口径）。基金不参与债券腿与赛道基准，"
                        "只在权益端按八因子打分竞争入选名额"
                    ),
                ),
                ParamSchema(
                    name="style_codes", label="风格指数", type="text", default="",
                    description=(
                        "六个巨潮风格指数，**必须按「大盘成长、大盘价值、中盘成长、中盘价值、"
                        "小盘成长、小盘价值」的顺序**填写：既用于合成 SMB/HML 风格因子，"
                        "也作为六个赛道基准参与赛道划分"
                    ),
                ),
                ParamSchema(
                    name="bench_codes", label="宽基基准", type="text", default="",
                    description=(
                        "中证全指（恰好一只）：提供 sig1 所需的市场成交额，同时作为「全指」"
                        "赛道基准；不参与持仓"
                    ),
                ),
                ParamSchema(
                    name="track_codes", label="赛道基准", type="text", default="",
                    description=(
                        "用于划分赛道的指数池，逗号分隔（如沪深300、中证500、中证1000、"
                        "A500、创业板指、科创50、上证50）。每只基金归入与它跟踪误差最小的"
                        "一个赛道，「单赛道上限」即按此赛道计数；留空则用六个风格指数作为"
                        "赛道基准。赛道只影响名额分配，不参与持仓与信号计算"
                    ),
                ),
                ParamSchema(
                    name="bond_codes", label="债券腿", type="text", default="",
                    description="中短久期利率债指数（恰好一只），承接权益上限之外的剩余权重",
                ),
                ParamSchema(
                    name="series_codes", label="宏观序列代码", type="text",
                    default="DIV,Y_CN10Y,Y_US10Y_RAW,FX_CFETS,LOAN_MLT",
                    description=(
                        "宏观与估值序列在「宏观与估值序列」中登记的代码，**顺序固定**为"
                        "股息率、中国十年国债、美债十年、人民币汇率、中长期贷款余额；"
                        "缺任一序列即拒绝运行"
                    ),
                ),
                ParamSchema(
                    name="industry_codes", label="行业成交额代码", type="text", default="",
                    description=(
                        "参与 sig2 的申万一级行业代码，逗号分隔；留空则自动取行情库中所有"
                        "以 801 开头、带 .SL/.SI 后缀且有成交额的行业"
                    ),
                ),
                # ━━━ 择时与选样（core）━━━
                ParamSchema(
                    name="cap", label="权益仓位上限", type="number", default=0.10,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="sigmoid 映射为满档时的股票仓位；债券腿 = 1 − 该值",
                ),
                ParamSchema(
                    name="sig_weight", label="单档战术偏离", type="number", default=0.10,
                    min_value=0.0, max_value=0.30, step=0.01,
                    description=(
                        "合成信号每 ±1 档对权益分位的平移幅度（先加在 0~1 的分位上再过 "
                        "sigmoid）；三信号同向时最多平移三倍"
                    ),
                ),
                ParamSchema(
                    name="erp_window", label="ERP 分位窗口", type="number", default=920,
                    min_value=60, max_value=3000, step=1, group="advanced",
                    description="ERP2 滚动分位窗口（交易日），原型取 920 日（约 184 周）",
                ),
                ParamSchema(
                    name="select_count", label="选基数量", type="number", default=10,
                    min_value=1, max_value=50, step=1,
                    description="八因子打分后入选的基金只数，入选基金在权益端等权",
                ),
                ParamSchema(
                    name="max_per_track", label="单赛道上限", type="number", default=2,
                    min_value=1, max_value=10, step=1,
                    description=(
                        "同一赛道最多入选几只，防止全部集中在某一类指数增强上；"
                        "七个赛道 × 上限不足选样数量时按实际可选数量入选"
                    ),
                ),
                ParamSchema(
                    name="train_months", label="指标窗口（月）", type="number", default=12,
                    min_value=1, max_value=60, step=1,
                    description="计算八因子与赛道基线所用的滚动窗口长度（月）",
                ),
                ParamSchema(
                    name="min_cov", label="净值覆盖率下限", type="number", default=0.70,
                    min_value=0.0, max_value=1.0, step=0.01, group="advanced",
                    description="窗口内该基金真实净值天数占比低于此值时剔除，避免用填充值打分",
                ),
                ParamSchema(
                    name="min_days", label="最少有效天数", type="number", default=60,
                    min_value=20, max_value=500, step=1, group="advanced",
                    description="窗口内该基金有效净值天数低于此值时剔除",
                ),
                ParamSchema(
                    name="factor_weights", label="八因子权重", type="text",
                    default="excess=0.22,ir=0.20,stab=0.18,alpha=0.12,win=0.10,t=0.06,te=0.06,style=0.06",
                    group="advanced",
                    description=(
                        "八项因子权重，形如 excess=0.22,ir=0.20,...；八项必须全部给出，"
                        "未知因子名直接报错"
                    ),
                ),
                ParamSchema(
                    name="w_abs", label="绝对分权重", type="number", default=0.5,
                    min_value=0.0, max_value=1.0, step=0.05, group="advanced",
                    description="赛道调整中「相对赛道基线」与「赛道内名次」的合成比例，另一侧为 1−该值",
                ),
                ParamSchema(
                    name="intra_min_n", label="赛道内打分最少只数", type="number", default=4,
                    min_value=2, max_value=50, step=1, group="advanced",
                    description="赛道内基金数少于此值时该赛道内名次分记为缺失，只用绝对分",
                ),
                ParamSchema(
                    name="track_min_funds", label="赛道基线最少只数", type="number", default=3,
                    min_value=2, max_value=50, step=1, group="advanced",
                    description="赛道内基金数少于此值时不单独建基线，并入全池基线，避免小样本噪声",
                ),
                # ━━━ 信号与风格（advanced）━━━
                ParamSchema(
                    name="fx_window", label="汇率分位窗口", type="number", default=252,
                    min_value=20, max_value=1500, step=1, group="advanced",
                    description="决定美债权重 w_us 的汇率滚动分位窗口（交易日）",
                ),
                ParamSchema(
                    name="delta_months", label="贷款同比变化回看（月）", type="number", default=2,
                    min_value=1, max_value=12, step=1, group="advanced",
                    description="股息率乘数使用的贷款余额同比变化回看月数",
                ),
                ParamSchema(
                    name="y_us_bad", label="美债串位阈值", type="number", default=5.7,
                    min_value=1.0, max_value=20.0, step=0.1, group="advanced",
                    description="美债十年原始值高于此阈值视为汇率列串位，剔除后前向填充",
                ),
                ParamSchema(
                    name="w_us_lo", label="美债权重下界", type="number", default=0.30,
                    min_value=0.0, max_value=1.0, step=0.01, group="advanced",
                    description="美债权重的下限（clip 下界）",
                ),
                ParamSchema(
                    name="w_us_hi", label="美债权重上界", type="number", default=0.70,
                    min_value=0.0, max_value=1.0, step=0.01, group="advanced",
                    description="美债权重的上限（clip 上界）",
                ),
                ParamSchema(
                    name="sigmoid_a", label="sigmoid 斜率", type="number", default=10.0,
                    min_value=1.0, max_value=50.0, step=0.5, group="advanced",
                    description="分位到仓位的 S 曲线陡峭度，值越大越接近阈值开关",
                ),
                ParamSchema(
                    name="retwin", label="sig3 收益回看（交易日）", type="number", default=20,
                    min_value=1, max_value=250, step=1, group="advanced",
                    description=(
                        "高/低 PB 组比较收益的窗口，按交易日语义填写；月末截面按 "
                        "max(1, round(retwin/20)) 期折合"
                    ),
                ),
                ParamSchema(
                    name="pb_quantile", label="PB 分组分位", type="number", default=0.2,
                    min_value=0.05, max_value=0.5, step=0.01, group="advanced",
                    description="sig3 高/低组各取 PB 截面两端的分位比例",
                ),
                ParamSchema(
                    name="min_stocks_per_period", label="截面最少股票数", type="number", default=10,
                    min_value=4, max_value=500, step=1, group="advanced",
                    description="某期有效 PB 股票数低于此值时该期不做 sig3 分组",
                ),
                ParamSchema(
                    name="min_leg_size", label="分组最少股票数", type="number", default=5,
                    min_value=2, max_value=500, step=1, group="advanced",
                    description="高组或低组有效收益股票数低于此值时该期 sig3 记为缺失",
                ),
                ParamSchema(
                    name="ann_days", label="年化交易日", type="number", default=252,
                    min_value=200, max_value=366, step=1, group="advanced",
                    description="八因子内部年化基数（原型 252），系统展示指标仍按 260 计算",
                ),
                # ━━━ 成本（core）━━━
                ParamSchema(
                    name="cost_bp", label="单边费率（bp）", type="number", default=0.0,
                    min_value=0.0, max_value=100.0, step=0.5,
                    description="基金与债券腿统一的单边换手费率（bp）；默认 0 与原型一致",
                ),
                # ━━━ 模型级通用执行参数（调度/引擎层消费） ━━━
                *_model_level_params(1),
            ],
        )

    # ------------------------------------------------------------------
    # 调度、面板与数据契约
    # ------------------------------------------------------------------

    @classmethod
    def get_extra_panels(cls) -> list:
        """声明三类面板：宏观序列（ERP）、成交额截面（sig1/sig2）、个股月末截面（sig3）."""
        return [_PANEL_MACRO, _PANEL_METRICS, _PANEL_FACTOR]

    @classmethod
    def get_panel_datasets(cls) -> dict:
        """factor_panel 按数据集分区，必须声明读 index_enhance_stock.

        不声明会把债券券池等其他数据集的同期日行并进 sig3 截面，PB 分组的分母被污染。
        """
        return {_PANEL_FACTOR: _FACTOR_DATASET}

    def get_data_feed_options(self) -> Dict[str, Any]:
        """加载三类面板；声明缺日保真，使覆盖率能反映真实净值天数.

        ``preserve_price_gaps=True``：引擎传入未前向填充的价格矩阵，``min_cov``
        才能识别「基金成立晚、中途停更、清盘后无净值」；若用的是 ffill 后的矩阵，
        后段停更会被填成恒定价格、覆盖率虚高到 100%，选样会把不可用的基金当满窗口
        样本打分。本策略在 ``_sanitize_prices`` 内部自行 ffill 供收益计算，
        覆盖率判定用收到的那份矩阵，两者互不干扰。

        ``panel_event_dates`` 保持缺省（False）：三个面板分别是日频、日频、月频，
        任一被当作调仓事件日都会把月末调仓改成面板驱动，与调度声明脱钩。
        """
        return {
            "extra_panels": [_PANEL_MACRO, _PANEL_METRICS, _PANEL_FACTOR],
            "preserve_price_gaps": True,
        }

    def get_execution_schedule(self) -> Optional[dict]:
        """月末信号、次一交易日成交；不写 selection_start_date / skip_dates 等日期常量."""
        return {"rebalance_freq": "month_end", "execution_delay": 1}

    def get_trading_costs(self, params: Dict[str, Any]) -> Dict[str, float]:
        """把 ``cost_bp`` 声明为全池统一单边费率.

        引擎按 code 在成交时扣费（``Σ|目标−调仓前实际权重| × 费率``），与原型
        ``Σ|Δw| × cost`` 同口径；监控侧取同一份参数，不出现一边计费一边不计费。
        """
        rate = _as_float(params.get("cost_bp"), 0.0, "cost_bp") / 10000.0
        if rate <= 0:
            return {}
        from app.backtesting.data_contract import parse_asset_codes

        codes: List[str] = []
        for param_name in GROUP_PARAM_TO_KEY:
            for code in parse_asset_codes(params.get(param_name)):
                if code not in codes:
                    codes.append(code)
        return {code: rate for code in codes}

    def has_native_vol_control(self) -> bool:
        """不声明包内日度风控：仓位只在月末随 ERP 分位变化，无日度触发."""
        return False

    @classmethod
    def get_data_contract(cls):
        """声明数据契约：五组覆盖全池 + 资产大类匹配 + 参数自洽.

        ``max_single_day_jump`` 取 0.20：池内是基金复权净值与债券指数，实测单日跳变
        远小于该值，阈值只用于拦截明显的行情串位；不声明 ``min_history_days`` /
        ``min_assets``——窗口与规模由前端参数控。
        """
        from app.backtesting.data_contract import DataContract, GroupSpec

        return DataContract(
            max_single_day_jump=0.20,
            group_params={
                "fund_codes": GroupSpec(required=True, cover_pool=True),
                "style_codes": GroupSpec(required=True, cover_pool=True),
                "bench_codes": GroupSpec(required=True, cover_pool=True),
                "bond_codes": GroupSpec(required=True, cover_pool=True),
                "track_codes": GroupSpec(required=False, cover_pool=True),
            },
            expected_asset_class={
                "fund_codes": "权益",
                "style_codes": "权益",
                "bench_codes": "权益",
                "bond_codes": "固收",
                "track_codes": "权益",
            },
            custom_checks=("param_consistency",),
        )

    def _check_param_consistency(
        self, prices: pd.DataFrame, params: Dict[str, Any]
    ) -> Optional[str]:
        """参数自洽检查（契约门禁）：不自洽时返回失败原因，由门禁统一拒绝运行."""
        try:
            cfg = self._parse_config(params)
        except ValueError as exc:
            return str(exc)
        from app.backtesting.data_contract import parse_asset_codes

        styles = parse_asset_codes(params.get("style_codes"))
        if len(styles) != len(_STYLE_KEYS):
            return (
                f"风格指数必须恰好 {len(_STYLE_KEYS)} 只（顺序：{'、'.join(_STYLE_LABELS)}），"
                f"当前 {len(styles)} 只：{styles}"
            )
        if len(parse_asset_codes(params.get("bench_codes"))) != 1:
            return "宽基基准必须恰好 1 只（中证全指）"
        if len(parse_asset_codes(params.get("bond_codes"))) != 1:
            return "债券腿必须恰好 1 只（中短久期利率债指数）"
        tracks = parse_asset_codes(params.get("track_codes"))
        if not tracks:
            # 留空即回退到六个风格指数，赛道数按 6 计
            tracks = list(_STYLE_KEYS)
        if len(tracks) != len(set(tracks)):
            return f"赛道基准含重复代码：{tracks}"
        if len(parse_asset_codes(params.get("fund_codes"))) < cfg["select_count"]:
            return (
                f"基金池只有 {len(parse_asset_codes(params.get('fund_codes')))} 只，"
                f"少于选样数量 {cfg['select_count']}"
            )
        if cfg["w_us_lo"] > cfg["w_us_hi"]:
            return f"美债权重下界 {cfg['w_us_lo']} 高于上界 {cfg['w_us_hi']}"
        if cfg["cap"] <= 0:
            return "权益仓位上限必须大于 0"
        if cfg["select_count"] > cfg["max_per_track"] * len(tracks):
            return (
                f"选样数量 {cfg['select_count']} 超过「赛道数 × 单赛道上限」"
                f"（{len(tracks)} × {cfg['max_per_track']} = {len(tracks) * cfg['max_per_track']}），"
                "名额不可达；请增加赛道基准、提高单赛道上限或减少选样数量"
            )
        return None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """信号日收盘计算目标权重（纯函数；缓存只存跨期不变的面板物化结果）."""
        if prices is None or not isinstance(prices, pd.DataFrame) or prices.empty:
            raise ValueError(f"[{_TAG}] 价格矩阵为空，无法计算")
        pool = list(prices.columns)
        cfg = self._parse_config(params)
        groups = self._resolve_groups(params, pool)
        px = self._sanitize_prices(prices, groups)

        cal = pd.DatetimeIndex(px.index)
        q_erp = self._erp_quantile(cal, cfg, params)
        sig = self._composite_signal(cal, cfg, params)
        w_equity = self._equity_weight(q_erp, sig, cfg)

        scored, tracks = self._score_funds(prices, px, groups, cfg, params)
        picked = self._pick(scored, cfg)
        weights = self._combine(picked, w_equity, groups, pool)
        self._audit(q_erp, sig, w_equity, picked, tracks, cfg)
        self._final_check(weights, cfg)
        return weights

    # ------------------------------------------------------------------
    # 参数与分组
    # ------------------------------------------------------------------

    def _parse_config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """把 params 归一为本期计算所需配置（一次性解析，避免散落在各步）."""
        series = [s.strip().upper() for s in str(
            params.get("series_codes") or ",".join(_SERIES_KEYS)
        ).replace(";", ",").split(",") if s.strip()]
        if len(series) != len(_SERIES_KEYS):
            raise ValueError(
                f"[{_TAG}] series_codes 必须给出 {len(_SERIES_KEYS)} 个代码"
                f"（顺序：{'、'.join(_SERIES_KEYS)}），收到 {series}"
            )
        cfg: Dict[str, Any] = {
            "series_codes": dict(zip(_SERIES_KEYS, series)),
            "industry_codes": [c.strip().upper() for c in str(
                params.get("industry_codes") or ""
            ).replace(";", ",").split(",") if c.strip()],
            "cap": _as_float(params.get("cap"), 0.10, "cap"),
            "sig_weight": _as_float(params.get("sig_weight"), 0.10, "sig_weight"),
            "erp_window": _as_int(params.get("erp_window"), 920, "erp_window", 60),
            "fx_window": _as_int(params.get("fx_window"), 252, "fx_window", 20),
            "delta_months": _as_int(params.get("delta_months"), 2, "delta_months", 1),
            "y_us_bad": _as_float(params.get("y_us_bad"), 5.7, "y_us_bad"),
            "w_us_lo": _as_float(params.get("w_us_lo"), 0.30, "w_us_lo"),
            "w_us_hi": _as_float(params.get("w_us_hi"), 0.70, "w_us_hi"),
            "sigmoid_a": _as_float(params.get("sigmoid_a"), 10.0, "sigmoid_a"),
            "select_count": _as_int(params.get("select_count"), 10, "select_count", 1),
            "max_per_track": _as_int(params.get("max_per_track"), 2, "max_per_track", 1),
            "train_months": _as_int(params.get("train_months"), 12, "train_months", 1),
            "min_cov": _as_float(params.get("min_cov"), 0.70, "min_cov"),
            "min_days": _as_int(params.get("min_days"), 60, "min_days", 20),
            "retwin": _as_int(params.get("retwin"), 20, "retwin", 1),
            "pb_quantile": _as_float(params.get("pb_quantile"), 0.2, "pb_quantile"),
            "min_stocks_per_period": _as_int(
                params.get("min_stocks_per_period"), 10, "min_stocks_per_period", 4),
            "min_leg_size": _as_int(params.get("min_leg_size"), 5, "min_leg_size", 2),
            "track_min_funds": _as_int(params.get("track_min_funds"), 3, "track_min_funds", 2),
            "w_abs": _as_float(params.get("w_abs"), 0.5, "w_abs"),
            "intra_min_n": _as_int(params.get("intra_min_n"), 4, "intra_min_n", 2),
            "ann_days": _as_int(params.get("ann_days"), _DEFAULT_ANN_DAYS, "ann_days", 200),
            "cost_bp": _as_float(params.get("cost_bp"), 0.0, "cost_bp"),
            "strict_validate": bool(params.get("strict_validate", True)),
        }
        cfg["factor_weights"] = _parse_weight_map(
            params.get("factor_weights"),
            {"excess": 0.22, "ir": 0.20, "stab": 0.18, "alpha": 0.12,
             "win": 0.10, "t": 0.06, "te": 0.06, "style": 0.06},
        )
        cfg["w_intra"] = max(0.0, 1.0 - cfg["w_abs"])
        if cfg["sig_weight"] < 0:
            raise ValueError(f"[{_TAG}] sig_weight 不得为负")
        if not 0.0 <= cfg["w_abs"] <= 1.0:
            raise ValueError(f"[{_TAG}] w_abs 必须在 [0, 1] 内")
        if cfg["pb_quantile"] <= 0 or cfg["pb_quantile"] >= 0.5:
            raise ValueError(f"[{_TAG}] pb_quantile 必须在 (0, 0.5) 内，收到 {cfg['pb_quantile']}")
        return cfg

    def _resolve_groups(
        self, params: Dict[str, Any], pool: Sequence[str]
    ) -> Dict[str, List[str]]:
        """解析四个分组参数；``strict_validate`` 下池内有资产未归组即报错."""
        from app.backtesting.data_contract import parse_asset_codes

        pool_set = set(pool)
        groups: Dict[str, List[str]] = {key: [] for key in GROUP_KEYS}
        unknown: Dict[str, List[str]] = {}
        for param_name, group_key in GROUP_PARAM_TO_KEY.items():
            codes = parse_asset_codes(params.get(param_name))
            inside = [c for c in codes if c in pool_set]
            outside = [c for c in codes if c not in pool_set]
            if outside:
                unknown[param_name] = outside
            groups[group_key] = inside

        strict = bool(params.get("strict_validate", True))
        if unknown:
            detail = "; ".join(f"{k}={v[:5]}{'...' if len(v) > 5 else ''}"
                               for k, v in unknown.items())
            if strict:
                raise ValueError(
                    f"[{_TAG}] 分组参数含资产池之外的代码：{detail}。"
                    "分组参数必须与模型资产池同步维护"
                )
            _log.warning("[%s] 分组参数含池外代码（已忽略）：%s", _TAG, detail)

        empty = [p for p, k in GROUP_PARAM_TO_KEY.items()
                 if not groups[k] and k not in OPTIONAL_GROUPS]
        if empty and strict:
            raise ValueError(
                f"[{_TAG}] 分组为空：{empty}。本策略需要基金池、六个风格指数、宽基基准、"
                "债券腿，缺一组无法计算赛道或剩余权重"
            )
        if strict and len(groups["STYLE"]) != len(_STYLE_KEYS):
            raise ValueError(
                f"[{_TAG}] 风格指数必须恰好 {len(_STYLE_KEYS)} 只且都在资产池内，"
                f"实际 {groups['STYLE']}"
            )
        if strict:
            covered = {c for members in groups.values() for c in members}
            missing = [c for c in pool if c not in covered]
            if missing:
                raise ValueError(
                    f"[{_TAG}] 资产池内 {len(missing)} 只资产未归入任何分组：{missing[:10]}。"
                    "请补齐四个分组参数，或关闭 strict_validate"
                )
        return groups

    def _sanitize_prices(
        self, prices: pd.DataFrame, groups: Dict[str, List[str]]
    ) -> pd.DataFrame:
        """抽取分组资产、前向填充缺日、校验价格为正.

        与前向填充后的矩阵相比，这里只在「核心资产」（六个风格指数、宽基基准、
        债券腿）上要求共同有效区间：基金池有几百只、成立日各不相同，对全列
        ``dropna(how="any")`` 会把整段历史截到最晚成立的那只基金，样本被腰斩。
        基金列保留上市前的 NaN（ffill 填不了前导空值），由 ``_score_funds``
        的覆盖率与有效天数两道门禁剔除。
        """
        cols: List[str] = []
        for group_key in GROUP_KEYS:
            for code in groups[group_key]:
                if code not in cols:
                    cols.append(code)
        if not cols:
            raise ValueError(f"[{_TAG}] 四个分组均无资产，无法计算")
        px = prices.loc[:, cols].apply(pd.to_numeric, errors="coerce")
        px = px.replace([float("inf"), float("-inf")], float("nan")).ffill()

        funds = set(groups["FUND"])
        core = [c for c in cols if c not in funds]
        if not core:
            raise ValueError(f"[{_TAG}] 缺少风格、基准、债券腿资产，无法计算信号与赛道基准")
        px = px.dropna(subset=core)
        if px.empty:
            raise ValueError(
                f"[{_TAG}] 风格指数、宽基基准与债券腿在价格矩阵上不存在共同有效区间，无法计算"
            )
        bad_core = [c for c in core if bool((px[c] <= 0).any())]
        if bad_core:
            raise ValueError(f"[{_TAG}] 以下资产存在非正价格：{bad_core[:10]}，请核查行情数据")
        bad_fund = [
            c for c in groups["FUND"]
            if c in px.columns and bool((px[c].dropna() <= 0).any())
        ]
        if bad_fund:
            raise ValueError(f"[{_TAG}] 以下基金存在非正净值：{bad_fund[:10]}，请核查行情数据")
        if len(px) < 2:
            raise ValueError(f"[{_TAG}] 有效价格行数 {len(px)} 不足 2 行，无法计算收益")
        return px

    # ------------------------------------------------------------------
    # ERP 分位
    # ------------------------------------------------------------------

    def _panel(self, params: Dict[str, Any], name: str) -> Dict[pd.Timestamp, pd.DataFrame]:
        """取引擎注入的面板字典；缺面板即报错，不退化成默认值."""
        panels = params.get(f"_panel_{name}")
        if not panels:
            hints = {
                _PANEL_MACRO: "请在「宏观与估值序列」导入五条 ERP 分量序列",
                _PANEL_METRICS: "请在「资产行情」导入中证全指与申万行业的成交额",
                _PANEL_FACTOR: "请在「因子截面数据」导入 index_enhance_stock",
            }
            raise ValueError(f"[{_TAG}] 未注入 {name} 面板，{hints.get(name, '')}")
        return panels

    def _macro_series(
        self, cfg: Dict[str, Any], params: Dict[str, Any]
    ) -> Dict[str, pd.Series]:
        """从 macro_series 面板抽出五条序列（面板整份注入，按需物化一次并缓存）."""
        panels = self._panel(params, _PANEL_MACRO)
        state = self._ensure_state()
        key = (id(panels), len(panels), tuple(cfg["series_codes"].items()))
        cached = state.get("_macro_cache")
        if cached is not None and cached[0] == key:
            return cached[1]

        out: Dict[str, pd.Series] = {}
        for logical, code in cfg["series_codes"].items():
            values: Dict[pd.Timestamp, float] = {}
            for dt, frame in panels.items():
                if not isinstance(frame, pd.DataFrame) or code not in frame.index:
                    continue
                try:
                    raw = frame.loc[code, "value"]
                except (KeyError, TypeError):
                    continue
                if isinstance(raw, pd.Series):
                    raw = raw.iloc[0]
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if np.isfinite(value):
                    values[pd.Timestamp(dt).normalize()] = value
            if not values:
                raise ValueError(
                    f"[{_TAG}] macro_series 面板中没有序列 {code!r}（{logical}）的任何取值。"
                    "请核对 series_codes 与已导入的序列代码"
                )
            out[logical] = pd.Series(values).sort_index()
        state["_macro_cache"] = (key, out)
        return out

    def _erp_frame(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> pd.DataFrame:
        """复现改进版 ERP2 与滚动分位（与原型 ``build_erp`` 同口径）.

        ``DIV2 = DIV × MULT``，``MULT = 1 + Δ(yoy_loan, delta_months)/10``，
        月度数据次月 15 日生效；``Y2 = (1−w_us)×Y_cn + w_us×Y_us``；
        ``w_us`` 由汇率滚动分位线性映射并 clip；美债原始值超阈值视为汇率串位。
        """
        state = self._ensure_state()
        key = (id(params.get(f"_panel_{_PANEL_MACRO}")), len(params.get(f"_panel_{_PANEL_MACRO}") or {}),
               tuple(cfg["series_codes"].items()), cfg["fx_window"], cfg["erp_window"],
               cfg["delta_months"], cfg["y_us_bad"], cfg["w_us_lo"], cfg["w_us_hi"])
        cached = state.get("_erp_cache")
        if cached is not None and cached[0] == key:
            return cached[1]

        src = self._macro_series(cfg, params)
        sig_cal = src["DIV"].index
        df = pd.DataFrame(index=sig_cal)
        df["DIV"] = src["DIV"].reindex(sig_cal)
        df["Y"] = src["Y_CN10Y"].reindex(sig_cal).ffill()
        df["Y_us_raw"] = src["Y_US10Y_RAW"].reindex(sig_cal)
        df["FX"] = src["FX_CFETS"].reindex(sig_cal).ffill()

        bad = (df["Y_us_raw"] > cfg["y_us_bad"]) | df["Y_us_raw"].isna()
        df["Y_us"] = df["Y_us_raw"].where(~bad).ffill()

        loan = src["LOAN_MLT"].dropna()
        need = cfg["delta_months"] + 13
        if len(loan) < need:
            raise ValueError(
                f"[{_TAG}] 中长期贷款序列只有 {len(loan)} 个期值，不足以计算 "
                f"{cfg['delta_months']} 个月的同比变化差分（至少需 {need} 个）"
            )
        yoy = (loan / loan.shift(12) - 1.0) * 100.0
        delta_pp = yoy - yoy.shift(cfg["delta_months"])
        mult = 1.0 + delta_pp / 10.0
        mh = mult.copy()
        mh.index = mh.index + pd.offsets.MonthBegin(1)
        mh.index = pd.DatetimeIndex([d.replace(day=15) for d in mh.index])
        df["MULT"] = mh.reindex(df.index, method="ffill")
        if df["MULT"].notna().sum() == 0:
            raise ValueError(
                f"[{_TAG}] 股息率序列起点 {df.index[0].date()} 早于贷款乘数的首个生效日，"
                "MULT 全为空；请确认贷款序列覆盖股息率区间"
            )

        pct_fx = pd.Series(
            _rolling_pct(df["FX"].values, cfg["fx_window"]), index=df.index)
        df["W_US"] = (0.30 + 0.40 * pct_fx / 100.0).clip(cfg["w_us_lo"], cfg["w_us_hi"])
        df["DIV2"] = df["DIV"] * df["MULT"]
        df["Y2"] = (1.0 - df["W_US"]) * df["Y"] + df["W_US"] * df["Y_us"]
        df["ERP2"] = df["DIV2"] - df["Y2"]
        df["PCT"] = _rolling_pct(df["ERP2"].values, cfg["erp_window"])
        state["_erp_cache"] = (key, df)
        return df

    def _erp_quantile(
        self, cal: pd.DatetimeIndex, cfg: Dict[str, Any], params: Dict[str, Any]
    ) -> float:
        """信号日的战略中枢：取「上一个月末」的 ERP2 分位，月内恒定.

        与原型 ``qs.reindex(me).shift(1).reindex(cal, method='ffill')`` 同构；
        分位缺失（窗口不足）按 0.5 处理，与原型 ``nan_to_num(nan=0.5)`` 一致。
        """
        erp = self._erp_frame(cfg, params)
        pct = erp["PCT"].reindex(cal).ffill() / 100.0
        q = pct.clip(0.0, 1.0).fillna(0.5)
        series = pd.Series(q.values, index=cal)
        month_end = series.groupby([cal.year, cal.month]).apply(lambda x: x.index[-1])
        prev = series.reindex(month_end).shift(1)
        rolled = prev.reindex(cal, method="ffill").ffill()
        rolled = rolled.fillna(float(series.iloc[0]))
        return float(np.clip(rolled.iloc[-1], 0.0, 1.0))

    # ------------------------------------------------------------------
    # 三战术信号
    # ------------------------------------------------------------------

    def _amount_series(self, params: Dict[str, Any], code: str) -> Optional[pd.Series]:
        """从 asset_metrics 面板抽单资产的日频成交额."""
        panels = self._panel(params, _PANEL_METRICS)
        values: Dict[pd.Timestamp, float] = {}
        for dt, frame in panels.items():
            if not isinstance(frame, pd.DataFrame) or "amount" not in frame.columns:
                continue
            if code not in frame.index:
                continue
            try:
                raw = frame.loc[code, "amount"]
            except (KeyError, TypeError):
                continue
            if isinstance(raw, pd.Series):
                raw = raw.iloc[0]
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if np.isfinite(value) and value > 0:
                values[pd.Timestamp(dt).normalize()] = value
        if not values:
            return None
        return pd.Series(values).sort_index()

    def _industry_codes(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
        """解析 sig2 的行业代码：参数优先，留空则从面板里按申万代码规范自动取."""
        if cfg["industry_codes"]:
            return list(cfg["industry_codes"])
        panels = self._panel(params, _PANEL_METRICS)
        found: Dict[str, str] = {}
        for frame in panels.values():
            if not isinstance(frame, pd.DataFrame):
                continue
            for code in frame.index:
                text = str(code).upper()
                if not text.startswith("801"):
                    continue
                if not (text.endswith(".SL") or text.endswith(".SI")):
                    continue
                stem = text.split(".")[0]
                # 同一行业两套后缀只保留一套（.SL 优先，与计划边界 4 一致）
                if stem not in found or text.endswith(".SL"):
                    found[stem] = text
        if not found:
            raise ValueError(
                f"[{_TAG}] 面板里找不到任何申万一级行业成交额（801xxx.SL/.SI），sig2 无法计算。"
                "请在「资产行情」导入行业成交额，或在「行业成交额代码」中显式指定"
            )
        return [found[k] for k in sorted(found)]

    def _industry_amount_matrix(
        self, params: Dict[str, Any], codes: Sequence[str]
    ) -> pd.DataFrame:
        """把行业成交额拼成「日期 × 行业」矩阵（缓存；面板整份不变）."""
        panels = self._panel(params, _PANEL_METRICS)
        state = self._ensure_state()
        key = (id(panels), len(panels), tuple(codes))
        cached = state.get("_ind_amt_cache")
        if cached is not None and cached[0] == key:
            return cached[1]
        rows: Dict[pd.Timestamp, pd.Series] = {}
        for dt, frame in panels.items():
            if not isinstance(frame, pd.DataFrame) or "amount" not in frame.columns:
                continue
            sub = pd.to_numeric(frame.reindex(list(codes))["amount"], errors="coerce")
            if sub.notna().any():
                rows[pd.Timestamp(dt).normalize()] = sub
        matrix = pd.DataFrame(rows).T.sort_index() if rows else pd.DataFrame(columns=list(codes))
        state["_ind_amt_cache"] = (key, matrix)
        return matrix

    @staticmethod
    def _minmax_signal(score: pd.Series, thr: float = 0.5) -> pd.Series:
        """把 0~1 的归一化分数映射为 ±1；分数缺失记为 0（与原型一致）."""
        sig = pd.Series(
            np.where(score > thr, 1.0, np.where(score < thr, -1.0, 0.0)),
            index=score.index, dtype=float,
        )
        sig[score.isna()] = 0.0
        return sig

    def _sig1(self, cal: pd.DatetimeIndex, params: Dict[str, Any]) -> pd.Series:
        """sig1：中证全指成交额 MA20 的 20 日 Min-Max 高于/低于 0.5."""
        from app.backtesting.data_contract import parse_asset_codes

        bench = parse_asset_codes(params.get("bench_codes"))
        if not bench:
            raise ValueError(f"[{_TAG}] 宽基基准为空，sig1 无法定位市场成交额")
        amount = self._amount_series(params, bench[0])
        if amount is None:
            raise ValueError(
                f"[{_TAG}] asset_metrics 面板中没有 {bench[0]} 的成交额，sig1 无法计算。"
                "请在「资产行情」补导该指数的 amount"
            )
        ma = amount.rolling(20, min_periods=20).mean()
        rmin = ma.rolling(20, min_periods=20).min()
        rmax = ma.rolling(20, min_periods=20).max()
        span = (rmax - rmin).replace(0.0, np.nan)
        sig = self._minmax_signal((ma - rmin) / span)
        return sig.reindex(cal).ffill()

    def _sig2(self, cal: pd.DatetimeIndex, cfg: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        """sig2：前 10 行业成交额占比 MA15 的 30 日 Min-Max 高于/低于 0.5."""
        codes = self._industry_codes(cfg, params)
        matrix = self._industry_amount_matrix(params, codes)
        if matrix.empty:
            raise ValueError(f"[{_TAG}] 行业成交额矩阵为空，sig2 无法计算")
        total = matrix.sum(axis=1, min_count=1)
        rank = matrix.rank(axis=1, ascending=False, method="first")
        top = matrix.where(rank <= 10).sum(axis=1, min_count=1)
        conc = (top / total).replace([np.inf, -np.inf], np.nan)
        smooth = conc.rolling(15, min_periods=15).mean()
        rmin = smooth.rolling(30, min_periods=30).min()
        rmax = smooth.rolling(30, min_periods=30).max()
        span = (rmax - rmin).replace(0.0, np.nan)
        sig = self._minmax_signal((smooth - rmin) / span)
        return sig.reindex(cal).ffill()

    def _sig3_periods(self, cfg: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        """逐期计算 sig3：月末 PB 分组后比高/低组的 ``retwin`` 期收益中位数.

        分组用当期截面、收益用「当期收盘 / 前 k 期收盘 − 1」，两者在月末收盘时
        均已实现，无前视。某期有效股票数不足时该期记为「不可算」，由调用方按 0 处理
        （原型同一行为：样本不足即中性，不退化成用部分样本瞎猜）。
        """
        panels = self._panel(params, _PANEL_FACTOR)
        state = self._ensure_state()
        k = max(1, int(round(cfg["retwin"] / 20.0)))
        key = (id(panels), len(panels), k, cfg["pb_quantile"],
               cfg["min_stocks_per_period"], cfg["min_leg_size"])
        cached = state.get("_sig3_cache")
        if cached is not None and cached[0] == key:
            return cached[1]

        periods = sorted(pd.Timestamp(p) for p in panels)
        if len(periods) <= k:
            raise ValueError(
                f"[{_TAG}] factor_panel 只有 {len(periods)} 期截面，sig3 需要至少 {k + 1} 期"
                f"（retwin={cfg['retwin']} 折合 {k} 期收益）"
            )
        pb_map: Dict[pd.Timestamp, pd.Series] = {}
        close_map: Dict[pd.Timestamp, pd.Series] = {}
        for period in periods:
            frame = panels[period]
            for col in ("pb", "close"):
                if col not in frame.columns:
                    raise ValueError(
                        f"[{_TAG}] factor_panel 的 {period.date()} 截面缺少 {col!r} 列，"
                        "请核对 index_enhance_stock 的因子列映射"
                    )
            pb = pd.to_numeric(frame["pb"], errors="coerce")
            close = pd.to_numeric(frame["close"], errors="coerce")
            ok = (pb > 0) & (close > 0)
            pb_map[period] = pb[ok]
            close_map[period] = close[ok]

        rows: Dict[pd.Timestamp, float] = {}
        for i in range(k, len(periods)):
            period = periods[i]
            pb = pb_map[period]
            if len(pb) < cfg["min_stocks_per_period"]:
                continue
            base = close_map[periods[i - k]]
            ret = (close_map[period] / base - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
            if ret.empty:
                continue
            ordered = pb.sort_values()
            n = len(ordered)
            n_leg = int(n * cfg["pb_quantile"])
            if n_leg < 1:
                continue
            low = set(ordered.index[:n_leg])
            high = set(ordered.index[n - n_leg:])
            high_ret = ret[ret.index.isin(high)]
            low_ret = ret[ret.index.isin(low)]
            if len(high_ret) < cfg["min_leg_size"] or len(low_ret) < cfg["min_leg_size"]:
                continue
            rows[period] = 1.0 if float(high_ret.median() - low_ret.median()) > 0 else -1.0

        series = pd.Series(rows, dtype=float).sort_index() if rows else pd.Series(dtype=float)
        if series.empty:
            _log.warning(
                "[%s] factor_panel %d 期中没有一期能算出 sig3（每期有效 PB 股票需 ≥%d 且高/低组收益样本 ≥%d），"
                "本期合成信号只用 sig1+sig2",
                _TAG, len(periods), cfg["min_stocks_per_period"], cfg["min_leg_size"],
            )
        state["_sig3_cache"] = (key, series)
        return series

    def _sig3(self, cal: pd.DatetimeIndex, cfg: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        """把期频 sig3 前向填充到交易日轴，**保留 NaN**（不并用部分信号）.

        原型 ``valid = notna().all(axis=1); S[~valid] = nan`` 要求三信号同时有值，
        此处不能把缺失期填 0：一旦填 0 就变成「三信号里只用两个」的真实仓位，
        偏离原型口径。缺失期由 ``_composite_signal`` 统一置 S=0。
        """
        series = self._sig3_periods(cfg, params)
        if series.empty:
            return pd.Series(np.nan, index=cal)
        return series.reindex(cal, method="ffill")

    def _composite_signal(
        self, cal: pd.DatetimeIndex, cfg: Dict[str, Any], params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """合成信号 S = sig1 + sig2 + sig3；三者须同时有值，否则 S 记 0.

        与原型 ``valid = notna().all(axis=1); S[~valid] = nan; nan_to_num(nan=0)``
        同一口径：任一信号缺失即视为「无法判断」取中性，不用部分信号代替。
        """
        sig1 = self._sig1(cal, params)
        sig2 = self._sig2(cal, cfg, params)
        sig3 = self._sig3(cal, cfg, params)
        frame = pd.DataFrame({"sig1": sig1, "sig2": sig2, "sig3": sig3}, index=cal)
        valid = frame[["sig1", "sig2", "sig3"]].notna().all(axis=1)
        total = frame[["sig1", "sig2", "sig3"]].sum(axis=1)
        total = total.where(valid, 0.0)
        return {
            "sig1": float(frame["sig1"].iloc[-1]) if pd.notna(frame["sig1"].iloc[-1]) else 0.0,
            "sig2": float(frame["sig2"].iloc[-1]) if pd.notna(frame["sig2"].iloc[-1]) else 0.0,
            "sig3": float(frame["sig3"].iloc[-1]) if pd.notna(frame["sig3"].iloc[-1]) else 0.0,
            "sig1_raw": frame["sig1"].iloc[-1],
            "sig2_raw": frame["sig2"].iloc[-1],
            "sig3_raw": frame["sig3"].iloc[-1],
            "valid": bool(valid.iloc[-1]),
            "S": float(total.iloc[-1]),
            "n_sig3_periods": int(frame["sig3"].notna().sum()),
        }

    def _equity_weight(self, q_erp: float, sig: Dict[str, Any], cfg: Dict[str, Any]) -> float:
        """权益目标仓位 = cap × clip(g(q_erp + sig_weight × S), 0, 1)."""
        q_adj = q_erp + cfg["sig_weight"] * float(sig["S"])
        g = _sigmoid_norm(np.array([q_adj], dtype=float), cfg["sigmoid_a"])[0]
        return float(cfg["cap"] * np.clip(g, 0.0, 1.0))

    # ------------------------------------------------------------------
    # 选基：八因子 + 赛道调整
    # ------------------------------------------------------------------

    _FACTOR_COL = {
        "excess": "excess_ann", "ir": "ir", "stab": "stab_raw",
        "alpha": "alpha_ann", "win": "win_m", "t": "t_m",
        "te": "te", "style": "style_raw",
    }

    def _style_factors(self, px: pd.DataFrame, styles: Sequence[str]) -> Tuple[pd.Series, pd.Series]:
        """按六风格指数合成 SMB / HML（与原型 ``factor_returns`` 同口径）."""
        ret = px[list(styles)].pct_change()
        cols = dict(zip(_STYLE_KEYS, styles))
        missing = [k for k in _STYLE_KEYS if k not in cols]
        if missing:
            raise ValueError(f"[{_TAG}] 风格指数缺少 {missing}，无法合成 SMB/HML")
        lg, lv = ret[cols["LG"]], ret[cols["LV"]]
        mg, mv = ret[cols["MG"]], ret[cols["MV"]]
        sg, sv = ret[cols["SG"]], ret[cols["SV"]]
        smb = (sg + sv) / 2.0 - (lg + lv) / 2.0
        hml = (lv + mv + sv) / 3.0 - (lg + mg + sg) / 3.0
        return smb, hml

    def _fund_metrics(
        self, r: pd.Series, b: pd.Series, cov: float,
        smb: pd.Series, hml: pd.Series, cfg: Dict[str, Any],
        month_keys: pd.Series,
    ) -> Optional[Dict[str, float]]:
        """单只基金在窗口内的八因子原始指标（与原型 ``compute_metrics`` 同口径）.

        ``month_keys`` 是窗口交易日 → (年, 月) 的分组键，由 ``_score_funds``
        按窗口算一次后全池复用：它只取决于日历，逐基金重算是同一份日历的
        重复构造。
        """
        ann = float(cfg["ann_days"])
        data = pd.DataFrame({"r": r, "b": b}).dropna()
        n = len(data)
        if n < cfg["min_days"]:
            return None
        rr, bb = data["r"], data["b"]
        excess = rr - bb
        te = float(excess.std(ddof=1) * np.sqrt(ann))
        ex_ann = _ann_ret(rr, cfg["ann_days"]) - _ann_ret(bb, cfg["ann_days"])
        ir = ex_ann / te if te > 1e-8 else float("nan")

        X = np.column_stack([np.ones(n), bb.values])
        try:
            coef, *_ = np.linalg.lstsq(X, rr.values, rcond=None)
            alpha_ann = float(coef[0]) * ann
        except np.linalg.LinAlgError:
            alpha_ann = float("nan")

        keys = month_keys.reindex(rr.index)
        mret = (1.0 + rr).groupby(keys).prod() - 1.0
        mben = (1.0 + bb).groupby(keys).prod() - 1.0
        me = (mret - mben).dropna()
        n_m = len(me)
        win_m = float((me > 0).mean()) if n_m else float("nan")
        sd_m = float(me.std(ddof=1)) if n_m > 2 else float("nan")
        t_m = float(me.mean() / sd_m * np.sqrt(n_m)) if n_m > 2 and sd_m > 0 else float("nan")
        ir_m = float(me.mean() / sd_m * np.sqrt(12)) if n_m > 2 and sd_m > 0 else float("nan")
        ar1_m = _autocorr1(me) if n_m > 5 else float("nan")

        rel = (1.0 + rr).cumprod() / (1.0 + bb).cumprod()
        excess_mdd = _max_dd(rel)

        style_mag = float("nan")
        frame = pd.DataFrame({"e": excess, "SMB": smb.reindex(excess.index),
                              "HML": hml.reindex(excess.index)}).dropna()
        if len(frame) > 60:
            Xs = np.column_stack([np.ones(len(frame)), frame["SMB"].values, frame["HML"].values])
            try:
                coef_s, *_ = np.linalg.lstsq(Xs, frame["e"].values, rcond=None)
                style_mag = float(np.sqrt(float(coef_s[1]) ** 2 + float(coef_s[2]) ** 2))
            except np.linalg.LinAlgError:
                style_mag = float("nan")

        stab_raw = (0.45 * win_m + 0.30 * (-excess_mdd) + 0.25 * ar1_m
                    if np.isfinite(win_m) and np.isfinite(excess_mdd) and np.isfinite(ar1_m)
                    else float("nan"))
        return {
            "n_days": float(n), "obs_ratio": float(cov), "excess_ann": ex_ann,
            "te": te, "ir": ir, "alpha_ann": alpha_ann, "win_m": win_m,
            "t_m": t_m, "ir_m": ir_m, "ar1_m": ar1_m, "excess_mdd": excess_mdd,
            "stab_raw": stab_raw, "style_mag": style_mag, "style_raw": -style_mag,
        }

    def _track_baselines(
        self, detail: pd.DataFrame, tracks: Sequence[str], cfg: Dict[str, Any]
    ) -> Dict[str, Dict[str, float]]:
        """逐赛道算八因子的中位数与稳健标准差；样本不足的赛道并入全池基线.

        原型默认 ``base_mode="hist"`` 用全历史指标作基线（含前视），本实现用同一
        ``train_months`` 窗口内的同类基金现算，无前视。
        """
        cols = [self._FACTOR_COL[k] for k in _FACTOR_NAMES]
        pool: Dict[str, float] = {}
        for col in cols:
            series = pd.to_numeric(detail[col], errors="coerce")
            pool[f"mu_{col}"] = float(series.median()) if series.notna().any() else float("nan")
            pool[f"sd_{col}"] = _robust_std(series)

        base: Dict[str, Dict[str, float]] = {}
        for track, group in detail.groupby("track"):
            record = dict(pool)
            for col in cols:
                series = pd.to_numeric(group[col], errors="coerce")
                record[f"mu_{col}"] = float(series.median()) if series.notna().any() else pool[f"mu_{col}"]
                sd = _robust_std(series)
                record[f"sd_{col}"] = sd if np.isfinite(sd) else pool[f"sd_{col}"]
            record["usable"] = len(group) >= cfg["track_min_funds"]
            record["n_funds"] = float(len(group))
            base[track] = record

        for track in tracks:
            if track not in base or not base[track]["usable"]:
                fallback = dict(pool)
                fallback["usable"] = False
                fallback["n_funds"] = float(len(detail[detail["track"] == track])) if track in set(detail["track"]) else 0.0
                fallback["fallback"] = True
                base[track] = fallback
        return base

    def _score_funds(
        self,
        raw_prices: pd.DataFrame,
        px: pd.DataFrame,
        groups: Dict[str, List[str]],
        cfg: Dict[str, Any],
        params: Dict[str, Any],
    ) -> Tuple[pd.DataFrame, Dict[str, str]]:
        """逐基金算八因子并按赛道相对打分，返回（含 score/track 的明细, 赛道映射）.

        赛道 = 与 ``track_codes`` 中跟踪误差最小的那只基准；未配赛道基准时回退到
        六个风格指数（与原型 STYLE_CODES 同一份）。赛道只决定「单赛道上限」的名额
        归属，不改变因子口径。
        """
        funds = groups["FUND"]
        styles = groups["STYLE"]
        tracks_pool = list(groups.get("TRACK") or styles)
        bench_rets = px[tracks_pool].pct_change()
        smb, hml = self._style_factors(px, styles)

        end = pd.Timestamp(px.index[-1])
        start = end - pd.DateOffset(months=cfg["train_months"])
        window = px.index[(px.index > start) & (px.index <= end)]
        if len(window) < cfg["min_days"]:
            raise ValueError(
                f"[{_TAG}] 指标窗口 {start.date()} ~ {end.date()} 只有 {len(window)} 个交易日，"
                f"少于最少有效天数 {cfg['min_days']}；请缩短 train_months 或延后回测起点"
            )

        rows: Dict[str, Dict[str, float]] = {}
        skipped: Dict[str, str] = {}
        # 月份分组键只取决于窗口日历，与基金无关：循环外算一次，全池复用
        month_keys = pd.Series([(d.year, d.month) for d in window], index=window)
        for code in funds:
            if code not in raw_prices.columns:
                skipped[code] = "价格矩阵缺列"
                continue
            coverage = pd.to_numeric(raw_prices[code], errors="coerce").reindex(window).notna()
            cov = float(coverage.mean()) if len(coverage) else 0.0
            if cov < cfg["min_cov"]:
                skipped[code] = f"覆盖率 {cov:.2%} < {cfg['min_cov']:.0%}"
                continue
            r = px[code].pct_change().reindex(window)
            if int(r.notna().sum()) < cfg["min_days"]:
                skipped[code] = f"有效天数 {int(r.notna().sum())} < {cfg['min_days']}"
                continue

            best_track, best_te = None, np.inf
            for track in tracks_pool:
                diff = (r - bench_rets[track].reindex(r.index)).dropna()
                if len(diff) < cfg["min_days"]:
                    continue
                te_raw = float(diff.std(ddof=1))
                if np.isfinite(te_raw) and te_raw < best_te:
                    best_track, best_te = track, te_raw
            if best_track is None:
                skipped[code] = "与任何赛道基准的重叠交易日都不足"
                continue

            metrics = self._fund_metrics(
                r, bench_rets[best_track].reindex(r.index), cov, smb, hml, cfg,
                month_keys)
            if metrics is None:
                skipped[code] = "窗口内有效样本不足"
                continue
            metrics["track"] = best_track
            rows[code] = metrics

        if len(rows) < cfg["select_count"]:
            sample = list(skipped.items())[:5]
            raise ValueError(
                f"[{_TAG}] 通过覆盖率与有效天数筛选的基金只有 {len(rows)} 只，"
                f"少于选样数量 {cfg['select_count']}。剔除样例：{sample}。"
                "请放宽 min_cov / min_days，或补充基金净值"
            )

        detail = pd.DataFrame(rows).T
        detail.index.name = "code"
        for col in detail.columns:
            if col != "track":
                detail[col] = pd.to_numeric(detail[col], errors="coerce")

        tracks = tracks_pool
        base = self._track_baselines(detail, tracks, cfg)

        z = pd.DataFrame(np.nan, index=detail.index, columns=list(_FACTOR_NAMES))
        for track, group in detail.groupby("track"):
            record = base[track]
            for name in _FACTOR_NAMES:
                col = self._FACTOR_COL[name]
                if name == "te":
                    center = record[f"mu_{col}"] if np.isfinite(record[f"mu_{col}"]) else float(
                        pd.to_numeric(group[col], errors="coerce").mean())
                    deviation = -(pd.to_numeric(group[col], errors="coerce") - center).abs()
                else:
                    deviation = pd.to_numeric(group[col], errors="coerce")
                abs_z = _z_abs(deviation, record[f"mu_{col}"], record[f"sd_{col}"])
                intra = _z_intra(deviation, cfg["intra_min_n"])
                merged = abs_z.copy()
                both = abs_z.notna() & intra.notna()
                if both.any():
                    merged.loc[both] = cfg["w_abs"] * abs_z.loc[both] + cfg["w_intra"] * intra.loc[both]
                z.loc[group.index, name] = merged

        score = pd.Series(0.0, index=detail.index)
        for name, weight in cfg["factor_weights"].items():
            score = score + z[name].fillna(0.0) * float(weight)
        detail["score"] = score
        detail["rank"] = detail["score"].rank(ascending=False, method="min")
        for name in _FACTOR_NAMES:
            detail[f"z_{name}"] = z[name]
        return detail, {code: str(detail.at[code, "track"]) for code in detail.index}

    def _pick(self, detail: pd.DataFrame, cfg: Dict[str, Any]) -> List[str]:
        """按分数从高到低入选，单赛道不超过上限（与原型 ``pick_portfolio`` 同口径）."""
        ordered = detail.sort_values("score", ascending=False)
        picked: List[str] = []
        counts: Dict[str, int] = {}
        for code, row in ordered.iterrows():
            track = str(row["track"])
            if counts.get(track, 0) >= cfg["max_per_track"]:
                continue
            picked.append(str(code))
            counts[track] = counts.get(track, 0) + 1
            if len(picked) >= cfg["select_count"]:
                break
        return picked

    def _combine(
        self, picked: Sequence[str], w_equity: float,
        groups: Dict[str, List[str]], pool: Sequence[str],
    ) -> pd.Series:
        """入选基金在权益端等权，剩余权重全部进债券腿."""
        if w_equity > _TOL and not picked:
            raise ValueError(
                f"[{_TAG}] 权益目标仓位 {w_equity:.2%} 但没有任何基金入选，"
                "无法构建持仓；请检查基金池与筛选阈值"
            )
        weights = pd.Series(0.0, index=list(pool), dtype=float)
        if picked:
            each = float(w_equity) / len(picked)
            for code in picked:
                weights.at[code] = each
        weights.at[groups["BOND"][0]] = 1.0 - float(w_equity)
        return weights

    def _audit(
        self, q_erp: float, sig: Dict[str, Any], w_equity: float,
        picked: Sequence[str], tracks: Dict[str, str], cfg: Dict[str, Any],
    ) -> None:
        """记录本期决策与告警，供监控页与验收对账（不参与权重计算）."""
        state = self._ensure_state()
        state["rebalance_count"] = int(state.get("rebalance_count", 0)) + 1
        track_count: Dict[str, int] = {}
        for code in picked:
            track = tracks.get(code, "?")
            track_count[track] = track_count.get(track, 0) + 1
        state["last_metrics"] = {
            "erp_quantile": float(q_erp),
            "sig1": float(sig["sig1"]),
            "sig2": float(sig["sig2"]),
            "sig3": float(sig["sig3"]),
            "signal_sum": float(sig["S"]),
            "signal_valid": bool(sig["valid"]),
            "equity_weight": float(w_equity),
            "bond_weight": float(1.0 - w_equity),
            "selected_count": len(picked),
            "track_count": len(track_count),
            "max_track_hit": max(track_count.values()) if track_count else 0,
            "cap": float(cfg["cap"]),
            "sig_weight": float(cfg["sig_weight"]),
        }
        if int(sig["n_sig3_periods"]) == 0:
            _log.warning(
                "[%s] 本期 sig3 全为 0（个股截面不足以分组），合成信号只含 sig1+sig2",
                _TAG,
            )

    def _final_check(self, weights: pd.Series, cfg: Dict[str, Any]) -> None:
        """归一化末检：合计为 1、无负权重、单资产不超 1；越界报错不静默裁剪."""
        total = float(weights.sum())
        if not np.isfinite(total) or abs(total - 1.0) > 1e-6:
            raise ValueError(f"[{_TAG}] 权重合计 {total!r} 不为 1，计算异常")
        negative = weights[weights < -1e-12]
        if len(negative):
            raise ValueError(f"[{_TAG}] 出现负权重：{negative.to_dict()}")
        if float(weights.max()) > 1.0 + 1e-9:
            raise ValueError(f"[{_TAG}] 单资产权重超过 1：{float(weights.max())!r}")

    # ------------------------------------------------------------------
    # 监控指标与跳期状态
    # ------------------------------------------------------------------

    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params: Any,
    ) -> Dict[str, Any]:
        """暴露本期 ERP 分位、三信号、权益/债券仓位与赛道分布（前端监控页指标区）."""
        state = self._ensure_state()
        metrics = dict(state.get("last_metrics") or {})
        metrics["rebalance_count"] = int(state.get("rebalance_count", 0))
        return metrics

    def _ensure_state(self) -> Dict[str, Any]:
        """跳期状态容器（面板物化缓存、审计与计数）；首次访问时惰性创建."""
        state = getattr(self, "_state", None)
        if not isinstance(state, dict):
            state = {}
            self._state = state
        return state
