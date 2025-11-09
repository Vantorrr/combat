from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
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
    
    if existing_call:
        await state.update_data(
            inn=inn, 
            company_name=existing_call.company_name,
            existing_call_id=existing_call.id
        )
        logger.info(f"[repeat_call] found company '{existing_call.company_name}' for inn={inn}")
        await state.set_state(RepeatCallStates.waiting_for_comment)
        
        await message.answer(
            f"✅ Найдена компания:\n\n"
            f"*{existing_call.company_name}*\n"
            f"ИНН: {inn}\n"
            f"Последний контакт: {existing_call.contact_name}\n"
            f"Последний комментарий: {existing_call.comment[:100]}...\n\n"
            f"💬 Введите комментарий по результатам повторного звонка:",
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard()
        )
    else:
        logger.info(f"[repeat_call] no company found for inn={inn} manager_id={data.get('manager_id')}")
        # Разрешаем продолжить, даже если компания не найдена в локальной базе
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
            column_updates = {
                'G': fresh.get('revenue', ''),
                'H': fresh.get('revenue_previous', ''),
                'I': fresh.get('capital', ''),
                'J': fresh.get('assets', ''),
                'K': fresh.get('debit', ''),
                'L': fresh.get('credit', ''),
                'M': fresh.get('region', ''),
                'N': fresh.get('okved', ''),
                'O': fresh.get('okved', ''),
                'P': fresh.get('gov_contracts', ''),
                'Q': fresh.get('arbitration_open_count', ''),
                'R': fresh.get('arbitration_open_sum', ''),
                'S': fresh.get('arbitration_last_doc_date', ''),
                'U': fresh.get('okpd', ''),
                'V': fresh.get('okpd_name', ''),
                'W': fresh.get('okved_name', ''),
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
            
            await message.answer(
                "✅ Данные повторного звонка сохранены!\n\n"
                f"Компания: *{data['company_name']}*\n"
                f"След. звонок: {data.get('next_call_date', 'Не указан')}\n\n"
                "Что дальше?",
                parse_mode="Markdown",
                reply_markup=get_main_menu()
            )
        else:
            await message.answer(
                "⚠️ Данные сохранены локально, но возникла ошибка при обновлении Google Sheets.\n"
                "Обратитесь к администратору.",
                reply_markup=get_main_menu()
            )
    except Exception as e:
        logger.error(f"Error updating Google Sheets: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при обновлении таблицы.\n"
            "Данные сохранены локально.",
            reply_markup=get_main_menu()
        )
    
    await state.clear()
