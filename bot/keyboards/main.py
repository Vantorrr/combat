from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


def get_main_menu() -> InlineKeyboardMarkup:
    """Главное меню бота"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🆕 Новый звонок", callback_data="new_call"),
        InlineKeyboardButton(text="🔄 Повторный звонок", callback_data="repeat_call")
    )
    builder.row(
        InlineKeyboardButton(text="📞 Текущая задача", callback_data="next_task")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Моя таблица", callback_data="my_sheet"),
        InlineKeyboardButton(text="📅 Звонки на сегодня", callback_data="today_calls")
    )
    
    return builder.as_markup()


def get_confirm_inn_keyboard(inn: str) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения ИНН"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="✅ Да, верный", callback_data=f"confirm_inn:{inn}"),
        InlineKeyboardButton(text="❌ Нет, другой", callback_data="wrong_inn")
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel")
    )
    
    return builder.as_markup()


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура отмены"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel"))
    return builder.as_markup()


def get_skip_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с возможностью пропустить"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip"),
        InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel")
    )
    return builder.as_markup()


def get_admin_menu() -> InlineKeyboardMarkup:
    """Меню администратора"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="👥 Управление менеджерами", callback_data="manage_managers")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Сводная таблица", callback_data="supervisor_sheet")
    )
    builder.row(
        InlineKeyboardButton(text="📥 Импорт CSV", callback_data="import_csv")
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить данные (DataNewton)", callback_data="update_datanewton")
    )
    builder.row(
        InlineKeyboardButton(text="🔍 Обновить 1 компанию по ИНН", callback_data="update_one_company")
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")
    )
    
    return builder.as_markup()
