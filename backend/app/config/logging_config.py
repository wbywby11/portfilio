"""
loguru 日志配置：启动时调用一次，配置控制台 + 文件切分存储
"""
import os
import sys
from loguru import logger


def setup_logging(
    log_dir: str = "logs",
    console_level: str = "INFO",
    file_level: str = "INFO",
    retention: str = "7 days",
):
    """配置 loguru：控制台 + 按天切分文件，旧文件按 retention 清理。"""
    logger.remove()
    os.makedirs(log_dir, exist_ok=True)
    logger.add(
        sys.stderr,
        level=console_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )
    logger.add(
        os.path.join(log_dir, "app_{time:YYYY-MM-DD}.log"),
        rotation="00:00",
        retention=retention,
        level=file_level,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )
