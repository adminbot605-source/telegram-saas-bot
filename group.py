"""
Bot entry point.

Startup order:
  1. wait_for_postgres + wait_for_redis
  2. run migrations (if AUTO_MIGRATE)
  3. warm access cache for all active groups
  4. set webhook (with secret token + allowed_updates)
  5. start delete worker pool (N workers consuming delete queue)
  6. start APScheduler (expiry check, reminders, posts, retry flush)
  7. start webhook recovery task
  8. serve HTTP on 0.0.0.0:8080

Routes:
  POST /webhook        — Telegram updates
  GET  /health         — Health check (JSON)
  GET  /metrics        — Prometheus text metrics
  GET  /               — same as /health
"""

import asyncio
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from redis.asyncio import Redis
from loguru import logger

from bot.config import settings
from bot.core.logging import setup_logging
from bot.core.metrics import metrics, metrics_handler
from bot.core.queue import DeleteQueue
from bot.core.errors import ErrorHandlerMiddleware
from bot.core.shutdown import graceful_shutdown
from bot.handlers import main_router
from bot.middlewares import DatabaseMiddleware, ThrottlingMiddleware
from bot.middlewares.access_check import AccessCheckMiddleware
from bot.scheduler.tasks import setup_scheduler
from bot.cache.redis_cache import AccessCache
from bot.workers import DeleteWorkerPool


async def run_migrations() -> None:
    logger.info("Running database migrations...")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "alembic", "upgrade", "head",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            logger.info("Migrations applied successfully")
            if stdout:
                logger.debug(stdout.decode())
        else:
            logger.error(f"Migration failed:\n{stderr.decode()}")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Migration error: {e}")
        sys.exit(1)


async def wait_for_postgres(max_retries: int = 30) -> None:
    import asyncpg
    logger.info("Waiting for PostgreSQL...")
    for i in range(max_retries):
        try:
            conn = await asyncpg.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                database=settings.POSTGRES_DB,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
            )
            await conn.close()
            logger.info("PostgreSQL is ready")
            return
        except Exception:
            if i < max_retries - 1:
                logger.debug(f"PG not ready, retry {i+1}/{max_retries}...")
                await asyncio.sleep(2)
    logger.error("PostgreSQL unavailable after retries")
    sys.exit(1)


async def wait_for_redis(redis: Redis, max_retries: int = 15) -> None:
    logger.info("Waiting for Redis...")
    for i in range(max_retries):
        try:
            await redis.ping()
            logger.info("Redis is ready")
            return
        except Exception:
            if i < max_retries - 1:
                await asyncio.sleep(1)
    logger.error("Redis unavailable after retries")
    sys.exit(1)


async def webhook_recovery_task(bot: Bot, dp: Dispatcher) -> None:
    """Periodically verify webhook is set; re-register if dropped."""
    while True:
        try:
            await asyncio.sleep(300)  # check every 5 min
            info = await bot.get_webhook_info()
            if info.url != settings.webhook_url:
                logger.warning(f"Webhook mismatch! Expected {settings.webhook_url}, got {info.url}. Re-registering...")
                await bot.set_webhook(
                    url=settings.webhook_url,
                    secret_token=settings.WEBHOOK_SECRET,
                    allowed_updates=dp.resolve_used_update_types(),
                    drop_pending_updates=False,
                )
                logger.info("Webhook re-registered")
            elif info.last_error_date:
                logger.warning(f"Webhook has errors: {info.last_error_message}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Webhook recovery error: {e}")


async def on_startup(app: web.Application) -> None:
    bot: Bot = app["bot"]
    dp: Dispatcher = app["dp"]
    redis: Redis = app["redis"]
    cache: AccessCache = app["cache"]
    delete_queue: DeleteQueue = app["delete_queue"]

    logger.info("Bot starting up...")

    await wait_for_postgres()
    await wait_for_redis(redis)

    if settings.AUTO_MIGRATE:
        await run_migrations()

    from bot.database.session import async_session_factory
    from bot.services.access_service import AccessService
    async with async_session_factory() as session:
        access_svc = AccessService(session, cache)
        await access_svc.warm_all_groups()
        await session.commit()
    logger.info("Access cache warmed for all active groups")

    await bot.set_webhook(
        url=settings.webhook_url,
        secret_token=settings.WEBHOOK_SECRET,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )
    logger.info(f"Webhook set: {settings.webhook_url}")

    worker_pool = DeleteWorkerPool(bot=bot, queue=delete_queue, num_workers=settings.DELETE_WORKERS)
    worker_pool.start()
    app["worker_pool"] = worker_pool
    app["delete_queue"] = delete_queue
    logger.info(f"Delete worker pool started ({settings.DELETE_WORKERS} workers)")

    scheduler = setup_scheduler(bot, cache)
    scheduler.start()
    app["scheduler"] = scheduler
    logger.info("APScheduler started")

    recovery_task = asyncio.create_task(webhook_recovery_task(bot, dp), name="webhook_recovery")
    app["recovery_task"] = recovery_task

    graceful_shutdown.setup_signals()
    graceful_shutdown.register(lambda: on_shutdown_manual(app))

    me = await bot.get_me()
    logger.info(f"Bot ready: @{me.username} (ID={me.id})")


async def on_shutdown_manual(app: web.Application) -> None:
    await _shutdown_app(app)


async def on_shutdown(app: web.Application) -> None:
    await _shutdown_app(app)


async def _shutdown_app(app: web.Application) -> None:
    logger.info("Shutting down...")

    if "recovery_task" in app:
        app["recovery_task"].cancel()
        try:
            await app["recovery_task"]
        except asyncio.CancelledError:
            pass

    if "scheduler" in app and app["scheduler"].running:
        app["scheduler"].shutdown(wait=False)
        logger.info("Scheduler stopped")

    if "worker_pool" in app:
        await app["worker_pool"].stop(timeout=10.0)

    bot: Bot = app["bot"]
    redis: Redis = app["redis"]

    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass

    from bot.database.session import dispose_engine
    await dispose_engine()

    await bot.session.close()
    await redis.aclose()
    logger.info("Shutdown complete")


async def health_check(request: web.Request) -> web.Response:
    redis: Redis = request.app["redis"]
    delete_queue: DeleteQueue = request.app.get("delete_queue")

    try:
        redis_ok = await redis.ping()
    except Exception:
        redis_ok = False

    queue_depth = 0
    if delete_queue:
        try:
            queue_depth = await delete_queue.queue_size()
        except Exception:
            pass

    status = "ok" if redis_ok else "degraded"
    return web.json_response(
        {
            "status": status,
            "bot": settings.BOT_USERNAME,
            "redis": "ok" if redis_ok else "error",
            "delete_queue_depth": queue_depth,
        },
        status=200 if status == "ok" else 503,
    )


def create_app() -> web.Application:
    setup_logging()

    redis = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD or None,
        decode_responses=False,
        socket_keepalive=True,
        socket_connect_timeout=5,
        retry_on_timeout=True,
        max_connections=100,
    )
    cache = AccessCache(redis)
    delete_queue = DeleteQueue(redis)

    storage = RedisStorage(redis=redis, key_builder=None)
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=storage)
    dp.include_router(main_router)

    access_middleware = AccessCheckMiddleware(
        access_cache=cache,
        delete_queue=delete_queue,
    )

    dp.update.outer_middleware(ErrorHandlerMiddleware())
    dp.update.outer_middleware(DatabaseMiddleware())
    dp.message.outer_middleware(access_middleware)
    dp.message.middleware(ThrottlingMiddleware(redis=redis, rate=settings.THROTTLE_RATE))
    dp.callback_query.middleware(ThrottlingMiddleware(redis=redis, rate=0.3))

    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp
    app["redis"] = redis
    app["cache"] = cache
    app["delete_queue"] = delete_queue

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    app.router.add_get("/health", health_check)
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/", health_check)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=settings.WEBHOOK_SECRET,
    ).register(app, path=settings.WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    dp["access_cache"] = cache
    dp["delete_queue"] = delete_queue
    dp["bot"] = bot

    return app


def main():
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        logger.info("Using uvloop event loop")
    except ImportError:
        pass

    app = create_app()
    web.run_app(
        app,
        host=settings.WEB_SERVER_HOST,
        port=settings.WEB_SERVER_PORT,
        access_log=None,
        shutdown_timeout=30,
    )


if __name__ == "__main__":
    main()
