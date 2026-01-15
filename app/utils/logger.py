"""
日志配置
使用 loguru 进行日志管理
"""
from loguru import logger
import sys
from pathlib import Path
from app.config import settings

# 移除默认处理器
logger.remove()

# 日志格式
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# 添加控制台输出
logger.add(
    sys.stdout,
    format=log_format,
    level=settings.LOG_LEVEL,
    colorize=True,
)

# 确保日志目录存在
log_file_path = Path(settings.LOG_FILE)
log_file_path.parent.mkdir(parents=True, exist_ok=True)

# 添加文件输出
logger.add(
    settings.LOG_FILE,
    rotation="00:00",  # 每天午夜轮转
    retention="30 days",  # 保留30天
    compression="zip",  # 压缩旧日志
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level=settings.LOG_LEVEL,
    encoding="utf-8",
)
