from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession
from bot.database.session import async_session_factory
from bot.repositories import (
    UserRepository, GroupRepository, AccessRepository,
    PaymentRepository, TariffRepository,
)
from loguru import logger


class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with async_session_factory() as session:
            data["session"] = session
            data["user_repo"] = UserRepository(session)
            data["group_repo"] = GroupRepository(session)
            data["access_repo"] = AccessRepository(session)
            data["payment_repo"] = PaymentRepository(session)
            data["tariff_repo"] = TariffRepository(session)

            # Inject shared objects from dispatcher context
            dp = data.get("dispatcher") or data.get("dp")
            if dp:
                if "access_cache" in dp.workflow_data:
                    data.setdefault("access_cache", dp["access_cache"])
                if "delete_queue" in dp.workflow_data:
                    data.setdefault("delete_queue", dp["delete_queue"])

            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                logger.error(f"DB middleware error: {e}")
                raise
            finally:
                await session.close()
