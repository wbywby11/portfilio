"""红利 GARP 增强（dividend_garp）：打包独立形态的红利估值防守 + 成长趋势 + 波动率控制策略.

方法（月末信号日收盘计算，次一交易日收盘成交）：目标仓位由三步乘数逐层施加得到——

1. **波动率控制**：把红利端（``dividend_codes`` 组内等权）与成长端
   （``growth_codes`` 组内等权）按 ``w_div`` / ``w_grw`` 合成权益日收益，
   取最近 ``vol_n`` 个交易日（含当日）样本标准差 ``×√ann_days`` 得实现波动率 σ，
   参与度 ``part = clip(vol_target/σ, part_min, part_max)``；
2. **红利估值防守**：估值序列（``pe_code``，中证红利 PE-TTM）在
   「信号日减 ``pe_years`` 年」至信号日窗口内的分位 = 窗口内取值 ≤ 当日取值的比例；
   ``> pe_hi`` 进入防守态（红利端 ``× div_mult``）、``< pe_lo`` 退出，
   中间保持上期状态（滞回，跨期状态存 ``self._state``）；
3. **成长趋势**：成长端相对 ``ma_n`` 日均线的偏离 ``dev``：``dev < 0`` → ``× grw_def``；
   ``dev > add_lo`` 且参与度已满 → 线性加仓 ``1 + add_max×min(1, (dev-add_lo)/(add_hi-add_lo))``。

目标权重 = 权益中枢 ``center`` × 组内配比 × 参与度 × 端点乘数；合计超 ``eq_cap``
时只压缩成长端加仓部分，低于 ``eq_floor``（仅权益类专户声明）时两端等比例放大，
剩余进债券端。两类专户用 ``account_mode`` 切换（``equity``：中枢 1.00 / 上限 1.00 /
下限 0.83；``mixed``：中枢 0.67 / 上限 0.72 / 无下限），两套数值全部进参数。

成本：``cost_eq``（权益端换手）/ ``cost_bond``（债券端换手）/ ``tool_fee``（全收益
指数年费）三项显式声明、默认取原型值。换手成本按「本期目标权重与上期目标权重之差」
在 :meth:`on_daily_settle` 从现金扣除（期初建仓不计成本）；年费按 ``tool_fee_codes``
的当日市值逐日计提（ETF 复权净值已含管理费，不应放进该清单）。回测请求的
``commission_rate`` 必须保持 0，否则与策略声明重复计量；监控通道不调用
:meth:`on_daily_settle`，监控净值为 gross 口径。

面板：``get_extra_panels`` 声明 ``macro_series``，估值序列按 ``_as_of`` 回看，
**不声明** ``panel_event_dates``（日频估值期日会把月度调仓变成日频调仓）。

红线：``allocate`` 为纯函数，只消费注入的 prices 与 params（含 ``_as_of``、
``_panel_macro_series``），不读文件、不查库；资产分组、窗口、阈值、中枢、上下限
全部来自参数，不写死资产代码与日期；窗口不足、估值缺失、分组未覆盖全池、参数
不自洽时一律报错，不兜底等权、不跳过资产、不放宽断言。
"""

from __future__ import annotations

import calendar
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.allocation.models.base import BaseStrategyModel

_log = logging.getLogger(__name__)

# 面板名（与 data_feed.PANEL_LOADERS 注册键、get_extra_panels 声明一致）
_PANEL_NAME = "macro_series"

# 分组参数名 → 包内组键
GROUP_PARAM_TO_KEY: Dict[str, str] = {
    "dividend_codes": "DIV",
    "growth_codes": "GRW",
    "bond_codes": "BOND",
}
GROUP_KEYS: Tuple[str, ...] = ("DIV", "GRW", "BOND")
# 包内组键 → 参数名（声明分资产费率、审计回显时反查参数）
_GROUP_CONFIG_KEY: Dict[str, str] = {v: k for k, v in GROUP_PARAM_TO_KEY.items()}

# 账户模式 → (中枢参数名, 权益上限参数名, 权益下限参数名)
_ACCOUNT_MODES: Dict[str, Tuple[str, str, str]] = {
    "equity": ("eq_center", "eq_cap", "eq_floor"),
    "mixed": ("mix_center", "mix_cap", "eq_floor"),
}

TOL = 1e-9


# ---------------------------------------------------------------------------
# 纯函数：日期与参数解析
# ---------------------------------------------------------------------------


def minus_years(ts: pd.Timestamp, years: int) -> pd.Timestamp:
    """日期减 years 年（同月同日；该月无该日时取月末），用于估值窗口左端点."""
    y, m = ts.year - years, ts.month
    last_day = calendar.monthrange(y, m)[1]
    return pd.Timestamp(year=y, month=m, day=min(ts.day, last_day))


def _as_float(value: Any, default: float, name: str) -> float:
    """参数转浮点；None 取默认值，非数值报错（不做静默回退）."""
    if value is None or value == "":
        return float(default)
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"[dividend_garp] 参数 {name} 必须为数值，收到 {value!r}") from exc
    if not np.isfinite(out):
        raise ValueError(f"[dividend_garp] 参数 {name} 非有限值：{value!r}")
    return out


def _as_int(value: Any, default: int, name: str) -> int:
    """参数转正整数；None 取默认值，非正数报错."""
    if value is None or value == "":
        return int(default)
    try:
        out = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"[dividend_garp] 参数 {name} 必须为整数，收到 {value!r}") from exc
    if out <= 0:
        raise ValueError(f"[dividend_garp] 参数 {name} 必须为正整数，收到 {out}")
    return out


def composite_price(frame: pd.DataFrame) -> pd.Series:
    """组内等权合成价格：单列时原样返回，多列时按首期归一等权合成.

    单列退化为原始价格序列，保证与只持一只标的的原型口径逐条一致；
    多列时用「首期归一等权净值 × 首期价格均值」保持价格量纲，供均线偏离计算。
    """
    if frame.shape[1] == 0:
        raise ValueError("[dividend_garp] 合成价格的分组为空")
    if frame.shape[1] == 1:
        return frame.iloc[:, 0].astype(float)
    base = frame.iloc[0].astype(float)
    if (base <= 0).any() or base.isna().any():
        raise ValueError("[dividend_garp] 合成价格的首期价格无效（含 0/负值/NaN）")
    return (frame.astype(float) / base).mean(axis=1) * float(base.mean())


def _model_level_params(execution_delay: int) -> List[Any]:
    """通用模型级参数组，并把 ``execution_delay`` 的默认值对齐本策略调度声明.

    通用组的默认值为 0；本策略缺省 T+1 执行，若沿用 0 则前端按默认值提交后会把
    :meth:`get_execution_schedule` 声明的 1 覆盖成 0（Pipeline 以模型参数为准）。
    """
    from dataclasses import replace

    from app.allocation.models.param_schema import model_level_param_group

    out: List[Any] = []
    for param in model_level_param_group():
        if param.name == "execution_delay":
            param = replace(
                param,
                default=int(execution_delay),
                min_value=1,
                description=(
                    "信号日到成交日的交易日延迟；本策略原型为月末信号次一交易日成交（T+1），"
                    "不得低于 1"
                ),
            )
        out.append(param)
    return out


class DividendGarpStrategy(BaseStrategyModel):
    """红利估值防守 + 成长趋势 + 波动率控制（打包独立形态）."""

    # ------------------------------------------------------------------
    # 参数 Schema
    # ------------------------------------------------------------------

    @classmethod
    def get_param_schema(cls):
        from app.allocation.models.param_schema import ParamSchema, StrategyParamSchema

        cond_mixed = {"field": "account_mode", "value": "mixed"}
        cond_equity = {"field": "account_mode", "value": "equity"}

        return StrategyParamSchema(
            strategy_type="dividend_garp",
            display_name="红利 GARP 增强",
            description=(
                "月末信号、次一交易日成交：权益端按红利/成长配比合成实现波动率，"
                "参与度 = clip(目标波动/实现波动, 下界, 上界)；估值序列近 N 年分位做"
                "红利估值防守（高位进入、低位退出、滞回保持）；成长端按相对长期均线的"
                "偏离做防守与线性加仓；再按账户中枢、权益上限/下限得到目标权重，"
                "剩余进债券端。选样/赋权/约束/成本全部在策略包内，前端配置资产分组、"
                "波动率窗口、估值阈值与账户中枢"
            ),
            composition={
                "selector": None,
                "allocator": "dividend_garp",
                "controller": None,
                "schedule": {"rebalance_freq": "month_end", "execution_delay": 1},
            },
            # 权重合计恒为 1（债券端回填），Pipeline 不再做杠杆缩放
            internal_leverage=True,
            params=[
                # ━━━ 资产分组（core）━━━
                ParamSchema(
                    name="dividend_codes", label="红利组资产", type="text", default="",
                    description=(
                        "红利端资产代码，逗号分隔，组内等权。原型为红利低波 ETF 与央企红利 "
                        "50 全收益两只各半"
                    ),
                ),
                ParamSchema(
                    name="growth_codes", label="成长组资产", type="text", default="",
                    description=(
                        "成长端资产代码，逗号分隔，组内等权；组内多只时按等权合成价格计算"
                        "长期均线偏离，单只时与原型口径一致"
                    ),
                ),
                ParamSchema(
                    name="bond_codes", label="债券组资产", type="text", default="",
                    description="债券端资产代码，逗号分隔，组内等权；承接权益端未占用的剩余权重",
                ),
                ParamSchema(
                    name="account_mode", label="账户模式", type="select", default="equity",
                    options=[
                        ("equity", "权益类专户（中枢 1.00 / 上限 1.00 / 下限 0.83）"),
                        ("mixed", "混合类专户（中枢 0.67 / 上限 0.72 / 无下限）"),
                    ],
                    description="选择使用哪一套中枢与上下限参数；两套数值在下方高级参数中分别声明",
                ),
                # ━━━ 权益内部配比与波动率控制（core）━━━
                ParamSchema(
                    name="w_div", label="红利端配比", type="number", default=0.80,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="权益端内部红利组配比，与成长端配比一同归一化后合成权益收益",
                ),
                ParamSchema(
                    name="w_grw", label="成长端配比", type="number", default=0.20,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="权益端内部成长组配比；两者之和必须大于 0",
                ),
                ParamSchema(
                    name="vol_n", label="波动率窗口", type="number", default=60,
                    min_value=2, max_value=750, step=1,
                    description="实现波动率的交易日窗口（含信号日当日）",
                ),
                ParamSchema(
                    name="vol_target", label="目标波动率", type="number", default=0.14,
                    min_value=0.005, max_value=1.0, step=0.005,
                    description="权益合成收益的年化目标波动率，如 0.14 = 14%",
                ),
                ParamSchema(
                    name="part_min", label="参与度下界", type="number", default=0.60,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="目标波动/实现波动 的裁剪下界（最低参与度）",
                ),
                ParamSchema(
                    name="part_max", label="参与度上界", type="number", default=1.00,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="目标波动/实现波动 的裁剪上界（最高参与度）；等于上界视为满参与",
                ),
                ParamSchema(
                    name="ann_days", label="波动率年化因子", type="number", default=252,
                    min_value=52, max_value=365, step=1,
                    description=(
                        "信号波动率与年费计提的年化交易日数（原型 252）。"
                        "系统绩效指标年化固定用 260，两者不混用"
                    ),
                ),
                # ━━━ 红利估值防守（core）━━━
                ParamSchema(
                    name="pe_code", label="估值序列代码", type="text", default="H00922_PE",
                    description=(
                        "macro_series 集合中的估值序列代码（中证红利 PE-TTM）；"
                        "留空或序列不存在时报错，不兜底"
                    ),
                ),
                ParamSchema(
                    name="pe_years", label="估值回看年数", type="number", default=3,
                    min_value=1, max_value=20, step=1,
                    description="估值分位窗口左端点 = 信号日减该年数（同月同日，无该日取月末）",
                ),
                ParamSchema(
                    name="pe_hi", label="防守进入分位", type="number", default=0.80,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="估值分位高于该值时进入防守态（红利端乘以防守乘数）",
                ),
                ParamSchema(
                    name="pe_lo", label="防守退出分位", type="number", default=0.70,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="估值分位低于该值时退防守态；介于退出线与进入线之间保持上期状态",
                ),
                ParamSchema(
                    name="div_mult", label="防守乘数", type="number", default=0.75,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="防守态下红利端配比的乘数（原型 0.75 = 只剩四分之三）",
                ),
                # ━━━ 成长趋势（core）━━━
                ParamSchema(
                    name="ma_n", label="趋势均线窗口", type="number", default=200,
                    min_value=2, max_value=750, step=1,
                    description="成长端合成价格的长期均线窗口（交易日，含信号日当日）",
                ),
                # ━━━ 数据加载（advanced）━━━
                ParamSchema(
                    name="min_history_days", label="最小历史天数（交易日）",
                    type="number", default=200, min_value=2, max_value=750,
                    step=1, group="advanced",
                    description=(
                        "回测起点之前必须预加载的交易日数，系统按它反推预加载自然日数。"
                        "须不小于 max(趋势均线窗口 ma_n, 波动率窗口 vol_n)；"
                        "调大 ma_n 或 vol_n 后须同步调大本项，否则首个调仓日会因历史不足被拒"
                    ),
                ),
                ParamSchema(
                    name="grw_def", label="成长防守乘数", type="number", default=0.75,
                    min_value=0.0, max_value=1.0, step=0.01,
                    description="成长端价格低于均线时的配比乘数",
                ),
                ParamSchema(
                    name="add_lo", label="加仓起点偏离", type="number", default=0.03,
                    min_value=0.0, max_value=1.0, step=0.005,
                    description="成长端偏离均线高于该值且参与度已满时开始线性加仓",
                ),
                ParamSchema(
                    name="add_hi", label="加仓满额偏离", type="number", default=0.15,
                    min_value=0.0, max_value=2.0, step=0.005,
                    description="偏离达到该值时加仓量达到 add_max（须大于加仓起点偏离）",
                ),
                # ━━━ 成本（core）━━━
                ParamSchema(
                    name="cost_eq", label="权益端换手成本", type="number", default=0.0010,
                    min_value=0.0, max_value=0.05, step=0.0001,
                    description="权益端单边换手费率（原型 0.0010）；由日结算钩子从现金扣除",
                ),
                ParamSchema(
                    name="cost_bond", label="债券端换手成本", type="number", default=0.0001,
                    min_value=0.0, max_value=0.05, step=0.0001,
                    description="债券端单边换手费率（原型 0.0001）；由日结算钩子从现金扣除",
                ),
                ParamSchema(
                    name="tool_fee", label="指数年费", type="number", default=0.006,
                    min_value=0.0, max_value=0.05, step=0.0005,
                    description=(
                        "全收益指数年化管理费（原型 0.006），按年费清单内资产的市值逐日计提；"
                        "ETF 复权净值已含管理费，不应放进年费清单"
                    ),
                ),
                ParamSchema(
                    name="tool_fee_codes", label="年费计提资产", type="text", default="",
                    description=(
                        "需要按 tool_fee 计提年费的资产代码，逗号分隔（原型为央企红利 50 "
                        "与东证优势成长两只全收益指数）；留空则不收年费"
                    ),
                ),
                ParamSchema(
                    name="enable_daily_vol_control", label="启用日度波动率风控",
                    type="boolean", default=False, group="advanced",
                    description=(
                        "本策略的波动率控制已在包内完成（vol_target/part_min/part_max 参与度），"
                        "日度重置会与包内缩放重复，默认关闭；监控侧读同一开关。"
                        "target_vol 是参与度基准而非风控目标，不能当重置阈值用"
                    ),
                ),
                ParamSchema(
                    name="daily_vol_trigger", label="日度波动触发线", type="number",
                    default=0.06, min_value=0.0, max_value=1.0, step=0.005,
                    group="advanced",
                    description="启用日度波动率风控时的触发阈值（年化），仅在该开关打开时生效",
                ),
                # ━━━ 账户中枢与上下限（advanced）━━━
                ParamSchema(
                    name="eq_center", label="权益类中枢", type="number", default=1.00,
                    min_value=0.0, max_value=1.0, step=0.01, group="advanced",
                    condition=cond_equity,
                    description="权益类专户的权益中枢（满仓口径）",
                ),
                ParamSchema(
                    name="eq_cap", label="权益类上限", type="number", default=1.00,
                    min_value=0.0, max_value=1.0, step=0.01, group="advanced",
                    condition=cond_equity,
                    description="权益类专户的权益合计上限，超出时只压缩成长端加仓部分",
                ),
                ParamSchema(
                    name="eq_floor", label="权益类下限", type="number", default=0.83,
                    min_value=0.0, max_value=1.0, step=0.01, group="advanced",
                    description=(
                        "权益合计低于该值时两端等比例放大；混合类专户不使用本参数"
                        "（设为 0 即不启用下限）"
                    ),
                ),
                ParamSchema(
                    name="mix_center", label="混合类中枢", type="number", default=0.67,
                    min_value=0.0, max_value=1.0, step=0.01, group="advanced",
                    condition=cond_mixed,
                    description="混合类专户的权益中枢（三分之二权益 + 三分之一债券口径）",
                ),
                ParamSchema(
                    name="mix_cap", label="混合类上限", type="number", default=0.72,
                    min_value=0.0, max_value=1.0, step=0.01, group="advanced",
                    condition=cond_mixed,
                    description="混合类专户的权益合计上限",
                ),
                ParamSchema(
                    name="add_max", label="加仓最大倍数", type="number", default=1.00,
                    min_value=0.0, max_value=5.0, step=0.05, group="advanced",
                    description="成长端线性加仓的额外倍数上限（1.00 表示最多加到配比的 2 倍）",
                ),
                ParamSchema(
                    name="strict_validate", label="严格校验", type="boolean", default=True,
                    group="advanced",
                    description=(
                        "开启时：资产池内有资产未归组、分组含池外代码、权重越界即报错；"
                        "关闭只降级为告警（不建议）"
                    ),
                ),
                *_model_level_params(1),
            ],
        )

    # ------------------------------------------------------------------
    # 调度、面板与数据契约
    # ------------------------------------------------------------------

    @classmethod
    def get_extra_panels(cls) -> list:
        """声明需要 macro_series 估值序列（数据加载层据此加载并经引擎注入）."""
        return [_PANEL_NAME]

    def get_data_feed_options(self) -> Dict[str, Any]:
        """声明数据源口径：加载宏观序列面板，**不**用面板期日驱动调仓.

        ``panel_event_dates`` 保持缺省（False）：估值序列是日频的，一旦把它当
        调仓事件日，月末策略会退化为日频调仓。
        """
        return {"extra_panels": [_PANEL_NAME]}

    def get_execution_schedule(self) -> Optional[dict]:
        """月末信号、次一交易日成交；不写 selection_start_date / skip_dates 等日期常量."""
        return {"rebalance_freq": "month_end", "execution_delay": 1}

    def get_trading_costs(self, params: Dict[str, Any]) -> Dict[str, float]:
        """声明分资产交易费率：权益两档代码走 ``cost_eq``，债券代码走 ``cost_bond``.

        引擎在成交时按 code 扣费（`Σ|目标−调仓前实际权重| × 费率` 等价于
        按成交额×费率），与原型 ``COST[a]`` 逐资产口径一致；监控侧费率入口
        同名同义，但系统通用监控固定 gross 口径，不在本策略中改写。
        """
        cfg = self._parse_config(params)
        from app.backtesting.data_contract import parse_asset_codes

        costs: Dict[str, float] = {}
        for key in GROUP_KEYS:
            rate = cfg["cost_bond"] if key == "BOND" else cfg["cost_eq"]
            if rate <= 0:
                continue
            for code in parse_asset_codes(params.get(_GROUP_CONFIG_KEY[key])):
                costs[code] = rate
        return costs

    def has_native_vol_control(self) -> bool:
        """波动率控制写在包内（作为目标仓位乘数），放行 Pipeline 代理."""
        return True

    @classmethod
    def get_data_contract(cls):
        """声明数据契约：分组覆盖全池 + 资产大类匹配 + 参数自洽 + 价格跳变上限.

        阈值来自 A5 实测：回测区间内四只资产最大单日跳变 10.98%（成长端
        2024-09-30），故取 0.20 留余量；不声明 ``min_assets`` /
        ``require_continuous``——资产只数由分组参数定。``min_history_days``
        由参数声明（默认 200 交易日）而非契约写死：窗口 ma_n / vol_n 可调，
        写死会让调大窗口后预加载自然日数跟不上。
        """
        from app.backtesting.data_contract import DataContract, GroupSpec

        return DataContract(
            max_single_day_jump=0.20,
            group_params={
                "dividend_codes": GroupSpec(required=True, cover_pool=True),
                "growth_codes": GroupSpec(required=True, cover_pool=True),
                "bond_codes": GroupSpec(required=True, cover_pool=True),
            },
            expected_asset_class={
                "dividend_codes": "权益",
                "growth_codes": "权益",
                "bond_codes": "固收",
            },
            custom_checks=("param_consistency",),
        )

    def _check_param_consistency(self, prices: pd.DataFrame, params: Dict[str, Any]) -> Optional[str]:
        """参数自洽检查（契约门禁）：不自洽时返回失败原因，由门禁统一拒绝运行."""
        try:
            cfg = self._parse_config(params)
        except ValueError as exc:
            return str(exc)
        if cfg["w_div"] + cfg["w_grw"] <= TOL:
            return "红利端配比与成长端配比之和必须大于 0"
        if cfg["eq_floor"] > cfg["eq_cap"] + TOL:
            return (
                f"权益下限 {cfg['eq_floor']} 高于权益上限 {cfg['eq_cap']}，"
                "约束不可行（请降低下限或提高上限）"
            )
        if cfg["pe_lo"] >= cfg["pe_hi"]:
            return f"防守退出分位 {cfg['pe_lo']} 必须小于防守进入分位 {cfg['pe_hi']}"
        if cfg["add_hi"] <= cfg["add_lo"]:
            return f"加仓满额偏离 {cfg['add_hi']} 必须大于加仓起点偏离 {cfg['add_lo']}"
        if cfg["part_min"] > cfg["part_max"] + TOL:
            return f"参与度下界 {cfg['part_min']} 高于上界 {cfg['part_max']}"
        return None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """月末信号日计算目标权重（纯函数；跨期状态只有估值防守滞回）."""
        if prices is None or not isinstance(prices, pd.DataFrame) or prices.empty:
            raise ValueError("[dividend_garp] 价格矩阵为空，无法计算")
        pool = list(prices.columns)
        cfg = self._parse_config(params)
        groups = self._resolve_groups(params, pool)
        px = self._sanitize_prices(prices, groups)

        sig = self._calc_signal(px, groups, cfg, params)
        weights, cons = self._make_weights(sig, groups, cfg)
        self._audit(sig, groups, cons, cfg)
        self._register_cost_state(weights, cfg)
        self._final_check(weights, cfg)
        return weights.reindex(pool).fillna(0.0)

    # ------------------------------------------------------------------
    # 分步实现（每步可单测）
    # ------------------------------------------------------------------

    def _parse_config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """把 params 归一为本期计算所需配置（一次性解析，避免散落在各步）."""
        mode = str(params.get("account_mode") or "equity").strip().lower()
        if mode not in _ACCOUNT_MODES:
            raise ValueError(
                f"[dividend_garp] account_mode 只支持 {sorted(_ACCOUNT_MODES)}，收到 {mode!r}"
            )
        center_param, cap_param, floor_param = _ACCOUNT_MODES[mode]
        center = _as_float(params.get(center_param), 1.0 if mode == "equity" else 0.67, center_param)
        cap = _as_float(params.get(cap_param), 1.0 if mode == "equity" else 0.72, cap_param)
        # 混合类专户不启用权益下限（原型该账户没有下限约束），把显式声明值当参考不生效
        floor = 0.0 if mode == "mixed" else _as_float(params.get(floor_param), 0.83, floor_param)

        cfg: Dict[str, Any] = {
            "account_mode": mode,
            "center": center,
            "eq_cap": cap,
            "eq_floor": floor,
            "w_div": _as_float(params.get("w_div"), 0.80, "w_div"),
            "w_grw": _as_float(params.get("w_grw"), 0.20, "w_grw"),
            "vol_n": _as_int(params.get("vol_n"), 60, "vol_n"),
            "vol_target": _as_float(params.get("vol_target"), 0.14, "vol_target"),
            "part_min": _as_float(params.get("part_min"), 0.60, "part_min"),
            "part_max": _as_float(params.get("part_max"), 1.00, "part_max"),
            "ann_days": _as_int(params.get("ann_days"), 252, "ann_days"),
            "pe_code": str(params.get("pe_code") or "H00922_PE").strip().upper(),
            "pe_years": _as_int(params.get("pe_years"), 3, "pe_years"),
            "pe_hi": _as_float(params.get("pe_hi"), 0.80, "pe_hi"),
            "pe_lo": _as_float(params.get("pe_lo"), 0.70, "pe_lo"),
            "div_mult": _as_float(params.get("div_mult"), 0.75, "div_mult"),
            "ma_n": _as_int(params.get("ma_n"), 200, "ma_n"),
            "min_history_days": _as_int(
                params.get("min_history_days"), 200, "min_history_days"
            ),
            "grw_def": _as_float(params.get("grw_def"), 0.75, "grw_def"),
            "add_lo": _as_float(params.get("add_lo"), 0.03, "add_lo"),
            "add_hi": _as_float(params.get("add_hi"), 0.15, "add_hi"),
            "add_max": _as_float(params.get("add_max"), 1.00, "add_max"),
            "cost_eq": _as_float(params.get("cost_eq"), 0.0010, "cost_eq"),
            "cost_bond": _as_float(params.get("cost_bond"), 0.0001, "cost_bond"),
            "tool_fee": _as_float(params.get("tool_fee"), 0.006, "tool_fee"),
            "strict_validate": bool(params.get("strict_validate", True)),
        }
        from app.backtesting.data_contract import parse_asset_codes

        cfg["fee_codes"] = [c.upper() for c in parse_asset_codes(params.get("tool_fee_codes"))]
        if cfg["tool_fee"] > 0 and not cfg["fee_codes"]:
            _log.warning(
                "[dividend_garp] 声明了 tool_fee=%s 但 tool_fee_codes 为空，本期不计提年费",
                cfg["tool_fee"],
            )
        if cfg["w_div"] < 0 or cfg["w_grw"] < 0:
            raise ValueError("[dividend_garp] 红利端/成长端配比不得为负")
        if cfg["vol_target"] <= 0:
            raise ValueError("[dividend_garp] 目标波动率必须为正")
        # 预加载量由 min_history_days 反推（见 data_feed.resolve_lookback_days），
        # 它小于实际窗口时首个调仓日必因历史不足被拒；此处提前拒，不等到取窗口
        need_n = max(cfg["ma_n"], cfg["vol_n"])
        if cfg["min_history_days"] < need_n:
            raise ValueError(
                f"[dividend_garp] 最小历史天数 {cfg['min_history_days']}（交易日）小于窗口需求 "
                f"max(ma_n={cfg['ma_n']}, vol_n={cfg['vol_n']})={need_n}；"
                "请把「最小历史天数」调到不小于该值，否则预加载的历史不够窗口计算"
            )
        return cfg

    def _resolve_groups(
        self, params: Dict[str, Any], pool: Sequence[str]
    ) -> Dict[str, List[str]]:
        """解析三个分组参数；``strict_validate`` 下池内有资产未归组即报错."""
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
            detail = "; ".join(f"{k}={v}" for k, v in unknown.items())
            if strict:
                raise ValueError(
                    f"[dividend_garp] 分组参数含资产池之外的代码：{detail}。"
                    "分组参数必须与模型资产池同步维护"
                )
            _log.warning("[dividend_garp] 分组参数含池外代码（已忽略）：%s", detail)

        empty = [p for p, k in GROUP_PARAM_TO_KEY.items() if not groups[k]]
        if empty and strict:
            raise ValueError(
                f"[dividend_garp] 分组为空：{empty}。本策略需要红利组、成长组、债券组"
                "各自至少一只资产（资产池只含其中一组时无法计算中枢与剩余权重）"
            )
        if strict:
            covered = {c for members in groups.values() for c in members}
            missing = [c for c in pool if c not in covered]
            if missing:
                raise ValueError(
                    f"[dividend_garp] 资产池内 {len(missing)} 只资产未归入任何分组：{missing}。"
                    "请补齐 dividend_codes / growth_codes / bond_codes，或关闭 strict_validate"
                )
            seen: Dict[str, str] = {}
            duplicated: Dict[str, List[str]] = {}
            for group_key in GROUP_KEYS:
                for code in groups[group_key]:
                    if code in seen:
                        duplicated.setdefault(code, [seen[code], group_key])
                    else:
                        seen[code] = group_key
            if duplicated:
                raise ValueError(f"[dividend_garp] 同一资产被重复归组：{duplicated}")
        return groups

    def _sanitize_prices(
        self, prices: pd.DataFrame, groups: Dict[str, List[str]]
    ) -> pd.DataFrame:
        """抽取分组资产、前向填充缺日、取共同有效区间，并校验价格为正.

        系统价格矩阵是资产池的日期并集，各资产在自身序列起点之前为缺值；
        三组资产全部参与权重分配（组内均匀分），任一只缺值都会让组内权重
        算错，故取全列共同有效区间而不是逐资产剔除。各资产自身区间记入
        ``price_coverage``：共同区间比某只资产短时，说明是那只资产把区间
        截短了，窗口不足报错里直接带出。
        """
        cols: List[str] = []
        for group_key in GROUP_KEYS:
            for code in groups[group_key]:
                if code not in cols:
                    cols.append(code)
        if not cols:
            raise ValueError("[dividend_garp] 三个分组均无资产，无法计算")
        raw = prices.loc[:, cols].apply(pd.to_numeric, errors="coerce")
        own_span = {
            c: (raw[c].first_valid_index(), raw[c].last_valid_index()) for c in cols
        }
        px = raw.ffill().dropna(how="any")
        if px.empty:
            raise ValueError(
                f"[dividend_garp] 价格矩阵在分组资产 {cols} 上不存在共同有效区间，无法计算"
            )
        if (px <= 0).any().any():
            bad = [c for c in px.columns if bool((px[c] <= 0).any())]
            raise ValueError(f"[dividend_garp] 以下资产存在非正价格：{bad}，请核查行情数据")
        if len(px) < 2:
            raise ValueError(f"[dividend_garp] 有效价格行数 {len(px)} 不足 2 行，无法计算收益")
        self._ensure_state()["price_coverage"] = {
            "rows": int(len(px)),
            "first": str(px.index[0].date()),
            "last": str(px.index[-1].date()),
            "per_asset": {
                c: {
                    "first": None if span[0] is None else str(span[0].date()),
                    "last": None if span[1] is None else str(span[1].date()),
                }
                for c, span in own_span.items()
            },
        }
        return px

    def _coverage_hint(self) -> str:
        """价格覆盖诊断：共同有效区间与各资产自身区间，拼进窗口不足报错."""
        cover = self._ensure_state().get("price_coverage") or {}
        if not cover:
            return ""
        spans = "；".join(
            f"{c} {v.get('first')}~{v.get('last')}"
            for c, v in (cover.get("per_asset") or {}).items()
        )
        return (
            f"；分组资产共同有效区间 {cover.get('first')}~{cover.get('last')}"
            f" 共 {cover.get('rows')} 行，各资产自身区间：{spans}"
            "（起点晚于其他资产的即截短区间的资产）"
        )

    def _valuation_context(
        self, index: pd.DatetimeIndex, cfg: Dict[str, Any], params: Dict[str, Any]
    ) -> Tuple[float, float]:
        """取信号日估值序列值与其在「信号日减 pe_years 年」窗口内的分位.

        窗口轴用**估值序列自身的期日**，而不是价格矩阵的日期轴：估值序列的期日
        就是它的采样密度（日频 PE 即交易日），价格矩阵在组内资产上市前的月份是
        空的，用它做轴会把分位分母算少。信号日不在期日上时取 ≤ 信号日的最近值
        （与原型「估值序列对齐到日历后前向填充」同构）。

        Returns:
            (当日估值, 分位)；当日估值缺失或窗口无有效值时抛错，不兜底
        """
        panels_raw = params.get(f"_panel_{_PANEL_NAME}")
        if not panels_raw:
            raise ValueError(
                "[dividend_garp] 未注入 macro_series 面板，无法计算红利估值防守。"
                "请确认已导入估值序列，且策略经 get_extra_panels 声明的面板加载通道生效"
            )
        code = cfg["pe_code"]
        values: Dict[pd.Timestamp, float] = {}
        for key, frame in panels_raw.items():
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
            if value == value and np.isfinite(value):
                values[pd.Timestamp(key).normalize()] = value
        if not values:
            raise ValueError(
                f"[dividend_garp] 面板中没有估值序列 {code!r}（或其取值全为空）。"
                "请检查 macro_series 导入的序列代码"
            )

        series = pd.Series(values).sort_index()
        signal_date = pd.Timestamp(index[-1])
        available = series.loc[series.index <= signal_date]
        if available.empty:
            raise ValueError(
                f"[dividend_garp] 估值序列 {code!r} 最早期日为 {series.index[0].date()}，"
                f"晚于信号日 {signal_date.date()}，无可用估值。请补齐估值序列历史"
            )
        pe_now = float(available.iloc[-1])
        if not np.isfinite(pe_now):
            raise ValueError(
                f"[dividend_garp] 信号日 {signal_date.date()} 的估值序列 {code!r} 无有效值"
                f"（最近期为 {available.index[-1].date()}）"
            )

        left = minus_years(signal_date, cfg["pe_years"])
        window = (series.index > left) & (series.index <= signal_date)
        window_values = series.loc[window].dropna()
        if window_values.empty:
            raise ValueError(
                f"[dividend_garp] 估值分位窗口（{left.date()} ~ {signal_date.date()}）内"
                f"没有 {code!r} 的有效取值，请延长估值序列历史或减小 pe_years"
            )
        pct = float((window_values <= pe_now).mean())
        if not np.isfinite(pct):
            raise ValueError(f"[dividend_garp] 信号日估值分位无效：{pct!r}")
        return pe_now, pct

    def _apply_pe_hysteresis(self, pct: float, cfg: Dict[str, Any]) -> bool:
        """估值防守滞回：> 进入线才进、< 退出线才出，中间保持上期状态."""
        state = self._ensure_state()
        prev = bool(state.get("div_defense", False))
        if not prev and pct > cfg["pe_hi"]:
            cur = True
        elif prev and pct < cfg["pe_lo"]:
            cur = False
        else:
            cur = prev
        state["div_defense"] = cur
        return cur

    def _apply_trend_add(self, dev: float, part: float, cfg: Dict[str, Any]) -> float:
        """成长趋势乘数：弱于均线做防守，强于均线且满参与时线性加仓."""
        if dev < 0:
            return cfg["grw_def"]
        full_part = min(1.0, cfg["part_max"])
        if dev > cfg["add_lo"] and part >= full_part - TOL:
            span = cfg["add_hi"] - cfg["add_lo"]
            gain = min(1.0, (dev - cfg["add_lo"]) / span)
            return 1.0 + cfg["add_max"] * gain
        return 1.0

    def _calc_signal(
        self,
        px: pd.DataFrame,
        groups: Dict[str, List[str]],
        cfg: Dict[str, Any],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """信号日收盘后的三步信号：波动率参与度 → 估值防守滞回 → 成长趋势乘数."""
        index = pd.DatetimeIndex(px.index)
        t = pd.Timestamp(index[-1])
        if not groups["DIV"] or not groups["GRW"]:
            raise ValueError(
                f"[dividend_garp] 分组为空：红利组 {groups['DIV']}、成长组 {groups['GRW']}；"
                "两组都需要至少一只资产才能合成权益收益"
            )

        # ① 权益合成日收益：红利端/成长端各自组内等权后按配比加权（配比归一化）
        rets = px.pct_change(fill_method=None)
        div_ret = rets[groups["DIV"]].mean(axis=1)
        grw_ret = rets[groups["GRW"]].mean(axis=1)
        w_sum = cfg["w_div"] + cfg["w_grw"]
        if w_sum <= TOL:
            raise ValueError("[dividend_garp] 红利端与成长端配比之和为 0，无法合成权益收益")
        eq_ret = (cfg["w_div"] * div_ret + cfg["w_grw"] * grw_ret) / w_sum

        # ② 实现波动率与参与度（窗口含信号日当日；样本标准差 skipna，与原型一致）
        vol_n = cfg["vol_n"]
        seg = eq_ret.iloc[-vol_n:]
        if len(seg) < vol_n:
            raise ValueError(
                f"[dividend_garp] 信号日 {t.date()} 的有效价格仅 {len(px)} 行，"
                f"不足波动率窗口 vol_n={vol_n}，请延长回测起点之前的历史或减小 vol_n"
                f"{self._coverage_hint()}"
            )
        vol = float(seg.std(ddof=1)) * np.sqrt(float(cfg["ann_days"]))
        if not np.isfinite(vol) or vol <= 0:
            raise ValueError(
                f"[dividend_garp] 信号日 {t.date()} 的 {vol_n} 日实现波动率无效：{vol!r}"
            )
        part = min(cfg["part_max"], max(cfg["part_min"], cfg["vol_target"] / vol))

        # ③ 估值防守（滞回）
        pe_now, pe_pct = self._valuation_context(index, cfg, params)
        div_defense = self._apply_pe_hysteresis(pe_pct, cfg)
        div_mult = cfg["div_mult"] if div_defense else 1.0

        # ④ 成长趋势偏离与乘数（合成价格：单只时即该只原始价格）
        grw_px = composite_price(px[groups["GRW"]])
        ma_n = cfg["ma_n"]
        ma_seg = grw_px.iloc[-ma_n:]
        if len(ma_seg) < ma_n:
            raise ValueError(
                f"[dividend_garp] 信号日 {t.date()} 的有效价格仅 {len(px)} 行，"
                f"不足趋势均线窗口 ma_n={ma_n}，请延长回测起点之前的历史或减小 ma_n"
                f"{self._coverage_hint()}"
            )
        ma = float(ma_seg.mean())
        if not np.isfinite(ma) or ma <= 0:
            raise ValueError(f"[dividend_garp] 信号日 {t.date()} 的趋势均线无效：{ma!r}")
        grw_now = float(grw_px.iloc[-1])
        dev = grw_now / ma - 1.0
        if not np.isfinite(dev):
            raise ValueError(f"[dividend_garp] 信号日 {t.date()} 的成长端均线偏离无效：{dev!r}")
        grw_mult = self._apply_trend_add(dev, part, cfg)

        return {
            "signal_date": t,
            "vol": vol,
            "part": part,
            "pe": pe_now,
            "pe_pct": pe_pct,
            "div_defense": div_defense,
            "div_mult": div_mult,
            "grw_price": grw_now,
            "ma": ma,
            "dev": dev,
            "grw_mult": grw_mult,
        }

    def _make_weights(
        self, sig: Dict[str, Any], groups: Dict[str, List[str]], cfg: Dict[str, Any]
    ) -> Tuple[pd.Series, Dict[str, Any]]:
        """按中枢 × 配比 × 参与度 × 端点乘数得到目标权重，剩余进债券端.

        顺序与原型一致：先算红利端/成长端 → 权益合计超上限只压成长端加仓部分 →
        低于下限两端等比例放大 → 债券端承接剩余。
        """
        part = float(sig["part"])
        wd = cfg["center"] * cfg["w_div"] * part * float(sig["div_mult"])
        wg = cfg["center"] * cfg["w_grw"] * part * float(sig["grw_mult"])

        cap = cfg["eq_cap"]
        cap_binding = (wd + wg) > cap + TOL
        if cap_binding:
            wg = max(cap - wd, 0.0)

        floor_binding = False
        floor = cfg["eq_floor"]
        if floor > TOL and (wd + wg) < floor - TOL:
            eq_total = wd + wg
            if eq_total <= TOL:
                raise ValueError(
                    f"[dividend_garp] 信号日权益合计 {eq_total:.6f} 过低，"
                    f"无法放大到权益下限 eq_floor={floor}；请检查参与度下界与防守乘数"
                )
            scale = floor / eq_total
            wd *= scale
            wg *= scale
            floor_binding = True

        bond_total = 1.0 - wd - wg
        if bond_total < -TOL:
            raise ValueError(
                f"[dividend_garp] 权益合计 {wd + wg:.6f} 超过 1，债券端权重为负"
                f"（{bond_total:.6f}）；请检查权益上限 eq_cap 与中枢设置"
            )
        bond_total = max(bond_total, 0.0)

        weights: Dict[str, float] = {}
        if bond_total > TOL and not groups["BOND"]:
            raise ValueError(
                f"[dividend_garp] 债券端需承接 {bond_total:.6f} 的剩余权重，但 bond_codes 为空；"
                "请补充债券组资产，或把权益中枢调至满仓口径"
            )
        for code in groups["DIV"]:
            weights[code] = wd / len(groups["DIV"])
        for code in groups["GRW"]:
            weights[code] = wg / len(groups["GRW"])
        for code in groups["BOND"]:
            weights[code] = bond_total / len(groups["BOND"])

        cons = {
            "w_div": wd,
            "w_grw": wg,
            "w_bond": bond_total,
            "eq_total": wd + wg,
            "cap_binding": cap_binding,
            "floor_binding": floor_binding,
        }
        return pd.Series(weights, dtype=float), cons

    def _register_cost_state(self, weights: pd.Series, cfg: Dict[str, Any]) -> None:
        """登记本期目标权重与年费口径，供日结算钩子计提指数年费.

        交易成本不在此处计：分资产费率由 :meth:`get_trading_costs` 声明，引擎在
        成交时按 code 从现金扣除并当日记入快照，与原型 ``tot *= (1 − tc)``
        同一时点。本处只保留按持有市值逐日计提的年费（属持有成本，非交易成本）。
        """
        state = self._ensure_state()
        target = {str(k): float(v) for k, v in weights.items() if float(v) > TOL}
        state["target_weights"] = target
        state["fee_codes"] = list(cfg["fee_codes"])
        state["tool_fee_annual"] = float(cfg["tool_fee"])
        state["ann_days"] = float(cfg["ann_days"])
        state["fee_weight"] = float(sum(target.get(c, 0.0) for c in cfg["fee_codes"]))

    def _audit(
        self,
        sig: Dict[str, Any],
        groups: Dict[str, List[str]],
        cons: Dict[str, Any],
        cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        """记录本期审计并累计跨期计数（供 compute_monitoring_metrics 暴露到前端）."""
        state = self._ensure_state()
        audit: Dict[str, Any] = {
            "signal_date": str(pd.Timestamp(sig["signal_date"]).date()),
            "account_mode": cfg["account_mode"],
            "center": cfg["center"],
            "eq_cap": cfg["eq_cap"],
            "eq_floor": cfg["eq_floor"],
            "vol": sig["vol"],
            "part": sig["part"],
            "pe": sig["pe"],
            "pe_pct": sig["pe_pct"],
            "div_defense": sig["div_defense"],
            "div_mult": sig["div_mult"],
            "grw_price": sig["grw_price"],
            "ma": sig["ma"],
            "dev": sig["dev"],
            "grw_mult": sig["grw_mult"],
            "w_div": cons["w_div"],
            "w_grw": cons["w_grw"],
            "w_bond": cons["w_bond"],
            "eq_total": cons["eq_total"],
            "cap_binding": cons["cap_binding"],
            "floor_binding": cons["floor_binding"],
            "group_detail": {k: list(v) for k, v in groups.items()},
        }
        state["last_audit"] = audit
        state["rebalance_count"] = int(state.get("rebalance_count", 0)) + 1
        counts: Dict[str, int] = state.setdefault("trigger_counts", {})
        if float(sig["part"]) < cfg["part_max"] - TOL:
            counts["vol_scaled"] = int(counts.get("vol_scaled", 0)) + 1
        if sig["div_defense"]:
            counts["div_defense"] = int(counts.get("div_defense", 0)) + 1
        if float(sig["grw_mult"]) < 1.0 - TOL:
            counts["grw_defense"] = int(counts.get("grw_defense", 0)) + 1
        elif float(sig["grw_mult"]) > 1.0 + TOL:
            counts["grw_add"] = int(counts.get("grw_add", 0)) + 1
        if cons["cap_binding"]:
            counts["cap_binding"] = int(counts.get("cap_binding", 0)) + 1
        if cons["floor_binding"]:
            counts["floor_binding"] = int(counts.get("floor_binding", 0)) + 1
        return audit

    def _final_check(self, weights: pd.Series, cfg: Dict[str, Any]) -> None:
        """归一化与越界末检；``strict_validate`` 下报错，不静默裁剪."""
        if (weights < -TOL).any():
            bad = {k: float(v) for k, v in weights.items() if float(v) < -TOL}
            if cfg["strict_validate"]:
                raise ValueError(f"[dividend_garp] 目标权重出现负值：{bad}")
            weights.clip(lower=0.0, inplace=True)
        total = float(weights.sum())
        if total <= TOL:
            raise ValueError("[dividend_garp] 目标权重合计为 0，约束投影后无可配置权重")
        if abs(total - 1.0) > 1e-6:
            if cfg["strict_validate"]:
                raise ValueError(
                    f"[dividend_garp] 目标权重合计 {total:.10f} 偏离 1（容差 1e-6），"
                    "请检查中枢、上限与下限的参数组合"
                )
            weights *= 1.0 / total

    # ------------------------------------------------------------------
    # 日度波动率风控（默认关闭）
    # ------------------------------------------------------------------

    def check_volatility_trigger(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params: Any,
    ) -> Tuple[bool, Optional[float]]:
        """日度波动率重置闸门（默认关闭）.

        波动率控制已在包内按``vol_target / σ`` 的参与度完成（含 ``part_min`` /
        ``part_max`` 上下限），日度重置会与包内缩放重复；且 ``target_vol`` 是参与度
        基准而非风控目标，被监控当成重置目标会把仓位误缩到 ``target_vol / 实现波动率``。
        回测引擎、监控 ``signal_detector`` 与本方法读同一个 ``enable_daily_vol_control``。

        开关打开时按组合权重的 ``vol_n`` 日实现波动率与 ``daily_vol_trigger`` 比较。
        """
        if not params.get("enable_daily_vol_control", False):
            return False, None
        if current_weights is None or prices is None or prices.empty:
            return False, None
        trigger = _as_float(params.get("daily_vol_trigger"), 0.06, "daily_vol_trigger")
        cols = [c for c in prices.columns if c in set(current_weights.index)]
        if not cols or len(prices) < 3:
            return False, None
        rets = prices[cols].pct_change(fill_method=None)
        vol_n = _as_int(params.get("vol_n"), 60, "vol_n")
        rets = rets.iloc[-vol_n:]
        w = current_weights.reindex(cols).fillna(0.0).astype(float)
        port_ret = (rets * w).sum(axis=1)
        vol = float(port_ret.std(ddof=1)) * np.sqrt(float(_as_float(
            params.get("ann_days"), 252.0, "ann_days"
        )))
        if not np.isfinite(vol) or vol <= 0:
            return False, None
        return (vol > trigger, vol)

    # ------------------------------------------------------------------
    # 日结算钩子：交易成本与指数年费
    # ------------------------------------------------------------------

    def on_daily_settle(self, time, position, total_value, bar_extra=None):
        """按持仓市值摊薄当日指数年费（持有成本，非交易成本）.

        年费按 ``tool_fee_codes`` 上一结算日市值 × ``tool_fee / ann_days`` 计提：结算
        钩子在快照之后执行，故 t 日收盘计提影响 t+1 日净值，与原型 ``nav[t]`` 内
        扣的 ``val[t-1] × fee_d`` 同相位。取不到当日收盘价时回退为「总市值 × 上次
        调仓时年费清单权重」。交易成本已由引擎在成交时按 :meth:`get_trading_costs`
        扣除，本钩子不重复计量。

        计提方式是**等比例缩减年费资产的持仓数量**，现金不变：原型在收益率
        序列上扣 ``tool_fee / ann_days``，等价于 ``qty × (1 - fee_d)``；若改为
        从现金扣，现金会长期为负，负现金不计息相当于无息杠杆，使年费的实际
        拖累被低估（实测复利放大倍数 1.372 对原型 1.384）。

        监控通道不调用本钩子，监控净值为 gross 口径（系统既有约定）。
        """
        from app.backtesting.types import Position

        if position is None or total_value is None or float(total_value) <= 0:
            return None
        state = self._ensure_state()
        settle_count = int(state.get("settle_count", 0))
        state["settle_count"] = settle_count + 1
        closes = (bar_extra or {}).get("close") or {}

        fee_annual = float(state.get("tool_fee_annual", 0.0) or 0.0)
        ann_days = float(state.get("ann_days", 252.0) or 252.0)
        fee_codes = set(state.get("fee_codes") or ())
        if fee_annual <= 0 or ann_days <= 0 or not fee_codes:
            return None
        fee_value = 0.0
        for code, qty in (position.quantity or {}).items():
            if code not in fee_codes:
                continue
            price = closes.get(code)
            if price is None:
                continue
            price = float(price)
            if not np.isfinite(price) or price <= 0:
                continue
            fee_value += float(qty) * price
        if fee_value <= 0:
            fee_value = float(total_value) * float(state.get("fee_weight", 0.0) or 0.0)
        # 计提基数取上一结算日的年费资产市值：原型在 t 日扣 ``val[t-1] × fee_d``，
        # 而本钩子在 t 日收盘执行、影响 t+1 净值，两者相位相同；用当日市值会使
        # 每期基数多算 1 日涨跌，累计多扣（实测 ±2e-5）。
        base_value = float(state.get("fee_value_prev", 0.0) or 0.0) or fee_value
        state["fee_value_prev"] = fee_value
        drag = base_value * fee_annual / ann_days
        if drag <= 0:
            return None
        # 缩放比例用当日市值换算，保证总市值减少量精确等于 drag
        keep = max(1.0 - drag / fee_value, 0.0) if fee_value > 0 else 1.0
        new_qty = dict(position.quantity or {})
        for code in fee_codes:
            if code in new_qty:
                new_qty[code] = float(new_qty[code]) * keep
        return (
            Position(quantity=new_qty, cash=float(position.cash)),
            float(total_value) - drag,
        )

    # ------------------------------------------------------------------
    # 监控指标
    # ------------------------------------------------------------------

    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> Dict[str, Any]:
        """暴露三步信号的实时取值、约束触发次数与权重分布（前端监控页指标区）."""
        state = self._ensure_state()
        audit: Dict[str, Any] = state.get("last_audit") or {}
        return {
            "rebalance_count": int(state.get("rebalance_count", 0)),
            "constraint_trigger_counts": dict(state.get("trigger_counts") or {}),
            "last_signal_date": audit.get("signal_date"),
            "account_mode": audit.get("account_mode"),
            "realized_volatility": audit.get("vol"),
            "vol_target": _as_float(params.get("vol_target"), 0.14, "vol_target"),
            "participation": audit.get("part"),
            "pe": audit.get("pe"),
            "pe_quantile": audit.get("pe_pct"),
            "div_defense": audit.get("div_defense"),
            "growth_deviation": audit.get("dev"),
            "growth_multiplier": audit.get("grw_mult"),
            "target_weight_dividend": audit.get("w_div"),
            "target_weight_growth": audit.get("w_grw"),
            "target_weight_bond": audit.get("w_bond"),
            "target_weight_equity": audit.get("eq_total"),
            "cap_binding": audit.get("cap_binding"),
            "floor_binding": audit.get("floor_binding"),
        }

    def _ensure_state(self) -> Dict[str, Any]:
        """跨期状态容器（估值防守滞回、成本登记）；首次访问时惰性创建."""
        state = getattr(self, "_state", None)
        if not isinstance(state, dict):
            state = {}
            self._state = state
        return state
