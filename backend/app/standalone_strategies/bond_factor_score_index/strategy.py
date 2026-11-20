"""债券券池因子打分指数（bond_factor_score_index）：打包独立形态的债券打分选样 + 等权策略.

方法：每个调仓生效日取当期券池截面 → 数值因子按名次线性打分
（score = 100*(rank_max-1)/(N-1)，并列同分）或距目标线性扣分
（score = max(0, 100*(1-|x-target|/span))）→ 加权合成综合分 → 按券池分组
（industry 列）逐组做单发行人限额后取得分前 K 只 → 等权 1/N。
截面缺数值因子列、或因子整列为空时无法打分：配置了拼接指数则改持指数，
未配置时视为指数成分快照期（全截面入选、等权），审计指标 selection_source
区分来源。

模式：打包独立形态（``strategy_form="standalone"``）。composition 三层全 None，
选样/打分/赋权全部在本模块内，对外只暴露参数与底层资产；券池截面经数据加载层
按 ``get_extra_panels`` 声明从 factor_panel 集合加载、由引擎 set_panels 注入，
调仓日由注入的面板期日（event_dates）驱动，策略类内不出现具体日期常量。
面板期日（as_of_date）= 截面决策日（生效日前一交易日）：引擎收盘成交、新权重
自次日起息，二者叠加即指数「生效日收益用新权重」的口径。指数现金桶（季内票息
存入现金桶、季首再投资）不在可执行口径内，与官方点位的累计差异量化留痕于
回归对账日志，不做隐式模拟。
同一份代码供回测、日常监控、组合子策略三条通道使用。

拼接（splice）
--------------
回测起点早于第一期券池截面、某期截面滞后超过 ``panel_max_lag_days``、或
期日存在但打分因子整列缺失时，默认直接报错要求补齐历史截面。配置
``splice_index_code``（真实指数代码，须在资产池内且行情到位）后，这些
「算不了」的期改为 100% 持有该指数（如浙江债券指数），有可用截面的期再按
因子打分；``splice_until`` 可显式指定强制拼接的截止日，留空则按截面可用性
自动切换。三种选样来源在审计指标
``selection_source`` 上区分：``factor_score`` / ``constituent_snapshot`` /
``index_splice``，拼接期同样计入调仓次数。

红线：``allocate`` 为纯函数，只消费注入的 prices 与 params（含 ``_as_of`` 与
``_panel_factor_panel``），不读文件、不查库；因子、券池分组、发行人全部来自
注入截面，打分权重、限额、选取数量、拼接指数全部来自参数；截面缺失、滞后
超限、分组未声明限额时报错，不隐式兜底等权、不跳过标的、不放宽断言（唯一
例外是显式配置的 ``splice_index_code``：无截面期改持该指数并留痕，未配置时
仍按原口径报错）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.allocation.models.base import BaseStrategyModel

_log = logging.getLogger(__name__)

# 面板名（与 data_feed.PANEL_LOADERS 注册键、get_extra_panels 声明一致）
_PANEL_NAME = "factor_panel"

# 本策略读的因子数据集（须在 field_mappings.FACTOR_DATASETS 受控清单内）。
# 写死在类上而不做成运行期参数：面板在 DataFeed 构建期按 strategy_type 静态
# 加载，早于策略实例化；要换数据集就是另一个数据产品，应另注册一个策略。
_DATASET = "bond_phoenix50"

# 打分因子默认键（与 field_mappings.FACTOR_NAME_MAPPING_BY_DATASET 的英文键一致）
_DEFAULT_SCORE_FACTORS: Tuple[str, ...] = (
    "issue_size",         # 债券发行规模（名次打分）
    "issuer_size",        # 主体发行规模（名次打分）
    "modified_duration",  # 修正久期（距目标打分）
)
_DEFAULT_SCORE_WEIGHTS: Tuple[float, ...] = (0.2, 0.2, 0.6)
# 名次打分因子；不在其中的打分因子按距目标线性扣分
_DEFAULT_RANK_FACTORS: Tuple[str, ...] = ("issue_size", "issuer_size")

# 分组（industry 列）→ 单发行人限额 / 组内选取数量
_DEFAULT_POOL_CAPS: Tuple[str, ...] = ("其它信用债:2", "金融债/地方债/二永债:10")
_DEFAULT_POOL_TOPK: Tuple[str, ...] = ("其它信用债:10", "金融债/地方债/二永债:50")

# 类别因子键：分组用固定字段 industry，单发行人限额用 issuer
_ISSUER_COL = "issuer"

# 等权权重合计容差
_WEIGHT_TOL = 1e-8

# 拼接原因（审计留痕用机器码，中文说明见 _PanelState.detail）
_SPLICE_NO_PANEL = "no_panel_before_as_of"   # 执行日早于最早期截面
_SPLICE_LAG = "lag_over_limit"               # 当期截面滞后超上限
_SPLICE_UNTIL = "splice_until_window"        # splice_until 显式窗口内
_SPLICE_NO_FACTORS = "no_scoring_factors"    # 期日存在但打分因子整列缺失

# 打分/排序内部列名
_SCORE_COL = "_composite_score"
_CODE_COL = "_code"


# ---------------------------------------------------------------------------
# 纯函数：参数解析
# ---------------------------------------------------------------------------


def _parse_list(value: Any, default: Sequence[str]) -> List[str]:
    """把逗号分隔参数归一为字符串列表（空→默认）."""
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple, set)):
        raw: Sequence[Any] = list(value)
    else:
        raw = [p.strip() for p in str(value).split(",") if p.strip()]
    parsed = [str(x).strip() for x in raw if str(x).strip()]
    return parsed or list(default)


def _parse_float_list(value: Any, default: Sequence[float], name: str) -> List[float]:
    """把逗号分隔数值参数归一为浮点列表（空→默认）；非法直接报错."""
    if value is None or value == "":
        return list(default)
    if isinstance(value, (list, tuple)):
        raw: Sequence[Any] = list(value)
    else:
        raw = [p.strip() for p in str(value).split(",") if p.strip()]
    out: List[float] = []
    for x in raw:
        try:
            out.append(float(x))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"[bond_factor_score_index] 参数 {name}={value!r} 含非数值项 {x!r}"
            ) from exc
    return out or list(default)


def _parse_int(value: Any, default: int, name: str) -> int:
    """把数量参数归一为整数；非法直接报错（不静默回退默认值）."""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"[bond_factor_score_index] 参数 {name}={value!r} 非法，应为整数：{exc}"
        ) from exc


def _parse_group_map(value: Any, default: Sequence[str], name: str) -> Dict[str, int]:
    """解析「分组:整数」逗号分隔参数（如 其它信用债:2,金融债/地方债/二永债:10）."""
    items = _parse_list(value, default)
    out: Dict[str, int] = {}
    for item in items:
        if ":" not in item:
            raise ValueError(
                f"[bond_factor_score_index] 参数 {name} 项 {item!r} 应为「分组:整数」格式"
            )
        grp, _, num = item.rpartition(":")
        grp = grp.strip()
        if not grp:
            raise ValueError(
                f"[bond_factor_score_index] 参数 {name} 项 {item!r} 分组名为空"
            )
        try:
            out[grp] = int(float(num))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"[bond_factor_score_index] 参数 {name} 项 {item!r} 限额非整数"
            ) from exc
    return out


def _truncate_list(items: Sequence[str], limit: int = 10) -> str:
    """列举前 limit 条，超出以计数收尾（用于异常文本，避免淹没关键信息）."""
    listed = list(items)
    if len(listed) <= limit:
        return "、".join(listed)
    return "、".join(listed[:limit]) + f" 等 {len(listed)} 只"


def _parse_splice_until(value: Any) -> Optional[pd.Timestamp]:
    """把拼接截止日归一为 Timestamp；空 → None；非法格式报错（不静默忽略）."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return pd.Timestamp(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"[bond_factor_score_index] 参数 splice_until={value!r} 非法，"
            f"应为 YYYY-MM-DD 格式日期：{exc}"
        ) from exc


@dataclass(frozen=True)
class _PanelState:
    """当期券池截面的解析结果：``reason`` 为空表示截面可用.

    截面不可用时不再就地抛错，而是把原因交给调用方裁决：配置了拼接指数就改持
    指数，未配置才按原口径报错。``detail`` 是可直接拼进异常文本的中文说明。
    """

    period_date: Optional[pd.Timestamp] = None
    panel: Optional[pd.DataFrame] = None
    lag: int = 0
    reason: str = ""
    detail: str = ""


# ---------------------------------------------------------------------------
# 纯函数：打分与等权
# ---------------------------------------------------------------------------


def rank_score(s: pd.Series) -> pd.Series:
    """名次线性打分: score = 100*(rank(x)-1)/(N-1).

    并列取 max 名次（同值同分）；分母固定为 N-1 而不是 max(rank)-min(rank)，
    否则最末并列组会被抬到 0 分以上、整体尺度偏差 100/(N-1)。
    """
    vals = s.astype(float)
    n = len(vals)
    if n < 2:
        raise ValueError(
            f"[bond_factor_score_index] 名次打分截面仅 {n} 行，无法计算名次分"
        )
    r = vals.rank(method="max", ascending=True)
    return 100.0 * (r - 1.0) / (n - 1.0)


def target_distance_score(s: pd.Series, target: float, span: float) -> pd.Series:
    """距目标线性扣分: score = max(0, 100*(1-|x-target|/span))；偏离 span 归零."""
    if span <= 0:
        raise ValueError(
            f"[bond_factor_score_index] 距目标打分全距 span={span} 非法，必须为正"
        )
    dev = (s.astype(float) - target).abs()
    return np.maximum(0.0, 100.0 * (1.0 - dev / span))


def equal_weights(codes: Sequence[str]) -> pd.Series:
    """等权 1/N：每只严格取 1/N（指数编制口径），不做十进位舍入.

    先均分再校验浮点累加和：仅当偏差超 ``_WEIGHT_TOL`` 时才把残差归代码
    最小券（常规 N 不会触发）。无条件先舍入到 8 位再把尾差堆到一只券，
    会使该券权重偏离 1/N 达 2e-7（N=60 时），是对指数等权口径的无益损失。
    """
    uniq = sorted(set(str(c) for c in codes))
    if not uniq:
        raise ValueError("[bond_factor_score_index] 入选集合为空，无法计算等权")
    per = 1.0 / len(uniq)
    weights = {code: per for code in uniq}
    residual = 1.0 - sum(weights.values())
    if abs(residual) > _WEIGHT_TOL:
        weights[uniq[0]] += residual
    if abs(sum(weights.values()) - 1.0) > _WEIGHT_TOL:
        raise RuntimeError(
            f"[bond_factor_score_index] 等权合计不为 1：{sum(weights.values())}"
        )
    return pd.Series(weights, dtype=float)


class BondFactorScoreIndexStrategy(BaseStrategyModel):
    """债券券池因子打分指数：名次/距目标打分 → 发行人限额 → 分组前 K → 等权."""

    # ------------------------------------------------------------------
    # 元信息声明
    # ------------------------------------------------------------------

    @classmethod
    def get_param_schema(cls):
        from app.allocation.models.param_schema import (
            ParamSchema,
            StrategyParamSchema,
            model_level_param_group,
        )

        return StrategyParamSchema(
            strategy_type="bond_factor_score_index",
            display_name="债券券池因子打分指数",
            description=(
                "每个调仓生效日取当期券池截面：数值因子按名次线性打分"
                "（100*(名次-1)/(N-1)）或距目标线性扣分（偏离全距归零），加权合成"
                "综合分 → 按券池分组逐组单发行人限额后取得分前 K 只 → 等权 1/N。"
                "截面缺数值因子列时按指数成分快照处理（全截面入选等权）。"
                "选样/打分/赋权全部在策略包内，前端配置打分因子、权重、分组限额与选取数量"
            ),
            composition={
                "selector": None,
                "allocator": "bond_factor_score_index",
                "controller": None,
                "schedule": {"rebalance_freq": "daily", "execution_delay": 0},
            },
            # 等权在包内归一到合计恰为 1，Pipeline 不再做杠杆缩放
            internal_leverage=True,
            params=[
                # ━━━ 算法核心（core） ━━━
                ParamSchema(
                    name="score_factors", label="打分因子", type="text",
                    default=",".join(_DEFAULT_SCORE_FACTORS),
                    description=(
                        "参与综合打分的因子键（逗号分隔，键名见 factor_panel 导入映射）。"
                        "默认：债券发行规模、主体发行规模、修正久期；顺序与打分权重一一对应"
                    ),
                ),
                ParamSchema(
                    name="score_weights", label="打分权重", type="text",
                    default=",".join(str(w) for w in _DEFAULT_SCORE_WEIGHTS),
                    description="综合分 = 各因子得分按此权重（逗号分隔）加权；个数须与打分因子一致",
                ),
                ParamSchema(
                    name="rank_factors", label="名次打分因子", type="text",
                    default=",".join(_DEFAULT_RANK_FACTORS),
                    description=(
                        "按名次线性打分的因子键（逗号分隔）；不在其中的打分因子按"
                        "距目标线性扣分（目标与全距见下两项）"
                    ),
                ),
                ParamSchema(
                    name="duration_target", label="距目标打分目标值", type="number",
                    default=2.5, min_value=-100.0, max_value=100.0, step=0.1,
                    description="距目标打分因子的目标值（修正久期目标 2.5 年）",
                ),
                ParamSchema(
                    name="duration_span", label="距目标打分全距", type="number",
                    default=7.5, min_value=0.01, max_value=100.0, step=0.1,
                    description="距目标打分的扣分全距：偏离达此值记 0 分（修正久期 7.5 年）",
                ),
                ParamSchema(
                    name="pool_caps", label="单发行人限额", type="text",
                    default=",".join(_DEFAULT_POOL_CAPS),
                    description=(
                        "按券池分组（industry 列）的单发行人入选限额，格式「分组:整数」"
                        "逗号分隔；截面出现未声明限额的分组即报错"
                    ),
                ),
                ParamSchema(
                    name="pool_topk", label="分组选取数量", type="text",
                    default=",".join(_DEFAULT_POOL_TOPK),
                    description=(
                        "按券池分组的入选数量上限，格式「分组:整数」逗号分隔；"
                        "与单发行人限额共用分组键"
                    ),
                ),
                ParamSchema(
                    name="splice_index_code", label="拼接指数代码", type="text",
                    default="CCX11801.WI",
                    description=(
                        "无可用券池截面的区间改为 100% 持有该指数（代码须在资产池内、"
                        "行情已导入）。默认 CCX11801.WI（浙江债券指数），券池截面"
                        "未覆盖的早期区间由它补足；留空 = 不拼接，缺截面时报错"
                    ),
                ),
                # ━━━ 技术细节（advanced） ━━━
                ParamSchema(
                    name="panel_max_lag_days", label="截面最大滞后交易日", type="number",
                    default=5, min_value=0, max_value=120, step=1,
                    description=(
                        "当期券池截面相对执行日允许的最大滞后交易日数，超过即报错"
                        "（调仓由面板期日驱动，正常滞后为 0）"
                    ),
                    group="advanced",
                ),
                ParamSchema(
                    name="splice_until", label="拼接截止日", type="text", default="",
                    description=(
                        "强制拼接的截止日（YYYY-MM-DD，含当日）：该日及之前一律持有"
                        "拼接指数，之后按因子打分。留空 = 自动，仅在截面缺失或滞后"
                        "超限的期用指数补"
                    ),
                    group="advanced",
                ),
                # ━━━ 模型级通用执行参数（调度/数据源/引擎层消费） ━━━
                *model_level_param_group(),
            ],
        )

    @classmethod
    def get_extra_panels(cls) -> list:
        """声明需要 factor_panel 截面（数据加载层据此从集合加载并经引擎注入）."""
        return [_PANEL_NAME]

    @classmethod
    def get_panel_datasets(cls) -> dict:
        """声明 factor_panel 读 bond_phoenix50（凤凰50债券券池季度截面）.

        factor_panel 被股票与债券两个数据集共用，不声明就会把另一域的同期日行
        并进本策略的截面：名次打分分母 N 被污染，成分快照期还会把另一域的券
        一起等权买入且不报错。
        """
        return {_PANEL_NAME: _DATASET}

    def get_data_feed_options(self) -> Dict[str, Any]:
        """声明数据源口径：加载 factor_panel、面板期日驱动调仓.

        ``panel_event_dates=True`` 使 Pipeline 把注入的面板期日作为 event_dates，
        调仓日 = 决策日收盘成交、新权重自生效日起息（与指数生效日口径一致）。
        """
        return {
            "extra_panels": [_PANEL_NAME],
            "panel_event_dates": True,
            # 调仓只依赖当期截面与拼接指数当日价格，不依赖价格历史窗口；
            # 声明 0 行使监控在首个价格日即可建仓（与回测首日口径一致），
            # 不再被 MonitorEngineAdapter 的 30 行门槛挡成空仓。
            "min_history_rows": 0,
        }

    def get_execution_schedule(self) -> Optional[dict]:
        """调仓由面板期日（event_dates）驱动，此处只声明频率兜底与零延迟.

        不写 selection_start_date / skip_dates 等日期常量：调仓日由注入的
        factor_panel 期日决定，什么日期范围的截面进来都能跑。
        """
        return {"rebalance_freq": "daily", "execution_delay": 0}

    @classmethod
    def get_data_contract(cls):
        """声明数据契约：价格须为正 + 参数自洽（运行前门禁，不依赖面板）.

        面板存在性、当期截面、因子有效性在 allocate 运行时校验（契约门禁
        执行时面板尚未注入）；此处只声明拿到配置与价格矩阵即可判定的项。
        不声明 min_assets / min_history_days / require_continuous：
        底层资产可自由配置、任意区间与日历都能跑。
        """
        from app.backtesting.data_contract import DataContract

        return DataContract(
            min_price=0.0,
            custom_checks=("params_coherent",),
        )

    # ------------------------------------------------------------------
    # allocate 主流程
    # ------------------------------------------------------------------

    def allocate(self, prices: pd.DataFrame, **params) -> pd.Series:
        """一次调仓的全部计算：取当期截面 → 打分 → 发行人限额 → 分组前 K → 等权.

        拼接期（无可用截面，或处于 ``splice_until`` 之前）不取截面，直接返回
        100% 拼接指数权重；未配置拼接指数时保持原报错口径。
        """
        if prices is None or prices.empty:
            raise ValueError("[bond_factor_score_index] 价格矩阵为空，无法计算权重")
        pool = [str(c) for c in prices.columns]
        # 面板未注入 / 未注入执行日属管道故障，优先于拼接配置报错
        state = self._try_resolve_panel(prices, params)
        as_of = pd.Timestamp(params["_as_of"])

        splice_code, splice_until = self._parse_splice(params)
        splice_reason = self._splice_reason(splice_code, splice_until, as_of, state)
        if splice_reason:
            return self._splice_weights(pool, splice_code, as_of, splice_reason, state)
        if state.reason:
            raise ValueError(
                f"[bond_factor_score_index] {state.detail}。请补齐该期截面，或配置"
                f" splice_index_code 关联真实指数，由指数行情补足无截面区间"
            )

        period_date, panel, lag = state.period_date, state.panel, state.lag
        cfg = self._parse_config(params)

        if self._is_constituent_snapshot(panel, cfg):
            # 无因子期：成分当期有行情时按成分快照等权（复现指数口径）；
            # 成分无行情时等权估不出净值，配置了拼接指数就改持指数。
            if splice_code and not self._panel_has_prices(prices, panel, as_of):
                return self._splice_weights(
                    pool, splice_code, as_of, _SPLICE_NO_FACTORS, state
                )
            selected = [str(c) for c in panel.index]
            dropped_screen = dropped_cap = 0
            source = "constituent_snapshot"
        else:
            screened, dropped_screen = self._screen(panel, cfg)
            if screened.empty:
                raise ValueError(
                    f"[bond_factor_score_index] {period_date.date()} 当期截面经初筛后"
                    f"无候选（打分因子 {cfg['score_factors']} 全部缺失）。请检查因子截面导入"
                )
            scored = self._score(screened, cfg)
            capped, dropped_cap = self._issuer_cap(scored, cfg, period_date)
            selected = self._select_topk(capped, cfg, period_date)
            source = "factor_score"
        if not selected:
            raise ValueError(
                f"[bond_factor_score_index] {period_date.date()} 未选出任何标的。"
                f"请检查截面分组与限额配置"
            )
        self._assert_in_pool(selected, pool, period_date)
        weights = equal_weights(selected)

        self._audit({
            "panel_as_of": str(period_date.date()),
            "lag_trading_days": lag,
            "selection_source": source,
            "candidate_count": int(len(panel)),
            "screened_out": int(dropped_screen),
            "issuer_cap_dropped": int(dropped_cap),
            "selected_count": len(selected),
            "weight_method": "equal",
            "max_weight": float(weights.max()),
            "top5_weight_sum": float(weights.nlargest(5).sum()),
        })
        return weights.reindex(pool).fillna(0.0)

    # ------------------------------------------------------------------
    # 分步实现（每步可单测）
    # ------------------------------------------------------------------

    def _parse_config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """把 params 归一为本期计算所需配置（一次性解析，避免散落在各步）."""
        score_factors = _parse_list(params.get("score_factors"), _DEFAULT_SCORE_FACTORS)
        score_weights = _parse_float_list(
            params.get("score_weights"), _DEFAULT_SCORE_WEIGHTS, "score_weights"
        )
        if len(score_weights) != len(score_factors):
            raise ValueError(
                f"[bond_factor_score_index] 打分权重个数 {len(score_weights)} 与"
                f"打分因子个数 {len(score_factors)} 不一致"
            )
        return {
            "score_factors": score_factors,
            "score_weights": score_weights,
            "rank_factors": set(_parse_list(params.get("rank_factors"), _DEFAULT_RANK_FACTORS)),
            "duration_target": float(params.get("duration_target", 2.5)),
            "duration_span": float(params.get("duration_span", 7.5)),
            "pool_caps": _parse_group_map(params.get("pool_caps"), _DEFAULT_POOL_CAPS, "pool_caps"),
            "pool_topk": _parse_group_map(params.get("pool_topk"), _DEFAULT_POOL_TOPK, "pool_topk"),
            "panel_max_lag_days": _parse_int(
                params.get("panel_max_lag_days"), 5, "panel_max_lag_days"
            ),
        }

    def _try_resolve_panel(
        self, prices: pd.DataFrame, params: Dict[str, Any]
    ) -> _PanelState:
        """尝试取执行日 ``_as_of`` 当期（≤ as_of 最近一期）券池截面.

        与直接报错的差别：截面「不可用」不再就地抛错，而是把原因带回由调用方
        裁决——配置了拼接指数就改持指数，未配置才按原口径报错。面板根本未注入
        属于管道故障，仍直接抛错：拼接只补历史缺失，不掩盖数据加载故障。

        Raises:
            ValueError: 面板未注入 / 未注入执行日 / 滞后上限参数非法
        """
        panels_raw = params.get(f"_panel_{_PANEL_NAME}")
        if not panels_raw:
            raise ValueError(
                "[bond_factor_score_index] 未注入 factor_panel 截面。请确认已导入券池"
                "截面数据，且策略经 get_extra_panels 声明的面板加载通道生效"
            )
        as_of = params.get("_as_of")
        if as_of is None:
            raise ValueError(
                "[bond_factor_score_index] 未注入执行日 _as_of，无法定位当期截面"
            )
        as_of = pd.Timestamp(as_of)
        panels = {pd.Timestamp(k): v for k, v in panels_raw.items()}
        eligible = sorted(d for d in panels if d <= as_of)
        if not eligible:
            earliest = min(panels)
            return _PanelState(
                reason=_SPLICE_NO_PANEL,
                detail=(
                    f"执行日 {as_of.date()} 之前无可用券池截面"
                    f"（最早期日 {earliest.date()}），该日之前没有可算的期"
                ),
            )
        period_date = eligible[-1]
        idx = pd.DatetimeIndex(prices.index)
        lag = int(((idx > period_date) & (idx <= as_of)).sum())
        max_lag = _parse_int(params.get("panel_max_lag_days"), 5, "panel_max_lag_days")
        if lag > max_lag:
            return _PanelState(
                period_date=period_date,
                panel=panels[period_date],
                lag=lag,
                reason=_SPLICE_LAG,
                detail=(
                    f"当期券池截面滞后 {lag} 个交易日（期日 {period_date.date()}，"
                    f"执行日 {as_of.date()}），超过上限 {max_lag}"
                ),
            )
        return _PanelState(period_date=period_date, panel=panels[period_date], lag=lag)

    @staticmethod
    def _parse_splice(params: Dict[str, Any]) -> Tuple[str, Optional[pd.Timestamp]]:
        """解析拼接配置；截止日必须与拼接指数成对出现（只配截止日无承接标的）."""
        code = str(params.get("splice_index_code") or "").strip()
        until = _parse_splice_until(params.get("splice_until"))
        if until is not None and not code:
            raise ValueError(
                "[bond_factor_score_index] 配置了拼接截止日 splice_until 但拼接指数"
                " splice_index_code 为空。请补全拼接指数，或清空截止日"
            )
        return code, until

    @staticmethod
    def _splice_reason(
        code: str,
        until: Optional[pd.Timestamp],
        as_of: pd.Timestamp,
        state: _PanelState,
    ) -> str:
        """判定本期是否拼接：显式窗口无条件拼接，自动模式只在截面不可用时拼接.

        Returns:
            拼接原因机器码；空串表示本期按截面选样
        """
        if not code:
            return ""
        if until is not None:
            return _SPLICE_UNTIL if as_of <= until else ""
        return state.reason

    def _splice_weights(
        self,
        pool: Sequence[str],
        code: str,
        as_of: pd.Timestamp,
        reason: str,
        state: _PanelState,
    ) -> pd.Series:
        """拼接期权重：100% 持有拼接指数，合并留痕.

        Raises:
            ValueError: 拼接指数不在资产池（``reindex`` 会静默清零，必须显式拦截）
        """
        if code not in set(pool):
            raise ValueError(
                f"[bond_factor_score_index] 拼接指数 {code!r} 不在资产池（价格矩阵）中，"
                f"权重无法落到净值。请把该代码加入 asset_codes 并导入其行情，"
                f"或清空 splice_index_code"
            )
        weights = pd.Series({code: 1.0}, dtype=float).reindex(list(pool)).fillna(0.0)
        self._audit({
            "panel_as_of": str(state.period_date.date()) if state.period_date is not None else "",
            "lag_trading_days": int(state.lag),
            "selection_source": "index_splice",
            "candidate_count": 0,
            "screened_out": 0,
            "issuer_cap_dropped": 0,
            "selected_count": 1,
            "weight_method": "splice_index",
            "max_weight": 1.0,
            "top5_weight_sum": 1.0,
            "splice_index_code": code,
            "splice_reason": reason,
            "as_of": str(as_of.date()),
        })
        _log.info(
            "[bond_factor_score_index] %s 拼接期（%s），100%% 持有 %s",
            as_of.date(), reason, code,
        )
        return weights

    @staticmethod
    def _is_constituent_snapshot(panel: pd.DataFrame, cfg: Dict[str, Any]) -> bool:
        """截面是否无打分因子（缺列或整列缺失），无法打分、只能走成分口径或拼接.

        不能只看列是否存在：data_feed 把整张面板所有期 union 后展平因子，
        早期期无因子但列仍在（值全 NaN），只看列会把无因子期误判为有因子截面，
        初筛后为空再报错，既不走拼接也不走成分快照。
        """
        for f in cfg["score_factors"]:
            if f not in panel.columns:
                return True
            if pd.to_numeric(panel[f], errors="coerce").notna().sum() == 0:
                return True
        return False

    @staticmethod
    def _panel_has_prices(
        prices: pd.DataFrame, panel: pd.DataFrame, as_of: pd.Timestamp
    ) -> bool:
        """截面成分在最近一个有效交易日是否全部有价格（成分等权可估值）."""
        if prices is None or prices.empty or panel is None or panel.empty:
            return False
        hist = prices.loc[:as_of]
        if hist.empty:
            return False
        last = hist.iloc[-1]
        return all(pd.notna(last.get(str(c))) for c in panel.index)

    def _screen(
        self, panel: pd.DataFrame, cfg: Dict[str, Any]
    ) -> Tuple[pd.DataFrame, int]:
        """初筛：打分因子转数值并剔除任一缺失的候选.

        Returns:
            (初筛后截面 index=code, 剔除行数)
        """
        df = panel.copy()
        df.index = df.index.astype(str)
        n0 = len(df)
        for f in cfg["score_factors"]:
            df[f] = pd.to_numeric(df[f], errors="coerce")
        df = df.dropna(subset=list(cfg["score_factors"]))
        return df, n0 - len(df)

    def _score(self, df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
        """逐因子打分（名次 / 距目标）后按 score_weights 加权合成综合分."""
        out = df.copy()
        score_cols: List[str] = []
        for f in cfg["score_factors"]:
            sc = f"_score_{f}"
            if f in cfg["rank_factors"]:
                out[sc] = rank_score(out[f])
            else:
                out[sc] = target_distance_score(
                    out[f], cfg["duration_target"], cfg["duration_span"]
                )
            score_cols.append(sc)
        out[_SCORE_COL] = sum(
            w * out[sc] for w, sc in zip(cfg["score_weights"], score_cols)
        )
        return out

    def _issuer_cap(
        self, df: pd.DataFrame, cfg: Dict[str, Any], period_date: pd.Timestamp
    ) -> Tuple[pd.DataFrame, int]:
        """按券池分组（industry）逐组做单发行人（issuer）限额；同分按代码升序."""
        if "industry" not in df.columns:
            raise ValueError(
                "[bond_factor_score_index] 当期截面缺少 industry（券池分组）列，无法分组限额"
            )
        if _ISSUER_COL not in df.columns:
            raise ValueError(
                f"[bond_factor_score_index] 当期截面缺少 {_ISSUER_COL}（发行人）列，"
                f"无法做单发行人限额。请在截面导入中补充债务主体列"
            )
        groups = sorted({str(g) for g in df["industry"].tolist()})
        unknown = [g for g in groups if g not in cfg["pool_caps"] or g not in cfg["pool_topk"]]
        if unknown:
            raise ValueError(
                f"[bond_factor_score_index] {period_date.date()} 截面分组 "
                f"{_truncate_list(unknown)} 未在 pool_caps/pool_topk 声明限额与选取数量。"
                f"已声明分组：{_truncate_list(sorted(cfg['pool_caps'].keys()))}"
            )
        tmp = df.copy()
        tmp[_CODE_COL] = tmp.index.astype(str)
        tmp["_group"] = tmp["industry"].astype(str)
        tmp[_ISSUER_COL] = tmp[_ISSUER_COL].astype(str)
        kept: List[pd.DataFrame] = []
        for g in groups:
            sub = tmp[tmp["_group"] == g].sort_values(
                by=[_SCORE_COL, _CODE_COL], ascending=[False, True], kind="mergesort"
            ).copy()
            sub["_rn"] = sub.groupby(_ISSUER_COL).cumcount() + 1
            kept.append(sub[sub["_rn"] <= cfg["pool_caps"][g]])
        capped = pd.concat(kept) if kept else tmp.iloc[0:0]
        return capped.drop(columns=[_CODE_COL, "_group", "_rn"]), len(tmp) - len(capped)

    def _select_topk(
        self, df: pd.DataFrame, cfg: Dict[str, Any], period_date: pd.Timestamp
    ) -> List[str]:
        """按券池分组逐组取综合分前 K（同分按代码升序）；返回选中代码列表."""
        tmp = df.copy()
        if _CODE_COL not in tmp.columns:
            tmp[_CODE_COL] = tmp.index.astype(str)
        tmp["_group"] = tmp["industry"].astype(str)
        picked: List[str] = []
        for g in sorted({str(x) for x in tmp["_group"]}):
            sub = tmp[tmp["_group"] == g].sort_values(
                by=[_SCORE_COL, _CODE_COL], ascending=[False, True], kind="mergesort"
            )
            picked.extend(list(sub[_CODE_COL].head(cfg["pool_topk"][g])))
        return picked

    def _assert_in_pool(
        self, selected: Sequence[str], pool: Sequence[str], period_date: pd.Timestamp
    ) -> None:
        """选中标的必须在价格矩阵（资产池）内，否则无法计算净值——报错不静默剔除."""
        pool_set = set(pool)
        missing = [c for c in selected if c not in pool_set]
        if missing:
            raise ValueError(
                f"[bond_factor_score_index] {period_date.date()} 选中标的不在资产池"
                f"（价格矩阵）中：{_truncate_list(missing)}。资产池须覆盖券池截面的"
                f"可选全集；请把这些代码加入 asset_codes 并补足行情"
            )

    # ------------------------------------------------------------------
    # 审计与监控指标
    # ------------------------------------------------------------------

    def _audit(self, metrics: Dict[str, Any]) -> None:
        """记录本期审计指标并累计调仓次数（供 compute_monitoring_metrics 暴露到前端）."""
        state = self._ensure_state()
        state["last_metrics"] = metrics
        state["rebalance_count"] = int(state.get("rebalance_count", 0)) + 1

    def compute_monitoring_metrics(
        self,
        current_weights: pd.Series,
        prices: pd.DataFrame,
        **params,
    ) -> Dict[str, Any]:
        """暴露当期截面、滞后、选样来源、限额淘汰与权重集中度（前端监控页指标区）."""
        state = self._ensure_state()
        metrics = dict(state.get("last_metrics") or {})
        metrics["rebalance_count"] = int(state.get("rebalance_count", 0))
        return metrics

    def _ensure_state(self) -> Dict[str, Any]:
        """跨期状态容器（不用模块级变量）."""
        state = getattr(self, "_state", None)
        if not isinstance(state, dict):
            state = {}
            self._state = state
        return state

    # ------------------------------------------------------------------
    # 自定义契约检查（DataContract.custom_checks）
    # ------------------------------------------------------------------

    def _check_params_coherent(
        self, prices: Optional[pd.DataFrame], params: Dict[str, Any]
    ) -> Optional[str]:
        """运行前门禁：校验参数配置自洽（不依赖面板，面板在 allocate 运行时校验）.

        返回 None 表示通过，返回非空字符串表示失败原因。
        """
        problems: List[str] = []
        try:
            cfg = self._parse_config(params)
            if not cfg["score_factors"]:
                problems.append("打分因子 score_factors 为空")
            if cfg["duration_span"] <= 0:
                problems.append("距目标打分全距 duration_span 必须为正")
            for name in ("pool_caps", "pool_topk"):
                if not cfg[name]:
                    problems.append(f"{name} 为空")
                neg = [g for g, v in cfg[name].items() if v < 0]
                if neg:
                    problems.append(f"{name} 分组 {neg} 取值为负")
            if set(cfg["pool_caps"]) != set(cfg["pool_topk"]):
                problems.append("pool_caps 与 pool_topk 的分组键不一致")
            unknown_rank = cfg["rank_factors"] - set(cfg["score_factors"])
            if unknown_rank:
                problems.append(f"名次打分因子 {sorted(unknown_rank)} 不在打分因子内")
        except ValueError as exc:
            problems.append(str(exc))
        splice_code = str(params.get("splice_index_code") or "").strip()
        try:
            splice_until = _parse_splice_until(params.get("splice_until"))
        except ValueError as exc:
            problems.append(str(exc))
            splice_until = None
        if splice_until is not None and not splice_code:
            problems.append("配置了拼接截止日 splice_until 但拼接指数 splice_index_code 为空")
        if splice_code and prices is not None and not prices.empty:
            if splice_code not in {str(c) for c in prices.columns}:
                problems.append(
                    f"拼接指数 {splice_code} 不在资产池（价格矩阵）中，"
                    f"拼接期权重无法落到净值"
                )
        if problems:
            return "[bond_factor_score_index] 参数配置不可行：" + "；".join(problems)
        return None
