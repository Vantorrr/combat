from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from loguru import logger

from bot.keyboards.main import (
    get_cancel_keyboard, 
    get_confirm_inn_keyboard,
    get_skip_keyboard,
    get_main_menu
)
from bot.states.call_states import NewCallStates
from models.database import Manager, CallSession
from services.datanewton_api import datanewton_api
from services.google_sheets import get_google_sheets_service

router = Router()


@router.callback_query(F.data == "new_call")
async def start_new_call(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начать процесс нового звонка"""
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
    await state.set_state(NewCallStates.waiting_for_inn)
    
    await callback.message.edit_text(
        "🆕 *Новый звонок*\n\n"
        "Введите ИНН компании:",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(NewCallStates.waiting_for_inn)
async def process_inn(message: Message, state: FSMContext):
    """Обработка введенного ИНН"""
    inn = message.text.strip()
    
    # Базовая валидация ИНН
    if not inn.isdigit() or len(inn) not in [10, 12]:
        await message.answer(
            "❌ Неверный формат ИНН.\n"
            "ИНН должен содержать 10 или 12 цифр.\n\n"
            "Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Отправляем сообщение о проверке
    checking_msg = await message.answer("🔍 Проверяю ИНН...")
    
    # Проверяем ИНН через API и получаем полные данные включая финансы
    company_data = await datanewton_api.get_full_company_data(inn)
    
    if company_data and company_data.get('name'):
        await state.update_data(inn=inn, company_data=company_data)
        await state.set_state(NewCallStates.confirm_inn)
        
        await checking_msg.edit_text(
            f"✅ Найдена компания:\n\n"
            f"*{company_data.get('name')}*\n"
            f"ИНН: {inn}\n"
            f"ОКВЭД: {company_data.get('okved', 'Не указан')}\n\n"
            f"Это правильная компания?",
            parse_mode="Markdown",
            reply_markup=get_confirm_inn_keyboard(inn)
        )
    else:
        await checking_msg.edit_text(
            "⚠️ Компания не найдена в базе данных.\n"
            "Вы можете продолжить ввод данных вручную.\n\n"
            "Продолжить с ИНН: " + inn + "?",
            reply_markup=get_confirm_inn_keyboard(inn)
        )
        await state.update_data(inn=inn, company_data={})
        await state.set_state(NewCallStates.confirm_inn)


@router.callback_query(NewCallStates.confirm_inn, F.data.startswith("confirm_inn:"))
async def confirm_inn(callback: CallbackQuery, state: FSMContext):
    """Подтверждение ИНН"""
    await state.set_state(NewCallStates.waiting_for_contact_name)
    
    data = await state.get_data()
    company_name = data.get('company_data', {}).get('name', 'Не указано')
    
    await callback.message.edit_text(
        f"✅ ИНН подтвержден.\n"
        f"Компания: *{company_name}*\n\n"
        "Введите ФИО контактного лица (ЛПР):",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(NewCallStates.confirm_inn, F.data == "wrong_inn")
async def wrong_inn(callback: CallbackQuery, state: FSMContext):
    """Неверный ИНН - ввести заново"""
    await state.set_state(NewCallStates.waiting_for_inn)
    
    await callback.message.edit_text(
        "Введите правильный ИНН компании:",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(NewCallStates.waiting_for_contact_name)
async def process_contact_name(message: Message, state: FSMContext):
    """Обработка ФИО контакта"""
    contact_name = message.text.strip()
    
    if len(contact_name) < 2:
        await message.answer(
            "❌ Слишком короткое имя.\n"
            "Введите полное ФИО контактного лица:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(contact_name=contact_name)
    await state.set_state(NewCallStates.waiting_for_phone)
    
    await message.answer(
        "📞 Введите телефон контактного лица:",
        reply_markup=get_skip_keyboard()
    )


@router.message(NewCallStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    """Обработка телефона"""
    phone = message.text.strip()
    
    await state.update_data(phone=phone)

    # Если email отсутствует в данных DataNewton — спросим у пользователя
    data = await state.get_data()
    api_email = (data.get('company_data') or {}).get('email', '')
    if not api_email:
        await state.set_state(NewCallStates.waiting_for_email)
        await message.answer(
            "📧 Введите email (или пропустите)",
            reply_markup=get_skip_keyboard()
        )
        return

    await state.set_state(NewCallStates.waiting_for_comment)
    await message.answer(
        "💬 Введите комментарий к звонку:\n"
        "(что обсуждали, договоренности, результат)",
        reply_markup=get_cancel_keyboard()
    )


@router.callback_query(NewCallStates.waiting_for_phone, F.data == "skip")
async def skip_phone(callback: CallbackQuery, state: FSMContext):
    """Пропустить ввод телефона"""
    await state.update_data(phone="")
    data = await state.get_data()
    api_email = (data.get('company_data') or {}).get('email', '')
    if not api_email:
        await state.set_state(NewCallStates.waiting_for_email)
        await callback.message.edit_text(
            "📧 Введите email (или пропустите)",
            reply_markup=get_skip_keyboard()
        )
        await callback.answer()
        return

    await state.set_state(NewCallStates.waiting_for_comment)
    await callback.message.edit_text(
        "💬 Введите комментарий к звонку:\n"
        "(что обсуждали, договоренности, результат)",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@router.message(NewCallStates.waiting_for_email)
async def process_email(message: Message, state: FSMContext):
    email = message.text.strip()
    await state.update_data(email=email)
    await state.set_state(NewCallStates.waiting_for_comment)
    await message.answer(
        "💬 Введите комментарий к звонку:\n"
        "(что обсуждали, договоренности, результат)",
        reply_markup=get_cancel_keyboard()
    )

@router.callback_query(NewCallStates.waiting_for_email, F.data == "skip")
async def skip_email(callback: CallbackQuery, state: FSMContext):
    await state.update_data(email="")
    await state.set_state(NewCallStates.waiting_for_comment)
    await callback.message.edit_text(
        "💬 Введите комментарий к звонку:\n"
        "(что обсуждали, договоренности, результат)",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()
@router.message(NewCallStates.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext):
    """Обработка комментария"""
    raw_comment = message.text.strip()
    # Добавляем дату к комментарию
    today = datetime.now().strftime("%d.%m.%y")
    comment = f"{today} - {raw_comment}"
    
    await state.update_data(comment=comment)
    await state.set_state(NewCallStates.waiting_for_next_call_date)
    
    await message.answer(
        "📅 Введите дату следующего звонка в формате ДД.ММ.ГГ:\n"
        "(например: 25.12.24)",
        reply_markup=get_skip_keyboard()
    )


@router.message(NewCallStates.waiting_for_next_call_date)
async def process_next_call_date(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка даты следующего звонка"""
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
    
    await save_new_call(message, state, session)


@router.callback_query(NewCallStates.waiting_for_next_call_date, F.data == "skip")
async def skip_next_call_date(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Пропустить дату следующего звонка"""
    await state.update_data(next_call_date="")
    await save_new_call(callback.message, state, session)
    await callback.answer()


async def save_new_call(message: Message, state: FSMContext, session: AsyncSession):
    """Сохранить данные нового звонка"""
    data = await state.get_data()
    
    # Сохраняем в базу данных
    call_session = CallSession(
        manager_id=data['manager_id'],
        session_type='new',
        company_inn=data['inn'],
        company_name=data.get('company_data', {}).get('name', 'Не указано'),
        contact_name=data['contact_name'],
        contact_phone=data.get('phone', ''),
        comment=data['comment'],
        next_call_date=datetime.strptime(data['next_call_date'], "%d.%m.%y") if data.get('next_call_date') else None
    )
    
    session.add(call_session)
    await session.commit()
    
    # Подготавливаем данные для Google Sheets
    sheet_data = {
        'company_name': data.get('company_data', {}).get('name', 'Не указано'),
        'inn': data['inn'],
        'contact_name': data['contact_name'],
        'phone': data.get('phone', ''),
        'next_call_date': data.get('next_call_date', ''),
        'comment': data['comment'],
        'revenue': data.get('company_data', {}).get('revenue', ''),
        'revenue_previous': data.get('company_data', {}).get('revenue_previous', ''),
        'capital': data.get('company_data', {}).get('capital', ''),
        'assets': data.get('company_data', {}).get('assets', ''),
        'debit': data.get('company_data', {}).get('debit', ''),
        'credit': data.get('company_data', {}).get('credit', ''),
        'okved': data.get('company_data', {}).get('okved', ''),
        'okved_main': data.get('company_data', {}).get('okved', ''),
        'okved_name': data.get('company_data', {}).get('okved_name', ''),
        'employees': data.get('company_data', {}).get('employees', ''),
        'address': data.get('company_data', {}).get('address', ''),
        'director': data.get('company_data', {}).get('director', ''),
        'status': data.get('company_data', {}).get('status', ''),
        'email': (data.get('email') or data.get('company_data', {}).get('email', '')),
        'region': data.get('company_data', {}).get('region', ''),
        'gov_contracts': data.get('company_data', {}).get('gov_contracts', ''),
        'arbitration_open_count': data.get('company_data', {}).get('arbitration_open_count', ''),
        'arbitration_open_sum': data.get('company_data', {}).get('arbitration_open_sum', ''),
        'arbitration_last_doc_date': data.get('company_data', {}).get('arbitration_last_doc_date', ''),
        'okpd': data.get('company_data', {}).get('okpd', ''),
        'okpd_name': data.get('company_data', {}).get('okpd_name', '')
    }
    
    # Сохраняем в Google Sheets
    try:
        google_sheets_service = get_google_sheets_service()
        success = await google_sheets_service.add_new_call(
            data['manager_sheet_id'], 
            sheet_data
        )
        
        if success:
            # Обновляем сводную таблицу руководителя
            await google_sheets_service.update_supervisor_sheet(
                data['manager_name'], 
                sheet_data
            )
            
            await message.answer(
                "✅ Данные успешно сохранены!\n\n"
                f"Компания: *{sheet_data['company_name']}*\n"
                f"Контакт: {sheet_data['contact_name']}\n"
                f"След. звонок: {sheet_data['next_call_date']}\n\n"
                "Что дальше?",
                parse_mode="Markdown",
                reply_markup=get_main_menu()
            )
        else:
            await message.answer(
                "⚠️ Данные сохранены локально, но возникла ошибка при сохранении в Google Sheets.\n"
                "Обратитесь к администратору.",
                reply_markup=get_main_menu()
            )
    except Exception as e:
        logger.error(f"Error saving to Google Sheets: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при сохранении в таблицу.\n"
            "Данные сохранены локально.",
            reply_markup=get_main_menu()
        )
    
    await state.clear()
