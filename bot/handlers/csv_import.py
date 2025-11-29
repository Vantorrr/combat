import asyncio
import random
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
from services.datanewton_api import datanewton_api

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


async def import_csv_task(data_rows, manager_name, sheet_id, bot, chat_id):
    """
    Фоновая задача для построчного импорта CSV с защитой от Rate Limit.
    """
    google_sheets_service = get_google_sheets_service()
    success_count = 0
    error_count = 0
    
    logger.info(f"Background CSV import started for {manager_name} ({len(data_rows)} rows)")

    for i, row in enumerate(data_rows, 1):
        try:
            # Минимум 7 колонок
            if len(row) < 7:
                logger.warning(f"Row {i} has less than 7 columns: {row}")
                error_count += 1
                continue
            
            # Подготавливаем базовые данные
            inn = row[1].strip()
            company_name = row[0].strip()
            
            # Пробуем обогатить данные через API (с повторами при ошибках/429)
            company_api_data = {}
            if inn:
                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        # Задержка перед запросом к API (плавающая)
                        await asyncio.sleep(0.6 + random.uniform(0, 0.4))
                        
                        api_result = await datanewton_api.get_full_company_data(inn)
                        
                        if api_result:
                            company_api_data = api_result
                            break # Успех
                        else:
                            # Если API вернул пустоту (возможно ошибка), пробуем retry
                            if attempt < max_retries - 1:
                                raise ValueError("API returned None")
                            
                    except Exception as e:
                        if attempt < max_retries - 1:
                            wait_time = (2 ** attempt) + random.uniform(0, 1)
                            logger.warning(f"Retry {attempt+1}/{max_retries} for INN {inn}: {e}. Wait {wait_time:.1f}s")
                            await asyncio.sleep(wait_time)
                        else:
                            logger.error(f"Max retries reached for INN {inn}")

            # Логика извлечения из CSV для отладки
            csv_gov = (row[13].strip() if len(row) > 13 and len(row) > 15 else (row[18].strip() if len(row) > 18 else 'NONE'))
            csv_okpd_name = (row[15].strip() if len(row) > 15 and len(row) > 15 else 'NONE')
            # logger.info(f"CSV Fallback for {inn}: Gov={csv_gov}, OKPD_Name={csv_okpd_name}") 

            call_data = {
                'company_name': company_api_data.get('name') or company_name,
                'inn': inn,
                'contact_name': row[2].strip() if len(row) > 2 else '',
                'phone': row[3].strip() if len(row) > 3 else '',
                # ЛОГИКА ДАТЫ ПЕРВОГО ЗВОНКА:
                # 1. Проверяем колонку 16 (Q) - как в экспорте из Google Sheets
                # 2. Проверяем колонку 4 (E) - как в инструкции бота (хотя там часто "Дата след. звонка")
                # 3. Если ничего нет - ставим сегодня
                'first_call_date': (
                    row[16].strip() if len(row) > 16 and row[16].strip() else (
                        row[4].strip() if len(row) > 4 and row[4].strip() else datetime.now().strftime('%d.%m.%y')
                    )
                ),
                'next_call_date': row[4].strip() if len(row) > 4 else '', # В экспорте Google Sheets дата след. звонка обычно в E (index 4)
                'comment': _format_imported_comments(row),
                
                # ЛОГИКА ФИНАНСОВ И ГОСКОНТРАКТОВ:
                # Приоритет: 1. API -> 2. Экспорт из Google Sheets (индексы 6-13) -> 3. Старая схема (индексы 9-18)
                
                'revenue': str(company_api_data.get('revenue') or 
                               (row[7].strip() if len(row) > 7 and len(row) > 15 else (row[9].strip() if len(row) > 9 else ''))),
                               
                'revenue_previous': str(company_api_data.get('revenue_previous') or 
                                        (row[6].strip() if len(row) > 6 and len(row) > 15 else (row[10].strip() if len(row) > 10 else ''))),
                                        
                'capital': str(company_api_data.get('capital') or 
                               (row[9].strip() if len(row) > 9 and len(row) > 15 else (row[11].strip() if len(row) > 11 else ''))),
                               
                'assets': str(company_api_data.get('assets') or 
                              (row[10].strip() if len(row) > 10 and len(row) > 15 else (row[12].strip() if len(row) > 12 else ''))),
                              
                'debit': str(company_api_data.get('debit') or 
                             (row[11].strip() if len(row) > 11 and len(row) > 15 else (row[13].strip() if len(row) > 13 else ''))),
                             
                'credit': str(company_api_data.get('credit') or 
                              (row[12].strip() if len(row) > 12 and len(row) > 15 else (row[14].strip() if len(row) > 14 else ''))),
                              
                'net_profit': str(company_api_data.get('net_profit') or 
                                  (row[8].strip() if len(row) > 8 and len(row) > 15 else '')),
                                  
                'gov_contracts': str(company_api_data.get('gov_contracts') or 
                                     (row[13].strip() if len(row) > 13 and len(row) > 15 else (row[18].strip() if len(row) > 18 else ''))),
                                     
                'okved_main': str(company_api_data.get('okved') or 
                                  (row[14].strip() if len(row) > 14 and len(row) > 15 else (row[17].strip() if len(row) > 17 else ''))),
                                  
                'okpd_name': str(company_api_data.get('okpd_name') or 
                                 (row[15].strip() if len(row) > 15 and len(row) > 15 else '')),
            }
            
            # Добавляем в таблицу менеджера
            await google_sheets_service.add_new_call(sheet_id, call_data)
            
            # Задержка 1 секунда между запросами к Google API, чтобы не ловить 429 ошибку
            await asyncio.sleep(1.5)

            # Добавляем в сводную таблицу
            await google_sheets_service.update_supervisor_sheet(manager_name, call_data)
            
            # Еще одна задержка для безопасности
            await asyncio.sleep(1.5)
            
            success_count += 1
            
        except Exception as e:
            logger.error(f"Error processing row {i}: {e}")
            error_count += 1
            
    # Отправляем результат в чат
    result_message = (
        f"✅ *Импорт завершен (фоновая задача)!*\n\n"
        f"Менеджер: {manager_name}\n"
        f"Успешно импортировано: {success_count} записей\n"
    )
    
    if error_count > 0:
        result_message += f"Ошибок: {error_count} записей\n"
    
    result_message += f"\n[Открыть таблицу менеджера](https://docs.google.com/spreadsheets/d/{sheet_id})"
    
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=result_message,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Failed to send import completion message: {e}")


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
    
    await message.answer("⏳ Скачиваю и читаю файл...")
    
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
        
        # Запускаем фоновую задачу
        asyncio.create_task(
            import_csv_task(
                data_rows=data_rows, 
                manager_name=manager_name, 
                sheet_id=sheet_id,
                bot=message.bot,
                chat_id=message.chat.id
            )
        )
        
        # Сразу отвечаем пользователю
        await message.answer(
            f"✅ *Импорт запущен в фоновом режиме!* (строк: {len(data_rows)})\n\n"
            "⏳ Это займет время (примерно 3-5 секунд на строку, чтобы заполнить все данные).\n"
            "🔔 Я пришлю уведомление, когда закончу.\n"
            "Вы можете продолжать пользоваться ботом.",
            parse_mode="Markdown",
            reply_markup=get_admin_menu()
        )
        
    except Exception as e:
        logger.error(f"Error preparing CSV import: {e}")
        await message.answer(
            f"❌ Ошибка при чтении файла:\n{str(e)}",
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
