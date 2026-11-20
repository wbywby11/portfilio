# -*- coding: utf-8 -*-
"""策略预设解析与三级校验服务.

职责边界：把一份预设声明（:mod:`app.allocation.builtin_presets`）展开成
「资产代码 + 参数 + 调仓频率」，并在展开过程中给出结构化问题清单。
本服务不落库、不改策略算法，只做展开与校验。

三级分级
--------
引擎层 :mod:`app.backtesting.data_contract` 的 ``ContractViolation`` 带
``level: "error" | "warning"`` 与机器码 ``code``，但 ``error`` 内部混了
两类东西：结构/配置错误（补数据不解决）与数据缺口（补数据即可解决）。
本服务在其外层按 ``_LEVEL_BY_CODE`` 再细分，不改引擎层：

- ``blocking_error``：结构或配置错误，应用后 ``allocate`` 必然报错，前端禁用「应用」；
- ``data_error``：数据缺口，可先应用（保存配置），但禁用「运行回测」；
- ``warning``：提示，不阻断。

门禁复用
--------
静态面校验直接调 :func:`~app.services.strategy_data_contract_service.check_static_contract`，
与实盘发布前的 ``enforce_static_contract`` 同源。三处挂载点的事实关系：

===========  ==========================  ============
挂载点        函数                        传 asset_meta
===========  ==========================  ============
回测前        ``validate_static``         否（引擎层禁止查库）
实盘发布前    ``enforce_static_contract`` 是
预设 resolve  ``check_static_contract``   是
===========  ==========================  ============

因此「resolve 通过 ⇒ 回测静态门禁必过」单向成立；反向不成立（回测不查
``asset_class``）。这是分层设计的结果，两套结论不会互相矛盾。

资产面口径（UI 必须写明）：resolve 只校验「资产池非空」与「池内代码在
``assets`` 集合有登记」，**不校验行情**——有没有行情、历史够不够、是否
落后最新交易日，与单日跳变、价格非正一样，全部由回测引擎的
``validate_with_prices`` 在真正运行时判定。理由：宽池必然含已清盘或暂停
申购的产品，逐只判行情只产出噪点，也不应该阻止先把配置存下来。
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from app.allocation.builtin_presets import find_preset, preset_content_hash
from app.allocation.runtime_params import (
    effective_param_names,
    normalize_runtime_params,
)
from app.allocation.strategy_manifest import resolve_class
from app.config.collections import COL_ASSETS
from app.config.database import Database
from app.services.strategy_data_contract_service import (
    check_static_contract,
    load_asset_meta,
    resolve_contract,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LEVEL_BLOCKING",
    "LEVEL_DATA",
    "LEVEL_WARNING",
    "PresetIssue",
    "PresetResolveResult",
    "resolve_preset",
    "validate_config",
    "config_hash",
    "classify",
    "stamp_preset_trace",
    "preset_derived_fields",
]

LEVEL_BLOCKING = "blocking_error"
LEVEL_DATA = "data_error"
LEVEL_WARNING = "warning"

# 引擎层/本服务机器码 → 三级分级。
# 未列出的码按引擎层 level 兜底：error → blocking_error，warning → warning。
_LEVEL_BY_CODE: Dict[str, str] = {
    # preset service 自身产出
    "template_not_found": LEVEL_BLOCKING,
    "duplicate_code": LEVEL_BLOCKING,
    "group_overlap": LEVEL_BLOCKING,
    "tag_empty": LEVEL_BLOCKING,
    "parameter_invalid": LEVEL_BLOCKING,
    "tag_unknown": LEVEL_WARNING,
    "empty_group": LEVEL_WARNING,
    "param_condition_unmet": LEVEL_WARNING,
    # validate_static
    "unknown_calendar": LEVEL_BLOCKING,
    "too_few_assets": LEVEL_BLOCKING,
    "group_missing": LEVEL_BLOCKING,
    "group_too_small": LEVEL_BLOCKING,
    "pool_not_covered": LEVEL_BLOCKING,
    "group_member_not_in_pool": LEVEL_BLOCKING,
    "asset_class_mismatch": LEVEL_BLOCKING,
    "asset_not_found": LEVEL_DATA,
    # 资产面：只判池子是否为空与代码是否登记，不判行情
    "pool_empty": LEVEL_DATA,
    "prices_empty": LEVEL_DATA,  # 旧码，等价 pool_empty，保留兼容
}


def classify(code: str, source_level: str = "error") -> str:
    """把机器码映射到三级分级.

    ``asset_class_mismatch`` 归 blocking 而非 data：资产存在，是大类字段填错
    或分组放错，补数据不解决，必须改配置。

    ``asset_not_found`` / ``pool_empty`` 归 data 而非 blocking：配置本身没写错，
    补资产或补标签即可解决；但池子为空时 ``allocate`` 必然失败，所以不能
    降为 warning。
    """
    level = _LEVEL_BY_CODE.get(code)
    if level:
        return level
    return LEVEL_BLOCKING if source_level == "error" else LEVEL_WARNING


def config_hash(asset_codes: Sequence[str], parameters: Dict[str, Any]) -> str:
    """应用时的配置指纹（sha256 前 8 位）.

    前端用它判断「应用预设后是否被手动调整过」：当前表单的
    ``asset_codes`` + ``parameters`` 重算出同一个值即未改动。
    """
    payload = {"asset_codes": list(asset_codes or []), "parameters": parameters or {}}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------


@dataclass
class PresetIssue:
    """一条展开/校验问题."""

    level: str  # blocking_error | data_error | warning
    type: str  # 机器码，前端据此分组与国际化
    message: str
    hint: str = ""
    assets: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "type": self.type,
            "message": self.message,
            "hint": self.hint,
            "assets": list(self.assets),
        }


@dataclass
class PresetResolveResult:
    """预设展开结果（resolve 与 validate 共用）."""

    template_code: str
    name: str
    asset_codes: List[str]
    parameters: Dict[str, Any]
    rebalance_frequency: Optional[str]
    min_history_days: Optional[int]
    groups: Dict[str, List[str]]
    issues: List[PresetIssue] = field(default_factory=list)
    preset_code: Optional[str] = None
    preset_version: Optional[str] = None
    asset_selection_snapshot: Dict[str, Any] = field(default_factory=dict)

    @property
    def blocking_issues(self) -> List[PresetIssue]:
        return [i for i in self.issues if i.level == LEVEL_BLOCKING]

    @property
    def data_issues(self) -> List[PresetIssue]:
        return [i for i in self.issues if i.level == LEVEL_DATA]

    @property
    def warning_issues(self) -> List[PresetIssue]:
        return [i for i in self.issues if i.level == LEVEL_WARNING]

    @property
    def applicable(self) -> bool:
        """「应用」按钮是否可点：只由 blocking 决定.

        data_error 允许应用（先把配置存下来，补数据后即可回测），
        但前端需同时禁用「运行回测」。
        """
        return not self.blocking_issues

    @property
    def backtest_ready(self) -> bool:
        """「运行回测」按钮是否可点：blocking 与 data 都必须清空."""
        return not self.blocking_issues and not self.data_issues

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_code": self.template_code,
            "preset_code": self.preset_code,
            "preset_version": self.preset_version,
            "name": self.name,
            "asset_codes": list(self.asset_codes),
            "parameters": dict(self.parameters),
            "rebalance_frequency": self.rebalance_frequency,
            "min_history_days": self.min_history_days,
            "groups": {k: list(v) for k, v in self.groups.items()},
            "asset_selection_snapshot": dict(self.asset_selection_snapshot),
            "issues": [i.to_dict() for i in self.issues],
            "applicable": self.applicable,
            "backtest_ready": self.backtest_ready,
        }


# ---------------------------------------------------------------------------
# 资产展开
# ---------------------------------------------------------------------------


def _uniq_codes(values: Any) -> List[str]:
    """归一为去空、去重、保序的代码列表."""
    out: List[str] = []
    for v in values or []:
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


def _codes_with_all_tags(tag_index: Dict[str, List[str]], tags: Sequence[str]) -> List[str]:
    """取同时具备全部标签的资产代码（多标签取交集），按代码升序."""
    wanted = [str(t).strip() for t in (tags or []) if str(t).strip()]
    if not wanted:
        return []
    sets = [set(tag_index.get(t) or []) for t in wanted]
    if any(not s for s in sets):
        return []
    return sorted(set.intersection(*sets))


async def _load_tag_index() -> Dict[str, List[str]]:
    """读 ``assets`` 组装 ``{tag: [code, ...]}``，停用资产不参与展开."""
    db = Database.get_database()
    cursor = db[COL_ASSETS].find(
        {"is_active": {"$ne": False}},
        {"code": 1, "tags": 1, "_id": 0},
    )
    index: Dict[str, List[str]] = {}
    async for doc in cursor:
        code = str(doc.get("code") or "").strip()
        if not code:
            continue
        for tag in doc.get("tags") or []:
            key = str(tag).strip()
            if key:
                index.setdefault(key, []).append(code)
    for codes in index.values():
        codes.sort()
    return index


async def _expand_assets(
    asset_selection: Optional[Dict[str, Any]],
) -> tuple[Dict[str, List[str]], List[str], Dict[str, List[str]]]:
    """按 ``mode`` 展开分组与资产池.

    Returns:
        (groups, asset_codes, tag_index)

    三种模式：

    - ``explicit``：分组直接枚举，池子 = 各组并集；
    - ``tags``：池子 = 具备 ``tags`` 全部标签的资产，分组由 ``group_rules`` 从池内切；
    - ``hybrid``：显式 ``groups`` 优先，未显式声明的组按 ``group_rules`` 从池内切。
    """
    card = asset_selection or {}
    mode = str(card.get("mode") or "explicit").strip().lower()
    declared: Dict[str, List[str]] = card.get("groups") or {}
    rules: Dict[str, Dict[str, Any]] = card.get("group_rules") or {}
    pool_tags = [str(t).strip() for t in (card.get("tags") or []) if str(t).strip()]

    tag_index: Dict[str, List[str]] = {}
    if mode in ("tags", "hybrid") or rules:
        tag_index = await _load_tag_index()

    # 池子：显式代码 + 标签命中
    pool: List[str] = []
    for codes in declared.values():
        for code in _uniq_codes(codes):
            if code not in pool:
                pool.append(code)
    if mode in ("tags", "hybrid") and pool_tags:
        for code in _codes_with_all_tags(tag_index, pool_tags):
            if code not in pool:
                pool.append(code)

    # 分组：显式优先，其余按标签规则从池内切
    groups: Dict[str, List[str]] = {}
    for name, codes in declared.items():
        groups[name] = _uniq_codes(codes)
    pool_set = set(pool)
    for name, rule in rules.items():
        if groups.get(name):
            continue
        matched = _codes_with_all_tags(tag_index, (rule or {}).get("tags") or [])
        groups[name] = [c for c in matched if c in pool_set]

    return groups, pool, tag_index


def _group_param_names(template_code: str) -> set:
    """返回该模板真正的「资产分组」参数名集合.

    不能按 ``*_codes`` 后缀一刀切：``series_codes``（宏观序列）、
    ``tool_fee_codes``（年费计提资产）同样以后缀结尾但不是分组，
    按后缀回写会把预设里的宏观序列抹成空串。
    口径优先取策略声明的 ``contract.group_params``；未声明契约时
    退化为 schema 里全部 ``*_codes`` 参数。
    """
    contract = resolve_contract(template_code)
    declared = set((getattr(contract, "group_params", None) or {}))
    if declared:
        return declared
    return {
        p.name for p in resolve_class(template_code).get_param_schema().params
        if p.name.endswith("_codes")
    }


def _merge_parameters(
    template_code: str,
    preset_parameters: Optional[Dict[str, Any]],
    groups: Dict[str, List[str]],
    min_history_days: Optional[int],
) -> Dict[str, Any]:
    """schema 默认值打底 → 预设覆盖 → 分组代码写回.

    分组写回是「声明层单一事实源」的落地：``parameters.*_codes`` 由
    ``groups`` 生成，预设声明里不写这些键，因此不存在两份来源。

    写回范围限于真正的分组参数（``groups`` 里声明的组 + 契约声明的
    分组），否则会误伤 ``series_codes`` 这类同后缀的非分组参数。
    """
    schema = resolve_class(template_code).get_param_schema()
    merged: Dict[str, Any] = {p.name: copy.deepcopy(p.default) for p in schema.params}

    for key, value in (preset_parameters or {}).items():
        merged[key] = value

    group_params = _group_param_names(template_code)
    for spec in schema.params:
        if spec.name.endswith("_codes") and (
            spec.name in groups or spec.name in group_params
        ):
            merged[spec.name] = ",".join(groups.get(spec.name) or [])

    # 顶层 min_history_days 是数据门禁阈值；模板有同名参数时以顶层为准，
    # 避免「门禁按 260 判、策略按 120 跑」的两套口径。
    if min_history_days is not None and "min_history_days" in merged:
        merged["min_history_days"] = int(min_history_days)

    return merged


# ---------------------------------------------------------------------------
# 结构 / 参数校验
# ---------------------------------------------------------------------------


def _check_structure(
    asset_selection: Optional[Dict[str, Any]],
    groups: Dict[str, List[str]],
    asset_pool: List[str],
    template_code: str,
    tag_index: Dict[str, List[str]],
    asset_meta: Optional[Dict[str, Dict[str, Any]]],
) -> List[PresetIssue]:
    """结构类问题：重复、越界、空组、未知标签."""
    issues: List[PresetIssue] = []
    card = asset_selection or {}
    mode = str(card.get("mode") or "explicit").strip().lower()
    rules: Dict[str, Dict[str, Any]] = card.get("group_rules") or {}
    pool_tags = [str(t).strip() for t in (card.get("tags") or []) if str(t).strip()]

    # 同组重复代码
    for name, codes in groups.items():
        seen: Dict[str, int] = {}
        for code in codes:
            seen[code] = seen.get(code, 0) + 1
        dup = sorted(c for c, n in seen.items() if n > 1)
        if dup:
            issues.append(PresetIssue(
                level=LEVEL_BLOCKING,
                type="duplicate_code",
                message=f"分组 {name} 内出现重复资产代码：{'、'.join(dup)}",
                hint="从该分组参数中删除重复的代码",
                assets=dup,
            ))

    # 跨组重叠
    owner: Dict[str, str] = {}
    for name, codes in groups.items():
        for code in codes:
            first = owner.get(code)
            if first is None:
                owner[code] = name
            elif first != name:
                issues.append(PresetIssue(
                    level=LEVEL_BLOCKING,
                    type="group_overlap",
                    message=f"资产 {code} 同时出现在分组 {first} 与 {name}",
                    hint="同一资产只能属于一个分组，删除其中一处",
                    assets=[code],
                ))

    # 标签模式但没给标签
    if mode == "tags" and not pool_tags:
        issues.append(PresetIssue(
            level=LEVEL_BLOCKING,
            type="tag_empty",
            message="标签模式预设未声明任何资产池标签",
            hint="在 asset_selection.tags 中补充 pool:<池名> 标签",
        ))

    # 未知标签（0 个资产使用）
    all_rule_tags: List[str] = list(pool_tags)
    for rule in rules.values():
        all_rule_tags.extend(str(t).strip() for t in ((rule or {}).get("tags") or []))
    unknown = sorted({t for t in all_rule_tags if t and not tag_index.get(t)})
    if unknown:
        issues.append(PresetIssue(
            level=LEVEL_WARNING,
            type="tag_unknown",
            message=f"标签在资产表中没有任何资产使用：{'、'.join(unknown)}",
            hint="到资产管理页给相关资产打上该标签，或修正预设中的标签名",
        ))

    # 空组：标签规则算出空组，且池内确实存在该组要求的大类资产
    if asset_meta is not None:
        contract = resolve_contract(template_code)
        expected_map = dict(getattr(contract, "expected_asset_class", None) or {})
        for name in rules:
            if groups.get(name):
                continue
            expected_class = expected_map.get(name)
            if not expected_class:
                continue
            candidates = [
                code for code in asset_pool
                if str((asset_meta.get(code) or {}).get("asset_class") or "").strip() == expected_class
            ]
            if not candidates:
                continue
            issues.append(PresetIssue(
                level=LEVEL_WARNING,
                type="empty_group",
                message=(
                    f"分组 {name} 按标签规则展开为空，但池内有 {len(candidates)} 只"
                    f"{expected_class}资产符合作组条件"
                ),
                hint="检查这些资产是否漏打了分组所需标签",
                assets=candidates,
            ))

    return issues


def _check_parameters(
    template_code: str, parameters: Dict[str, Any]
) -> List[PresetIssue]:
    """参数类问题：未定义、类型/范围、必填为空、条件不满足.

    判定口径 = 模板 schema ∪ 运行时键（:mod:`app.allocation.runtime_params`）。
    运行时键由系统写入、被 Pipeline / 回测引擎 / 监控消费（选择器参数、
    主观调仓、模型级调度声明、按模板固化的监控参数），不属于模板可配置
    参数，不能因「不在 schema 中」阻断回测——否则配置能存下来却跑不了回测。
    历史参数名（如 ``max_weight_dict``）先归一为现名，再按现名的 schema
    规格校验，避免出现「同一个约束两种口径」。
    """
    issues: List[PresetIssue] = []
    try:
        schema = resolve_class(template_code).get_param_schema()
    except Exception as exc:  # 类加载失败：模板不可用，属配置错误
        issues.append(PresetIssue(
            level=LEVEL_BLOCKING,
            type="template_not_found",
            message=f"无法加载模板 {template_code} 的参数定义：{exc}",
            hint="确认 strategy_manifest 中该模板的 class_path 有效",
        ))
        return issues

    known = {spec.name: spec for spec in schema.params}
    effective = normalize_runtime_params(parameters)
    runtime_keys = effective_param_names(template_code)

    for name, value in effective.items():
        spec = known.get(name)
        if spec is None:
            if name in runtime_keys:
                continue
            issues.append(PresetIssue(
                level=LEVEL_BLOCKING,
                type="parameter_invalid",
                message=f"参数 {name!r} 不在模板 {template_code} 的参数定义中",
                hint="删除该参数，或确认它属于当前模板",
            ))
            continue
        ok, msg = spec.validate(value)
        if not ok:
            issues.append(PresetIssue(
                level=LEVEL_BLOCKING,
                type="parameter_invalid",
                message=msg,
                hint=f"按 {spec.label} 的取值范围修正参数值",
            ))

    issues.extend(_check_param_conditions(schema, known, effective))
    return issues


def _check_param_conditions(
    schema: Any, known: Dict[str, Any], parameters: Dict[str, Any]
) -> List[PresetIssue]:
    """条件不满足的提示（warning）：值仍停留在默认值时不报.

    默认值本就是该条件下的中性取值，报出来只是噪点。

    Args:
        schema: 模板参数 schema
        known: ``{参数名: ParamSchema}``
        parameters: 已归一的参数（历史名 → 现名）

    Returns:
        ``param_condition_unmet`` 级别的问题列表
    """
    issues: List[PresetIssue] = []
    for spec in schema.params:
        cond = spec.condition
        if not cond:
            continue
        field_name = cond.get("field")
        expected = cond.get("value")
        if field_name not in known:
            continue
        if parameters.get(field_name) == expected:
            continue
        value = parameters.get(spec.name)
        if value is None or value == spec.default:
            continue
        issues.append(PresetIssue(
            level=LEVEL_WARNING,
            type="param_condition_unmet",
            message=(
                f"参数 {spec.label}（{spec.name}）在 {field_name}="
                f"{parameters.get(field_name)!r} 时不生效，但仍被设为 {value!r}"
            ),
            hint=f"把 {spec.name} 改回默认值 {spec.default!r}，或先打开 {field_name}",
        ))
    return issues


# ---------------------------------------------------------------------------
# 契约 / 价格校验
# ---------------------------------------------------------------------------

# issue 文案里最多逐个列举多少只资产。宽池（如 354 只基金）不截断会让
# 弹窗文案过万字符，前端渲染与阅读都失效；完整清单仍在 ``assets`` 字段
_MAX_LISTED_ASSETS = 8


def _brief(items: List[str]) -> str:
    """列举资产清单，超过上限时只列前几项并用总数收尾."""
    if len(items) <= _MAX_LISTED_ASSETS:
        return "、".join(items)
    head = "、".join(items[:_MAX_LISTED_ASSETS])
    return f"{head} 等 {len(items)} 只"


async def _check_contract(
    template_code: str, asset_codes: List[str], parameters: Dict[str, Any]
) -> List[PresetIssue]:
    """静态面契约校验，结论与实盘发布门禁同源."""
    report = await check_static_contract(
        template_code, asset_codes, parameters, strategy_label=template_code
    )
    return [
        PresetIssue(
            level=classify(v.code, v.level),
            type=v.code,
            message=v.message,
            hint=v.hint,
            assets=[v.asset] if v.asset else [],
        )
        for v in report.violations
    ]


async def _check_assets(
    asset_codes: List[str], template_code: str
) -> List[PresetIssue]:
    """资产面检查：池子非空 + 池内代码在 ``assets`` 集合有登记.

    只校验「名字存在」，不校验「有没有数据」：行情有无、历史长短、是否落后
    最新交易日，与单日跳变、价格非正一样，全部由回测引擎在真正运行时判定
    （``validate_with_prices``）。宽池（如 354 只指数增强基金）必然包含已清盘
    或暂停申购的产品，逐只判行情只产出噪点，也不应该阻止先把配置存下来。

    契约声明了 ``expected_asset_class`` 的模板，``check_static_contract`` 已逐组
    产出 ``asset_not_found``，此处不再重复查库。
    """
    codes = [c for c in asset_codes or [] if c]
    if not codes:
        # 空池（典型是标签池未打标签）归 data_error 而非静默通过：
        # 补标签即可解决，属数据缺口，不等于配置错；但绝不能允许直接回测
        return [PresetIssue(
            level=LEVEL_DATA,
            type="pool_empty",
            message="资产池为空，没有展开出任何资产",
            hint="给资产打上预设要求的标签，或改用手工选择资产",
        )]

    contract = resolve_contract(template_code)
    if contract is not None and getattr(contract, "expected_asset_class", None):
        return []

    db = Database.get_database()
    registered = {
        str(doc.get("code") or "").strip()
        async for doc in db[COL_ASSETS].find(
            {"code": {"$in": codes}}, {"code": 1, "_id": 0}
        )
    }
    missing = [c for c in codes if c not in registered]
    if not missing:
        return []
    return [PresetIssue(
        level=LEVEL_DATA,
        type="asset_not_found",
        message=f"资产池有 {len(missing)} 只不在 assets 集合中：{_brief(missing)}",
        hint="先在资产管理页创建这些资产，或修正资产池中的代码",
        assets=missing,
    )]


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


def build_asset_selection_snapshot(
    asset_selection: Optional[Dict[str, Any]],
    groups: Dict[str, List[str]],
    asset_codes: List[str],
    parameters: Dict[str, Any],
    applied_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """构造应用时的资产池规则快照（随模型一起落库）.

    本期语义是「应用即快照」：``form.asset_codes`` 存展开后的代码，
    快照只留规则原文与展开时点，供详情页溯源。标签后续变更不会自动同步——
    ``published_snapshot`` 是下游回测/监控/组合的唯一读取源，动态展开会让
    同一模型在不同时间得到不同资产池，与「发布冻结快照」冲突。
    """
    card = asset_selection or {}
    return {
        "mode": card.get("mode") or "explicit",
        "tags": list(card.get("tags") or []),
        "group_rules": copy.deepcopy(card.get("group_rules") or {}),
        "groups": {k: list(v) for k, v in (groups or {}).items()},
        "expanded_at": (applied_at or datetime.now()).isoformat(),
        "expanded_codes": list(asset_codes or []),
        "applied_hash": config_hash(asset_codes, parameters),
    }


async def _run_checks(
    template_code: str,
    asset_selection: Optional[Dict[str, Any]],
    groups: Dict[str, List[str]],
    asset_codes: List[str],
    parameters: Dict[str, Any],
) -> List[PresetIssue]:
    """跑完整校验链：参数 → 结构 → 契约 → 资产登记."""
    issues = _check_parameters(template_code, parameters)

    contract = resolve_contract(template_code)
    asset_meta: Optional[Dict[str, Dict[str, Any]]] = None
    if contract is not None and getattr(contract, "expected_asset_class", None):
        lookup = list(asset_codes)
        for spec_name in (contract.group_params or {}):
            for code in str(parameters.get(spec_name) or "").replace("，", ",").split(","):
                code = code.strip()
                if code and code not in lookup:
                    lookup.append(code)
        asset_meta = await load_asset_meta(lookup)

    tag_index: Dict[str, List[str]] = {}
    if str((asset_selection or {}).get("mode") or "").lower() in ("tags", "hybrid") \
            or (asset_selection or {}).get("group_rules"):
        tag_index = await _load_tag_index()

    issues.extend(_check_structure(
        asset_selection, groups, asset_codes, template_code, tag_index, asset_meta
    ))
    issues.extend(await _check_contract(template_code, asset_codes, parameters))
    issues.extend(await _check_assets(asset_codes, template_code))
    return issues


async def resolve_preset(preset_code: str) -> PresetResolveResult:
    """按 preset_code 展开并校验一个内置预设.

    Raises:
        KeyError: preset_code 未注册（API 层转 404）
    """
    preset = find_preset(preset_code)
    if preset is None:
        raise KeyError(f"未找到预设 {preset_code!r}")

    template_code = str(preset["template_code"])
    try:
        resolve_class(template_code)
    except Exception as exc:
        raise KeyError(f"预设 {preset_code!r} 指向的模板 {template_code!r} 不可用：{exc}") from exc

    groups, asset_codes, _ = await _expand_assets(preset.get("asset_selection"))
    min_history_days = preset.get("min_history_days")
    parameters = _merge_parameters(
        template_code, preset.get("parameters"), groups, min_history_days
    )

    issues = await _run_checks(
        template_code, preset.get("asset_selection"), groups,
        asset_codes, parameters,
    )

    version = preset_content_hash(preset)
    return PresetResolveResult(
        template_code=template_code,
        name=str(preset.get("name") or ""),
        asset_codes=asset_codes,
        parameters=parameters,
        rebalance_frequency=preset.get("rebalance_frequency"),
        min_history_days=min_history_days,
        groups=groups,
        issues=issues,
        preset_code=preset_code,
        preset_version=version,
        asset_selection_snapshot=build_asset_selection_snapshot(
            preset.get("asset_selection"), groups, asset_codes, parameters
        ),
    )


async def validate_config(
    template_code: str,
    asset_codes: Sequence[str],
    parameters: Optional[Dict[str, Any]] = None,
    min_history_days: Optional[int] = None,
    rebalance_frequency: Optional[str] = None,
    asset_selection: Optional[Dict[str, Any]] = None,
    name: str = "",
) -> PresetResolveResult:
    """校验任意一组配置（不依赖预设，也不要求已保存）.

    详情页与其他入口用它实时算门禁结论：``asset_codes`` 与 ``parameters``
    可以直接来自表单，未保存也能给出「能不能跑回测」的答案。

    模板不可用时返回带 ``template_not_found`` 阻断结论的结果，**不抛异常**：
    抛 KeyError 会被 API 层转成 404，前端 catch 后清空问题清单，
    一个根本跑不起来的模型看起来反而「可以回测」。
    """
    effective_params = normalize_runtime_params(parameters)
    try:
        strategy_cls = resolve_class(template_code)
    except Exception as exc:
        logger.warning(
            "validate_config 模板不可用：%s（%s）", template_code, exc
        )
        return PresetResolveResult(
            template_code=template_code,
            name=name,
            asset_codes=_uniq_codes(asset_codes),
            parameters=effective_params,
            rebalance_frequency=rebalance_frequency,
            min_history_days=min_history_days,
            groups={},
            issues=[PresetIssue(
                level=LEVEL_BLOCKING,
                type="template_not_found",
                message=f"模板 {template_code!r} 不可用，无法回测：{exc}",
                hint=(
                    "确认模型的 template_code 是否为历史遗留值，"
                    "或在 strategy_manifest 中注册该模板"
                ),
            )],
            preset_code=None,
            preset_version=None,
            asset_selection_snapshot={},
        )

    # 分组以入参 parameters 为准（列表里的资产可能已展开）；
    # 若调用方额外给了 asset_selection，则按它重新展开覆盖之。
    # 只抽真正的分组参数：series_codes / tool_fee_codes 等不是分组，
    # 混入会把宏观序列当成资产分组参与结构与价格校验。
    groups: Dict[str, List[str]] = {}
    schema = strategy_cls.get_param_schema()
    group_params = _group_param_names(template_code)
    for spec in schema.params:
        if spec.name in group_params:
            raw = str(effective_params.get(spec.name) or "")
            groups[spec.name] = _uniq_codes(
                part for part in raw.replace("，", ",").replace(";", ",").split(",")
            )

    if asset_selection:
        groups, expanded, _ = await _expand_assets(asset_selection)
        codes = expanded
    else:
        codes = _uniq_codes(asset_codes)

    merged: Dict[str, Any] = {p.name: copy.deepcopy(p.default) for p in schema.params}
    merged.update(effective_params)
    for spec in schema.params:
        if spec.name in group_params and spec.name in groups:
            merged[spec.name] = ",".join(groups[spec.name])
    effective_min_history = min_history_days
    if effective_min_history is None:
        effective_min_history = merged.get("min_history_days")

    issues = await _run_checks(
        template_code, asset_selection, groups, codes, merged
    )

    return PresetResolveResult(
        template_code=template_code,
        name=name,
        asset_codes=codes,
        parameters=merged,
        rebalance_frequency=rebalance_frequency,
        min_history_days=effective_min_history,
        groups=groups,
        issues=issues,
        preset_code=None,
        preset_version=None,
        asset_selection_snapshot={},
    )


def stamp_preset_trace(
    model_data: Dict[str, Any],
    previous_preset_code: Optional[str] = None,
    fallback_asset_codes: Optional[Sequence[str]] = None,
    fallback_parameters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把预设留痕字段归一（原地修改并返回）.

    ``preset_version`` 一律按当前预设定义重算，不采信前端传值：否则改过预设
    后旧模型会被伪造的版本号掩盖，``preset_outdated`` 永不触发。

    ``preset_applied_at`` 只在预设变更时刷新；同一预设反复保存不刷新应用时间。

    ``asset_selection_snapshot.applied_hash`` 必须保留前端应用那一刻算出的指纹
    ——它就是「应用后是否被手动调整」的基准。前端没给时才用当前配置兜底。

    Raises:
        ValueError: preset_code 未注册（不静默忽略，避开留下无法溯源的模型）

    ``fallback_asset_codes`` / ``fallback_parameters`` 用于 update 场景：
    只改 ``preset_code`` 而未同时传资产与参数时，取存量值作指纹兜底。
    """
    preset_code = model_data.get("preset_code")
    if not preset_code:
        if "preset_code" in model_data:
            # 显式清除预设时同步清空留痕，不留指向旧预设的孤儿字段
            model_data["preset_version"] = None
            model_data["preset_applied_at"] = None
            model_data["asset_selection_snapshot"] = None
        return model_data

    preset = find_preset(str(preset_code))
    if preset is None:
        raise ValueError(f"未找到预设 {preset_code!r}，无法记录预设来源")

    model_data["preset_version"] = preset_content_hash(preset)
    if str(preset_code) != str(previous_preset_code or ""):
        model_data["preset_applied_at"] = datetime.now()
    elif not model_data.get("preset_applied_at"):
        model_data["preset_applied_at"] = datetime.now()

    card = preset.get("asset_selection") or {}
    codes = model_data.get("asset_codes")
    if codes is None:
        codes = list(fallback_asset_codes or [])
    params = model_data.get("parameters")
    if params is None:
        params = dict(fallback_parameters or {})

    snapshot = dict(model_data.get("asset_selection_snapshot") or {})
    snapshot.setdefault("mode", card.get("mode") or "explicit")
    snapshot.setdefault("tags", list(card.get("tags") or []))
    snapshot.setdefault("group_rules", copy.deepcopy(card.get("group_rules") or {}))
    snapshot.setdefault("expanded_codes", list(codes))
    snapshot.setdefault("expanded_at", datetime.now().isoformat())
    if not snapshot.get("applied_hash"):
        snapshot["applied_hash"] = config_hash(codes, params)
    model_data["asset_selection_snapshot"] = snapshot
    return model_data


def preset_derived_fields(model: Any) -> Dict[str, bool]:
    """计算预设派生字段（不落库，接口实时算）.

    - ``preset_modified``：当前 ``asset_codes`` + ``parameters`` 指纹 ≠
      应用预设时的 ``asset_selection_snapshot.applied_hash``
    - ``preset_outdated``：模型记录的 ``preset_version`` ≠ 当前预设定义的内容 hash

    前端算不了 sha256，因此这两个标记只能由后端给出。预设被下线时
    （``find_preset`` 未命中）归为 outdated：模型仍指向一个已不存在的定义，
    提示“基于旧版预设”比沉默更准确。

    Args:
        model: ``StrategyModel`` 实例或 Mongo 文档 dict

    Returns:
        ``{"preset_modified": bool, "preset_outdated": bool}``
    """

    def _get(name: str, default: Any = None) -> Any:
        if isinstance(model, dict):
            return model.get(name, default)
        return getattr(model, name, default)

    preset_code = _get("preset_code")
    if not preset_code:
        return {"preset_modified": False, "preset_outdated": False}

    snapshot = _get("asset_selection_snapshot") or {}
    applied_hash = snapshot.get("applied_hash") if isinstance(snapshot, dict) else None
    current_hash = config_hash(_get("asset_codes") or [], _get("parameters") or {})
    modified = bool(applied_hash) and str(applied_hash) != current_hash

    recorded_version = _get("preset_version")
    if not recorded_version:
        outdated = False
    else:
        preset = find_preset(str(preset_code))
        outdated = True if preset is None else preset_content_hash(preset) != str(recorded_version)

    return {"preset_modified": modified, "preset_outdated": outdated}
