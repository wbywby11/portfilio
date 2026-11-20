# -*- coding: utf-8 -*-
"""策略数据契约门禁服务 —— services 层的库侧校验封装.

引擎层 :mod:`app.backtesting.data_contract` 是纯函数、禁止 IO，因此需要查库的
那部分校验（``expected_asset_class`` 依赖 ``assets`` 文档的 asset_class）由本服务
补齐：查 ``assets`` 组装 ``asset_meta`` → 调引擎层纯函数 → 汇总报告。

两类门禁入口，分别对应计划中的挂载点 3、4：

- :func:`enforce_static_contract`  实盘发布前（配置错误在发布时即拦，
  不等到监控启动才发现）
- :func:`enforce_price_contract`   日常监控拿到价格矩阵后

契约不满足一律抛 :class:`~app.backtesting.data_contract.DataContractError`
（继承 ValueError，API 层按既有惯例转 400，缺口清单原样呈现到前端），
不降级、不跳过资产、不放宽断言。

策略未声明契约（``DataContract()`` 全缺省）时快速返回，存量策略零影响。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from loguru import logger

from app.backtesting.data_contract import (
    ContractReport,
    ContractViolation,
    DataContract,
    DataContractError,
    validate_static,
    validate_with_prices,
    with_panel_declarations,
)
from app.config.collections import COL_ASSETS
from app.config.database import Database

__all__ = [
    "resolve_contract",
    "load_asset_meta",
    "check_static_contract",
    "check_price_contract",
    "enforce_static_contract",
    "enforce_price_contract",
]


def resolve_contract(template_code: Optional[str]) -> Optional[DataContract]:
    """按模板代码解析策略类并取其声明的数据契约.

    Args:
        template_code: 策略模板代码（= STRATEGY_MANIFEST 的键）

    Returns:
        策略声明的 DataContract（面板声明已按契约单源补齐，见
        :func:`with_panel_declarations`）；模板代码为空或**未注册**时返回 None。

    Raises:
        DataContractError: 代码已注册但类加载失败。此前这里 fail-open 返回 None，
            后果是「类别名写错」与「策略未声明契约」表现完全一样，配置错误被静默
            放过；现在改为 fail-closed：已注册就一定要拿到可用的契约。
    """
    if not template_code:
        return None
    from app.allocation.strategy_manifest import get_class_paths, resolve_class_safe

    code = str(template_code)
    if code not in get_class_paths():
        return None
    strategy_cls = resolve_class_safe(code)
    if strategy_cls is None:
        raise DataContractError(
            code,
            [
                ContractViolation(
                    level="error",
                    code="class_load_failed",
                    message="策略已注册但类加载失败，无法读取数据契约",
                    hint="检查 STRATEGY_MANIFEST 的 class_path 是否指向可导入的类",
                )
            ],
        )
    getter = getattr(strategy_cls, "get_data_contract", None)
    if not callable(getter):
        return None
    contract = getter()
    if not isinstance(contract, DataContract):
        return None
    return with_panel_declarations(contract, strategy_cls)


async def load_asset_meta(asset_codes: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """查 ``assets`` 集合组装 ``{code: {asset_class, instrument_type, ...}}``.

    仅取契约校验需要的字段；库中不存在的代码不进结果，
    由 ``validate_static`` 报 ``asset_not_found``（提示先在资产管理页创建）。
    """
    codes = [str(c).strip() for c in (asset_codes or []) if str(c).strip()]
    if not codes:
        return {}

    db = Database.get_database()
    cursor = db[COL_ASSETS].find(
        {"code": {"$in": codes}},
        {"code": 1, "name": 1, "asset_class": 1,
         "instrument_type": 1, "security_type": 1, "is_active": 1},
    )
    meta: Dict[str, Dict[str, Any]] = {}
    async for doc in cursor:
        code = str(doc.get("code") or "").strip()
        if not code:
            continue
        meta[code] = {
            "name": doc.get("name"),
            "asset_class": doc.get("asset_class"),
            "instrument_type": doc.get("instrument_type"),
            "security_type": doc.get("security_type"),
            "is_active": doc.get("is_active", True),
        }
    return meta


def _collect_group_codes(
    contract: DataContract, strategy_params: Dict[str, Any]
) -> List[str]:
    """契约分组参数里出现的全部资产代码（分组内的资产也需在 assets 中有文档）."""
    from app.backtesting.data_contract import parse_asset_codes

    out: List[str] = []
    for name in contract.group_params or {}:
        for code in parse_asset_codes((strategy_params or {}).get(name)):
            if code not in out:
                out.append(code)
    return out


async def check_static_contract(
    template_code: Optional[str],
    asset_codes: Sequence[str],
    strategy_params: Optional[Dict[str, Any]] = None,
    strategy_label: Optional[str] = None,
) -> ContractReport:
    """静态面校验（含库侧 asset_meta）；不抛错，返回报告供调用方决定.

    ``asset_meta`` 覆盖资产池与契约分组参数中出现的全部代码 ——
    分组参数里写了库中不存在的代码同样属于配置错误，需在发布时拦住。
    """
    contract = resolve_contract(template_code)
    if contract is None or contract.is_empty:
        return ContractReport()

    params = dict(strategy_params or {})
    codes = [str(c).strip() for c in (asset_codes or []) if str(c).strip()]

    meta: Optional[Dict[str, Dict[str, Any]]] = None
    if contract.expected_asset_class:
        lookup = list(codes)
        for code in _collect_group_codes(contract, params):
            if code not in lookup:
                lookup.append(code)
        meta = await load_asset_meta(lookup)

    return validate_static(contract, codes, params, asset_meta=meta)


async def check_price_contract(
    template_code: Optional[str],
    asset_codes: Sequence[str],
    strategy_params: Optional[Dict[str, Any]] = None,
    prices: Optional[pd.DataFrame] = None,
) -> ContractReport:
    """数据面校验（历史长度/日历一致性/价格异常）；不抛错，返回报告.

    ``prices`` 应为未经清洗的价格矩阵（监控侧 ``load_prices`` 的原始结果），
    口径与回测侧 ``DataFeed.strategy_prices`` 一致。
    """
    contract = resolve_contract(template_code)
    if contract is None or contract.is_empty:
        return ContractReport()

    codes = [str(c).strip() for c in (asset_codes or []) if str(c).strip()]
    return validate_with_prices(contract, codes, dict(strategy_params or {}), prices)


async def enforce_static_contract(
    template_code: Optional[str],
    asset_codes: Sequence[str],
    strategy_params: Optional[Dict[str, Any]] = None,
    strategy_label: Optional[str] = None,
) -> ContractReport:
    """静态面门禁：契约不满足即抛 DataContractError（实盘发布前调用）."""
    report = await check_static_contract(
        template_code, asset_codes, strategy_params, strategy_label
    )
    label = strategy_label or template_code or "unknown"
    for warn in report.warnings:
        logger.warning("[DataContract] {} 提示: {}", label, warn.format())
    report.raise_if_failed(label)
    return report


async def enforce_price_contract(
    template_code: Optional[str],
    asset_codes: Sequence[str],
    strategy_params: Optional[Dict[str, Any]] = None,
    prices: Optional[pd.DataFrame] = None,
    strategy_label: Optional[str] = None,
) -> ContractReport:
    """数据面门禁：契约不满足即抛 DataContractError（日常监控取数后调用）."""
    report = await check_price_contract(
        template_code, asset_codes, strategy_params, prices
    )
    label = strategy_label or template_code or "unknown"
    for warn in report.warnings:
        logger.warning("[DataContract] {} 提示: {}", label, warn.format())
    report.raise_if_failed(label)
    return report
