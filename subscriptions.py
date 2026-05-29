"""Creator panel — superadmin управление всей системой."""

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from bot.repositories import UserRepository, GroupRepository, AccessRepository
from bot.repositories.payment_repo import PaymentRepository
from bot.services.access_service import AccessService
from bot.services.stats_service import StatsService
from bot.services.notification_service import NotificationService
from bot.cache.redis_cache import AccessCache
from bot.keyboards.reply import ReplyKeyboards
from bot.utils.helpers import format_date
from bot.config import settings

router = Router()


class CreatorStates(StatesGroup):
    broadcast_text = State()
    grant_user_id = State()
    grant_group_id = State()
    grant_duration = State()
    revoke_user_id = State()
    revoke_group_id = State()
    reject_reason = State()
    find_user = State()


def is_creator(user_id: int) -> bool:
    return user_id == settings.CREATOR_USER_ID


def creator_only(func):
    async def wrapper(event, *args, **kwargs):
        uid = None
        if isinstance(event, Message):
            uid = event.from_user.id
        elif isinstance(event, CallbackQuery):
            uid = event.from_user.id
        if not is_creator(uid):
            if isinstance(event, CallbackQuery):
                await event.answer("❌ Только для создателя.", show_alert=True)
            return
        return await func(event, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


def build_creator_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📊 Глобальная статистика", callback_data="cr:stats"),
    )
    b.row(
        InlineKeyboardButton(text="👥 Все пользователи", callback_data="cr:users"),
        InlineKeyboardButton(text="📋 Все группы", callback_data="cr:groups"),
    )
    b.row(
        InlineKeyboardButton(text="💳 Все заявки", callback_data="cr:payments"),
        InlineKeyboardButton(text="🔑 Выдать доступ", callback_data="cr:grant"),
    )
    b.row(
        InlineKeyboardButton(text="🚫 Отозвать доступ", callback_data="cr:revoke"),
        InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="cr:find"),
    )
    b.row(
        InlineKeyboardButton(text="📢 Глобальная рассылка", callback_data="cr:broadcast"),
        InlineKeyboardButton(text="⚡ Очистить кэш", callback_data="cr:clear_cache"),
    )
    b.row(InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"))
    return b


@router.message(Command("creator"))
async def cmd_creator(message: Message):
    if not is_creator(message.from_user.id):
        return
    await message.answer(
        "🔐 <b>Панель создателя</b>\n\nВыберите действие:",
        reply_markup=build_creator_kb().as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cr:stats")
async def cb_creator_stats(callback: CallbackQuery, session: AsyncSession, access_cache: AccessCache):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    stats_svc = StatsService(session, access_cache)
    stats = await stats_svc.get_global_stats()
    total_deleted = await stats_svc.get_total_deleted()
    u = stats["users"]
    g = stats["groups"]
    p = stats["payments"]
    text = (
        "📊 <b>Глобальная статистика</b>\n\n"
        f"<b>👥 Пользователи:</b>\n"
        f"  Всего: <b>{u['total']}</b>\n"
        f"  Сегодня: <b>{u['today']}</b>\n"
        f"  Заблокированных: <b>{u['blocked']}</b>\n\n"
        f"<b>📋 Группы:</b>\n"
        f"  Всего: <b>{g['total']}</b>\n"
        f"  Активных: <b>{g['active']}</b>\n"
        f"  С контролем: <b>{g['access_controlled']}</b>\n\n"
        f"<b>💳 Платежи:</b>\n"
        f"  Одобрено: <b>{p['approved_count']}</b>\n"
        f"  На проверке: <b>{p['pending_count']}</b>\n"
        f"  Выручка: <b>{p['total_revenue']:.0f}₽</b>\n\n"
        f"🗑 Удалено сообщений всего: <b>{total_deleted}</b>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Обновить", callback_data="cr:stats"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="cr:panel"))
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "cr:panel")
async def cb_creator_panel(callback: CallbackQuery):
    if not is_creator(callback.from_user.id): return
    await callback.message.edit_text(
        "🔐 <b>Панель создателя</b>",
        reply_markup=build_creator_kb().as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cr:payments")
async def cb_creator_payments(callback: CallbackQuery, session: AsyncSession):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    payment_repo = PaymentRepository(session)
    pending = await payment_repo.get_pending_all()
    b = InlineKeyboardBuilder()
    for p in pending[:15]:
        b.row(InlineKeyboardButton(
            text=f"#{p.id} | u:{p.user_id} | {int(p.amount)}₽",
            callback_data=f"pay_view:{p.id}",
        ))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="cr:panel"))
    text = f"💳 <b>Все заявки на оплату</b>\n\nНа проверке: {len(pending)}"
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "cr:grant")
async def cb_creator_grant(callback: CallbackQuery, state: FSMContext):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    await state.set_state(CreatorStates.grant_user_id)
    await callback.message.answer("👤 Введите Telegram ID пользователя:", reply_markup=ReplyKeyboards.cancel())
    await callback.answer()


@router.message(CreatorStates.grant_user_id, F.text != "❌ Отмена")
async def handle_creator_grant_uid(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный ID."); return
    await state.update_data(target_uid=uid)
    await state.set_state(CreatorStates.grant_group_id)
    await message.answer("📋 Введите ID группы (числовой chat_id):")


@router.message(CreatorStates.grant_group_id, F.text != "❌ Отмена")
async def handle_creator_grant_gid(message: Message, state: FSMContext):
    try:
        gid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный ID."); return
    await state.update_data(target_gid=gid)
    await state.set_state(CreatorStates.grant_duration)
    b = InlineKeyboardBuilder()
    for label, days in [("7 дней", 7), ("30 дней", 30), ("90 дней", 90), ("365 дней", 365), ("Бессрочно", 0)]:
        b.row(InlineKeyboardButton(text=label, callback_data=f"cr_grant_dur:{days}"))
    await message.answer("📅 Выберите срок:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("cr_grant_dur:"))
async def cb_creator_grant_dur(callback: CallbackQuery, state: FSMContext, session: AsyncSession, access_cache: AccessCache, group_repo: GroupRepository):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    days = int(callback.data.split(":")[1])
    data = await state.get_data()
    await state.clear()
    uid = data.get("target_uid")
    gid = data.get("target_gid")

    group = await group_repo.get_by_id(gid)
    group_title = group.title if group else str(gid)

    access_svc = AccessService(session, access_cache)
    is_lifetime = (days == 0)
    access = await access_svc.grant_access(
        user_id=uid, group_id=gid,
        tariff_id=None, duration_days=None if is_lifetime else days,
        is_lifetime=is_lifetime, granted_by=callback.from_user.id,
        note="Выдан создателем вручную",
    )
    dur = "Бессрочно" if is_lifetime else f"{days} дн."
    await callback.message.edit_text(
        f"✅ Доступ выдан:\nПользователь: <code>{uid}</code>\nГруппа: {group_title}\nСрок: {dur}",
        parse_mode="HTML", reply_markup=build_creator_kb().as_markup(),
    )
    try:
        await callback.bot.send_message(uid, f"✅ Вам выдан доступ в группу <b>{group_title}</b>. Срок: {dur}", parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "cr:revoke")
async def cb_creator_revoke(callback: CallbackQuery, state: FSMContext):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    await state.set_state(CreatorStates.revoke_user_id)
    await callback.message.answer("👤 Введите Telegram ID:", reply_markup=ReplyKeyboards.cancel())
    await callback.answer()


@router.message(CreatorStates.revoke_user_id, F.text != "❌ Отмена")
async def handle_creator_revoke_uid(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный ID."); return
    await state.update_data(revoke_uid=uid)
    await state.set_state(CreatorStates.revoke_group_id)
    await message.answer("📋 Введите ID группы:")


@router.message(CreatorStates.revoke_group_id, F.text != "❌ Отмена")
async def handle_creator_revoke_gid(message: Message, state: FSMContext, session: AsyncSession, access_cache: AccessCache):
    try:
        gid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный ID."); return
    data = await state.get_data()
    await state.clear()
    uid = data.get("revoke_uid")
    access_svc = AccessService(session, access_cache)
    revoked = await access_svc.revoke_access(uid, gid)
    if revoked:
        await message.answer(f"✅ Доступ отозван у <code>{uid}</code> в группе {gid}.", reply_markup=ReplyKeyboards.remove(), parse_mode="HTML")
    else:
        await message.answer(f"⚠️ Активный доступ не найден.", reply_markup=ReplyKeyboards.remove())


@router.callback_query(F.data == "cr:broadcast")
async def cb_creator_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    await state.set_state(CreatorStates.broadcast_text)
    await callback.message.answer("📢 Введите текст глобальной рассылки:", reply_markup=ReplyKeyboards.cancel())
    await callback.answer()


@router.message(CreatorStates.broadcast_text, F.text != "❌ Отмена")
async def handle_creator_broadcast(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    if not is_creator(message.from_user.id): return
    await state.clear()
    user_repo = UserRepository(session)
    user_ids = await user_repo.get_all_ids()
    await message.answer(f"📢 Рассылка {len(user_ids)} пользователям...", reply_markup=ReplyKeyboards.remove())
    notif = NotificationService(bot)
    sent, failed = await notif.broadcast(bot, user_ids, message.text)
    await message.answer(f"✅ Готово!\nОтправлено: {sent}\nОшибок: {failed}", reply_markup=build_creator_kb().as_markup())


@router.callback_query(F.data == "cr:clear_cache")
async def cb_clear_cache(callback: CallbackQuery, session: AsyncSession, access_cache: AccessCache):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    group_repo = GroupRepository(session)
    groups = await group_repo.get_all_access_controlled()
    for g in groups:
        await access_cache.invalidate_group(g.id)
    await callback.answer(f"✅ Кэш сброшен для {len(groups)} групп", show_alert=True)


@router.callback_query(F.data == "cr:find")
async def cb_creator_find(callback: CallbackQuery, state: FSMContext):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    await state.set_state(CreatorStates.find_user)
    await callback.message.answer("🔍 Введите ID или @username пользователя:", reply_markup=ReplyKeyboards.cancel())
    await callback.answer()


@router.message(CreatorStates.find_user, F.text != "❌ Отмена")
async def handle_creator_find(message: Message, state: FSMContext, session: AsyncSession, access_cache: AccessCache):
    if not is_creator(message.from_user.id): return
    await state.clear()
    text = message.text.strip().lstrip("@")
    user_repo = UserRepository(session)
    access_repo = AccessRepository(session)
    from sqlalchemy import select
    from bot.models.user import User

    user = None
    try:
        uid = int(text)
        user = await user_repo.get_by_id(uid)
    except ValueError:
        result = await session.execute(select(User).where(User.username == text))
        user = result.scalar_one_or_none()

    if not user:
        await message.answer("❌ Пользователь не найден.", reply_markup=ReplyKeyboards.remove()); return

    accesses = await access_repo.get_user_accesses(user.id)
    access_lines = ""
    for acc in accesses:
        exp = "♾️ Бессрочно" if acc.is_lifetime else format_date(acc.expires_at)
        access_lines += f"  • Группа {acc.group_id}: {exp}\n"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="cr:panel"))

    await message.answer(
        f"🔍 <b>Пользователь найден</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Имя: {user.full_name}\n"
        f"Username: @{user.username or '—'}\n"
        f"Реферальный код: <code>{user.referral_code or '—'}</code>\n\n"
        f"<b>Активные доступы ({len(accesses)}):</b>\n{access_lines or '  Нет'}",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )


@router.callback_query(F.data == "cr:users")
async def cb_creator_users(callback: CallbackQuery, session: AsyncSession):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    user_repo = UserRepository(session)
    stats = await user_repo.get_stats()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="cr:panel"))
    await callback.message.edit_text(
        f"👥 <b>Пользователи</b>\n\nВсего: {stats['total']}\nСегодня: {stats['today']}\nЗаблокированных: {stats['blocked']}",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cr:groups")
async def cb_creator_groups(callback: CallbackQuery, session: AsyncSession):
    if not is_creator(callback.from_user.id):
        await callback.answer("❌", show_alert=True); return
    group_repo = GroupRepository(session)
    stats = await group_repo.get_stats()
    from sqlalchemy import select
    from bot.models.group import Group
    result = await session.execute(select(Group).where(Group.is_active == True).limit(20))
    groups = result.scalars().all()
    lines = "\n".join(f"• <b>{g.title[:30]}</b> | {g.id}" for g in groups)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="cr:panel"))
    await callback.message.edit_text(
        f"📋 <b>Все группы</b>\n\nВсего: {stats['total']} | Активных: {stats['active']} | С контролем: {stats['access_controlled']}\n\n{lines}",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()
