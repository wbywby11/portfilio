"""
投资经理服务层
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId

from app.config.database import Database
from app.models.investment_manager import (
    InvestmentManager, ManagerLevel, ExpertiseDomain, RiskAppetite
)


class InvestmentManagerService:
    """投资经理服务"""

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
            self._collection = self.db['investment_managers']
        return self._collection

    async def ensure_indexes(self):
        """确保索引存在"""
        # manager_code 唯一索引
        await self.collection.create_index("manager_code", unique=True)
        # (expertise, is_active) 复合索引
        await self.collection.create_index([("expertise", 1), ("is_active", 1)])
        # risk_appetite 索引
        await self.collection.create_index("risk_appetite")

    async def create_manager(self, manager: InvestmentManager) -> str:
        """创建投资经理"""
        manager_dict = manager.dict(by_alias=True, exclude={'id'})
        result = await self.collection.insert_one(manager_dict)
        return str(result.inserted_id)

    async def get_manager(self, manager_id: str) -> Optional[InvestmentManager]:
        """根据ID获取投资经理"""
        data = await self.collection.find_one({"_id": ObjectId(manager_id)})
        if data:
            data['_id'] = str(data['_id'])
            return InvestmentManager(**data)
        return None

    async def get_manager_by_code(self, manager_code: str) -> Optional[InvestmentManager]:
        """根据经理代码获取投资经理"""
        data = await self.collection.find_one({"manager_code": manager_code})
        if data:
            data['_id'] = str(data['_id'])
            return InvestmentManager(**data)
        return None

    async def list_managers(
        self,
        level: Optional[ManagerLevel] = None,
        expertise: Optional[ExpertiseDomain] = None,
        risk_appetite: Optional[RiskAppetite] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[InvestmentManager]:
        """
        查询投资经理列表

        Args:
            level: 职级过滤
            expertise: 专长领域过滤
            risk_appetite: 风险偏好过滤
            is_active: 是否只查询启用的经理
            skip: 跳过记录数
            limit: 返回记录数
        """
        query: Dict[str, Any] = {}
        if level is not None:
            query["level"] = level
        if expertise is not None:
            query["expertise"] = expertise
        if risk_appetite is not None:
            query["risk_appetite"] = risk_appetite
        if is_active is not None:
            query["is_active"] = is_active

        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        managers: List[InvestmentManager] = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            managers.append(InvestmentManager(**doc))
        return managers

    async def update_manager(self, manager_id: str, update_data: Dict[str, Any]) -> bool:
        """更新投资经理"""
        update_data['updated_at'] = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(manager_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0

    async def delete_manager(self, manager_id: str) -> bool:
        """删除投资经理（软删除）"""
        result = await self.collection.update_one(
            {"_id": ObjectId(manager_id)},
            {"$set": {"is_active": False, "updated_at": datetime.now()}}
        )
        return result.modified_count > 0
