from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.states.call_states import TaskStates, RepeatCallStates
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api
from services.ai_advisor import generate_ai_notification
from models.database import Manager, CallSession
from config import settings

router = Router()

def get_task_keyboard(inn: str) -> InlineKeyboardMarkup:
    """Клавиатура действий с задачей"""
    builder = InlineKeyboardBuilder()
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
    """Переход к следующей задаче"""
    await callback.answer()
    
    data = await state.get_data()
    current_index = data.get("task_index", 0)
    await state.update_data(task_index=current_index + 1)
    
    await show_next_task(callback.message, state, callback.from_user.id, session)

async def show_next_task(message: types.Message, state: FSMContext, user_id: int, session: AsyncSession):
    """Показать следующую задачу из списка на сегодня"""
    
    # 1. Ищем sheet_id пользователя
    # Используем переданную сессию
    result = await session.execute(select(Manager).where(Manager.telegram_id == user_id))
    manager = result.scalar_one_or_none()
        
    if not manager or not manager.google_sheet_id:
        await message.edit_text("❌ Ваша таблица не привязана. Обратитесь к администратору.")
        return

    google_sheets_service = get_google_sheets_service()
    
    # 2. Получаем список звонков на сегодня
    today_calls = await google_sheets_service.get_today_calls(manager.google_sheet_id)
    
    data = await state.get_data()
    current_index = data.get("task_index", 0)
    
    if not today_calls:
        await message.edit_text(
            "🎉 На сегодня запланированных звонков нет!\n"
            "Отличная возможность поработать с новыми клиентами! 🚀",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
        )
        return

    # Если дошли до конца списка - начинаем сначала (или говорим что всё)
    if current_index >= len(today_calls):
        await message.edit_text(
            "✅ Все запланированные на сегодня звонки просмотрены!",
             reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="next_task")],
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
        )
        return

    # 3. Берем задачу
    task = today_calls[current_index]
    inn = task.get('inn', '').replace("'", "") # Убираем апостроф если есть
    
    await message.edit_text(f"⏳ Загружаю информацию по компании (ИНН: {inn})...")

    # 4. Загружаем полные данные из таблицы
    company_data = await google_sheets_service.find_company_by_inn(manager.google_sheet_id, inn)
    
    if not company_data:
        # Если вдруг не нашли (странно, но бывает)
        await message.edit_text(
            f"⚠️ Ошибка: Компания с ИНН {inn} есть в плане, но не найдена в таблице детально.\n"
            f"Пропускаю...",
        )
        await state.update_data(task_index=current_index + 1)
        await show_next_task(message, state, user_id, session)
        return

    # 5. Формируем карточку
    company_name = company_data.get('company_name', 'Не указано')
    contact_name = company_data.get('contact_name', 'Не указан')
    phone = company_data.get('phone', 'Не указан')
    last_comment = company_data.get('comment', '')
    
    # AI Подсказка
    ai_text = "⏳ Генерация AI-подсказки..."
    
    # Отправляем основное сообщение
    info_text = (
        f"📞 <b>Задача {current_index + 1} из {len(today_calls)}</b>\n\n"
        f"🏢 <b>{company_name}</b>\n"
        f"🆔 ИНН: <code>{inn}</code>\n"
        f"👤 Контакт: <b>{contact_name}</b>\n"
        f"📱 Телефон: <b>{phone}</b>\n\n"
        f"💬 <b>Последний комментарий:</b>\n{last_comment[:300] + '...' if len(last_comment) > 300 else last_comment}\n"
    )
    
    # Кнопки
    kb = get_task_keyboard(inn)
    
    sent_msg = await message.edit_text(info_text, reply_markup=kb, parse_mode="HTML")
    
    # 6. Генерируем и досылаем AI подсказку
    if settings.openai_api_key:
        try:
            # Получаем данные DataNewton
            fresh = await datanewton_api.get_full_company_data(inn)
            # Если пусто, берем из таблицы
            if not fresh:
                fresh = {
                    'revenue': company_data.get('revenue', ''),
                    'revenue_previous': company_data.get('revenue_previous', ''),
                    'net_profit': company_data.get('net_profit', ''),
                    # ... остальные поля
                }
            
            ai_insight = await generate_ai_notification(
                inn=inn,
                company_name=company_name,
                last_comment=last_comment,
                last_call_date=datetime.now(),
                all_comments=[last_comment] if last_comment else [],
                # ... передаем поля (упрощенно)
                revenue=fresh.get('revenue'),
                net_profit=fresh.get('net_profit'),
                contact_name=contact_name,
                planned_call_date=datetime.now()
            )
            
            await message.answer(f"🤖 <b>AI-Анализ:</b>\n\n{ai_insight}", parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"AI generation failed: {e}")

    # Сохраняем состояние (включая manager_id и manager_name для save_repeat_call)
    await state.set_state(TaskStates.viewing_task)
    await state.update_data(
        current_inn=inn, 
        manager_sheet_id=manager.google_sheet_id,
        company_name=company_name,
        manager_id=manager.id,
        manager_name=manager.full_name
    )

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
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="next_task")] # Возврат к задаче
        ])
    )
    
    # Удаляем старое сообщение с кнопками задачи, чтобы не путало
    try:
        await callback.message.delete()
    except:
        pass
