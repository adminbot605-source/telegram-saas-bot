from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder


class ReplyKeyboards:

    @staticmethod
    def remove() -> ReplyKeyboardRemove:
        return ReplyKeyboardRemove()

    @staticmethod
    def cancel() -> ReplyKeyboardMarkup:
        builder = ReplyKeyboardBuilder()
        builder.row(KeyboardButton(text="❌ Отмена"))
        return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

    @staticmethod
    def share_group() -> ReplyKeyboardMarkup:
        builder = ReplyKeyboardBuilder()
        builder.row(KeyboardButton(text="❌ Отмена"))
        return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)
