from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.models.group import Group
from typing import List


class InlineKeyboards:

    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="🔧 Панель владельца", callback_data="owner_menu"),
            InlineKeyboardButton(text="🔑 Мои доступы", callback_data="my_accesses"),
        )
        b.row(
            InlineKeyboardButton(text="🎁 Рефералы", callback_data="referral"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="help"),
        )
        return b.as_markup()

    @staticmethod
    def back_to_menu() -> InlineKeyboardMarkup:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
        return b.as_markup()

    @staticmethod
    def back_to_groups() -> InlineKeyboardMarkup:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="◀️ К группам", callback_data="my_groups"))
        return b.as_markup()

    @staticmethod
    def confirm_action(action: str, entity_id) -> InlineKeyboardMarkup:
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{action}:{entity_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu"),
        )
        return b.as_markup()
