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
from loguru import logger

from app.models.strategy_model import StrategyModel, ModelStatus, LiveRebalanceMode
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
    merge_runtime_and_snapshot_diff,
    rewrite_resolved_asset_list_diff_for_display,
    summarize_monitor_scoped_diff_zh,
)
from app.services.published_snapshot import (
    build_published_snapshot,
    compute_config_fingerprint,
)
from app.services.live_portfolio_usage import ensure_not_used_by_live_portfolio
from app.services.strategy_data_contract_service import enforce_static_contract
from app.services.strategy_model_service import (
    StrategyModelService,
    _merge_model_asset_name_maps,
)
from app.services.strategy_version_service import StrategyVersionService


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

    async def publish_model(
        self, model_id: str, source: str = "strategy", operator: Optional[str] = None
    ) -> bool:
        """发布模型：冻结配置快照，发布版本 +1。

        仅草稿可发布；发布后全部配置字段锁定，如需修改先取消发布。
        发布前执行策略数据契约门禁（静态面 + 库侧资产大类），
        契约不满足即抛 DataContractError，使配置错误在发布时就拦住，
        不等到监控启动才发现。
        """
        model = await self._models.get_model(model_id)
        if not model:
            return False
        if model.status == ModelStatus.ARCHIVED:
            raise ValueError("已归档的模型不能发布")
        if model.status == ModelStatus.PUBLISHED:
            raise ValueError("模型已发布，如需修改请先取消发布")

        await enforce_static_contract(
            template_code=model.template_code,
            asset_codes=model.asset_codes or [],
            strategy_params=model.parameters or {},
            strategy_label=f"{model.name}（{model.template_code}）",
        )

        snapshot = await self._build_snapshot_with_universe(model)
        version = int(model.published_version or 0) + 1
        # 实盘参数变更（live_config_update）可能已占用该序号：顺延到下一个空号，
        # 否则 append_version 会幂等短路，本次发布正文不会入表。
        while await StrategyVersionService().get_version(model_id, version) is not None:
            version += 1
        fingerprint = compute_config_fingerprint(snapshot)
        now = datetime.now()
        update_data = {
            "status": ModelStatus.PUBLISHED,
            "published_at": now,
            "published_version": version,
            "published_snapshot": snapshot,
            "config_fingerprint": fingerprint,
            "updated_at": now,
        }
        result = await self.collection.update_one(
            {"_id": ObjectId(model_id)}, {"$set": update_data}
        )
        if result.modified_count > 0:
            # 先留档版本正文、再写变更日志：S15 审计转发要按 published_version
            # 反查到本条版本记录（两步都是 append-only，顺序不影响原返回值）。
            await self._append_published_version(
                model_id=model_id,
                model=model,
                version=version,
                snapshot=snapshot,
                fingerprint=fingerprint,
                source_action="publish",
                operator=operator,
            )
            await self.log_live_change(
                model_id=model_id,
                action="publish",
                source=source,
                operator=operator,
                live_version=None,
                before={
                    "status": str(model.status),
                    "published_version": model.published_version,
                },
                after={
                    "status": str(ModelStatus.PUBLISHED),
                    "published_version": version,
                    "config_fingerprint": fingerprint,
                },
                change_summary=f"发布 v{version}",
            )
            return True
        return False

    async def republish_model(
        self, model_id: str, source: str = "portfolio_edit", operator: Optional[str] = None
    ) -> bool:
        """已发布模型重发：按当前配置刷新发布快照，版本 +1。

        组合管理不暴露发布动作，编辑保存后由后端刷新快照，
        保证下次实盘发布使用最新配置，而不是编辑前的旧快照。
        """
        model = await self._models.get_model(model_id)
        if not model:
            return False
        if model.status != ModelStatus.PUBLISHED:
            raise ValueError("仅已发布模型可以刷新发布快照")
        if model.live_publish_enabled:
            raise ValueError("实盘中模型不能刷新发布快照，请先取消实盘")

        snapshot = await self._build_snapshot_with_universe(model)
        version = int(model.published_version or 0) + 1
        # 实盘参数变更（live_config_update）可能已占用该序号：顺延到下一个空号
        while await StrategyVersionService().get_version(model_id, version) is not None:
            version += 1
        fingerprint = compute_config_fingerprint(snapshot)
        now = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(model_id)},
            {
                "$set": {
                    "published_at": now,
                    "published_version": version,
                    "published_snapshot": snapshot,
                    "config_fingerprint": fingerprint,
                    "updated_at": now,
                }
            },
        )
        if result.modified_count > 0:
            # 与 publish 同序：先留档版本正文，再写变更日志（S15 审计需要反查版本）。
            await self._append_published_version(
                model_id=model_id,
                model=model,
                version=version,
                snapshot=snapshot,
                fingerprint=fingerprint,
                source_action="republish",
                operator=operator,
            )
            await self.log_live_change(
                model_id=model_id,
                action="republish",
                source=source,
                operator=operator,
                live_version=model.live_version,
                before={
                    "published_version": model.published_version,
                    "config_fingerprint": model.config_fingerprint,
                },
                after={"published_version": version, "config_fingerprint": fingerprint},
                change_summary=f"编辑后刷新发布快照 v{version}",
            )
            return True
        return False

    async def _build_snapshot_with_universe(self, model: StrategyModel) -> Dict[str, Any]:
        """构建发布快照；模型绑定了资产池时解析当前生效版本一并冻结（S09）.

        未绑定 ``parameters["asset_universe_ref"]`` 的模型不会查库（直接返回），
        发布主链路行为不变。解析失败只 warn，快照里保留 ref、版本号写 None，
        不把「没解析到」伪装成「没有绑定」。
        """
        universe_version: Optional[Dict[str, Any]] = None
        try:
            from app.services.asset_universe_service import AssetUniverseService

            active = await AssetUniverseService().resolve_active_for_model(model)
            if active is not None:
                universe_version = active.model_dump()
        except Exception as exc:  # noqa: BLE001 —— 解析失败不阻断发布
            logger.warning(f"[published_snapshot] 资产池版本解析失败（按未解析处理）: {exc}")
        return build_published_snapshot(model, universe_version=universe_version)

    async def _append_published_version(
        self,
        model_id: str,
        model: StrategyModel,
        version: int,
        snapshot: Dict[str, Any],
        fingerprint: str,
        source_action: str,
        operator: Optional[str],
    ) -> None:
        """发布成功后追加配置版本正文（append-only）.

        约束：整块 try/except，失败只 warn，**不改变原返回值与 return 分支**；
        正文整份复制（不引用 published_snapshot），否则下一次发布就覆盖了
        上一版的可回溯内容。
        """
        try:
            version_id = await StrategyVersionService().append_version(
                model_id=model_id,
                version_no=version,
                source_action=source_action,
                snapshot_body=snapshot,
                config_fingerprint=fingerprint,
                template_code=getattr(model, "template_code", None),
                operator=operator,
            )
            if version_id:
                logger.info(
                    "[strategy_versions] %s v%s 留档 version_id=%s model_id=%s",
                    source_action, version, version_id, model_id,
                )
        except Exception as exc:  # noqa: BLE001 —— 留档失败不得影响发布主流程
            logger.warning(f"[strategy_versions] 发布版本追加失败（不影响发布）: {exc}")

    async def _append_live_config_version(
        self,
        model_id: str,
        model: StrategyModel,
        snapshot: Dict[str, Any],
        fingerprint: str,
        operator: Optional[str],
    ) -> None:
        """实盘参数变更后追加一条配置版本正文（append-only）。

        版本号取「发布版本与既有版本链最大序号 + 1」：实盘调参不推进
        published_version，但必须占用新的 version_no，否则会与发布版本撞号
        （append_version 幂等短路后本次正文丢失）。失败只 warn，不改变
        update_live_config 的返回值。
        """
        try:
            service = StrategyVersionService()
            latest = await service.latest_version(model_id)
            version_no = max(
                int(model.published_version or 0),
                int(latest.version_no) if latest else 0,
            ) + 1
            version_id = await service.append_version(
                model_id=model_id,
                version_no=version_no,
                source_action="live_config_update",
                snapshot_body=snapshot,
                config_fingerprint=fingerprint,
                template_code=getattr(model, "template_code", None),
                operator=operator,
            )
            if version_id:
                logger.info(
                    "[strategy_versions] live_config_update v%s 留档 version_id=%s model_id=%s",
                    version_no, version_id, model_id,
                )
        except Exception as exc:  # noqa: BLE001 —— 留档失败不得影响实盘调参主流程
            logger.warning(f"[strategy_versions] 实盘配置版本追加失败（不影响配置更新）: {exc}")

    async def unpublish_model(
        self, model_id: str, source: str = "strategy", operator: Optional[str] = None
    ) -> bool:
        """取消发布：回到草稿，允许编辑。

        发布与实盘发布是递进关系：已实盘发布的模型先取消实盘（监控下架），
        所有历史记录（变更日志、监控状态、参数版本、回测记录）均保留。
        """
        model = await self._models.get_model(model_id)
        if not model:
            return False
        if model.status != ModelStatus.PUBLISHED:
            raise ValueError("仅已发布的模型可以取消发布")

        # 被实盘组合引用时禁止取消发布：成员退回草稿会中断组合的日常监控
        await ensure_not_used_by_live_portfolio(self.collection, model_id, "取消发布")

        was_live = bool(model.live_publish_enabled)
        if was_live:
            await self.live_unpublish_model(model_id, source=source, operator=operator)

        now = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(model_id)},
            {"$set": {"status": ModelStatus.DRAFT, "updated_at": now}},
        )
        if result.modified_count > 0:
            await self._archive_monitored_entries(model_id, "unpublish")
            await self.log_live_change(
                model_id=model_id,
                action="unpublish",
                source=source,
                operator=operator,
                live_version=model.live_version,
                before={
                    "status": str(model.status),
                    "published_version": model.published_version,
                    "live_publish_enabled": was_live,
                },
                after={
                    "status": str(ModelStatus.DRAFT),
                    "live_publish_enabled": False,
                },
                change_summary="取消发布（回到草稿，历史记录保留）",
            )
            return True
        return False

    async def _archive_monitored_entries(self, model_id: str, reason: str) -> None:
        """归档监控条目（不删除 monitor_states 等历史数据）。"""
        from app.config.collections import COL_MONITORED_STRATEGIES

        now = datetime.now()
        await self._models.db[COL_MONITORED_STRATEGIES].update_many(
            {"source_ref": model_id, "status": {"$ne": "archived"}},
            {
                "$set": {
                    "status": "archived",
                    "archive_reason": reason,
                    "archived_at": now,
                    "updated_at": now,
                }
            },
        )

    async def _next_trade_datetime(self, base_time: datetime) -> datetime:
        """获取基准时点后的下一个交易日（00:00:00）。

        日历以资产行情日期为主：历史段用 asset_prices 实际日期，晚于资产覆盖
        范围的未来段按资产星期模式外推（time_norm.next_forward_trade_day）。
        不再依赖 Mongo trade_dates 集合（仅研究员策略 sharpe_18/hybrid_12 使用）。
        资产行情日历为空（无价格数据）时降级为 T+1 自然日并记 warning。
        """
        from app.monitor.data_provider import MongoDataProvider
        from app.monitor.time_norm import next_forward_trade_day

        asset_dates = await MongoDataProvider().load_asset_price_dates()
        next_ds = next_forward_trade_day(asset_dates, base_time)
        if next_ds:
            return datetime.strptime(next_ds, "%Y-%m-%d")
        logger.warning("资产行情日历为空，实盘发布生效日降级为 T+1 自然日")
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
        """实盘快照 = 发布快照副本（实盘只读发布冻结内容，不再读当前文档）。"""
        published = model.published_snapshot or {}
        if not published:
            raise ValueError(
                f"模型「{model.name}」缺少发布快照，请重新发布后再实盘发布"
            )
        snapshot = dict(published)
        snapshot["source_published_version"] = model.published_version
        snapshot["frozen_at"] = datetime.now().isoformat()
        return snapshot

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
        # 治理审计（S15）：本方法是 5 个状态动作的唯一漏斗，这里把同一动作
        # 投影成结构化事件 + 血缘边；转发失败只 warn，不影响原日志 ID。
        try:
            from app.services.strategy_audit_service import StrategyAuditService

            await StrategyAuditService().record_action(
                model_id=model_id,
                action=action,
                source=source,
                operator=operator,
            )
        except Exception as exc:  # noqa: BLE001 —— 审计旁路不得影响变更日志
            logger.warning(f"[strategy_audit] 治理事件转发失败: {exc}")
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
        if model.status != ModelStatus.PUBLISHED:
            raise ValueError("仅已发布模型可以实盘发布，请先发布")
        if not (model.published_snapshot or {}):
            raise ValueError("模型缺少发布快照，请重新发布后再实盘发布")

        # 生命周期准入（S14）：LIFECYCLE_ENFORCE=False 时零副作用（不查库、不写事件）。
        # 仅允许 paper → live；research/shadow 直接调实盘发布会被拒并留 rejected 事件。
        from app.services.strategy_lifecycle_service import StrategyLifecycleService

        await StrategyLifecycleService().enforce(
            "live",
            model,
            action="live_publish",
            operator=operator,
            source=source,
        )

        now = datetime.now()
        live_version = (model.live_version or 0) + 1
        next_trade_day = await self._next_trade_datetime(now)
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
            "live_published_version": model.published_version,
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
        1. 复制组合发布快照（成员/权重/权重模型参数/初始净值/调仓频率）为 live_snapshot
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
        if model.status != ModelStatus.PUBLISHED:
            # 组合管理不暴露发布动作：实盘发布即冻结当前配置
            await self.publish_model(model_id, source=source, operator=operator)
            model = await self._models.get_model(model_id)
            if not model:
                raise ValueError(f"模型不存在: {model_id}")
        published = model.published_snapshot or {}
        if not published:
            raise ValueError(f"组合「{model.name}」缺少发布快照，请重新发布后再实盘发布")

        now = datetime.now()
        live_version = (model.live_version or 0) + 1

        # 实盘快照 = 发布快照副本，不重新读取当前文档
        snapshot = dict(published)
        snapshot["is_portfolio"] = True
        snapshot["source_published_version"] = model.published_version
        snapshot["frozen_at"] = now.isoformat()

        before = {
            "live_publish_enabled": model.live_publish_enabled,
            "live_version": model.live_version,
        }

        update_data = {
            "live_publish_enabled": True,
            "live_published_at": now,
            "live_version": live_version,
            "live_published_version": model.published_version,
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
            await self._archive_monitored_entries(model_id, "live_unpublish")
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
        if not model.live_publish_enabled:
            raise ValueError("模型未实盘发布，无法修改实盘配置")
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
        if rebalance_mode is None and volatility_threshold is None:
            return True

        # 实盘参数变更 = 一次配置变更：递增 live_version、重算快照指纹、追加版本正文。
        # 否则 model.config_fingerprint 仍是上一份快照的值，而监控运行记录
        # （config_versions.config_fingerprint 取 model.config_fingerprint）与实际
        # 生效的 live_snapshot 对不上。
        new_snapshot = dict(model.live_snapshot or {})
        if volatility_threshold is not None:
            vt = float(volatility_threshold)
            # 只改实盘快照，不回头修改已冻结的发布配置
            snap_params = dict(new_snapshot.get("parameters") or {})
            snap_params["vol_reset_threshold"] = vt
            new_snapshot["parameters"] = snap_params
            new_snapshot["live_volatility_threshold"] = vt
        new_fingerprint = compute_config_fingerprint(new_snapshot)
        update_data: Dict[str, Any] = {
            "updated_at": datetime.now(),
            "live_version": int(model.live_version or 0) + 1,
            "live_snapshot": new_snapshot,
            "config_fingerprint": new_fingerprint,
        }
        if rebalance_mode is not None:
            update_data["live_rebalance_mode"] = _mode_val(rebalance_mode) or "auto"
        if volatility_threshold is not None:
            update_data["live_volatility_threshold"] = float(volatility_threshold)

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
            # 版本正文先留档（append-only），再写变更日志；失败只 warn 不影响返回值
            await self._append_live_config_version(
                model_id=model_id,
                model=model,
                snapshot=new_snapshot,
                fingerprint=new_fingerprint,
                operator=operator,
            )
            await self.log_live_change(
                model_id=model_id,
                action="live_config_update",
                source=source,
                operator=operator,
                live_version=update_data["live_version"],
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
