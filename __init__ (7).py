"""Referral system handler."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.referral_service import ReferralService
from bot.services.access_service import AccessService
from bot.cache.redis_cache import AccessCache
from bot.config import settings

router = Router()


@router.message(Command("referral"))
async def cmd_referral(message: Message, session: AsyncSession, access_cache: AccessCache):
    access_svc = AccessService(session, access_cache)
    ref_svc = ReferralService(session, access_svc)
    stats = await ref_svc.get_referral_stats(message.from_user.id)

    bot_username = settings.BOT_USERNAME.lstrip("@")
    ref_link = f"https://t.me/{bot_username}?start=ref_{stats['code']}"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))

    text = (
        f"🎁 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей и получайте бонусные дни доступа!\n\n"
        f"<b>Ваш код:</b> <code>{stats['code']}</code>\n"
        f"<b>Ваша ссылка:</b>\n{ref_link}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"  Приглашено: {stats['total_referrals']} чел.\n"
        f"  Бонус получен: {stats['total_bonus_days']} дн.\n\n"
        f"<i>За каждого платящего реферала вы получаете {settings.REFERRAL_BONUS_DAYS} дней бонусного доступа.</i>"
    )
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery, session: AsyncSession, access_cache: AccessCache):
    access_svc = AccessService(session, access_cache)
    ref_svc = ReferralService(session, access_svc)
    stats = await ref_svc.get_referral_stats(callback.from_user.id)

    bot_username = settings.BOT_USERNAME.lstrip("@")
    ref_link = f"https://t.me/{bot_username}?start=ref_{stats['code']}"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))

    text = (
        f"🎁 <b>Реферальная программа</b>\n\n"
        f"<b>Ваш код:</b> <code>{stats['code']}</code>\n"
        f"<b>Ссылка:</b> {ref_link}\n\n"
        f"Приглашено: {stats['total_referrals']} чел.\n"
        f"Бонус: {stats['total_bonus_days']} дн.\n\n"
        f"<i>+{settings.REFERRAL_BONUS_DAYS} дней за каждого платящего реферала</i>"
    )
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()
