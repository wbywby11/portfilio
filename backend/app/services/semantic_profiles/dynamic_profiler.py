"""
动态画像计算引擎 - 从MongoDB实时计算数据统计

职责：
1. 连接MongoDB集合实时计算记录数、字段覆盖率、数值/分类分布、日期范围、增量趋势等。
2. 提供基于TTL的内存缓存，行情域TTL=1小时，其他域TTL=24小时。
3. 当MongoDB未连接或集合为空时优雅降级，不抛异常、不影响静态画像。
"""
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

from loguru import logger

from .models import DynamicStats


class DynamicProfiler:
    """动态画像计算器

    从MongoDB集合中实时计算统计数据，与静态画像合并。
    具备缓存机制避免频繁计算。
    """

    _instance: Optional["DynamicProfiler"] = None
    _cache: Dict[str, Tuple[DynamicStats, float]] = {}
    _date_field_cache: Dict[str, Optional[str]] = {}  # 集合名 -> 探测到的日期字段

    # 缓存TTL（秒）
    CACHE_TTL = {
        "market": 3600,        # 行情域：1小时
        "default": 86400,      # 其他域：24小时
    }

    # 单次聚合操作超时（毫秒）
    AGGREGATE_TIMEOUT_MS = 5000

    # 抽样大小
    SAMPLE_SIZE = 500

    # 域名到表前缀的映射（用于推断TTL）
    DOMAIN_PREFIX_MAP = {
        "dwd_mkt_": "market",
        "dwd_ast_": "asset",
        "dwd_ptl_": "product",
        "dwd_val_": "valuation",
        "dwd_trn_": "transaction",
        "dwd_cust_": "customer",
        "dwd_rsk_": "risk",
        "dwd_isr_": "subject",
        "dwd_sale_": "seller",
    }

    # 常见分类字段（静态种子，仅作为补充参考）
    CATEGORICAL_FIELDS = [
        "AST_TYPE", "AST_SUB_TYPE", "PORT_TYPE", "STATUS",
        "RATING", "MARKET", "DIRECTION", "SETTLE_TYPE",
        "CCY", "EXCH_CD", "TRD_TYP",
    ]

    # 常见日期字段候选（按优先级排列，自动探测首个存在的字段）
    DATE_FIELD_CANDIDATES = [
        "BIZ_DT", "date", "DATE", "trade_date", "TRADE_DATE",
        "trade_dt", "TRADE_DT", "biz_date", "BIZ_DATE",
        "created_at", "CREATED_AT", "update_time", "UPDATE_TIME",
    ]

    # 动态分类字段推断：基数阈值（不同值数量 < 此值视为分类字段）
    CATEGORICAL_CARDINALITY_THRESHOLD = 50
    # 动态分类字段推断：最大选取数量
    CATEGORICAL_MAX_FIELDS = 8

    @classmethod
    def get_instance(cls) -> "DynamicProfiler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ----------------- 缓存与域识别 -----------------

    def _get_domain(self, collection_name: str) -> str:
        """根据集合名推断所属域"""
        for prefix, domain in self.DOMAIN_PREFIX_MAP.items():
            if collection_name.startswith(prefix):
                return domain
        return "default"

    def _get_ttl(self, collection_name: str) -> int:
        """获取缓存TTL（秒）"""
        domain = self._get_domain(collection_name)
        return self.CACHE_TTL.get(domain, self.CACHE_TTL["default"])

    def _is_cache_valid(self, collection_name: str) -> bool:
        """检查缓存是否有效"""
        if collection_name not in self._cache:
            return False
        _, cached_time = self._cache[collection_name]
        ttl = self._get_ttl(collection_name)
        return (time.time() - cached_time) < ttl

    def invalidate_cache(self, collection_name: Optional[str] = None) -> None:
        """手动失效缓存。collection_name为None时清空全部。"""
        if collection_name:
            self._cache.pop(collection_name, None)
            self._date_field_cache.pop(collection_name, None)
            logger.info("动态画像缓存已失效: {}", collection_name)
        else:
            self._cache.clear()
            self._date_field_cache.clear()
            logger.info("动态画像缓存已全部清空")

    # ----------------- 入口方法 -----------------

    async def compute_stats(self, collection_name: str) -> Optional[DynamicStats]:
        """计算集合的动态统计（带缓存）"""
        # 命中缓存
        if self._is_cache_valid(collection_name):
            return self._cache[collection_name][0]

        try:
            stats = await self._do_compute(collection_name)
            if stats is not None:
                self._cache[collection_name] = (stats, time.time())
            return stats
        except Exception as e:  # noqa: BLE001
            logger.warning("动态画像计算失败 [{}]: {}", collection_name, e)
            # 优雅降级：返回默认对象
            return DynamicStats(
                table_name=collection_name,
                computed_at=datetime.now().isoformat(),
            )

    async def _do_compute(self, collection_name: str) -> Optional[DynamicStats]:
        """执行实际的统计计算"""
        from app.config.database import Database

        db = Database.get_database()
        if db is None:
            logger.warning("MongoDB未连接，跳过动态画像计算 [{}]", collection_name)
            return DynamicStats(
                table_name=collection_name,
                computed_at=datetime.now().isoformat(),
            )

        collection = db[collection_name]

        # 1. 总记录数
        try:
            record_count = await collection.count_documents({}, maxTimeMS=self.AGGREGATE_TIMEOUT_MS)
        except Exception as e:  # noqa: BLE001
            logger.warning("count_documents失败 [{}]: {}", collection_name, e)
            return DynamicStats(
                table_name=collection_name,
                computed_at=datetime.now().isoformat(),
            )

        if record_count == 0:
            logger.debug("集合为空，返回默认动态画像 [{}]", collection_name)
            return DynamicStats(
                table_name=collection_name,
                record_count=0,
                computed_at=datetime.now().isoformat(),
            )

        # 2. 抽样（一次拿出，后续覆盖率/数值统计共享）
        samples = await self._sample_documents(collection, collection_name)

        # 3. 字段覆盖率
        field_coverage = self._compute_field_coverage(samples)

        # 4. 数值字段统计（基于抽样收集到的数值字段做MongoDB聚合）
        numeric_stats = await self._compute_numeric_stats(collection, samples, collection_name)

        # 5. 日期范围
        date_range = await self._compute_date_range(collection, collection_name)

        # 6. 最近7天增量趋势
        recent_trend = await self._compute_recent_trend(collection, collection_name)

        # 7. 分类字段Top10分布
        categorical_distribution = await self._compute_categorical_dist(
            collection, samples, collection_name
        )

        # 8. 异常值比例（基于简单规则：数值字段>3σ占比的均值）
        anomaly_ratio = self._compute_anomaly_ratio(samples, numeric_stats)

        return DynamicStats(
            table_name=collection_name,
            record_count=record_count,
            field_coverage=field_coverage,
            numeric_stats=numeric_stats,
            categorical_distribution=categorical_distribution,
            date_range=date_range,
            recent_trend=recent_trend,
            anomaly_ratio=anomaly_ratio,
            computed_at=datetime.now().isoformat(),
        )

    # ----------------- 子统计计算 -----------------

    async def _sample_documents(self, collection, collection_name: str) -> list:
        """使用 $sample 抽样最多SAMPLE_SIZE条文档"""
        try:
            pipeline = [{"$sample": {"size": self.SAMPLE_SIZE}}]
            cursor = collection.aggregate(pipeline, maxTimeMS=self.AGGREGATE_TIMEOUT_MS)
            samples = []
            async for doc in cursor:
                samples.append(doc)
            return samples
        except Exception as e:  # noqa: BLE001
            logger.warning("抽样失败 [{}]: {}", collection_name, e)
            return []

    def _compute_field_coverage(self, samples: list) -> dict:
        """基于抽样计算字段非空覆盖率"""
        if not samples:
            return {}

        all_fields: set = set()
        for doc in samples:
            all_fields.update(doc.keys())
        all_fields.discard("_id")

        total = len(samples)
        coverage: dict = {}
        for field in all_fields:
            non_null = 0
            for doc in samples:
                v = doc.get(field)
                if v is None:
                    continue
                if isinstance(v, str) and v == "":
                    continue
                non_null += 1
            coverage[field] = round(non_null / total, 3)
        return coverage

    async def _compute_numeric_stats(
        self, collection, samples: list, collection_name: str
    ) -> dict:
        """计算数值字段的 min/max/mean/median（中位数基于抽样近似）"""
        if not samples:
            return {}

        # 从抽样中识别数值字段（排除布尔型）
        numeric_fields: set = set()
        for doc in samples:
            for k, v in doc.items():
                if k == "_id":
                    continue
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)):
                    numeric_fields.add(k)

        if not numeric_fields:
            return {}

        # 限制最多统计20个数值字段，避免聚合过重
        numeric_fields_list = list(numeric_fields)[:20]

        group_stage: dict = {"_id": None}
        for f in numeric_fields_list:
            group_stage[f"{f}__min"] = {"$min": f"${f}"}
            group_stage[f"{f}__max"] = {"$max": f"${f}"}
            group_stage[f"{f}__avg"] = {"$avg": f"${f}"}

        stats: dict = {}
        try:
            pipeline = [{"$group": group_stage}]
            cursor = collection.aggregate(pipeline, maxTimeMS=self.AGGREGATE_TIMEOUT_MS)
            async for result in cursor:
                for f in numeric_fields_list:
                    fmin = result.get(f"{f}__min")
                    fmax = result.get(f"{f}__max")
                    favg = result.get(f"{f}__avg")
                    if fmin is None and fmax is None and favg is None:
                        continue
                    # 中位数：基于抽样近似（避免全表扫描）
                    sample_vals = sorted(
                        v for doc in samples
                        for v in [doc.get(f)]
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                    )
                    median = None
                    if sample_vals:
                        n = len(sample_vals)
                        mid = n // 2
                        median = (
                            sample_vals[mid]
                            if n % 2 == 1
                            else (sample_vals[mid - 1] + sample_vals[mid]) / 2
                        )
                    stats[f] = {
                        "min": fmin,
                        "max": fmax,
                        "mean": round(favg, 6) if isinstance(favg, (int, float)) else favg,
                        "median": median,
                    }
                break
        except Exception as e:  # noqa: BLE001
            logger.warning("数值统计失败 [{}]: {}", collection_name, e)

        return stats

    async def _discover_date_field(self, collection, collection_name: str) -> Optional[str]:
        """自动探测集合中存在的日期字段，按候选列表优先级返回首个有数据的字段名（带缓存）"""
        if collection_name in self._date_field_cache:
            return self._date_field_cache[collection_name]
        try:
            for candidate in self.DATE_FIELD_CANDIDATES:
                pipeline = [
                    {"$match": {candidate: {"$exists": True, "$ne": None}}},
                    {"$limit": 1},
                ]
                cursor = collection.aggregate(pipeline, maxTimeMS=3000)
                async for _ in cursor:
                    logger.debug("探测到日期字段 [{}] -> {}", collection_name, candidate)
                    self._date_field_cache[collection_name] = candidate
                    return candidate
        except Exception as e:  # noqa: BLE001
            logger.debug("日期字段探测异常 [{}]: {}", collection_name, e)
        self._date_field_cache[collection_name] = None
        return None

    async def _compute_date_range(self, collection, collection_name: str) -> Optional[dict]:
        """计算日期字段的范围（自动探测字段名）"""
        date_field = await self._discover_date_field(collection, collection_name)
        if not date_field:
            return None
        try:
            pipeline = [
                {"$match": {date_field: {"$exists": True, "$ne": None}}},
                {"$group": {"_id": None, "min": {"$min": f"${date_field}"}, "max": {"$max": f"${date_field}"}}},
            ]
            cursor = collection.aggregate(pipeline, maxTimeMS=self.AGGREGATE_TIMEOUT_MS)
            async for result in cursor:
                return {
                    "min": str(result.get("min")),
                    "max": str(result.get("max")),
                    "field": date_field,
                }
        except Exception as e:  # noqa: BLE001
            logger.debug("日期范围计算失败 [{}]: {}", collection_name, e)
        return None

    async def _compute_recent_trend(self, collection, collection_name: str) -> Optional[dict]:
        """计算最近7天每天的新增记录数（按探测到的日期字段分组）"""
        date_field = await self._discover_date_field(collection, collection_name)
        if not date_field:
            return None
        try:
            pipeline = [
                {"$match": {date_field: {"$exists": True, "$ne": None}}},
                {"$sort": {date_field: -1}},
                {"$limit": 10000},
                {"$group": {"_id": f"${date_field}", "count": {"$sum": 1}}},
                {"$sort": {"_id": -1}},
                {"$limit": 7},
            ]
            cursor = collection.aggregate(pipeline, maxTimeMS=self.AGGREGATE_TIMEOUT_MS)
            trend: dict = {}
            async for result in cursor:
                key = result.get("_id")
                if key is None:
                    continue
                trend[str(key)] = result.get("count", 0)
            return trend if trend else None
        except Exception as e:  # noqa: BLE001
            logger.debug("最近趋势计算失败 [{}]: {}", collection_name, e)
            return None

    async def _compute_categorical_dist(
        self, collection, samples: list, collection_name: str
    ) -> dict:
        """计算关键分类字段的Top10值及计数

        策略：
        1. 优先匹配静态白名单中的字段（ZY域等已知的分类字段）
        2. 动态推断：从抽样中识别低基数（cardinality < 阈值）字符串字段
        3. 合并去重后使用 $facet 一次性聚合
        """
        if not samples:
            return {}

        sample_fields = set()
        for doc in samples:
            sample_fields.update(doc.keys())

        # 1. 静态白名单命中
        target_fields = [f for f in self.CATEGORICAL_FIELDS if f in sample_fields]
        static_set = set(target_fields)

        # 2. 动态推断低基数字符串字段
        dynamic_candidates: dict[str, int] = {}
        for field in sample_fields:
            if field in static_set or field == "_id":
                continue
            # 只考虑字符串型字段
            str_vals = set()
            is_string_field = False
            for doc in samples:
                v = doc.get(field)
                if isinstance(v, str):
                    is_string_field = True
                    str_vals.add(v)
                    if len(str_vals) > self.CATEGORICAL_CARDINALITY_THRESHOLD:
                        break
            if is_string_field and 0 < len(str_vals) <= self.CATEGORICAL_CARDINALITY_THRESHOLD:
                dynamic_candidates[field] = len(str_vals)

        # 按基数升序排列，优先选取低基数字段
        sorted_dynamic = sorted(dynamic_candidates.items(), key=lambda x: x[1])
        remaining_slots = self.CATEGORICAL_MAX_FIELDS - len(target_fields)
        for field, _card in sorted_dynamic[:max(remaining_slots, 3)]:
            target_fields.append(field)

        if not target_fields:
            return {}

        facet: dict = {}
        for f in target_fields:
            facet[f] = [
                {"$match": {f: {"$exists": True, "$ne": None}}},
                {"$group": {"_id": f"${f}", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10},
            ]

        distribution: dict = {}
        try:
            pipeline = [{"$facet": facet}]
            cursor = collection.aggregate(pipeline, maxTimeMS=self.AGGREGATE_TIMEOUT_MS)
            async for result in cursor:
                for field, buckets in result.items():
                    values: dict = {}
                    for bucket in buckets:
                        key = bucket.get("_id")
                        if key is None or key == "":
                            continue
                        values[str(key)] = bucket.get("count", 0)
                    if values:
                        distribution[field] = values
                break
        except Exception as e:  # noqa: BLE001
            logger.debug("分类分布计算失败 [{}]: {}", collection_name, e)

        return distribution

    def _compute_anomaly_ratio(self, samples: list, numeric_stats: dict) -> Optional[float]:
        """异常值比例：基于标准差的 3σ 原则

        对每个数值字段，计算样本的标准差(std)，
        然后统计 |x - mean| > 3 * std 的占比，最后对所有字段取均值。
        若字段内所有值相同（std=0），则跳过该字段。
        """
        if not samples or not numeric_stats:
            return None

        ratios = []
        for field, st in numeric_stats.items():
            mean = st.get("mean")
            if not isinstance(mean, (int, float)):
                continue
            # 收集该字段的所有有效样本值
            vals = [
                doc.get(field) for doc in samples
                if isinstance(doc.get(field), (int, float)) and not isinstance(doc.get(field), bool)
            ]
            if len(vals) < 3:
                continue
            # 计算标准差
            variance = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = variance ** 0.5
            if std < 1e-12:
                # 标准差为0，所有值相同，无异常
                continue
            # 3σ 异常检测
            outlier = sum(1 for v in vals if abs(v - mean) > 3 * std)
            total = len(vals)
            if total > 0:
                ratios.append(outlier / total)

        if not ratios:
            return None
        return round(sum(ratios) / len(ratios), 4)
