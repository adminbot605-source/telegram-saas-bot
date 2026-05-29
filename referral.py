"""Fallback callback handler — always last in router chain."""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from bot.repositories import GroupRepository
from bot.repositories.access_repo import AccessRepository
from bot.cache.redis_cache import AccessCache
from bot.keyboards.inline import InlineKeyboards
from bot.utils.helpers import format_date, days_until

router = Router()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("❌ Отменено")


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "owner_menu")
async def cb_owner_menu(callback: CallbackQuery, group_repo: GroupRepository):
    groups = await group_repo.get_by_owner(callback.from_user.id)
    if not groups:
        await callback.answer("У вас нет зарегистрированных групп.", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for g in groups:
        icon = "🟢" if g.access_control_enabled else "⚪"
        b.row(InlineKeyboardButton(text=f"{icon} {g.title[:35]}", callback_data=f"own:panel:{g.id}"))
    b.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    try:
        await callback.message.edit_text(
            "🔧 <b>Панель владельца</b>\n\nВыберите группу:",
            reply_markup=b.as_markup(), parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            "🔧 <b>Панель владельца</b>\n\nВыберите группу:",
            reply_markup=b.as_markup(), parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "my_accesses")
async def cb_my_accesses(callback: CallbackQuery, session: AsyncSession, access_cache: AccessCache):
    access_repo = AccessRepository(session)
    accesses = await access_repo.get_user_accesses(callback.from_user.id)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    if not accesses:
        await callback.message.edit_text(
            "🔑 <b>Мои доступы</b>\n\nУ вас нет активных доступов.",
            reply_markup=b.as_markup(), parse_mode="HTML",
        )
        await callback.answer()
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
        b.row(InlineKeyboardButton(
            text=f"📋 {acc.group_id}",
            callback_data=f"group_access:{acc.group_id}",
        ))
    b.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query()
async def cb_unknown(callback: CallbackQuery):
    logger.warning(f"Unknown callback: {callback.data!r} from {callback.from_user.id}")
    await callback.answer("⚠️ Неизвестная команда.", show_alert=False)
