from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from bot.repositories.user_repo import UserRepository
from bot.services.referral_service import ReferralService
from bot.services.access_service import AccessService
from bot.cache.redis_cache import AccessCache
from bot.keyboards.inline import InlineKeyboards
from bot.config import settings

router = Router()


def main_menu_text(first_name: str, is_new: bool) -> str:
    if is_new:
        return (
            f"👋 Добро пожаловать, <b>{first_name}</b>!\n\n"
            f"Я — SaaS-бот для управления доступом в Telegram-группах и каналах.\n\n"
            f"<b>Возможности:</b>\n"
            f"• 🔒 Контроль доступа — только платящие пишут\n"
            f"• 💳 Приём оплаты с проверкой чека\n"
            f"• 📦 Гибкие тарифы (срочные и бессрочные)\n"
            f"• 🎁 Реферальная программа\n"
            f"• 📊 Статистика и аналитика\n"
            f"• ⚡ Redis-кэш для мгновенного удаления сообщений\n\n"
            f"Используйте меню ниже:"
        )
    return f"👋 С возвращением, <b>{first_name}</b>!\n\nВыберите действие:"


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    access_cache: AccessCache,
    user_repo: UserRepository,
):
    args = message.text.split() if message.text else []
    ref_code = None
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1][4:]

    user, is_new = await user_repo.get_or_create(message.from_user)

    if is_new and ref_code and ref_code != user.referral_code:
        access_svc = AccessService(session, access_cache)
        ref_svc = ReferralService(session, access_svc)
        applied = await ref_svc.apply_referral(user.id, ref_code)
        if applied:
            logger.info(f"Referral applied for new user {user.id} via code {ref_code}")

    text = main_menu_text(message.from_user.first_name, is_new)
    await message.answer(text, reply_markup=InlineKeyboards.main_menu(), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "❓ <b>Справка</b>\n\n"
        "/start — Главное меню\n"
        "/owner — Панель владельца группы\n"
        "/access — Мои активные доступы\n"
        "/referral — Реферальная программа\n"
        f"/creator — Панель создателя (только для {settings.CREATOR_USER_ID})\n\n"
        f"<b>Как получить доступ в группу:</b>\n"
        f"1. Выберите группу в меню\n"
        f"2. Ознакомьтесь с тарифами\n"
        f"3. Оплатите и загрузите чек\n"
        f"4. Дождитесь подтверждения\n\n"
        f"<b>Как подключить бота к группе:</b>\n"
        f"1. Добавьте {settings.BOT_USERNAME} в группу\n"
        f"2. Назначьте его администратором\n"
        f"3. Включите контроль доступа в /owner"
    )
    await message.answer(help_text, parse_mode="HTML", reply_markup=InlineKeyboards.back_to_menu())


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    text = f"👋 <b>Главное меню</b>\n\nВыберите действие:"
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboards.main_menu(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=InlineKeyboards.main_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    help_text = (
        "❓ <b>Справка по боту</b>\n\n"
        "🔒 <b>Контроль доступа</b>\n"
        "Бот мгновенно удаляет сообщения от пользователей без доступа.\n\n"
        "💳 <b>Оплата</b>\n"
        "Отправьте скриншот квитанции — владелец группы подтвердит вручную.\n\n"
        "📦 <b>Тарифы</b>\n"
        "Каждая группа настраивает свои тарифы: срочные или бессрочные.\n\n"
        "🎁 <b>Реферальная программа</b>\n"
        f"Пригласите друга и получите +{settings.REFERRAL_BONUS_DAYS} дней бонуса."
    )
    await callback.message.edit_text(help_text, reply_markup=InlineKeyboards.back_to_menu(), parse_mode="HTML")
    await callback.answer()
