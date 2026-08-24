# -*- coding: utf-8 -*-
"""
收益凭证估值服务层

编排产品管理、估值运行、风险分析、生命周期检测等完整流程。
数据从 MongoDB 加载后转换为 ProductRecord / MarketDataRecord，
传给未修改的 PricingDispatcher 和 RiskReportGenerator。
"""

from datetime import datetime, date
from typing import List, Optional, Dict, Any
from dataclasses import asdict

from bson import ObjectId
from loguru import logger

from app.config.database import Database
from app.config.collections import COL_ASSET_PRICES
from app.options.data_loader import ProductRecord, MarketDataRecord, build_vol_surface_from_doc
from app.options.dispatcher import ValuationRecord, PricingDispatcher
from app.options.product_manager import ProductLifecycleManager
from app.options.risk import RiskReportGenerator
from app.options.config import DEFAULT_N_PATHS


class OptionPricingService:
    """收益凭证估值服务"""

    # ── 集合访问 ──────────────────────────────────────

    @property
    def db(self):
        return Database.get_database()

    @property
    def products_col(self):
        from app.config.collections import COL_OPTION_PRODUCTS
        return self.db[COL_OPTION_PRODUCTS]

    @property
    def market_col(self):
        from app.config.collections import COL_OPTION_MARKET_DATA
        return self.db[COL_OPTION_MARKET_DATA]

    @property
    def vol_surface_col(self):
        from app.config.collections import COL_OPTION_VOL_SURFACES
        return self.db[COL_OPTION_VOL_SURFACES]

    @property
    def valuations_col(self):
        from app.config.collections import COL_OPTION_VALUATIONS
        return self.db[COL_OPTION_VALUATIONS]

    @property
    def history_col(self):
        from app.config.collections import COL_OPTION_VALUATION_HISTORY
        return self.db[COL_OPTION_VALUATION_HISTORY]

    @property
    def events_col(self):
        from app.config.collections import COL_OPTION_LIFECYCLE_EVENTS
        return self.db[COL_OPTION_LIFECYCLE_EVENTS]

    @property
    def risk_col(self):
        from app.config.collections import COL_OPTION_RISK_REPORTS
        return self.db[COL_OPTION_RISK_REPORTS]

    # ══════════════════════════════════════════════════
    #  产品 CRUD
    # ══════════════════════════════════════════════════

    async def list_products(
        self,
        product_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> List[dict]:
        """查询产品列表"""
        query: Dict[str, Any] = {}
        if product_type:
            query["type"] = product_type
        if status:
            query["status"] = status

        cursor = self.products_col.find(query).skip(skip).limit(limit).sort("product_id", 1)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def create_product(self, data: dict) -> str:
        """创建产品"""
        data["created_at"] = datetime.now()
        data["updated_at"] = datetime.now()
        result = await self.products_col.insert_one(data)
        return str(result.inserted_id)

    async def get_product(self, product_id: str) -> Optional[dict]:
        """根据 MongoDB _id 获取产品"""
        doc = await self.products_col.find_one({"_id": ObjectId(product_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def get_product_by_code(self, product_code: str) -> Optional[dict]:
        """根据 product_id（业务编号）获取产品"""
        doc = await self.products_col.find_one({"product_id": product_code})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def update_product(self, mongo_id: str, update_data: dict) -> bool:
        """更新产品"""
        update_data["updated_at"] = datetime.now()
        # 过滤 None 值
        update_data = {k: v for k, v in update_data.items() if v is not None}
        if not update_data:
            return False
        result = await self.products_col.update_one(
            {"_id": ObjectId(mongo_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0

    async def delete_product(self, mongo_id: str) -> bool:
        """删除产品"""
        result = await self.products_col.delete_one({"_id": ObjectId(mongo_id)})
        return result.deleted_count > 0

    # ══════════════════════════════════════════════════
    #  市场数据管理
    # ══════════════════════════════════════════════════

    async def import_market_data(self, records: List[dict]) -> dict:
        """批量导入/更新市场数据（按 date+underlying 去重）"""
        inserted = 0
        updated = 0
        for rec in records:
            rec["created_at"] = datetime.now()
            result = await self.market_col.update_one(
                {"date": rec["date"], "underlying": rec["underlying"]},
                {"$set": rec},
                upsert=True,
            )
            if result.upserted_id:
                inserted += 1
            else:
                updated += 1
        return {"inserted": inserted, "updated": updated, "total": len(records)}

    async def get_market_data(self, date_str: str) -> List[dict]:
        """获取指定日期的市场数据"""
        cursor = self.market_col.find({"date": date_str})
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def get_market_data_records(self, date_str: str) -> Dict[str, MarketDataRecord]:
        """获取 MarketDataRecord 字典（供 PricingDispatcher 使用）

        优先从 option_market_data 加载完整记录（含利率/波动率），
        对于 option_products 中存在但 option_market_data 缺失的 underlying，
        自动从主系统 asset_prices 集合补充 spot（收盘价），利率/波动率使用合理默认值。
        """
        # 1. 先从 option_market_data 加载
        docs = await self.get_market_data(date_str)
        result = {}
        for doc in docs:
            rec = MarketDataRecord(doc)
            result[rec.underlying] = rec

        # 2. 收集所有 active 产品需要的 underlying，找出缺失项
        products = await self._load_product_records()
        if not products:
            return result

        needed = {p.underlying for p in products}
        missing = needed - set(result.keys())

        if missing:
            # 3. 从 asset_prices 批量补充缺失的 underlying
            asset_codes = list(missing)
            cursor = self.db[COL_ASSET_PRICES].find(
                {"asset_code": {"$in": asset_codes}, "date": date_str}
            )
            async for doc in cursor:
                code = doc["asset_code"]
                if code not in result and doc.get("close"):
                    fallback_doc = {
                        "date": date_str,
                        "underlying": code,
                        "spot": float(doc["close"]),
                        "dividend_yield": 0.0,
                        "vol_1m": 0.20, "vol_3m": 0.18, "vol_6m": 0.17, "vol_12m": 0.16,
                        "rate_1m": 0.02, "rate_3m": 0.02, "rate_6m": 0.02,
                        "rate_1y": 0.025, "rate_2y": 0.028, "rate_5y": 0.03,
                    }
                    result[code] = MarketDataRecord(fallback_doc)
                    logger.info(
                        "[行情桥接] {} 从 asset_prices 补充 spot={}",
                        code, doc["close"]
                    )

        return result

    async def sync_market_data_from_assets(self, date_str: str) -> dict:
        """从 asset_prices 同步标的现价到 option_market_data

        收集所有产品的 underlying 代码，从主系统 asset_prices 集合查询当日收盘价，
        写入 option_market_data 集合。已有记录仅更新 spot（保留利率/波动率），
        新记录用默认值填充利率/波动率字段。
        """
        # 1. 收集所有产品的 underlying
        products = await self.list_products()
        underlyings = list(set(p["underlying"] for p in products))
        if not underlyings:
            return {"synced": 0, "date": date_str, "message": "无产品"}

        # 2. 从 asset_prices 批量查询
        cursor = self.db[COL_ASSET_PRICES].find(
            {"asset_code": {"$in": underlyings}, "date": date_str}
        )
        synced = 0
        not_found = []
        async for doc in cursor:
            code = doc["asset_code"]
            spot = doc.get("close")
            if spot is None:
                continue
            # 检查 option_market_data 是否已有该记录
            existing = await self.market_col.find_one({"date": date_str, "underlying": code})
            if existing:
                # 仅更新 spot，保留已有的利率/波动率
                await self.market_col.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"spot": float(spot), "synced_from": "asset_prices", "updated_at": datetime.now()}}
                )
            else:
                # 新建完整记录
                await self.market_col.insert_one({
                    "date": date_str, "underlying": code,
                    "spot": float(spot),
                    "dividend_yield": 0.0,
                    "vol_1m": 0.20, "vol_3m": 0.18, "vol_6m": 0.17, "vol_12m": 0.16,
                    "rate_1m": 0.02, "rate_3m": 0.02, "rate_6m": 0.02,
                    "rate_1y": 0.025, "rate_2y": 0.028, "rate_5y": 0.03,
                    "synced_from": "asset_prices",
                    "created_at": datetime.now()
                })
            synced += 1

        # 检查哪些 underlying 在 asset_prices 中找不到
        found_codes = set()
        cursor2 = self.db[COL_ASSET_PRICES].find(
            {"asset_code": {"$in": underlyings}, "date": date_str}, {"asset_code": 1}
        )
        async for doc in cursor2:
            found_codes.add(doc["asset_code"])
        not_found = [u for u in underlyings if u not in found_codes]

        logger.info("[行情同步] date={} synced={} not_found={}", date_str, synced, not_found)
        return {"synced": synced, "date": date_str, "not_found": not_found}

    # ══════════════════════════════════════════════════
    #  波动率曲面管理
    # ══════════════════════════════════════════════════

    async def import_vol_surface(self, data: dict) -> str:
        """导入/更新波动率曲面（按 underlying 去重）"""
        data["updated_at"] = datetime.now()
        data["created_at"] = datetime.now()
        result = await self.vol_surface_col.update_one(
            {"underlying": data["underlying"]},
            {"$set": data},
            upsert=True,
        )
        return str(result.upserted_id) if result.upserted_id else None

    async def get_vol_surface(self, underlying: str) -> Optional[dict]:
        """获取标的的波动率曲面"""
        doc = await self.vol_surface_col.find_one({"underlying": underlying})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def list_vol_surfaces(self) -> List[dict]:
        """列出所有波动率曲面"""
        cursor = self.vol_surface_col.find()
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ══════════════════════════════════════════════════
    #  估值运行
    # ══════════════════════════════════════════════════

    async def run_valuation(
        self,
        date_str: str,
        product_ids: Optional[List[str]] = None,
        skip_lifecycle: bool = False,
    ) -> dict:
        """运行估值

        Args:
            date_str: 估值日期 YYYY-MM-DD
            product_ids: 指定产品编号列表（空=全部）
            skip_lifecycle: 是否跳过生命周期检测

        Returns:
            估值结果摘要
        """
        val_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        # 1. 加载产品
        products = await self._load_product_records(product_ids)
        if not products:
            return {"error": "无产品数据", "date": date_str, "products": []}

        # 2. 加载市场数据
        market_data = await self.get_market_data_records(date_str)
        if not market_data:
            return {"error": f"无市场数据: {date_str}", "date": date_str, "products": []}

        # 3. 加载波动率曲面（按标的分组）
        vol_surfaces = await self._load_vol_surfaces(market_data)

        # 4. 生命周期检测（基于交易日历判定观察日）
        events = []
        if not skip_lifecycle:
            state_map = await self._build_state_map(products)
            lifecycle_mgr = ProductLifecycleManager()
            # 加载交易日历用于观察日判定
            trade_dates = await self._load_trade_dates(val_date)
            events = lifecycle_mgr.check_products(
                products, market_data, val_date, state_map, trade_dates=trade_dates
            )
            # 持久化事件
            for event in events:
                await self.events_col.update_one(
                    {"product_id": event.product_id, "event_type": event.event_type, "event_date": event.event_date},
                    {"$setOnInsert": event.to_dict()},
                    upsert=True,
                )
            # 更新产品状态
            for prod in products:
                if prod.status in ("knocked_out", "matured", "knocked_in"):
                    await self.products_col.update_one(
                        {"product_id": prod.id},
                        {"$set": {"status": prod.status, "updated_at": datetime.now()}}
                    )

        # 5. 逐产品估值
        dispatcher = PricingDispatcher()
        records: List[ValuationRecord] = []
        warnings = []

        for prod in products:
            market = market_data.get(prod.underlying)
            if market is None:
                rec = ValuationRecord(
                    product_id=prod.id, name=prod.name, type=prod.type,
                    issuer=prod.issuer, date=date_str,
                    status=prod.status, principal=prod.principal,
                    underlying=prod.underlying, price_total=0.0,
                    error=f"无市场数据: {prod.underlying}",
                )
                records.append(rec)
                continue

            vs = vol_surfaces.get(prod.underlying)
            rec = dispatcher.price_product(prod, market, vol_surface=vs)

            # 估值失败自动重试一次
            if rec.error:
                try:
                    rec = dispatcher.price_product(prod, market, vol_surface=vs)
                except Exception:
                    pass

            # 校验
            if not rec.error:
                ws = dispatcher.validate_record(rec, prod)
                for w in ws:
                    warnings.append({"product_id": prod.id, "message": w})

            records.append(rec)

        # 6. 存储结果（版本化：同日多次运行递增版本号）
        # 计算下一个版本号
        max_version_doc = await self.valuations_col.find_one(
            {"date": date_str}, sort=[("version", -1)], projection={"version": 1}
        )
        next_version = (max_version_doc.get("version", 0) + 1) if max_version_doc else 1

        snapshot = {
            "date": date_str,
            "generated_at": datetime.now().isoformat(),
            "total_products": len(records),
            "success_count": sum(1 for r in records if not r.error),
            "error_count": sum(1 for r in records if r.error),
            "total_value": sum(r.price_total for r in records if not r.error),
            "warnings": warnings,
            "events": [e.to_dict() for e in events],
        }

        # 存储到 option_valuations（版本化，不覆盖同日旧版本）
        await self.valuations_col.insert_one({
            "date": date_str,
            "version": next_version,
            "run_at": datetime.now().isoformat(),
            "run_config": {
                "skip_lifecycle": skip_lifecycle,
                "mc_paths": DEFAULT_N_PATHS,
                "market_source": "option_market_data+asset_prices",
            },
            "snapshot": snapshot,
            "products": [asdict(r) for r in records],
            "is_final": False,
            "confirmed_by": None,
            "confirmed_at": None,
            "created_at": datetime.now(),
        })

        # 追加到历史（按 date+product_id+version 去重）
        for rec in records:
            await self.history_col.update_one(
                {"date": date_str, "product_id": rec.product_id, "version": next_version},
                {"$set": {
                    "date": date_str,
                    "product_id": rec.product_id,
                    "version": next_version,
                    "name": rec.name,
                    "type": rec.type,
                    "principal": rec.principal,
                    "underlying": rec.underlying,
                    "price_total": round(rec.price_total, 2),
                    "delta": round(rec.delta, 6),
                    "gamma": round(rec.gamma, 8),
                    "vega": round(rec.vega, 6),
                    "theta": round(rec.theta, 6),
                    "method": rec.method,
                    "error": rec.error,
                    "created_at": datetime.now(),
                }},
                upsert=True,
            )

        # 7. 构建返回
        product_results = [asdict(r) for r in records]
        snapshot["products"] = product_results
        snapshot["version"] = next_version
        logger.info(f"估值完成: date={date_str}, version={next_version}, total={len(records)}, "
                     f"success={snapshot['success_count']}, error={snapshot['error_count']}")

        return snapshot

    # ══════════════════════════════════════════════════
    #  估值查询
    # ══════════════════════════════════════════════════

    async def get_valuation_snapshot(self, date_str: str) -> Optional[dict]:
        """获取指定日期的最终确认版估值快照（无确认版则取最新版本）"""
        # 优先取 is_final=true 的版本
        doc = await self.valuations_col.find_one({"date": date_str, "is_final": True})
        if not doc:
            # 取最新版本
            doc = await self.valuations_col.find_one({"date": date_str}, sort=[("version", -1)])
        if doc:
            doc.pop("_id", None)
        return doc

    async def get_valuation_versions(self, date_str: str) -> List[dict]:
        """获取指定日期所有估值版本列表（按版本号降序）"""
        cursor = self.valuations_col.find(
            {"date": date_str},
            {"products": 0, "snapshot.products": 0},  # 不返回明细，只返回摘要
        ).sort("version", -1)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def confirm_valuation_version(self, date_str: str, version: int, confirmed_by: str = "") -> bool:
        """确认某版本为最终版（同日其他版本的 is_final 设为 False）"""
        # 先取消同日其他版本的确认
        await self.valuations_col.update_many(
            {"date": date_str, "is_final": True},
            {"$set": {"is_final": False, "confirmed_by": None, "confirmed_at": None}}
        )
        # 确认目标版本
        result = await self.valuations_col.update_one(
            {"date": date_str, "version": version},
            {"$set": {"is_final": True, "confirmed_by": confirmed_by, "confirmed_at": datetime.now().isoformat()}}
        )
        return result.modified_count > 0

    async def get_valuation_version_detail(self, date_str: str, version: int) -> Optional[dict]:
        """获取指定日期指定版本的完整估值详情"""
        doc = await self.valuations_col.find_one({"date": date_str, "version": version})
        if doc:
            doc.pop("_id", None)
        return doc

    async def get_valuation_trend(
        self,
        product_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[dict]:
        """获取指定产品的估值趋势序列（取每日最终版）"""
        query: Dict[str, Any] = {"product_id": product_id}
        if start_date:
            query["date"] = {"$gte": start_date}
        if end_date:
            query.setdefault("date", {})["$lte"] = end_date

        cursor = self.history_col.find(query).sort("date", 1)
        # 按日期取最新版本
        by_date: Dict[str, dict] = {}
        async for doc in cursor:
            d = doc["date"]
            v = doc.get("version", 0)
            if d not in by_date or v > by_date[d].get("version", 0):
                by_date[d] = doc
        results = []
        for d in sorted(by_date.keys()):
            doc = by_date[d]
            doc.pop("_id", None)
            results.append(doc)
        return results

    async def get_valuation_history(
        self,
        product_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[dict]:
        """获取估值历史"""
        query: Dict[str, Any] = {}
        if product_id:
            query["product_id"] = product_id
        if start_date:
            query["date"] = {"$gte": start_date}
        if end_date:
            if "date" in query:
                query["date"]["$lte"] = end_date
            else:
                query["date"] = {"$lte": end_date}

        cursor = self.history_col.find(query).sort("date", -1).skip(skip).limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ══════════════════════════════════════════════════
    #  风险分析
    # ══════════════════════════════════════════════════

    async def run_risk_analysis(
        self,
        date_str: str,
        run_scenario: bool = True,
        run_stress: bool = True,
        run_pnl: bool = False,
    ) -> dict:
        """运行风险分析

        加载产品和市场数据，先运行基准估值，然后执行情景/压力/P&L分析。
        """
        val_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        # 加载数据
        products = await self._load_product_records()
        market_data = await self.get_market_data_records(date_str)
        if not products or not market_data:
            return {"error": "无产品或市场数据", "date": date_str}

        vol_surfaces = await self._load_vol_surfaces(market_data)

        # 基准估值
        dispatcher = PricingDispatcher()
        base_records = []
        for prod in products:
            market = market_data.get(prod.underlying)
            if market is None:
                continue
            vs = vol_surfaces.get(prod.underlying)
            rec = dispatcher.price_product(prod, market, vol_surface=vs)
            base_records.append(rec)

        # P&L 归因：自动加载 T-1 日数据
        prev_records = None
        prev_market_data = None
        if run_pnl:
            from datetime import timedelta
            prev_date = (val_date - timedelta(days=1)).isoformat()
            # 尝试加载 T-1 估值快照
            prev_snapshot = await self.get_valuation_snapshot(prev_date)
            if prev_snapshot and prev_snapshot.get("products"):
                prev_records = [ValuationRecord(**p) for p in prev_snapshot["products"]]
                logger.info("[P&L归因] 加载 T-1 快照: date={}, 产品数={}", prev_date, len(prev_records))
            else:
                logger.info("[P&L归因] T-1 无估值快照: date={}", prev_date)
            # 加载 T-1 市场数据
            prev_market_data = await self.get_market_data_records(prev_date)
            if not prev_records or not prev_market_data:
                logger.info("[P&L归因] T-1 数据不完整，跳过 P&L 归因")
                prev_records = None
                prev_market_data = None

        # 风险分析
        risk_gen = RiskReportGenerator()
        report = risk_gen.generate(
            val_date, products, market_data, dispatcher, base_records,
            prev_records=prev_records,
            prev_market_data=prev_market_data,
            run_scenario=run_scenario,
            run_stress=run_stress,
            run_pnl=run_pnl and prev_records is not None,
            vol_surfaces=vol_surfaces,
        )

        # 存储到 MongoDB
        # 转换 numpy 类型为 Python 原生类型
        import numpy as np
        def convert(obj):
            if isinstance(obj, (np.integer, np.int64)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            return obj

        report_doc = {
            "date": date_str,
            "scenario": report.get("scenario"),
            "stress": report.get("stress"),
            "pnl": report.get("pnl"),
            "created_at": datetime.now(),
        }
        await self.risk_col.update_one(
            {"date": date_str},
            {"$set": report_doc},
            upsert=True,
        )

        return report

    async def get_risk_report(self, date_str: str) -> Optional[dict]:
        """获取风险报告"""
        doc = await self.risk_col.find_one({"date": date_str})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    # ══════════════════════════════════════════════════
    #  事件日志
    # ══════════════════════════════════════════════════

    async def get_events(
        self,
        product_id: Optional[str] = None,
        event_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> List[dict]:
        """获取事件日志"""
        query: Dict[str, Any] = {}
        if product_id:
            query["product_id"] = product_id
        if event_type:
            query["event_type"] = event_type

        cursor = self.events_col.find(query).sort("event_date", -1).skip(skip).limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ══════════════════════════════════════════════════
    #  内部工具方法
    # ══════════════════════════════════════════════════

    async def _load_product_records(self, product_ids: Optional[List[str]] = None) -> List[ProductRecord]:
        """从 MongoDB 加载产品并转换为 ProductRecord"""
        query: Dict[str, Any] = {}
        if product_ids:
            query["product_id"] = {"$in": product_ids}

        cursor = self.products_col.find(query)
        products = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            # 将 MongoDB doc 转为 ProductRecord 兼容的 raw dict
            raw = {
                "id": doc["product_id"],
                "name": doc["name"],
                "type": doc["type"],
                "issuer": doc.get("issuer", ""),
                "issue_date": doc["issue_date"],
                "maturity_date": doc["maturity_date"],
                "principal": doc["principal"],
                "underlying": doc["underlying"],
                "status": doc.get("status", "active"),
                "params": doc.get("params", {}),
            }
            if doc.get("knock_out_date"):
                raw["knock_out_date"] = doc["knock_out_date"]
            products.append(ProductRecord(raw))
        return products

    async def _load_vol_surfaces(self, market_data: Dict[str, MarketDataRecord]) -> Dict[str, Any]:
        """加载波动率曲面（按标的代码）"""
        vol_surfaces = {}
        for underlying in market_data:
            doc = await self.get_vol_surface(underlying)
            if doc:
                vol_surfaces[underlying] = build_vol_surface_from_doc(doc)
        return vol_surfaces

    async def _build_state_map(self, products: List[ProductRecord]) -> Dict[str, dict]:
        """构建产品运行时状态映射"""
        state_map = {}
        for prod in products:
            doc = await self.products_col.find_one({"product_id": prod.id})
            if doc:
                state_map[prod.id] = {"status": doc.get("status", "active")}
        return state_map

    async def _load_trade_dates(self, val_date: date) -> List[str]:
        """加载交易日历（估值日期所在年 + 前后一年，覆盖产品存续期）

        返回 YYYY-MM-DD 字符串列表。如果 trade_dates 集合为空则返回空列表，
        由 ProductLifecycleManager 回退为自然日判定。
        """
        from app.services.trade_calendar_service import TradeCalendarService
        cal_svc = TradeCalendarService()
        # 加载估值日前后各一年的交易日历，确保覆盖产品存续期
        years = {val_date.year - 1, val_date.year, val_date.year + 1}
        all_dates: List[str] = []
        for y in years:
            dates = await cal_svc.get_dates_by_year(y)
            all_dates.extend(dates)
        return sorted(set(all_dates))
