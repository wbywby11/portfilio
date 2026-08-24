"""
loguru 日志配置：启动时调用一次，配置控制台 + 文件切分存储

包含 InterceptHandler：将标准库 logging 的所有消息转发到 loguru，
确保使用 logging.getLogger(__name__) 的模块日志不会丢失。
"""
import logging
import os
import sys
from loguru import logger


class InterceptHandler(logging.Handler):
    """将标准库 logging 消息桥接到 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        # 获取对应的 loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找到真正的 caller frame
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


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

    # 桥接标准库 logging → loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
