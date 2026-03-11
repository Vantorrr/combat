import asyncio
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from bot.states.call_states import TaskStates, RepeatCallStates
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api
from services.ai_advisor import generate_ai_notification
from models.database import Manager
from config import settings

router = Router()

def get_task_keyboard(inn: str) -> InlineKeyboardMarkup:
    """Клавиатура действий с задачей"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🤖 AI инфоповод", callback_data=f"task_ai:{inn}"),
    )
    builder.row(
        InlineKeyboardButton(text="✅ Звонок совершен", callback_data=f"task_done:{inn}"),
    )
    builder.row(
        InlineKeyboardButton(text="➡️ Следующая", callback_data="task_next"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")
    )
    return builder.as_markup()

@router.callback_query(F.data == "next_task")
async def start_tasks_flow(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Запуск режима 'Текущая задача'"""
    await callback.answer()
    
    # Сбрасываем состояние и индекс задачи
    await state.clear()
    await state.update_data(task_index=0)
    
    await show_next_task(callback.message, state, callback.from_user.id, session)

@router.callback_query(F.data == "task_next")
async def next_task_handler(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Переход к следующей задаче (пропуск)"""
    await callback.answer()
    
    data = await state.get_data()
    current_index = data.get("task_index", 0)
    await state.update_data(task_index=current_index + 1)
    
    await show_next_task(callback.message, state, callback.from_user.id, session)

@router.callback_query(F.data == "task_completed")
async def task_completed_handler(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Переход к следующей задаче после выполнения (без увеличения индекса, т.к. список сдвигается)"""
    await callback.answer()
    
    # Индекс НЕ увеличиваем, так как выполненная задача исчезает из списка, 
    # и на её место встает следующая
    
    await show_next_task(callback.message, state, callback.from_user.id, session)

async def show_next_task(message: types.Message, state: FSMContext, user_id: int, session: AsyncSession):
    """Показать следующую задачу из списка (просроченные + на сегодня)"""
    
    # 1. Ищем sheet_id пользователя
    result = await session.execute(select(Manager).where(Manager.telegram_id == user_id))
    manager = result.scalar_one_or_none()
        
    if not manager or not manager.google_sheet_id:
        await message.edit_text("❌ Ваша таблица не привязана. Обратитесь к администратору.")
        return

    google_sheets_service = get_google_sheets_service()
    
    # 2. Получаем список просроченных звонков (недозвонов) и звонков на сегодня
    missed_calls = await google_sheets_service.get_missed_calls(manager.google_sheet_id)
    today_calls = await google_sheets_service.get_today_calls(manager.google_sheet_id)
    
    # 3. Маркируем просроченные задачи
    for call in missed_calls:
        call['is_overdue'] = True
    for call in today_calls:
        call['is_overdue'] = False
    
    # 4. Объединяем списки (сначала просроченные - они приоритетнее)
    all_tasks = missed_calls + today_calls
    
    data = await state.get_data()
    current_index = data.get("task_index", 0)
    
    if not all_tasks:
        await message.edit_text(
            "🎉 На сегодня запланированных звонков нет!\n"
            "Отличная возможность поработать с новыми клиентами! 🚀",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
        )
        return

    # Если дошли до конца списка - начинаем сначала (или говорим что всё)
    if current_index >= len(all_tasks):
        # Если были пропущенные задачи (индекс > 0), предложим начать сначала
        if len(all_tasks) > 0:
            await message.edit_text(
                "✅ Вы просмотрели все задачи в списке!\n"
                "Остались пропущенные задачи. Начать сначала?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="next_task")],
                    [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
                ])
            )
        else:
            await message.edit_text(
                "✅ Все запланированные на сегодня звонки выполнены!",
                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
                ])
            )
        return

    # 3. Берем задачу
    task = all_tasks[current_index]
    inn = task.get('inn', '').replace("'", "") # Убираем апостроф если есть
    
    # При edit_text иногда бывает, что сообщение не изменилось - ловим ошибку
    try:
        await message.edit_text(f"⏳ Загружаю информацию по компании (ИНН: {inn})...")
    except Exception:
        # Если не получилось отредактировать (например, текст тот же), отправляем новое
        pass

    # 4. Загружаем полные данные из таблицы
    company_data = await google_sheets_service.find_company_by_inn(manager.google_sheet_id, inn)
    
    if not company_data:
        # Если вдруг не нашли (странно, но бывает)
        try:
            await message.edit_text(
                f"⚠️ Ошибка: Компания с ИНН {inn} есть в плане, но не найдена в таблице детально.\n"
                f"Пропускаю...",
            )
        except:
            pass
        await state.update_data(task_index=current_index + 1)
        await show_next_task(message, state, user_id, session)
        return

    # 5. Формируем карточку
    company_name = company_data.get('company_name', 'Не указано')
    contact_name = company_data.get('contact_name', 'Не указан')
    phone = company_data.get('phone', 'Не указан')
    last_comment = company_data.get('comment', '')
    is_overdue = task.get('is_overdue', False)
    
    # Подсчёт просроченных и сегодняшних задач для информации
    overdue_count = len(missed_calls)
    today_count = len(today_calls)
    
    # Статус задачи
    task_status = "⚠️ <b>ПРОСРОЧЕНО</b>" if is_overdue else "📅 На сегодня"
    
    # Отправляем основное сообщение
    info_text = (
        f"📞 <b>Задача {current_index + 1} из {len(all_tasks)}</b> ({task_status})\n"
        f"<i>Просроченных: {overdue_count}, На сегодня: {today_count}</i>\n\n"
        f"🏢 <b>{company_name}</b>\n"
        f"🆔 ИНН: <code>{inn}</code>\n"
        f"👤 Контакт: <b>{contact_name}</b>\n"
        f"📱 Телефон: <b>{phone}</b>\n\n"
        f"💬 <b>Последний комментарий:</b>\n{last_comment[:800] + '...' if len(last_comment) > 800 else last_comment}\n"
    )
    
    # Кнопки
    kb = get_task_keyboard(inn)
    
    # Защита от превышения лимита Telegram (4096 символов)
    if len(info_text) > 4000:
        info_text = info_text[:4000] + "...\n<i>(комментарий обрезан)</i>"

    try:
        sent_msg = await message.edit_text(info_text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        # Если сообщение устарело или не может быть отредактировано
        sent_msg = await message.answer(info_text, reply_markup=kb, parse_mode="HTML")
    
    # Сохраняем состояние (включая manager_id и manager_name для save_repeat_call)
    await state.set_state(TaskStates.viewing_task)
    await state.update_data(
        current_inn=inn, 
        manager_sheet_id=manager.google_sheet_id,
        company_name=company_name,
        manager_id=manager.id,
        manager_name=manager.full_name
    )

@router.callback_query(F.data.startswith("task_ai:"))
async def task_ai_handler(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Генерация AI-инфоповода по кнопке"""
    inn = callback.data.split(":")[1]
    await callback.answer("🤖 Генерирую AI-анализ...")
    
    data = await state.get_data()
    company_name = data.get("company_name", "Компания")
    manager_sheet_id = data.get("manager_sheet_id")
    
    if not settings.openai_api_key:
        await callback.message.answer("⚠️ AI модуль не настроен.")
        return
    
    try:
        # Получаем данные из таблицы (как базовый источник)
        google_sheets_service = get_google_sheets_service()
        company_data = await google_sheets_service.find_company_by_inn(manager_sheet_id, inn)
        
        if not company_data:
            company_data = {}

        last_comment = company_data.get('comment', '')
        contact_name = company_data.get('contact_name', '')

        # Получаем свежие данные DataNewton
        try:
            fresh = await datanewton_api.get_full_company_data(inn)
        except Exception as e:
            fresh = {}
            logger.warning(f"DataNewton failed: {e}")
        
        if not fresh:
            fresh = {}

        # Собираем данные, отдавая приоритет fresh (DataNewton), затем company_data (Sheet)
        def get_val(key_fresh, key_sheet=None):
            return fresh.get(key_fresh) or company_data.get(key_sheet or key_fresh) or ""

        # Формируем аргументы, обязательно передаем keyword-only аргументы
        ai_insight = await generate_ai_notification(
            inn=inn,
            company_name=company_name,
            last_comment=last_comment,
            last_call_date=datetime.now(),
            all_comments=[last_comment] if last_comment else [],
            contact_name=contact_name,
            planned_call_date=datetime.now(),
            
            # Обязательные поля (keyword-only)
            okved_code=get_val('okved', 'okved_main'),
            okved_name=get_val('okved_name', 'okpd_name'), # В таблице иногда okpd_name используется как описание деятельности
            region=get_val('region'), # В таблице региона может не быть, будет ""
            
            # Опциональные поля (для лучшего анализа)
            revenue=get_val('revenue'),
            revenue_previous=get_val('revenue_previous'),
            net_profit=get_val('net_profit'),
            capital=get_val('capital'),
            assets=get_val('assets'),
            debit=get_val('debit'),
            credit=get_val('credit'),
            gov_contracts=get_val('gov_contracts'),
            arbitration_open_count=str(fresh.get('arbitration_open_count') or company_data.get('arbitration') or '0'),
            arbitration_open_sum=str(fresh.get('arbitration_open_sum') or '0'),
            arbitration_last_doc_date=str(fresh.get('arbitration_last_doc_date') or '')
        )
        # Сохраняем данные компании в state, чтобы AI чат мог их использовать
        company_data_full = {
            'revenue': get_val('revenue'),
            'net_profit': get_val('net_profit'),
            'gov_contracts': get_val('gov_contracts'),
            'region': get_val('region'),
            'okved_code': get_val('okved', 'okved_main'),
            'okved_name': get_val('okved_name', 'okpd_name'),
        }
        await state.update_data(company_data=company_data_full)
        
        # Клавиатура "Спросить AI"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Спросить ИИ (Чат)", callback_data="ask_ai")]
        ])
        
        await callback.message.answer(f"🤖 <b>AI-Анализ:</b>\n\n{ai_insight}", parse_mode="HTML", reply_markup=kb)
        
    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        await callback.message.answer(f"❌ Ошибка генерации AI-анализа:\n{e}")

@router.callback_query(F.data.startswith("task_done:"))
async def task_done_handler(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Пользователь нажал 'Звонок совершен'"""
    inn = callback.data.split(":")[1]
    
    data = await state.get_data()
    company_name = data.get("company_name", "Компания")
    manager_sheet_id = data.get("manager_sheet_id")
    manager_id = data.get("manager_id")
    manager_name = data.get("manager_name")
    task_index = data.get("task_index", 0)
    
    # Сохраняем данные для повторного звонка (все нужные поля для save_repeat_call)
    await state.set_state(RepeatCallStates.waiting_for_comment)
    await state.update_data(
        inn=inn,
        manager_sheet_id=manager_sheet_id,
        company_name=company_name,
        manager_id=manager_id,
        manager_name=manager_name,
        task_index=task_index,
        is_task_flow=True # Флаг, что мы в режиме задач (чтобы потом вернуть в tasks)
    )
    
    await callback.message.answer(
        "💬 Введите комментарий по результатам звонка:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="task_completed")] # Возврат к задаче (без инкремента, если отменил? нет, тут отмена)
             # Если отмена - лучше вернуться к просмотру ЭТОЙ же задачи. 
             # Но callback "task_completed" вызовет show_next_task с текущим индексом.
             # Если задача не была выполнена (коммент не сохранен), она осталась в списке на том же месте.
             # Так что task_completed (без инкремента) подойдет.
        ])
    )
    
    # Удаляем старое сообщение с кнопками задачи, чтобы не путало
    try:
        await callback.message.delete()
    except:
        pass
