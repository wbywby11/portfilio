"""
回测记录服务层

职责：回测记录的查询/保存/备注更新，以及模型配置 → 回测请求参数的转换
（从 strategy_model_service 拆分而来）。

依赖方向：BacktestService → StrategyModelService / ParamVersionService（单向，无环）。
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId
import pandas as pd
import numpy as np

from app.allocation.runtime_params import WEIGHT_CAPS_PARAM_NAMES, parse_mapping_param
from app.models.strategy_model import StrategyModel, BacktestRecord, RunKind, normalize_run_kind
from app.services.strategy_model_service import (
    StrategyModelService,
    resolve_full_params,
    build_backtest_params,
)
from app.services.param_version_service import ParamVersionService
from app.services.strategy_fingerprint import (
    param_hash,
    pool_hash,
    reproducibility_fingerprint,
)
from app.services.strategy_version_service import resolve_contract_hash
from app.services.strategy_run_service import StrategyRunService, build_run_metrics
from app.config.settings import settings


# 参数版本匹配时忽略的易变键（与 strategy_fingerprint._VOLATILE_KEYS 同口径）
_VOLATILE_KEYS = frozenset({"created_at", "updated_at", "frozen_at", "published_at"})

# 需要归一为 dict 的参数：历史模型与前端表单可能把它们存成 JSON 字符串
_MAPPING_PARAM_KEYS = frozenset(WEIGHT_CAPS_PARAM_NAMES) | {"_asset_tags"}


def build_run_kind_filter(run_kind: Optional[str]) -> Dict[str, Any]:
    """构造 ``backtest_records`` 的 run_kind 过滤片段.

    存量文档没有 ``run_kind`` 字段，因此「只要回测」必须用 ``$ne`` 而不是
    ``{"run_kind": "backtest"}`` —— 后者会把全部存量记录过滤掉。

    Args:
        run_kind: ``"backtest"``（默认）排除监控产物；``"monitor"`` 只取监控产物；
            ``None`` 不过滤。
    """
    if run_kind is None:
        return {}
    if normalize_run_kind(run_kind) == RunKind.MONITOR.value:
        return {"run_kind": RunKind.MONITOR.value}
    return {"run_kind": {"$ne": RunKind.MONITOR.value}}


def _param_version_matches(doc: Dict[str, Any], snapshot: Dict[str, Any]) -> bool:
    """参数版本与本次参数快照是否一致（替代「永远取最新版本」的旧语义）。

    ``param_snapshot`` 是 allocator + selector + controller **合并后**的扁平字典，
    而 ``strategy_param_versions`` 文档按三块分开存，二者无法直接比整份 hash。
    因此按「双方都有的键逐一相等」判定，并要求至少一个共同键：任一共同键不等
    即视为不同版本；没有任何共同键（如空参数策略）不参与匹配，回退最新版本。
    """
    flat: Dict[str, Any] = {}
    for part in ("allocator_params", "selector_params", "controller_params"):
        value = doc.get(part)
        if isinstance(value, dict):
            flat.update(value)
    for key in ("selector_type", "controller_code"):
        if doc.get(key) is not None:
            flat[key] = doc[key]
    flat.pop("selector_parameters", None)
    if not flat:
        return False
    common = 0
    for key, value in flat.items():
        if key in _VOLATILE_KEYS or key not in snapshot:
            continue
        common += 1
        if snapshot.get(key) != value:
            return False
    return common > 0


class BacktestService:
    """回测记录服务 - 回测记录 CRUD 与回测请求转换"""

    def __init__(
        self,
        model_service: Optional[StrategyModelService] = None,
        param_version_service: Optional[ParamVersionService] = None,
    ):
        self._models = model_service or StrategyModelService()
        self._param_versions = param_version_service or ParamVersionService()

    @property
    def collection(self):
        return self._models.collection

    @property
    def backtest_collection(self):
        return self._models.backtest_collection

    async def list_backtest_records(
        self,
        model_id: str,
        skip: int = 0,
        limit: int = 100,
        run_kind: Optional[str] = RunKind.BACKTEST.value,
    ) -> List[BacktestRecord]:
        """
        查询模型的回测记录列表
        
        Args:
            model_id: 模型ID
            skip: 跳过数量
            limit: 返回数量
            run_kind: 运行类型过滤。默认 ``backtest`` —— 排除监控批次产物
                （``run_kind=monitor``），保证策略详情的回测记录列表不被高频
                监控跑批污染；传 ``"monitor"`` 只取监控批次；传 ``None`` 不过滤。
            
        Returns:
            回测记录列表
        """
        query: Dict[str, Any] = {"model_id": model_id}
        query.update(build_run_kind_filter(run_kind))
        cursor = self.backtest_collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
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

    async def save_backtest_record(
        self,
        record: BacktestRecord,
        param_snapshot: Optional[Dict[str, Any]] = None,
        data_fingerprint: Optional[str] = None,
        identity: Optional[Dict[str, Any]] = None,
    ) -> str:
        """保存回测记录，并自动将绩效快照写入策略模型的 latest_backtest_summary。
        
        层间连接：第5层（策略验证）→ 第6层（策略入库）。
        每次保存回测记录时，自动提取核心绩效指标，更新对应策略模型，
        使策略列表中可直接展示最近回测绩效。
        
        参数快照（param_snapshot）：
        - 若调用方提供，则直接使用
        - 否则从当前模型状态自动生成
        - 快照一旦写入即为不可变，确保回测结果可追溯
        
        数据指纹（data_fingerprint）：
        - hash(asset_codes + start_date + end_date)
        - 用于检测相同参数但不同行情数据的情况
        
        同时自动关联当前最新的参数版本，建立版本-回测双向追溯。

        身份注入（identity，S12）：
        - 可选显式传入 ``{"strategy_id": ..., "config_version_id": ...}``，以传入值为准；
        - 未传入时按 ``record.model_id`` 反查 ``strategy_registry``（走 template_code）
          与最新 ``strategy_versions``，回填到记录字段；
        - 草稿模型通常没有发布版本，``config_version_id`` 保持 None。
        """
        # --- 读取模型一次：参数快照兜底、身份与指纹计算共用同一份数据 ---
        model = None
        try:
            model = await self._models.get_model(record.model_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "回测读取策略模型失败 model_id=%s: %s", record.model_id, e
            )

        # --- 自动生成参数快照（若未提供）---
        if param_snapshot is None and model is not None:
            try:
                param_snapshot = resolve_full_params(model)
                # 补充基础信息
                param_snapshot["template_code"] = model.template_code
                param_snapshot["asset_codes"] = list(model.asset_codes or [])
                param_snapshot["rebalance_frequency"] = model.rebalance_frequency
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "回测自动生成参数快照失败 model_id=%s: %s", record.model_id, e
                )
        
        # --- 自动生成数据指纹（若未提供）---
        if data_fingerprint is None:
            try:
                import hashlib
                fp_data = {
                    "asset_codes": sorted(record.result.asset_names.keys()) if record.result.asset_names else [],
                    "start_date": record.start_date.strftime("%Y-%m-%d") if hasattr(record.start_date, "strftime") else str(record.start_date),
                    "end_date": record.end_date.strftime("%Y-%m-%d") if hasattr(record.end_date, "strftime") else str(record.end_date),
                }
                import json
                data_fingerprint = hashlib.sha256(json.dumps(fp_data, sort_keys=True).encode()).hexdigest()[:16]
            except Exception:
                pass
        
        # 将快照和指纹写入 record
        if param_snapshot is not None:
            record.param_snapshot = param_snapshot
        if data_fingerprint is not None:
            record.data_fingerprint = data_fingerprint
        
        # --- 关联参数版本（本次运行对应的版本优先，匹配不到回退最新）---
        try:
            cursor = (
                self._param_versions.collection.find({"model_id": record.model_id})
                .sort("version", -1)
                .limit(50)
            )
            candidates = [doc async for doc in cursor]
            matched = None
            if param_snapshot:
                for doc in candidates:
                    if _param_version_matches(doc, param_snapshot):
                        matched = doc
                        break
            chosen = matched or (candidates[0] if candidates else None)
            if chosen:
                record.param_version_id = str(chosen["_id"])
                record.param_version_number = chosen.get("version", 1)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "回测关联参数版本失败 model_id=%s: %s", record.model_id, e
            )
        
        # --- 可复现性指纹（S10）与身份注入链（S12）---
        # 与 save_monitor_record 共用同一段推导，保证「监控批次 vs 手动回测」
        # 的指纹口径一致，可直接按 reproducibility_fingerprint 对齐比对。
        self._apply_reproducibility_fingerprints(record, model, param_snapshot)
        await self._apply_record_identity(record, model, identity)

        record_dict = self._record_to_doc(record)
        result = await self.backtest_collection.insert_one(record_dict)
        record_id = str(result.inserted_id)

        # --- 运行台账（S11）：主记录插入成功后再追加，失败只 warn ---
        # strategy_id / config_version_id 由 S12 身份注入链回填；此处先按现有值透传。
        try:
            await StrategyRunService().append_run(
                run_kind="backtest",
                model_id=record.model_id,
                strategy_id=record.strategy_id,
                config_version_id=record.config_version_id,
                backtest_record_id=record_id,
                pool_hash_value=record.asset_pool_hash,
                contract_hash_value=record.contract_hash,
                data_digest=record.data_digest_v2,
                config_fingerprint=record.config_fingerprint,
                reproducibility_fingerprint=record.reproducibility_fingerprint,
                engine_version=settings.APP_VERSION,
                window_start=record.start_date,
                window_end=record.end_date,
                metrics=build_run_metrics(record.result),
                status="success",
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "策略运行台账写入失败 model_id=%s: %s", record.model_id, e
            )

        # --- 参数试错计数与搜索空间（S17）：写回 strategy_registry，失败只 warn ---
        # 计数口径：按 param_hash 去重，同参数不同区间算 1 次；搜索空间只在
        # 与库内值不一致时回写（网格由 get_param_schema 静态推导）。
        if record.strategy_id:
            try:
                from app.services.strategy_registry_service import StrategyRegistryService

                _registry = StrategyRegistryService()
                await _registry.refresh_trial_count(record.strategy_id)
                if model is not None:
                    await _registry.refresh_parameter_search_space(
                        record.strategy_id, model.template_code
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "试错计数/搜索空间刷新失败 strategy_id=%s: %s", record.strategy_id, e
                )
        
        # --- 自动写入 latest_backtest_summary（层间数据流）---
        try:
            bt_result = record.result
            summary = {
                "annual_return": float(bt_result.annual_return) if bt_result.annual_return else 0.0,
                "annual_vol": float(bt_result.annual_volatility) if bt_result.annual_volatility else 0.0,
                "sharpe": float(bt_result.sharpe_ratio) if bt_result.sharpe_ratio else 0.0,
                "max_drawdown": float(bt_result.max_drawdown) if bt_result.max_drawdown else 0.0,
                "calmar": float(bt_result.calmar_ratio) if bt_result.calmar_ratio else None,
                "annual_return_365": float(bt_result.annual_return_365) if bt_result.annual_return_365 else 0.0,
                "annual_vol_365": float(bt_result.annual_volatility_365) if bt_result.annual_volatility_365 else 0.0,
                "sharpe_365": float(bt_result.sharpe_ratio_365) if bt_result.sharpe_ratio_365 else 0.0,
                "calmar_365": float(bt_result.calmar_ratio_365) if bt_result.calmar_ratio_365 else None,
                "total_return": float(bt_result.total_return) if bt_result.total_return else 0.0,
                "win_rate": float(bt_result.win_rate) if bt_result.win_rate else None,
                "backtest_date": datetime.now().isoformat(),
                "start_date": record.start_date.strftime("%Y-%m-%d") if hasattr(record.start_date, "strftime") else str(record.start_date),
                "end_date": record.end_date.strftime("%Y-%m-%d") if hasattr(record.end_date, "strftime") else str(record.end_date),
                "record_id": record_id,
            }
            # 清理 NaN/inf
            for k, v in list(summary.items()):
                if isinstance(v, float) and (pd.isna(v) or np.isinf(v)):
                    summary[k] = None
            
            await self.collection.update_one(
                {"_id": ObjectId(record.model_id)},
                {"$set": {"latest_backtest_summary": summary, "updated_at": datetime.now()}}
            )
        except Exception as e:
            # 回测摘要写入失败不影响回测记录保存
            import logging
            logging.getLogger(__name__).warning(
                "回测摘要写入策略模型失败 model_id=%s: %s", record.model_id, e
            )
        
        return record_id

    # ------------------------------------------------------------------
    # 监控批次专用写入路径（阶段一）
    # ------------------------------------------------------------------

    async def save_monitor_record(
        self,
        record: BacktestRecord,
        batch_id: str,
        monitor_id: str,
        *,
        param_snapshot: Optional[Dict[str, Any]] = None,
        identity: Optional[Dict[str, Any]] = None,
    ) -> str:
        """监控批次专用写入：直接 insert，不触发任何回测侧副作用.

        与 :meth:`save_backtest_record` 的差异（必须保持）：
            1. **不写 ``strategy_models.latest_backtest_summary``** —— 监控跑批不得
               改变策略列表的「最近回测绩效」；
            2. **不写 ``strategy_runs``** —— 监控台账已由
               ``MonitorService._append_monitor_run`` 以 run_kind=monitor 写入，
               两边都写会产生双份台账；
            3. **不刷 ``trial_count``** —— 监控不是参数试错，计入会抬高策略的
               参数搜索次数；
            4. 强制 ``run_kind=monitor`` + ``batch_id`` + ``monitor_id``。

        保留的部分：参数快照、数据指纹、可复现性指纹与身份链与回测同口径，
        因此监控批次可与手动回测按 ``reproducibility_fingerprint`` 直接对齐。

        Args:
            record: 已组装好的记录（result 里放模型轨净值）。
            batch_id: 批次号，不得为空。
            monitor_id: 监控实例 ID，不得为空。
            param_snapshot: 可选；不传且能读到模型时自动生成。
            identity: 可选身份注入 ``{"strategy_id":..., "config_version_id":...}``。

        Returns:
            新插入记录的 ID 字符串。
        """
        if not batch_id:
            raise ValueError("save_monitor_record 必须传入 batch_id")
        if not monitor_id:
            raise ValueError("save_monitor_record 必须传入 monitor_id")

        record.run_kind = RunKind.MONITOR.value
        record.batch_id = batch_id
        record.monitor_id = monitor_id

        model = None
        try:
            model = await self._models.get_model(record.model_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "监控记录读取策略模型失败 model_id=%s: %s", record.model_id, e
            )

        if param_snapshot is None and model is not None:
            try:
                param_snapshot = resolve_full_params(model)
                param_snapshot["template_code"] = model.template_code
                param_snapshot["asset_codes"] = list(model.asset_codes or [])
                param_snapshot["rebalance_frequency"] = model.rebalance_frequency
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "监控记录生成参数快照失败 model_id=%s: %s", record.model_id, e
                )
        if param_snapshot is not None:
            record.param_snapshot = param_snapshot

        self._apply_reproducibility_fingerprints(record, model, param_snapshot)
        await self._apply_record_identity(record, model, identity)

        result = await self.backtest_collection.insert_one(self._record_to_doc(record))
        return str(result.inserted_id)

    def _apply_reproducibility_fingerprints(
        self,
        record: BacktestRecord,
        model: Optional[StrategyModel],
        param_snapshot: Optional[Dict[str, Any]],
    ) -> None:
        """可复现性指纹（S10）：纯计算，缺项留 None，落库前剔除.

        回测与监控两条写入路径共用，口径单源。
        """
        try:
            if record.param_hash is None:
                record.param_hash = param_hash(param_snapshot)
            if record.asset_pool_hash is None:
                codes = (
                    list(record.result.asset_names.keys())
                    if record.result and record.result.asset_names
                    else []
                )
                if not codes and model is not None:
                    codes = list(model.asset_codes or [])
                record.asset_pool_hash = pool_hash(codes)
            if record.contract_hash is None and model is not None:
                record.contract_hash = resolve_contract_hash(model.template_code)
            if record.config_fingerprint is None and model is not None:
                record.config_fingerprint = getattr(model, "config_fingerprint", None)
            if record.reproducibility_fingerprint is None:
                record.reproducibility_fingerprint = reproducibility_fingerprint(
                    record.config_fingerprint or record.param_hash,
                    pool_hash_value=record.asset_pool_hash,
                    contract_hash_value=record.contract_hash,
                    param_hash_value=record.param_hash,
                    engine_version=settings.APP_VERSION,
                    data_digest=record.data_digest_v2,
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "可复现性指纹计算失败 model_id=%s: %s", record.model_id, e
            )

    async def _apply_record_identity(
        self,
        record: BacktestRecord,
        model: Optional[StrategyModel],
        identity: Optional[Dict[str, Any]],
    ) -> None:
        """身份注入链（S12）：模型 → 策略本体 → 本次配置版本.

        优先级：record 字段 / identity 参数（显式传入）> 服务端反查。
        反查失败不阻断保存：字段保持 None，落库时剔除（读取侧容忍空值）。
        """
        _identity = identity or {}
        explicit_strategy_id = record.strategy_id or _identity.get("strategy_id")
        explicit_version_id = record.config_version_id or _identity.get("config_version_id")
        try:
            strategy_id = explicit_strategy_id
            if not strategy_id and model is not None:
                strategy_id = await self._resolve_strategy_id(model.template_code)
            record.strategy_id = strategy_id

            config_version_id = explicit_version_id
            if not config_version_id:
                config_version_id = await self._resolve_config_version_id(
                    record.model_id, record.config_fingerprint
                )
            record.config_version_id = config_version_id
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "记录身份注入失败 model_id=%s: %s", record.model_id, e
            )

    @staticmethod
    def _record_to_doc(record: BacktestRecord) -> Dict[str, Any]:
        """序列化为落库文档：可选字段为 None 时不写 null，保持存量文档形状."""
        record_dict = record.dict(by_alias=True, exclude={'id'})
        for _key in (
            "strategy_id", "config_version_id", "config_fingerprint",
            "asset_pool_hash", "contract_hash", "param_hash",
            "data_digest_v2", "reproducibility_fingerprint",
            "run_kind", "batch_id", "monitor_id",
        ):
            if record_dict.get(_key) is None:
                record_dict.pop(_key, None)
        return record_dict

    async def _resolve_strategy_id(self, template_code: Optional[str]) -> Optional[str]:
        """按策略码反查 ``strategy_registry`` 的 strategy_id（走别名归一）."""
        code = str(template_code or "").strip()
        if not code:
            return None
        try:
            from app.services.strategy_registry_service import StrategyRegistryService

            entry = await StrategyRegistryService().get_by_template_code(code)
            return entry.strategy_id if entry else None
        except Exception:
            return None

    async def _resolve_config_version_id(
        self, model_id: str, config_fingerprint: Optional[str]
    ) -> Optional[str]:
        """取本次运行对应的配置版本：优先指纹相等，否则最新版本；无记录返回 None."""
        try:
            from app.services.strategy_version_service import StrategyVersionService

            svc = StrategyVersionService()
            if config_fingerprint:
                doc = await svc.collection.find_one(
                    {"model_id": model_id, "config_fingerprint": config_fingerprint},
                    sort=[("version_no", -1)],
                )
                if doc:
                    return doc.get("version_id")
            return await svc.latest_version_id(model_id)
        except Exception:
            return None

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
        
        # 使用统一参数组装函数，合并 allocator + selector + controller 参数
        if "strategy_params" in overrides:
            strategy_params = overrides["strategy_params"]
        else:
            # 从 overrides 中获取 model_data，用于回退读取 MongoDB 原始文档字段
            _model_data = overrides.pop("model_data", None)
            strategy_params = build_backtest_params(model=model, model_data=_model_data)
        if isinstance(strategy_params, str):
            import json
            try:
                strategy_params = json.loads(strategy_params.replace("'", '"'))
            except Exception:
                pass
        
        # 清理和转换策略参数：字典类参数（资产权重约束 / 资产标签）统一解析为 dict，
        # 解析口径与运行时、门禁同源（无法解析时为空字典 = 不限制）
        if isinstance(strategy_params, dict):
            strategy_params = {
                key: (parse_mapping_param(value) if key in _MAPPING_PARAM_KEYS else value)
                for key, value in strategy_params.items()
            }
        
        request_data = {
            "name": overrides.get("name", f"{model.name}_回测"),
            "strategy_type": model.template_code,  # 模板代码就是策略类型
            "strategy_params": strategy_params,
            "thscodes": overrides.get("thscodes", model.asset_codes),
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": overrides.get("initial_cash", 10_000_000.0),
            "rebalance_freq": overrides.get("rebalance_freq", rebalance_freq),
            # 缺省不计费，与 BacktestConfig / BacktestRequest 的 0.0 默认对齐。
            # 曾硬编码 0.0003 / 0.0005 作兜底，导致两处口径断裂：策略经
            # get_trading_costs 声明「不计费」（返回空 dict）时仍被扣万三手续费
            # 与万五滑点；已声明分资产费率的策略，commission_by_code 只覆盖
            # commission_rate，滑点无分资产通道，会被额外叠加一次。且组合与
            # 监控通道均显式传 0.0（gross NAV），回测独自计费使三通道净值不可比。
            # 策略自带费率一律走 get_trading_costs -> commission_by_code，
            # 用户需要计费时在请求里显式传 commission_rate / slippage。
            "commission_rate": overrides.get("commission_rate", 0.0),
            "slippage": overrides.get("slippage", 0.0),
            "lookback_days": overrides.get("lookback_days", 500)
        }
        
        return request_data
