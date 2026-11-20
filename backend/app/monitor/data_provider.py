# -*- coding: utf-8 -*-
"""
大类资产配置监测系统 - 数据提供者

本模块提供从 MongoDB 读取数据的异步接口，替代原来的 Excel data_loader。
核心功能：
- 从 MongoDB 读取资产价格数据
- 从 MongoDB 读取汇率数据
- 从 MongoDB 读取交易日历
- 全量加载（无资产子集）时列名为监控标准中文名；策略实例子集加载时列名与 Mongo asset_code、模型选择资产一致（原样）
"""

from typing import Any, Dict, List, Optional
import pandas as pd
from datetime import datetime
from loguru import logger

from app.config.database import Database
from app.monitor import config
from app.monitor.mongo_asset_codes import canonical_price_code, stored_price_codes_for_monitor
from app.monitor.time_norm import normalize_calendar_timestamp, normalize_datetime_index


def _prepare_prices_for_pivot(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    pivot 要求 (date, asset_code) 唯一；Mongo 中若存在重复文档会触发
    Index contains duplicate entries, cannot reshape。
    统一日期为 Timestamp 后按 (date, asset_code) 去重，保留最后一条。
    """
    if df_raw.empty or "date" not in df_raw.columns or "asset_code" not in df_raw.columns:
        return df_raw
    out = df_raw.copy()
    out["date"] = pd.to_datetime(out["date"])
    n0 = len(out)
    out = out.sort_values(["asset_code", "date"]).drop_duplicates(
        subset=["date", "asset_code"], keep="last"
    )
    dropped = n0 - len(out)
    if dropped:
        logger.warning(
            "asset_prices 存在 {} 条重复 (date, asset_code)，已去重后再透视",
            dropped,
        )
    return out


def _dedupe_asset_tokens(tokens: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for x in tokens:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _is_full_legacy_chinese_universe(asset_columns: Optional[List[str]]) -> bool:
    """
    Legacy 监控（monitor_id=default / tracker 未绑定策略模型）下 asset_list 为 config.ASSET_LIST 中文名。
    Mongo asset_prices.asset_code 存的是标准码（及可选后缀），不能用中文名做 $in 查询，须走全量码查询路径。
    """
    if not asset_columns:
        return False
    cols = _dedupe_asset_tokens(list(asset_columns))
    if len(cols) != len(config.ASSET_LIST):
        return False
    return set(cols) == set(config.ASSET_LIST)


def _prices_pivot_from_records(
    records: list,
    column_order: Optional[List[str]],
) -> pd.DataFrame:
    """Mongo 行情 -> 行为日期。column_order 为 None 时列为标准中文名；否则列名与库内 asset_code 原样一致。"""
    if not records:
        cols = list(config.ASSET_LIST) if column_order is None else list(column_order)
        return pd.DataFrame(columns=cols)
    df_raw = _prepare_prices_for_pivot(pd.DataFrame(records))
    df_pivot = df_raw.pivot(index="date", columns="asset_code", values="close")
    use_canonical = column_order is None
    if use_canonical:
        df_pivot = df_pivot.rename(columns=lambda c: canonical_price_code(str(c)))
        df_pivot.columns = [
            config.ASSET_CODE_TO_NAME.get(str(code).strip(), str(code).strip())
            for code in df_pivot.columns
        ]
        for asset in config.ASSET_LIST:
            if asset not in df_pivot.columns:
                df_pivot[asset] = None
        df_pivot = df_pivot[config.ASSET_LIST]
    else:
        df_pivot.columns = [str(c).strip() for c in df_pivot.columns]
        for asset in column_order:
            if asset not in df_pivot.columns:
                df_pivot[asset] = None
        df_pivot = df_pivot[list(column_order)]
    df_pivot.index = normalize_datetime_index(pd.to_datetime(df_pivot.index))
    df_pivot.index.name = "date"
    df_pivot = df_pivot.sort_index()
    if df_pivot.index.has_duplicates:
        df_pivot = df_pivot[~df_pivot.index.duplicated(keep="last")]
    return df_pivot


def _normalize_fx_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """与 portfolio_tracker 约定一致：列 HKD/USD/EUR/JPY/CNH，索引为日历日。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["HKD", "USD", "EUR", "JPY", "CNH"])
    out = df.copy()
    out.index = normalize_datetime_index(pd.to_datetime(out.index))
    out.index.name = "date"
    for col in ("HKD", "USD", "EUR", "JPY"):
        if col not in out.columns:
            out[col] = 1.0
    out["CNH"] = 1.0
    out = out[["HKD", "USD", "EUR", "JPY", "CNH"]]
    if out.index.has_duplicates:
        out = out[~out.index.duplicated(keep="last")]
    return out.sort_index()


def _fx_from_xlsx(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """与 FxService 一致：Mongo 无数据时使用 portfilio-end/data/fx.xlsx。"""
    try:
        from app.services.fx_service import FxService
    except ImportError:
        return pd.DataFrame(columns=["HKD", "USD", "EUR", "JPY", "CNH"])
    raw = FxService._load_from_xlsx(start_date=start_date, end_date=end_date)
    return _normalize_fx_dataframe(raw)


class MongoDataProvider:
    """
    MongoDB 数据提供者
    
    使用 Motor 异步驱动从 MongoDB 读取数据，
    返回格式与原 ExcelDataLoader 完全一致。
    """
    
    def __init__(self):
        """初始化数据提供者"""
        # 缓存数据，避免重复查询
        self._prices_cache: Optional[pd.DataFrame] = None
        self._fx_cache: Optional[pd.DataFrame] = None
        self._trade_dates_cache: Optional[List[pd.Timestamp]] = None
    
    def _get_db(self):
        """获取数据库实例"""
        return Database.get_database()
    
    # =========================================================================
    # 价格数据
    # =========================================================================
    
    async def load_prices(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        asset_columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        加载资产价格数据
        
        从 MongoDB asset_prices 集合查询数据，构建 DataFrame。
        
        asset_columns 为 None：查询标准 12 类（含 MONGO_ASSET_CODE_SUFFIX），列为监控中文名。
        传入子集时：按原样字符串查询 Mongo asset_code，列名与策略「选择资产」一致，不做映射。
        
        Parameters
        ----------
        start_date : str, optional
            起始日期，格式 'YYYY-MM-DD'
        end_date : str, optional
            结束日期，格式 'YYYY-MM-DD'
        asset_columns : list of str, optional
            与库内 asset_code 一致的标识列表；None 表示 12 类全量
            
        Returns
        -------
        pd.DataFrame
            索引为日期；列名为中文名（全量模式）或与 asset_columns 原样一致（子集模式）
        """
        db = self._get_db()
        collection = db[config.MONGO_COLLECTIONS['prices']]
        
        # 构建查询条件（asset_prices.date 为 YYYY-MM-DD 字符串，直接用字符串比较）
        query: Dict = {}
        if start_date or end_date:
            query['date'] = {}
            if start_date:
                query['date']['$gte'] = start_date
            if end_date:
                query['date']['$lte'] = end_date
        
        pivot_columns: Optional[List[str]] = asset_columns
        if asset_columns is None or _is_full_legacy_chinese_universe(asset_columns):
            asset_codes = stored_price_codes_for_monitor()
            pivot_columns = None
        else:
            asset_codes = _dedupe_asset_tokens(list(asset_columns))
        if not asset_codes:
            cols = list(config.ASSET_LIST) if pivot_columns is None else _dedupe_asset_tokens(
                list(asset_columns or [])
            )
            return pd.DataFrame(columns=cols)
        query['asset_code'] = {'$in': asset_codes}
        
        # 只取 pivot 需要的三列：全历史矩阵下省略 _id/open/high/low/volume 等字段可显著减小传输量
        cursor = collection.find(
            query, {'_id': 0, 'asset_code': 1, 'date': 1, 'close': 1}
        ).sort('date', 1)
        records = await cursor.to_list(length=None)
        return _prices_pivot_from_records(records, pivot_columns)
    
    async def load_prices_sync_format(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        asset_columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        同步方式加载价格数据（供非异步场景使用的兼容接口）
        实际调用异步方法
        """
        return await self.load_prices(start_date, end_date, asset_columns=asset_columns)
    
    # =========================================================================
    # 汇率数据
    # =========================================================================
    
    async def load_fx(self, start_date: Optional[str] = None,
                      end_date: Optional[str] = None) -> pd.DataFrame:
        """
        加载汇率数据
        
        优先 MongoDB `fx_rates`；无数据时回退 `data/fx.xlsx`（与 FxService 一致）。
        
        Parameters
        ----------
        start_date : str, optional
            起始日期，格式 'YYYY-MM-DD'
        end_date : str, optional
            结束日期，格式 'YYYY-MM-DD'
            
        Returns
        -------
        pd.DataFrame
            索引为日期(pd.Timestamp)，列为 HKD, USD, EUR, JPY, CNH
        """
        db = self._get_db()
        collection = db[config.MONGO_COLLECTIONS['fx']]
        
        # 构建查询条件（fx_rates.date 为 YYYY-MM-DD 字符串，直接用字符串比较）
        query = {}
        if start_date or end_date:
            query['date'] = {}
            if start_date:
                query['date']['$gte'] = start_date
            if end_date:
                query['date']['$lte'] = end_date
        
        # 查询数据
        cursor = collection.find(query).sort('date', 1)
        records = await cursor.to_list(length=None)
        
        if not records:
            df = _fx_from_xlsx(start_date=start_date, end_date=end_date)
            if not df.empty:
                logger.info(
                    "Mongo fx_rates 为空，已从 data/fx.xlsx 加载 {} 行汇率",
                    len(df),
                )
            return df
        
        # 转换为 DataFrame
        df = pd.DataFrame(records)
        
        # 设置日期索引
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df.index.name = 'date'
        
        # 确保包含必需的汇率列
        required_columns = ['HKD', 'USD', 'EUR', 'JPY']
        for col in required_columns:
            if col not in df.columns:
                df[col] = 1.0
        
        # CNH 始终为 1.0
        df['CNH'] = 1.0
        
        # 只保留需要的列
        df = df[['HKD', 'USD', 'EUR', 'JPY', 'CNH']]
        
        return _normalize_fx_dataframe(df)
    
    # =========================================================================
    # 交易日历
    # =========================================================================
    
    async def load_trade_dates(self) -> List[pd.Timestamp]:
        """
        加载交易日历（MongoDB trade_dates 集合，唯一来源）

        Returns
        -------
        List[pd.Timestamp]
            排序后的交易日列表；集合为空时返回空列表
        """
        db = self._get_db()
        collection = db[config.MONGO_COLLECTIONS['trade_dates']]

        cursor = collection.find({}).sort('date', 1)
        records = await cursor.to_list(length=None)

        if not records:
            logger.warning("Mongo trade_dates 集合为空，交易日历不可用")
            return []

        # 提取日期并统一为日历日
        dates = [normalize_calendar_timestamp(r['date']) for r in records]

        return sorted(set(dates))

    async def load_asset_price_dates(self) -> List[str]:
        """
        加载资产行情日历（asset_prices 全资产日期并集，YYYY-MM-DD 升序去重）

        系统级日历参考（前瞻型工具、数据QA），不依赖 Mongo trade_dates 集合
        （该集合仅研究员策略 sharpe_18/hybrid_12 使用）。无行情数据时返回空列表。

        Returns
        -------
        List[str]
            YYYY-MM-DD 字符串列表（升序去重）
        """
        db = self._get_db()
        collection = db[config.MONGO_COLLECTIONS['prices']]
        raw = await collection.distinct('date')
        out: set = set()
        for dt in raw or []:
            if dt is None:
                continue
            try:
                out.add(normalize_calendar_timestamp(dt).strftime('%Y-%m-%d'))
            except (ValueError, TypeError):
                continue
        return sorted(out)
    
    # =========================================================================
    # 辅助方法
    # =========================================================================
    
    async def get_latest_date(self) -> pd.Timestamp:
        """
        获取价格数据中的最新日期
        
        Returns
        -------
        pd.Timestamp
            最新日期
        """
        db = self._get_db()
        collection = db[config.MONGO_COLLECTIONS['prices']]
        
        # 查询最新日期
        cursor = collection.find({}).sort('date', -1).limit(1)
        records = await cursor.to_list(length=1)
        
        if records:
            return pd.Timestamp(records[0]['date'])
        
        return pd.Timestamp.now()
    
    async def validate_data(self) -> Dict[str, any]:
        """
        数据校验
        
        检查内容：
        - 必需的资产列是否完整
        - 数据起止日期
        - 数据行数
        
        Returns
        -------
        dict
            校验结果
        """
        result = {
            'is_valid': True,
            'missing_assets': [],
            'prices_info': {},
            'fx_info': {},
            'trade_dates_info': {},
        }
        
        # 检查价格数据
        prices = await self.load_prices()
        if not prices.empty:
            result['prices_info'] = {
                'start_date': prices.index.min().strftime('%Y-%m-%d'),
                'end_date': prices.index.max().strftime('%Y-%m-%d'),
                'row_count': len(prices),
                'columns': list(prices.columns),
            }
            
            # 检查缺失的资产
            for asset in config.ASSET_LIST:
                if asset not in prices.columns or prices[asset].isna().all():
                    result['missing_assets'].append(asset)
                    result['is_valid'] = False
        else:
            result['is_valid'] = False
            result['missing_assets'] = config.ASSET_LIST.copy()
        
        # 检查汇率数据
        fx = await self.load_fx()
        if not fx.empty:
            result['fx_info'] = {
                'start_date': fx.index.min().strftime('%Y-%m-%d'),
                'end_date': fx.index.max().strftime('%Y-%m-%d'),
                'row_count': len(fx),
                'columns': list(fx.columns),
            }
        
        # 检查交易日历
        trade_dates = await self.load_trade_dates()
        if trade_dates:
            result['trade_dates_info'] = {
                'start_date': trade_dates[0].strftime('%Y-%m-%d'),
                'end_date': trade_dates[-1].strftime('%Y-%m-%d'),
                'count': len(trade_dates),
            }
        
        return result
    
    def clear_cache(self):
        """清除缓存数据"""
        self._prices_cache = None
        self._fx_cache = None
        self._trade_dates_cache = None


# =============================================================================
# 同步数据提供者（用于非异步场景）
# =============================================================================

class SyncDataProvider:
    """
    同步数据提供者
    
    使用 PyMongo 同步驱动从 MongoDB 读取数据，
    适用于非异步的计算场景（如 strategy_engine, portfolio_tracker）。
    """
    
    def __init__(self, db=None):
        """
        初始化同步数据提供者
        
        Args:
            db: MongoDB 数据库实例，如果为 None 则从 Database 获取
        """
        self._db = db
        self._prices_cache: Optional[pd.DataFrame] = None
        self._fx_cache: Optional[pd.DataFrame] = None
        self._trade_dates_cache: Optional[List[pd.Timestamp]] = None
    
    def _get_db(self):
        """获取数据库实例"""
        if self._db is not None:
            return self._db
        # 使用同步客户端
        from app.config.database import get_sync_db
        return get_sync_db()
    
    def load_prices(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        asset_columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        加载资产价格数据（同步版本）。参数与异步版 load_prices 一致。
        """
        db = self._get_db()
        collection = db[config.MONGO_COLLECTIONS['prices']]
        
        # asset_prices.date 为 YYYY-MM-DD 字符串，直接用字符串比较
        query: Dict = {}
        if start_date or end_date:
            query['date'] = {}
            if start_date:
                query['date']['$gte'] = start_date
            if end_date:
                query['date']['$lte'] = end_date
        
        pivot_columns: Optional[List[str]] = asset_columns
        if asset_columns is None or _is_full_legacy_chinese_universe(asset_columns):
            asset_codes = stored_price_codes_for_monitor()
            pivot_columns = None
        else:
            asset_codes = _dedupe_asset_tokens(list(asset_columns))
        if not asset_codes:
            cols = list(config.ASSET_LIST) if pivot_columns is None else _dedupe_asset_tokens(
                list(asset_columns or [])
            )
            return pd.DataFrame(columns=cols)
        query['asset_code'] = {'$in': asset_codes}
        
        records = list(collection.find(query).sort('date', 1))
        return _prices_pivot_from_records(records, pivot_columns)
    
    def load_fx(self, start_date: Optional[str] = None,
                end_date: Optional[str] = None) -> pd.DataFrame:
        """
        加载汇率数据（同步版本）
        
        Mongo 为空时回退 data/fx.xlsx（与 async 版、FxService 一致）。
        
        Returns
        -------
        pd.DataFrame
            索引为日期(pd.Timestamp)，列为 HKD, USD, EUR, JPY, CNH
        """
        db = self._get_db()
        collection = db[config.MONGO_COLLECTIONS['fx']]
        
        # 构建查询条件（fx_rates.date 为 YYYY-MM-DD 字符串，直接用字符串比较）
        query = {}
        if start_date or end_date:
            query['date'] = {}
            if start_date:
                query['date']['$gte'] = start_date
            if end_date:
                query['date']['$lte'] = end_date
        
        # 查询数据
        records = list(collection.find(query).sort('date', 1))
        
        if not records:
            df = _fx_from_xlsx(start_date=start_date, end_date=end_date)
            if not df.empty:
                logger.info(
                    "Mongo fx_rates 为空，已从 data/fx.xlsx 加载 {} 行汇率",
                    len(df),
                )
            return df
        
        # 转换为 DataFrame
        df = pd.DataFrame(records)
        
        # 设置日期索引
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        df.index.name = 'date'
        
        # 确保包含必需的汇率列
        for col in ['HKD', 'USD', 'EUR', 'JPY']:
            if col not in df.columns:
                df[col] = 1.0
        
        # CNH 始终为 1.0
        df['CNH'] = 1.0
        
        # 只保留需要的列
        df = df[['HKD', 'USD', 'EUR', 'JPY', 'CNH']]
        
        return _normalize_fx_dataframe(df)
    
    def load_trade_dates(self) -> List[pd.Timestamp]:
        """
        加载交易日历（同步版本，MongoDB trade_dates 集合，唯一来源）

        Returns
        -------
        List[pd.Timestamp]
            排序后的交易日列表；集合为空时返回空列表
        """
        db = self._get_db()
        collection = db[config.MONGO_COLLECTIONS['trade_dates']]

        records = list(collection.find({}).sort('date', 1))

        if not records:
            logger.warning("Mongo trade_dates 集合为空，交易日历不可用")
            return []

        dates = [normalize_calendar_timestamp(r['date']) for r in records]

        return sorted(set(dates))
    
    def get_latest_date(self) -> pd.Timestamp:
        """获取价格数据中的最新日期"""
        db = self._get_db()
        collection = db[config.MONGO_COLLECTIONS['prices']]
        
        # 查询最新日期
        record = collection.find_one({}, sort=[('date', -1)])
        
        if record:
            return pd.Timestamp(record['date'])
        
        return pd.Timestamp.now()
    
    def clear_cache(self):
        """清除缓存数据"""
        self._prices_cache = None
        self._fx_cache = None
        self._trade_dates_cache = None


# =============================================================================
# 工厂函数
# =============================================================================

def create_data_provider(async_mode: bool = True):
    """
    创建数据提供者实例
    
    Parameters
    ----------
    async_mode : bool
        是否使用异步模式，默认 True
        
    Returns
    -------
    MongoDataProvider 或 SyncDataProvider
    """
    if async_mode:
        return MongoDataProvider()
    return SyncDataProvider()


def get_sync_provider() -> SyncDataProvider:
    """获取同步数据提供者实例"""
    return SyncDataProvider()
