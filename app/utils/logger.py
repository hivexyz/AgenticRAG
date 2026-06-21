"""
日志配置
使用 loguru 进行日志管理
"""
import json
import sys
from pathlib import Path

from loguru import logger

from app.config import settings
from app.log_context import current_request_context


def _json_sink(message):
    record = message.record
    payload = {
        "time": record["time"].strftime("%Y-%m-%dT%H:%M:%S%z"),
        "level": record["level"].name,
        "message": record["message"],
        "module": record["name"],
        "function": record["function"],
        "line": record["line"],
        **current_request_context(),
    }
    with open(settings.LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


logger.remove()

log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

logger.add(sys.stdout, format=log_format, level=settings.LOG_LEVEL, colorize=True)

log_file_path = Path(settings.LOG_FILE)
log_file_path.parent.mkdir(parents=True, exist_ok=True)

logger.add(_json_sink, level=settings.LOG_LEVEL)
