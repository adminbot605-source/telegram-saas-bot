import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.models.base import Base
from bot.models.user import User
from bot.models.group import Group
from bot.models.subscription import Subscription
from bot.models.scheduled_post import ScheduledPost
from bot.models.access import UserAccess
from bot.models.tariff import Tariff
from bot.models.payment import Payment
from bot.models.referral import Referral, ReferralCode
from bot.models.qr_code import QRCode

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "saas_bot")
    user = os.getenv("POSTGRES_USER", "botuser")
    password = os.getenv("POSTGRES_PASSWORD", "botpassword123secure")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


def run_migrations_offline() -> None:
    url = get_database_url()
    context.configure(
        url=url.replace("+asyncpg", "+psycopg2"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = get_database_url()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
