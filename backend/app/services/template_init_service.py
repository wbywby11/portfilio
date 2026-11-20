"""内置模板初始化服务

在程序启动时自动同步内置模板到数据库。
"""

import logging
from typing import Dict, FrozenSet
from app.services.model_template_service import ModelTemplateService
from app.models.model_template import ModelTemplate, ModelParameter
from app.allocation.builtin_templates import get_builtin_templates
from app.allocation.strategy_manifest import STRATEGY_MANIFEST

logger = logging.getLogger(__name__)

# ── 历史上所有曾作为内置模板发布过的 code ──────────────────────────
# 自动从 STRATEGY_MANIFEST 派生当前 Allocation 策略码，
# 加上历史已移除的固定码，无需手动维护。
_HISTORICAL_RETIRED_CODES: FrozenSet[str] = frozenset({
    # 已从代码中移除的历史内置模板
    "gmsi2", "gmap", "gcmi", "etf_discount",
    # ETF贴水率选择器（2026-10-27 弃用）：代码已移除，启动时软删除库内该模板记录
    "sel_etf_discount",
    "ctrl_risk_budget_vol",
    # 波动率定标已回归策略参数（vol_targeting_*），不再作为控制器模板
    "ctrl_dual_window_targeting",
    # 历史别名（已合并到其他策略）
    "sel_momentum",
})

_KNOWN_BUILTIN_CODES: FrozenSet[str] = (
    frozenset(STRATEGY_MANIFEST.keys())
    | frozenset({
        # Selection 策略
        "sel_momentum_reversal", "sel_sharpe",
        "sel_cross_sectional_momentum", "sel_trend_following",
        "sel_etf_rotation",
        "sel_cross_sectional_long_short",
        # Control 策略
        "ctrl_rolling_vol", "ctrl_dual_window_vol",
    })
    | _HISTORICAL_RETIRED_CODES
)


async def _dedup_active_templates(service: ModelTemplateService) -> int:
    """自愈清理同 code 的重复活跃文档。

    对存在多条活跃文档的 code，保留一条、其余软删除：
    - 保留规则确定性排序：updated_at → created_at → id 取最大者，
      多进程并发启动时各进程计算结果一致，操作收敛；
    - 仅软删除（is_active=False），不物理删除，保留可审计历史。

    Returns:
        软删除的文档数
    """
    active_templates = await service.list_templates(is_active=True, limit=100000)
    by_code: Dict[str, list] = {}
    for template in active_templates:
        by_code.setdefault(template.code, []).append(template)

    deduped = 0
    for code, docs in by_code.items():
        if len(docs) < 2:
            continue
        docs.sort(key=lambda t: (t.updated_at, t.created_at, t.id or ""))
        for stale in docs[:-1]:
            try:
                await service.delete_template(stale.id)
                deduped += 1
                logger.info("[OK] 自愈: 软删除重复模板 [%s] id=%s", code, stale.id)
            except Exception as e:
                logger.warning(
                    "[FAIL] 自愈: 软删除重复模板 [%s] id=%s 失败: %s", code, stale.id, e
                )
    return deduped


async def _sync_strategy_registry() -> None:
    """同步策略档案（挂在本服务的两个模板同步入口，不挂纯函数）.
    ``get_builtin_templates()`` 是纯函数，在那里注入 DB 副作用会让模板派生
    与落库耦死、单测无法纯内存运行；因此采集器 hook 挂在这里的两个
    「写库入口」：启动初始化与手动同步。失败只 warn，不阻断模板同步。
    """
    try:
        from app.services.strategy_registry_collector import sync_registry_from_manifest

        await sync_registry_from_manifest()
    except Exception as exc:  # noqa: BLE001 —— 档案同步失败不影响模板可用性
        logger.warning("[registry] 策略档案同步失败（不影响启动）: %s", exc)


async def init_builtin_templates() -> dict:
    """
    初始化内置模板到数据库
    
    逻辑：
    1. 自愈清理同 code 的历史重复文档（软删除，保留最近更新者）
    2. 确保 model_templates.code 部分唯一索引（仅约束 is_active=true）
    3. 获取所有内置模板定义
    4. 对每个模板，检查数据库中是否存在（通过 code 判断）
    5. 如果不存在，插入到数据库（is_builtin=True）
    6. 如果存在，同步参数/composition（不覆盖用户 source_code）
    
    Returns:
        {
            "total": 总数,
            "created": 新创建数,
            "skipped": 跳过数,
            "deduped": 自愈软删除数,
            "templates": [模板代码列表]
        }
    """
    service = ModelTemplateService()

    # === 自愈阶段：清理同 code 历史重复文档 ===
    # 必须先于唯一索引创建执行：只要集合中存在重复 code，唯一索引必然创建失败
    deduped = await _dedup_active_templates(service)

    # 确保 code 唯一约束：部分唯一索引，仅约束活跃文档
    # （软删除的历史文档仍带 code，全量唯一索引在有历史残留的库上永远无法建立）
    try:
        await service.collection.create_index(
            "code",
            unique=True,
            name="code_unique_active",
            partialFilterExpression={"is_active": True},
        )
    except Exception as e:
        logger.warning(f"创建 model_templates.code 部分唯一索引失败: {e}")

    builtin_templates = get_builtin_templates()

    # 策略档案同步：按 manifest_key 幂等 upsert，已存在的 strategy_id 与人工字段不变
    await _sync_strategy_registry()

    result = {
        "total": len(builtin_templates),
        "created": 0,
        "skipped": 0,
        "deleted": 0,
        "deduped": deduped,
        "templates": []
    }
    
    # === 清理阶段：软删除代码中已移除的内置模板 ===
    # 安全策略：只清理「曾经是内置 (_KNOWN_BUILTIN_CODES) 但当前代码已不再定义」的模板，
    # 用户通过界面自建的自定义模板永远不会被此逻辑触碰。
    current_codes = {t["code"] for t in builtin_templates}
    retired_codes = _KNOWN_BUILTIN_CODES - current_codes  # 已退役的内置 code
    if retired_codes:
        try:
            all_active_templates = await service.list_templates(is_active=True)
            for db_template in all_active_templates:
                if db_template.code in retired_codes:
                    await service.delete_template(db_template.id)
                    logger.info(
                        "[OK] 清理已移除的内置模板 [%s]", db_template.code
                    )
                    result["deleted"] += 1
        except Exception as e:
            logger.warning("[FAIL] 清理旧模板时出错: %s", e)
    
    # === 创建/更新阶段 ===
    for template_data in builtin_templates:
        code = template_data["code"]
        result["templates"].append(code)
        
        # 转换参数格式（无论是否已存在都需要最新参数定义）
        try:
            new_parameters = [
                ModelParameter(**param_data)
                for param_data in template_data["parameters"]
            ]
        except Exception as e:
            logger.error("[FAIL] 解析内置模板 [%s] 参数失败: %s", code, e)
            continue
        
        # 检查是否已存在
        existing = await service.get_template_by_code(code)
        
        if existing:
            # 已存在：同步参数定义（修复旧版 min/max_value 等字段错误），
            # 但不覆盖用户的 source_code 自定义修改
            update_fields = {}
            if not existing.is_active:
                update_fields["is_active"] = True
            # 始终同步参数（确保代码侧修复生效）
            update_fields["parameters"] = [p.dict() for p in new_parameters]
            # 同步 composition 配置
            if template_data.get("composition"):
                update_fields["composition"] = template_data["composition"]
            # 同步策略形态（存量模板缺该字段时补 composite，独立策略补 standalone）
            _form = template_data.get("strategy_form") or "composite"
            if getattr(existing, "strategy_form", None) != _form:
                update_fields["strategy_form"] = _form
            
            if update_fields:
                await service.update_template(existing.id, update_fields)
                result["created"] += 1
                logger.info("[OK] 更新内置模板 [%s] 参数定义", code)
            else:
                result["skipped"] += 1
                logger.info("[OK] 内置模板 [%s] 已存在，跳过", code)
            continue
        
        # 不存在，创建新模板
        try:
            # 创建模板实例（使用上面已解析好的 new_parameters）
            template = ModelTemplate(
                code=template_data["code"],
                name=template_data["name"],
                description=template_data["description"],
                source_code=template_data.get("source_code"),
                parameters=new_parameters,
                category=template_data.get("category", "allocation"),
                strategy_form=template_data.get("strategy_form") or "composite",
                composition=template_data.get("composition"),
                is_active=True,
                is_builtin=True,
            )
            
            # 插入数据库
            template_id = await service.create_template(template)
            result["created"] += 1
            logger.info(
                "[OK] 创建内置模板 [%s] - %s (ID: %s)",
                code, template_data["name"], template_id,
            )
            
        except Exception as e:
            logger.error("[FAIL] 创建内置模板 [%s] 失败: %s", code, e)
    
    logger.info(
        f"内置模板初始化完成: 总计={result['total']}, "
        f"创建={result['created']}, 跳过={result['skipped']}, "
        f"清理={result['deleted']}, 自愈去重={result['deduped']}"
    )
    return result


async def sync_builtin_templates(force_update: bool = False) -> dict:
    """
    同步内置模板（高级版本，支持强制更新）
    
    Args:
        force_update: 是否强制更新已存在的模板
    
    Returns:
        同步结果
    """
    service = ModelTemplateService()
    builtin_templates = get_builtin_templates()

    # 策略档案同步：与本函数共用同一幂等入口，保证手动同步也能补齐档案
    await _sync_strategy_registry()
    
    result = {
        "total": len(builtin_templates),
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "templates": []
    }
    
    for template_data in builtin_templates:
        code = template_data["code"]
        result["templates"].append(code)
        
        # 检查是否已存在
        existing = await service.get_template_by_code(code)
        
        if existing:
            if force_update:
                # 强制更新
                try:
                    parameters = [
                        ModelParameter(**param_data)
                        for param_data in template_data["parameters"]
                    ]
                    
                    update_data = {
                        "name": template_data["name"],
                        "description": template_data["description"],
                        "source_code": template_data.get("source_code"),
                        "parameters": [p.dict() for p in parameters],
                        "category": template_data.get("category", "allocation"),
                        "strategy_form": template_data.get("strategy_form") or "composite",
                        "composition": template_data.get("composition"),
                    }
                    
                    await service.update_template(existing.id, update_data)
                    result["updated"] += 1
                    logger.info(
                        "[OK] 更新内置模板 [%s] - %s", code, template_data["name"]
                    )
                    
                except Exception as e:
                    logger.error("[FAIL] 更新内置模板 [%s] 失败: %s", code, e)
            else:
                result["skipped"] += 1
                logger.info("[OK] 内置模板 [%s] 已存在，跳过", code)
            continue
        
        # 不存在，创建新模板
        try:
            parameters = [
                ModelParameter(**param_data)
                for param_data in template_data["parameters"]
            ]
            
            template = ModelTemplate(
                code=template_data["code"],
                name=template_data["name"],
                description=template_data["description"],
                source_code=template_data.get("source_code"),
                parameters=parameters,
                category=template_data.get("category", "allocation"),
                strategy_form=template_data.get("strategy_form") or "composite",
                composition=template_data.get("composition"),
                is_active=True
            )
            
            template_id = await service.create_template(template)
            result["created"] += 1
            logger.info(
                "[OK] 创建内置模板 [%s] - %s (ID: %s)",
                code, template_data["name"], template_id,
            )
            
        except Exception as e:
            logger.error("[FAIL] 创建内置模板 [%s] 失败: %s", code, e)
    
    return result
