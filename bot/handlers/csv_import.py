import csv
import io
from datetime import datetime
from typing import List, Dict, Any

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from bot.states.call_states import AdminStates
from bot.keyboards.main import get_cancel_keyboard, get_admin_menu
from models.database import Manager
from services.google_sheets import get_google_sheets_service

router = Router()


def _format_imported_comments(row):
    """Форматировать комментарии из CSV в единую историю"""
    comments = []
    today = datetime.now().strftime('%d.%m.%y')
    
    # Комментарий 1
    if len(row) > 6 and row[6].strip():
        comments.append(f"{today} - {row[6].strip()}")
    
    # Комментарий 2 (если есть)
    if len(row) > 7 and row[7].strip():
        comments.append(row[7].strip())
    
    # Комментарий 3 (если есть)
    if len(row) > 8 and row[8].strip():
        comments.append(row[8].strip())
    
    return "\n---\n".join(comments) if comments else ""


@router.callback_query(F.data == "import_csv")
async def start_csv_import(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать процесс импорта CSV"""
    # Получаем список активных менеджеров
    result = await session.execute(
        select(Manager).where(Manager.is_active == True).order_by(Manager.full_name)
    )
    managers = result.scalars().all()
    
    if not managers:
        await callback.answer("Нет активных менеджеров", show_alert=True)
        return
    
    # Создаем клавиатуру с менеджерами
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for manager in managers:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"📤 {manager.full_name}",
                callback_data=f"csv_manager:{manager.id}"
            )
        ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")
    ])
    
    await state.set_state(AdminStates.waiting_for_csv_manager)
    
    await callback.message.edit_text(
        "📥 *Импорт CSV*\n\n"
        "Выберите менеджера, для которого загружаете данные:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(AdminStates.waiting_for_csv_manager, F.data.startswith("csv_manager:"))
async def select_csv_manager(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбор менеджера для импорта"""
    manager_id = int(callback.data.split(":")[1])
    
    # Получаем менеджера
    result = await session.execute(
        select(Manager).where(Manager.id == manager_id)
    )
    manager = result.scalar_one_or_none()
    
    if not manager:
        await callback.answer("Менеджер не найден", show_alert=True)
        return
    
    await state.update_data(
        csv_manager_id=manager.id,
        csv_manager_name=manager.full_name,
        csv_manager_sheet_id=manager.google_sheet_id
    )
    await state.set_state(AdminStates.waiting_for_csv_file)
    
    await callback.message.edit_text(
        f"📥 *Импорт данных для менеджера:*\n{manager.full_name}\n\n"
        "Отправьте CSV файл со следующими колонками:\n"
        "1. Наименование компании\n"
        "2. ИНН\n"
        "3. ФИО ЛПР\n"
        "4. Телефон\n"
        "5. Дата первого звонка (ДД.ММ.ГГГГ)\n"
        "6. Дата звонка будущая (ДД.ММ.ГГГГ)\n"
        "7. Комментарий 1\n\n"
        "📝 Формат: UTF-8, разделитель - запятая или точка с запятой",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_csv_file, F.document)
async def process_csv_file(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка CSV файла"""
    document = message.document
    
    # Проверяем расширение файла
    if not document.file_name.lower().endswith('.csv'):
        await message.answer(
            "❌ Пожалуйста, отправьте файл в формате CSV",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await message.answer("⏳ Обрабатываю файл...")
    
    try:
        # Скачиваем файл
        file_info = await message.bot.get_file(document.file_id)
        file_content = await message.bot.download_file(file_info.file_path)
        
        # Читаем содержимое как текст
        content = file_content.read().decode('utf-8-sig')  # utf-8-sig убирает BOM
        
        # Определяем разделитель
        delimiter = ';' if ';' in content.split('\n')[0] else ','
        
        # Парсим CSV
        csv_reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        rows = list(csv_reader)
        
        if len(rows) < 2:  # Минимум заголовок + 1 строка данных
            await message.answer(
                "❌ Файл пустой или содержит только заголовки",
                reply_markup=get_admin_menu()
            )
            await state.clear()
            return
        
        # Пропускаем заголовок и обрабатываем данные
        data_rows = rows[1:] if len(rows[0]) >= 7 else rows  # Если первая строка похожа на заголовок
        
        # Получаем данные из состояния
        state_data = await state.get_data()
        manager_name = state_data['csv_manager_name']
        sheet_id = state_data['csv_manager_sheet_id']
        
        # Проверяем наличие таблицы у менеджера
        if not sheet_id:
            await message.answer(
                "❌ У менеджера нет привязанной таблицы Google Sheets",
                reply_markup=get_admin_menu()
            )
            await state.clear()
            return
        
        # Обрабатываем строки
        google_sheets_service = get_google_sheets_service()
        success_count = 0
        error_count = 0
        
        for i, row in enumerate(data_rows, 1):
            try:
                # Минимум 7 колонок
                if len(row) < 7:
                    logger.warning(f"Row {i} has less than 7 columns: {row}")
                    error_count += 1
                    continue
                
                # Подготавливаем данные
                call_data = {
                    'company_name': row[0].strip(),
                    'inn': row[1].strip(),
                    'contact_name': row[2].strip() if len(row) > 2 else '',
                    'phone': row[3].strip() if len(row) > 3 else '',
                    'first_call_date': row[4].strip() if len(row) > 4 else datetime.now().strftime('%d.%m.%y'),
                    'next_call_date': row[5].strip() if len(row) > 5 else '',
                    'comment': _format_imported_comments(row),
                    'revenue': row[9].strip() if len(row) > 9 else '',
                    'revenue_previous': row[10].strip() if len(row) > 10 else '',
                    'capital': row[11].strip() if len(row) > 11 else '',
                    'assets': row[12].strip() if len(row) > 12 else '',
                    'debit': row[13].strip() if len(row) > 13 else '',
                    'credit': row[14].strip() if len(row) > 14 else '',
                    'region': row[15].strip() if len(row) > 15 else '',
                    'okved': row[16].strip() if len(row) > 16 else '',
                    'okved_main': row[17].strip() if len(row) > 17 else '',
                    'gov_contracts': row[18].strip() if len(row) > 18 else '',
                    'arbitration': row[19].strip() if len(row) > 19 else '',
                    'bankruptcy': row[20].strip() if len(row) > 20 else '',
                    'email': row[22].strip() if len(row) > 22 else '',
                }
                
                # Добавляем в таблицу менеджера
                await google_sheets_service.add_new_call(sheet_id, call_data)
                
                # Добавляем в сводную таблицу
                await google_sheets_service.update_supervisor_sheet(manager_name, call_data)
                
                success_count += 1
                
            except Exception as e:
                logger.error(f"Error processing row {i}: {e}")
                error_count += 1
        
        # Отправляем результат
        result_message = (
            f"✅ *Импорт завершен!*\n\n"
            f"Менеджер: {manager_name}\n"
            f"Успешно импортировано: {success_count} записей\n"
        )
        
        if error_count > 0:
            result_message += f"Ошибок: {error_count} записей\n"
        
        result_message += f"\n[Открыть таблицу менеджера](https://docs.google.com/spreadsheets/d/{sheet_id})"
        
        await message.answer(
            result_message,
            parse_mode="Markdown",
            reply_markup=get_admin_menu(),
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error processing CSV: {e}")
        await message.answer(
            f"❌ Ошибка при обработке файла:\n{str(e)}",
            reply_markup=get_admin_menu()
        )
    
    await state.clear()


@router.message(AdminStates.waiting_for_csv_file)
async def invalid_csv_file(message: Message, state: FSMContext):
    """Обработка невалидного сообщения вместо файла"""
    await message.answer(
        "❌ Пожалуйста, отправьте CSV файл как документ",
        reply_markup=get_cancel_keyboard()
    )
