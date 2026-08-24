"""
参数版本快照服务

从 strategy_model_service.py 拆分而来，负责策略参数版本的创建、查询与变更摘要。
只操作 strategy_param_versions 集合（附带只读访问策略模型与回测记录集合）。
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId

from app.config.database import Database
from app.models.strategy_model import StrategyModel


class ParamVersionService:
    """参数版本快照服务 - 版本创建 / 列表 / 详情 / 变更摘要"""

    def __init__(self):
        self._db = None
        self._collection = None
        self._backtest_collection = None
        self._model_collection = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            from app.config.collections import COL_STRATEGY_PARAM_VERSIONS
            self._collection = self.db[COL_STRATEGY_PARAM_VERSIONS]
        return self._collection

    @property
    def backtest_collection(self):
        if self._backtest_collection is None:
            from app.config.collections import COL_BACKTEST_RECORDS
            self._backtest_collection = self.db[COL_BACKTEST_RECORDS]
        return self._backtest_collection

    @property
    def model_collection(self):
        if self._model_collection is None:
            from app.config.collections import COL_STRATEGY_MODELS
            self._model_collection = self.db[COL_STRATEGY_MODELS]
        return self._model_collection

    async def _get_model(self, model_id: str) -> Optional[StrategyModel]:
        """只读获取策略模型（懒初始化补建 v1 用，避免反向依赖 StrategyModelService）"""
        data = await self.model_collection.find_one({"_id": ObjectId(model_id)})
        if data:
            data['_id'] = str(data['_id'])
            return StrategyModel(**data)
        return None

    def _extract_selector_params(self, model: StrategyModel) -> Dict[str, Any]:
        """从模型中提取资产选择器相关参数。
        
        新架构优先从 parameters.selector_parameters 字典读取；
        旧数据回退从顶层字段提取。
        """
        # 优先从 parameters.selector_parameters 读取（新架构）
        sel_params = (model.parameters or {}).get("selector_parameters", {})
        if sel_params and isinstance(sel_params, dict):
            result = dict(sel_params)
            # 合并通用选择器参数（顶层字段）
            if model.asset_selection_count is not None:
                result["asset_selection_count"] = model.asset_selection_count
            if model.min_history_days is not None:
                result["min_history_days"] = model.min_history_days
            return result
        # 兼容旧数据：从顶层字段回退读取
        fields = [
            "selector_type", "asset_selection_count", "min_history_days",
            "momentum_windows", "mom_windows", "posi_windows", "smom_windows",
            "macd_windows", "macd_long_window", "reversal_windows",
            "sharp_windows", "tie_break_window",
        ]
        out = {}
        for f in fields:
            v = getattr(model, f, None)
            if v is not None:
                out[f] = v
        return out

    async def create_param_version(
        self,
        model_id: str,
        model: StrategyModel,
        change_summary: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> str:
        """创建一条参数版本快照记录"""
        # 查询当前最新版本号
        latest = await self.collection.find_one(
            {"model_id": model_id},
            sort=[("version", -1)],
        )
        next_version = (latest["version"] + 1) if latest else 1

        # allocator_params 排除选择器动态参数（选择器参数独立存储在 selector_params）
        alloc = dict(model.parameters or {})
        alloc.pop("selector_parameters", None)

        doc = {
            "model_id": model_id,
            "version": next_version,
            "allocator_params": alloc,
            "selector_enabled": bool(model.enable_momentum_selection),
            "selector_type": model.selector_type,
            "selector_params": self._extract_selector_params(model),
            "controller_code": model.controller_code,
            "controller_params": dict(model.controller_parameters or {}),
            "template_code": model.template_code,
            "asset_codes": list(model.asset_codes or []),
            "change_summary": change_summary,
            "created_at": datetime.now(),
            "created_by": created_by,
        }
        result = await self.collection.insert_one(doc)
        return str(result.inserted_id)

    async def list_param_versions(
        self,
        model_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """按版本号倒序返回参数版本列表（懒初始化：无记录时补建 v1）
        
        每个版本自动附加 backtest_count（该版本关联的回测记录数）。
        """
        total = await self.collection.count_documents(
            {"model_id": model_id}
        )
        if total == 0:
            # lazy init：从当前模型补建初始版本
            model = await self._get_model(model_id)
            if model:
                await self.create_param_version(
                    model_id, model, change_summary="初始创建（自动补建）"
                )

        cursor = (
            self.collection.find({"model_id": model_id})
            .skip(skip)
            .limit(limit)
            .sort("version", -1)
        )
        rows: List[Dict[str, Any]] = []
        async for doc in cursor:
            pv_id_str = str(doc["_id"])
            doc["_id"] = pv_id_str
            doc["id"] = pv_id_str  # Pydantic 需要 id 字段
            # 查询该版本关联的回测记录数
            doc["backtest_count"] = await self.backtest_collection.count_documents(
                {"param_version_id": pv_id_str}
            )
            rows.append(doc)
        return rows

    async def get_param_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        """获取单个参数版本详情"""
        doc = await self.collection.find_one(
            {"_id": ObjectId(version_id)}
        )
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        doc["id"] = doc["_id"]  # Pydantic 需要 id 字段
        return doc

    def build_param_change_summary(
        self,
        old_model: Optional[StrategyModel],
        new_model: StrategyModel,
    ) -> str:
        """对比前后参数字段差异，生成简短中文摘要"""
        if not old_model:
            return "初始创建"

        changed_keys: List[str] = []

        # 分配策略参数
        old_params = dict(old_model.parameters or {})
        new_params = dict(new_model.parameters or {})
        all_keys = set(old_params.keys()) | set(new_params.keys())
        for k in all_keys:
            if old_params.get(k) != new_params.get(k):
                changed_keys.append(k)

        # 选择器相关顶层字段
        sel_fields = [
            "enable_momentum_selection", "selector_type",
            "asset_selection_count", "asset_codes",
            "controller_code",
        ]
        for f in sel_fields:
            if getattr(old_model, f, None) != getattr(new_model, f, None):
                label = {
                    "enable_momentum_selection": "启用选择器",
                    "selector_type": "选择器类型",
                    "asset_selection_count": "选择资产数量",
                    "asset_codes": "资产列表",
                    "controller_code": "控制器",
                }.get(f, f)
                if label not in changed_keys:
                    changed_keys.append(label)

        if not changed_keys:
            return "参数未变化"
        return "变更字段: " + ", ".join(changed_keys[:8])
