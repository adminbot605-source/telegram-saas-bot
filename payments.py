"""User access flow: view tariffs, submit payment requests."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from bot.repositories import GroupRepository
from bot.repositories.access_repo import AccessRepository
from bot.repositories.tariff_repo import TariffRepository
from bot.services.access_service import AccessService
from bot.services.tariff_service import TariffService
from bot.cache.redis_cache import AccessCache
from bot.utils.helpers import format_date, days_until

router = Router()


@router.message(Command("access"))
async def cmd_access(message: Message, session: AsyncSession, access_cache: AccessCache):
    access_repo = AccessRepository(session)
    accesses = await access_repo.get_user_accesses(message.from_user.id)

    if not accesses:
        await message.answer(
            "🔑 <b>Мои доступы</b>\n\nУ вас нет активных доступов.",
            parse_mode="HTML",
        )
        return

    text = "🔑 <b>Мои активные доступы:</b>\n\n"
    for acc in accesses:
        if acc.is_lifetime:
            exp = "♾️ Бессрочно"
        elif acc.expires_at:
            d = days_until(acc.expires_at)
            exp = f"📅 до {format_date(acc.expires_at)} ({d} дн.)"
        else:
            exp = "—"
        text += f"📋 Группа: <code>{acc.group_id}</code>\n   {exp}\n\n"

    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("group_access:"))
async def cb_group_access(callback: CallbackQuery, session: AsyncSession, access_cache: AccessCache):
    group_id = int(callback.data.split(":")[1])
    group_repo = GroupRepository(session)
    group = await group_repo.get_by_id(group_id)
    if not group:
        await callback.answer("❌ Группа не найдена.", show_alert=True); return

    tariff_repo = TariffRepository(session)
    tariffs = await tariff_repo.get_group_tariffs(group_id)
    access_svc = AccessService(session, access_cache)
    has_access = await access_svc.is_authorized(callback.from_user.id, group_id)

    b = InlineKeyboardBuilder()
    if has_access:
        access_repo = AccessRepository(session)
        acc = await access_repo.get_user_group_access(callback.from_user.id, group_id)
        if acc and acc.is_lifetime:
            exp_text = "♾️ Бессрочный доступ"
        elif acc and acc.expires_at:
            exp_text = f"📅 Доступ до: {format_date(acc.expires_at)}"
        else:
            exp_text = "✅ Доступ активен"
        text = f"✅ <b>Доступ активен</b>\n\n📋 {group.title}\n{exp_text}"
    else:
        text = f"🔒 <b>Доступ закрыт</b>\n\n📋 {group.title}\n\nВыберите тариф для получения доступа:"
        for t in tariffs:
            details = f" ({group.payment_details[:30]}...)" if group.payment_details else ""
            b.row(InlineKeyboardButton(
                text=f"📦 {t.name} — {t.price_label} / {t.duration_label}",
                callback_data=f"buy:{group_id}:{t.id}",
            ))

    b.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("tariff_info:"))
async def cb_tariff_info(callback: CallbackQuery, session: AsyncSession):
    tariff_id = int(callback.data.split(":")[1])
    tariff_repo = TariffRepository(session)
    tariff = await tariff_repo.get_active(tariff_id)
    if not tariff:
        await callback.answer("❌ Тариф не найден.", show_alert=True); return

    b = InlineKeyboardBuilder()
    if tariff.payment_details:
        b.row(InlineKeyboardButton(text="💳 Оплатить и отправить чек", callback_data=f"buy:{tariff.group_id}:{tariff.id}"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"group_access:{tariff.group_id}"))

    text = (
        f"📦 <b>{tariff.name}</b>\n\n"
        f"💰 Стоимость: <b>{tariff.price_label}</b>\n"
        f"⏱ Срок: <b>{tariff.duration_label}</b>\n"
    )
    if tariff.description:
        text += f"\n{tariff.description}\n"
    if tariff.payment_details:
        text += f"\n<b>Реквизиты для оплаты:</b>\n<code>{tariff.payment_details}</code>"

    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()
