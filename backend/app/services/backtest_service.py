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

from app.models.strategy_model import StrategyModel, BacktestRecord
from app.services.strategy_model_service import (
    StrategyModelService,
    resolve_full_params,
    build_backtest_params,
)
from app.services.param_version_service import ParamVersionService


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

    async def save_backtest_record(
        self,
        record: BacktestRecord,
        param_snapshot: Optional[Dict[str, Any]] = None,
        data_fingerprint: Optional[str] = None,
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
        """
        # --- 自动生成参数快照（若未提供）---
        if param_snapshot is None:
            try:
                model = await self._models.get_model(record.model_id)
                if model:
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
        
        # --- 自动关联最新参数版本 ---
        try:
            latest_pv = await self._param_versions.collection.find_one(
                {"model_id": record.model_id},
                sort=[("version", -1)],
            )
            if latest_pv:
                record.param_version_id = str(latest_pv["_id"])
                record.param_version_number = latest_pv.get("version", 1)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "回测关联参数版本失败 model_id=%s: %s", record.model_id, e
            )
        
        record_dict = record.dict(by_alias=True, exclude={'id'})
        result = await self.backtest_collection.insert_one(record_dict)
        record_id = str(result.inserted_id)
        
        # --- 自动写入 latest_backtest_summary（层间数据流）---
        try:
            bt_result = record.result
            summary = {
                "annual_return": float(bt_result.annual_return) if bt_result.annual_return else 0.0,
                "annual_vol": float(bt_result.annual_volatility) if bt_result.annual_volatility else 0.0,
                "sharpe": float(bt_result.sharpe_ratio) if bt_result.sharpe_ratio else 0.0,
                "max_drawdown": float(bt_result.max_drawdown) if bt_result.max_drawdown else 0.0,
                "calmar": float(bt_result.calmar_ratio) if bt_result.calmar_ratio else None,
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
        
        # 清理和转换策略参数，确保字典类型参数格式正确
        if isinstance(strategy_params, dict):
            import json
            cleaned_params = {}
            for key, value in strategy_params.items():
                # 处理 weight_caps / max_weight_dict 参数
                if key in ("weight_caps", "max_weight_dict"):
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
