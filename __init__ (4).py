import sys
import os
from loguru import logger
from bot.config import settings


def setup_logging() -> None:
    logger.remove()

    fmt_console = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
        "<level>{message}</level>"
    )
    fmt_file = (
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
        "{name}:{function}:{line} — {message}"
    )

    logger.add(
        sys.stdout,
        format=fmt_console,
        level=settings.LOG_LEVEL,
        colorize=True,
        enqueue=True,
    )

    os.makedirs("logs", exist_ok=True)

    logger.add(
        "logs/bot.log",
        format=fmt_file,
        level="INFO",
        rotation="50 MB",
        retention="14 days",
        compression="zip",
        enqueue=True,
    )

    logger.add(
        "logs/errors.log",
        format=fmt_file,
        level="ERROR",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        enqueue=True,
    )

    logger.info(
        f"Logging configured | level={settings.LOG_LEVEL} | debug={settings.DEBUG}"
    )
