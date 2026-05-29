from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.services import UserService, GroupService, SubscriptionService
from bot.models.subscription import SubscriptionPlan
from bot.keyboards.inline import InlineKeyboards
from bot.keyboards.reply import ReplyKeyboards
from bot.config import settings
from loguru import logger

router = Router()


class AdminStates(StatesGroup):
    waiting_broadcast_text = State()
    waiting_user_id_for_sub = State()
    waiting_plan_for_sub = State()


def is_admin(user_id: int) -> bool:
    return user_id == settings.CREATOR_USER_ID


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🔐 <b>Панель администратора</b>\n\nВыберите действие:",
        reply_markup=InlineKeyboards.admin_panel(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(
    callback: CallbackQuery,
    user_service: UserService,
    group_service: GroupService,
    sub_service: SubscriptionService,
):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    user_stats = await user_service.get_stats()
    group_stats = await group_service.get_stats()
    sub_stats = await sub_service.get_stats()

    free_count = sub_stats.get(SubscriptionPlan.FREE.value, 0)
    basic_count = sub_stats.get(SubscriptionPlan.BASIC.value, 0)
    pro_count = sub_stats.get(SubscriptionPlan.PRO.value, 0)

    text = (
        "📊 <b>Общая статистика</b>\n\n"
        f"<b>👥 Пользователи:</b>\n"
        f"  Всего: {user_stats['total']}\n"
        f"  Заблокированных: {user_stats['blocked']}\n\n"
        f"<b>📋 Группы:</b>\n"
        f"  Всего: {group_stats['total']}\n"
        f"  Активных: {group_stats['active']}\n\n"
        f"<b>💳 Подписки:</b>\n"
        f"  🆓 Бесплатных: {free_count}\n"
        f"  ⭐ Базовых: {basic_count}\n"
        f"  💎 Профессиональных: {pro_count}\n"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboards.admin_panel(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_broadcast_text)
    await callback.message.answer(
        "📢 Введите текст рассылки (HTML разметка поддерживается):",
        reply_markup=ReplyKeyboards.cancel(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_broadcast_text, F.text != "❌ Отмена")
async def handle_broadcast_text(
    message: Message,
    state: FSMContext,
    bot: Bot,
    user_service: UserService,
):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    text = message.text
    await message.answer("📢 Начинаю рассылку...", reply_markup=ReplyKeyboards.remove())

    from sqlalchemy import select
    from bot.models.user import User
    from bot.database.session import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(
            select(User.id).where(User.is_blocked == False)
        )
        user_ids = [row[0] for row in result.all()]

    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Broadcast failed for {user_id}: {e}")

    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"Отправлено: {sent}\n"
        f"Ошибок: {failed}",
        reply_markup=InlineKeyboards.admin_panel(),
    )


@router.message(AdminStates.waiting_broadcast_text, F.text == "❌ Отмена")
async def cancel_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.", reply_markup=ReplyKeyboards.remove())
    await message.answer("🔐 Панель администратора:", reply_markup=InlineKeyboards.admin_panel())


@router.callback_query(F.data == "admin_subs")
async def cb_admin_subs(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_user_id_for_sub)
    await callback.message.answer(
        "💳 Введите Telegram ID пользователя для управления подпиской:",
        reply_markup=ReplyKeyboards.cancel(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_user_id_for_sub, F.text != "❌ Отмена")
async def handle_user_id_for_sub(
    message: Message, state: FSMContext, user_service: UserService
):
    if not is_admin(message.from_user.id):
        return

    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный ID. Введите числовой ID пользователя.")
        return

    user = await user_service.get_by_id(target_id)
    if not user:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return

    await state.update_data(target_user_id=target_id)
    await state.set_state(AdminStates.waiting_plan_for_sub)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🆓 Бесплатный", callback_data=f"admin_set_plan:free"),
        InlineKeyboardButton(text="⭐ Базовый", callback_data=f"admin_set_plan:basic"),
    )
    builder.row(
        InlineKeyboardButton(text="💎 Профессиональный", callback_data=f"admin_set_plan:pro"),
    )

    await message.answer(
        f"Пользователь: {user.full_name} (ID: {target_id})\n\nВыберите тариф:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("admin_set_plan:"))
async def cb_admin_set_plan(
    callback: CallbackQuery, state: FSMContext, sub_service: SubscriptionService
):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён.", show_alert=True)
        return

    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    plan_value = callback.data.split(":")[1]

    try:
        plan = SubscriptionPlan(plan_value)
    except ValueError:
        await callback.answer("❌ Неверный тариф.", show_alert=True)
        return

    if plan == SubscriptionPlan.FREE:
        await sub_service.downgrade_to_free(target_user_id)
    else:
        await sub_service.upgrade(target_user_id, plan, months=1)

    await state.clear()
    await callback.message.edit_text(
        f"✅ Тариф пользователя {target_user_id} обновлён на <b>{plan.value}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboards.admin_panel(),
    )
    await callback.answer("Подписка обновлена")

    try:
        from bot.models.subscription import PLAN_CONFIG
        cfg = PLAN_CONFIG[plan]
        await callback.bot.send_message(
            target_user_id,
            f"🎉 Ваша подписка обновлена!\n\n"
            f"Тарифный план: {cfg['emoji']} <b>{cfg['name']}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass
