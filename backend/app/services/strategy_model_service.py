"""
策略模型服务层
"""
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId
import pandas as pd
import numpy as np

from app.config.database import Database
from app.models.strategy_model import (
    StrategyModel, 
    ModelStatus, 
    BacktestResult, 
    BacktestRecord,
    PositionRecord,
    AssetPosition,
    EquityPoint,
    ReturnPoint,
    BenchmarkReturnPoint,
    WeightChangePoint
)
from app.services.asset_service import AssetService
from app.services.model_template_service import ModelTemplateService
from app.services.benchmark_service import BenchmarkService
from app.models.strategy_model import LiveRebalanceMode
from app.data.trade_dates import load_trade_dates, get_future_trade_dates
from app.monitor.live_publish_log_scope import (
    align_scoped_for_live_publish,
    collect_asset_codes_from_scoped_diff,
    compute_monitor_scoped_diff,
    compute_snapshot_frozen_monitor_diff,
    drop_live_version_from_scoped_diff,
    extract_monitor_scoped_from_model,
    extract_monitor_scoped_from_published_snapshot,
    filter_monitor_scoped_diff_for_subjective_template,
    merge_parameters_with_top_level_windows,
    merge_runtime_and_snapshot_diff,
    rewrite_resolved_asset_list_diff_for_display,
    summarize_monitor_scoped_diff_zh,
)


def _merge_model_asset_name_maps(
    model_before: Any,
    model_after: Any,
) -> Dict[str, str]:
    """合并前后模型的 asset_names，供底层资产展示名解析。"""
    out: Dict[str, str] = {}
    for m in (model_before, model_after):
        if m is None:
            continue
        an = getattr(m, "asset_names", None)
        if isinstance(an, dict):
            for k, v in an.items():
                if v is not None and str(v).strip():
                    out[str(k)] = str(v).strip()
    return out


def _strip_non_editable_monitor_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """风险预算与编制规则一致，由监控引擎固定，不作为策略模型可变传参持久化。"""
    if not isinstance(params, dict):
        return params
    out = dict(params)
    out.pop("risk_budget_both", None)
    out.pop("risk_budget_single", None)
    return out


_RISK_BUDGET_TARGET_VOL_CODES = frozenset({"risk_budget_target_vol", "risk_budget_vol_target"})
_MANUAL_ALLOCATION_TEMPLATE_CODES = frozenset({"manual_allocation", "manual_allocation_strategy"})


def _is_risk_budget_target_vol_template(template_code: Optional[str]) -> bool:
    return (template_code or "") in _RISK_BUDGET_TARGET_VOL_CODES


def _is_manual_allocation_template(template_code: Optional[str]) -> bool:
    return (template_code or "") in _MANUAL_ALLOCATION_TEMPLATE_CODES


def _apply_manual_allocation_fixed_parameters(params: Dict[str, Any]) -> None:
    """主观配置：日常监控不使用的参数固定为产品默认。"""
    params["max_leverage"] = 1
    params["auto_normalize"] = False
    params["fill_missing"] = "zero"
    params["target_vol"] = 0.05
    params["vol_reset_threshold"] = 0.06
    params["enable_vol_reset"] = False


def _enforce_manual_allocation_monitor_fixed_on_dict(model_dict: Dict[str, Any]) -> None:
    if not _is_manual_allocation_template(model_dict.get("template_code")):
        return
    params = dict(model_dict.get("parameters") or {})
    _apply_manual_allocation_fixed_parameters(params)
    model_dict["parameters"] = params
    model_dict["min_history_days"] = 260
    model_dict["momentum_windows"] = "20,60,120,250"
    model_dict["mom_windows"] = "20,60,120,250"
    model_dict["posi_windows"] = "20,60,120,250"
    model_dict["smom_windows"] = "20,60,120,250"
    model_dict["macd_windows"] = "40,80,120,160"
    model_dict["macd_long_window"] = 250
    model_dict["reversal_windows"] = "10,22"


def _enforce_risk_budget_target_vol_fixed_on_dict(model_dict: Dict[str, Any]) -> None:
    """风险预算目标波动率：固定最小历史 260、波动重置阈值 0.06、回看期 260、并列决胜 22。"""
    if not _is_risk_budget_target_vol_template(model_dict.get("template_code")):
        return
    params = dict(model_dict.get("parameters") or {})
    params["lookback_days"] = 260
    params["vol_reset_threshold"] = 0.06
    params["enable_vol_reset"] = True
    model_dict["parameters"] = params
    model_dict["min_history_days"] = 260
    model_dict["tie_break_window"] = 22


def _merge_strategy_parameters_for_update(
    existing: Optional[StrategyModel],
    update_data: Dict[str, Any],
) -> Dict[str, Any]:
    base = dict(getattr(existing, "parameters", None) or {}) if existing else {}
    if isinstance(update_data.get("parameters"), dict):
        base.update(update_data["parameters"])
    merged = _strip_non_editable_monitor_params(base)
    return dict(merged) if isinstance(merged, dict) else {}


def _float_weight(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sync_manual_allocation_weights_to_asset_codes(
    parameters: Dict[str, Any],
    new_asset_codes: List[Any],
) -> Dict[str, Any]:
    """
    主观配置：底层资产变更时，初始化权重与预设调仓日权重与 asset_codes 对齐。
    移除已删除资产的键；新增资产补 0（小数权重）。
    """
    params = dict(parameters or {})
    codes = [
        str(c).strip()
        for c in (new_asset_codes or [])
        if c is not None and str(c).strip()
    ]
    if not codes:
        return params

    mw_raw = params.get("manual_weights")
    if isinstance(mw_raw, dict):
        params["manual_weights"] = {c: _float_weight(mw_raw.get(c)) for c in codes}

    mwa = params.get("manual_weight_adjustments")
    parsed: Any = mwa
    if isinstance(mwa, str):
        try:
            parsed = json.loads(mwa)
        except (TypeError, ValueError):
            parsed = None
    if isinstance(parsed, list):
        new_list: List[Any] = []
        for item in parsed:
            if not isinstance(item, dict):
                new_list.append(item)
                continue
            row = dict(item)
            w = row.get("weights")
            if isinstance(w, dict):
                row["weights"] = {c: _float_weight(w.get(c)) for c in codes}
            new_list.append(row)
        params["manual_weight_adjustments"] = new_list

    return params


class StrategyModelService:
    """策略模型服务 - 策略配置管理
    
    职责：
    1. 管理策略模型的 CRUD 操作
    2. 存储策略配置（模板、参数、资产池、调仓频率等）
    3. 查询历史回测记录
    
    注意：
    - 本服务不执行回测，回测功能请使用 /api/v1/backtests/run 接口
    - 可以通过 to_backtest_request() 方法将模型配置转换为回测请求参数
    """
    
    def __init__(self):
        self._db = None
        self._collection = None
        self._backtest_collection = None
        self._live_change_collection = None
        self._live_monitoring_collection = None
        self.asset_service = AssetService()
        self.template_service = ModelTemplateService()
        self.benchmark_service = BenchmarkService()  # 添加基准服务

    async def _enrich_asset_name_map_from_db(
        self,
        base: Dict[str, str],
        scoped_diff: Dict[str, Dict[str, Any]],
    ) -> Dict[str, str]:
        """用资产主数据补全展示名（策略 asset_names 未覆盖或键不一致时）。"""
        codes = collect_asset_codes_from_scoped_diff(scoped_diff)
        if not codes:
            return base
        fetched = await self.asset_service.resolve_display_names_for_codes(codes)
        out = dict(base)
        for k, v in (fetched or {}).items():
            if v and str(v).strip():
                sk = str(k).strip()
                prev = out.get(sk)
                if prev is None or not str(prev).strip():
                    out[sk] = str(v).strip()
        return out
    
    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.db['strategy_models']
        return self._collection

    @property
    def backtest_collection(self):
        if self._backtest_collection is None:
            self._backtest_collection = self.db['backtest_records']
        return self._backtest_collection

    @property
    def live_change_collection(self):
        if self._live_change_collection is None:
            self._live_change_collection = self.db['strategy_live_change_logs']
        return self._live_change_collection

    @property
    def live_monitoring_collection(self):
        if self._live_monitoring_collection is None:
            self._live_monitoring_collection = self.db['strategy_live_monitoring_records']
        return self._live_monitoring_collection
    
    async def create_model(self, model: StrategyModel) -> str:
        """创建模型"""
        model_dict = model.dict(by_alias=True, exclude={'id'})
        if isinstance(model_dict.get("parameters"), dict):
            model_dict["parameters"] = _strip_non_editable_monitor_params(model_dict["parameters"])
        _enforce_risk_budget_target_vol_fixed_on_dict(model_dict)
        _enforce_manual_allocation_monitor_fixed_on_dict(model_dict)
        result = await self.collection.insert_one(model_dict)
        return str(result.inserted_id)
    
    async def get_model(self, model_id: str) -> Optional[StrategyModel]:
        """获取单个模型"""
        data = await self.collection.find_one({"_id": ObjectId(model_id)})
        if data:
            data['_id'] = str(data['_id'])
            return StrategyModel(**data)
        return None
    
    async def list_models(
        self,
        status: Optional[ModelStatus] = None,
        template_code: Optional[str] = None,
        rebalance_frequency: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[StrategyModel]:
        """查询模型列表"""
        query = {}
        if status:
            query["status"] = status
        if template_code:
            query["template_code"] = template_code
        if rebalance_frequency:
            query["rebalance_frequency"] = rebalance_frequency
        
        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        models = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            models.append(StrategyModel(**doc))
        
        return models
    
    async def update_model(self, model_id: str, update_data: Dict[str, Any]) -> bool:
        """更新模型"""
        if isinstance(update_data.get("parameters"), dict):
            update_data["parameters"] = _strip_non_editable_monitor_params(update_data["parameters"])
        change_source = update_data.pop("_change_source", "strategy")
        change_operator = update_data.pop("_change_operator", None)
        existing_model = await self.get_model(model_id)
        tpl_code = update_data.get("template_code")
        if tpl_code is None and existing_model is not None:
            tpl_code = getattr(existing_model, "template_code", None)
        if _is_risk_budget_target_vol_template(str(tpl_code or "")):
            update_data["min_history_days"] = 260
            update_data["tie_break_window"] = 22
            if isinstance(update_data.get("parameters"), dict):
                merged_params = _merge_strategy_parameters_for_update(existing_model, update_data)
                merged_params["lookback_days"] = 260
                merged_params["vol_reset_threshold"] = 0.06
                merged_params["enable_vol_reset"] = True
                update_data["parameters"] = merged_params
            else:
                # 不整包替换 parameters，避免仅改名称等非参数字段时误标实盘快照过期
                update_data["parameters.lookback_days"] = 260
                update_data["parameters.vol_reset_threshold"] = 0.06
                update_data["parameters.enable_vol_reset"] = True
        if _is_manual_allocation_template(str(tpl_code or "")) and (
            "parameters" in update_data
            or "template_code" in update_data
            or "asset_codes" in update_data
        ):
            merged_params = _merge_strategy_parameters_for_update(existing_model, update_data)
            new_ac = update_data.get("asset_codes")
            if isinstance(new_ac, list):
                merged_params = _sync_manual_allocation_weights_to_asset_codes(
                    merged_params, new_ac
                )
                # 去掉已移除资产在 asset_names 中的条目，避免展示名与底层资产不一致
                if existing_model is not None and "asset_names" not in update_data:
                    an = dict(getattr(existing_model, "asset_names", None) or {})
                    keep = {str(x).strip() for x in new_ac if x is not None and str(x).strip()}
                    update_data["asset_names"] = {
                        str(k).strip(): v
                        for k, v in an.items()
                        if str(k).strip() in keep
                    }
            _apply_manual_allocation_fixed_parameters(merged_params)
            update_data["parameters"] = merged_params
            update_data["min_history_days"] = 260
            update_data["momentum_windows"] = "20,60,120,250"
            update_data["mom_windows"] = "20,60,120,250"
            update_data["posi_windows"] = "20,60,120,250"
            update_data["smom_windows"] = "20,60,120,250"
            update_data["macd_windows"] = "40,80,120,160"
            update_data["macd_long_window"] = 250
            update_data["reversal_windows"] = "10,22"
        if existing_model and existing_model.live_publish_enabled:
            sensitive_keys = {"asset_codes", "parameters", "rebalance_frequency", "template_code"}
            if any(k in update_data for k in sensitive_keys):
                update_data["live_snapshot_outdated"] = True

        update_data['updated_at'] = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(model_id)},
            {"$set": update_data}
        )
        if result.modified_count > 0 and existing_model and existing_model.live_publish_enabled:
            updated_model = await self.get_model(model_id)
            if not updated_model:
                return result.modified_count > 0
            before_scoped = extract_monitor_scoped_from_model(existing_model)
            after_scoped = extract_monitor_scoped_from_model(updated_model)
            scoped_diff = compute_monitor_scoped_diff(before_scoped, after_scoped)
            scoped_diff = filter_monitor_scoped_diff_for_subjective_template(
                scoped_diff, getattr(updated_model, "template_code", None)
            )
            scoped_diff = drop_live_version_from_scoped_diff(scoped_diff)
            if scoped_diff:
                names = _merge_model_asset_name_maps(existing_model, updated_model)
                names = await self._enrich_asset_name_map_from_db(names, scoped_diff)
                scoped_diff = rewrite_resolved_asset_list_diff_for_display(scoped_diff, names)
                summary_zh = summarize_monitor_scoped_diff_zh(scoped_diff)
                await self.log_live_change(
                    model_id=model_id,
                    action="strategy_update",
                    source=change_source,
                    operator=change_operator,
                    live_version=existing_model.live_version,
                    before={
                        "asset_codes": existing_model.asset_codes,
                        "parameters": existing_model.parameters,
                        "rebalance_frequency": existing_model.rebalance_frequency,
                    },
                    after={
                        "asset_codes": update_data.get("asset_codes", updated_model.asset_codes),
                        "parameters": update_data.get("parameters", updated_model.parameters),
                        "rebalance_frequency": update_data.get(
                            "rebalance_frequency", updated_model.rebalance_frequency
                        ),
                    },
                    change_summary=summary_zh or None,
                    monitor_scoped_changes=scoped_diff,
                )
        return result.modified_count > 0
    
    async def delete_model(self, model_id: str) -> bool:
        """
        删除模型及其关联的回测记录
        
        Args:
            model_id: 模型ID
            
        Returns:
            是否删除成功
        """
        # 先检查模型是否存在
        model = await self.get_model(model_id)
        if not model:
            return False
        
        # 删除所有关联的回测记录
        await self.backtest_collection.delete_many({"model_id": model_id})
        
        # 删除模型
        result = await self.collection.delete_one({"_id": ObjectId(model_id)})
        return result.deleted_count > 0
    
    async def list_backtest_records(
        self,
        model_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[BacktestRecord]:
        """
        查询模型的回测记录列表
        
        Args:
            model_id: 模型ID
            skip: 跳过数量
            limit: 返回数量
            
        Returns:
            回测记录列表
        """
        cursor = self.backtest_collection.find({"model_id": model_id}).skip(skip).limit(limit).sort("created_at", -1)
        records = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            
            # 兼容旧数据：为 equity_curve 添加 unit_value
            if 'result' in doc and 'equity_curve' in doc['result']:
                initial_capital = doc.get('initial_capital', 1000000)
                for point in doc['result']['equity_curve']:
                    if 'unit_value' not in point and 'value' in point:
                        point['unit_value'] = point['value'] / initial_capital
            
            # 兼容旧数据：为 positions 添加 portfolio_value
            if 'result' in doc and 'positions' in doc['result']:
                for i, pos in enumerate(doc['result']['positions']):
                    if 'portfolio_value' not in pos:
                        # 如果有 equity_curve，从对应的净值点获取
                        if 'equity_curve' in doc['result'] and i < len(doc['result']['equity_curve']):
                            pos['portfolio_value'] = doc['result']['equity_curve'][i].get('value')
            
            # 兼容旧数据：weight_changes 从字典格式或 WeightChangePoint 对象转换为统一的 WeightChangePoint 对象
            if 'result' in doc and 'weight_changes' in doc['result']:
                converted_weight_changes = []
                for wc_item in doc['result']['weight_changes']:
                    if isinstance(wc_item, dict):
                        # 旧格式：字典
                        from app.models.strategy_model import WeightChangePoint
                        converted_item = WeightChangePoint(**wc_item)
                        converted_weight_changes.append(converted_item)
                    elif hasattr(wc_item, 'date') and hasattr(wc_item, 'weights'):
                        # WeightChangePoint 对象（已经是正确格式）
                        converted_weight_changes.append(wc_item)
                    else:
                        # 其他未知格式，跳过
                        continue
                doc['result']['weight_changes'] = converted_weight_changes
            
            # 兼容旧数据：确保收益率曲线字段存在
            if 'result' in doc:
                if 'return_curve' not in doc['result']:
                    doc['result']['return_curve'] = []
                if 'benchmark_return_curve' not in doc['result']:
                    doc['result']['benchmark_return_curve'] = []
            
            # 兼容旧数据：确保基准代码字段存在
            if 'benchmark_code' not in doc:
                doc['benchmark_code'] = None
            
            records.append(BacktestRecord(**doc))
        
        return records
    
    async def get_backtest_record(self, record_id: str) -> Optional[BacktestRecord]:
        """
        获取单条回测记录详情
        
        Args:
            record_id: 回测记录ID
            
        Returns:
            回测记录对象
        """
        doc = await self.backtest_collection.find_one({"_id": ObjectId(record_id)})
        if not doc:
            return None
            
        doc['_id'] = str(doc['_id'])
        
        # 兼容性处理逻辑复用 list_backtest_records 中的逻辑
        if 'result' in doc and 'equity_curve' in doc['result']:
            initial_capital = doc.get('initial_capital', 1000000)
            for point in doc['result']['equity_curve']:
                if 'unit_value' not in point and 'value' in point:
                    point['unit_value'] = point['value'] / initial_capital
        
        if 'result' in doc and 'positions' in doc['result']:
            for i, pos in enumerate(doc['result']['positions']):
                if 'portfolio_value' not in pos:
                    if 'equity_curve' in doc['result'] and i < len(doc['result']['equity_curve']):
                        pos['portfolio_value'] = doc['result']['equity_curve'][i].get('value')
        
        if 'result' in doc and 'weight_changes' in doc['result']:
            converted_weight_changes = []
            for wc_item in doc['result']['weight_changes']:
                if isinstance(wc_item, dict):
                    from app.models.strategy_model import WeightChangePoint
                    converted_item = WeightChangePoint(**wc_item)
                    converted_weight_changes.append(converted_item)
                elif hasattr(wc_item, 'date') and hasattr(wc_item, 'weights'):
                    converted_weight_changes.append(wc_item)
                else:
                    continue
            doc['result']['weight_changes'] = converted_weight_changes
        
        if 'result' in doc:
            if 'return_curve' not in doc['result']:
                doc['result']['return_curve'] = []
            if 'benchmark_return_curve' not in doc['result']:
                doc['result']['benchmark_return_curve'] = []
        
        if 'benchmark_code' not in doc:
            doc['benchmark_code'] = None
            
        return BacktestRecord(**doc)

    async def publish_model(self, model_id: str) -> bool:
        """发布模型"""
        model = await self.get_model(model_id)
        if not model:
            return False
        
        # 移除回测状态检查，只要是草稿状态就可以发布
        if model.status == ModelStatus.ARCHIVED:
            raise ValueError("已归档的模型不能发布")
        
        return await self.update_model(model_id, {
            "status": ModelStatus.PUBLISHED,
            "published_at": datetime.now()
        })

    def _next_trade_datetime(self, base_time: datetime) -> datetime:
        """获取基准时点后的下一个交易日（00:00:00）"""
        loaded = load_trade_dates()
        if loaded:
            trade_dates_list = loaded[0]
            future_dates = get_future_trade_dates(pd.Timestamp(base_time), n=1, trade_dates_list=trade_dates_list)
            if future_dates:
                next_day = future_dates[0].to_pydatetime()
                return datetime(next_day.year, next_day.month, next_day.day)
        # 无交易日历时降级为 T+1 自然日
        fallback = base_time + pd.Timedelta(days=1)
        return datetime(fallback.year, fallback.month, fallback.day)

    def _extract_volatility_from_params(self, model: StrategyModel) -> Optional[float]:
        """从策略 parameters 中提取波动率相关参数，用于实盘阈值预填。
        支持：1) 扁平 dict；2) live_snapshot.parameters；3) items 数组格式 { items: [{ name, value }] }
        """
        def _from_flat(params: Any) -> Optional[float]:
            if not isinstance(params, dict):
                return None
            for key in ("vol_reset_threshold", "target_vol", "volatility_threshold"):
                v = params.get(key)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        pass
            return None

        def _from_items(params: Any) -> Optional[float]:
            if not isinstance(params, dict):
                return None
            items = params.get("items")
            if not isinstance(items, list):
                return None
            key_to_val = {}
            for it in items:
                if isinstance(it, dict) and "name" in it and "value" in it:
                    key_to_val[it["name"]] = it["value"]
            for key in ("vol_reset_threshold", "target_vol", "volatility_threshold"):
                v = key_to_val.get(key)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        pass
            return None

        # 1) 优先 model.parameters
        v = _from_flat(model.parameters) or _from_items(model.parameters)
        if v is not None:
            return v
        # 2) 再试 live_snapshot.parameters
        snapshot = model.live_snapshot or {}
        snap_params = snapshot.get("parameters") if isinstance(snapshot, dict) else None
        if snap_params is not None:
            v = _from_flat(snap_params) if isinstance(snap_params, dict) else None
            if v is None and isinstance(snap_params, dict):
                v = _from_items(snap_params)
            if v is not None:
                return v
        return None

    def _build_live_snapshot(self, model: StrategyModel) -> Dict[str, Any]:
        # 与监控运行时一致：顶层 mom_windows 等并入 parameters 再落库，避免快照缺键与运行时 overlay 不一致
        merged_params = merge_parameters_with_top_level_windows(model, model.parameters)
        return {
            "name": model.name,
            "template_code": model.template_code,
            "asset_codes": model.asset_codes,
            "parameters": merged_params,
            "rebalance_frequency": model.rebalance_frequency,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }

    async def log_live_change(
        self,
        model_id: str,
        action: str,
        source: str,
        operator: Optional[str],
        live_version: Optional[int],
        before: Dict[str, Any],
        after: Dict[str, Any],
        change_summary: Optional[str] = None,
        monitor_scoped_changes: Optional[Dict[str, Any]] = None,
    ) -> str:
        log_doc = {
            "model_id": model_id,
            "action": action,
            "source": source or "unknown",
            "operator": operator,
            "live_version": live_version,
            "before": before or {},
            "after": after or {},
            "change_summary": change_summary,
            "created_at": datetime.now(),
        }
        if monitor_scoped_changes is not None:
            log_doc["monitor_scoped_changes"] = monitor_scoped_changes
        result = await self.live_change_collection.insert_one(log_doc)
        return str(result.inserted_id)

    async def live_publish_model(
        self,
        model_id: str,
        source: str = "strategy",
        operator: Optional[str] = None,
        rebalance_mode: Optional[LiveRebalanceMode] = None,
        volatility_threshold: Optional[float] = None,
    ) -> bool:
        model = await self.get_model(model_id)
        if not model:
            return False
        if model.status == ModelStatus.ARCHIVED:
            raise ValueError("已归档模型不能实盘发布")

        now = datetime.now()
        live_version = (model.live_version or 0) + 1
        next_trade_day = self._next_trade_datetime(now)
        next_mode = rebalance_mode or model.live_rebalance_mode or LiveRebalanceMode.AUTO
        next_threshold = (
            volatility_threshold
            if volatility_threshold is not None
            else (model.live_volatility_threshold or self._extract_volatility_from_params(model))
        )
        def _mode_val(v):
            if v is None:
                return None
            s = str(v).lower()
            return "manual" if "manual" in s else ("auto" if "auto" in s or s == "auto" else None)

        snapshot = self._build_live_snapshot(model)
        before = {
            "live_publish_enabled": model.live_publish_enabled,
            "live_version": model.live_version,
            "live_effective_date": model.live_effective_date.isoformat() if model.live_effective_date else None,
            "live_rebalance_mode": _mode_val(model.live_rebalance_mode),
            "live_volatility_threshold": model.live_volatility_threshold,
            "live_snapshot_outdated": model.live_snapshot_outdated,
        }
        update_data = {
            "live_publish_enabled": True,
            "live_published_at": now,
            "live_effective_date": next_trade_day,
            "live_rebalance_mode": next_mode,
            "live_volatility_threshold": next_threshold,
            "live_version": live_version,
            "live_snapshot": snapshot,
            "live_snapshot_outdated": False,
            "updated_at": now,
        }
        result = await self.collection.update_one({"_id": ObjectId(model_id)}, {"$set": update_data})
        if result.modified_count > 0:
            after_log = {**update_data}
            if "live_rebalance_mode" in after_log:
                after_log["live_rebalance_mode"] = _mode_val(after_log["live_rebalance_mode"])
            model_after = await self.get_model(model_id)
            scoped_diff = {}
            summary_zh = "实盘发布"
            if model_after:
                old_snap = model.live_snapshot if isinstance(model.live_snapshot, dict) else {}
                new_snap = (
                    model_after.live_snapshot if isinstance(model_after.live_snapshot, dict) else {}
                )
                # 前后均用「快照 parameters + 顶层窗口 overlay」解析，与 monitor_runtime 一致，避免一侧缺键走默认、一侧有 overlay 导致误报无变更
                before_scoped = extract_monitor_scoped_from_published_snapshot(
                    old_snap,
                    getattr(model, "live_volatility_threshold", None),
                    model,
                )
                after_scoped = extract_monitor_scoped_from_published_snapshot(
                    new_snap,
                    getattr(model_after, "live_volatility_threshold", None),
                    model_after,
                )
                runtime_diff = compute_monitor_scoped_diff(
                    align_scoped_for_live_publish(before_scoped),
                    align_scoped_for_live_publish(after_scoped),
                )
                snapshot_diff = compute_snapshot_frozen_monitor_diff(
                    old_snap,
                    snapshot,
                    model,
                    model_after,
                    getattr(model, "live_volatility_threshold", None),
                    getattr(model_after, "live_volatility_threshold", None),
                )
                scoped_diff = merge_runtime_and_snapshot_diff(runtime_diff, snapshot_diff)
                scoped_diff = filter_monitor_scoped_diff_for_subjective_template(
                    scoped_diff, getattr(model_after, "template_code", None)
                )
                if scoped_diff:
                    names = _merge_model_asset_name_maps(model, model_after)
                    names = await self._enrich_asset_name_map_from_db(names, scoped_diff)
                    scoped_diff = rewrite_resolved_asset_list_diff_for_display(
                        scoped_diff, names
                    )
                scoped_diff = drop_live_version_from_scoped_diff(scoped_diff)
                extra = summarize_monitor_scoped_diff_zh(scoped_diff)
                if extra:
                    summary_zh = extra
            await self.log_live_change(
                model_id=model_id,
                action="live_publish",
                source=source,
                operator=operator,
                live_version=live_version,
                before=before,
                after=after_log,
                change_summary=summary_zh,
                monitor_scoped_changes=scoped_diff if scoped_diff else None,
            )
            return True
        return False

    async def live_unpublish_model(
        self,
        model_id: str,
        source: str = "strategy",
        operator: Optional[str] = None,
    ) -> bool:
        model = await self.get_model(model_id)
        if not model:
            return False
        before = {
            "live_publish_enabled": model.live_publish_enabled,
            "live_version": model.live_version,
            "live_effective_date": model.live_effective_date.isoformat() if model.live_effective_date else None,
        }
        update_data = {
            "live_publish_enabled": False,
            "updated_at": datetime.now(),
        }
        result = await self.collection.update_one({"_id": ObjectId(model_id)}, {"$set": update_data})
        if result.modified_count > 0:
            model_after = await self.get_model(model_id)
            scoped_diff = {}
            summary_zh = "取消实盘发布"
            if model_after:
                before_scoped = extract_monitor_scoped_from_model(model)
                after_scoped = extract_monitor_scoped_from_model(model_after)
                scoped_diff = compute_monitor_scoped_diff(before_scoped, after_scoped)
                scoped_diff = filter_monitor_scoped_diff_for_subjective_template(
                    scoped_diff, getattr(model_after, "template_code", None)
                )
                scoped_diff = drop_live_version_from_scoped_diff(scoped_diff)
                extra = summarize_monitor_scoped_diff_zh(scoped_diff)
                if extra:
                    summary_zh = extra
            await self.log_live_change(
                model_id=model_id,
                action="live_unpublish",
                source=source,
                operator=operator,
                live_version=model.live_version,
                before=before,
                after=update_data,
                change_summary=summary_zh,
                monitor_scoped_changes=scoped_diff if scoped_diff else None,
            )
            return True
        return False

    async def update_live_config(
        self,
        model_id: str,
        source: str = "live_monitoring",
        operator: Optional[str] = None,
        rebalance_mode: Optional[LiveRebalanceMode] = None,
        volatility_threshold: Optional[float] = None,
    ) -> bool:
        model = await self.get_model(model_id)
        if not model:
            return False
        def _mode_val(v):
            if v is None:
                return None
            s = str(v).lower()
            return "manual" if "manual" in s else ("auto" if "auto" in s or s == "auto" else None)

        before_mode = _mode_val(model.live_rebalance_mode) or "-"
        before = {
            "live_rebalance_mode": before_mode if before_mode != "-" else None,
            "live_volatility_threshold": model.live_volatility_threshold,
        }
        update_data: Dict[str, Any] = {"updated_at": datetime.now()}
        if rebalance_mode is not None:
            update_data["live_rebalance_mode"] = _mode_val(rebalance_mode) or "auto"
        if volatility_threshold is not None:
            vt = float(volatility_threshold)
            update_data["live_volatility_threshold"] = vt
            # 同步到 parameters，便于与监控运行时、列表摘要（合并快照+当前参数）一致
            params = dict(model.parameters) if model.parameters else {}
            params["vol_reset_threshold"] = vt
            update_data["parameters"] = params
        if len(update_data) == 1:
            return True

        # 构建可读的变更摘要（中文显示）
        mode_labels = {"auto": "自动调仓", "manual": "手动调仓"}
        parts = []
        if rebalance_mode is not None and _mode_val(rebalance_mode) != _mode_val(model.live_rebalance_mode):
            old_label = mode_labels.get(before.get("live_rebalance_mode"), before.get("live_rebalance_mode", "-"))
            new_label = mode_labels.get(update_data["live_rebalance_mode"], update_data["live_rebalance_mode"])
            parts.append(f"调仓模式: {old_label} → {new_label}")
        if volatility_threshold is not None and volatility_threshold != model.live_volatility_threshold:
            old_v = before.get("live_volatility_threshold")
            old_s = f"{old_v:.4f}" if old_v is not None else "-"
            parts.append(f"波动率阈值: {old_s} → {volatility_threshold:.4f}")
        change_summary = "; ".join(parts) if parts else "参数配置更新"

        result = await self.collection.update_one({"_id": ObjectId(model_id)}, {"$set": update_data})
        if result.modified_count > 0:
            after_mode = update_data.get("live_rebalance_mode") if "live_rebalance_mode" in update_data else before.get("live_rebalance_mode")
            after_log = {
                "live_rebalance_mode": after_mode,
                "live_volatility_threshold": update_data.get("live_volatility_threshold", model.live_volatility_threshold),
            }
            model_after = await self.get_model(model_id)
            scoped_diff = {}
            if model_after:
                before_scoped = extract_monitor_scoped_from_model(model)
                after_scoped = extract_monitor_scoped_from_model(model_after)
                scoped_diff = compute_monitor_scoped_diff(before_scoped, after_scoped)
                scoped_diff = filter_monitor_scoped_diff_for_subjective_template(
                    scoped_diff, getattr(model_after, "template_code", None)
                )
                if scoped_diff:
                    names = _merge_model_asset_name_maps(model, model_after)
                    names = await self._enrich_asset_name_map_from_db(names, scoped_diff)
                    scoped_diff = rewrite_resolved_asset_list_diff_for_display(
                        scoped_diff, names
                    )
                scoped_diff = drop_live_version_from_scoped_diff(scoped_diff)
                extra = summarize_monitor_scoped_diff_zh(scoped_diff)
                if extra:
                    if change_summary and change_summary != "参数配置更新":
                        change_summary = f"{change_summary}；{extra}"
                    else:
                        change_summary = extra
            await self.log_live_change(
                model_id=model_id,
                action="live_config_update",
                source=source,
                operator=operator,
                live_version=model.live_version,
                before=before,
                after=after_log,
                change_summary=change_summary,
                monitor_scoped_changes=scoped_diff if scoped_diff else None,
            )
            return True
        return False

    async def list_live_models(self, skip: int = 0, limit: int = 100) -> List[StrategyModel]:
        cursor = (
            self.collection.find({"live_publish_enabled": True})
            .skip(skip)
            .limit(limit)
            .sort("updated_at", -1)
        )
        models = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            models.append(StrategyModel(**doc))
        return models

    async def list_live_eligible_monitor_models(
        self, skip: int = 0, limit: int = 100
    ) -> List[StrategyModel]:
        """
        日常监控准入：已实盘发布，且为
        - risk_budget_target_vol + 混合动量 (selector_type=hybrid)，或
        - 主观配置模板 manual_allocation / manual_allocation_strategy，或
        - etf_cycle_rotation，或
        - risk_parity。
        """
        query = {
            "live_publish_enabled": True,
            "$or": [
                {"template_code": "risk_budget_target_vol", "selector_type": "hybrid"},
                {"template_code": "manual_allocation"},
                {"template_code": "manual_allocation_strategy"},
                {"template_code": "etf_cycle_rotation"},
                {"template_code": "risk_parity"},
            ],
        }
        cursor = (
            self.collection.find(query)
            .skip(skip)
            .limit(limit)
            .sort("updated_at", -1)
        )
        models: List[StrategyModel] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            models.append(StrategyModel(**doc))
        return models

    async def has_live_eligible_monitor_model(self) -> bool:
        rows = await self.list_live_eligible_monitor_models(skip=0, limit=1)
        return len(rows) > 0

    async def list_live_change_logs(self, model_id: str, skip: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = (
            self.live_change_collection.find({"model_id": model_id})
            .skip(skip)
            .limit(limit)
            .sort("created_at", -1)
        )
        rows: List[Dict[str, Any]] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            rows.append(doc)
        return rows

    async def save_live_monitoring_snapshot(self, model_id: str, payload: Dict[str, Any]) -> str:
        doc = {
            "model_id": model_id,
            "created_at": datetime.now(),
            "payload": payload,
        }
        result = await self.live_monitoring_collection.insert_one(doc)
        return str(result.inserted_id)

    async def get_latest_live_monitoring_snapshot(self, model_id: str) -> Optional[Dict[str, Any]]:
        doc = await self.live_monitoring_collection.find_one(
            {"model_id": model_id},
            sort=[("created_at", -1)],
        )
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        return doc

    async def confirm_manual_rebalance(
        self,
        model_id: str,
        decision: str,
        operator: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> bool:
        model = await self.get_model(model_id)
        if not model:
            return False
        action = "manual_rebalance_confirmed" if decision == "confirm" else "manual_rebalance_skipped"
        await self.log_live_change(
            model_id=model_id,
            action=action,
            source="live_monitoring",
            operator=operator,
            live_version=model.live_version,
            before={},
            after={"decision": decision, "comment": comment},
        )
        return True
    
    async def save_backtest_record(self, record: BacktestRecord) -> str:
        """保存回测记录"""
        record_dict = record.dict(by_alias=True, exclude={'id'})
        result = await self.backtest_collection.insert_one(record_dict)
        return str(result.inserted_id)

    async def update_backtest_record_remark(self, record_id: str, model_id: str, remark: Optional[str]) -> bool:
        """更新回测记录备注"""
        result = await self.backtest_collection.update_one(
            {"_id": ObjectId(record_id), "model_id": model_id},
            {"$set": {"remark": remark if remark is not None else ""}}
        )
        return result.matched_count > 0

    def to_backtest_request(self, model: StrategyModel, start_date: str, end_date: str, **overrides) -> Dict[str, Any]:
        """
        将策略模型转换为回测请求参数
        
        这个方法方便前端从策略模型配置生成回测请求。
        
        Args:
            model: 策略模型实例
            start_date: 回测开始日期（格式：YYYYMMDD）
            end_date: 回测结束日期（格式：YYYYMMDD）
            **overrides: 覆盖参数（可选）
        
        Returns:
            回测请求参数字典，可直接用于 POST /api/v1/backtests/run
        
        Example:
            >>> model = await service.get_model(model_id)
            >>> request_data = service.to_backtest_request(
            ...     model,
            ...     start_date="20230101",
            ...     end_date="20231231",
            ...     initial_cash=5000000  # 覆盖初始资金
            ... )
            >>> # 前端可以直接使用 request_data 调用回测 API
        """
        # 调仓频率映射：中文 -> 英文
        freq_mapping = {
            "日": "daily",
            "周": "weekly",
            "月": "monthly",
            "季": "quarterly",
            "年": "yearly",
            "daily": "daily",
            "weekly": "weekly",
            "monthly": "monthly",
            "quarterly": "quarterly",
            "yearly": "yearly"
        }
        
        rebalance_freq = freq_mapping.get(model.rebalance_frequency, "monthly")
        
        strategy_params = overrides.get("strategy_params", model.parameters)
        if isinstance(strategy_params, str):
            import json
            try:
                strategy_params = json.loads(strategy_params.replace("'", '"'))
            except Exception:
                pass
        
        # 清理和转换策略参数，确保字典类型参数格式正确
        if isinstance(strategy_params, dict):
            import json
            cleaned_params = {}
            for key, value in strategy_params.items():
                # 处理 max_weight_dict 参数
                if key == "max_weight_dict":
                    if isinstance(value, str):
                        try:
                            parsed = json.loads(value)
                            # 确保解析后是字典
                            if isinstance(parsed, dict):
                                cleaned_params[key] = parsed
                            else:
                                # 如果不是字典，使用空字典
                                cleaned_params[key] = {}
                        except Exception:
                            # 解析失败，使用空字典
                            cleaned_params[key] = {}
                    elif isinstance(value, dict):
                        cleaned_params[key] = value
                    else:
                        # 其他类型（如数值），使用空字典
                        cleaned_params[key] = {}
                # 处理 _asset_tags 参数
                elif key == "_asset_tags":
                    if isinstance(value, str):
                        try:
                            parsed = json.loads(value)
                            if isinstance(parsed, dict):
                                cleaned_params[key] = parsed
                            else:
                                cleaned_params[key] = {}
                        except Exception:
                            cleaned_params[key] = {}
                    elif isinstance(value, dict):
                        cleaned_params[key] = value
                    else:
                        cleaned_params[key] = {}
                else:
                    # 其他参数直接传递
                    cleaned_params[key] = value
            strategy_params = cleaned_params
        
        request_data = {
            "name": overrides.get("name", f"{model.name}_回测"),
            "strategy_type": model.template_code,  # 模板代码就是策略类型
            "strategy_params": strategy_params,
            "thscodes": overrides.get("thscodes", model.asset_codes),
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": overrides.get("initial_cash", 10_000_000.0),
            "rebalance_freq": overrides.get("rebalance_freq", rebalance_freq),
            "commission_rate": overrides.get("commission_rate", 0.0003),
            "slippage": overrides.get("slippage", 0.0005),
            "lookback_days": overrides.get("lookback_days", 500)
        }
        
        return request_data