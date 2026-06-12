"""
资产服务层
"""
import asyncio
import io
import re
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Optional, Dict, Any, Set, Tuple
from bson import ObjectId
from pymongo import UpdateOne
from loguru import logger
from app.config.database import Database
from app.models.asset import Asset, AssetPrice, AssetType
from app.services.price_import_progress import touch_progress
import pandas as pd

# 行情导入单次 bulk_write / insert_many 的批大小（过小会显著拉长导入与前端轮询时间）
PRICE_IMPORT_BATCH_SIZE = 2000

# 常见别名 → 系统中的资产代码（便于「沪深300」等与库内简称不一致时的检索）
_KEYWORD_CODE_HINTS = (
    ("沪深300", ["SH000300", "SZ159919"]),
    ("hs300", ["SH000300", "SZ159919"]),
    ("标普500", ["SPX", "^GSPC", "SPY"]),
    ("标普", ["SPX", "^GSPC", "SPY"]),
    ("s&p", ["SPX", "^GSPC", "SPY"]),
    ("黄金", ["GLD", "XAUUSD", "Au9999", "Au(T+D)"]),
    ("纳指100", ["NDX", "QQQ"]),
)

def _keyword_hint_codes(user_kw: str) -> List[str]:
    """若用户关键字命中常见别名，返回可能被引用的 asset code 列表。"""
    s = user_kw.strip()
    if not s:
        return []
    low = s.lower()
    out: List[str] = []
    for alias, codes in _KEYWORD_CODE_HINTS:
        if alias in s or alias.lower() in low:
            out.extend(codes)
    seen: set[str] = set()
    uniq: List[str] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq

# 多资产宽表单次最多解析列数（防止错位解析出上千「伪资产」导致 analyze 超时）
MAX_MULTI_ASSET_COLUMNS_PER_SHEET = 512

_PRICE_NUM_FIELDS = ("open", "high", "low", "close", "volume", "amount", "scale")


def _is_blank_val(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    return False


def _sparse_price_fields(price_data: dict) -> Dict[str, Any]:
    """从一行导入数据中提取非空的行情数字字段（不含 date）。"""
    sparse: Dict[str, Any] = {}
    for k in _PRICE_NUM_FIELDS:
        if k not in price_data:
            continue
        v = price_data.get(k)
        if _is_blank_val(v):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if isinstance(fv, float) and pd.isna(fv):
            continue
        if k == "close" and fv <= 0:
            continue
        if k == "volume":
            sparse[k] = int(round(fv))
        else:
            sparse[k] = fv
    return sparse


def _effective_close_for_sparse(sp: Dict[str, Any]) -> Optional[float]:
    """（保留）由 OHLC 推断有效价；新交易日插入已改为须显式收盘价，本函数仅用于兼容旧逻辑/文档。"""
    for k in ("close", "high", "low", "open"):
        v = sp.get(k)
        if v is not None and float(v) > 0:
            return float(v)
    return None


def _explicit_close_positive(sp: Dict[str, Any]) -> bool:
    """是否在本行提供了大于 0 的收盘价（新交易日插入、全量覆盖行的必要条件）。"""
    v = sp.get("close")
    if v is None or _is_blank_val(v):
        return False
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def _normalize_import_date(date_raw: Any) -> str:
    if date_raw is None:
        raise ValueError("日期为空")
    if hasattr(date_raw, "strftime"):
        return date_raw.strftime("%Y-%m-%d")
    if isinstance(date_raw, str):
        s0 = date_raw.strip()
        ds = s0.replace("-", "").replace("/", "").strip()
        if len(ds) == 8 and ds.isdigit():
            return datetime.strptime(ds, "%Y%m%d").strftime("%Y-%m-%d")
        try:
            return datetime.strptime(s0.replace("/", "-"), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError(f"日期格式错误: {date_raw}")
    raise ValueError(f"日期类型不支持: {type(date_raw)}")


def _full_price_document(
    asset_code: str, date_formatted: str, sparse: Dict[str, Any], close_val: float
) -> dict:
    """写入新文档时的完整行情行（未出现的 OHLC 为 None）。"""
    return {
        "asset_code": asset_code,
        "date": date_formatted,
        "open": sparse.get("open"),
        "high": sparse.get("high"),
        "low": sparse.get("low"),
        "close": close_val,
        "volume": sparse.get("volume"),
        "amount": sparse.get("amount"),
        "scale": sparse.get("scale"),
    }


class AssetService:
    """资产服务"""
    
    def __init__(self):
        self._db = None
        self._collection = None
        self._price_collection = None
    
    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.db['assets']
        return self._collection

    @property
    def price_collection(self):
        if self._price_collection is None:
            self._price_collection = self.db['asset_prices']
        return self._price_collection
    
    async def create_asset(self, asset: Asset) -> str:
        """创建资产"""
        asset_dict = asset.dict(by_alias=True, exclude={'id'})
        result = await self.collection.insert_one(asset_dict)
        return str(result.inserted_id)
    
    async def get_asset(self, asset_id: str) -> Optional[Asset]:
        """获取单个资产"""
        data = await self.collection.find_one({"_id": ObjectId(asset_id)})
        if data:
            data['_id'] = str(data['_id'])
            return Asset(**data)
        return None
    
    async def get_asset_by_code(self, code: str) -> Optional[Asset]:
        """根据代码获取资产（精确匹配）"""
        data = await self.collection.find_one({"code": code})
        if data:
            data['_id'] = str(data['_id'])
            return Asset(**data)
        return None

    @staticmethod
    def _normalize_code_str(s: str) -> str:
        """去除所有 Unicode 不可见空白（全角空格、零宽字符、不间断空格等）后再 strip。"""
        return re.sub(r'[\u00A0\u200B\u200C\u200D\u3000\uFEFF\t\r\n]', '', (s or '').strip()).strip()

    async def find_asset_by_code_tolerant(self, code: str) -> Optional[Asset]:
        """
        多资产导入用：容错代码查找，按优先级依次降级：
        1. 原始值精确匹配
        2. 去除 Unicode 不可见空白后精确匹配
        3. 大小写不敏感精确匹配（DR007.ib → DR007.IB）
        4. 去除交易所后缀后匹配（160216.SZ → 160216）
        5. 交易所前缀格式匹配（160216.SZ → SZ160216）
        """
        raw = (code or "").strip()
        if not raw:
            return None
        normalized = self._normalize_code_str(raw)

        async def _try_exact_and_icase(q: str) -> Optional[dict]:
            d = await self.collection.find_one({"code": q})
            if d:
                return d
            return await self.collection.find_one(
                {"code": {"$regex": f"^{re.escape(q)}$", "$options": "i"}}
            )

        # 1+2. 原始值 / 去 Unicode 空白后精确 & 大小写不敏感
        for candidate in dict.fromkeys([raw, normalized]):  # 保持顺序、去重
            data = await _try_exact_and_icase(candidate)
            if data:
                data["_id"] = str(data["_id"])
                logger.debug("[multi_import] code matched (step1/2): {!r} → {}", raw, data.get("code"))
                return Asset(**data)

        # 3. 去除交易所后缀（.SZ/.SH/.IB/.CS/.WI 等）
        suffix_m = re.match(r'^(.*?)\.([A-Za-z]{1,4})$', normalized)
        bare = suffix_m.group(1) if suffix_m else None
        exchange = suffix_m.group(2).upper() if suffix_m else None

        if bare and bare != normalized:
            data = await _try_exact_and_icase(bare)
            if data:
                data["_id"] = str(data["_id"])
                logger.debug("[multi_import] code matched (suffix-strip): {!r} → {}", raw, data.get("code"))
                return Asset(**data)

            # 4. 交易所前缀格式（SZ160216 ↔ 160216.SZ）
            if exchange:
                prefix_code = exchange + bare
                data = await _try_exact_and_icase(prefix_code)
                if data:
                    data["_id"] = str(data["_id"])
                    logger.debug("[multi_import] code matched (prefix-format): {!r} → {}", raw, data.get("code"))
                    return Asset(**data)

        logger.warning(
            "[multi_import] 代码查找无结果: raw={!r} normalized={!r} bare={!r} | collection={}",
            raw, normalized, bare, self.collection.name,
        )
        return None

    async def find_assets_by_exact_name(self, name: str) -> List[Asset]:
        """按资产名称精确匹配（去首尾空格及 Unicode 不可见空白），用于多资产导入时「仅名称一致」判断。"""
        n = self._normalize_code_str(name)
        if not n:
            return []
        # 1. 精确匹配
        cursor = self.collection.find({"name": n})
        out: List[Asset] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            out.append(Asset(**doc))
        if out:
            return out
        # 2. 大小写不敏感兜底（中文名一般不涉及，但处理含英文缩写的名称）
        cursor = self.collection.find(
            {"name": {"$regex": f"^{re.escape(n)}$", "$options": "i"}}
        )
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            out.append(Asset(**doc))
        return out

    async def resolve_display_names_for_codes(self, codes: List[str]) -> Dict[str, str]:
        """
        按策略/监控中使用的代码批量解析资产展示名（查 assets 主数据）。
        兼容 Mongo 行情后缀（canonical / stored 变体），解决仅代码无中文名的问题。
        """
        from app.monitor.mongo_asset_codes import canonical_price_code, stored_price_code

        def _variants(c: str) -> List[str]:
            s = str(c).strip()
            if not s:
                return []
            out: List[str] = []
            seen: set = set()
            for v in (s, canonical_price_code(s), stored_price_code(s), stored_price_code(canonical_price_code(s))):
                vv = str(v).strip()
                if vv and vv not in seen:
                    seen.add(vv)
                    out.append(vv)
            return out

        uniq_inputs: List[str] = []
        seen_in: set = set()
        for c in codes or []:
            s = str(c).strip() if c is not None else ""
            if s and s not in seen_in:
                seen_in.add(s)
                uniq_inputs.append(s)
        if not uniq_inputs:
            return {}

        variant_set: set = set()
        for c in uniq_inputs:
            for v in _variants(c):
                variant_set.add(v)
        if not variant_set:
            return {}

        cursor = self.collection.find(
            {"code": {"$in": list(variant_set)}},
            {"code": 1, "name": 1},
        )
        by_code: Dict[str, str] = {}
        async for doc in cursor:
            code = str(doc.get("code") or "").strip()
            nm = doc.get("name")
            if code and nm is not None and str(nm).strip():
                by_code[code] = str(nm).strip()

        out: Dict[str, str] = {}
        for c in uniq_inputs:
            name = None
            for v in _variants(c):
                name = by_code.get(v)
                if name:
                    break
            if not name:
                continue
            out[c] = name
            for v in _variants(c):
                if v not in out:
                    out[v] = name
        return out
    
    def _build_asset_query(
        self,
        asset_type: Optional["AssetType"] = None,
        is_active: bool = True,
        keyword: Optional[str] = None,
        code: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构建资产查询条件（供 list_assets / count_assets 复用）。"""
        query: Dict[str, Any] = {"is_active": is_active} if is_active else {}
        if asset_type:
            query["asset_type"] = asset_type

        if keyword is not None and (kw := keyword.strip()):
            pattern = re.escape(kw)
            rx = {"$regex": pattern, "$options": "i"}
            or_clause: List[Dict[str, Any]] = [
                {"name": rx},
                {"code": rx},
            ]
            hint_codes = _keyword_hint_codes(kw)
            if hint_codes:
                or_clause.append({"code": {"$in": hint_codes}})
            query["$or"] = or_clause
        else:
            # 独立 code / name 过滤（AND 逻辑，模糊匹配）
            code_str = (code or "").strip()
            name_str = (name or "").strip()
            if code_str:
                query["code"] = {"$regex": re.escape(code_str), "$options": "i"}
            if name_str:
                query["name"] = {"$regex": re.escape(name_str), "$options": "i"}

        return query

    async def list_assets(
        self,
        asset_type: Optional[AssetType] = None,
        is_active: bool = True,
        skip: int = 0,
        limit: int = 100,
        keyword: Optional[str] = None,
        code: Optional[str] = None,
        name: Optional[str] = None,
    ) -> List[Asset]:
        """
        查询资产列表

        Args:
            asset_type: 资产类型过滤
            is_active: 是否只查询启用的资产
            skip: 跳过记录数
            limit: 返回记录数
            keyword: 按名称/代码关键字模糊匹配（Mongo 正则，不区分大小写）
            code: 资产代码模糊过滤（与 name 做 AND，keyword 存在时忽略）
            name: 资产名称模糊过滤（与 code 做 AND，keyword 存在时忽略）
        """
        query = self._build_asset_query(
            asset_type=asset_type, is_active=is_active,
            keyword=keyword, code=code, name=name,
        )
        cursor = self.collection.find(query).skip(skip).limit(limit)
        assets = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            assets.append(Asset(**doc))

        return assets

    async def count_assets(
        self,
        asset_type: Optional[AssetType] = None,
        is_active: bool = True,
        keyword: Optional[str] = None,
        code: Optional[str] = None,
        name: Optional[str] = None,
    ) -> int:
        """返回满足条件的资产总数，与 list_assets 使用相同查询条件。"""
        query = self._build_asset_query(
            asset_type=asset_type, is_active=is_active,
            keyword=keyword, code=code, name=name,
        )
        return await self.collection.count_documents(query)
    
    async def update_asset(self, asset_id: str, update_data: Dict[str, Any]) -> bool:
        """更新资产"""
        update_data['updated_at'] = datetime.now()
        result = await self.collection.update_one(
            {"_id": ObjectId(asset_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0
    
    async def delete_asset(self, asset_id: str) -> bool:
        """删除资产(软删除)"""
        result = await self.collection.update_one(
            {"_id": ObjectId(asset_id)},
            {"$set": {"is_active": False, "updated_at": datetime.now()}}
        )
        return result.modified_count > 0
    
    async def delete_asset_price_by_date(self, asset_code: str, date: str) -> bool:
        """
        删除指定资产、指定日期的单条行情记录。

        Args:
            asset_code: 资产代码（如 SH000016）。
            date: 日期字符串，要求 YYYY-MM-DD。

        Returns:
            True 表示删除成功（命中 1 条），False 表示该日期无行情记录。
        """
        d = (date or "").strip()
        if len(d) < 10:
            raise ValueError(f"日期格式错误，需 YYYY-MM-DD: {date}")
        d = d[:10].replace("/", "-")
        result = await self.price_collection.delete_one(
            {"asset_code": asset_code, "date": d}
        )
        return result.deleted_count > 0

    async def delete_asset_prices_by_dates(
        self, asset_code: str, dates: List[str]
    ) -> int:
        """
        按日期列表批量删除行情记录，返回实际删除条数。
        """
        if not dates:
            return 0
        normalized: List[str] = []
        for raw in dates:
            s = (raw or "").strip().replace("/", "-")
            if len(s) >= 10:
                normalized.append(s[:10])
        if not normalized:
            return 0
        result = await self.price_collection.delete_many(
            {"asset_code": asset_code, "date": {"$in": normalized}}
        )
        return int(result.deleted_count or 0)

    async def get_asset_prices(
        self,
        asset_code: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[AssetPrice]:
        """
        获取资产价格数据
        
        Args:
            asset_code: 资产代码
            start_date: 开始日期
            end_date: 结束日期
        """
        query = {"asset_code": asset_code}
        if start_date or end_date:
            query["date"] = {}
            if start_date:
                # 转换为 YYYY-MM-DD 字符串进行比较
                query["date"]["$gte"] = start_date.strftime('%Y-%m-%d')
            if end_date:
                query["date"]["$lte"] = end_date.strftime('%Y-%m-%d')
        
        cursor = self.price_collection.find(query).sort("date", 1)
        prices = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            prices.append(AssetPrice(**doc))
        
        return prices

    async def load_trade_calendar_date_set(self) -> Optional[Set[str]]:
        """
        加载交易日集合（YYYY-MM-DD），用于导入时跳过非交易日。

        同时读取 Mongo ``trade_dates`` 集合与 ``data/trade_dates.xlsx`` 并取并集，
        任一来源认为是交易日即视为交易日，避免增量只同步了某一边（如只更新了 xlsx 
        但未同步到 Mongo）时部分交易日被误判为非交易日。两者皆无有效数据时返回 None，
        导入不做日历过滤。
        """
        out: Set[str] = set()

        # 来源 1：Mongo trade_dates 集合
        mongo_count = 0
        try:
            col = self.db["trade_dates"]
            cursor = col.find({}).sort("date", 1)
            records = await cursor.to_list(length=None)
            for r in records or []:
                dt = r.get("date")
                if dt is None:
                    continue
                if hasattr(dt, "strftime"):
                    out.add(dt.strftime("%Y-%m-%d")[:10])
                    mongo_count += 1
                elif isinstance(dt, str):
                    s = dt.strip()
                    if len(s) >= 10:
                        out.add(s[:10])
                        mongo_count += 1
        except Exception:
            pass

        # 来源 2：data/trade_dates.xlsx，无论 Mongo 是否有值都合并
        xlsx_count = 0
        try:
            from app.data.trade_dates import load_trade_dates

            loaded = load_trade_dates()
            if loaded:
                _, td_set = loaded
                for d in td_set:
                    out.add(pd.Timestamp(d).strftime("%Y-%m-%d"))
                    xlsx_count += 1
        except Exception:
            pass

        if not out:
            return None
        # 调试日志：便于后续排查两侧是否同步
        try:
            max_date = max(out)
            print(
                f"[trade_calendar] mongo={mongo_count} xlsx={xlsx_count} "
                f"union={len(out)} max_date={max_date}"
            )
        except Exception:
            pass
        return out

    async def get_price_coverage_gaps(
        self,
        asset_code: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """
        对比「区间内应有交易日」与 Mongo 中已有行情日期，返回缺失日列表。
        优先使用 data/trade_dates.xlsx；若无文件则用工作日（周一至周五）近似。
        """
        from app.data.trade_dates import load_trade_dates

        s_str = start_date.strftime("%Y-%m-%d")
        e_str = end_date.strftime("%Y-%m-%d")

        loaded = load_trade_dates()
        if loaded:
            td_list, _ = loaded
            expected: List[str] = []
            for d in td_list:
                ds = pd.Timestamp(d).strftime("%Y-%m-%d")
                if s_str <= ds <= e_str:
                    expected.append(ds)
            mode = "trade_calendar"
        else:
            bdays = pd.bdate_range(start=s_str, end=e_str)
            expected = [x.strftime("%Y-%m-%d") for x in bdays]
            mode = "business_days"

        expected_set = set(expected)
        existing: set = set()
        cursor = self.price_collection.find(
            {"asset_code": asset_code, "date": {"$gte": s_str, "$lte": e_str}},
            {"date": 1},
        )
        async for doc in cursor:
            dt = doc.get("date")
            if isinstance(dt, str):
                existing.add(dt[:10])
            elif hasattr(dt, "strftime"):
                existing.add(dt.strftime("%Y-%m-%d"))
            else:
                existing.add(str(dt)[:10])

        missing = sorted(expected_set - existing)
        first_missing = missing[0] if missing else None
        last_missing = missing[-1] if missing else None
        return {
            "asset_code": asset_code,
            "start_date": s_str,
            "end_date": e_str,
            "calendar_mode": mode,
            "expected_trade_days": len(expected_set),
            "existing_days": len(existing),
            "missing_dates": missing,
            "first_missing": first_missing,
            "last_missing": last_missing,
        }
    
    async def bulk_insert_prices(self, prices: List[AssetPrice]) -> int:
        """批量插入价格数据"""
        if not prices:
            return 0
        
        price_dicts = [p.dict(by_alias=True, exclude={'id'}) for p in prices]
        result = await self.price_collection.insert_many(price_dicts)
        return len(result.inserted_ids)
    
    async def import_price_data(
        self,
        asset_code: str,
        price_data_list: List[dict],
        replace_existing: bool = False,
        only_missing_dates: bool = False,
        progress_id: Optional[str] = None,
        progress_asset_name: Optional[str] = None,
        progress_import_metric: Optional[str] = None,
    ) -> dict:
        """
        导入价格数据（批量 bulk_write / insert_many）。
        replace_existing=False 时按日合并：仅 $set 文件中出现的字段。
        only_missing_dates=True 时（须与 replace_existing=False 联用）：库中已有该交易日的行一律跳过，仅插入文件中尚未存在的日期。
        新交易日：须在行内提供大于 0 的收盘价（不接受仅用开/高/低推断），以便先建收盘价再补其他字段。
        已存在交易日：若本行未带有效收盘价，则库中该日须已有大于 0 的收盘价，否则拒绝（规模/成交额/OHLC 等须在收盘价之后导入）。
        replace_existing=True 时全量替换：每行均须提供大于 0 的收盘价（此时忽略 only_missing_dates）。
        若系统存在交易日历（Mongo ``trade_dates`` 或 ``data/trade_dates.xlsx``），则文件中**非交易日**的行一律跳过（不计错），避免收盘价含假期时把 OHLC/规模/成交额等写入非交易日。
        progress_*：可选，供前端轮询展示导入进度。
        """
        if replace_existing:
            only_missing_dates = False

        total_count = len(price_data_list)
        inserted_count = 0
        updated_count = 0
        skipped_count = 0
        skipped_non_trade_days = 0
        error_count = 0
        errors: List[str] = []
        pan = (progress_asset_name or "").strip()

        async def _prog(
            phase: str,
            prepare_done: int = 0,
            write_done: int = 0,
            write_total: int = 0,
            message: str = "",
        ):
            await touch_progress(
                progress_id,
                asset_code=asset_code,
                asset_name=pan,
                import_metric=progress_import_metric,
                phase=phase,
                prepare_done=prepare_done,
                file_line_total=total_count,
                write_done=write_done,
                write_total=write_total,
                message=message,
            )

        # 须在 load_trade_calendar_date_set 等耗时步骤之前写入进度，否则前端轮询长时间 data=null
        if progress_id and total_count:
            await _prog("prepare", prepare_done=0, message="开始处理（加载交易日历…）")

        trade_calendar: Optional[Set[str]] = await self.load_trade_calendar_date_set()
        if trade_calendar:
            print(
                f"[行情导入-service] 已加载交易日历 {len(trade_calendar)} 天，将跳过不在历内的日期"
            )
        else:
            print(
                "[行情导入-service] 未加载到交易日历（Mongo trade_dates 与 data/trade_dates.xlsx 均为空），"
                "不按日历过滤日期"
            )

        print(
            f"[行情导入-service] asset_code={asset_code} 待导入 {total_count} 条 "
            f"replace_existing={replace_existing} only_missing_dates={only_missing_dates}"
        )
        if progress_id and total_count:
            await _prog("prepare", prepare_done=0, message="解析与校验数据…")

        def _prepare_row(idx: int, price_data: dict, errs: List[str]) -> Optional[Tuple[str, Dict[str, Any]]]:
            nonlocal error_count
            try:
                date_formatted = _normalize_import_date(price_data.get("date"))
                sparse = _sparse_price_fields(price_data)
                if not sparse:
                    raise ValueError("未提供任何有效行情数值列")
                return date_formatted, sparse
            except Exception as e:
                error_count += 1
                err_msg = f"第{idx + 1}行错误: {str(e)}"
                errs.append(err_msg)
                if error_count <= 3:
                    print(f"[行情导入-service] {err_msg}")
                return None

        if replace_existing:
            deleted = await self.price_collection.delete_many({"asset_code": asset_code})
            print(f"[行情导入-service] 已删除旧数据: {deleted.deleted_count} 条")

            documents: List[dict] = []
            for idx, pd_item in enumerate(price_data_list):
                prep = _prepare_row(idx, pd_item, errors)
                if not prep:
                    continue
                date_formatted, sparse = prep
                if trade_calendar is not None and date_formatted not in trade_calendar:
                    skipped_non_trade_days += 1
                    continue
                if not _explicit_close_positive(sparse):
                    error_count += 1
                    err_msg = (
                        f"第{idx + 1}行错误: 全量覆盖每行均须提供大于 0 的收盘价"
                    )
                    errors.append(err_msg)
                    if error_count <= 3:
                        print(f"[行情导入-service] {err_msg}")
                    continue
                ec = float(sparse["close"])
                documents.append(_full_price_document(asset_code, date_formatted, sparse, ec))
                if progress_id and total_count and ((idx + 1) % 200 == 0 or (idx + 1) == total_count):
                    await _prog(
                        "prepare",
                        prepare_done=idx + 1,
                        message=f"准备全量数据 {idx + 1}/{total_count}",
                    )
            n_doc = len(documents)
            # 即使 n_doc=0 也要刷新进度，避免前端卡在 "写入数据库 0/xxx"
            if progress_id:
                if n_doc > 0:
                    await _prog(
                        "write",
                        prepare_done=total_count,
                        write_done=0,
                        write_total=n_doc,
                        message=f"写入数据库 0/{n_doc}（文件共 {total_count} 行）",
                    )
                else:
                    # n_doc=0 说明没有可写入的数据，告知前端跳过原因
                    reason = f"无待写入数据（已跳过 {skipped_non_trade_days} 条非交易日，"
                    reason += f"{error_count} 条无效数据）"
                    await _prog(
                        "done",
                        prepare_done=total_count,
                        write_done=0,
                        write_total=1,
                        message=reason,
                    )
            batch_size = PRICE_IMPORT_BATCH_SIZE
            for i in range(0, len(documents), batch_size):
                await asyncio.sleep(0)
                batch = documents[i : i + batch_size]
                try:
                    result = await self.price_collection.insert_many(batch, ordered=False)
                    inserted_count += len(result.inserted_ids)
                    done = min(i + batch_size, len(documents))
                    print(f"[行情导入-service] 进度: {done}/{len(documents)}")
                    if progress_id:
                        await _prog(
                            "write",
                            prepare_done=total_count,
                            write_done=done,
                            write_total=n_doc,
                            message=f"写入数据库 {done}/{n_doc}（文件共 {total_count} 行）",
                        )
                        await asyncio.sleep(0)
                except Exception as e:
                    err_msg = f"第{i + 1}-{min(i + batch_size, len(documents))}批写入失败: {str(e)}"
                    errors.append(err_msg)
                    error_count += len(batch)
                    print(f"[行情导入-service] {err_msg}")
            skipped_count = max(0, total_count - inserted_count - error_count)
        else:
            prepared: List[Tuple[int, str, Dict[str, Any]]] = []
            for idx, pd_item in enumerate(price_data_list):
                prep = _prepare_row(idx, pd_item, errors)
                if prep:
                    date_formatted, sparse = prep
                    if trade_calendar is not None and date_formatted not in trade_calendar:
                        skipped_non_trade_days += 1
                        continue
                    prepared.append((idx, date_formatted, sparse))
                if progress_id and total_count and ((idx + 1) % 200 == 0 or (idx + 1) == total_count):
                    await _prog(
                        "prepare",
                        prepare_done=idx + 1,
                        message=f"解析与校验 {idx + 1}/{total_count}",
                    )

            dates_unique = sorted({p[1] for p in prepared})
            existing_dates, dates_with_positive_close = await self.load_existing_dates_and_positive_close_bulk(
                asset_code, dates_unique
            )

            operations: List[UpdateOne] = []
            skipped_existing_rows = 0
            opi = 0
            for idx, date_formatted, sparse in prepared:
                if date_formatted in existing_dates:
                    if only_missing_dates:
                        skipped_existing_rows += 1
                        continue
                    if not sparse:
                        continue
                    if not _explicit_close_positive(sparse):
                        if date_formatted not in dates_with_positive_close:
                            error_count += 1
                            err_msg = (
                                f"第{idx + 1}行错误: 日期 {date_formatted} 库中尚无有效收盘价，"
                                "须先导入该日收盘价后再导入规模/成交额/成交量/OHLC 等；若本行含收盘价请填大于 0"
                            )
                            errors.append(err_msg)
                            if error_count <= 3:
                                print(f"[行情导入-service] {err_msg}")
                            continue
                    operations.append(
                        UpdateOne(
                            {"asset_code": asset_code, "date": date_formatted},
                            {"$set": sparse},
                            upsert=False,
                        )
                    )
                else:
                    if not _explicit_close_positive(sparse):
                        error_count += 1
                        err_msg = (
                            f"第{idx + 1}行错误: 库中无日期 {date_formatted} 的行情时，"
                            "须在本行提供大于 0 的收盘价（须先导入收盘价后再补其他字段）"
                        )
                        errors.append(err_msg)
                        if error_count <= 3:
                            print(f"[行情导入-service] {err_msg}")
                        continue
                    ec = float(sparse["close"])
                    full_doc = _full_price_document(asset_code, date_formatted, sparse, ec)
                    operations.append(
                        UpdateOne(
                            {"asset_code": asset_code, "date": date_formatted},
                            {"$set": full_doc},
                            upsert=True,
                        )
                    )
                opi += 1
                if progress_id and len(prepared) and (opi % 300 == 0 or opi == len(prepared)):
                    await _prog(
                        "prepare",
                        prepare_done=opi,
                        message=f"构建待写入操作 {opi}/{len(prepared)}（文件 {total_count} 行）",
                    )

            n_op = len(operations)
            # 即使 n_op=0 也要刷新进度，避免前端卡在 "写入数据库 0/xxx"
            if progress_id:
                if n_op > 0:
                    await _prog(
                        "write",
                        prepare_done=len(prepared),
                        write_done=0,
                        write_total=n_op,
                        message=f"写入数据库 0/{n_op}（文件共 {total_count} 行）",
                    )
                else:
                    # n_op=0 说明没有可写入的数据，告知前端跳过原因
                    reason = f"无待写入操作（已跳过 {skipped_existing_rows} 条已有日期，"
                    reason += f"{skipped_non_trade_days} 条非交易日）"
                    await _prog(
                        "done",
                        prepare_done=len(prepared),
                        write_done=0,
                        write_total=1,
                        message=reason,
                    )
            batch_size = PRICE_IMPORT_BATCH_SIZE
            for i in range(0, len(operations), batch_size):
                await asyncio.sleep(0)
                batch = operations[i : i + batch_size]
                try:
                    result = await self.price_collection.bulk_write(batch, ordered=False)
                    inserted_count += result.upserted_count
                    updated_count += result.modified_count
                    done = min(i + batch_size, len(operations))
                    if progress_id:
                        await _prog(
                            "write",
                            prepare_done=len(prepared),
                            write_done=done,
                            write_total=n_op,
                            message=f"写入数据库 {done}/{n_op}（文件共 {total_count} 行）",
                        )
                        await asyncio.sleep(0)
                except Exception as e:
                    batch_start, batch_end = i + 1, min(i + batch_size, len(operations))
                    err_msg = f"第{batch_start}-{batch_end}批写入失败: {str(e)}"
                    errors.append(err_msg)
                    error_count += len(batch)
                    print(f"[行情导入-service] {err_msg}")
            bulk_tail_skipped = max(0, len(operations) - inserted_count - updated_count)
            skipped_count = skipped_existing_rows + bulk_tail_skipped + skipped_non_trade_days

        print(f"[行情导入-service] 结束 inserted={inserted_count} updated={updated_count} skipped={skipped_count} error={error_count} skipped_non_trade={skipped_non_trade_days}")

        out = {
            "total_count": total_count,
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "skipped_non_trade_days": skipped_non_trade_days,
            "error_count": error_count,
            "errors": errors,
        }
        if progress_id:
            await _prog(
                "done",
                prepare_done=total_count,
                write_done=out.get("inserted_count", 0) + out.get("updated_count", 0),
                write_total=max(1, total_count),
                message="导入完成",
            )
        return out

    async def get_price_date_bounds_and_count(
        self, asset_code: str
    ) -> Tuple[Optional[str], Optional[str], int]:
        """库中该资产行情最小/最大日期与总条数；无数据时 (None, None, 0)。"""
        if not asset_code:
            return None, None, 0
        pipeline = [
            {"$match": {"asset_code": asset_code}},
            {
                "$group": {
                    "_id": None,
                    "date_min": {"$min": "$date"},
                    "date_max": {"$max": "$date"},
                    "cnt": {"$sum": 1},
                }
            },
        ]
        cursor = self.price_collection.aggregate(pipeline)
        async for doc in cursor:
            return (
                doc.get("date_min"),
                doc.get("date_max"),
                int(doc.get("cnt") or 0),
            )
        return None, None, 0

    async def find_existing_price_dates_in_set(
        self, asset_code: str, dates: List[str]
    ) -> Set[str]:
        """在给定日期列表中，返回库中已存在的日期（用于预览重叠）。"""
        if not asset_code or not dates:
            return set()
        out: Set[str] = set()
        chunk = 800
        for i in range(0, len(dates), chunk):
            part = dates[i : i + chunk]
            cursor = self.price_collection.find(
                {"asset_code": asset_code, "date": {"$in": part}},
                {"date": 1, "_id": 0},
            )
            async for doc in cursor:
                d = doc.get("date")
                if d:
                    out.add(d)
        return out

    async def find_dates_with_positive_close(
        self, asset_code: str, dates: List[str]
    ) -> Set[str]:
        """在给定日期中，返回库中已存在且 close>0 的日期（用于校验「先收盘价再补其他字段」）。"""
        if not asset_code or not dates:
            return set()
        out: Set[str] = set()
        chunk = 800
        for i in range(0, len(dates), chunk):
            part = dates[i : i + chunk]
            cursor = self.price_collection.find(
                {
                    "asset_code": asset_code,
                    "date": {"$in": part},
                    "close": {"$gt": 0},
                },
                {"date": 1, "_id": 0},
            )
            async for doc in cursor:
                d = doc.get("date")
                if d:
                    out.add(str(d)[:10])
        return out

    async def load_existing_dates_and_positive_close_bulk(
        self, asset_code: str, dates: List[str]
    ) -> Tuple[Set[str], Set[str]]:
        """
        单次按日期分批查询库里已有行情（含 close），导入与预览共用。
        避免先 find_existing_dates 再 find_dates_with_positive_close 的两倍 round-trip。
        """
        if not asset_code or not dates:
            return set(), set()
        existing: Set[str] = set()
        positive: Set[str] = set()
        chunk = 1500
        for i in range(0, len(dates), chunk):
            part = dates[i : i + chunk]
            cursor = self.price_collection.find(
                {"asset_code": asset_code, "date": {"$in": part}},
                {"date": 1, "close": 1, "_id": 0},
            )
            async for doc in cursor:
                d = doc.get("date")
                if not d:
                    continue
                ds = str(d)[:10]
                existing.add(ds)
                cv = doc.get("close")
                try:
                    if cv is not None and float(cv) > 0:
                        positive.add(ds)
                except (TypeError, ValueError):
                    pass
        return existing, positive

    async def compute_price_import_preview_stats(
        self, target_code: str, prices: List[dict]
    ) -> dict:
        """
        预览导入影响：库内已有区间 + 按日合并 vs 全量覆盖 两种模式下的条数/日期区间。
        replace_existing=false：同日 upsert，重叠日为更新、新日为插入。
        replace_existing=true：删除该资产全部行情后插入文件中的行。
        与 import_price_data 一致：若已加载交易日历，文件中不在历内的日期不计入预览（避免「显示将新增」实际写入被跳过）。
        """
        empty = {
            "target_code": target_code or "",
            "existing_date_min": None,
            "existing_date_max": None,
            "existing_price_count": 0,
            "file_unique_date_count": 0,
            "file_row_count": len(prices) if prices else 0,
            "skipped_non_trade_rows": 0,
            "merge_import": {
                "will_insert_count": 0,
                "will_update_count": 0,
                "new_dates_min": None,
                "new_dates_max": None,
                "overlap_dates_min": None,
                "overlap_dates_max": None,
            },
            "full_replace": {
                "will_delete_count": 0,
                "will_insert_count": 0,
                "result_date_min": None,
                "result_date_max": None,
            },
        }
        if not target_code or not prices:
            return empty

        trade_calendar: Optional[Set[str]] = await self.load_trade_calendar_date_set()
        skipped_non_trade_rows = 0
        norm_file_dates: List[str] = []
        for p in prices:
            pd = p if isinstance(p, dict) else (
                p.model_dump(exclude_none=True) if hasattr(p, "model_dump") else p.dict(exclude_none=True)
            )
            try:
                ds = _normalize_import_date(pd.get("date"))
            except Exception:
                continue
            if trade_calendar is not None and ds not in trade_calendar:
                skipped_non_trade_rows += 1
                continue
            norm_file_dates.append(ds)
        empty["skipped_non_trade_rows"] = skipped_non_trade_rows
        file_dates_unique = sorted(set(norm_file_dates))
        empty["file_unique_date_count"] = len(file_dates_unique)
        d_file_min = file_dates_unique[0] if file_dates_unique else None
        d_file_max = file_dates_unique[-1] if file_dates_unique else None

        e_min, e_max, e_cnt = await self.get_price_date_bounds_and_count(target_code)
        empty["existing_date_min"] = e_min
        empty["existing_date_max"] = e_max
        empty["existing_price_count"] = e_cnt

        existing_on_dates, dates_with_close = await self.load_existing_dates_and_positive_close_bulk(
            target_code, file_dates_unique
        )
        overlap = sorted(existing_on_dates)
        new_only = [d for d in file_dates_unique if d not in existing_on_dates]
        new_only_set = set(new_only)

        date_to_sparses: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for p in prices:
            pd = p if isinstance(p, dict) else (
                p.model_dump(exclude_none=True) if hasattr(p, "model_dump") else p.dict(exclude_none=True)
            )
            try:
                ds = _normalize_import_date(pd.get("date"))
            except Exception:
                continue
            if trade_calendar is not None and ds not in trade_calendar:
                continue
            date_to_sparses[ds].append(_sparse_price_fields(pd))

        def _file_has_explicit_close_for_date(d: str) -> bool:
            return any(_explicit_close_positive(sp) for sp in date_to_sparses.get(d, []))

        new_dates_insertable: Set[str] = set()
        for d in new_only:
            if _file_has_explicit_close_for_date(d):
                new_dates_insertable.add(d)

        will_update = 0
        for d in overlap:
            if d in dates_with_close or _file_has_explicit_close_for_date(d):
                will_update += 1

        merge = empty["merge_import"]
        merge["will_update_count"] = will_update
        merge["will_insert_count"] = len(new_dates_insertable)
        ins_sorted = sorted(new_dates_insertable)
        if ins_sorted:
            merge["new_dates_min"] = ins_sorted[0]
            merge["new_dates_max"] = ins_sorted[-1]
        if overlap:
            merge["overlap_dates_min"] = overlap[0]
            merge["overlap_dates_max"] = overlap[-1]

        full = empty["full_replace"]
        full["will_delete_count"] = e_cnt
        ins_full = 0
        for p in prices:
            pd = p if isinstance(p, dict) else (
                p.model_dump(exclude_none=True) if hasattr(p, "model_dump") else p.dict(exclude_none=True)
            )
            try:
                ds = _normalize_import_date(pd.get("date"))
            except Exception:
                continue
            if trade_calendar is not None and ds not in trade_calendar:
                continue
            if _explicit_close_positive(_sparse_price_fields(pd)):
                ins_full += 1
        full["will_insert_count"] = ins_full
        full["result_date_min"] = d_file_min
        full["result_date_max"] = d_file_max

        return empty

    async def get_latest_price_date(self, asset_code: str) -> Optional[str]:
        """
        获取资产的最新价格数据日期
        
        Returns:
            最新日期字符串（YYYY-MM-DD），如果没有数据则返回 None
        """
        cursor = self.price_collection.find(
            {"asset_code": asset_code}
        ).sort("date", -1).limit(1)
        
        async for doc in cursor:
            return doc.get("date")  # 已经是 YYYY-MM-DD 字符串格式
        return None
    
    async def get_latest_price_dates(self, asset_codes: List[str]) -> Dict[str, Optional[str]]:
        """
        批量获取多个资产的最新价格数据日期
        
        Returns:
            字典：{asset_code: latest_date 或 None}
        """
        result = {}
        for code in asset_codes:
            result[code] = await self.get_latest_price_date(code)
        return result
    
    async def get_price_dataframe(
        self,
        asset_codes: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        获取多个资产的价格DataFrame
        
        Returns:
            DataFrame with columns as asset_codes and index as dates
        """
        all_data = {}
        
        for code in asset_codes:
            prices = await self.get_asset_prices(code, start_date, end_date)
            if prices:
                df = pd.DataFrame([{
                    'date': p.date,  # 现在是字符串格式 YYYY-MM-DD
                    'close': p.close
                } for p in prices])
                # 转换为 datetime 索引
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                all_data[code] = df['close']
        
        if not all_data:
            return pd.DataFrame()
        
        # 合并所有资产数据
        result_df = pd.DataFrame(all_data)
        return result_df

    async def import_assets_from_excel_data(self, assets_data: List[dict]) -> dict:
        """
        从 Excel 数据批量导入资产
        
        Args:
            assets_data: 资产数据列表
            
        Returns:
            统计结果
        """
        total_count = len(assets_data)
        inserted_count = 0
        updated_count = 0
        error_count = 0
        errors = []

        for idx, item in enumerate(assets_data):
            try:
                code = item.get('code')
                if not code:
                    raise ValueError("资产代码不能为空")
                
                # 转换资产类型字符串为枚举名(如果需要)
                # MongoDB 存储的是字符串值，Asset 类初始化会自动处理
                
                # 检查资产是否已存在
                existing = await self.get_asset_by_code(code)
                
                if existing:
                    # 更新
                    update_data = {k: v for k, v in item.items() if v is not None and k != 'code'}
                    if update_data:
                        await self.update_asset(existing.id, update_data)
                        updated_count += 1
                else:
                    # 创建
                    asset = Asset(**item)
                    await self.create_asset(asset)
                    inserted_count += 1
                    
            except Exception as e:
                error_count += 1
                errors.append(f"第{idx + 2}行({item.get('code', '未知')}): {str(e)}")

        return {
            "total_count": total_count,
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "error_count": error_count,
            "errors": errors
        }

    @staticmethod
    def _cell_as_date_string(val: Any) -> Optional[str]:
        if _is_blank_val(val):
            return None
        if hasattr(val, "strftime"):
            try:
                return val.strftime("%Y-%m-%d")
            except Exception:
                return None
        # Excel 序列日期（A 列为数值）
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            fv = float(val)
            if 20000 < fv < 80000:
                try:
                    base = datetime(1899, 12, 30)
                    return (base + timedelta(days=fv)).strftime("%Y-%m-%d")
                except (OverflowError, ValueError, OSError):
                    pass
        s = str(val).strip()
        if not s:
            return None
        digits = s.replace("-", "").replace("/", "").replace(".", "")[:8]
        if len(digits) == 8 and digits.isdigit():
            try:
                return datetime.strptime(digits, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                return None
        try:
            ts = pd.to_datetime(s, errors="coerce")
            if not pd.isna(ts):
                return pd.Timestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            pass
        return None

    @staticmethod
    def _code_cell_plausible_for_wide_header(val: Any) -> bool:
        """宽表「资产代码」行：排除 Date、纯价格小数、8 位日期串等误识别。"""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return False
        if isinstance(val, float) and val == int(val) and abs(val) < 1e12:
            cs = str(int(val))
        else:
            cs = str(val).strip()
        if re.fullmatch(r"\d+\.0+", cs):
            cs = cs.split(".")[0]
        if not cs or len(cs) < 3:
            return False
        low = cs.lower()
        if low in ("date", "日期", "datetime", "时间"):
            return False
        if re.fullmatch(r"\d{8}", cs):
            return False
        if re.fullmatch(r"\d{1,6}\.\d{2,6}", cs) and not any(
            suf in cs for suf in (".SH", ".SZ", ".CS", ".IB", ".WI", ".OF", ".HK")
        ):
            return False
        # 以中文为主的长串多为资产展示名，不应当作「代码行」判定（避免 Wind 双行表误判为 code_on_row0）
        cjk_n = sum(1 for ch in cs if "\u4e00" <= ch <= "\u9fff")
        if cjk_n >= 4:
            return False
        return True

    @staticmethod
    def _looks_like_exchange_or_wind_symbol(val: Any) -> bool:
        """是否像交易所/Wind 证券码（用于判断双行表头是 code-on-row0 还是 code-on-row1）。"""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return False
        if isinstance(val, float) and val == int(val) and abs(val) < 1e15:
            cs = str(int(val))
        else:
            cs = str(val).strip()
            if re.fullmatch(r"\d+\.0+", cs):
                cs = cs.split(".")[0]
        if not cs:
            return False
        up = cs.upper()
        if any(up.endswith(sfx) for sfx in (".SH", ".SZ", ".CS", ".IB", ".WI", ".OF", ".HK")):
            return True
        if re.fullmatch(r"\d{6}", cs):
            return True
        if re.match(r"^[A-Z]{2,8}\d[A-Z0-9.]*", up):
            return True
        return False

    @staticmethod
    def _name_cell_plausible_for_wide_header(name_val: Any, code_val: Any) -> bool:
        """宽表「资产名称」行：排除 Date、与代码同为价格型数值等。"""
        if name_val is None or (isinstance(name_val, float) and pd.isna(name_val)):
            return False
        ns = str(name_val).strip()
        if not ns or ns in ("Date", "日期") or ns.lower() == "date":
            return False
        c_raw = code_val
        if c_raw is not None and not (isinstance(c_raw, float) and pd.isna(c_raw)):
            cs = str(c_raw).strip()
            try:
                fn = float(ns.replace(",", ""))
                fc = float(cs.replace(",", ""))
                if fn > 50 and fc > 50 and abs(fn - fc) / max(fn, fc) < 0.02:
                    return False
            except ValueError:
                pass
        return True

    @classmethod
    def _wide_layout_has_asset_columns(
        cls, df: "pd.DataFrame", names_row: int, codes_row: int
    ) -> bool:
        """在指定名称行/代码行上是否至少有一列像资产（用于选择固定布局 vs 自动探测）。"""
        if df.shape[0] <= max(names_row, codes_row) or df.shape[1] < 2:
            return False
        max_j = min(df.shape[1], 128)
        for j in range(1, max_j):
            code_cell = df.iloc[codes_row, j]
            if not cls._code_cell_plausible_for_wide_header(code_cell):
                continue
            name_cell = df.iloc[names_row, j]
            if not cls._name_cell_plausible_for_wide_header(name_cell, code_cell):
                continue
            return True
        return False

    def _detect_wide_sheet_layout(self, df: "pd.DataFrame") -> Optional[Tuple[int, int, int]]:
        """
        根据 A 列连续日期行推断「名称行、代码行、数据起始行」。
        成功返回 (names_row_idx, codes_row_idx, data_start_row)；失败返回 None（调用方回退到 3/4/5）。
        """
        max_r = min(len(df), 28)
        for dr in range(max_r - 1):
            d0 = self._cell_as_date_string(df.iloc[dr, 0])
            d1 = self._cell_as_date_string(df.iloc[dr + 1, 0])
            if d0 and d1 and dr >= 2:
                return dr - 2, dr - 1, dr
        return None

    @staticmethod
    def _norm_header_a0(val: Any) -> str:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        return str(val).strip()

    @staticmethod
    def _header_row_contains_keyword(df: "pd.DataFrame", row_idx: int, keys: Tuple[str, ...]) -> bool:
        """表头可能在 A1，也可能因合并单元格落在 B1/C1 等。"""
        if row_idx < 0 or row_idx >= len(df):
            return False
        max_c = min(df.shape[1], 8)
        for col in range(max_c):
            s = AssetService._norm_header_a0(df.iloc[row_idx, col])
            if any(kw in s for kw in keys):
                return True
        return False

    def _first_data_row_in_column_a(self, df: "pd.DataFrame", from_row: int = 2) -> Optional[int]:
        """自 from_row 起在 A 列找连续两行均为日期的起始行；否则找首个单日。"""
        lim = min(len(df) - 1, from_row + 200)
        for r in range(from_row, lim):
            if self._cell_as_date_string(df.iloc[r, 0]) and self._cell_as_date_string(df.iloc[r + 1, 0]):
                return r
        for r in range(from_row, min(len(df), from_row + 200)):
            if self._cell_as_date_string(df.iloc[r, 0]):
                return r
        return None

    def _try_fund_signature_rows_0_1_col_b(
        self, df: "pd.DataFrame"
    ) -> Optional[Tuple[int, int, int]]:
        """
        图3 等表：首行各列为代码、次行为名称；数据区从 A 列首次出现连续日期行开始（可跳过「日期」表头行）。
        不依赖 A1 是否为「基金代码」（合并后 A1 常为空）。
        """
        if df.shape[0] < 3 or df.shape[1] < 2:
            return None
        data_start = self._first_data_row_in_column_a(df, 2)
        if data_start is None:
            return None
        # 若多数列在「下一行」更像证券码、而首行不像，则不是「首行代码·次行名称」模板（常见于：首行中文名、次行 Wind 码）
        t0 = t1 = 0
        for j in range(1, min(df.shape[1], 64)):
            if self._looks_like_exchange_or_wind_symbol(df.iloc[0, j]):
                t0 += 1
            if self._looks_like_exchange_or_wind_symbol(df.iloc[1, j]):
                t1 += 1
        if t1 >= 2 and t1 > t0:
            return None
        ok = 0
        for j in range(1, min(df.shape[1], 64)):
            c0 = df.iloc[0, j]
            n1 = df.iloc[1, j]
            if self._code_cell_plausible_for_wide_header(c0) and self._name_cell_plausible_for_wide_header(
                n1, c0
            ):
                ok += 1
        if ok < 2:
            return None
        if self._wide_layout_has_asset_columns(df, 1, 0):
            return 1, 0, data_start
        return None

    def _try_date_corner_cn_name_wind_code_rows_0_1(
        self, df: "pd.DataFrame"
    ) -> Optional[Tuple[int, int, int]]:
        """
        Wind/通用导出：A1 为「日期」、A2 为「Date」，第 0 行中文资产名、第 1 行 Wind/交易所代码，自第 3 行起为时间序列。
        （如：大类资产底层数据上传版本.xlsx）
        """
        if df.shape[0] < 3 or df.shape[1] < 2:
            return None
        a0 = self._norm_header_a0(df.iloc[0, 0])
        a1 = self._norm_header_a0(df.iloc[1, 0])
        if "日期" not in a0 and a0 != "日期":
            return None
        if a1.strip().lower() != "date":
            return None
        if not self._wide_layout_has_asset_columns(df, 0, 1):
            return None
        data_start = self._first_data_row_in_column_a(df, 2)
        if data_start is None:
            return None
        return 0, 1, data_start

    def _try_fund_or_security_two_row_header_layout(
        self, df: "pd.DataFrame"
    ) -> Optional[Tuple[int, int, int]]:
        """
        新宽表：前两行表头，A 列（或首几列）为「基金代码/基金名称」等，
        自第 3 行（index 2）起为日期 + 各列行情。返回 (names_row_idx, codes_row_idx, data_start_row)。
        """
        if df.shape[0] < 3 or df.shape[1] < 2:
            return None
        code_like = ("基金代码", "证券代码", "资产代码")
        name_like = ("基金名称", "证券名称", "资产名称")

        # 1) 结构签名：首行代码 + 次行名称 + 第3行 A 为日期（解决 A1 合并为空）
        sig = self._try_fund_signature_rows_0_1_col_b(df)
        if sig:
            return sig

        a0 = self._norm_header_a0(df.iloc[0, 0])
        a1 = self._norm_header_a0(df.iloc[1, 0])

        def has_any(s: str, keys: tuple) -> bool:
            return any(k in s for k in keys)

        # 2) A1/A2 文案（或首行前几列）含基金/证券代码、名称
        row0_kw = has_any(a0, code_like) or self._header_row_contains_keyword(df, 0, code_like)
        row1_kw = has_any(a1, name_like) or self._header_row_contains_keyword(df, 1, name_like)
        if row0_kw and row1_kw:
            dr = self._first_data_row_in_column_a(df, 2)
            if dr is None:
                return None
            names_row, codes_row, data_start = 1, 0, dr
            if self._wide_layout_has_asset_columns(df, names_row, codes_row):
                return names_row, codes_row, data_start

        row0_name = has_any(a0, name_like) or self._header_row_contains_keyword(df, 0, name_like)
        row1_code = has_any(a1, code_like) or self._header_row_contains_keyword(df, 1, code_like)
        if row0_name and row1_code:
            dr = self._first_data_row_in_column_a(df, 2)
            if dr is None:
                return None
            names_row, codes_row, data_start = 0, 1, dr
            if self._wide_layout_has_asset_columns(df, names_row, codes_row):
                return names_row, codes_row, data_start
        return None

    def _resolve_multi_asset_wide_layout(self, df: "pd.DataFrame") -> Tuple[int, int, int]:
        """
        多模板兼容（优先级）：
        1) Wind 导出：行0中文名·行1代码，A1「日期」+ A2「Date」拐角签名
        2) 基金/证券 两行表头 + 第3行起数据（含：首行代码·次行名称等）
        3) Wind 类：名称/代码在 3、4 行，数据自第6行起
        4) A 列连续日期推断 + 名称/代码行校验
        5) 回退 3/4/5
        """
        corner = self._try_date_corner_cn_name_wind_code_rows_0_1(df)
        if corner:
            return corner
        fund = self._try_fund_or_security_two_row_header_layout(df)
        if fund:
            return fund
        if self._wide_layout_has_asset_columns(df, 3, 4):
            return 3, 4, 5
        layout = self._detect_wide_sheet_layout(df)
        if layout:
            nr, cr, dr = layout
            if self._wide_layout_has_asset_columns(df, nr, cr):
                return nr, cr, dr
        return 3, 4, 5

    def _parse_multi_asset_excel(self, contents: bytes, metric: str = "close") -> List[dict]:
        """
        解析多资产宽表 Excel（兼容：Wind「日期/Date」拐角 + 行0中文名·行1 Wind 码；
        Wind 类第4～6行布局；基金/证券代码+名称两行表头自第3行起等）。
        metric：列内数值写入 close / open / high / low / amount / volume / scale。
        """
        metric = (metric or "close").strip().lower()
        allowed_m = {"close", "open", "high", "low", "amount", "volume", "scale"}
        if metric not in allowed_m:
            metric = "close"
        value_key = metric

        buf = io.BytesIO(contents)
        xl_file = pd.ExcelFile(buf)
        sheets = [s for s in xl_file.sheet_names if s]
        assets_with_prices: List[dict] = []
        seen_codes: Set[str] = set()

        _header_tokens_skip = frozenset(
            (
                "date",
                "日期",
                "基金代码",
                "基金名称",
                "证券代码",
                "证券名称",
                "资产代码",
                "资产名称",
            )
        )

        for sheet_name in sheets:
            df = xl_file.parse(sheet_name=sheet_name, header=None)
            if df.shape[0] < 3 or df.shape[1] < 2:
                continue
            names_row_idx, codes_row_idx, data_start_row = self._resolve_multi_asset_wide_layout(df)
            names = df.iloc[names_row_idx].tolist()
            codes = df.iloc[codes_row_idx].tolist()
            dates = df.iloc[data_start_row:, 0].values
            max_col = max(len(names), len(codes))

            for col_idx in range(1, max_col):
                name = names[col_idx] if col_idx < len(names) else None
                code = codes[col_idx] if col_idx < len(codes) else None
                if pd.isna(name) or str(name).strip() == "" or str(name) == "Date":
                    continue
                code_str = str(code).strip() if code is not None and not pd.isna(code) else ""
                name_str = str(name).strip()
                low_name = name_str.lower()
                if low_name in _header_tokens_skip or name_str in _header_tokens_skip:
                    continue
                if not code_str or code_str == "Date" or code_str.lower() in _header_tokens_skip:
                    continue
                if code_str in seen_codes:
                    continue
                values = df.iloc[data_start_row:, col_idx].values
                valid_mask = pd.notna(values) & (values != "")
                if not valid_mask.any():
                    continue
                seen_codes.add(code_str)

                prices = []
                for d, v in zip(dates, values):
                    if pd.isna(v) or v == "":
                        continue
                    try:
                        num_val = float(v)
                    except (TypeError, ValueError):
                        continue
                    date_str = self._to_iso_date(d)
                    rec = {
                        "date": date_str,
                        "open": None,
                        "high": None,
                        "low": None,
                        "close": None,
                        "volume": None,
                        "amount": None,
                        "scale": None,
                    }
                    if value_key == "volume":
                        rec[value_key] = int(round(num_val))
                    else:
                        rec[value_key] = num_val
                    prices.append(rec)
                if prices:
                    assets_with_prices.append({
                        "code": code_str,
                        "name": name_str,
                        "prices": prices,
                        "price_count": len(prices),
                    })
                    if len(assets_with_prices) >= MAX_MULTI_ASSET_COLUMNS_PER_SHEET:
                        break
            if len(assets_with_prices) >= MAX_MULTI_ASSET_COLUMNS_PER_SHEET:
                break
        return assets_with_prices

    @staticmethod
    def _date_range_from_prices(prices: List[dict]) -> tuple:
        if not prices:
            return None, None
        ds = [p.get("date") for p in prices if p.get("date")]
        if not ds:
            return None, None
        return min(ds), max(ds)

    async def _enrich_multi_asset_row(self, item: dict) -> dict:
        """为解析结果补充匹配类型、系统侧信息等（含 prices）。"""
        code = item["code"]
        name = item["name"]
        logger.debug("[multi_import] 开始匹配 file_code={!r} file_name={!r}", code, name)
        prices = item.get("prices") or []
        dmin, dmax = self._date_range_from_prices(prices)
        base: Dict[str, Any] = {
            "file_code": code,
            "file_name": name,
            "prices": prices,
            "price_count": len(prices),
            "date_min": dmin,
            "date_max": dmax,
        }
        by_code = await self.find_asset_by_code_tolerant(code)
        if by_code:
            nm_sys = (by_code.name or "").strip()
            nm_file = (name or "").strip()
            latest = await self.get_latest_price_date(code)
            if nm_sys == nm_file:
                base["match_kind"] = "exact"
            else:
                base["match_kind"] = "code_name_diff"
            base["system_code"] = by_code.code
            base["system_name"] = by_code.name
            base["suggested_import_code"] = by_code.code
            base["has_prices"] = latest is not None
            base["name_match_candidates"] = []
        else:
            name_hits = await self.find_assets_by_exact_name(name)
            if not name_hits:
                base["match_kind"] = "new_asset"
                base["system_code"] = None
                base["system_name"] = None
                base["suggested_import_code"] = code
                base["has_prices"] = False
                base["name_match_candidates"] = []
            elif len(name_hits) == 1:
                a = name_hits[0]
                latest = await self.get_latest_price_date(a.code)
                base["match_kind"] = "name_code_diff"
                base["system_code"] = a.code
                base["system_name"] = a.name
                base["suggested_import_code"] = a.code
                base["has_prices"] = latest is not None
                base["name_match_candidates"] = []
            else:
                base["match_kind"] = "name_ambiguous"
                base["system_code"] = None
                base["system_name"] = None
                base["suggested_import_code"] = name_hits[0].code
                latest0 = await self.get_latest_price_date(name_hits[0].code)
                base["has_prices"] = latest0 is not None
                base["name_match_candidates"] = [
                    {"code": x.code, "name": x.name} for x in name_hits
                ]

        target = base.get("suggested_import_code") or base["file_code"]
        base["import_preview"] = await self.compute_price_import_preview_stats(target, prices)
        return base

    @staticmethod
    def _to_iso_date(dt) -> str:
        if _is_blank_val(dt):
            return ""
        if hasattr(dt, "strftime"):
            try:
                return pd.Timestamp(dt).strftime("%Y-%m-%d")
            except Exception:
                try:
                    return dt.strftime("%Y-%m-%d")
                except Exception:
                    return str(dt)[:10]
        if isinstance(dt, str):
            s = dt.strip()
            if s:
                ts = pd.to_datetime(s, errors="coerce")
                if not pd.isna(ts):
                    return ts.strftime("%Y-%m-%d")
            s2 = dt.replace("-", "").replace("/", "").strip()
            if len(s2) == 8 and s2.isdigit():
                return f"{s2[:4]}-{s2[4:6]}-{s2[6:8]}"
        return str(dt)[:10]

    async def preview_multi_asset_import(self, contents: bytes, metric: str = "close") -> dict:
        """
        预览多资产导入：解析 Excel，返回资产列表及冲突信息（不含 prices，减轻体积）。
        """
        loop = asyncio.get_event_loop()
        assets_raw = await loop.run_in_executor(
            None,
            lambda: self._parse_multi_asset_excel(contents, metric),
        )
        if not assets_raw:
            return {"assets": []}
        rows = await asyncio.gather(
            *[self._enrich_multi_asset_row(item) for item in assets_raw],
        )
        result = [{k: v for k, v in row.items() if k != "prices"} for row in rows]
        return {"assets": result}

    async def analyze_multi_asset_import(self, contents: bytes, metric: str = "close") -> dict:
        """
        分析多资产 Excel：解析并返回每条资产的匹配信息 + 完整行情，供前端一步完成预览与导入。
        """
        # 诊断日志：检查 assets 集合状态
        total_in_db = await self.collection.count_documents({})
        sample = await self.collection.find_one()
        sample_code = sample.get("code") if sample else None
        logger.info(
            "[multi_import] assets 集合状态: total_docs={} sample_code={!r} collection={}",
            total_in_db, sample_code, self.collection.name,
        )
        loop = asyncio.get_event_loop()
        assets_raw = await loop.run_in_executor(
            None,
            lambda: self._parse_multi_asset_excel(contents, metric),
        )
        if not assets_raw:
            return {"assets": []}
        result = await asyncio.gather(
            *[self._enrich_multi_asset_row(item) for item in assets_raw],
        )
        return {"assets": list(result)}

    async def import_multi_asset_from_excel(
        self,
        contents: bytes,
        overwrite_name: bool = False,
        replace_existing: bool = False,
        only_missing_dates: bool = False,
        metric: str = "close",
    ) -> dict:
        """
        从多资产 Excel 批量导入资产及行情。
        - overwrite_name: 代码一致但名称不一致时是否覆盖名称
        - replace_existing: 已有行情时是否全覆盖
        - only_missing_dates: 与 replace_existing=false 联用时，仅插入库中尚不存在的交易日
        - metric: 宽表列数值映射到 close/open/high/low/amount/volume/scale
        """
        assets_raw = self._parse_multi_asset_excel(contents, metric)
        stats = {
            "total_assets": len(assets_raw),
            "assets_created": 0,
            "assets_updated": 0,
            "prices_imported": 0,
            "errors": [],
        }
        for item in assets_raw:
            try:
                existing = await self.get_asset_by_code(item["code"])
                if existing:
                    if overwrite_name and existing.name != item["name"]:
                        await self.update_asset(existing.id, {"name": item["name"]})
                        stats["assets_updated"] += 1
                else:
                    asset_type = self._infer_asset_type(item["name"], item["code"])
                    exchange = self._infer_exchange(item["code"])
                    asset = Asset(
                        code=item["code"],
                        name=item["name"],
                        asset_type=asset_type,
                        exchange=exchange,
                        is_active=True,
                    )
                    await self.create_asset(asset)
                    stats["assets_created"] += 1

                pr = await self.import_price_data(
                    asset_code=item["code"],
                    price_data_list=item["prices"],
                    replace_existing=replace_existing,
                    only_missing_dates=only_missing_dates,
                )
                stats["prices_imported"] += pr.get("inserted_count", 0) + pr.get("updated_count", 0)
                if pr.get("errors"):
                    stats["errors"].extend([f"{item['code']}: {e}" for e in pr["errors"][:3]])
            except Exception as e:
                stats["errors"].append(f"{item['code']}: {str(e)}")
        return stats

    @staticmethod
    def _infer_asset_type(name: str, code: str) -> AssetType:
        n, c = str(name), str(code).upper()
        if "债" in n or ".CS" in c:
            return AssetType.BOND
        if "质押" in n or "DR007" in c or ".IB" in c:
            return AssetType.CURRENCY
        if "商品" in n or "黄金" in n or "有色" in n or "化工" in n or "能源" in n or "贵金属" in n or "原油" in n or "豆粕" in n:
            return AssetType.COMMODITY
        if "ETF" in n or "LOF" in n or "518" in c or "159" in c or "501" in c or "160" in c or "164" in c or "161" in c:
            return AssetType.FUND
        if "指数" in n or "300" in n or ".WI" in c or "000300" in c:
            return AssetType.INDEX
        if ".SH" in c or ".SZ" in c:
            return AssetType.FUND if ("ETF" in n or "LOF" in n) else AssetType.INDEX
        return AssetType.INDEX

    @staticmethod
    def _infer_exchange(code: str) -> Optional[str]:
        c = str(code).upper()
        if ".SH" in c or c.endswith("SH"):
            return "SSE"
        if ".SZ" in c or c.endswith("SZ"):
            return "SZSE"
        if ".CS" in c:
            return "CBB"
        if ".IB" in c:
            return "IB"
        if ".WI" in c:
            return "Wind"
        return None

    async def import_single_asset_from_multi(
        self,
        code: str,
        name: str,
        prices: List[dict],
        overwrite_name: bool = False,
        replace_existing: bool = False,
        only_missing_dates: bool = False,
        import_as_code: Optional[str] = None,
        create_new_asset: bool = False,
        new_asset_code: Optional[str] = None,
        progress_id: Optional[str] = None,
        import_metric: Optional[str] = None,
    ) -> dict:
        """
        导入单个资产（用于多资产逐条导入，支持进度展示）。
        import_as_code: 若指定，行情写入该代码对应资产（用于「仅名称一致」绑定到系统已有代码）；
        此时不会在库中自动创建 import_as_code；若目标不存在则报错。
        create_new_asset + new_asset_code: 与系统「仅代码一致」但不想覆盖原名称时，新建一条资产并写入行情。
        """
        code = (code or "").strip()
        name = (name or "").strip()
        if not code:
            raise ValueError("资产代码不能为空，无法导入行情")
        if not name:
            raise ValueError("资产名称不能为空，无法导入行情")

        if create_new_asset:
            nc = (new_asset_code or "").strip()
            if not nc:
                raise ValueError("选择新建资产时请填写 new_asset_code")
            if await self.get_asset_by_code(nc):
                raise ValueError(f"新资产代码已存在，无法新建: {nc}")
            asset_type = self._infer_asset_type(name, code)
            exchange = self._infer_exchange(nc)
            asset = Asset(
                code=nc,
                name=(name or "").strip() or nc,
                asset_type=asset_type,
                exchange=exchange,
                is_active=True,
            )
            await self.create_asset(asset)
            pr = await self.import_price_data(
                asset_code=nc,
                price_data_list=prices,
                replace_existing=replace_existing,
                only_missing_dates=only_missing_dates,
                progress_id=progress_id,
                progress_asset_name=name,
                progress_import_metric=import_metric,
            )
            return {
                "code": code,
                "name": name,
                "import_as_code": nc,
                "created_new_code": nc,
                "inserted": pr.get("inserted_count", 0),
                "updated": pr.get("updated_count", 0),
                "skipped": pr.get("skipped_count", 0),
                "skipped_non_trade_days": pr.get("skipped_non_trade_days", 0),
                "errors": pr.get("errors", []),
            }

        target = (import_as_code or "").strip() or code
        existing = await self.get_asset_by_code(target)
        if existing:
            if overwrite_name and (existing.name or "").strip() != (name or "").strip():
                await self.update_asset(existing.id, {"name": name})
        else:
            if import_as_code:
                raise ValueError(f"目标资产代码不存在，无法导入行情: {target}")
            asset_type = self._infer_asset_type(name, code)
            exchange = self._infer_exchange(code)
            asset = Asset(
                code=code,
                name=name,
                asset_type=asset_type,
                exchange=exchange,
                is_active=True,
            )
            await self.create_asset(asset)

        pr = await self.import_price_data(
            asset_code=target,
            price_data_list=prices,
            replace_existing=replace_existing,
            only_missing_dates=only_missing_dates,
            progress_id=progress_id,
            progress_asset_name=name,
            progress_import_metric=import_metric,
        )
        return {
            "code": code,
            "name": name,
            "import_as_code": target,
            "inserted": pr.get("inserted_count", 0),
            "updated": pr.get("updated_count", 0),
            "skipped": pr.get("skipped_count", 0),
            "skipped_non_trade_days": pr.get("skipped_non_trade_days", 0),
            "errors": pr.get("errors", []),
        }
