"""
实盘发布服务层

职责：策略/组合模型的实盘发布、取消发布、实盘配置更新、
实盘变更日志与监控快照的读写（从 strategy_model_service 拆分而来）。

依赖方向：LivePublishService → StrategyModelService（单向，无环）。
"""
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from bson import ObjectId
import pandas as pd

from app.models.strategy_model import StrategyModel, ModelStatus, LiveRebalanceMode
from app.data.trade_dates import load_trade_dates, get_future_trade_dates
from app.monitor.monitor_runtime import (
    config_baseline_eligible_strategy_dict,
    live_effective_display_bundle,
    live_effective_asset_display_labels,
    live_effective_structured_params,
    normalize_strategy_asset_codes,
)
from app.monitor.live_publish_log_scope import (
    align_scoped_for_live_publish,
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
from app.services.strategy_model_service import (
    StrategyModelService,
    _merge_model_asset_name_maps,
)


class LivePublishService:
    """实盘发布服务 - 实盘发布/配置/变更日志/监控快照"""

    def __init__(self, model_service: Optional[StrategyModelService] = None):
        self._models = model_service or StrategyModelService()

    @property
    def collection(self):
        return self._models.collection

    @property
    def live_change_collection(self):
        return self._models.live_change_collection

    @property
    def live_monitoring_collection(self):
        return self._models.live_monitoring_collection

    # ------------------------------------------------------------------
    # 实盘生效展示字段（实盘发布 ↔ 监控互通，从 API 层下沉）
    # ------------------------------------------------------------------

    @staticmethod
    def live_effective_fields(
        model: StrategyModel,
        asset_names: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[str], Optional[List[str]], Optional[List[str]]]:
        """实盘摘要文案 + 监控资产标识列表 + 同序展示名称列表（仅已实盘发布快照，不含未发布草稿）。"""
        codes_list = normalize_strategy_asset_codes(getattr(model, "asset_codes", None))
        summary, assets = live_effective_display_bundle(
            model.live_publish_enabled,
            model.live_snapshot or {},
            model.live_volatility_threshold,
            current_parameters=model.parameters,
            current_asset_codes=codes_list,
            asset_names=asset_names,
            published_only=True,
        )
        labels = live_effective_asset_display_labels(assets, asset_names)
        return summary, assets, labels

    @staticmethod
    def live_effective_params(model: StrategyModel) -> Optional[Dict[str, Any]]:
        """实盘生效结构化参数（仅已发布快照），供监控准入策略展示。"""
        codes_list = normalize_strategy_asset_codes(getattr(model, "asset_codes", None))
        return live_effective_structured_params(
            model.live_publish_enabled,
            model.live_snapshot or {},
            model.live_volatility_threshold,
            current_parameters=model.parameters,
            current_asset_codes=codes_list,
            model_for_selection=model,
            published_only=True,
        )

    async def build_config_baseline_strategy(self, asset_service) -> Dict[str, Any]:
        """构造配置基准策略的监控准入条目（基于 monitor 全局配置资产清单）。"""
        from app.monitor import config as monitor_config

        baseline_asset_names: Dict[str, str] = {}
        for nm in monitor_config.ASSET_LIST:
            code = monitor_config.ASSET_NAME_TO_CODE.get(nm)
            if not code:
                continue
            asset_info = await asset_service.get_asset_by_code(code)
            baseline_asset_names[code] = asset_info.name if asset_info else code
        return config_baseline_eligible_strategy_dict(baseline_asset_names)

    async def publish_model(self, model_id: str) -> bool:
        """发布模型"""
        model = await self._models.get_model(model_id)
        if not model:
            return False
        
        # 移除回测状态检查，只要是草稿状态就可以发布
        if model.status == ModelStatus.ARCHIVED:
            raise ValueError("已归档的模型不能发布")
        
        return await self._models.update_model(model_id, {
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
            "selector_type": model.selector_type,  # 资产选择器类型，monitor 路由键
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
        model = await self._models.get_model(model_id)
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
            model_after = await self._models.get_model(model_id)
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
                    names = await self._models._enrich_asset_name_map_from_db(names, scoped_diff)
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

    async def live_publish_portfolio_model(
        self,
        model_id: str,
        source: str = "strategy",
        operator: Optional[str] = None,
    ) -> bool:
        """
        发布组合模型（is_portfolio=True）。

        组合发布逻辑：
        1. 冻结当前 sub_strategies 配置为 live_snapshot
        2. 设置 live_publish_enabled = True
        3. 记录 live_change_log
        """
        model = await self._models.get_model(model_id)
        if not model:
            raise ValueError(f"模型不存在: {model_id}")
        if not model.is_portfolio:
            raise ValueError("此方法仅用于组合模型（is_portfolio=True）")
        if model.status == ModelStatus.ARCHIVED:
            raise ValueError("已归档模型不能发布")

        now = datetime.now()
        live_version = (model.live_version or 0) + 1

        # 构建组合快照：包含子策略配置
        snapshot = {
            "name": model.name,
            "is_portfolio": True,
            "sub_strategies": [
                {
                    "model_id": sub.get("model_id", ""),
                    "name": sub.get("name", ""),
                    "weight": sub.get("weight", 0),
                    "template_code": sub.get("template_code", ""),
                }
                for sub in (model.sub_strategies or [])
            ],
            "rebalance_frequency": model.rebalance_frequency,
            "initial_nav": getattr(model, "initial_nav", 1000),
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }

        before = {
            "live_publish_enabled": model.live_publish_enabled,
            "live_version": model.live_version,
        }

        update_data = {
            "live_publish_enabled": True,
            "live_published_at": now,
            "live_version": live_version,
            "live_snapshot": snapshot,
            "live_snapshot_outdated": False,
            "updated_at": now,
        }

        result = await self.collection.update_one(
            {"_id": ObjectId(model_id)}, {"$set": update_data}
        )

        if result.modified_count > 0:
            after_log = {
                "live_publish_enabled": True,
                "live_version": live_version,
                "sub_strategies": snapshot["sub_strategies"],
            }
            await self.log_live_change(
                model_id=model_id,
                action="live_publish_portfolio",
                source=source,
                operator=operator,
                live_version=live_version,
                before=before,
                after=after_log,
                change_summary="组合模型实盘发布",
            )
            return True
        return False

    async def live_unpublish_model(
        self,
        model_id: str,
        source: str = "strategy",
        operator: Optional[str] = None,
    ) -> bool:
        model = await self._models.get_model(model_id)
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
            model_after = await self._models.get_model(model_id)
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
        model = await self._models.get_model(model_id)
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
            model_after = await self._models.get_model(model_id)
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
                    names = await self._models._enrich_asset_name_map_from_db(names, scoped_diff)
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
        日常监控准入：已实盘发布的策略均可进入监控。
        任何 live_publish_enabled=True 的策略均可进入监控，
        由下游 engine_adapter 动态解析 allocator，无需白名单。
        """
        query = {"live_publish_enabled": True}
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
        model = await self._models.get_model(model_id)
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
