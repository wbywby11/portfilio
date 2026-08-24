# -*- coding: utf-8 -*-
"""
会计辅助服务层

编排会计分录生成、查询、配置管理等流程。
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from loguru import logger

from app.config.database import Database
from app.options.accounting import AccountingGenerator, DEFAULT_ACCOUNT_MAP
from app.options.dispatcher import ValuationRecord


class OptionAccountingService:
    """会计辅助服务"""

    @property
    def db(self):
        return Database.get_database()

    @property
    def entries_col(self):
        from app.config.collections import COL_OPTION_ACCOUNTING_ENTRIES
        return self.db[COL_OPTION_ACCOUNTING_ENTRIES]

    @property
    def config_col(self):
        from app.config.collections import COL_OPTION_ACCOUNTING_CONFIG
        return self.db[COL_OPTION_ACCOUNTING_CONFIG]

    @property
    def valuations_col(self):
        from app.config.collections import COL_OPTION_VALUATIONS
        return self.db[COL_OPTION_VALUATIONS]

    @property
    def events_col(self):
        from app.config.collections import COL_OPTION_LIFECYCLE_EVENTS
        return self.db[COL_OPTION_LIFECYCLE_EVENTS]

    # ══════════════════════════════════════════════════
    #  会计分录生成
    # ══════════════════════════════════════════════════

    async def generate_entries(self, date_str: str) -> dict:
        """根据估值结果生成会计分录

        流程：
        1. 加载当日最终版估值结果
        2. 加载前一日估值结果（用于日终盯市对比）
        3. 加载当日生命周期事件（敲出/到期）
        4. 生成日终盯市分录 + 事件结算分录
        5. 持久化到 option_accounting_entries
        """
        # 获取科目映射
        account_map = await self.get_config()
        generator = AccountingGenerator(account_map)

        # 加载当日估值
        today_doc = await self._load_final_valuation(date_str)
        if not today_doc:
            return {"error": f"无估值数据: {date_str}"}

        today_products = today_doc.get("products", [])
        version = today_doc.get("version", 0)

        # 构建当日 ValuationRecord 字典
        today_dict = {p["product_id"]: ValuationRecord(**p) for p in today_products}

        # 加载前一日估值
        prev_date = self._prev_date_str(date_str)
        prev_doc = await self._load_final_valuation(prev_date)
        prev_dict = {}
        if prev_doc:
            prev_dict = {p["product_id"]: ValuationRecord(**p) for p in prev_doc.get("products", [])}

        # 生成日终盯市分录
        entries = generator.generate_daily_mark(
            date_str, list(today_dict.values()), prev_dict, valuation_version=version
        )

        # 加载当日事件，生成结算分录
        events = await self._load_events(date_str)
        for event in events:
            pid = event["product_id"]
            etype = event["event_type"]
            val = today_dict.get(pid)
            if not val:
                continue

            if etype in ("knock_out", "maturity"):
                settlement_amount = val.price_total  # 结算金额 = 最终估值
                carrying_value = prev_dict[pid].price_total if pid in prev_dict else val.principal

                if etype == "knock_out":
                    entries.extend(generator.generate_knock_out_settlement(
                        date_str, pid, val.name, settlement_amount, carrying_value, version
                    ))
                else:
                    entries.extend(generator.generate_maturity_settlement(
                        date_str, pid, val.name, settlement_amount, carrying_value, version
                    ))

        # 持久化
        if entries:
            # 先删除当日旧分录（允许重新生成）
            await self.entries_col.delete_many({"date": date_str})
            await self.entries_col.insert_many(entries)

            # 将 ObjectId 转为字符串（JSON 可序列化）
            for e in entries:
                if "_id" in e:
                    e["_id"] = str(e["_id"])

        # 汇总
        summary = AccountingGenerator.summarize_by_account(entries)

        logger.info(f"[会计服务] 生成分录: date={date_str}, 共 {len(entries)} 条")
        return {
            "date": date_str,
            "total_entries": len(entries),
            "entries": entries,
            "summary": summary,
        }

    # ══════════════════════════════════════════════════
    #  会计分录查询
    # ══════════════════════════════════════════════════

    async def get_entries(
        self,
        date: Optional[str] = None,
        product_id: Optional[str] = None,
        entry_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> List[dict]:
        """查询会计分录"""
        query: Dict[str, Any] = {}
        if date:
            query["date"] = date
        if product_id:
            query["product_id"] = product_id
        if entry_type:
            query["entry_type"] = entry_type

        cursor = self.entries_col.find(query).sort("date", -1).skip(skip).limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ══════════════════════════════════════════════════
    #  科目配置管理
    # ══════════════════════════════════════════════════

    async def get_config(self) -> Dict[str, str]:
        """获取科目映射配置"""
        doc = await self.config_col.find_one({"_type": "account_map"})
        if doc:
            return doc.get("account_map", DEFAULT_ACCOUNT_MAP.copy())
        return DEFAULT_ACCOUNT_MAP.copy()

    async def update_config(self, account_map: Dict[str, str]) -> bool:
        """更新科目映射配置"""
        result = await self.config_col.update_one(
            {"_type": "account_map"},
            {"$set": {"account_map": account_map, "updated_at": datetime.now()}},
            upsert=True,
        )
        return result.upserted_id is not None or result.modified_count > 0

    # ══════════════════════════════════════════════════
    #  内部工具方法
    # ══════════════════════════════════════════════════

    async def _load_final_valuation(self, date_str: str) -> Optional[dict]:
        """加载指定日期的最终版估值（无最终版则取最新版）"""
        doc = await self.valuations_col.find_one({"date": date_str, "is_final": True})
        if not doc:
            doc = await self.valuations_col.find_one({"date": date_str}, sort=[("version", -1)])
        return doc

    async def _load_events(self, date_str: str) -> List[dict]:
        """加载指定日期的生命周期事件"""
        cursor = self.events_col.find({"event_date": date_str})
        results = []
        async for doc in cursor:
            results.append(doc)
        return results

    @staticmethod
    def _prev_date_str(date_str: str) -> str:
        """获取前一天的日期字符串"""
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (d - timedelta(days=1)).strftime("%Y-%m-%d")
