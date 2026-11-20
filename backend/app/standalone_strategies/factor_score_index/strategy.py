"""因子打分指数（factor_score_index）：打包独立形态的因子打分 + 市值加权选股策略.

方法：每个调仓生效日取当期因子截面 → 按打分因子缺失剔除候选 → 逐因子
winsorize（均值 ± k 倍标准差截断）后做 min-max 打分（反向因子取
(max-x)/(max-min)，非正值记 0 分）→ 综合得分 = 各因子得分相加 → 行业内
取得分前 M 只 → 全体取得分前 N 只 → 按总市值加权（尾差归市值最大股）。

模式：打包独立形态（``strategy_form="standalone"``）。composition 三层全 None，
选样/打分/赋权全部在本模块内，对外只暴露参数与底层资产；因子截面经数据加载层
按 ``get_extra_panels`` 声明从 factor_panel 集合加载、由引擎 set_panels 注入，
调仓日由注入的面板期日（event_dates）驱动，策略类内不出现具体日期常量。
同一份代码供回测、日常监控、组合子策略三条通道使用。

拼接（splice）
--------------
回测起点早于第一期因子截面、或某期截面滞后超过 ``panel_max_lag_days`` 时，
默认直接报错要求补齐历史截面。配置 ``splice_index_code``（真实指数代码，须在
资产池内且行情到位）后，这些「算不了」的期改为 100% 持有该指数，有可用截面的
期再按因子打分；``splice_until`` 可显式指定强制拼接的截止日（早期因子质量差时
用真实指数替代），留空则按截面可用性自动切换。审计指标 ``selection_source``
区分 ``factor_score`` 与 ``index_splice``，拼接期同样计入调仓次数。

红线：``allocate`` 为纯函数，只消费注入的 prices 与 params（含 ``_as_of`` 与
``_panel_factor_panel``），不读文件、不查库；因子、行业、市值全部来自注入截面，
打分倍数、选取数量、赋权口径、拼接指数全部来自参数；截面缺失、滞后超限、市值
非法时报错，不隐式兜底等权、不跳过标的、不放宽断言（唯一例外是显式配置的
``splice_index_code``：无截面期改持该指数并留痕，未配置时仍按原口径报错）。
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
_DATASET = "equity_quality_growth"

# 打分因子默认键（与 field_mappings.FACTOR_NAME_MAPPING_BY_DATASET 的英文键一致）
_DEFAULT_SCORE_FACTORS: Tuple[str, ...] = (
    "profit_yoy_sq_dn",     # 单季度扣非净利润同比增速（正向）
    "pe_ttm_dn",            # 扣非 PE（反向）
    "dividend_yield_ttm",   # 股息率 TTM（正向）
)
_DEFAULT_REVERSE_FACTORS: Tuple[str, ...] = ("pe_ttm_dn",)

# 赋权口径可选值
_WEIGHT_METHODS: Tuple[str, ...] = ("market_cap", "free_float_cap", "equal")

# 市值加权权重合计容差
_WEIGHT_TOL = 1e-8

# 拼接原因（审计留痕用机器码，中文说明见 _PanelState.detail）
_SPLICE_NO_PANEL = "no_panel_before_as_of"   # 执行日早于最早期截面
_SPLICE_LAG = "lag_over_limit"               # 当期截面滞后超上限
_SPLICE_UNTIL = "splice_until_window"        # splice_until 显式窗口内
_SPLICE_NO_FACTORS = "no_scoring_factors"    # 期日存在但打分因子整列缺失

# 打分/排序内部列名
_SCORE_COL = "_composite_score"
_CODE_COL = "_code"
_INDUSTRY_COL = "_industry"


# ---------------------------------------------------------------------------
# 纯函数：参数解析
# ---------------------------------------------------------------------------


def _parse_factor_list(value: Any, default: Sequence[str]) -> List[str]:
    """把因子参数归一为键名列表（逗号分隔字符串 / 列表 / 空→默认）."""
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple, set)):
        raw: Sequence[Any] = list(value)
    else:
        raw = [p.strip() for p in str(value).split(",") if p.strip()]
    parsed = [str(x).strip() for x in raw if str(x).strip()]
    return parsed or list(default)


def _parse_int(value: Any, default: int, name: str) -> int:
    """把数量参数归一为整数；非法直接报错（不静默回退默认值）."""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"[factor_score_index] 参数 {name}={value!r} 非法，应为整数：{exc}"
        ) from exc


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
            f"[factor_score_index] 参数 splice_until={value!r} 非法，"
            f"应为 YYYY-MM-DD 格式日期：{exc}"
        ) from exc


@dataclass(frozen=True)
class _PanelState:
    """当期因子截面的解析结果：``reason`` 为空表示截面可用.

    截面不可用时不再就地抛错，而是把原因交给调用方裁决：配置了拼接指数就改持
    指数，未配置才按原口径报错。``detail`` 是可直接拼进异常文本的中文说明。
    """

    period_date: Optional[pd.Timestamp] = None
    panel: Optional[pd.DataFrame] = None
    lag: int = 0
    reason: str = ""
    detail: str = ""


# ---------------------------------------------------------------------------
# 纯函数：市值加权
# ---------------------------------------------------------------------------


def cap_weights(market_caps: Dict[str, float]) -> pd.Series:
    """按市值计算一期权重：round(mv/Σmv, 8)，尾差归市值最大股，合计严格为 1.

    市值降序、同值按代码升序排序，保证尾差始终加在同一只（市值最大）股票上。
    单位不影响权重（同口径即可）；等权时对每只传相同市值即得 1/N。

    Raises:
        ValueError: 市值为空或合计非正
        RuntimeError: 归一后权重合计偏离 1 超过 1e-8
    """
    if not market_caps:
        raise ValueError("[factor_score_index] 市值为空，无法计算权重")
    total = sum(market_caps.values())
    if total <= 0:
        raise ValueError("[factor_score_index] 市值合计不是正数，无法计算权重")
    ranked = sorted(market_caps.items(), key=lambda item: (-item[1], item[0]))
    weights = {code: round(mv / total, 8) for code, mv in ranked}
    residual = round(1 - sum(weights.values()), 8)
    largest = ranked[0][0]
    weights[largest] = round(weights[largest] + residual, 8)
    if abs(sum(weights.values()) - 1) > _WEIGHT_TOL:
        raise RuntimeError(
            f"[factor_score_index] 权重合计不为 1：{sum(weights.values())}"
        )
    return pd.Series(weights, dtype=float)


class FactorScoreIndexStrategy(BaseStrategyModel):
    """因子打分指数：截面 winsorize+min-max 打分 → 行业限额 → 前 N → 市值加权."""

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
            strategy_type="factor_score_index",
            display_name="因子打分指数",
            description=(
                "每个调仓生效日取当期因子截面，逐因子 winsorize 后 min-max 打分"
                "（反向因子取 (max-x)/(max-min)、非正值记 0），综合得分相加 →"
                "行业内前 M → 全体前 N → 按总市值加权（尾差归市值最大股）。"
                "选样/打分/赋权全部在策略包内，前端只需配置打分因子、选取数量与赋权口径"
            ),
            composition={
                "selector": None,
                "allocator": "factor_score_index",
                "controller": None,
                "schedule": {"rebalance_freq": "daily", "execution_delay": 0},
            },
            # 市值加权在包内归一到合计恰为 1，Pipeline 不再做杠杆缩放
            internal_leverage=True,
            params=[
                # ━━━ 算法核心（core） ━━━
                ParamSchema(
                    name="score_factors", label="打分因子", type="text",
                    default=",".join(_DEFAULT_SCORE_FACTORS),
                    description=(
                        "参与综合打分的因子键（逗号分隔，键名见 factor_panel 导入映射）。"
                        "默认三因子：单季度扣非净利润同比增速、扣非 PE、股息率 TTM"
                    ),
                ),
                ParamSchema(
                    name="reverse_factors", label="反向因子", type="text",
                    default=",".join(_DEFAULT_REVERSE_FACTORS),
                    description=(
                        "值越大得分越低的因子键（逗号分隔），按 (max-x)/(max-min) 打分。"
                        "默认扣非 PE；留空表示全部因子正向"
                    ),
                ),
                ParamSchema(
                    name="select_count", label="选取数量", type="number", default=50,
                    min_value=1, max_value=1000, step=1,
                    description="综合得分排名后入选的标的只数（指数成分数量）",
                ),
                ParamSchema(
                    name="industry_top_n", label="行业内限额", type="number", default=5,
                    min_value=0, max_value=100, step=1,
                    description="每个行业按综合得分最多入选的只数；0 = 不做行业限额",
                ),
                ParamSchema(
                    name="weight_method", label="赋权方式", type="select", default="market_cap",
                    options=[
                        ("market_cap", "总市值加权"),
                        ("free_float_cap", "自由流通市值加权"),
                        ("equal", "等权"),
                    ],
                    description="入选标的的赋权口径；总市值加权为指数默认",
                ),
                ParamSchema(
                    name="splice_index_code", label="拼接指数代码", type="text",
                    default="512190.SH",
                    description=(
                        "无可用因子截面的区间改为 100% 持有该指数（代码须在资产池内、"
                        "行情已导入）。默认 512190.SH（凤凰ETF），因子截面未覆盖的"
                        "早期区间由它补足；留空 = 不拼接，缺截面时报错要求补齐历史截面"
                    ),
                ),
                # ━━━ 技术细节（advanced） ━━━
                ParamSchema(
                    name="winsorize_k", label="极值处理倍数", type="number", default=2.0,
                    min_value=0.0, max_value=10.0, step=0.5,
                    description="打分前按 均值 ± k×标准差 截断极值（k=0 表示不截断）",
                    group="advanced",
                ),
                ParamSchema(
                    name="reverse_zero_floor", label="反向因子非正记零", type="boolean", default=True,
                    description="反向因子截断后值 ≤ 0 时记 0 分（扣非 PE 口径）",
                    group="advanced",
                ),
                ParamSchema(
                    name="screen_positive_factors", label="正值筛选因子", type="text", default="",
                    description=(
                        "额外要求取值 > 0 的因子键（逗号分隔）；留空表示只按打分因子"
                        "缺失剔除候选"
                    ),
                    group="advanced",
                ),
                ParamSchema(
                    name="panel_max_lag_days", label="截面最大滞后交易日", type="number", default=5,
                    min_value=0, max_value=120, step=1,
                    description=(
                        "当期因子截面相对执行日允许的最大滞后交易日数，超过即报错"
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
        """声明 factor_panel 读 equity_quality_growth（A股质量成长因子季度截面）.

        factor_panel 被股票与债券两个数据集共用，不声明就会把另一域的同期日行
        并进本策略的截面：打分归一化的样本被污染，行业内选取也会把另一域的券
        当成候选且不报错。
        """
        return {_PANEL_NAME: _DATASET}

    def get_data_feed_options(self) -> Dict[str, Any]:
        """声明数据源口径：加载 factor_panel、面板期日驱动调仓.

        ``panel_event_dates=True`` 使 Pipeline 把注入的面板期日作为 event_dates，
        调仓日 = 生效日（信号日 = 执行日，execution_delay=0）。
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

        面板存在性、当期截面、市值有效性在 allocate 运行时校验（契约门禁
        执行时面板尚未注入，见 runner._gate_prices）；此处只声明拿到配置与
        价格矩阵即可判定的项。不声明 min_assets / min_history_days /
        require_continuous：底层资产可自由配置、任意区间与日历都能跑。
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
        """一次调仓的全部计算：取当期截面 → 打分 → 行业限额 → 前 N → 市值加权.

        拼接期（无可用截面，或处于 ``splice_until`` 之前）不取截面，直接返回
        100% 拼接指数权重；未配置拼接指数时保持原报错口径。
        """
        if prices is None or prices.empty:
            raise ValueError("[factor_score_index] 价格矩阵为空，无法计算权重")
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
                f"[factor_score_index] {state.detail}。请补齐该期截面，或配置"
                f" splice_index_code 关联真实指数，由指数行情补足无截面区间"
            )

        period_date, panel, lag = state.period_date, state.panel, state.lag
        cfg = self._parse_config(params)

        # 期日存在但打分因子整列缺失：与「无期日」同属算不了，
        # 配置了拼接指数就改持指数，由指数行情补足该区间。
        if splice_code and self._is_constituent_snapshot(panel, cfg):
            return self._splice_weights(
                pool, splice_code, as_of, _SPLICE_NO_FACTORS, state
            )

        screened, dropped_screen = self._screen(panel, cfg)
        if screened.empty:
            raise ValueError(
                f"[factor_score_index] {period_date.date()} 当期截面经初筛后无候选"
                f"（打分因子 {cfg['score_factors']} 全部缺失）。请检查因子截面导入"
            )
        scored = self._score(screened, cfg)
        capped, dropped_industry = self._industry_cap(scored, cfg)
        selected = self._select_top(capped, cfg)
        if not selected:
            raise ValueError(
                f"[factor_score_index] {period_date.date()} 未选出任何标的"
                f"（select_count={cfg['select_count']}）。请检查截面候选数量"
            )
        self._assert_in_pool(selected, pool, period_date)
        weights = self._weights(scored, selected, cfg, period_date)

        self._audit({
            "panel_as_of": str(period_date.date()),
            "data_date": self._period_data_date(panel),
            "lag_trading_days": lag,
            "candidate_count": int(len(panel)),
            "screened_out": int(dropped_screen),
            "industry_cap_dropped": int(dropped_industry),
            "selected_count": len(selected),
            "weight_method": cfg["weight_method"],
            "max_weight": float(weights.max()),
            "top5_weight_sum": float(weights.nlargest(5).sum()),
            "selection_source": "factor_score",
        })
        return weights.reindex(pool).fillna(0.0)

    # ------------------------------------------------------------------
    # 分步实现（每步可单测）
    # ------------------------------------------------------------------

    def _parse_config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """把 params 归一为本期计算所需配置（一次性解析，避免散落在各步）."""
        return {
            "score_factors": _parse_factor_list(params.get("score_factors"), _DEFAULT_SCORE_FACTORS),
            "reverse_factors": set(_parse_factor_list(params.get("reverse_factors"), _DEFAULT_REVERSE_FACTORS)),
            "positive_factors": set(_parse_factor_list(params.get("screen_positive_factors"), ())),
            "winsorize_k": float(params.get("winsorize_k", 2.0) or 0.0),
            "reverse_zero_floor": bool(params.get("reverse_zero_floor", True)),
            "industry_top_n": _parse_int(params.get("industry_top_n"), 5, "industry_top_n"),
            "select_count": _parse_int(params.get("select_count"), 50, "select_count"),
            "weight_method": str(params.get("weight_method", "market_cap") or "market_cap"),
            "panel_max_lag_days": _parse_int(params.get("panel_max_lag_days"), 5, "panel_max_lag_days"),
        }

    def _try_resolve_panel(
        self, prices: pd.DataFrame, params: Dict[str, Any]
    ) -> _PanelState:
        """尝试取执行日 ``_as_of`` 当期（≤ as_of 最近一期）因子截面.

        与直接报错的差别：截面「不可用」不再就地抛错，而是把原因带回由调用方
        裁决——配置了拼接指数就改持指数，未配置才按原口径报错。面板根本未注入
        属于管道故障，仍直接抛错：拼接只补历史缺失，不掩盖数据加载故障。

        Raises:
            ValueError: 面板未注入 / 未注入执行日 / 滞后上限参数非法
        """
        panels_raw = params.get(f"_panel_{_PANEL_NAME}")
        if not panels_raw:
            raise ValueError(
                "[factor_score_index] 未注入 factor_panel 截面。请确认已导入因子截面数据，"
                "且策略经 get_extra_panels 声明的面板加载通道生效"
            )
        as_of = params.get("_as_of")
        if as_of is None:
            raise ValueError("[factor_score_index] 未注入执行日 _as_of，无法定位当期截面")
        as_of = pd.Timestamp(as_of)
        panels = {pd.Timestamp(k): v for k, v in panels_raw.items()}
        eligible = sorted(d for d in panels if d <= as_of)
        if not eligible:
            earliest = min(panels)
            return _PanelState(
                reason=_SPLICE_NO_PANEL,
                detail=(
                    f"执行日 {as_of.date()} 之前无可用因子截面"
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
                    f"当期因子截面滞后 {lag} 个交易日（期日 {period_date.date()}，"
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
                "[factor_score_index] 配置了拼接截止日 splice_until 但拼接指数"
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
            拼接原因机器码；空串表示本期按因子打分
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
                f"[factor_score_index] 拼接指数 {code!r} 不在资产池（价格矩阵）中，"
                f"权重无法落到净值。请把该代码加入 asset_codes 并导入其行情，"
                f"或清空 splice_index_code"
            )
        weights = pd.Series({code: 1.0}, dtype=float).reindex(list(pool)).fillna(0.0)
        self._audit({
            "panel_as_of": str(state.period_date.date()) if state.period_date is not None else "",
            "data_date": "",
            "lag_trading_days": int(state.lag),
            "candidate_count": 0,
            "screened_out": 0,
            "industry_cap_dropped": 0,
            "selected_count": 1,
            "weight_method": "splice_index",
            "max_weight": 1.0,
            "top5_weight_sum": 1.0,
            "selection_source": "index_splice",
            "splice_index_code": code,
            "splice_reason": reason,
            "as_of": str(as_of.date()),
        })
        _log.info(
            "[factor_score_index] %s 拼接期（%s），100%% 持有 %s",
            as_of.date(), reason, code,
        )
        return weights

    @staticmethod
    def _is_constituent_snapshot(panel: pd.DataFrame, cfg: Dict[str, Any]) -> bool:
        """截面是否无打分因子（缺列或整列缺失），此时无法打分只能拼接.

        不能只看列是否存在：data_feed 把整张面板所有期 union 后展平因子，
        早期期无因子但列仍在（值全 NaN），只看列会把无因子期误判为有因子截面，
        初筛后为空再报错。
        """
        for f in cfg["score_factors"]:
            if f not in panel.columns:
                return True
            if pd.to_numeric(panel[f], errors="coerce").notna().sum() == 0:
                return True
        return False

    def _screen(
        self, panel: pd.DataFrame, cfg: Dict[str, Any]
    ) -> Tuple[pd.DataFrame, int]:
        """初筛：打分因子转数值并剔除任一缺失的候选，可选叠加正值筛选.

        Returns:
            (初筛后截面 index=code, 剔除行数)
        """
        df = panel.copy()
        df.index = df.index.astype(str)
        score_factors = cfg["score_factors"]
        missing = [f for f in score_factors if f not in df.columns]
        if missing:
            raise ValueError(
                f"[factor_score_index] 当期截面缺少打分因子列 {missing}。"
                f"已有列：{list(df.columns)}。请检查因子导入映射"
            )
        n0 = len(df)
        for f in score_factors:
            df[f] = pd.to_numeric(df[f], errors="coerce")
        df = df.dropna(subset=list(score_factors))
        positive = [f for f in cfg["positive_factors"] if f in df.columns]
        if positive:
            for f in positive:
                df[f] = pd.to_numeric(df[f], errors="coerce")
            df = df[(df[positive] > 0).all(axis=1)]
        return df, n0 - len(df)

    def _score(self, df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
        """逐因子 winsorize + min-max 打分，综合得分 = 各因子得分相加.

        标准差 ddof=1；极值取自截断后列；分母为 0 记 0 分；反向因子按
        (max-x)/(max-min)，``reverse_zero_floor`` 时截断后 ≤0 记 0 分。
        """
        out = df.copy()
        k = cfg["winsorize_k"]
        score_cols: List[str] = []
        for f in cfg["score_factors"]:
            col = out[f]
            if k > 0:
                mean, std = col.mean(), col.std()
                clipped = col.clip(lower=mean - k * std, upper=mean + k * std)
            else:
                clipped = col
            fmax, fmin = clipped.max(), clipped.min()
            denom = fmax - fmin
            sc = f"_score_{f}"
            if denom == 0 or pd.isna(denom):
                out[sc] = 0.0
            elif f in cfg["reverse_factors"]:
                base = (fmax - clipped) / denom
                out[sc] = np.where(clipped > 0, base, 0.0) if cfg["reverse_zero_floor"] else base
            else:
                out[sc] = (clipped - fmin) / denom
            score_cols.append(sc)
        out[_SCORE_COL] = out[score_cols].sum(axis=1)
        return out

    def _industry_cap(
        self, df: pd.DataFrame, cfg: Dict[str, Any]
    ) -> Tuple[pd.DataFrame, int]:
        """行业内按综合得分取前 M（industry_top_n≤0 跳过）；同分按代码升序，结果确定."""
        top_n = cfg["industry_top_n"]
        if top_n <= 0:
            return df, 0
        if "industry" not in df.columns:
            raise ValueError("[factor_score_index] 当期截面缺少 industry 列，无法做行业内限额")
        n0 = len(df)
        tmp = df.copy()
        tmp[_CODE_COL] = tmp.index.astype(str)
        tmp[_INDUSTRY_COL] = tmp["industry"].astype(str)
        ranked = tmp.sort_values(
            by=[_INDUSTRY_COL, _SCORE_COL, _CODE_COL],
            ascending=[True, False, True],
            kind="mergesort",
        )
        capped = ranked.groupby(_INDUSTRY_COL, sort=False).head(top_n)
        return capped.drop(columns=[_CODE_COL, _INDUSTRY_COL]), n0 - len(capped)

    def _select_top(self, df: pd.DataFrame, cfg: Dict[str, Any]) -> List[str]:
        """全体按综合得分取前 N（同分按代码升序）；返回选中代码列表."""
        n = cfg["select_count"]
        if n <= 0:
            raise ValueError(f"[factor_score_index] select_count={n} 非法，必须为正整数")
        tmp = df.copy()
        tmp[_CODE_COL] = tmp.index.astype(str)
        ranked = tmp.sort_values(
            by=[_SCORE_COL, _CODE_COL], ascending=[False, True], kind="mergesort"
        )
        return list(ranked[_CODE_COL].head(n))

    def _assert_in_pool(
        self, selected: Sequence[str], pool: Sequence[str], period_date: pd.Timestamp
    ) -> None:
        """选中标的必须在价格矩阵（资产池）内，否则无法计算净值——报错不静默剔除."""
        pool_set = set(pool)
        missing = [c for c in selected if c not in pool_set]
        if missing:
            raise ValueError(
                f"[factor_score_index] {period_date.date()} 选中标的不在资产池（价格矩阵）中："
                f"{_truncate_list(missing)}。资产池须覆盖因子截面的可选全集；"
                f"请把这些代码加入 asset_codes 并补足行情"
            )

    def _weights(
        self,
        df: pd.DataFrame,
        selected: Sequence[str],
        cfg: Dict[str, Any],
        period_date: pd.Timestamp,
    ) -> pd.Series:
        """按赋权口径计算入选标的权重（市值加权合计恰为 1，尾差归市值最大股）."""
        method = cfg["weight_method"]
        if method not in _WEIGHT_METHODS:
            raise ValueError(f"[factor_score_index] weight_method={method!r} 不在 {_WEIGHT_METHODS}")
        if method == "equal":
            return cap_weights({code: 1.0 for code in selected})
        col = "free_float_mv" if method == "free_float_cap" else "total_mv"
        return cap_weights(self._extract_caps(df, selected, col, period_date))

    def _extract_caps(
        self,
        df: pd.DataFrame,
        selected: Sequence[str],
        col: str,
        period_date: pd.Timestamp,
    ) -> Dict[str, float]:
        """取入选标的的市值列；任一缺失或非正即报错（不静默改等权）."""
        if col not in df.columns:
            raise ValueError(
                f"[factor_score_index] 当期截面缺少 {col} 列，无法按 {col} 加权。"
                f"请改用其他赋权方式或补足该字段"
            )
        caps: Dict[str, float] = {}
        invalid: List[str] = []
        for code in selected:
            val = pd.to_numeric(df.at[code, col], errors="coerce") if code in df.index else np.nan
            if pd.isna(val) or float(val) <= 0:
                invalid.append(code)
            else:
                caps[code] = float(val)
        if invalid:
            raise ValueError(
                f"[factor_score_index] {period_date.date()} 以下选中标的缺少有效 {col}（须 >0）："
                f"{_truncate_list(invalid)}。请补足市值字段或改用等权"
            )
        return caps

    def _period_data_date(self, panel: pd.DataFrame) -> str:
        """当期截面的财报日（data_date）留痕：唯一值直接返回，多值返回区间摘要."""
        if "data_date" not in panel.columns:
            return ""
        vals = sorted({
            str(v) for v in panel["data_date"].tolist()
            if v is not None and str(v) not in ("nan", "None", "")
        })
        if not vals:
            return ""
        if len(vals) == 1:
            return vals[0]
        return f"{vals[0]}~{vals[-1]}（{len(vals)} 个财报日）"

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
        """暴露当期截面、滞后、初筛/行业限额淘汰、选取数与权重集中度（前端监控页指标区）."""
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
        score_factors = _parse_factor_list(params.get("score_factors"), _DEFAULT_SCORE_FACTORS)
        if not score_factors:
            problems.append("打分因子 score_factors 为空")
        reverse = set(_parse_factor_list(params.get("reverse_factors"), _DEFAULT_REVERSE_FACTORS))
        unknown_reverse = reverse - set(score_factors)
        if unknown_reverse:
            problems.append(f"反向因子 {sorted(unknown_reverse)} 不在打分因子内")
        try:
            if _parse_int(params.get("select_count"), 50, "select_count") <= 0:
                problems.append("选取数量 select_count 必须为正整数")
            if _parse_int(params.get("industry_top_n"), 5, "industry_top_n") < 0:
                problems.append("行业限额 industry_top_n 不能为负")
            if _parse_int(params.get("panel_max_lag_days"), 5, "panel_max_lag_days") < 0:
                problems.append("截面最大滞后 panel_max_lag_days 不能为负")
        except ValueError as exc:
            problems.append(str(exc))
        weight_method = str(params.get("weight_method", "market_cap") or "market_cap")
        if weight_method not in _WEIGHT_METHODS:
            problems.append(f"赋权方式 weight_method={weight_method!r} 不在 {_WEIGHT_METHODS}")
        try:
            if float(params.get("winsorize_k", 2.0)) < 0:
                problems.append("极值倍数 winsorize_k 不能为负")
        except (TypeError, ValueError):
            problems.append(f"极值倍数 winsorize_k={params.get('winsorize_k')!r} 非法")
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
            return "[factor_score_index] 参数配置不可行：" + "；".join(problems)
        return None
