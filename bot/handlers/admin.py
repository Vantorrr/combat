from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from bot.keyboards.main import get_cancel_keyboard, get_admin_menu
from bot.states.call_states import AdminStates
from models.database import Manager
from services.google_sheets import get_google_sheets_service
from config import settings

router = Router()


@router.callback_query(F.data == "admin_menu")
async def back_to_admin_menu(callback: CallbackQuery, state: FSMContext):
    """Вернуться в админ меню"""
    await state.clear()
    await callback.message.edit_text(
        "👨‍💼 *Панель администратора*\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=get_admin_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "manage_managers")
async def manage_managers(callback: CallbackQuery, session: AsyncSession):
    """Управление менеджерами"""
    user_id = callback.from_user.id
    
    if user_id not in settings.admin_ids_list:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    # Получаем список менеджеров
    result = await session.execute(select(Manager))
    managers = result.scalars().all()
    
    builder = InlineKeyboardBuilder()
    
    for manager in managers:
        status = "✅" if manager.is_active else "❌"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} {manager.full_name}",
                callback_data=f"manager:{manager.id}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="➕ Добавить менеджера", callback_data="add_manager"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_menu")
    )
    
    await callback.message.edit_text(
        "👥 *Управление менеджерами*\n\n"
        "Выберите менеджера для редактирования или добавьте нового:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data == "add_manager")
async def add_manager_start(callback: CallbackQuery, state: FSMContext):
    """Начать добавление менеджера"""
    user_id = callback.from_user.id
    
    if user_id not in settings.admin_ids_list:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_manager_id)
    
    await callback.message.edit_text(
        "➕ *Добавление нового менеджера*\n\n"
        "Отправьте Telegram ID менеджера.\n"
        "Менеджер должен написать боту /start и переслать вам свой ID.",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_manager_id)
async def process_manager_id(message: Message, state: FSMContext):
    """Обработка ID менеджера"""
    try:
        manager_telegram_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID.\n"
            "ID должен быть числом. Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(manager_telegram_id=manager_telegram_id)
    await state.set_state(AdminStates.waiting_for_manager_name)
    
    await message.answer(
        "👤 Введите полное имя менеджера:",
        reply_markup=get_cancel_keyboard()
    )


@router.message(AdminStates.waiting_for_manager_name)
async def process_manager_name(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка имени менеджера и создание записи"""
    manager_name = message.text.strip()
    
    if len(manager_name) < 2:
        await message.answer(
            "❌ Слишком короткое имя.\n"
            "Введите полное имя менеджера:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    data = await state.get_data()
    manager_telegram_id = data['manager_telegram_id']
    
    # Проверяем, не существует ли уже такой менеджер
    result = await session.execute(
        select(Manager).where(Manager.telegram_id == manager_telegram_id)
    )
    existing_manager = result.scalar_one_or_none()
    
    if existing_manager:
        await message.answer(
            f"⚠️ Менеджер с ID {manager_telegram_id} уже существует:\n"
            f"{existing_manager.full_name}",
            reply_markup=get_admin_menu()
        )
        await state.clear()
        return
    
    # Создаем Google таблицу для менеджера
    creating_msg = await message.answer("🔄 Создаю таблицу для менеджера...")
    
    try:
        google_sheets_service = get_google_sheets_service()
        sheet_id = await google_sheets_service.create_manager_sheet(manager_name)
        
        if sheet_id:
            # Создаем менеджера в БД
            new_manager = Manager(
                telegram_id=manager_telegram_id,
                full_name=manager_name,
                google_sheet_id=sheet_id,
                is_active=True
            )
            
            session.add(new_manager)
            await session.commit()
            
            await creating_msg.edit_text(
                f"✅ Менеджер успешно добавлен!\n\n"
                f"Имя: {manager_name}\n"
                f"Telegram ID: {manager_telegram_id}\n"
                f"Google таблица создана\n\n"
                f"Менеджер может начать работу, написав боту /start",
                reply_markup=get_admin_menu()
            )
    except Exception as e:
        logger.error(f"Error creating manager: {e}")
        await creating_msg.edit_text(
            f"❌ Ошибка при создании Google таблицы:\n{str(e)[:300]}\n\n"
            "Проверьте настройки или обратитесь к разработчику.",
            reply_markup=get_admin_menu()
        )
    
    await state.clear()


@router.callback_query(F.data.startswith("manager:"))
async def manage_specific_manager(callback: CallbackQuery, session: AsyncSession):
    """Управление конкретным менеджером"""
    user_id = callback.from_user.id
    
    if user_id not in settings.admin_ids_list:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    manager_id = int(callback.data.split(":")[1])
    
    result = await session.execute(
        select(Manager).where(Manager.id == manager_id)
    )
    manager = result.scalar_one_or_none()
    
    if not manager:
        await callback.answer("❌ Менеджер не найден", show_alert=True)
        return
    
    builder = InlineKeyboardBuilder()
    
    if manager.is_active:
        builder.row(
            InlineKeyboardButton(
                text="🚫 Деактивировать", 
                callback_data=f"deactivate_manager:{manager_id}"
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="✅ Активировать", 
                callback_data=f"activate_manager:{manager_id}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(
            text="📊 Открыть таблицу", 
            url=f"https://docs.google.com/spreadsheets/d/{manager.google_sheet_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="manage_managers")
    )
    
    status = "Активен" if manager.is_active else "Неактивен"
    
    await callback.message.edit_text(
        f"👤 *Менеджер: {manager.full_name}*\n\n"
        f"Telegram ID: `{manager.telegram_id}`\n"
        f"Статус: {status}\n"
        f"Дата регистрации: {manager.created_at.strftime('%d.%m.%y')}\n",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("activate_manager:"))
async def activate_manager(callback: CallbackQuery, session: AsyncSession):
    """Активировать менеджера"""
    manager_id = int(callback.data.split(":")[1])
    
    result = await session.execute(
        select(Manager).where(Manager.id == manager_id)
    )
    manager = result.scalar_one_or_none()
    
    if manager:
        manager.is_active = True
        await session.commit()
        await callback.answer("✅ Менеджер активирован", show_alert=True)
        await manage_specific_manager(callback, session)
    else:
        await callback.answer("❌ Менеджер не найден", show_alert=True)


@router.callback_query(F.data.startswith("deactivate_manager:"))
async def deactivate_manager(callback: CallbackQuery, session: AsyncSession):
    """Деактивировать менеджера"""
    manager_id = int(callback.data.split(":")[1])
    
    result = await session.execute(
        select(Manager).where(Manager.id == manager_id)
    )
    manager = result.scalar_one_or_none()
    
    if manager:
        manager.is_active = False
        await session.commit()
        await callback.answer("🚫 Менеджер деактивирован", show_alert=True)
        await manage_specific_manager(callback, session)
    else:
        await callback.answer("❌ Менеджер не найден", show_alert=True)


@router.callback_query(F.data == "supervisor_sheet") 
async def show_supervisor_sheet(callback: CallbackQuery):
    """Показать ссылку на сводную таблицу"""
    user_id = callback.from_user.id
    
    if user_id not in settings.admin_ids_list:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    sheet_url = f"https://docs.google.com/spreadsheets/d/{settings.supervisor_sheet_id}"
    
    await callback.message.answer(
        f"📊 Сводная таблица руководителя:\n\n"
        f"[Открыть сводную таблицу]({sheet_url})\n\n"
        f"В этой таблице собраны данные от всех менеджеров.",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await callback.answer()


@router.callback_query(F.data == "admin_menu")
async def show_admin_menu(callback: CallbackQuery):
    """Показать меню администратора"""
    user_id = callback.from_user.id
    
    if user_id not in settings.admin_ids_list:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        "👋 Меню администратора\n\n"
        "Выберите действие:",
        reply_markup=get_admin_menu()
    )
    await callback.answer()
