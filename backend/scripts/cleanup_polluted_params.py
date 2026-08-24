# -*- coding: utf-8 -*-
"""清理策略模型参数污染

根据每个策略模板的 schema 定义，清理 parameters 中不属于该模板的参数。
这些污染参数通常由前端无条件注入或历史残留导致。

使用方式:
    # 预览模式（不修改数据）
    python scripts/cleanup_polluted_params.py --dry-run

    # 执行清理
    python scripts/cleanup_polluted_params.py
"""
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from loguru import logger

# 模板到类路径的映射
TEMPLATE_CLASS_MAP = {
    "risk_parity": "app.allocation.models.risk_parity.RiskParityStrategy",
    "cso": "app.allocation.models.enhanced_risk_parity.CovarianceSharpeOptimization",
    "risk_budget": "app.allocation.models.risk_budget.RiskBudgetStrategy",
    "factor_rp": "app.allocation.models.factor_risk_parity.FactorRiskParityStrategy",
    "mean_variance": "app.allocation.models.mean_variance.MeanVarianceOptimization",
    "vol_scaled_budget": "app.allocation.models.vol_scaled_budget.VolScaledBudgetStrategy",
    "manual_allocation": "app.allocation.models.manual_allocation.ManualAllocationStrategy",
    "black_litterman": "app.allocation.models.black_litterman.BlackLittermanOptimization",
    "trend_cross_sectional": "app.allocation.models.trend_cross_sectional.TrendCrossSectionalStrategy",
    "etf_cycle_rotation": "app.allocation.models.etf_cycle_rotation.ETFCycleRotationStrategy",
    # 兼容旧 code
    "risk_budget_target_vol": "app.allocation.models.vol_scaled_budget.VolScaledBudgetStrategy",
    "sharpe_risk_budget": "app.allocation.models.vol_scaled_budget.VolScaledBudgetStrategy",
    "momentum_risk_parity": "app.allocation.models.vol_scaled_budget.VolScaledBudgetStrategy",
}

# 运行时必要字段白名单（非 schema 参数但系统执行时需要）
RUNTIME_PARAM_WHITELIST = {
    "manual_weight_adjustments",
    "selector_parameters",
    "weight_caps",
    "max_weight_dict",
    "manual_weights",
}


def get_schema_param_names(template_code: str):
    """根据 template_code 获取其 schema 声明的参数名集合"""
    class_path = TEMPLATE_CLASS_MAP.get(template_code)
    if not class_path:
        return None
    
    try:
        mod_path, cls_name = class_path.rsplit(".", 1)
        mod = __import__(mod_path, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        schema = cls.get_param_schema()
        return {p.name for p in schema.params}
    except Exception as e:
        logger.warning(f"获取模板 {template_code} schema 失败: {e}")
        return None


def main():
    dry_run = "--dry-run" in sys.argv
    
    # 连接数据库
    client = MongoClient("mongodb://localhost:27017")
    db = client["asset_allocation"]
    collection = db["strategy_models"]
    
    print("=" * 60)
    print("策略模型参数污染清理工具")
    print("=" * 60)
    if dry_run:
        print("[预览模式] 不会修改数据\n")
    else:
        print("[执行模式] 将修改数据\n")
    
    # 统计
    total_models = collection.count_documents({})
    cleaned_count = 0
    total_removed_keys = set()
    
    print(f"共 {total_models} 个策略模型\n")
    print("-" * 60)
    
    # 遍历所有策略模型
    for model in collection.find({}):
        model_id = str(model["_id"])
        model_name = model.get("name", "未命名")
        template_code = model.get("template_code", "")
        current_params = model.get("parameters", {})
        
        if not isinstance(current_params, dict) or not current_params:
            continue
        
        # 获取 schema 参数名
        schema_names = get_schema_param_names(template_code)
        if schema_names is None:
            print(f"[跳过] {model_name} ({template_code}) - 未知模板")
            continue
        
        # 计算需要移除的参数
        current_keys = set(current_params.keys())
        allowed_keys = schema_names | RUNTIME_PARAM_WHITELIST
        keys_to_remove = current_keys - allowed_keys
        
        if not keys_to_remove:
            print(f"[正常] {model_name} ({template_code}) - {len(current_keys)} 个参数")
            continue
        
        # 需要清理
        cleaned_count += 1
        total_removed_keys.update(keys_to_remove)
        
        print(f"\n[清理] {model_name} ({template_code})")
        print(f"  当前参数: {sorted(current_keys)}")
        print(f"  Schema参数: {sorted(schema_names)}")
        print(f"  移除: {sorted(keys_to_remove)}")
        
        # 构建清理后的参数
        cleaned_params = {
            k: v for k, v in current_params.items()
            if k in allowed_keys
        }
        
        if not dry_run:
            collection.update_one(
                {"_id": model["_id"]},
                {"$set": {"parameters": cleaned_params}}
            )
            print(f"  -> 已更新")
    
    # 总结
    print("\n" + "=" * 60)
    print("清理总结")
    print("=" * 60)
    print(f"扫描模型数: {total_models}")
    print(f"需要清理: {cleaned_count}")
    print(f"移除的参数类型: {sorted(total_removed_keys)}")
    
    if dry_run and cleaned_count > 0:
        print("\n[提示] 运行以下命令执行实际清理:")
        print("  python scripts/cleanup_polluted_params.py")
    
    client.close()


if __name__ == "__main__":
    main()
