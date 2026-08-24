"""
资产服务层
"""
import asyncio
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from bson import ObjectId
from loguru import logger
from app.config.database import Database
from app.models.asset import Asset, AssetPrice, AssetType
from app.services.excel_layout import ExcelLayoutMixin
from app.services.price_importer import PriceImporterMixin, _is_blank_val
import pandas as pd

# 常见别名 → 系统中的资产代码（便于「沪深300」等与库内简称不一致时的检索）
_KEYWORD_CODE_HINTS = (
    ("沪深300", ["000300.SH", "SZ159919"]),
    ("hs300", ["000300.SH", "SZ159919"]),
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

class AssetService(ExcelLayoutMixin, PriceImporterMixin):
    """资产服务

    Excel 宽表布局推断/解析见 ExcelLayoutMixin（excel_layout.py）；
    行情导入引擎（写入/预览/缺口）见 PriceImporterMixin（price_importer.py）。
    """
    
    def __init__(self):
        self._db = None
        self._collection = None
        self._price_collection = None
        self._price_repo = None

    @property
    def db(self):
        if self._db is None:
            self._db = Database.get_database()
        return self._db

    @property
    def collection(self):
        if self._collection is None:
            from app.config.collections import COL_ASSETS
            self._collection = self.db[COL_ASSETS]
        return self._collection

    @property
    def price_collection(self):
        if self._price_collection is None:
            from app.config.collections import COL_ASSET_PRICES
            self._price_collection = self.db[COL_ASSET_PRICES]
        return self._price_collection

    @property
    def price_repo(self):
        """行情读收口仓储（读端统一经此，写端仅限 PriceImporterMixin）."""
        if self._price_repo is None:
            from app.data.price_repository import PriceRepository
            self._price_repo = PriceRepository(db=self.db)
        return self._price_repo
    
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

    async def list_assets_raw(
        self,
        base_filter: Dict[str, Any],
        skip: int = 0,
        limit: int = 500,
        code: Optional[str] = None,
        name: Optional[str] = None,
    ) -> List[Asset]:
        """使用原始 MongoDB 查询条件查询资产列表（支持新维度字段过滤）。

        Args:
            base_filter: MongoDB 查询条件 dict（直接传给 find）
            skip: 跳过记录数
            limit: 返回记录数
            code: 资产代码模糊过滤
            name: 资产名称模糊过滤
        """
        query = dict(base_filter)
        code_str = (code or "").strip()
        name_str = (name or "").strip()
        if code_str:
            query["code"] = {"$regex": re.escape(code_str), "$options": "i"}
        if name_str:
            query["name"] = {"$regex": re.escape(name_str), "$options": "i"}
        cursor = self.collection.find(query).skip(skip).limit(limit)
        assets = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            assets.append(Asset(**doc))
        return assets

    async def count_assets_raw(
        self,
        base_filter: Dict[str, Any],
        code: Optional[str] = None,
        name: Optional[str] = None,
    ) -> int:
        """使用原始 MongoDB 查询条件统计资产总数。"""
        query = dict(base_filter)
        code_str = (code or "").strip()
        name_str = (name or "").strip()
        if code_str:
            query["code"] = {"$regex": re.escape(code_str), "$options": "i"}
        if name_str:
            query["name"] = {"$regex": re.escape(name_str), "$options": "i"}
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
        获取资产价格数据（读端委托 PriceRepository）
        
        Args:
            asset_code: 资产代码
            start_date: 开始日期
            end_date: 结束日期
        """
        return await self.price_repo.get_price_docs(asset_code, start_date, end_date)

    async def get_latest_price_date(self, asset_code: str) -> Optional[str]:
        """
        获取资产的最新价格数据日期（读端委托 PriceRepository）
        
        Returns:
            最新日期字符串（YYYY-MM-DD），如果没有数据则返回 None
        """
        return await self.price_repo.get_latest_price_date(asset_code)
    
    async def get_latest_price_dates(self, asset_codes: List[str]) -> Dict[str, Optional[str]]:
        """
        批量获取多个资产的最新价格数据日期（读端委托 PriceRepository）
        
        Returns:
            字典：{asset_code: latest_date 或 None}
        """
        return await self.price_repo.get_latest_price_dates(asset_codes)
    
    async def get_price_dataframe(
        self,
        asset_codes: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        获取多个资产的价格DataFrame（读端委托 PriceRepository）
        
        Returns:
            DataFrame with columns as asset_codes and index as dates
        """
        return await self.price_repo.get_price_dataframe(asset_codes, start_date, end_date)

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
                # 空值sanitize：pandas 将空单元格读为 NaN，直接写入 MongoDB
                # 会导致列表页 Asset(**doc) 校验失败（500），统一转 None
                item = {k: (None if _is_blank_val(v) else v) for k, v in item.items()}
                code = item.get('code')
                if not code:
                    raise ValueError("资产代码不能为空")
                
                # 转换资产类型字符串为枚举名(如果需要)
                # MongoDB 存储的是字符串值，Asset 类初始化会自动处理
                
                # 检查资产是否已存在
                existing = await self.get_asset_by_code(code)
                
                if existing:
                    # 资产代码为业务主键：命中即整行覆盖，导入文件是唯一事实来源。
                    # 先经 Asset 模型校验（枚举/三维度 backfill），再 replace_one：
                    # Excel 中缺失的列回落为模型默认值（None），不残留旧值；
                    # is_active 强制 True（重新导入即复活/保持启用）；
                    # created_at 保留首次创建时间，仅刷新 updated_at
                    asset = Asset(**item)
                    new_doc = asset.dict(by_alias=True, exclude={'id'})
                    new_doc['is_active'] = True
                    new_doc['created_at'] = existing.created_at
                    new_doc['updated_at'] = datetime.now()
                    await self.collection.replace_one(
                        {"_id": ObjectId(existing.id)}, new_doc
                    )
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
