"""
模型模板服务层（支持动态策略加载与注册）
"""
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId
from app.config.database import Database
from app.models.model_template import ModelTemplate
from app.strategies.dynamic_loader import DynamicStrategyLoader


class ModelTemplateService:
    """模型模板服务"""
    
    def __init__(self):
        self._db = None
        self._collection = None
    
    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.db['model_templates']
        return self._collection
    
    async def create_template(self, template: ModelTemplate) -> str:
        """创建模板"""
        template_dict = template.dict(by_alias=True, exclude={'id'})
        result = await self.collection.insert_one(template_dict)
        return str(result.inserted_id)
    
    async def get_template(self, template_id: str) -> Optional[ModelTemplate]:
        """获取单个模板"""
        data = await self.collection.find_one({"_id": ObjectId(template_id)})
        if data:
            data['_id'] = str(data['_id'])
            return ModelTemplate(**data)
        return None
    
    async def get_template_by_code(self, code: str) -> Optional[ModelTemplate]:
        """根据代码获取模板"""
        data = await self.collection.find_one({"code": code})
        if data:
            data['_id'] = str(data['_id'])
            return ModelTemplate(**data)
        return None
    
    async def list_templates(
        self,
        is_active: bool = True,
        skip: int = 0,
        limit: int = 100
    ) -> List[ModelTemplate]:
        """查询模板列表"""
        query = {"is_active": is_active} if is_active else {}
        cursor = self.collection.find(query).skip(skip).limit(limit)
        
        templates = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            templates.append(ModelTemplate(**doc))
        
        return templates
    
    async def update_template(self, template_id: str, update_data: Dict[str, Any]) -> bool:
        """更新模板"""
        update_data['updated_at'] = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(template_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0
    
    async def delete_template(self, template_id: str) -> bool:
        """删除模板(软删除)"""
        result = await self.collection.update_one(
            {"_id": ObjectId(template_id)},
            {"$set": {"is_active": False, "updated_at": datetime.now()}}
        )
        return result.modified_count > 0
    
    async def validate_template(self, template: ModelTemplate) -> Dict[str, Any]:
        """
        验证模板的有效性（包括源代码验证）
        
        Args:
            template: 模型模板实例
            
        Returns:
            验证结果字典：
            {
                "valid": bool,
                "errors": List[str],
                "warnings": List[str],
                "strategy_class": Optional[str]
            }
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "strategy_class": None
        }
        
        # 1. 基础字段验证
        if not template.code:
            result["errors"].append("模板代码不能为空")
            result["valid"] = False
        
        if not template.name:
            result["errors"].append("模板名称不能为空")
            result["valid"] = False
        
        # 2. 源代码验证（必须提供）
        if not template.source_code:
            result["errors"].append("必须提供源代码")
            result["valid"] = False
        else:
            validation = DynamicStrategyLoader.validate_template_source_code(template)
            result["valid"] = result["valid"] and validation["valid"]
            result["errors"].extend(validation["errors"])
            result["warnings"].extend(validation["warnings"])
            result["strategy_class"] = validation["strategy_class"]
        
        # 3. 参数定义验证
        if not template.parameters:
            result["warnings"].append("未定义参数，策略将不接受任何配置参数")
        else:
            # 验证参数定义的完整性
            for i, param in enumerate(template.parameters):
                if not param.name:
                    result["errors"].append(f"第{i+1}个参数缺少name字段")
                    result["valid"] = False
                if not param.label:
                    result["errors"].append(f"第{i+1}个参数缺少label字段")
                    result["valid"] = False
        
        return result
    
    async def register_template_to_strategy_service(
        self, 
        template: ModelTemplate, 
        strategy_service
    ) -> bool:
        """
        将模板注册到策略服务
        
        内置策略（如 risk_budget_target_vol）优先使用代码中的类，保证修复和迭代生效；
        其他模板从数据库 source_code 动态加载。
        
        Args:
            template: 模型模板实例
            strategy_service: StrategyService实例
            
        Returns:
            是否注册成功
        """
        try:
            # 1. 验证模板
            validation = await self.validate_template(template)
            if not validation["valid"]:
                raise ValueError(f"模板验证失败: {', '.join(validation['errors'])}")
            
            # 2. 内置策略优先使用代码中的类（避免数据库 source_code 旧版本覆盖本地修复）
            strategy_cls = self._get_builtin_strategy_class(template.code)
            if strategy_cls is None:
                strategy_cls = DynamicStrategyLoader.load_strategy_class_from_template(template)
            
            # 3. 注册到策略服务
            strategy_service.register(template.code, strategy_cls)
            return True
        
        except Exception as e:
            import warnings
            warnings.warn(f"注册模板 {template.code} 到策略服务失败: {e}")
            return False

    def _get_builtin_strategy_class(self, template_code: str):
        """内置策略类型返回代码中的类，否则返回 None（走动态加载）。"""
        builtins = {
            "risk_parity": "app.strategies.models.risk_parity.RiskParityStrategy",
            "cso": "app.strategies.models.enhanced_risk_parity.CovarianceSharpeOptimization",
            "risk_budget": "app.strategies.models.risk_budget.RiskBudgetStrategy",
            "factor_rp": "app.strategies.models.factor_risk_parity.FactorRiskParityStrategy",
            "mean_variance": "app.strategies.models.mean_variance.MeanVarianceOptimization",
            "risk_budget_target_vol": "app.strategies.models.risk_budget_target_vol.RiskBudgetTargetVolStrategy",
            "manual_allocation": "app.strategies.models.manual_allocation.ManualAllocationStrategy",
            "black_litterman": "app.strategies.models.black_litterman.BlackLittermanOptimization",
        }
        path = builtins.get(template_code)
        if not path:
            return None
        mod_path, cls_name = path.rsplit(".", 1)
        mod = __import__(mod_path, fromlist=[cls_name])
        return getattr(mod, cls_name)
    

