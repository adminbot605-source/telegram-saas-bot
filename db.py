from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from bot.services import SubscriptionService
from bot.models.subscription import SubscriptionPlan, PLAN_CONFIG
from bot.keyboards.inline import InlineKeyboards
from bot.utils.helpers import format_date

router = Router()


def format_plan_info(plan: SubscriptionPlan) -> str:
    cfg = PLAN_CONFIG[plan]
    features = []
    features.append(f"👥 Групп/каналов: до {cfg['groups_limit']}")
    features.append(f"📅 Запланированных постов: {cfg['scheduled_posts'] if cfg['scheduled_posts'] != 999 else 'неограниченно'}")
    features.append(f"🎉 Приветствия: {'✅' if cfg['welcome_message'] else '❌'}")
    features.append(f"🛡 Антиспам: {'✅' if cfg['anti_spam'] else '❌'}")
    features.append(f"📊 Аналитика: {'✅' if cfg['analytics'] else '❌'}")
    return "\n".join(features)


@router.message(Command("subscription"))
async def cmd_subscription(message: Message, sub_service: SubscriptionService):
    sub = await sub_service.get_or_create_free(message.from_user.id)

    text = (
        f"💳 <b>Ваша подписка</b>\n\n"
        f"Тарифный план: {sub.plan_emoji} <b>{sub.plan_name}</b>\n"
    )
    if sub.expires_at:
        text += f"Активна до: <b>{format_date(sub.expires_at)}</b>\n"
    else:
        text += "Срок действия: <b>Бессрочно</b>\n"

    text += f"\n<b>Ваши возможности:</b>\n{format_plan_info(SubscriptionPlan(sub.plan))}\n"

    if sub.plan != SubscriptionPlan.PRO.value:
        text += "\n⬆️ Обновите подписку для доступа к большему функционалу:"

    await message.answer(
        text,
        reply_markup=InlineKeyboards.subscription_plans(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "subscription")
async def cb_subscription(callback: CallbackQuery, sub_service: SubscriptionService):
    sub = await sub_service.get_or_create_free(callback.from_user.id)

    text = (
        f"💳 <b>Ваша подписка</b>\n\n"
        f"Тарифный план: {sub.plan_emoji} <b>{sub.plan_name}</b>\n"
    )
    if sub.expires_at:
        text += f"Активна до: <b>{format_date(sub.expires_at)}</b>\n"
    else:
        text += "Срок действия: <b>Бессрочно</b>\n"

    text += f"\n<b>Возможности вашего тарифа:</b>\n{format_plan_info(SubscriptionPlan(sub.plan))}"

    if sub.plan != SubscriptionPlan.PRO.value:
        text += "\n\n⬆️ Обновите подписку для расширенного функционала:"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboards.subscription_plans(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "yearly_plans")
async def cb_yearly_plans(callback: CallbackQuery):
    text = (
        "📅 <b>Годовая подписка</b>\n\n"
        "Экономьте 15% при оплате на год!\n\n"
        "<b>Доступные тарифы:</b>"
    )
    for plan in [SubscriptionPlan.BASIC, SubscriptionPlan.PRO]:
        cfg = PLAN_CONFIG[plan]
        monthly_total = cfg['price_month'] * 12
        saving = monthly_total - cfg['price_year']
        text += f"\n\n{cfg['emoji']} <b>{cfg['name']}</b>\n"
        text += f"Год: {cfg['price_year']}₽ (экономия {saving}₽)"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboards.yearly_plans(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy_plan:"))
async def cb_buy_plan(callback: CallbackQuery, sub_service: SubscriptionService):
    parts = callback.data.split(":")
    plan_value = parts[1]
    months = int(parts[2])

    try:
        plan = SubscriptionPlan(plan_value)
    except ValueError:
        await callback.answer("❌ Неверный тариф.", show_alert=True)
        return

    cfg = PLAN_CONFIG[plan]
    price = cfg['price_month'] if months == 1 else cfg['price_year']
    period = "месяц" if months == 1 else "год"

    text = (
        f"💳 <b>Оформление подписки</b>\n\n"
        f"Тариф: {cfg['emoji']} <b>{cfg['name']}</b>\n"
        f"Период: <b>{months} {period if months == 1 else 'год'}</b>\n"
        f"Стоимость: <b>{price}₽</b>\n\n"
        f"<b>Что входит:</b>\n{format_plan_info(plan)}\n\n"
        "💬 Для оплаты обратитесь к администратору или используйте реквизиты:\n"
        "<i>Функция оплаты будет добавлена позже</i>\n\n"
        "После оплаты отправьте скриншот администратору для активации подписки."
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboards.back_to_menu(),
        parse_mode="HTML",
    )
    await callback.answer()
