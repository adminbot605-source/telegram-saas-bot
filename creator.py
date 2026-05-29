"""
Async SQLAlchemy session factory with production-grade connection pooling.

Pool settings tuned for high-load (100k+ users):
  pool_size=20        — persistent connections per process
  max_overflow=30     — burst capacity (total 50 connections max)
  pool_timeout=30     — wait time to get connection from pool
  pool_recycle=1800   — recycle every 30 min (prevents stale connections)
  pool_pre_ping=True  — validate connection before use (handles PG restarts)
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
    AsyncEngine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool
from loguru import logger

from bot.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            poolclass=AsyncAdaptedQueuePool,
            pool_size=20,
            max_overflow=30,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            echo=settings.DEBUG,
            connect_args={
                "server_settings": {
                    "application_name": "saas_bot",
                    "statement_timeout": "25000",
                },
            },
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async_session_factory = get_session_factory()


async def get_session() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Session error: {e}")
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("Database engine disposed")
