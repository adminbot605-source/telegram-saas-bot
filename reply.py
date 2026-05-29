"""Payment receipts, approve/reject flow."""

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, PhotoSize
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from bot.repositories import GroupRepository, PaymentRepository, TariffRepository
from bot.repositories.access_repo import AccessRepository
from bot.services.payment_service import PaymentService
from bot.services.access_service import AccessService
from bot.services.notification_service import NotificationService
from bot.services.tariff_service import TariffService
from bot.cache.redis_cache import AccessCache
from bot.keyboards.reply import ReplyKeyboards
from bot.utils.helpers import format_date
from bot.config import settings
from bot.models.payment import PaymentReceiptType

router = Router()


class PaymentStates(StatesGroup):
    select_tariff = State()
    enter_comment = State()
    upload_receipt = State()
    reject_reason = State()


@router.callback_query(F.data.startswith("pay_view:"))
async def cb_view_payment(callback: CallbackQuery, session: AsyncSession, access_cache: AccessCache, bot: Bot):
    payment_id = int(callback.data.split(":")[1])
    payment_repo = PaymentRepository(session)
    payment = await payment_repo.get_by_id(payment_id)

    if not payment:
        await callback.answer("❌ Заявка не найдена.", show_alert=True); return

    group_repo = GroupRepository(session)
    group = await group_repo.get_by_id(payment.group_id)
    is_owner = (group and group.owner_id == callback.from_user.id)
    is_creator = (callback.from_user.id == settings.CREATOR_USER_ID)

    if not (is_owner or is_creator):
        await callback.answer("❌ Нет доступа.", show_alert=True); return

    tariff_repo = TariffRepository(session)
    tariff = await tariff_repo.get_by_id(payment.tariff_id) if payment.tariff_id else None

    text = (
        f"💳 <b>Заявка #{payment.id}</b>\n\n"
        f"👤 Пользователь: <code>{payment.user_id}</code>\n"
        f"📋 Группа: {group.title if group else payment.group_id}\n"
        f"📦 Тариф: {tariff.name if tariff else '—'} ({tariff.duration_label if tariff else '—'})\n"
        f"💰 Сумма: <b>{int(payment.amount)}₽</b>\n"
        f"📅 Создана: {format_date(payment.created_at)}\n"
        f"💬 Комментарий: {payment.user_comment or '—'}\n\n"
        f"Статус: {payment.status_label}"
    )

    b = InlineKeyboardBuilder()
    if payment.status == "pending":
        b.row(
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"pay_approve:{payment.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pay_reject_prompt:{payment.id}"),
        )
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="cr:payments" if is_creator else f"own:payments:{payment.group_id}"))

    if payment.receipt_file_id and payment.receipt_type == PaymentReceiptType.PHOTO.value:
        try:
            await callback.message.delete()
            await bot.send_photo(callback.from_user.id, payment.receipt_file_id, caption=text, reply_markup=b.as_markup(), parse_mode="HTML")
        except Exception:
            await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("pay_approve:"))
async def cb_approve_payment(callback: CallbackQuery, session: AsyncSession, access_cache: AccessCache, bot: Bot):
    payment_id = int(callback.data.split(":")[1])
    payment_repo = PaymentRepository(session)
    payment = await payment_repo.get_by_id(payment_id)
    if not payment:
        await callback.answer("❌ Не найдено.", show_alert=True); return

    group_repo = GroupRepository(session)
    group = await group_repo.get_by_id(payment.group_id)
    is_owner = (group and group.owner_id == callback.from_user.id)
    is_creator_user = (callback.from_user.id == settings.CREATOR_USER_ID)
    if not (is_owner or is_creator_user):
        await callback.answer("❌ Нет доступа.", show_alert=True); return

    access_svc = AccessService(session, access_cache)
    payment_svc = PaymentService(session, access_svc, bot)
    approved = await payment_svc.approve_payment(payment_id, callback.from_user.id)

    if approved:
        await callback.message.edit_text(
            f"✅ <b>Заявка #{payment_id} подтверждена!</b>\nДоступ выдан пользователю <code>{payment.user_id}</code>.",
            parse_mode="HTML",
        )
        await callback.answer("✅ Оплата подтверждена!")
    else:
        await callback.answer("❌ Не удалось подтвердить.", show_alert=True)


@router.callback_query(F.data.startswith("pay_reject_prompt:"))
async def cb_reject_prompt(callback: CallbackQuery, state: FSMContext):
    payment_id = int(callback.data.split(":")[1])
    await state.set_state(PaymentStates.reject_reason)
    await state.update_data(payment_id=payment_id)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏭ Без причины", callback_data=f"pay_reject:{payment_id}:"))
    await callback.message.answer("✏️ Укажите причину отклонения (или нажмите «Без причины»):", reply_markup=b.as_markup())
    await callback.answer()


@router.message(PaymentStates.reject_reason)
async def handle_reject_reason(message: Message, state: FSMContext, session: AsyncSession, access_cache: AccessCache, bot: Bot):
    data = await state.get_data()
    await state.clear()
    payment_id = data.get("payment_id")
    reason = message.text.strip()
    group_repo = GroupRepository(session)
    payment_repo = PaymentRepository(session)
    payment = await payment_repo.get_by_id(payment_id)
    if not payment:
        await message.answer("❌ Заявка не найдена.", reply_markup=ReplyKeyboards.remove()); return

    access_svc = AccessService(session, access_cache)
    payment_svc = PaymentService(session, access_svc, bot)
    await payment_svc.reject_payment(payment_id, message.from_user.id, reason)
    await message.answer(f"❌ Заявка #{payment_id} отклонена.", reply_markup=ReplyKeyboards.remove())


@router.callback_query(F.data.startswith("pay_reject:"))
async def cb_reject_payment(callback: CallbackQuery, session: AsyncSession, access_cache: AccessCache, bot: Bot, state: FSMContext):
    parts = callback.data.split(":")
    payment_id = int(parts[1])
    reason = parts[2] if len(parts) > 2 else None
    await state.clear()

    payment_repo = PaymentRepository(session)
    payment = await payment_repo.get_by_id(payment_id)
    if not payment:
        await callback.answer("❌ Не найдено.", show_alert=True); return

    access_svc = AccessService(session, access_cache)
    payment_svc = PaymentService(session, access_svc, bot)
    await payment_svc.reject_payment(payment_id, callback.from_user.id, reason or None)

    await callback.message.edit_text(f"❌ Заявка #{payment_id} отклонена.")
    await callback.answer("Заявка отклонена")


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy_tariff(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    group_id = int(parts[1])
    tariff_id = int(parts[2])
    await state.set_state(PaymentStates.upload_receipt)
    await state.update_data(group_id=group_id, tariff_id=tariff_id)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    await callback.message.answer(
        "📎 <b>Отправьте чек об оплате</b>\n\n"
        "Загрузите скриншот или фото квитанции, подтверждающей оплату.\n\n"
        "<i>Также можно отправить текстовый комментарий с номером транзакции.</i>",
        reply_markup=b.as_markup(), parse_mode="HTML",
    )
    await callback.answer()


@router.message(PaymentStates.upload_receipt)
async def handle_receipt_upload(
    message: Message, state: FSMContext,
    session: AsyncSession, access_cache: AccessCache, bot: Bot,
    group_repo: GroupRepository,
):
    data = await state.get_data()
    group_id = data.get("group_id")
    tariff_id = data.get("tariff_id")
    await state.clear()

    receipt_file_id = None
    receipt_type = PaymentReceiptType.TEXT.value

    if message.photo:
        receipt_file_id = message.photo[-1].file_id
        receipt_type = PaymentReceiptType.PHOTO.value
    elif message.document:
        receipt_file_id = message.document.file_id
        receipt_type = PaymentReceiptType.DOCUMENT.value

    comment = message.caption or (message.text if message.text else None)

    tariff_repo = TariffRepository(session)
    tariff = await tariff_repo.get_active(tariff_id)
    if not tariff:
        await message.answer("❌ Тариф не найден."); return

    group = await group_repo.get_by_id(group_id)
    if not group:
        await message.answer("❌ Группа не найдена."); return

    access_svc = AccessService(session, access_cache)
    payment_svc = PaymentService(session, access_svc, bot)
    payment = await payment_svc.create_payment(
        user_id=message.from_user.id,
        group_id=group_id,
        tariff_id=tariff_id,
        receipt_file_id=receipt_file_id,
        receipt_type=receipt_type,
        user_comment=comment,
    )

    if not payment:
        await message.answer("⚠️ У вас уже есть активная заявка на рассмотрении."); return

    notif = NotificationService(bot)
    await notif.notify_owner_new_payment(
        owner_id=group.owner_id,
        payment_id=payment.id,
        user_name=message.from_user.full_name,
        user_id=message.from_user.id,
        group_title=group.title,
        tariff_name=tariff.name,
        amount=float(tariff.price),
        receipt_file_id=receipt_file_id,
        receipt_type=receipt_type,
    )
    if group.owner_id != settings.CREATOR_USER_ID:
        try:
            await notif.notify_owner_new_payment(
                owner_id=settings.CREATOR_USER_ID,
                payment_id=payment.id,
                user_name=message.from_user.full_name,
                user_id=message.from_user.id,
                group_title=group.title,
                tariff_name=tariff.name,
                amount=float(tariff.price),
                receipt_file_id=receipt_file_id,
                receipt_type=receipt_type,
            )
        except Exception:
            pass

    await message.answer(
        f"✅ <b>Чек отправлен на проверку!</b>\n\n"
        f"Заявка #{payment.id}\n"
        f"Тариф: {tariff.name}\n"
        f"Сумма: {int(tariff.price)}₽\n\n"
        f"Ожидайте подтверждения от администратора.",
        parse_mode="HTML",
    )
