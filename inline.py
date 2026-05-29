"""Owner panel — per-group owner management."""

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from loguru import logger

from bot.repositories import GroupRepository, AccessRepository, UserRepository
from bot.repositories.tariff_repo import TariffRepository
from bot.services.access_service import AccessService
from bot.services.tariff_service import TariffService
from bot.services.stats_service import StatsService
from bot.cache.redis_cache import AccessCache
from bot.middlewares.access_check import AccessCheckMiddleware
from bot.keyboards.inline import InlineKeyboards
from bot.keyboards.reply import ReplyKeyboards
from bot.utils.helpers import format_date, parse_date_input
from bot.config import settings

router = Router()


class OwnerStates(StatesGroup):
    select_group = State()
    add_access_user_id = State()
    add_access_duration = State()
    revoke_access_user_id = State()
    create_tariff_name = State()
    create_tariff_price = State()
    create_tariff_duration = State()
    create_tariff_details = State()
    set_welcome_text = State()
    extend_access_user_id = State()
    extend_access_days = State()
    change_expiry_user_id = State()
    change_expiry_date = State()
    broadcast_text = State()


def is_group_owner(user_id: int, group) -> bool:
    return group.owner_id == user_id or user_id == settings.CREATOR_USER_ID


async def get_owner_group(group_id: int, user_id: int, group_repo: GroupRepository):
    group = await group_repo.get_by_id(group_id)
    if not group or not is_group_owner(user_id, group):
        return None
    return group


def build_owner_panel_kb(group_id: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="👥 Участники", callback_data=f"own:members:{group_id}"),
        InlineKeyboardButton(text="📊 Статистика", callback_data=f"own:stats:{group_id}"),
    )
    b.row(
        InlineKeyboardButton(text="➕ Выдать доступ", callback_data=f"own:grant:{group_id}"),
        InlineKeyboardButton(text="➖ Отозвать доступ", callback_data=f"own:revoke:{group_id}"),
    )
    b.row(
        InlineKeyboardButton(text="📦 Тарифы", callback_data=f"own:tariffs:{group_id}"),
        InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"own:settings:{group_id}"),
    )
    b.row(
        InlineKeyboardButton(text="💳 Заявки", callback_data=f"own:payments:{group_id}"),
        InlineKeyboardButton(text="📢 Рассылка", callback_data=f"own:broadcast:{group_id}"),
    )
    b.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return b


@router.message(Command("owner"))
async def cmd_owner(message: Message, group_repo: GroupRepository):
    groups = await group_repo.get_by_owner(message.from_user.id)
    if not groups:
        await message.answer("❌ У вас нет зарегистрированных групп.")
        return
    b = InlineKeyboardBuilder()
    for g in groups:
        icon = "🟢" if g.access_control_enabled else "⚪"
        b.row(InlineKeyboardButton(text=f"{icon} {g.title[:35]}", callback_data=f"own:panel:{g.id}"))
    b.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    await message.answer("🔧 <b>Панель владельца</b>\n\nВыберите группу:", reply_markup=b.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("own:panel:"))
async def cb_owner_panel(callback: CallbackQuery, group_repo: GroupRepository):
    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌ Нет доступа.", show_alert=True)
        return
    ctrl = "🟢 Включён" if group.access_control_enabled else "⚪ Выключен"
    text = (
        f"🔧 <b>Панель: {group.title}</b>\n\n"
        f"Контроль доступа: {ctrl}\n"
        f"Участников: {group.member_count}\n"
    )
    await callback.message.edit_text(text, reply_markup=build_owner_panel_kb(group_id).as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("own:settings:"))
async def cb_owner_settings(callback: CallbackQuery, group_repo: GroupRepository, session: AsyncSession):
    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌ Нет доступа.", show_alert=True)
        return

    b = InlineKeyboardBuilder()
    ctrl_label = "🟢 Контроль: ВКЛ" if group.access_control_enabled else "⚪ Контроль: ВЫКЛ"
    b.row(InlineKeyboardButton(text=ctrl_label, callback_data=f"own:toggle_ctrl:{group_id}"))
    welcome_label = "✅ Приветствие: ВКЛ" if group.welcome_enabled else "❌ Приветствие: ВЫКЛ"
    b.row(InlineKeyboardButton(text=welcome_label, callback_data=f"own:toggle_welcome:{group_id}"))
    spam_label = "✅ Антиспам: ВКЛ" if group.anti_spam_enabled else "❌ Антиспам: ВЫКЛ"
    b.row(InlineKeyboardButton(text=spam_label, callback_data=f"own:toggle_spam:{group_id}"))
    flood_label = "✅ Антифлуд: ВКЛ" if group.anti_flood_enabled else "❌ Антифлуд: ВЫКЛ"
    b.row(InlineKeyboardButton(text=flood_label, callback_data=f"own:toggle_flood:{group_id}"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"own:panel:{group_id}"))

    text = (
        f"⚙️ <b>Настройки: {group.title}</b>\n\n"
        f"Контроль доступа: {'🟢 ВКЛ' if group.access_control_enabled else '⚪ ВЫКЛ'}\n"
        f"Приветствие: {'✅ ВКЛ' if group.welcome_enabled else '❌ ВЫКЛ'}\n"
        f"Антиспам: {'✅ ВКЛ' if group.anti_spam_enabled else '❌ ВЫКЛ'}\n"
        f"Антифлуд: {'✅ ВКЛ' if group.anti_flood_enabled else '❌ ВЫКЛ'}\n"
    )
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("own:toggle_ctrl:"))
async def cb_toggle_ctrl(callback: CallbackQuery, group_repo: GroupRepository, session: AsyncSession):
    from sqlalchemy import update
    from bot.models.group import Group

    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌ Нет доступа.", show_alert=True)
        return

    new_val = not group.access_control_enabled
    await session.execute(update(Group).where(Group.id == group_id).values(access_control_enabled=new_val))
    AccessCheckMiddleware.invalidate_group_control_cache(group_id)

    status = "включён" if new_val else "выключен"
    await callback.answer(f"Контроль доступа {status}", show_alert=True)
    await cb_owner_settings(callback, group_repo, session)


@router.callback_query(F.data.startswith("own:toggle_welcome:"))
async def cb_toggle_welcome(callback: CallbackQuery, group_repo: GroupRepository, session: AsyncSession):
    from sqlalchemy import update
    from bot.models.group import Group
    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌", show_alert=True); return
    new_val = not group.welcome_enabled
    await session.execute(update(Group).where(Group.id == group_id).values(welcome_enabled=new_val))
    await callback.answer(f"Приветствие {'включено' if new_val else 'выключено'}")
    await cb_owner_settings(callback, group_repo, session)


@router.callback_query(F.data.startswith("own:toggle_spam:"))
async def cb_toggle_spam(callback: CallbackQuery, group_repo: GroupRepository, session: AsyncSession):
    from sqlalchemy import update
    from bot.models.group import Group
    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌", show_alert=True); return
    new_val = not group.anti_spam_enabled
    await session.execute(update(Group).where(Group.id == group_id).values(anti_spam_enabled=new_val))
    await callback.answer(f"Антиспам {'включён' if new_val else 'выключён'}")
    await cb_owner_settings(callback, group_repo, session)


@router.callback_query(F.data.startswith("own:toggle_flood:"))
async def cb_toggle_flood(callback: CallbackQuery, group_repo: GroupRepository, session: AsyncSession):
    from sqlalchemy import update
    from bot.models.group import Group
    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌", show_alert=True); return
    new_val = not group.anti_flood_enabled
    await session.execute(update(Group).where(Group.id == group_id).values(anti_flood_enabled=new_val))
    await callback.answer(f"Антифлуд {'включён' if new_val else 'выключён'}")
    await cb_owner_settings(callback, group_repo, session)


@router.callback_query(F.data.startswith("own:stats:"))
async def cb_owner_stats(callback: CallbackQuery, group_repo: GroupRepository, session: AsyncSession, access_cache: AccessCache):
    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌ Нет доступа.", show_alert=True); return

    stats_svc = StatsService(session, access_cache)
    stats = await stats_svc.get_group_stats(group_id)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"own:panel:{group_id}"))

    text = (
        f"📊 <b>Статистика: {group.title}</b>\n\n"
        f"👥 Активных доступов: <b>{stats['access']['total_active']}</b>\n"
        f"♾️ Бессрочных: <b>{stats['access']['lifetime']}</b>\n"
        f"📦 Оплат (итого): <b>{stats['payments']['total']}</b>\n"
        f"✅ Одобрено: <b>{stats['payments']['approved_count']}</b>\n"
        f"💰 Выручка: <b>{stats['payments']['total_revenue']:.0f}₽</b>\n"
        f"🗑 Удалено сообщений: <b>{stats['messages_deleted']}</b>\n"
        f"⚡ Кэш (пользователей): <b>{stats['cache']['cached_users']}</b>\n"
    )
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("own:grant:"))
async def cb_owner_grant(callback: CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(":")[2])
    await state.set_state(OwnerStates.add_access_user_id)
    await state.update_data(group_id=group_id)
    await callback.message.answer(
        "👤 Введите Telegram ID пользователя для выдачи доступа:",
        reply_markup=ReplyKeyboards.cancel(),
    )
    await callback.answer()


@router.message(OwnerStates.add_access_user_id, F.text != "❌ Отмена")
async def handle_grant_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный ID. Введите числовой Telegram ID.")
        return
    await state.update_data(target_user_id=user_id)
    await state.set_state(OwnerStates.add_access_duration)
    b = InlineKeyboardBuilder()
    for label, days in [("7 дней", 7), ("30 дней", 30), ("90 дней", 90), ("180 дней", 180), ("365 дней", 365), ("Бессрочно", 0)]:
        b.row(InlineKeyboardButton(text=label, callback_data=f"grant_dur:{days}"))
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    await message.answer("📅 Выберите срок доступа:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("grant_dur:"))
async def cb_grant_duration(callback: CallbackQuery, state: FSMContext, session: AsyncSession, access_cache: AccessCache, group_repo: GroupRepository):
    data = await state.get_data()
    group_id = data.get("group_id")
    target_user_id = data.get("target_user_id")
    days = int(callback.data.split(":")[1])
    await state.clear()

    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌ Нет доступа.", show_alert=True); return

    access_svc = AccessService(session, access_cache)
    is_lifetime = (days == 0)
    access = await access_svc.grant_access(
        user_id=target_user_id,
        group_id=group_id,
        tariff_id=None,
        duration_days=None if is_lifetime else days,
        is_lifetime=is_lifetime,
        granted_by=callback.from_user.id,
        note="Выдан вручную владельцем",
    )
    dur_text = "Бессрочно" if is_lifetime else f"{days} дн. (до {format_date(access.expires_at)})"
    await callback.message.edit_text(
        f"✅ <b>Доступ выдан!</b>\n\n"
        f"Пользователь: <code>{target_user_id}</code>\n"
        f"Группа: {group.title}\n"
        f"Срок: {dur_text}",
        parse_mode="HTML",
        reply_markup=build_owner_panel_kb(group_id).as_markup(),
    )
    try:
        await callback.bot.send_message(
            target_user_id,
            f"✅ <b>Доступ выдан!</b>\n\nВы получили доступ в группу <b>{group.title}</b>.\nСрок: {dur_text}",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("own:revoke:"))
async def cb_owner_revoke(callback: CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(":")[2])
    await state.set_state(OwnerStates.revoke_access_user_id)
    await state.update_data(group_id=group_id)
    await callback.message.answer("👤 Введите Telegram ID пользователя для отзыва доступа:", reply_markup=ReplyKeyboards.cancel())
    await callback.answer()


@router.message(OwnerStates.revoke_access_user_id, F.text != "❌ Отмена")
async def handle_revoke_user_id(message: Message, state: FSMContext, session: AsyncSession, access_cache: AccessCache, group_repo: GroupRepository):
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный ID.")
        return
    data = await state.get_data()
    group_id = data.get("group_id")
    await state.clear()

    group = await get_owner_group(group_id, message.from_user.id, group_repo)
    if not group:
        await message.answer("❌ Нет доступа."); return

    access_svc = AccessService(session, access_cache)
    revoked = await access_svc.revoke_access(user_id, group_id)

    if revoked:
        await message.answer(
            f"✅ Доступ отозван у пользователя <code>{user_id}</code>.",
            reply_markup=ReplyKeyboards.remove(), parse_mode="HTML",
        )
        try:
            await message.bot.send_message(user_id, f"❌ Ваш доступ в группу <b>{group.title}</b> был отозван.", parse_mode="HTML")
        except Exception:
            pass
    else:
        await message.answer(f"⚠️ Активный доступ для <code>{user_id}</code> не найден.", reply_markup=ReplyKeyboards.remove(), parse_mode="HTML")


@router.callback_query(F.data.startswith("own:members:"))
async def cb_owner_members(callback: CallbackQuery, group_repo: GroupRepository, session: AsyncSession):
    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌ Нет доступа.", show_alert=True); return

    access_repo = AccessRepository(session)
    user_ids = await access_repo.get_group_authorized_users(group_id)

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"own:panel:{group_id}"))

    if not user_ids:
        await callback.message.edit_text(
            f"👥 <b>Участники с доступом: {group.title}</b>\n\nНет активных доступов.",
            reply_markup=b.as_markup(), parse_mode="HTML",
        )
    else:
        text = f"👥 <b>Участники с доступом: {group.title}</b>\n\nВсего: {len(user_ids)}\n\n"
        accesses = await access_repo.get_expiring_soon(hours=72)
        expiring = {a.user_id: a for a in accesses if a.group_id == group_id}
        for uid in list(user_ids)[:20]:
            acc = expiring.get(uid)
            if acc:
                text += f"• <code>{uid}</code> ⏰ до {format_date(acc.expires_at)}\n"
            else:
                text += f"• <code>{uid}</code>\n"
        if len(user_ids) > 20:
            text += f"\n<i>... и ещё {len(user_ids) - 20}</i>"
        await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("own:tariffs:"))
async def cb_owner_tariffs(callback: CallbackQuery, group_repo: GroupRepository, session: AsyncSession):
    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌ Нет доступа.", show_alert=True); return

    tariff_svc = TariffService(session)
    tariffs = await tariff_svc.get_group_tariffs(group_id)
    b = InlineKeyboardBuilder()
    for t in tariffs:
        b.row(InlineKeyboardButton(text=f"📦 {t.name} — {t.price_label} / {t.duration_label}", callback_data=f"own:tariff:{t.id}"))
    b.row(InlineKeyboardButton(text="➕ Добавить тариф", callback_data=f"own:add_tariff:{group_id}"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"own:panel:{group_id}"))

    text = f"📦 <b>Тарифы: {group.title}</b>\n\nВсего: {len(tariffs)}"
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("own:add_tariff:"))
async def cb_add_tariff(callback: CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(":")[2])
    await state.set_state(OwnerStates.create_tariff_name)
    await state.update_data(group_id=group_id)
    await callback.message.answer("📦 Введите название тарифа:", reply_markup=ReplyKeyboards.cancel())
    await callback.answer()


@router.message(OwnerStates.create_tariff_name, F.text != "❌ Отмена")
async def handle_tariff_name(message: Message, state: FSMContext):
    await state.update_data(tariff_name=message.text.strip())
    await state.set_state(OwnerStates.create_tariff_price)
    await message.answer("💰 Введите цену (в рублях, только число):")


@router.message(OwnerStates.create_tariff_price, F.text != "❌ Отмена")
async def handle_tariff_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Неверная сумма. Введите число (например: 299).")
        return
    await state.update_data(tariff_price=price)
    await state.set_state(OwnerStates.create_tariff_duration)
    b = InlineKeyboardBuilder()
    for label, days in [("7 дней", 7), ("30 дней", 30), ("90 дней", 90), ("180 дней", 180), ("365 дней", 365), ("Бессрочно", 0)]:
        b.row(InlineKeyboardButton(text=label, callback_data=f"tariff_dur:{days}"))
    await message.answer("📅 Выберите срок тарифа:", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("tariff_dur:"))
async def cb_tariff_duration(callback: CallbackQuery, state: FSMContext):
    days = int(callback.data.split(":")[1])
    await state.update_data(tariff_days=days)
    await state.set_state(OwnerStates.create_tariff_details)
    await callback.message.answer("💳 Введите реквизиты для оплаты (карта/ЮMoney/Qiwi) или '-' если нет:")
    await callback.answer()


@router.message(OwnerStates.create_tariff_details, F.text != "❌ Отмена")
async def handle_tariff_details(message: Message, state: FSMContext, session: AsyncSession, group_repo: GroupRepository):
    data = await state.get_data()
    await state.clear()
    group_id = data["group_id"]
    name = data["tariff_name"]
    price = data["tariff_price"]
    days = data["tariff_days"]
    details = message.text.strip() if message.text.strip() != "-" else None

    group = await get_owner_group(group_id, message.from_user.id, group_repo)
    if not group:
        await message.answer("❌ Нет доступа."); return

    tariff_svc = TariffService(session)
    tariff = await tariff_svc.create_tariff(
        group_id=group_id,
        name=name,
        price=price,
        duration_days=None if days == 0 else days,
        is_lifetime=(days == 0),
        payment_details=details,
    )
    await message.answer(
        f"✅ <b>Тариф создан!</b>\n\n"
        f"📦 {tariff.name}\n"
        f"💰 {tariff.price_label}\n"
        f"📅 {tariff.duration_label}",
        reply_markup=ReplyKeyboards.remove(), parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("own:payments:"))
async def cb_owner_payments(callback: CallbackQuery, group_repo: GroupRepository, session: AsyncSession, bot: Bot, access_cache: AccessCache):
    group_id = int(callback.data.split(":")[2])
    group = await get_owner_group(group_id, callback.from_user.id, group_repo)
    if not group:
        await callback.answer("❌ Нет доступа.", show_alert=True); return

    from bot.repositories.payment_repo import PaymentRepository
    payment_repo = PaymentRepository(session)
    pending = await payment_repo.get_pending_for_group(group_id)
    b = InlineKeyboardBuilder()
    for p in pending[:10]:
        b.row(InlineKeyboardButton(
            text=f"#{p.id} | {p.user_id} | {int(p.amount)}₽",
            callback_data=f"pay_view:{p.id}",
        ))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"own:panel:{group_id}"))
    text = f"💳 <b>Заявки на оплату</b>\n\nОжидают: {len(pending)}"
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("own:broadcast:"))
async def cb_owner_broadcast(callback: CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(":")[2])
    await state.set_state(OwnerStates.broadcast_text)
    await state.update_data(group_id=group_id, broadcast_target="group")
    await callback.message.answer("📢 Введите текст рассылки участникам группы:", reply_markup=ReplyKeyboards.cancel())
    await callback.answer()


@router.message(OwnerStates.broadcast_text, F.text != "❌ Отмена")
async def handle_owner_broadcast(message: Message, state: FSMContext, session: AsyncSession, group_repo: GroupRepository, bot: Bot, access_cache: AccessCache):
    data = await state.get_data()
    group_id = data.get("group_id")
    await state.clear()

    group = await get_owner_group(group_id, message.from_user.id, group_repo)
    if not group:
        await message.answer("❌ Нет доступа.", reply_markup=ReplyKeyboards.remove()); return

    access_repo = AccessRepository(session)
    user_ids = list(await access_repo.get_group_authorized_users(group_id))

    from bot.services.notification_service import NotificationService
    notif = NotificationService(bot)
    sent, failed = await notif.broadcast(bot, user_ids, message.text)
    await message.answer(
        f"📢 Рассылка завершена!\nОтправлено: {sent}\nОшибок: {failed}",
        reply_markup=ReplyKeyboards.remove(),
    )


@router.message(F.text == "❌ Отмена")
async def cancel_owner(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=ReplyKeyboards.remove())
