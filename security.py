"""
Telegram FloodWait handler with exponential backoff.
Wraps Bot API calls to automatically retry after FloodWait.
"""

import asyncio
import functools
from typing import Callable, TypeVar, Any
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError
from loguru import logger

from bot.core.metrics import metrics

T = TypeVar("T")

MAX_FLOOD_WAIT = 300  # seconds — abort if floodwait > 5 min
MAX_RETRIES = 4


async def call_with_retry(coro_fn: Callable, *args, max_retries: int = MAX_RETRIES, **kwargs) -> Any:
    """
    Call an async function with automatic FloodWait retry.
    Usage: await call_with_retry(bot.delete_message, chat_id, message_id)
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except TelegramRetryAfter as e:
            wait = e.retry_after
            metrics.floodwait_total.inc()
            if wait > MAX_FLOOD_WAIT:
                logger.warning(f"FloodWait too long ({wait}s), aborting")
                raise
            logger.warning(f"FloodWait {wait}s on attempt {attempt + 1}, sleeping...")
            await asyncio.sleep(wait + 0.5)
            last_exc = e
        except TelegramNetworkError as e:
            if attempt < max_retries:
                delay = 2 ** attempt
                logger.warning(f"NetworkError attempt {attempt + 1}, retry in {delay}s: {e}")
                await asyncio.sleep(delay)
                last_exc = e
            else:
                raise
    raise last_exc


async def safe_delete_message(bot: Bot, chat_id: int, message_id: int) -> bool:
    """Delete a message, handling all expected errors gracefully."""
    try:
        await call_with_retry(bot.delete_message, chat_id, message_id)
        return True
    except TelegramRetryAfter:
        return False
    except Exception as e:
        err = str(e).lower()
        if any(s in err for s in (
            "message to delete not found",
            "message can't be deleted",
            "chat not found",
            "not enough rights",
            "bot was kicked",
            "bot is not a member",
        )):
            return False
        logger.debug(f"safe_delete_message {chat_id}:{message_id} — {e}")
        return False
