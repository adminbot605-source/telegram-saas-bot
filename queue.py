"""Centralized error handling and reporting."""

import traceback
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramBadRequest
from loguru import logger

from bot.core.metrics import metrics


class ErrorHandlerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramForbiddenError as e:
            user_id = _extract_user_id(event)
            logger.warning(f"Bot forbidden by user {user_id}: {e}")
        except TelegramBadRequest as e:
            msg = str(e).lower()
            if any(s in msg for s in ("message to delete not found", "message can't be deleted", "chat not found")):
                pass
            else:
                logger.error(f"TelegramBadRequest in handler: {e}")
                metrics.errors_total.inc(handler="telegram_bad_request")
        except TelegramAPIError as e:
            logger.error(f"TelegramAPIError in handler: {e}")
            metrics.errors_total.inc(handler="telegram_api")
        except Exception as e:
            handler_name = handler.__name__ if hasattr(handler, "__name__") else str(type(handler))
            logger.exception(f"Unhandled exception in {handler_name}: {e}")
            metrics.errors_total.inc(handler=handler_name)

            if isinstance(event, (Message, CallbackQuery)):
                try:
                    user = getattr(event, "from_user", None)
                    if user and isinstance(event, CallbackQuery):
                        await event.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
                    elif isinstance(event, Message) and event.chat.type == "private":
                        await event.answer("❌ Произошла внутренняя ошибка. Попробуйте позже.")
                except Exception:
                    pass


def _extract_user_id(event: TelegramObject) -> int:
    for attr in ("from_user", "message"):
        obj = getattr(event, attr, None)
        if obj:
            user = getattr(obj, "from_user", None) or obj
            if hasattr(user, "id"):
                return user.id
    return 0
