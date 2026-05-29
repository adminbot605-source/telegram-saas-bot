from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from redis.asyncio import Redis
from loguru import logger


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, redis: Redis, rate: float = 0.5):
        self.redis = redis
        self.rate = rate
        self.prefix = "throttle"

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        key = f"{self.prefix}:{user.id}"
        result = await self.redis.set(key, "1", px=int(self.rate * 1000), nx=True)

        if not result:
            if isinstance(event, Message):
                await event.answer("⏳ Подождите немного перед следующим запросом.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⏳ Подождите немного.", show_alert=False)
            return

        return await handler(event, data)
