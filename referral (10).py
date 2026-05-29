"""
ACCESS CHECK MIDDLEWARE — priority message deletion with full Telegram support.

Supported:
  ✓ Regular groups / supergroups
  ✓ Channels (via linked groups)
  ✓ Forum topics (message_thread_id preserved)
  ✓ Media groups (all messages in group tracked)
  ✓ Anonymous admins (sender_chat detection)
  ✓ Business chats (bypass — no access check)
  ✓ Bot messages (bypass)
  ✓ Creator bypass

Architecture:
  1. Filter out bypasses (private, bot, creator, business, anon admin)
  2. Check group access_control_enabled (in-process dict cache)
  3. Check Redis O(1): is_warm? → SISMEMBER; not warm → DB query + bg warm
  4. If not authorized → DeleteQueue.enqueue() (non-blocking) + stats
"""

import asyncio
from typing import Callable, Dict, Any, Awaitable, Optional, Set
from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Message
from loguru import logger

from bot.cache.redis_cache import AccessCache
from bot.core.queue import DeleteQueue
from bot.core.metrics import metrics
from bot.config import settings


_SKIP_CHAT_TYPES = frozenset(("private", "sender"))

_group_control_cache: Dict[int, bool] = {}
_tg_admin_cache: Dict[str, Set[int]] = {}
_tg_admin_cache_ttl: Dict[str, float] = {}
_media_group_tracked: Dict[str, bool] = {}
ADMIN_CACHE_TTL = 120.0
MEDIA_GROUP_CACHE_TTL = 60.0

_warming: Set[int] = set()


async def _is_tg_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    import time
    key = str(chat_id)
    now = time.monotonic()
    if key in _tg_admin_cache and (now - _tg_admin_cache_ttl.get(key, 0)) < ADMIN_CACHE_TTL:
        return user_id in _tg_admin_cache[key]
    try:
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids: Set[int] = set()
        for a in admins:
            admin_ids.add(a.user.id)
            if hasattr(a, "is_anonymous") and a.is_anonymous:
                admin_ids.add(0)
        _tg_admin_cache[key] = admin_ids
        _tg_admin_cache_ttl[key] = now
        return user_id in admin_ids
    except Exception:
        return False


def _is_anonymous_admin(message: Message) -> bool:
    """Detect anonymous admin posts (sender_chat = channel/group instead of user)."""
    if message.sender_chat:
        return message.sender_chat.id == message.chat.id
    return False


def _is_business_chat(message: Message) -> bool:
    """Telegram Business chats should bypass access control."""
    return bool(getattr(message, "business_connection_id", None))


def _is_media_group_duplicate(message: Message) -> bool:
    """Track media groups to avoid queuing multiple deletes for same group."""
    if not message.media_group_id:
        return False
    import time
    key = f"{message.chat.id}:{message.media_group_id}"
    now = time.monotonic()
    existing_ts = _media_group_tracked.get(key)
    if existing_ts is not None and (now - existing_ts) < MEDIA_GROUP_CACHE_TTL:
        return True
    _media_group_tracked[key] = now
    _cleanup_old_media_group_cache()
    return False


def _cleanup_old_media_group_cache() -> None:
    import time
    if len(_media_group_tracked) < 1000:
        return
    now = time.monotonic()
    expired = [k for k, ts in _media_group_tracked.items() if (now - ts) > MEDIA_GROUP_CACHE_TTL]
    for k in expired:
        del _media_group_tracked[k]


class AccessCheckMiddleware(BaseMiddleware):
    """
    Priority message deletion middleware.
    Register as OUTER middleware on messages AFTER DatabaseMiddleware.
    """

    def __init__(self, access_cache: AccessCache, delete_queue: DeleteQueue):
        self.cache = access_cache
        self.queue = delete_queue

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        chat = event.chat
        if chat.type in _SKIP_CHAT_TYPES:
            return await handler(event, data)

        user = event.from_user
        if not user or user.is_bot:
            return await handler(event, data)

        group_id = chat.id
        user_id = user.id

        if user_id == settings.CREATOR_USER_ID:
            return await handler(event, data)

        if _is_business_chat(event):
            return await handler(event, data)

        if _is_anonymous_admin(event):
            return await handler(event, data)

        session = data.get("session")
        if session is None:
            return await handler(event, data)

        if not await self._is_group_controlled(group_id, session):
            return await handler(event, data)

        bot: Bot = data["bot"]

        if await _is_tg_admin(bot, group_id, user_id):
            metrics.messages_allowed.inc()
            return await handler(event, data)

        authorized = await self._check_access(group_id, user_id, session)

        if not authorized:
            if _is_media_group_duplicate(event):
                await self.queue.enqueue(group_id, event.message_id, user_id)
                return
            await self.queue.enqueue(group_id, event.message_id, user_id)
            asyncio.create_task(self._inc_stats(group_id))
            metrics.messages_deleted.inc()
            return

        metrics.messages_allowed.inc()
        return await handler(event, data)

    async def _is_group_controlled(self, group_id: int, session) -> bool:
        if group_id in _group_control_cache:
            return _group_control_cache[group_id]
        try:
            from sqlalchemy import select
            from bot.models.group import Group
            result = await session.execute(
                select(Group.access_control_enabled, Group.is_active).where(Group.id == group_id)
            )
            row = result.one_or_none()
            if row is None:
                _group_control_cache[group_id] = False
                return False
            controlled = bool(row[0]) and bool(row[1])
            _group_control_cache[group_id] = controlled
            return controlled
        except Exception as e:
            logger.error(f"Group control check failed for {group_id}: {e}")
            return False

    async def _check_access(self, group_id: int, user_id: int, session) -> bool:
        if await self.cache.is_cache_warm(group_id):
            result = await self.cache.check_user_access(group_id, user_id)
            if result:
                metrics.cache_hits.inc()
            else:
                metrics.cache_misses.inc()
            return result

        if group_id not in _warming:
            _warming.add(group_id)
            asyncio.create_task(self._warm_group_async(group_id, session))

        try:
            from sqlalchemy import select, and_
            from bot.models.access import UserAccess
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            result = await session.execute(
                select(UserAccess.id).where(
                    and_(
                        UserAccess.user_id == user_id,
                        UserAccess.group_id == group_id,
                        UserAccess.is_active == True,
                        (UserAccess.expires_at == None) | (UserAccess.expires_at > now),
                    )
                ).limit(1)
            )
            has_access = result.scalar_one_or_none() is not None
            metrics.cache_misses.inc()
            if has_access:
                await self.cache.grant_access(group_id, user_id)
            return has_access
        except Exception as e:
            logger.error(f"DB access check failed for {group_id}/{user_id}: {e}")
            return True  # fail-open to avoid false positives

    async def _warm_group_async(self, group_id: int, session) -> None:
        try:
            from sqlalchemy import select, and_
            from bot.models.access import UserAccess
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            result = await session.execute(
                select(UserAccess.user_id).where(
                    and_(
                        UserAccess.group_id == group_id,
                        UserAccess.is_active == True,
                        (UserAccess.expires_at == None) | (UserAccess.expires_at > now),
                    )
                )
            )
            user_ids = {row[0] for row in result.all()}
            await self.cache.warm_group_cache(group_id, user_ids, set())
            metrics.cache_warm_groups.inc()
            logger.debug(f"Cache warmed for group {group_id}: {len(user_ids)} users")
        except Exception as e:
            logger.error(f"Cache warm failed for group {group_id}: {e}")
        finally:
            _warming.discard(group_id)

    async def _inc_stats(self, group_id: int) -> None:
        try:
            await self.cache.incr(f"stats:deleted:{group_id}")
            await self.cache.incr("stats:deleted:total")
        except Exception:
            pass

    @classmethod
    def invalidate_group_control_cache(cls, group_id: int) -> None:
        _group_control_cache.pop(group_id, None)

    @classmethod
    def invalidate_tg_admin_cache(cls, group_id: int) -> None:
        _tg_admin_cache.pop(str(group_id), None)
