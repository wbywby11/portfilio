"""
系统配置文件
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用基本配置
    APP_NAME: str = "资产配置系统"
    APP_VERSION: str = "0.2.28"  # 0228 版本基准
    DEBUG: bool = True
    
    # 数据库配置
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "asset_allocation"
    # Mongo asset_prices 中 asset_code 相对监控标准码的后缀（如 _TEST）；空表示与 config 一致
    MONGO_ASSET_CODE_SUFFIX: str = ""
    
    # API配置
    API_PREFIX: str = "/api/v1"
    # 与 .env / .env.example 一致，供 uvicorn 启动与前端 VUE_APP_API_PORT 对齐
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    # 数据源配置
    DATA_SOURCE: str = "local"  # local, tushare, akshare

    # Agent DataHub 专用工具：执行查询前先尝试上游拉数落库；失败或非成功状态时仍查本地 Mongo
    AGENT_SYNC_HUB_BEFORE_QUERY: bool = True
    AGENT_HUB_IMPORT_ROWNUM: int = 50_000
    AGENT_HUB_IMPORT_TIMEOUT: float = 120.0
    # 主体舆情：同一会话内上游同步成功过一次后，后续 subject_risk_search 默认仅查本地库（避免重复大流量 API）；工具参数 force_upstream_sync=true 可强制再拉取
    AGENT_SUBJECT_RISK_ONE_SYNC_PER_CONVERSATION: bool = True

    # Data Hub 上游数据接入配置
    DATA_HUB_UPSTREAM_URL: str = "http://zylcorms.wmverify.com:8080/jxdatamid/apiManage/getPyResult"
    DATA_HUB_UPSTREAM_TIMEOUT: float = 180.0
    SUBJECT_RISK_RESOURCE: str = "adm_subject_opinion_risk_stats"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
