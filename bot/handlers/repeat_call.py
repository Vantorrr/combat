from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import re
from loguru import logger

from bot.keyboards.main import (
    get_cancel_keyboard, 
    get_skip_keyboard,
    get_main_menu
)
from bot.states.call_states import RepeatCallStates
from models.database import Manager, CallSession
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api
from services.ai_advisor import generate_ai_notification
from config import settings

router = Router()


@router.callback_query(F.data == "repeat_call")
async def start_repeat_call(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать процесс повторного звонка"""
    user_id = callback.from_user.id
    
    # Проверяем менеджера
    result = await session.execute(
        select(Manager).where(Manager.telegram_id == user_id)
    )
    manager = result.scalar_one_or_none()
    
    if not manager:
        await callback.answer("❌ Вы не зарегистрированы в системе", show_alert=True)
        return
    
    await state.update_data(
        manager_id=manager.id,
        manager_sheet_id=manager.google_sheet_id,
        manager_name=manager.full_name
    )
    await state.set_state(RepeatCallStates.waiting_for_inn)
    
    # Отправляем новое сообщение вместо редактирования старого, чтобы избежать возможных ошибок edit_text
    await callback.answer()
    await callback.message.answer(
        "🔄 *Повторный звонок*\n\n"
        "Введите ИНН компании, которой звоните повторно:",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )


@router.message(RepeatCallStates.waiting_for_inn)
async def process_repeat_inn(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка ИНН для повторного звонка"""
    raw = (message.text or "").strip()
    inn = re.sub(r"\D", "", raw)
    logger.info(f"[repeat_call] waiting_for_inn from={message.from_user.id} text='{inn}'")
    
    # Базовая валидация ИНН
    if not inn.isdigit() or len(inn) not in [10, 12]:
        await message.answer(
            "❌ Неверный формат ИНН.\n"
            "ИНН должен содержать 10 или 12 цифр.\n\n"
            "Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Проверяем, есть ли компания в базе менеджера
    try:
        data = await state.get_data()
        manager_id = data['manager_id']
        logger.info(f"[repeat_call] searching existing call manager_id={manager_id} inn={inn}")
        result = await session.execute(
            select(CallSession).where(
                CallSession.manager_id == manager_id,
                CallSession.company_inn == inn
            ).order_by(CallSession.created_at.desc())
        )
        existing_call = result.scalars().first()
    except Exception as e:
        logger.error(f"[repeat_call] DB error while searching existing call: {e}")
        await message.answer(
            "⚠️ Внутренняя ошибка при поиске компании. Попробуйте ещё раз или отмените действие.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Переменные для данных компании
    company_name = None
    contact_name = None
    last_comment = None
    sheet_company = None
    
    if existing_call:
        company_name = existing_call.company_name
        contact_name = existing_call.contact_name
        last_comment = existing_call.comment
        await state.update_data(
            inn=inn, 
            company_name=company_name,
            existing_call_id=existing_call.id
        )
        logger.info(f"[repeat_call] found company '{company_name}' for inn={inn}")
    else:
        # Не нашли в локальной БД - ищем в Google Sheets
        logger.info(f"[repeat_call] not in local DB, searching Google Sheets for inn={inn}")
        google_sheets_service = get_google_sheets_service()
        sheet_company = await google_sheets_service.find_company_by_inn(data['manager_sheet_id'], inn)
        
        if sheet_company:
            company_name = sheet_company.get('company_name', 'Не указано')
            contact_name = sheet_company.get('contact_name', '')
            last_comment = sheet_company.get('comment', '')
            await state.update_data(
                inn=inn,
                company_name=company_name
            )
            logger.info(f"[repeat_call] found company in Google Sheets: '{company_name}'")
        else:
            # Нет ни в БД, ни в таблице
            logger.info(f"[repeat_call] company not found anywhere for inn={inn}")
            await state.update_data(
                inn=inn,
                company_name="Не указано"
            )
            await state.set_state(RepeatCallStates.waiting_for_comment)
            await message.answer(
                "ℹ️ Компания с таким ИНН не найдена в вашей базе.\n"
                "Вы всё равно можете добавить комментарий к повторному звонку.",
                reply_markup=get_cancel_keyboard()
            )
            return
    
    # Компания найдена - показываем базовую информацию
    await state.set_state(RepeatCallStates.waiting_for_comment)
    
    comment_preview = last_comment[:200] + "..." if last_comment and len(last_comment) > 200 else (last_comment or "Нет")
    
    await message.answer(
        f"✅ Найдена компания:\n\n"
        f"*{company_name}*\n"
        f"ИНН: {inn}\n"
        f"Контакт: {contact_name or 'Не указан'}\n"
        f"Последний комментарий: {comment_preview}\n\n"
        f"⏳ Загружаю AI-подсказку...",
        parse_mode="Markdown"
    )
    
    # Генерируем AI-подсказку ПЕРЕД звонком
    if settings.openai_api_key:
        try:
            # Получаем свежие данные из DataNewton
            try:
                fresh = await datanewton_api.get_full_company_data(inn)
            except Exception as e:
                fresh = {}
                logger.warning(f"[repeat_call] DataNewton fetch failed: {e}")
            
            # Если нашли в Google Sheets, используем данные оттуда как fallback
            if not fresh and sheet_company:
                fresh = {
                    'revenue': sheet_company.get('revenue', ''),
                    'revenue_previous': sheet_company.get('revenue_previous', ''),
                    'net_profit': sheet_company.get('net_profit', ''),
                    'capital': sheet_company.get('capital', ''),
                    'assets': sheet_company.get('assets', ''),
                    'debit': sheet_company.get('debit', ''),
                    'credit': sheet_company.get('credit', ''),
                    'gov_contracts': sheet_company.get('gov_contracts', ''),
                    'okved': sheet_company.get('okved_main', ''),
                }
            
            # Собираем историю комментариев
            all_comments = []
            if existing_call:
                hist_result = await session.execute(
                    select(CallSession)
                    .where(
                        CallSession.manager_id == data['manager_id'],
                        CallSession.company_inn == inn,
                    )
                    .order_by(CallSession.created_at.asc())
                )
                history = hist_result.scalars().all()
                all_comments = [s.comment for s in history if s.comment]
            elif last_comment:
                all_comments = [last_comment]
            
            ai_text = await generate_ai_notification(
                inn=inn,
                company_name=company_name,
                last_comment=last_comment or "",
                last_call_date=datetime.now(),
                all_comments=all_comments,
                okved_code=fresh.get('okved') if fresh else None,
                okved_name=fresh.get('okved_name') if fresh else None,
                region=fresh.get('region') if fresh else None,
                revenue=fresh.get('revenue') if fresh else None,
                revenue_previous=fresh.get('revenue_previous') if fresh else None,
                net_profit=fresh.get('net_profit') if fresh else None,
                capital=fresh.get('capital') if fresh else None,
                assets=fresh.get('assets') if fresh else None,
                debit=fresh.get('debit') if fresh else None,
                credit=fresh.get('credit') if fresh else None,
                gov_contracts=fresh.get('gov_contracts') if fresh else None,
                arbitration_open_count=fresh.get('arbitration_open_count') if fresh else None,
                arbitration_open_sum=fresh.get('arbitration_open_sum') if fresh else None,
                arbitration_last_doc_date=fresh.get('arbitration_last_doc_date') if fresh else None,
                planned_call_date=datetime.now(),
                contact_name=contact_name,
            )
            
            # Сохраняем расширенные данные для чата
            company_data_full = {
                'revenue': fresh.get('revenue') if fresh else sheet_company.get('revenue'),
                'net_profit': fresh.get('net_profit') if fresh else sheet_company.get('net_profit'),
                'gov_contracts': fresh.get('gov_contracts') if fresh else sheet_company.get('gov_contracts'),
                'region': fresh.get('region') if fresh else '',
                'okved_code': fresh.get('okved') if fresh else sheet_company.get('okved_main'),
                'okved_name': fresh.get('okved_name') if fresh else sheet_company.get('okpd_name'),
            }
            await state.update_data(company_data=company_data_full)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Спросить ИИ (Чат)", callback_data="ask_ai")]
            ])
            
            await message.answer(ai_text, reply_markup=kb)
        except Exception as e:
            logger.warning(f"[repeat_call] AI pre-call notification failed: {e}")
    
    # Запрашиваем комментарий
    await message.answer(
        "💬 Введите комментарий по результатам звонка:",
        reply_markup=get_cancel_keyboard()
    )


@router.message(RepeatCallStates.waiting_for_comment)
async def process_repeat_comment(message: Message, state: FSMContext):
    """Обработка комментария повторного звонка"""
    raw_comment = message.text.strip()
    # Добавляем дату к комментарию
    today = datetime.now().strftime("%d.%m.%y")
    comment = f"{today} - {raw_comment}"
    
    await state.update_data(comment=comment)
    await state.set_state(RepeatCallStates.waiting_for_next_call_date)
    
    await message.answer(
        "📅 Введите дату следующего звонка в формате ДД.ММ.ГГ:\n"
        "(например: 25.12.24)",
        reply_markup=get_skip_keyboard()
    )


@router.message(RepeatCallStates.waiting_for_next_call_date)
async def process_repeat_next_call_date(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка даты следующего звонка для повторного звонка"""
    date_text = message.text.strip()
    
    # Проверка формата даты
    try:
        next_call_date = datetime.strptime(date_text, "%d.%m.%y")
        await state.update_data(next_call_date=date_text)
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты.\n"
            "Используйте формат ДД.ММ.ГГ (например: 25.12.24)",
            reply_markup=get_skip_keyboard()
        )
        return
    
    await save_repeat_call(message, state, session)


@router.callback_query(RepeatCallStates.waiting_for_next_call_date, F.data == "skip")
async def skip_repeat_next_call_date(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Пропустить дату следующего звонка для повторного звонка"""
    await state.update_data(next_call_date="")
    await save_repeat_call(callback.message, state, session)
    await callback.answer()

async def save_repeat_call(message: Message, state: FSMContext, session: AsyncSession):
    """Сохранить данные повторного звонка"""
    data = await state.get_data()
    
    # Сохраняем в базу данных
    call_session = CallSession(
        manager_id=data['manager_id'],
        session_type='repeat',
        company_inn=data['inn'],
        company_name=data['company_name'],
        contact_name='',  # Используем из предыдущего звонка
        contact_phone='',  # Используем из предыдущего звонка
        comment=data['comment'],
        next_call_date=datetime.strptime(data['next_call_date'], "%d.%m.%y") if data.get('next_call_date') else None
    )
    
    session.add(call_session)
    await session.commit()
    
    # Обновляем данные в Google Sheets
    update_data = {
        'comment': data['comment'],
        'next_call_date': data.get('next_call_date', '')
    }
    
    try:
        google_sheets_service = get_google_sheets_service()
        # 1) Обновляем дату следующего звонка и историю комментариев
        success = await google_sheets_service.update_repeat_call(
            data['manager_sheet_id'],
            data['inn'],
            update_data
        )
        # 2) По запросу: на повторном звонке подтягиваем актуальные данные из DataNewton
        try:
            fresh = await datanewton_api.get_full_company_data(data['inn'])
        except Exception as e:
            fresh = {}
            logger.warning(f"[repeat_call] DataNewton refresh failed: {e}")
        if fresh:
            # Обновляем актуальные финданные и справочники в таблице менеджера
            column_updates = {
                'G': fresh.get('revenue_previous', ''),  # выручка позапрошлый год
                'H': fresh.get('revenue', ''),  # выручка прошлый год
                'I': fresh.get('net_profit', ''),  # чистая прибыль прошлый год
                'J': fresh.get('capital', ''),  # капитал и резервы
                'K': fresh.get('assets', ''),  # основные средства
                'L': fresh.get('debit', ''),  # дебиторка
                'M': fresh.get('credit', ''),  # кредиторка
                'N': fresh.get('gov_contracts', ''),  # госконтракты (сумма)
                'O': fresh.get('okved', ''),  # основной ОКВЭД
                'P': fresh.get('okpd_name', ''),  # наименование ОКПД
            }
            await google_sheets_service.update_specific_columns(
                data['manager_sheet_id'],
                data['inn'],
                column_updates
            )
        
        if success:
            # Обновляем сводную таблицу руководителя
            supervisor_data = {
                'company_name': data['company_name'],
                'inn': data['inn'],
                'contact_name': '',  # Берется из существующих данных
                'phone': '',  # Берется из существующих данных
                'comment': update_data['comment'],
                'next_call_date': update_data['next_call_date']
            }
            await google_sheets_service.update_supervisor_sheet(
                data['manager_name'],
                supervisor_data
            )
            
            # Проверяем режим "Текущая задача"
            if data.get('is_task_flow'):
                # Не очищаем state полностью, чтобы сохранить task_index
                # Но нам нужно вернуться в логику tasks.py
                # Просто показываем кнопку "Следующая"
                
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="➡️ Следующая задача", callback_data="task_completed")],
                    [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
                ])
                
                await message.answer(
                    "✅ Данные сохранены! Переходим к следующему?",
                    reply_markup=kb
                )
                # Важно: не делаем state.clear(), но и не оставляем мусор
                # В tasks.py мы ожидаем, что state хранит task_index.
                # Здесь мы в state RepeatCallStates. 
                # Лучше не очищать, tasks.py сам разберется или перезапишет.
                # Но task_index мы потеряли при переходе в RepeatCallStates?
                # Нет, FSMContext хранит данные пока не clear().
                # Мы делали update_data(is_task_flow=True). task_index должен был остаться, если мы не делали clear().
                
                # В repeat_call мы делали set_state, это не стирает данные.
                # Значит task_index там лежит.
                
            else:
                await message.answer(
                    "✅ Данные повторного звонка сохранены!\n\n"
                    f"Компания: *{data['company_name']}*\n"
                    f"След. звонок: {data.get('next_call_date', 'Не указан')}\n\n"
                    "Что дальше?",
                    parse_mode="Markdown",
                    reply_markup=get_main_menu()
                )
                await state.clear()

        else:
            await message.answer(
                "⚠️ Данные сохранены локально, но возникла ошибка при обновлении Google Sheets.\n"
                "Обратитесь к администратору.",
                reply_markup=get_main_menu()
            )
            if not data.get('is_task_flow'):
                await state.clear()
                
    except Exception as e:
        import traceback
        logger.error(f"Error updating Google Sheets: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        if data.get('is_task_flow'):
            # В режиме задач не теряем контекст
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"task_done:{data.get('inn', '')}")],
                [InlineKeyboardButton(text="➡️ Следующая задача", callback_data="task_completed")],
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
            await message.answer(
                f"⚠️ Ошибка при обновлении таблицы: {str(e)[:150]}\n"
                "Данные сохранены локально.",
                reply_markup=kb
            )
        else:
            await message.answer(
                "⚠️ Произошла ошибка при обновлении таблицы.\n"
                "Данные сохранены локально.",
                reply_markup=get_main_menu()
            )
            await state.clear()
