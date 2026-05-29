"""
Chat events handler: join/leave, message moderation.
Access control is handled UPSTREAM by AccessCheckMiddleware.
This module handles anti-flood, welcome messages, and link/forward filtering.
"""

import asyncio
import time
from collections import defaultdict, deque
from aiogram import Router, F, Bot
from aiogram.types import Message, ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION, LEAVE_TRANSITION
from loguru import logger

from bot.database.session import async_session_factory
from bot.models.group import Group
from sqlalchemy import select, update

router = Router()

_flood_buckets: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_user_join(event: ChatMemberUpdated, bot: Bot):
    user = event.new_chat_member.user
    if user.is_bot:
        return

    async with async_session_factory() as session:
        result = await session.execute(
            select(Group).where(Group.id == event.chat.id, Group.is_active == True)
        )
        group = result.scalar_one_or_none()

    if not group:
        return

    try:
        count = await bot.get_chat_member_count(event.chat.id)
        async with async_session_factory() as session:
            await session.execute(
                update(Group).where(Group.id == event.chat.id).values(member_count=count)
            )
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to update member count for {event.chat.id}: {e}")

    if not group.welcome_enabled or not group.welcome_message:
        return

    try:
        text = group.welcome_message.format(
            name=user.first_name,
            username=f"@{user.username}" if user.username else user.first_name,
            group=event.chat.title or "",
            id=user.id,
        )
        sent = await bot.send_message(
            event.chat.id,
            text,
            parse_mode="HTML",
        )
        if group.welcome_delete_after > 0:
            asyncio.create_task(_delete_after(bot, event.chat.id, sent.message_id, group.welcome_delete_after))
    except Exception as e:
        logger.error(f"Welcome message error in {event.chat.id}: {e}")


async def _delete_after(bot: Bot, chat_id: int, message_id: int, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def on_user_leave(event: ChatMemberUpdated, bot: Bot):
    try:
        count = await bot.get_chat_member_count(event.chat.id)
        async with async_session_factory() as session:
            await session.execute(
                update(Group).where(Group.id == event.chat.id).values(member_count=count)
            )
            await session.commit()
    except Exception as e:
        logger.warning(f"Leave update failed for {event.chat.id}: {e}")


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: Message, bot: Bot):
    """
    Secondary moderation (anti-flood, link/forward delete).
    Access control is already handled by AccessCheckMiddleware upstream.
    """
    if not message.from_user or message.from_user.is_bot:
        return

    async with async_session_factory() as session:
        result = await session.execute(
            select(Group).where(Group.id == message.chat.id, Group.is_active == True)
        )
        group = result.scalar_one_or_none()

    if not group:
        return

    if group.delete_joins and message.new_chat_members:
        try:
            await message.delete()
            return
        except Exception:
            pass

    if group.delete_links and message.entities:
        for entity in message.entities:
            if entity.type in ("url", "text_link"):
                try:
                    await message.delete()
                    return
                except Exception:
                    pass

    if group.delete_forwards and message.forward_date:
        try:
            await message.delete()
            return
        except Exception:
            pass

    if group.anti_flood_enabled and message.from_user:
        user_id = message.from_user.id
        chat_id = message.chat.id
        key = f"{chat_id}:{user_id}"
        now = time.monotonic()
        window = 10.0
        limit = group.flood_limit

        bucket = _flood_buckets[key]
        while bucket and (now - bucket[0]) > window:
            bucket.popleft()
        bucket.append(now)

        if len(bucket) > limit:
            try:
                await message.delete()
                until = int(time.time()) + group.flood_mute_duration
                await bot.restrict_chat_member(
                    chat_id,
                    user_id,
                    permissions={"can_send_messages": False},
                    until_date=until,
                )
                await bot.send_message(
                    chat_id,
                    f"🚫 {message.from_user.first_name} временно ограничен за флуд "
                    f"на {group.flood_mute_duration} сек.",
                )
                bucket.clear()
            except Exception as e:
                logger.warning(f"Flood restrict failed in {chat_id}: {e}")
