"""
数据库连接配置
"""
from loguru import logger
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from app.config.settings import settings


class Database:
    """数据库连接管理"""
    
    client: AsyncIOMotorClient = None
    db = None
    
    @classmethod
    def connect(cls):
        """建立数据库连接"""
        cls.client = AsyncIOMotorClient(settings.MONGODB_URL)
        cls.db = cls.client[settings.DATABASE_NAME]
        logger.info("数据库连接成功: {}", settings.DATABASE_NAME)
    
    @classmethod
    def close(cls):
        """关闭数据库连接"""
        if cls.client:
            cls.client.close()
            logger.info("数据库连接已关闭")
    
    @classmethod
    def get_database(cls):
        """获取数据库实例"""
        return cls.db


# 同步客户端(用于数据初始化等场景)
def get_sync_db():
    """获取同步数据库连接"""
    client = MongoClient(settings.MONGODB_URL)
    return client[settings.DATABASE_NAME]
