# -*- coding: utf-8 -*-
"""策略数据契约 —— 声明结构与校验纯函数（引擎层，禁止 IO）.

独立策略（``strategy_form="standalone"``）自带数据口径：资产池由前端自由配置，
历史长度、日历口径、分组划分因策略而异。契约由策略类经
``BaseStrategyModel.get_data_contract()`` 声明，运行前由 :mod:`app.backtesting.runner`
与 services 层门禁调用本模块校验；不满足即抛 :class:`DataContractError` 拒绝运行，
不降级、不跳过资产、不放宽断言。

本模块位于引擎层，受 ``tests/test_backtesting_boundary.py`` 的向上依赖守卫约束
（禁止 import app.services / app.monitor / app.api / app.portfolio），
故全部函数为纯函数：需要库数据（``assets`` 文档的 asset_class 等）时，
由调用方以 ``asset_meta`` 参数传入，本模块不查库。

校验分三段，对应三个挂载时机：

======================  =========================================  ================
函数                    校验内容                                    可用时机
======================  =========================================  ================
:func:`validate_static` 资产数量、分组划分、资产大类                拿到配置即可
:func:`validate_with_prices` 历史长度、日历一致性、价格异常         拿到价格矩阵后
:func:`validate_custom` 策略包内自定义检查                          拿到策略实例后
======================  =========================================  ================

价格矩阵来源要求：``validate_with_prices`` 的 ``prices`` 应传入
**未经数据源层清洗的原始矩阵**（``DataFeed.strategy_prices``，仅置 inf→NaN），
而不是 ``DataFeed.prices``。后者经 ``data_feed.sanitize_prices`` 处理，
已对缺日做 ffill、并把单日涨跌超阈值的点用前一日价格填充，
在其上校验 ``require_continuous`` 与 ``max_single_day_jump`` 会恒通过，失去意义。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

__all__ = [
    "CALENDAR_SOURCES",
    "GroupSpec",
    "DataContract",
    "ContractViolation",
    "ContractReport",
    "DataContractError",
    "parse_asset_codes",
    "read_class_panel_declarations",
    "with_panel_declarations",
    "validate_static",
    "validate_with_prices",
    "validate_custom",
    "merge_reports",
]

# 日历口径可选值：prices=价格矩阵索引（系统策略与回测轴，默认）；
# trade_dates=Mongo 交易日历集合（仅研究员策略 sharpe_18/hybrid_12 语义）
CALENDAR_SOURCES: Tuple[str, ...] = ("trade_dates", "prices")

# 违规明细最多列举条数，避免异常文本过长淹没关键信息
_MAX_LISTED = 10

# 分组参数值的分隔符（前端 text 控件常用逗号，也兼容顿号/分号/空白）
_CODE_SEPARATORS = ("，", ",", "、", ";", "；", "|", "\n", "\t", " ")


# ---------------------------------------------------------------------------
# 声明结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupSpec:
    """单个资产分组的契约规格.

    Attributes:
        required: 该分组参数是否必须非空。
        cover_pool: 是否参与「全池覆盖」检查。所有标记为 True 的分组，
            其资产并集必须等于策略资产池；池内有资产未归入任何一组即报错。
        min_size: 组内最小资产只数（0 表示不限）。
    """

    required: bool = True
    cover_pool: bool = False
    min_size: int = 0


@dataclass(frozen=True)
class DataContract:
    """策略数据契约声明.

    全部字段缺省即不校验，:attr:`is_empty` 为 True 时门禁快速通过，
    保证未声明契约的存量策略行为完全不变。
    """

    # ---- 静态面（拿到配置即可校验）----
    min_assets: int = 0
    group_params: Dict[str, GroupSpec] = field(default_factory=dict)
    expected_asset_class: Dict[str, str] = field(default_factory=dict)

    # ---- 价格面（拿到价格矩阵才能校验）----
    min_history_days: int = 0
    require_continuous: bool = False
    max_single_day_jump: Optional[float] = None
    min_price: float = 0.0

    # ---- 口径声明与自定义检查 ----
    # 系统策略与回测轴恒用价格日历（资产价格日期并集）；trade_dates 仅研究员
    # 策略 sharpe_18/hybrid_12 语义，故全缺省契约声明 prices
    calendar: str = "prices"
    custom_checks: Tuple[str, ...] = ()

    # ---- 面板声明（契约单源，见 with_panel_declarations）----
    # panels 与 datasets 是新增字段，全部带默认值，旧的 DataContract(...) 位置参数
    # 与关键字参数写法均不受影响（backward compatible）。
    # 面板此前只能由策略类的 get_extra_panels()/get_panel_datasets() 声明，
    # 现在可由契约声明，读取侧（data_feed）契约优先、类方法回退。
    panels: Dict[str, str] = field(default_factory=dict)
    datasets: Tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """是否为全缺省契约（无需任何校验）."""
        return (
            self.min_assets <= 0
            and self.min_history_days <= 0
            and not self.require_continuous
            and self.max_single_day_jump is None
            and self.min_price <= 0.0
            and not self.group_params
            and not self.expected_asset_class
            and not self.custom_checks
            and self.calendar == "prices"
            and not self.panels
            and not self.datasets
        )


# ---------------------------------------------------------------------------
# 面板声明单源
# ---------------------------------------------------------------------------


def read_class_panel_declarations(cls: Any) -> Tuple[List[str], Dict[str, str]]:
    """读取策略类静态声明的面板（不实例化）.

    Returns:
        (面板名列表, {面板名: dataset})；类未声明或反射失败时返回 ([], {})。

    反射失败只降级为空声明：面板缺失会在加载层报错，不会静默串数据。
    """
    out_names: List[str] = []
    out_datasets: Dict[str, str] = {}
    try:
        panels_getter = getattr(cls, "get_extra_panels", None)
        if callable(panels_getter):
            out_names = [str(n) for n in (panels_getter() or [])]
        datasets_getter = getattr(cls, "get_panel_datasets", None)
        if callable(datasets_getter):
            out_datasets = {str(k): str(v) for k, v in dict(datasets_getter() or {}).items()}
    except Exception:  # noqa: BLE001 —— 声明读不到不阻断加载，后续按空声明处理
        return [], {}
    return out_names, out_datasets


def with_panel_declarations(contract: DataContract, cls: Any = None) -> DataContract:
    """把类方法声明的面板补齐进契约（契约已声明则原样返回）.

    为什么需要补齐而不是二选一：
        6 个 standalone 策略的面板声明写在类方法里（历史实现），契约字段是本期
        新增。读取侧必须只有一个取值入口，否则「契约」与「类方法」两份声明迟早
        不一致。本函数把两者合流：
        - 契约已声明 ``panels`` → 以契约为准（**不回读类方法**，避免双源）；
        - 契约未声明 → 用类方法声明补齐，并同步写 ``datasets``；
        - 类方法也没声明 → 原样返回（空契约行为不变）。

    返回新对象（frozen dataclass 用 ``replace``），不修改入参。
    """
    if contract is None:
        return contract
    if contract.panels:
        return contract
    class_panels, class_datasets = read_class_panel_declarations(cls)
    if not class_panels and not class_datasets:
        return contract
    panels = {name: class_datasets.get(name, "") for name in class_panels if name}
    datasets = tuple(sorted({v for v in class_datasets.values() if v}))
    return replace(contract, panels=panels, datasets=datasets)


# ---------------------------------------------------------------------------
# 校验结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractViolation:
    """单条契约违规."""

    level: str  # "error"（阻断运行）/ "warning"（仅提示）
    code: str  # 机器可读码，如 "history_too_short"
    message: str  # 含实际值的人类可读描述
    hint: str = ""  # 修复建议
    asset: Optional[str] = None  # 涉及的资产代码（如有）

    def format(self) -> str:
        prefix = f"[{self.asset}] " if self.asset else ""
        tail = f"（修复建议：{self.hint}）" if self.hint else ""
        return f"{prefix}{self.message}{tail}"


@dataclass
class ContractReport:
    """契约校验结果。``passed`` 由 error 级违规决定，warning 不阻断。"""

    violations: List[ContractViolation] = field(default_factory=list)

    @property
    def errors(self) -> List[ContractViolation]:
        return [v for v in self.violations if v.level == "error"]

    @property
    def warnings(self) -> List[ContractViolation]:
        return [v for v in self.violations if v.level == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def add(
        self,
        code: str,
        message: str,
        hint: str = "",
        asset: Optional[str] = None,
        level: str = "error",
    ) -> None:
        self.violations.append(
            ContractViolation(level=level, code=code, message=message, hint=hint, asset=asset)
        )

    def raise_if_failed(self, strategy_label: str) -> None:
        """校验未通过时抛 DataContractError（文本含策略标识、实际值、修复建议）."""
        if self.passed:
            return
        raise DataContractError(strategy_label, self.violations)


def merge_reports(*reports: Optional[ContractReport]) -> ContractReport:
    """合并多段校验结果（静态 + 价格 + 自定义）."""
    merged = ContractReport()
    for r in reports:
        if r is not None:
            merged.violations.extend(r.violations)
    return merged


class DataContractError(ValueError):
    """策略数据契约校验失败.

    继承 ValueError 以复用 API 层既有的 400 转换惯例
    （``except ValueError as exc: raise HTTPException(400, str(exc))``），
    使缺口清单能原样呈现到前端，而不是变成 500。
    """

    def __init__(self, strategy_label: str, violations: Sequence[ContractViolation]):
        self.strategy_label = strategy_label
        self.violations = list(violations)
        errors = [v for v in self.violations if v.level == "error"]
        warnings = [v for v in self.violations if v.level == "warning"]
        lines = [
            f"策略 {strategy_label} 数据契约校验未通过（{len(errors)} 项）：",
            *(f"  - {v.format()}" for v in errors),
        ]
        if warnings:
            lines.append(f"另有 {len(warnings)} 项提示：")
            lines.extend(f"  - {v.format()}" for v in warnings)
        super().__init__("\n".join(lines))


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def parse_asset_codes(value: Any) -> List[str]:
    """把分组参数值归一为资产代码列表.

    兼容前端 text 控件的逗号分隔字符串、顿号/分号/空白分隔、
    以及已是 list/tuple/set 的形态；空值返回空列表。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    for sep in _CODE_SEPARATORS:
        text = text.replace(sep, ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def _resolve_groups(
    contract: DataContract, strategy_params: Dict[str, Any]
) -> Dict[str, List[str]]:
    """解析契约声明的各分组参数为 {分组参数名: [资产代码]}."""
    params = strategy_params or {}
    return {name: parse_asset_codes(params.get(name)) for name in contract.group_params}


def _truncate(items: Iterable[str]) -> str:
    """列举前 _MAX_LISTED 条，超出部分以计数收尾。"""
    listed = list(items)
    if len(listed) <= _MAX_LISTED:
        return "、".join(listed)
    return "、".join(listed[:_MAX_LISTED]) + f" 等 {len(listed)} 项"


def _price_columns(prices: pd.DataFrame, asset_codes: Sequence[str]) -> List[Any]:
    """取资产池在价格矩阵中实际存在的列（保留矩阵原始列类型）."""
    if prices is None or prices.empty:
        return []
    col_map = {str(c): c for c in prices.columns}
    return [col_map[code] for code in asset_codes if code in col_map]


# ---------------------------------------------------------------------------
# 校验：静态面
# ---------------------------------------------------------------------------


def validate_static(
    contract: Optional[DataContract],
    asset_codes: Sequence[str],
    strategy_params: Optional[Dict[str, Any]] = None,
    asset_meta: Optional[Dict[str, Dict[str, Any]]] = None,
) -> ContractReport:
    """校验配置面契约：资产数量、分组划分、资产大类、日历口径声明.

    Args:
        contract: 策略声明的契约；None 或空契约直接通过。
        asset_codes: 策略资产池（前端配置的 asset_codes）。
        strategy_params: 扁平化策略参数（分组参数从中读取）。
        asset_meta: 可选的 ``{code: {"asset_class": ..., "instrument_type": ...}}``，
            由 services 层查库组装。为 None 时跳过 expected_asset_class 校验
            （引擎层不查库）。
    """
    report = ContractReport()
    if contract is None or contract.is_empty:
        return report

    params = strategy_params or {}
    codes = [str(c).strip() for c in (asset_codes or []) if str(c).strip()]

    # ---- 日历口径声明合法性（calendar_source 模型参数已停用，系统恒用价格日历）----
    if contract.calendar not in CALENDAR_SOURCES:
        report.add(
            code="unknown_calendar",
            message=f"契约声明了未知日历口径 {contract.calendar!r}",
            hint=f"可选值：{' / '.join(CALENDAR_SOURCES)}",
        )

    # ---- 资产池规模 ----
    if contract.min_assets > 0 and len(codes) < contract.min_assets:
        report.add(
            code="too_few_assets",
            message=(
                f"资产池只有 {len(codes)} 只，少于策略要求的最小 {contract.min_assets} 只"
                if codes
                else f"资产池为空，策略要求至少 {contract.min_assets} 只资产"
            ),
            hint="在策略建模页的资产多选框中补足资产池",
        )
    if not codes:
        # 池为空时后续分组/大类校验无意义，直接返回
        return report

    groups = _resolve_groups(contract, params)

    # ---- 分组划分 ----
    for name, spec in contract.group_params.items():
        members = groups.get(name) or []
        if spec.required and not members:
            report.add(
                code="group_missing",
                message=f"分组参数 {name!r} 为空，该策略要求此分组必填",
                hint=f"在策略参数区填写 {name}（资产代码，逗号分隔）",
            )
            continue
        if spec.min_size > 0 and len(members) < spec.min_size:
            report.add(
                code="group_too_small",
                message=(
                    f"分组 {name!r} 只有 {len(members)} 只资产"
                    f"（{_truncate(members)}），少于要求的最小 {spec.min_size} 只"
                ),
                hint=f"在策略参数区补足 {name}",
            )

    covered = [name for name, spec in contract.group_params.items() if spec.cover_pool]
    if covered:
        union: List[str] = []
        for name in covered:
            union.extend(groups.get(name) or [])
        union_set = set(union)
        pool_set = set(codes)
        ungrouped = sorted(pool_set - union_set)
        if ungrouped:
            report.add(
                code="pool_not_covered",
                message=(
                    f"资产池有 {len(ungrouped)} 只未归入任何分组"
                    f"（分组参数：{'、'.join(covered)}）：{_truncate(ungrouped)}"
                ),
                hint="把未归组资产补入对应分组参数，或从资产池中移除",
            )
        unknown = sorted(union_set - pool_set)
        if unknown:
            report.add(
                code="group_member_not_in_pool",
                message=(
                    f"分组参数中出现 {len(unknown)} 只不在资产池内的资产："
                    f"{_truncate(unknown)}"
                ),
                hint="分组参数与资产池必须一致；把该资产加入资产池或从分组参数中删除",
            )

    # ---- 资产大类（需 services 层传入 asset_meta）----
    if asset_meta is not None and contract.expected_asset_class:
        for name, expected in contract.expected_asset_class.items():
            for code in groups.get(name) or []:
                meta = asset_meta.get(code)
                if meta is None:
                    report.add(
                        code="asset_not_found",
                        message=f"资产 {code!r} 不在 assets 集合中（分组 {name}）",
                        hint="先在资产管理页创建该资产，或修正分组参数中的代码",
                        asset=code,
                    )
                    continue
                actual = str(meta.get("asset_class") or "").strip()
                if actual and actual != expected:
                    report.add(
                        code="asset_class_mismatch",
                        message=(
                            f"资产大类为 {actual!r}，但分组 {name} 要求 {expected!r}"
                        ),
                        hint=(
                            "批量导入按中文名关键词推断资产大类，可能出错；"
                            "到资产管理页编辑该资产的「资产大类」字段"
                        ),
                        asset=code,
                    )
    return report


# ---------------------------------------------------------------------------
# 校验：价格面
# ---------------------------------------------------------------------------


def validate_with_prices(
    contract: Optional[DataContract],
    asset_codes: Sequence[str],
    strategy_params: Optional[Dict[str, Any]] = None,
    prices: Optional[pd.DataFrame] = None,
) -> ContractReport:
    """校验数据面契约：历史长度、日历一致性、价格异常.

    Args:
        contract: 策略声明的契约；None 或空契约直接通过。
        asset_codes: 策略资产池。
        strategy_params: 扁平化策略参数（当前仅用于错误提示，保留扩展位）。
        prices: 未经清洗的原始价格矩阵（index=日期，columns=资产代码）。
            回测侧应传 ``DataFeed.strategy_prices``，见模块 docstring。
    """
    report = ContractReport()
    if contract is None or contract.is_empty:
        return report

    codes = [str(c).strip() for c in (asset_codes or []) if str(c).strip()]
    needs_prices = (
        contract.min_history_days > 0
        or contract.require_continuous
        or contract.max_single_day_jump is not None
        or contract.min_price > 0.0
    )
    if not needs_prices:
        return report

    if prices is None or prices.empty:
        report.add(
            code="prices_empty",
            message="价格矩阵为空，无法执行数据契约校验",
            hint=(
                "确认资产池内各资产在 asset_prices 中有行情，"
                "且回测/监控区间与数据日期范围有交集"
            ),
        )
        return report

    cols = _price_columns(prices, codes)
    missing_cols = [c for c in codes if c not in {str(x) for x in cols}]
    if missing_cols:
        report.add(
            code="prices_missing_assets",
            message=(
                f"资产池有 {len(missing_cols)} 只在价格矩阵中无数据列："
                f"{_truncate(missing_cols)}"
            ),
            hint="到资产行情页为该资产导入行情，或从资产池中移除",
        )
    if not cols:
        return report

    sub = prices[cols]

    # ---- 历史长度 ----
    if contract.min_history_days > 0:
        counts = sub.notna().sum()
        for col in cols:
            n = int(counts[col])
            if n < contract.min_history_days:
                first_valid = sub[col].first_valid_index()
                span = (
                    f"，首个有效日 {pd.Timestamp(first_valid).date()}"
                    if first_valid is not None
                    else "，无任何有效价格"
                )
                report.add(
                    code="history_too_short",
                    message=(
                        f"有效价格 {n} 条，少于策略要求的最小 "
                        f"{contract.min_history_days} 条{span}"
                    ),
                    hint=(
                        "补足该资产历史行情（含上市前替代序列），"
                        "或调低模型参数中的最小历史天数"
                    ),
                    asset=str(col),
                )

    # ---- 日历一致性 ----
    if contract.require_continuous:
        valid = sub.notna()
        inconsistent = valid.any(axis=1) & ~valid.all(axis=1)
        bad_dates = sorted(sub.index[inconsistent])
        if bad_dates:
            detail = _truncate(
                str(pd.Timestamp(d).date()) for d in bad_dates
            )
            report.add(
                code="calendar_inconsistent",
                message=(
                    f"资产池日历不一致：{len(bad_dates)} 个日期上部分资产有价、"
                    f"部分缺失（{detail}）"
                ),
                hint=(
                    "同一策略的资产必须用同一套日历口径。混入不同日历的资产"
                    "（如交易日日历资产 + 工作日日历拼接序列）会导致波动率窗口口径错误；"
                    "请为不同口径的加工序列使用不同的资产代码"
                ),
            )

    # ---- 价格下限：缺省 0.0 即要求价格严格为正（0 值与负值都是脏数据）----
    if contract.min_price >= 0.0:
        bad = sub[sub <= contract.min_price]
        hits = [
            (str(col), str(pd.Timestamp(idx).date()), float(bad.at[idx, col]))
            for col in bad.columns
            for idx in bad[col].dropna().index
        ]
        if hits:
            detail = _truncate(f"{c} @ {d}={v:g}" for c, d, v in hits)
            report.add(
                code="non_positive_price",
                message=(
                    f"存在 {len(hits)} 条价格 <= {contract.min_price:g} 的记录"
                    f"（{detail}）"
                ),
                hint="价格序列须为正数；检查导入源文件是否含 0 值或占位负值",
            )

    if contract.max_single_day_jump is not None:
        threshold = float(contract.max_single_day_jump)
        changes = sub.pct_change(fill_method=None).abs()
        over = changes[changes > threshold]
        hits = [
            (str(col), str(pd.Timestamp(idx).date()), float(over.at[idx, col]))
            for col in over.columns
            for idx in over[col].dropna().index
        ]
        if hits:
            detail = _truncate(f"{c} @ {d}={v:.1%}" for c, d, v in hits)
            report.add(
                code="price_jump",
                message=(
                    f"存在 {len(hits)} 条单日涨跌幅超过 {threshold:.1%} 的记录"
                    f"（{detail}）"
                ),
                hint=(
                    "常见原因是拼接序列未做收益率衔接（直接用价格 combine_first "
                    "会在切换日产生跳变），或导入了未复权价格"
                ),
            )
    return report


# ---------------------------------------------------------------------------
# 校验：策略包内自定义检查
# ---------------------------------------------------------------------------


def validate_custom(
    contract: Optional[DataContract],
    strategy_instance: Any,
    prices: Optional[pd.DataFrame] = None,
    strategy_params: Optional[Dict[str, Any]] = None,
) -> ContractReport:
    """执行策略类自带的自定义检查 ``_check_<name>(prices, params) -> Optional[str]``.

    约定：返回 None 或空字符串表示通过，返回非空字符串表示失败原因。
    契约声明了检查名但策略类未实现对应方法时记 error —— 声明与实现不同步
    属于配置错误，不得静默跳过。
    """
    report = ContractReport()
    if contract is None or not contract.custom_checks:
        return report

    for name in contract.custom_checks:
        fn = getattr(strategy_instance, f"_check_{name}", None)
        if not callable(fn):
            report.add(
                code="custom_check_missing",
                message=(
                    f"契约声明了自定义检查 {name!r}，"
                    f"但策略类未实现 _check_{name}()"
                ),
                hint=(
                    f"在策略类中实现 _check_{name}(self, prices, params)，"
                    "返回 None 表示通过，返回字符串表示失败原因"
                ),
            )
            continue
        try:
            reason = fn(prices, strategy_params or {})
        except Exception as exc:  # 检查自身异常不得被当作通过
            report.add(
                code="custom_check_error",
                message=f"自定义检查 {name!r} 执行异常：{type(exc).__name__}: {exc}",
                hint="检查方法需自行处理数据缺失，不得靠异常绕过校验",
            )
            continue
        if reason:
            report.add(
                code="custom_check_failed",
                message=f"自定义检查 {name!r} 未通过：{reason}",
                hint=f"见策略类 _check_{name}() 的实现说明",
            )
    return report
