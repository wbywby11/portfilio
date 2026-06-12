"""业绩基准服务层"""
from datetime import datetime
from typing import List, Optional
from bson import ObjectId

from app.config.database import Database
from app.models.benchmark import PerformanceBenchmark, BenchmarkType


class BenchmarkService:
    """业绩基准服务"""
    
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
            self._collection = self.db['performance_benchmarks']
        return self._collection
    
    async def create_benchmark(self, benchmark: PerformanceBenchmark) -> str:
        """创建业绩基准"""
        # 验证复合基准的权重总和是否等于1
        if benchmark.benchmark_type == BenchmarkType.COMPOSITE:
            total_weight = sum(comp.weight for comp in benchmark.components)
            if abs(total_weight - 1.0) > 0.001:  # 允许微小误差
                raise ValueError(f"复合基准权重总和必须为1，当前总和为: {total_weight}")
        
        # 验证绝对基准必须有固定收益率
        if benchmark.benchmark_type == BenchmarkType.ABSOLUTE:
            if benchmark.fixed_return is None:
                raise ValueError("绝对基准必须提供固定收益率")
        
        benchmark_dict = benchmark.dict(by_alias=True, exclude={'id'})
        result = await self.collection.insert_one(benchmark_dict)
        return str(result.inserted_id)
    
    async def get_benchmark(self, benchmark_id: str) -> Optional[PerformanceBenchmark]:
        """获取单个业绩基准"""
        data = await self.collection.find_one({"_id": ObjectId(benchmark_id)})
        if data:
            data['_id'] = str(data['_id'])
            return PerformanceBenchmark(**data)
        return None
    
    async def get_benchmark_by_code(self, code: str) -> Optional[PerformanceBenchmark]:
        """根据代码获取业绩基准"""
        data = await self.collection.find_one({"code": code})
        if data:
            data['_id'] = str(data['_id'])
            return PerformanceBenchmark(**data)
        return None
    
    async def list_benchmarks(
        self,
        benchmark_type: Optional[BenchmarkType] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100
    ) -> List[PerformanceBenchmark]:
        """查询业绩基准列表"""
        query = {}
        if benchmark_type:
            query["benchmark_type"] = benchmark_type
        if is_active is not None:
            query["is_active"] = is_active
        
        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        benchmarks = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            benchmarks.append(PerformanceBenchmark(**doc))
        
        return benchmarks
    
    async def update_benchmark(self, benchmark_id: str, update_data: dict) -> bool:
        """更新业绩基准"""
        # 获取现有基准以检查其类型
        existing_benchmark = await self.get_benchmark(benchmark_id)
        if not existing_benchmark:
            return False
            
        # 验证复合基准的权重总和
        benchmark_type = update_data.get('benchmark_type', existing_benchmark.benchmark_type)
            
        if benchmark_type == BenchmarkType.COMPOSITE.__str__() or \
           (isinstance(benchmark_type, BenchmarkType) and benchmark_type == BenchmarkType.COMPOSITE):
            if 'components' in update_data:
                total_weight = sum(comp['weight'] for comp in update_data['components'])
                if abs(total_weight - 1.0) > 0.001:
                    raise ValueError(f"复合基准权重总和必须为1，当前总和为: {total_weight}")
        elif benchmark_type == BenchmarkType.ABSOLUTE.__str__() or \
             (isinstance(benchmark_type, BenchmarkType) and benchmark_type == BenchmarkType.ABSOLUTE):
            if 'fixed_return' in update_data:
                if update_data['fixed_return'] is None:
                    raise ValueError("绝对基准必须提供固定收益率")
            elif 'benchmark_type' in update_data and ('fixed_return' not in update_data or update_data['fixed_return'] is None):
                # 如果正在转换为绝对基准但没有提供fixed_return
                raise ValueError("绝对基准必须提供固定收益率")
            
        update_data['updated_at'] = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(benchmark_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0
    
    async def delete_benchmark(self, benchmark_id: str) -> bool:
        """删除业绩基准（软删除）"""
        result = await self.collection.update_one(
            {"_id": ObjectId(benchmark_id)},
            {"$set": {"is_active": False, "updated_at": datetime.now()}}
        )
        return result.modified_count > 0