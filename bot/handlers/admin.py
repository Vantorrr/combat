from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger
import asyncio

from bot.keyboards.main import get_cancel_keyboard, get_admin_menu
from bot.states.call_states import AdminStates
from models.database import Manager
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api
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
    
    # Кнопка удаления (только если деактивирован)
    if not manager.is_active:
        builder.row(
            InlineKeyboardButton(
                text="🗑 Удалить навсегда", 
                callback_data=f"delete_manager_confirm:{manager_id}"
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


@router.callback_query(F.data.startswith("delete_manager_confirm:"))
async def confirm_delete_manager(callback: CallbackQuery, session: AsyncSession):
    """Подтверждение удаления менеджера"""
    manager_id = int(callback.data.split(":")[1])
    
    result = await session.execute(
        select(Manager).where(Manager.id == manager_id)
    )
    manager = result.scalar_one_or_none()
    
    if not manager:
        await callback.answer("❌ Менеджер не найден", show_alert=True)
        return
        
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💣 ДА, УДАЛИТЬ", 
            callback_data=f"delete_manager_final:{manager_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔙 Нет, отмена", 
            callback_data=f"manager:{manager_id}"
        )
    )
    
    await callback.message.edit_text(
        f"⚠️ *ВНИМАНИЕ! УДАЛЕНИЕ МЕНЕДЖЕРА*\n\n"
        f"Вы собираетесь удалить менеджера: *{manager.full_name}*\n"
        f"ID: `{manager.telegram_id}`\n\n"
        f"❗ Это действие необратимо. Менеджер пропадет из базы бота.\n"
        f"Его Google-таблица ОСТАНЕТСЯ (бот её не удалит), но связь с ней будет потеряна.\n\n"
        f"Вы уверены?",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_manager_final:"))
async def final_delete_manager(callback: CallbackQuery, session: AsyncSession):
    """Финальное удаление менеджера"""
    manager_id = int(callback.data.split(":")[1])
    
    result = await session.execute(
        select(Manager).where(Manager.id == manager_id)
    )
    manager = result.scalar_one_or_none()
    
    if manager:
        manager_name = manager.full_name
        await session.delete(manager)
        await session.commit()
        
        await callback.message.edit_text(
            f"🗑 Менеджер *{manager_name}* успешно удален из базы.",
            parse_mode="Markdown",
            reply_markup=get_admin_menu()
        )
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

# --- New Logic for DataNewton Update ---

async def background_update_task(manager_name, sheet_id, bot, chat_id):
    """
    Фоновая задача для обновления данных из DataNewton в таблице менеджера.
    """
    google_sheets = get_google_sheets_service()
    updated_count = 0
    error_count = 0
    skipped_count = 0
    
    logger.info(f"Background DataNewton update started for {manager_name}")
    
    try:
        # 1. Читаем всю таблицу
        result = google_sheets.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='A:P' # Читаем до P (ОКПД)
        ).execute()
        values = result.get('values', [])
        
        if len(values) < 2:
            await bot.send_message(chat_id, f"⚠️ Таблица менеджера {manager_name} пуста (кроме заголовков).", parse_mode="Markdown")
            return

        total_rows = len(values) - 1
        await bot.send_message(chat_id, f"🔄 Начинаю проверку {total_rows} строк для {manager_name}...\n\n_Это может занять несколько минут._", parse_mode="Markdown")

        # 2. Итерируемся по строкам
        for i, row in enumerate(values[1:], 1): # i - это реальный индекс в списке values (без заголовка), +1 чтобы нумерация с 1
            try:
                inn = row[1].strip() if len(row) > 1 else ""
                
                if not inn:
                    skipped_count += 1
                    continue
                
                needs_update = False
                
                # Проверяем выручку (H - 7)
                revenue = row[7].strip() if len(row) > 7 else ""
                # Если пустая или 0 - обновляем
                if not revenue or revenue == "0" or revenue == "0 ₽":
                    needs_update = True
                
                # Проверяем госконтракты (N - 13)
                gov = row[13].strip() if len(row) > 13 else ""
                if not gov: 
                    needs_update = True
                    
                # Проверяем ОКПД (P - 15)
                okpd = row[15].strip() if len(row) > 15 else ""
                if not okpd:
                    needs_update = True

                if not needs_update:
                    skipped_count += 1
                    continue

                # 3. Запрашиваем данные
                await asyncio.sleep(0.5) # Anti-rate limit
                fresh_data = await datanewton_api.get_full_company_data(inn)
                
                if fresh_data:
                    # 4. Обновляем в таблице
                    column_updates = {
                        'G': fresh_data.get('revenue_previous', ''),
                        'H': fresh_data.get('revenue', ''),
                        'I': fresh_data.get('net_profit', ''),
                        'J': fresh_data.get('capital', ''),
                        'K': fresh_data.get('assets', ''),
                        'L': fresh_data.get('debit', ''),
                        'M': fresh_data.get('credit', ''),
                        'N': fresh_data.get('gov_contracts', ''),
                        'O': fresh_data.get('okved', ''),
                        'P': fresh_data.get('okpd_name', ''),
                    }
                    
                    success = await google_sheets.update_specific_columns(sheet_id, inn, column_updates)
                    
                    if success:
                        updated_count += 1
                    else:
                        error_count += 1
                else:
                    # API ничего не вернул
                    skipped_count += 1
                    
            except Exception as e:
                logger.error(f"Error updating row {i} for {manager_name}: {e}")
                error_count += 1
            
            # Лог каждые 10 строк
            if i % 10 == 0:
                logger.info(f"Processed {i}/{total_rows} for {manager_name}...")
        
        # 5. Отчет
        await bot.send_message(
            chat_id,
            f"✅ *Обновление завершено для {manager_name}*\n\n"
            f"Всего строк: {total_rows}\n"
            f"Обновлено: {updated_count}\n"
            f"Пропущено (актуально): {skipped_count}\n"
            f"Ошибок: {error_count}",
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Global error in update task: {e}")
        await bot.send_message(chat_id, f"❌ Критическая ошибка обновления: {e}")


@router.callback_query(F.data == "update_datanewton")
async def start_update_datanewton(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать процесс обновления данных"""
    user_id = callback.from_user.id
    
    if user_id not in settings.admin_ids_list:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return

    # Получаем список активных менеджеров
    result = await session.execute(
        select(Manager).where(Manager.is_active == True).order_by(Manager.full_name)
    )
    managers = result.scalars().all()
    
    if not managers:
        await callback.answer("Нет активных менеджеров", show_alert=True)
        return
    
    # Создаем клавиатуру с менеджерами
    builder = InlineKeyboardBuilder()
    for manager in managers:
        builder.row(
            InlineKeyboardButton(
                text=f"🔄 {manager.full_name}",
                callback_data=f"update_manager:{manager.id}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")
    )
    
    await state.set_state(AdminStates.waiting_for_update_manager)
    
    await callback.message.edit_text(
        "🔄 *Обновление данных (DataNewton)*\n\n"
        "Эта функция пройдет по таблице менеджера и попытается загрузить недостающие финансовые данные, госконтракты и ОКПД.\n\n"
        "Выберите менеджера:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(AdminStates.waiting_for_update_manager, F.data.startswith("update_manager:"))
async def select_update_manager(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор менеджера для обновления"""
    manager_id = int(callback.data.split(":")[1])
    
    # Получаем менеджера
    result = await session.execute(
        select(Manager).where(Manager.id == manager_id)
    )
    manager = result.scalar_one_or_none()
    
    if not manager:
        await callback.answer("Менеджер не найден", show_alert=True)
        return
    
    # Запускаем фоновую задачу
    asyncio.create_task(
        background_update_task(
            manager_name=manager.full_name,
            sheet_id=manager.google_sheet_id,
            bot=callback.message.bot,
            chat_id=callback.message.chat.id
        )
    )
    
    await callback.message.edit_text(
        f"✅ *Задача запущена!* \n"
        f"Менеджер: {manager.full_name}\n\n"
        "Я буду проверять строки и догружать данные, если они отсутствуют.\n"
        "По завершении пришлю отчет.\n\n"
        "Вы можете продолжать работу.",
        parse_mode="Markdown",
        reply_markup=get_admin_menu()
    )
    await state.clear()


@router.message(F.text == "/test_missed_calls")
async def test_missed_calls_report(message: Message, session: AsyncSession):
    """Ручной запуск проверки недозвонов (только для админов)"""
    user_id = message.from_user.id
    
    if user_id not in settings.admin_ids_list:
        await message.answer("❌ Недостаточно прав")
        return
    
    await message.answer("🔍 Запускаю проверку недозвонов...")
    
    try:
        google_sheets = get_google_sheets_service()
        result = await session.execute(select(Manager).where(Manager.is_active == True))
        managers = result.scalars().all()
        
        report_lines = [f"📊 *Отчет о недозвонах*\n\nВсего менеджеров: {len(managers)}\n"]
        
        for manager in managers:
            if not manager.google_sheet_id:
                report_lines.append(f"• {manager.full_name}: ⚠️ Нет sheet_id")
                continue
            
            try:
                missed_calls = await google_sheets.get_missed_calls(manager.google_sheet_id)
                if missed_calls:
                    report_lines.append(f"• {manager.full_name}: ❌ {len(missed_calls)} недозвонов")
                else:
                    report_lines.append(f"• {manager.full_name}: ✅ Все звонки совершены")
            except Exception as e:
                report_lines.append(f"• {manager.full_name}: ⚠️ Ошибка: {str(e)[:50]}")
        
        report_text = "\n".join(report_lines)
        await message.answer(report_text, parse_mode="Markdown")
        
    except Exception as e:
        import traceback
        logger.error(f"Test missed calls failed: {e}")
        logger.error(traceback.format_exc())
        await message.answer(f"❌ Ошибка: {str(e)[:200]}")


@router.callback_query(F.data == "update_one_company")
async def update_one_company_start(callback: CallbackQuery, state: FSMContext):
    """Начало обновления одной компании по ИНН"""
    user_id = callback.from_user.id
    
    if user_id not in settings.admin_ids_list:
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🔍 *Обновление одной компании*\n\n"
        "Отправьте ИНН компании для обновления данных:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_menu")]
        ])
    )
    await state.set_state(AdminStates.waiting_for_update_one_inn)
    await callback.answer()


@router.message(AdminStates.waiting_for_update_one_inn)
async def process_update_one_inn(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка ИНН для обновления одной компании"""
    inn = message.text.strip()
    
    # Валидация ИНН
    if not inn.isdigit() or len(inn) not in [10, 12]:
        await message.answer("❌ Некорректный ИНН. Введите 10 или 12 цифр:")
        return
    
    await state.update_data(update_inn=inn)
    
    # Получаем список менеджеров
    result = await session.execute(select(Manager).where(Manager.is_active == True))
    managers = result.scalars().all()
    
    if not managers:
        await message.answer("❌ Нет активных менеджеров")
        await state.clear()
        return
    
    # Создаем клавиатуру выбора менеджера
    builder = InlineKeyboardBuilder()
    for manager in managers:
        builder.row(
            InlineKeyboardButton(
                text=f"{manager.full_name}",
                callback_data=f"update_one_mgr:{manager.id}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_menu")
    )
    
    await message.answer(
        f"📋 ИНН: `{inn}`\n\n"
        f"Выберите менеджера, в чьей таблице обновить данные:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.waiting_for_update_one_manager)


@router.callback_query(F.data.startswith("update_one_mgr:"))
async def process_update_one_manager(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обновление данных одной компании у выбранного менеджера"""
    manager_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    inn = data.get('update_inn')
    
    if not inn:
        await callback.answer("❌ Ошибка: ИНН не найден", show_alert=True)
        await state.clear()
        return
    
    # Получаем менеджера
    result = await session.execute(select(Manager).where(Manager.id == manager_id))
    manager = result.scalar_one_or_none()
    
    if not manager or not manager.google_sheet_id:
        await callback.answer("❌ Менеджер или таблица не найдены", show_alert=True)
        await state.clear()
        return
    
    await callback.message.edit_text(
        f"⏳ Обновляю данные компании `{inn}` в таблице {manager.full_name}...\n\n"
        f"Это может занять несколько секунд.",
        parse_mode="Markdown"
    )
    
    try:
        google_sheets = get_google_sheets_service()
        
        # 1. Проверяем что компания есть в таблице
        company_data = await google_sheets.find_company_by_inn(manager.google_sheet_id, inn)
        
        if not company_data:
            await callback.message.edit_text(
                f"❌ Компания с ИНН `{inn}` не найдена в таблице {manager.full_name}",
                parse_mode="Markdown",
                reply_markup=get_admin_menu()
            )
            await state.clear()
            return
        
        # 2. Получаем свежие данные из DataNewton
        fresh_data = await datanewton_api.get_full_company_data(inn)
        
        if not fresh_data:
            await callback.message.edit_text(
                f"❌ Не удалось получить данные из DataNewton для ИНН `{inn}`",
                parse_mode="Markdown",
                reply_markup=get_admin_menu()
            )
            await state.clear()
            return
        
        # 3. Обновляем данные в таблице менеджера
        column_updates = {
            'G': fresh_data.get('revenue_previous', ''),
            'H': fresh_data.get('revenue', ''),
            'I': fresh_data.get('net_profit', ''),
            'J': fresh_data.get('capital', ''),
            'K': fresh_data.get('assets', ''),
            'L': fresh_data.get('debit', ''),
            'M': fresh_data.get('credit', ''),
            'N': fresh_data.get('gov_contracts', ''),
            'O': fresh_data.get('okved', ''),
            'P': fresh_data.get('okpd_name', ''),
        }
        
        success = await google_sheets.update_specific_columns(
            manager.google_sheet_id,
            inn,
            column_updates
        )
        
        if not success:
            await callback.message.edit_text(
                f"❌ Ошибка при обновлении таблицы менеджера",
                parse_mode="Markdown",
                reply_markup=get_admin_menu()
            )
            await state.clear()
            return
        
        # 4. Обновляем сводную таблицу
        call_data = {
            'inn': inn,
            'company_name': company_data.get('company_name', ''),
            'contact_name': company_data.get('contact_name', ''),
            'phone': company_data.get('phone', ''),
            'next_call_date': company_data.get('next_call_date', ''),
            'comment': f"Обновлены данные DataNewton",
            'revenue_previous': fresh_data.get('revenue_previous', ''),
            'revenue': fresh_data.get('revenue', ''),
            'net_profit': fresh_data.get('net_profit', ''),
            'capital': fresh_data.get('capital', ''),
            'assets': fresh_data.get('assets', ''),
            'debit': fresh_data.get('debit', ''),
            'credit': fresh_data.get('credit', ''),
            'gov_contracts': fresh_data.get('gov_contracts', ''),
            'okved_main': fresh_data.get('okved', ''),
            'okpd_name': fresh_data.get('okpd_name', ''),
        }
        
        await google_sheets.update_supervisor_sheet(
            manager_name=manager.full_name,
            call_data=call_data,
            check_headers=False
        )
        
        await callback.message.edit_text(
            f"✅ *Данные успешно обновлены!*\n\n"
            f"ИНН: `{inn}`\n"
            f"Компания: {company_data.get('company_name', 'Н/Д')}\n"
            f"Менеджер: {manager.full_name}\n\n"
            f"Обновлено:\n"
            f"• Таблица менеджера ✅\n"
            f"• Сводная таблица ✅",
            parse_mode="Markdown",
            reply_markup=get_admin_menu()
        )
        
    except Exception as e:
        logger.error(f"Error updating one company: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await callback.message.edit_text(
            f"❌ Ошибка при обновлении:\n{str(e)[:200]}",
            reply_markup=get_admin_menu()
        )
    
    await state.clear()
