from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from bot.services import UserService, GroupService, SubscriptionService
from bot.keyboards.inline import InlineKeyboards
from bot.keyboards.reply import ReplyKeyboards
from bot.utils.helpers import format_date, truncate
from loguru import logger

router = Router()


class GroupStates(StatesGroup):
    waiting_for_group_id = State()
    waiting_for_welcome_text = State()
    waiting_for_scheduled_post = State()
    waiting_for_schedule_time = State()


@router.message(Command("groups"))
async def cmd_groups(message: Message, group_service: GroupService):
    groups = await group_service.get_by_owner(message.from_user.id)
    if not groups:
        text = (
            "👥 <b>Мои группы</b>\n\n"
            "У вас пока нет зарегистрированных групп.\n\n"
            f"Добавьте бота в группу как администратора, "
            "затем нажмите «Добавить группу» и отправьте ID группы."
        )
    else:
        text = f"👥 <b>Мои группы</b> ({len(groups)}):\n\nВыберите группу для настройки:"
    await message.answer(
        text,
        reply_markup=InlineKeyboards.groups_list(groups),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "my_groups")
async def cb_my_groups(callback: CallbackQuery, group_service: GroupService):
    groups = await group_service.get_by_owner(callback.from_user.id)
    if not groups:
        text = (
            "👥 <b>Мои группы</b>\n\n"
            "У вас пока нет зарегистрированных групп.\n\n"
            "Добавьте бота в группу как администратора, "
            "затем нажмите «Добавить группу» и введите ID чата."
        )
    else:
        text = f"👥 <b>Мои группы</b> ({len(groups)}):\n\nВыберите группу для настройки:"
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboards.groups_list(groups),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "add_group")
async def cb_add_group(
    callback: CallbackQuery,
    state: FSMContext,
    group_service: GroupService,
    sub_service: SubscriptionService,
):
    sub = await sub_service.get_or_create_free(callback.from_user.id)
    can_add = await group_service.can_add_group(callback.from_user.id, sub)

    if not can_add:
        await callback.message.edit_text(
            f"❌ <b>Лимит групп достигнут</b>\n\n"
            f"Ваш тариф <b>{sub.plan_name}</b> позволяет добавить максимум "
            f"<b>{sub.groups_limit}</b> групп.\n\n"
            f"Обновите подписку для добавления большего количества групп:",
            reply_markup=InlineKeyboards.subscription_plans(),
            parse_mode="HTML",
        )
        await callback.answer("Лимит групп достигнут", show_alert=True)
        return

    await state.set_state(GroupStates.waiting_for_group_id)
    await callback.message.edit_text(
        "➕ <b>Добавление группы</b>\n\n"
        "Чтобы добавить группу:\n"
        "1. Добавьте бота в группу как администратора\n"
        "2. Перешлите любое сообщение из этой группы сюда\n\n"
        "<i>Или введите ID группы вручную (например: -1001234567890)</i>",
        reply_markup=None,
        parse_mode="HTML",
    )
    await callback.message.answer("Отправьте сообщение из группы или введите ID:", reply_markup=ReplyKeyboards.cancel())
    await callback.answer()


@router.message(GroupStates.waiting_for_group_id, F.text == "❌ Отмена")
async def cancel_add_group(message: Message, state: FSMContext, group_service: GroupService):
    await state.clear()
    groups = await group_service.get_by_owner(message.from_user.id)
    await message.answer(
        "❌ Добавление группы отменено.",
        reply_markup=ReplyKeyboards.remove(),
    )
    await message.answer(
        "👥 <b>Мои группы</b>",
        reply_markup=InlineKeyboards.groups_list(groups),
        parse_mode="HTML",
    )


@router.message(GroupStates.waiting_for_group_id, F.forward_from_chat)
async def handle_forwarded_group(
    message: Message,
    state: FSMContext,
    bot: Bot,
    group_service: GroupService,
    sub_service: SubscriptionService,
):
    chat = message.forward_from_chat
    if chat.type not in ("group", "supergroup", "channel"):
        await message.answer("❌ Это не группа и не канал. Перешлите сообщение из группы или канала.")
        return

    await _register_group(message, state, bot, group_service, sub_service, chat.id)


@router.message(GroupStates.waiting_for_group_id)
async def handle_group_id_input(
    message: Message,
    state: FSMContext,
    bot: Bot,
    group_service: GroupService,
    sub_service: SubscriptionService,
):
    text = message.text.strip() if message.text else ""
    try:
        group_id = int(text)
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите числовой ID группы (например: -1001234567890)")
        return

    await _register_group(message, state, bot, group_service, sub_service, group_id)


async def _register_group(message, state, bot, group_service, sub_service, chat_id):
    try:
        chat = await bot.get_chat(chat_id)
    except Exception:
        await message.answer(
            "❌ Не могу получить информацию о группе.\n"
            "Убедитесь, что бот является администратором этой группы.",
            reply_markup=ReplyKeyboards.remove(),
        )
        await state.clear()
        return

    if chat.type not in ("group", "supergroup", "channel"):
        await message.answer("❌ Это не группа и не канал.", reply_markup=ReplyKeyboards.remove())
        await state.clear()
        return

    sub = await sub_service.get_or_create_free(message.from_user.id)
    can_add = await group_service.can_add_group(message.from_user.id, sub)
    if not can_add:
        await message.answer(
            f"❌ Лимит групп достигнут. Обновите подписку.",
            reply_markup=ReplyKeyboards.remove(),
        )
        await state.clear()
        return

    group, is_new = await group_service.register_group(chat, message.from_user.id)
    await state.clear()

    try:
        member_count = await bot.get_chat_member_count(chat_id)
        await group_service.update_member_count(chat_id, member_count)
        group.member_count = member_count
    except Exception:
        pass

    if is_new:
        text = f"✅ <b>Группа успешно добавлена!</b>\n\n"
    else:
        text = f"✅ <b>Группа обновлена!</b>\n\n"

    text += (
        f"📋 <b>{chat.title}</b>\n"
        f"👤 Участников: {group.member_count}\n\n"
        f"Теперь вы можете настроить параметры группы:"
    )

    await message.answer(text, reply_markup=ReplyKeyboards.remove(), parse_mode="HTML")
    await message.answer(
        "⚙️ Настройки группы:",
        reply_markup=InlineKeyboards.group_settings(group),
    )


@router.callback_query(F.data.startswith("group:"))
async def cb_group_settings(callback: CallbackQuery, group_service: GroupService):
    group_id = int(callback.data.split(":")[1])
    group = await group_service.get_by_id(group_id)

    if not group or group.owner_id != callback.from_user.id:
        await callback.answer("❌ Группа не найдена.", show_alert=True)
        return

    text = (
        f"⚙️ <b>Настройки: {group.title}</b>\n\n"
        f"👤 Участников: <b>{group.member_count}</b>\n"
        f"🎉 Приветствие: {'✅' if group.welcome_enabled else '❌'}\n"
        f"🛡 Антиспам: {'✅' if group.anti_spam_enabled else '❌'}\n"
        f"🌊 Антифлуд: {'✅' if group.anti_flood_enabled else '❌'}\n"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboards.group_settings(group),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("grp_welcome:"))
async def cb_group_welcome(callback: CallbackQuery, group_service: GroupService):
    group_id = int(callback.data.split(":")[1])
    group = await group_service.get_by_id(group_id)

    if not group or group.owner_id != callback.from_user.id:
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    current_text = group.welcome_message or "Не задано"
    text = (
        f"🎉 <b>Приветственное сообщение</b>\n\n"
        f"Статус: {'✅ Включено' if group.welcome_enabled else '❌ Выключено'}\n\n"
        f"<b>Текущий текст:</b>\n{current_text}\n\n"
        f"<i>Доступные переменные: {{name}} — имя, {{username}} — username, {{group}} — название группы</i>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboards.welcome_message_settings(group),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_welcome:"))
async def cb_toggle_welcome(callback: CallbackQuery, group_service: GroupService):
    group_id = int(callback.data.split(":")[1])
    group = await group_service.get_by_id(group_id)

    if not group or group.owner_id != callback.from_user.id:
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    group = await group_service.update_group(group_id, welcome_enabled=not group.welcome_enabled)
    status = "включено" if group.welcome_enabled else "выключено"
    await callback.answer(f"Приветствие {status}", show_alert=False)

    text = (
        f"🎉 <b>Приветственное сообщение</b>\n\n"
        f"Статус: {'✅ Включено' if group.welcome_enabled else '❌ Выключено'}\n\n"
        f"<b>Текущий текст:</b>\n{group.welcome_message or 'Не задано'}\n\n"
        f"<i>Доступные переменные: {{name}} — имя, {{username}} — username, {{group}} — название группы</i>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboards.welcome_message_settings(group),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("edit_welcome:"))
async def cb_edit_welcome(callback: CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(":")[1])
    await state.set_state(GroupStates.waiting_for_welcome_text)
    await state.update_data(group_id=group_id)
    await callback.message.answer(
        "✏️ Введите новый текст приветствия:\n\n"
        "<i>Переменные: {name} — имя, {username} — @username, {group} — название группы</i>",
        reply_markup=ReplyKeyboards.cancel(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(GroupStates.waiting_for_welcome_text, F.text != "❌ Отмена")
async def handle_welcome_text(
    message: Message, state: FSMContext, group_service: GroupService
):
    data = await state.get_data()
    group_id = data.get("group_id")
    group = await group_service.update_group(group_id, welcome_message=message.text)
    await state.clear()
    await message.answer(
        "✅ Текст приветствия обновлён!",
        reply_markup=ReplyKeyboards.remove(),
    )
    await message.answer(
        f"⚙️ Настройки: {group.title}",
        reply_markup=InlineKeyboards.group_settings(group),
    )


@router.callback_query(F.data.startswith("grp_spam:"))
async def cb_toggle_spam(callback: CallbackQuery, group_service: GroupService, sub_service: SubscriptionService):
    group_id = int(callback.data.split(":")[1])
    group = await group_service.get_by_id(group_id)
    if not group or group.owner_id != callback.from_user.id:
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    sub = await sub_service.get_or_create_free(callback.from_user.id)
    if not sub.plan_config.get("anti_spam") and not group.anti_spam_enabled:
        await callback.answer("❌ Антиспам доступен в тарифах Базовый и выше.", show_alert=True)
        return

    group = await group_service.update_group(group_id, anti_spam_enabled=not group.anti_spam_enabled)
    status = "включён" if group.anti_spam_enabled else "выключён"
    await callback.answer(f"Антиспам {status}")

    await callback.message.edit_text(
        f"⚙️ <b>Настройки: {group.title}</b>\n\n"
        f"👤 Участников: <b>{group.member_count}</b>\n"
        f"🎉 Приветствие: {'✅' if group.welcome_enabled else '❌'}\n"
        f"🛡 Антиспам: {'✅' if group.anti_spam_enabled else '❌'}\n"
        f"🌊 Антифлуд: {'✅' if group.anti_flood_enabled else '❌'}\n",
        reply_markup=InlineKeyboards.group_settings(group),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("grp_flood:"))
async def cb_toggle_flood(callback: CallbackQuery, group_service: GroupService, sub_service: SubscriptionService):
    group_id = int(callback.data.split(":")[1])
    group = await group_service.get_by_id(group_id)
    if not group or group.owner_id != callback.from_user.id:
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    sub = await sub_service.get_or_create_free(callback.from_user.id)
    if not sub.plan_config.get("anti_spam") and not group.anti_flood_enabled:
        await callback.answer("❌ Антифлуд доступен в тарифах Базовый и выше.", show_alert=True)
        return

    group = await group_service.update_group(group_id, anti_flood_enabled=not group.anti_flood_enabled)
    status = "включён" if group.anti_flood_enabled else "выключён"
    await callback.answer(f"Антифлуд {status}")
    await callback.message.edit_text(
        f"⚙️ <b>Настройки: {group.title}</b>\n\n"
        f"👤 Участников: <b>{group.member_count}</b>\n"
        f"🎉 Приветствие: {'✅' if group.welcome_enabled else '❌'}\n"
        f"🛡 Антиспам: {'✅' if group.anti_spam_enabled else '❌'}\n"
        f"🌊 Антифлуд: {'✅' if group.anti_flood_enabled else '❌'}\n",
        reply_markup=InlineKeyboards.group_settings(group),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("grp_delete:"))
async def cb_delete_group_confirm(callback: CallbackQuery):
    group_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "⚠️ <b>Вы уверены, что хотите удалить группу?</b>\n\n"
        "Все настройки и запланированные посты будут удалены.",
        reply_markup=InlineKeyboards.confirm_action("delete_group", group_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm:delete_group:"))
async def cb_delete_group(callback: CallbackQuery, group_service: GroupService):
    group_id = int(callback.data.split(":")[2])
    group = await group_service.get_by_id(group_id)
    if not group or group.owner_id != callback.from_user.id:
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    await group_service.deactivate_group(group_id)
    groups = await group_service.get_by_owner(callback.from_user.id)
    await callback.message.edit_text(
        "✅ Группа удалена.\n\n👥 <b>Мои группы:</b>",
        reply_markup=InlineKeyboards.groups_list(groups),
        parse_mode="HTML",
    )
    await callback.answer("Группа удалена")


@router.callback_query(F.data.startswith("grp_stats:"))
async def cb_group_stats(callback: CallbackQuery, group_service: GroupService):
    group_id = int(callback.data.split(":")[1])
    group = await group_service.get_by_id(group_id)
    if not group or group.owner_id != callback.from_user.id:
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    text = (
        f"📊 <b>Статистика: {group.title}</b>\n\n"
        f"👤 Участников: <b>{group.member_count}</b>\n"
        f"📅 Запланированных постов: <b>{len(group.scheduled_posts)}</b>\n"
        f"🎉 Приветствие: {'✅ Включено' if group.welcome_enabled else '❌ Выключено'}\n"
        f"🛡 Антиспам: {'✅ Включён' if group.anti_spam_enabled else '❌ Выключён'}\n"
        f"🌊 Антифлуд: {'✅ Включён' if group.anti_flood_enabled else '❌ Выключён'}\n"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboards.back_to_groups(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext, group_service: GroupService):
    await state.clear()
    groups = await group_service.get_by_owner(callback.from_user.id)
    await callback.message.edit_text(
        "👥 <b>Мои группы</b>",
        reply_markup=InlineKeyboards.groups_list(groups),
        parse_mode="HTML",
    )
    await callback.answer("Отменено")
