"""
初始化指数数据脚本（扩展版）
从互联网获取多种指数的历史行情数据并导入数据库

支持的指数：
- A股：上证50、沪深300、创业板指数、科创50
- 港股：恒生指数
- 美股：纳斯达克指数
- 日股：日经225指数
- ETF：黄金ETF

使用 akshare 库获取数据（免费、无需注册）
安装: pip install akshare
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict
from pymongo import MongoClient
from app.config.settings import settings
from app.models.asset import Asset, AssetPrice, AssetType


class IndexDataInitializer:
    """指数数据初始化器"""
    
    def __init__(self):
        """初始化数据库连接"""
        self.client = MongoClient(settings.MONGODB_URL)
        self.db = self.client[settings.DATABASE_NAME]
        self.assets_collection = self.db['assets']
        self.prices_collection = self.db['asset_prices']
        
        # 指数配置
        self.indices = [
            # A股指数
            {
                'code': 'SH000016',
                'name': '上证50指数',
                'symbol': 'sh000016',
                'exchange': '上海证券交易所',
                'description': '上证50指数由上海证券市场规模大、流动性好的最具代表性的50只股票组成',
                'fetch_method': 'cn_index'
            },
            {
                'code': 'SH000300',
                'name': '沪深300指数',
                'symbol': 'sh000300',
                'exchange': '沪深交易所',
                'description': '沪深300指数由沪深市场中市值大、流动性好的300只股票组成',
                'fetch_method': 'cn_index'
            },
            {
                'code': 'SH000852',
                'name': '中证1000指数',
                'symbol': 'sh000852',
                'exchange': '中证指数公司',
                'description': '中证1000指数由中证800指数样本股之外规模偏小且流动性好的1000只证券组成',
                'fetch_method': 'cn_index'
            },
            {
                'code': 'SH000510',
                'name': '中证A500指数',
                'symbol': 'sh000510',
                'exchange': '中证指数公司',
                'description': '中证A500指数由沪深市场代表性强、流动性好的500只股票组成',
                'fetch_method': 'cn_index'
            },
            {
                'code': 'SZ399006',
                'name': '创业板指数',
                'symbol': 'sz399006',
                'exchange': '深圳证券交易所',
                'description': '创业板指数反映创业板市场整体运行情况',
                'fetch_method': 'cn_index'
            },
            {
                'code': 'SH000688',
                'name': '科创50指数',
                'symbol': 'sh000688',
                'exchange': '上海证券交易所',
                'description': '科创50指数由科创板中市值大、流动性好的50只证券组成',
                'fetch_method': 'cn_index'
            },
            
            # 港股指数
            {
                'code': 'HSI',
                'name': '恒生指数',
                'symbol': 'HSI',
                'exchange': '香港证券交易所',
                'description': '恒生指数是香港股市的主要指标，反映香港股市整体表现',
                'fetch_method': 'hk_index'
            },
        ]
    
    def fetch_index_data(self, symbol: str, fetch_method: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        根据不同的方法获取指数历史数据
        
        Args:
            symbol: 指数代码
            fetch_method: 获取方法 (cn_index/hk_index/us_index/jp_index/us_etf)
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
        
        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount
        """
        try:
            print(f"📊 正在获取 {symbol} 的历史数据...")
            
            df = pd.DataFrame()
            
            # 根据不同的方法获取数据
            if fetch_method == 'cn_index':
                df = self._fetch_cn_index(symbol)
            elif fetch_method == 'hk_index':
                df = self._fetch_hk_index(symbol)
            elif fetch_method == 'us_index':
                df = self._fetch_us_index(symbol)
            elif fetch_method == 'jp_index':
                df = self._fetch_jp_index(symbol)
            elif fetch_method == 'us_etf':
                df = self._fetch_us_etf(symbol)
            else:
                print(f"   ⚠️  未知的获取方法: {fetch_method}")
                return pd.DataFrame()
            
            if df.empty:
                print(f"   ⚠️  未获取到 {symbol} 的数据")
                return pd.DataFrame()
            
            # 筛选日期范围
            if start_date:
                start = pd.to_datetime(start_date)
                df = df[df['date'] >= start]
            if end_date:
                end = pd.to_datetime(end_date)
                df = df[df['date'] <= end]
            
            print(f"   ✅ 成功获取 {len(df)} 条数据")
            return df
            
        except Exception as e:
            print(f"   ❌ 获取 {symbol} 数据失败: {str(e)}")
            return pd.DataFrame()
    
    def _fetch_cn_index(self, symbol: str) -> pd.DataFrame:
        """获取中国指数数据"""
        df = ak.stock_zh_index_daily(symbol=symbol)
        if df.empty:
            return pd.DataFrame()
        
        df.rename(columns={'date': 'date', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'}, inplace=True)
        df['date'] = pd.to_datetime(df['date'])
        columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        df = df[[col for col in columns if col in df.columns]]
        if 'amount' not in df.columns:
            df['amount'] = None
        return df
    
    def _fetch_hk_index(self, symbol: str) -> pd.DataFrame:
        """获取香港指数数据"""
        try:
            df = ak.stock_hk_index_daily_em(symbol=symbol)
            if df.empty:
                return pd.DataFrame()
            df.rename(columns={'日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low', '收盘': 'close', '成交量': 'volume'}, inplace=True)
            df['date'] = pd.to_datetime(df['date'])
            columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            df = df[[col for col in columns if col in df.columns]]
            if 'amount' not in df.columns:
                df['amount'] = None
            return df
        except Exception:
            return pd.DataFrame()
    
    def _fetch_us_index(self, symbol: str) -> pd.DataFrame:
        """获取美国指数数据"""
        try:
            df = ak.index_us_stock_sina(symbol=symbol)
            if df.empty:
                return pd.DataFrame()
            df.rename(columns={'date': 'date', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'}, inplace=True)
            df['date'] = pd.to_datetime(df['date'])
            columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            df = df[[col for col in columns if col in df.columns]]
            if 'amount' not in df.columns:
                df['amount'] = None
            return df
        except Exception:
            return pd.DataFrame()
    
    def _fetch_jp_index(self, symbol: str) -> pd.DataFrame:
        """获取日本指数数据"""
        try:
            # 使用东方财富接口获取日经225指数
            df = ak.index_investing_global(symbol="日经225", country="日本")
            if df.empty:
                return pd.DataFrame()
            df.rename(columns={'日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low', '收盘': 'close', '成交量': 'volume'}, inplace=True)
            df['date'] = pd.to_datetime(df['date'])
            columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            df = df[[col for col in columns if col in df.columns]]
            if 'amount' not in df.columns:
                df['amount'] = None
            return df
        except Exception:
            return pd.DataFrame()
    
    def _fetch_us_etf(self, symbol: str) -> pd.DataFrame:
        """获取美国ETF数据"""
        try:
            # 使用美股指数接口获取ETF数据
            df = ak.index_us_stock_sina(symbol=symbol)
            if df.empty:
                return pd.DataFrame()
            df.rename(columns={'date': 'date', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'}, inplace=True)
            df['date'] = pd.to_datetime(df['date'])
            columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            df = df[[col for col in columns if col in df.columns]]
            if 'amount' not in df.columns:
                df['amount'] = None
            return df
        except Exception:
            return pd.DataFrame()
    
    def create_or_update_asset(self, asset_info: Dict) -> str:
        """
        创建或更新资产记录
        
        Returns:
            资产代码
        """
        asset_code = asset_info['code']
        
        # 检查资产是否已存在
        existing = self.assets_collection.find_one({'code': asset_code})
        
        asset_data = {
            'code': asset_code,
            'name': asset_info['name'],
            'asset_type': AssetType.INDEX.value,
            'exchange': asset_info['exchange'],
            'description': asset_info['description'],
            'is_active': True,
            'updated_at': datetime.now()
        }
        
        if existing:
            # 更新现有资产
            self.assets_collection.update_one(
                {'code': asset_code},
                {'$set': asset_data}
            )
            print(f"   ✅ 资产已更新: {asset_info['name']} ({asset_code})")
        else:
            # 创建新资产
            asset_data['created_at'] = datetime.now()
            self.assets_collection.insert_one(asset_data)
            print(f"   ✅ 资产已创建: {asset_info['name']} ({asset_code})")
        
        return asset_code
    
    def insert_price_data(self, asset_code: str, df: pd.DataFrame, replace_existing: bool = False):
        """
        插入价格数据
        
        Args:
            asset_code: 资产代码
            df: 价格数据 DataFrame
            replace_existing: 是否替换已存在的数据
        """
        if df.empty:
            print(f"   ⚠️  没有数据需要插入")
            return
        
        # 如果需要替换，先删除已存在的数据
        if replace_existing:
            result = self.prices_collection.delete_many({'asset_code': asset_code})
            print(f"   🗑️  已删除 {result.deleted_count} 条旧数据")
        
        # 准备插入的数据
        price_records = []
        for _, row in df.iterrows():
            # 将日期转换为 YYYY-MM-DD 字符串格式
            date_str = row['date'].strftime('%Y-%m-%d') if isinstance(row['date'], (pd.Timestamp, datetime)) else str(row['date'])
            
            price_data = {
                'asset_code': asset_code,
                'date': date_str,  # 使用字符串格式
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': round(float(row['volume'])) if pd.notna(row.get('volume')) else None,  # 成交量取整
                'amount': float(row['amount']) if pd.notna(row.get('amount')) else None,
            }
            price_records.append(price_data)
        
        # 批量插入
        if price_records:
            try:
                # 为了避免重复，使用 upsert
                for record in price_records:
                    self.prices_collection.update_one(
                        {
                            'asset_code': asset_code,
                            'date': record['date']
                        },
                        {'$set': record},
                        upsert=True
                    )
                print(f"   ✅ 成功插入/更新 {len(price_records)} 条价格数据")
            except Exception as e:
                print(f"   ❌ 插入数据失败: {str(e)}")
    
    def initialize_all(self, start_date: str = None, end_date: str = None, replace_existing: bool = False):
        """
        初始化所有指数数据
        
        Args:
            start_date: 开始日期 YYYY-MM-DD（默认为3年前）
            end_date: 结束日期 YYYY-MM-DD（默认为今天）
            replace_existing: 是否替换已存在的数据
        """
        # 默认获取最近3年的数据
        if not start_date:
            start_date = (datetime.now() - timedelta(days=3*365)).strftime('%Y%m%d')
        else:
            start_date = start_date.replace('-', '')
        
        if not end_date:
            end_date = datetime.now().strftime('%Y%m%d')
        else:
            end_date = end_date.replace('-', '')
        
        print("=" * 70)
        print("🚀 开始初始化指数数据（扩展版）")
        print(f"📅 数据区间: {start_date} ~ {end_date}")
        print(f"🔄 替换模式: {'是' if replace_existing else '否'}")
        print(f"📊 指数数量: {len(self.indices)}")
        print("=" * 70)
        
        success_count = 0
        fail_count = 0
        
        for index_info in self.indices:
            print(f"\n{'='*70}")
            print(f"📈 处理指数: {index_info['name']} ({index_info['code']})")
            print(f"{'='*70}")
            
            try:
                # 1. 创建/更新资产
                asset_code = self.create_or_update_asset(index_info)
                
                # 2. 获取历史数据
                df = self.fetch_index_data(
                    symbol=index_info['symbol'],
                    fetch_method=index_info['fetch_method'],
                    start_date=start_date,
                    end_date=end_date
                )
                
                # 3. 插入价格数据
                if not df.empty:
                    self.insert_price_data(asset_code, df, replace_existing)
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                print(f"   ❌ 处理失败: {str(e)}")
                fail_count += 1
            
            print(f"{'='*70}\n")
        
        print("=" * 70)
        print("🎉 数据初始化完成!")
        print(f"✅ 成功: {success_count} 个指数")
        print(f"❌ 失败: {fail_count} 个指数")
        print("=" * 70)
        
        # 输出统计信息
        self.print_statistics()
    
    def print_statistics(self):
        """打印数据统计信息"""
        print("\n📊 数据统计:")
        for index_info in self.indices:
            asset_code = index_info['code']
            count = self.prices_collection.count_documents({'asset_code': asset_code})
            
            if count > 0:
                # 获取日期范围
                first_record = self.prices_collection.find_one(
                    {'asset_code': asset_code},
                    sort=[('date', 1)]
                )
                last_record = self.prices_collection.find_one(
                    {'asset_code': asset_code},
                    sort=[('date', -1)]
                )
                
                # 日期现在是字符串格式，直接使用
                start_date_str = first_record['date']
                end_date_str = last_record['date']
                
                print(f"\n   {index_info['name']} ({asset_code}):")
                print(f"   - 记录数: {count}")
                print(f"   - 开始日期: {start_date_str}")
                print(f"   - 结束日期: {end_date_str}")
        print()
    
    def close(self):
        """关闭数据库连接"""
        self.client.close()


def main():
    """主函数"""
    print("""
╭──────────────────────────────────────────────────────────────╮
│          指数数据初始化工具（重新导入模式）                       │
│          Index Data Initialization Tool (Re-import)            │
╰──────────────────────────────────────────────────────────────╯
    """)
    
    print("📊 将重新导入以下指数的行情数据：")
    print("   1. 上证50指数 (SH000016)")
    print("   2. 沪深300指数 (SH000300)")
    print("   3. 中证1000指数 (SH000852)")
    print("   4. 中证A500指数 (SH000510)")
    print("   5. 创业板指数 (SZ399006)")
    print("   6. 科创50指数 (SH000688)")
    print("   7. 恒生指数 (HSI)")
    print("\n⚠️  注意：将使用 replace_existing=True 模式，会删除并重新导入所有数据\n")
    
    # 创建初始化器
    initializer = IndexDataInitializer()
    
    try:
        # 执行初始化 - 使用替换模式
        initializer.initialize_all(
            start_date=None,  # 默认3年前
            end_date=None,    # 默认今天
            replace_existing=True  # 重新导入模式
        )
        
    except Exception as e:
        print(f"\n❌ 初始化失败: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        initializer.close()


if __name__ == "__main__":
    main()
