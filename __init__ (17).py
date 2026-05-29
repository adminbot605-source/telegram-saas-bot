"""
APScheduler background tasks.
All tasks use their own DB sessions — never share with request context.
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from loguru import logger

from bot.database.session import async_session_factory
from bot.cache.redis_cache import AccessCache


scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


async def process_expired_accesses(bot: Bot, cache: AccessCache) -> None:
    """Revoke expired accesses, restrict users in groups, notify them."""
    try:
        from bot.repositories.access_repo import AccessRepository
        from bot.repositories.group_repo import GroupRepository
        from sqlalchemy import update
        from bot.models.access import UserAccess
        from datetime import datetime, timezone

        async with async_session_factory() as session:
            access_repo = AccessRepository(session)
            group_repo = GroupRepository(session)
            expired = await access_repo.get_expired_accesses()

            if not expired:
                return

            groups_users: dict[int, list[int]] = {}
            for acc in expired:
                groups_users.setdefault(acc.group_id, []).append(acc.user_id)

            count = await access_repo.expire_batch([a.id for a in expired])
            await session.commit()

        for group_id, user_ids in groups_users.items():
            await cache.bulk_revoke_expired(group_id, set(user_ids))

        from bot.repositories.group_repo import GroupRepository
        async with async_session_factory() as session:
            group_repo = GroupRepository(session)
            for acc in expired:
                group = await group_repo.get_by_id(acc.group_id)
                if group and group.access_control_enabled:
                    try:
                        await bot.restrict_chat_member(
                            acc.group_id,
                            acc.user_id,
                            permissions={"can_send_messages": False},
                        )
                    except Exception as e:
                        logger.debug(f"Restrict {acc.user_id} in {acc.group_id}: {e}")

                try:
                    group_title = group.title if group else str(acc.group_id)
                    await bot.send_message(
                        acc.user_id,
                        f"❌ <b>Доступ истёк</b>\n\n"
                        f"Ваш доступ в группу <b>{group_title}</b> истёк.\n"
                        f"Для продления обратитесь к владельцу группы.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

        logger.info(f"Expired accesses processed: {count}")
    except Exception as e:
        logger.error(f"process_expired_accesses error: {e}")


async def send_expiry_reminders(bot: Bot) -> None:
    """Send reminders 24h and 3h before expiry."""
    try:
        from bot.repositories.access_repo import AccessRepository
        from bot.repositories.group_repo import GroupRepository
        from bot.utils.helpers import format_date

        for hours in [72, 24, 3]:
            async with async_session_factory() as session:
                access_repo = AccessRepository(session)
                group_repo = GroupRepository(session)
                expiring = await access_repo.get_expiring_soon(hours=hours)

                for acc in expiring:
                    key = f"remind_sent:{acc.id}:{hours}"
                    already_sent = await _check_remind_key(key)
                    if already_sent:
                        continue

                    group = await group_repo.get_by_id(acc.group_id)
                    group_title = group.title if group else str(acc.group_id)
                    try:
                        await bot.send_message(
                            acc.user_id,
                            f"⏰ <b>Напоминание</b>\n\n"
                            f"Ваш доступ в <b>{group_title}</b> истекает через <b>{hours} ч.</b>\n"
                            f"📅 {format_date(acc.expires_at)}\n\n"
                            f"Продлите доступ у владельца группы.",
                            parse_mode="HTML",
                        )
                        await _set_remind_key(key, ttl=hours * 3600 + 3600)
                    except Exception as e:
                        logger.debug(f"Reminder to {acc.user_id} failed: {e}")
    except Exception as e:
        logger.error(f"send_expiry_reminders error: {e}")


_reminder_cache: dict[str, bool] = {}


async def _check_remind_key(key: str) -> bool:
    return _reminder_cache.get(key, False)


async def _set_remind_key(key: str, ttl: int = 86400) -> None:
    _reminder_cache[key] = True


async def send_scheduled_posts(bot: Bot) -> None:
    try:
        from bot.models.scheduled_post import ScheduledPost, PostStatus
        from sqlalchemy import select, update
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        async with async_session_factory() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ScheduledPost).where(
                    ScheduledPost.status == PostStatus.PENDING.value,
                    ScheduledPost.scheduled_at <= now,
                )
            )
            posts = list(result.scalars().all())

        for post in posts:
            try:
                await bot.send_message(post.group_id, post.text, parse_mode=post.parse_mode)
                async with async_session_factory() as session:
                    from sqlalchemy import update
                    await session.execute(
                        update(ScheduledPost).where(ScheduledPost.id == post.id)
                        .values(status=PostStatus.SENT.value, sent_at=now)
                    )
                    await session.commit()
                logger.info(f"Scheduled post {post.id} sent to {post.group_id}")
            except Exception as e:
                logger.error(f"Scheduled post {post.id} failed: {e}")
                async with async_session_factory() as session:
                    from sqlalchemy import update
                    await session.execute(
                        update(ScheduledPost).where(ScheduledPost.id == post.id)
                        .values(status=PostStatus.FAILED.value, error_message=str(e)[:500])
                    )
                    await session.commit()
    except Exception as e:
        logger.error(f"send_scheduled_posts error: {e}")


async def refresh_access_cache(cache: AccessCache) -> None:
    """Periodically rewarm expired cache entries for active groups."""
    try:
        from bot.repositories.group_repo import GroupRepository
        from bot.repositories.access_repo import AccessRepository

        async with async_session_factory() as session:
            group_repo = GroupRepository(session)
            access_repo = AccessRepository(session)
            groups = await group_repo.get_all_access_controlled()

            for group in groups:
                if not await cache.is_cache_warm(group.id):
                    user_ids = await access_repo.get_group_authorized_users(group.id)
                    await cache.warm_group_cache(group.id, user_ids, set())

        logger.debug(f"Access cache refresh done for {len(groups)} groups")
    except Exception as e:
        logger.error(f"refresh_access_cache error: {e}")


async def cleanup_old_payments() -> None:
    """Mark very old pending payments as expired."""
    try:
        from bot.models.payment import Payment, PaymentStatus
        from sqlalchemy import update
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        async with async_session_factory() as session:
            result = await session.execute(
                update(Payment)
                .where(
                    Payment.status == PaymentStatus.PENDING.value,
                    Payment.created_at < cutoff,
                )
                .values(status=PaymentStatus.EXPIRED.value)
                .returning(Payment.id)
            )
            ids = result.all()
            await session.commit()
        if ids:
            logger.info(f"Expired {len(ids)} old pending payments")
    except Exception as e:
        logger.error(f"cleanup_old_payments error: {e}")


def setup_scheduler(bot: Bot, cache: AccessCache) -> AsyncIOScheduler:
    scheduler.add_job(
        process_expired_accesses,
        trigger=IntervalTrigger(minutes=5),
        args=[bot, cache],
        id="process_expired_accesses",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        send_expiry_reminders,
        trigger=IntervalTrigger(hours=1),
        args=[bot],
        id="send_expiry_reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        send_scheduled_posts,
        trigger=IntervalTrigger(minutes=1),
        args=[bot],
        id="send_scheduled_posts",
        replace_existing=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        refresh_access_cache,
        trigger=IntervalTrigger(minutes=30),
        args=[cache],
        id="refresh_access_cache",
        replace_existing=True,
    )
    scheduler.add_job(
        cleanup_old_payments,
        trigger=CronTrigger(hour=3, minute=0),
        id="cleanup_old_payments",
        replace_existing=True,
    )
    return scheduler
