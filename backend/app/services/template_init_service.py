"""内置模板初始化服务

在程序启动时自动同步内置模板到数据库。
"""

import logging
from typing import List, FrozenSet
from app.services.model_template_service import ModelTemplateService
from app.models.model_template import ModelTemplate, ModelParameter
from app.strategies.builtin_templates import get_builtin_templates

logger = logging.getLogger(__name__)

# ── 历史上所有曾作为内置模板发布过的 code ──────────────────────────
# 维护此集合的目的：清理阶段只软删除「曾经是内置、但代码已移除」的模板，
# 绝不触碰用户通过界面自建的自定义模板。
# 每当新增或移除内置策略时，务必同步更新此集合。
_KNOWN_BUILTIN_CODES: FrozenSet[str] = frozenset({
    "risk_parity",
    "mean_variance",
    "cso",
    "risk_budget",
    "factor_rp",
    "risk_budget_target_vol",
    "manual_allocation",
    "black_litterman",
    "etf_cycle_rotation",
    # ---- 已从代码中移除的历史内置模板 ----
    "target_volatility",
})


async def init_builtin_templates() -> dict:
    """
    初始化内置模板到数据库
    
    逻辑：
    1. 获取所有内置模板定义
    2. 对每个模板，检查数据库中是否存在（通过 code 判断）
    3. 如果不存在，插入到数据库
    4. 如果存在，可选择更新（目前保持不变，避免覆盖用户修改）
    
    Returns:
        {
            "total": 总数,
            "created": 新创建数,
            "skipped": 跳过数,
            "templates": [模板代码列表]
        }
    """
    service = ModelTemplateService()
    builtin_templates = get_builtin_templates()
    
    result = {
        "total": len(builtin_templates),
        "created": 0,
        "skipped": 0,
        "deleted": 0,
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
                    logger.info(f"  ✓ 清理已移除的内置模板 [{db_template.code}]")
                    result["deleted"] += 1
        except Exception as e:
            logger.warning(f"  ✗ 清理旧模板时出错: {e}")
    
    # === 创建/跳过阶段 ===
    for template_data in builtin_templates:
        code = template_data["code"]
        result["templates"].append(code)
        
        # 检查是否已存在
        existing = await service.get_template_by_code(code)
        
        if existing:
            # 已存在，跳过（避免覆盖用户可能的修改）
            result["skipped"] += 1
            print(f"  ✓ 内置模板 [{code}] 已存在，跳过")
            continue
        
        # 不存在，创建新模板
        try:
            # 转换参数格式
            parameters = [
                ModelParameter(**param_data)
                for param_data in template_data["parameters"]
            ]
            
            # 创建模板实例
            template = ModelTemplate(
                code=template_data["code"],
                name=template_data["name"],
                description=template_data["description"],
                source_code=template_data["source_code"],
                parameters=parameters,
                is_active=True
            )
            
            # 插入数据库
            template_id = await service.create_template(template)
            result["created"] += 1
            print(f"  ✓ 创建内置模板 [{code}] - {template_data['name']} (ID: {template_id})")
            
        except Exception as e:
            print(f"  ✗ 创建内置模板 [{code}] 失败: {e}")
    
    logger.info(
        f"内置模板初始化完成: 总计={result['total']}, "
        f"创建={result['created']}, 跳过={result['skipped']}, "
        f"清理={result['deleted']}"
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
                        "source_code": template_data["source_code"],
                        "parameters": [p.dict() for p in parameters]
                    }
                    
                    await service.update_template(existing.id, update_data)
                    result["updated"] += 1
                    print(f"  ✓ 更新内置模板 [{code}] - {template_data['name']}")
                    
                except Exception as e:
                    print(f"  ✗ 更新内置模板 [{code}] 失败: {e}")
            else:
                result["skipped"] += 1
                print(f"  ✓ 内置模板 [{code}] 已存在，跳过")
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
                source_code=template_data["source_code"],
                parameters=parameters,
                is_active=True
            )
            
            template_id = await service.create_template(template)
            result["created"] += 1
            print(f"  ✓ 创建内置模板 [{code}] - {template_data['name']} (ID: {template_id})")
            
        except Exception as e:
            print(f"  ✗ 创建内置模板 [{code}] 失败: {e}")
    
    return result
