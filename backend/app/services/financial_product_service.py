"""
理财产品服务层
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId
from app.config.database import Database
from app.models.financial_product import FinancialProduct, ProductType, RiskLevel, ProductStatus


class FinancialProductService:
    """理财产品服务"""

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
            self._collection = self.db['financial_products']
        return self._collection

    async def ensure_indexes(self):
        """确保 MongoDB 索引已创建"""
        # 产品代码唯一索引
        await self.collection.create_index(
            "product_code",
            unique=True,
            name="idx_product_code_unique",
        )
        # (status, product_type) 复合索引
        await self.collection.create_index(
            [("status", 1), ("product_type", 1)],
            name="idx_status_product_type",
        )
        # (risk_level, status) 复合索引
        await self.collection.create_index(
            [("risk_level", 1), ("status", 1)],
            name="idx_risk_level_status",
        )

    async def create_product(self, product: FinancialProduct) -> str:
        """创建理财产品"""
        product_dict = product.dict(by_alias=True, exclude={'id'})
        result = await self.collection.insert_one(product_dict)
        return str(result.inserted_id)

    async def get_product(self, product_id: str) -> Optional[FinancialProduct]:
        """根据ID获取理财产品"""
        data = await self.collection.find_one({"_id": ObjectId(product_id)})
        if data:
            data['_id'] = str(data['_id'])
            return FinancialProduct(**data)
        return None

    async def get_product_by_code(self, product_code: str) -> Optional[FinancialProduct]:
        """根据产品代码获取理财产品"""
        data = await self.collection.find_one({"product_code": product_code})
        if data:
            data['_id'] = str(data['_id'])
            return FinancialProduct(**data)
        return None

    async def list_products(
        self,
        product_type: Optional[ProductType] = None,
        risk_level: Optional[RiskLevel] = None,
        status: Optional[ProductStatus] = None,
        is_active: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[FinancialProduct]:
        """
        查询理财产品列表

        Args:
            product_type: 产品类型过滤
            risk_level: 风险等级过滤
            status: 产品状态过滤
            is_active: 是否只查询启用的产品
            skip: 跳过记录数
            limit: 返回记录数
        """
        query: Dict[str, Any] = {"is_active": is_active} if is_active else {}
        if product_type:
            query["product_type"] = product_type
        if risk_level:
            query["risk_level"] = risk_level
        if status:
            query["status"] = status

        cursor = self.collection.find(query).skip(skip).limit(limit)
        products = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            products.append(FinancialProduct(**doc))

        return products

    async def update_product(self, product_id: str, update_data: Dict[str, Any]) -> bool:
        """更新理财产品"""
        update_data['updated_at'] = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0

    async def delete_product(self, product_id: str) -> bool:
        """删除理财产品（软删除：is_active=False）"""
        result = await self.collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": {"is_active": False, "updated_at": datetime.now()}}
        )
        return result.modified_count > 0
