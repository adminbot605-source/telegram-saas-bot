"""QR payment system handlers.

Commands / flows:
  Owner panel → Tariff settings → Show QR / Generate QR / Upload custom QR / Preview QR

Inline flows:
  qr_show:{tariff_id}        — send QR to user (cached)
  qr_generate:{tariff_id}    — regenerate QR from payment details
  qr_upload:{tariff_id}      — upload custom QR (FSM)
  qr_preview:{tariff_id}     — preview in owner panel
  qr_delete:{tariff_id}      — delete QR
"""

import io
from aiogram import Router, Bot, F
from aiogram.types import (
    CallbackQuery, Message,
    BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from loguru import logger

from bot.core.security import sign_callback, verify_callback
from bot.qr.generator import QRGenerator
from bot.qr.storage import QRStorage
from bot.models.tariff import Tariff
from bot.models.group import Group
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = Router(name="qr")


class QRUploadStates(StatesGroup):
    waiting_for_image = State()


# ─── Show QR to user (tariff selection) ──────────────────────────────────────

async def send_qr_to_user(
    message: Message,
    session: AsyncSession,
    cache,
    tariff_id: int,
    user_id: int,
) -> None:
    """Send QR code to user when they select a tariff for payment."""
    tariff: Tariff | None = await session.get(Tariff, tariff_id)
    if not tariff or not tariff.is_active:
        await message.answer("❌ Тариф не найден.")
        return

    group: Group | None = await session.get(Group, tariff.group_id)
    group_title = group.title if group else "Группа"

    storage = QRStorage(cache.redis)
    try:
        qr_bytes, from_cache = await storage.get_or_generate(
            session=session,
            tariff_id=tariff_id,
            payment_details=tariff.payment_details or "",
            group_title=group_title,
            tariff_name=tariff.name,
            amount=tariff.price or 0.0,
        )
    except Exception as e:
        logger.error(f"QR generation failed for tariff {tariff_id}: {e}")
        await message.answer(
            f"💳 <b>Реквизиты для оплаты:</b>\n\n"
            f"{tariff.payment_details or 'Уточните у владельца группы'}"
        )
        return

    file = BufferedInputFile(qr_bytes, filename="payment_qr.png")
    duration_text = f"{tariff.duration_days} дн." if tariff.duration_days else "бессрочно"
    amount_text = f"{int(tariff.price)} ₽" if tariff.price else "договорная"

    await message.answer_photo(
        photo=file,
        caption=(
            f"📲 <b>QR-код для оплаты</b>\n\n"
            f"🏷 Тариф: <b>{tariff.name}</b>\n"
            f"💰 Сумма: <b>{amount_text}</b>\n"
            f"⏱ Срок: <b>{duration_text}</b>\n\n"
            f"<i>Сканируйте QR или переведите вручную по реквизитам ниже.</i>\n\n"
            f"💳 <b>Реквизиты:</b>\n{tariff.payment_details or '—'}"
        ),
    )


# ─── Owner: manage QR for tariff ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("qr_show:"))
async def cb_qr_show(call: CallbackQuery, session: AsyncSession, access_cache, bot: Bot):
    tariff_id = int(call.data.split(":", 1)[1])
    tariff: Tariff | None = await session.get(Tariff, tariff_id)
    if not tariff:
        await call.answer("Тариф не найден", show_alert=True)
        return

    group: Group | None = await session.get(Group, tariff.group_id)
    group_title = group.title if group else "Группа"

    storage = QRStorage(access_cache.redis)
    try:
        qr_bytes, from_cache = await storage.get_or_generate(
            session=session,
            tariff_id=tariff_id,
            payment_details=tariff.payment_details or "",
            group_title=group_title,
            tariff_name=tariff.name,
            amount=tariff.price or 0.0,
        )
        source = "из кэша" if from_cache else "сгенерирован"
        file = BufferedInputFile(qr_bytes, filename="qr.png")
        kb = _qr_manage_keyboard(tariff_id, call.from_user.id)
        await call.message.answer_photo(
            photo=file,
            caption=f"📲 <b>QR для тарифа «{tariff.name}»</b>\n<i>({source})</i>",
            reply_markup=kb,
        )
        await call.answer()
    except Exception as e:
        logger.error(f"QR show error: {e}")
        await call.answer("Ошибка генерации QR", show_alert=True)


@router.callback_query(F.data.startswith("qr_generate:"))
async def cb_qr_generate(call: CallbackQuery, session: AsyncSession, access_cache):
    tariff_id = int(call.data.split(":", 1)[1])
    tariff: Tariff | None = await session.get(Tariff, tariff_id)
    if not tariff:
        await call.answer("Тариф не найден", show_alert=True)
        return

    await call.answer("⏳ Генерирую QR...")
    group: Group | None = await session.get(Group, tariff.group_id)
    group_title = group.title if group else "Группа"

    storage = QRStorage(access_cache.redis)
    try:
        qr_bytes, _ = await storage.get_or_generate(
            session=session,
            tariff_id=tariff_id,
            payment_details=tariff.payment_details or "",
            group_title=group_title,
            tariff_name=tariff.name,
            amount=tariff.price or 0.0,
            force_regen=True,
        )
        await session.commit()
        file = BufferedInputFile(qr_bytes, filename="qr.png")
        kb = _qr_manage_keyboard(tariff_id, call.from_user.id)
        await call.message.answer_photo(
            photo=file,
            caption=f"✅ QR для тарифа «{tariff.name}» перегенерирован.",
            reply_markup=kb,
        )
    except Exception as e:
        logger.error(f"QR regen error: {e}")
        await call.message.answer("❌ Ошибка генерации QR.")


@router.callback_query(F.data.startswith("qr_upload:"))
async def cb_qr_upload_start(call: CallbackQuery, state: FSMContext):
    tariff_id = int(call.data.split(":", 1)[1])
    await state.set_state(QRUploadStates.waiting_for_image)
    await state.update_data(tariff_id=tariff_id)
    await call.message.answer(
        "📤 Отправьте изображение QR-кода (PNG, JPG, до 5MB).\n"
        "Или /cancel для отмены."
    )
    await call.answer()


@router.message(QRUploadStates.waiting_for_image, F.photo | F.document)
async def handle_qr_upload(message: Message, state: FSMContext, session: AsyncSession, access_cache, bot: Bot):
    data = await state.get_data()
    tariff_id = data.get("tariff_id")
    if not tariff_id:
        await state.clear()
        return

    try:
        if message.photo:
            file_id = message.photo[-1].file_id
        elif message.document and message.document.mime_type in ("image/png", "image/jpeg"):
            file_id = message.document.file_id
        else:
            await message.answer("❌ Пожалуйста, отправьте PNG или JPG изображение.")
            return

        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_bytes = file_bytes.read()

        storage = QRStorage(access_cache.redis)
        tariff: Tariff | None = await session.get(Tariff, tariff_id)
        if not tariff:
            await message.answer("❌ Тариф не найден.")
            await state.clear()
            return

        await storage.store_custom_qr(
            session=session,
            tariff_id=tariff_id,
            qr_bytes=image_bytes,
            payment_details=tariff.payment_details,
        )
        await session.commit()
        await state.clear()
        await message.answer(f"✅ Кастомный QR для тарифа «{tariff.name}» сохранён.")
        logger.info(f"Custom QR uploaded for tariff {tariff_id} by user {message.from_user.id}")

    except ValueError as e:
        await message.answer(f"❌ {e}")
    except Exception as e:
        logger.error(f"QR upload error: {e}")
        await message.answer("❌ Ошибка при сохранении QR.")
        await state.clear()


@router.callback_query(F.data.startswith("qr_delete:"))
async def cb_qr_delete(call: CallbackQuery, session: AsyncSession, access_cache):
    tariff_id = int(call.data.split(":", 1)[1])
    storage = QRStorage(access_cache.redis)
    await storage.delete(session, tariff_id)
    await session.commit()
    await call.answer("🗑 QR удалён", show_alert=True)
    await call.message.delete()


def _qr_manage_keyboard(tariff_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Перегенерировать", callback_data=f"qr_generate:{tariff_id}"),
            InlineKeyboardButton(text="📤 Загрузить свой", callback_data=f"qr_upload:{tariff_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить QR", callback_data=f"qr_delete:{tariff_id}"),
        ],
    ])
