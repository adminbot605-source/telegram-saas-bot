from aiogram import Router
from .start import router as start_router
from .owner import router as owner_router
from .creator import router as creator_router
from .payments import router as payments_router
from .access import router as access_router
from .referral import router as referral_router
from .chat_events import router as chat_events_router
from .callbacks import router as callbacks_router
from .qr import router as qr_router

main_router = Router()
main_router.include_router(start_router)
main_router.include_router(qr_router)
main_router.include_router(owner_router)
main_router.include_router(creator_router)
main_router.include_router(payments_router)
main_router.include_router(access_router)
main_router.include_router(referral_router)
main_router.include_router(chat_events_router)
main_router.include_router(callbacks_router)

__all__ = ["main_router"]
