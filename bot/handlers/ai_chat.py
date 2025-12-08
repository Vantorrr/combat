from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from loguru import logger

from bot.states.call_states import AIChatStates, TaskStates, RepeatCallStates
from services.ai_advisor import ask_ai_advisor

router = Router()

@router.callback_query(F.data == "ask_ai")
async def start_ai_chat(callback: CallbackQuery, state: FSMContext):
    """Начинает диалог с AI по текущей компании"""
    data = await state.get_data()
    
    # Определяем, откуда пришли, чтобы знать куда вернуться
    current_state = await state.get_state()
    return_route = "main"
    
    if current_state in [TaskStates.viewing_task, TaskStates.processing_call] or data.get('is_task_flow'):
        return_route = "task"
    elif current_state in [RepeatCallStates.waiting_for_inn, RepeatCallStates.waiting_for_comment, RepeatCallStates.waiting_for_next_call_date]:
        return_route = "repeat"
        
    await state.update_data(return_route=return_route)
    await state.set_state(AIChatStates.waiting_for_question)
    
    company_name = data.get('company_name', 'Компании')
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Вернуться назад", callback_data="stop_ai_chat")]
    ])
    
    await callback.message.answer(
        f"🤖 Я готов ответить на вопросы по компании *{company_name}*.\n\n"
        "Спрашивай что угодно: как построить диалог, какие есть риски, что значат цифры и т.д.",
        parse_mode="Markdown",
        reply_markup=kb
    )
    await callback.answer()


@router.message(AIChatStates.waiting_for_question)
async def process_ai_question(message: Message, state: FSMContext):
    """Обрабатывает вопрос пользователя к AI"""
    question = message.text
    if not question:
        return

    # Проверка на команду выхода (на случай если кнопки нет или юзер пишет текстом)
    if question.lower() in ['выход', 'назад', 'отмена', 'стоп']:
        await stop_ai_chat_message(message, state)
        return

    data = await state.get_data()
    
    # Формируем контекст из данных в state
    # Мы ожидаем, что в data есть поля, собранные ранее (inn, company_name, revenue, comments, etc.)
    # Но в repeat_call мы не сохраняли ВСЕ фин данные в state, только часть.
    # В tasks.py мы сохраняли company_data (словарь).
    
    context_lines = []
    context_lines.append(f"Компания: {data.get('company_name')}")
    context_lines.append(f"ИНН: {data.get('inn')}")
    
    # Пытаемся достать данные. Они могут быть разбросаны или в data['company_data']
    company_data = data.get('company_data', {})
    if not company_data and 'revenue' in data: # Fallback for repeat_call if we stored it there
         company_data = data
         
    if company_data:
        context_lines.append(f"Выручка: {company_data.get('revenue', 'н/д')}")
        context_lines.append(f"Прибыль: {company_data.get('net_profit', 'н/д')}")
        context_lines.append(f"Госконтракты: {company_data.get('gov_contracts', 'н/д')}")
        context_lines.append(f"Регион: {company_data.get('region', 'н/д')}")
        context_lines.append(f"ОКВЭД: {company_data.get('okved_code')} {company_data.get('okved_name')}")
        
    # История комментов
    if 'last_comment' in data:
        context_lines.append(f"Последний комментарий: {data['last_comment']}")
        
    context_str = "\n".join(context_lines)
    
    waiting_msg = await message.answer("⏳ Думаю...")
    
    answer = await ask_ai_advisor(question, context_str)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Вернуться назад", callback_data="stop_ai_chat")]
    ])
    
    await waiting_msg.edit_text(
        f"🤖 *Ответ AI:*\n\n{answer}", 
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.callback_query(F.data == "stop_ai_chat")
async def stop_ai_chat_callback(callback: CallbackQuery, state: FSMContext):
    await stop_ai_chat_logic(callback.message, state)
    await callback.answer()

async def stop_ai_chat_message(message: Message, state: FSMContext):
    await stop_ai_chat_logic(message, state)

async def stop_ai_chat_logic(message: Message, state: FSMContext):
    """Логика возврата из чата"""
    data = await state.get_data()
    return_route = data.get('return_route', 'main')
    
    if return_route == 'task':
        # Возвращаемся в меню задачи
        # Нам нужно восстановить TaskStates.viewing_task или processing_call
        # В tasks.py логика построена на show_next_task.
        # Но у нас уже есть задача.
        # Просто скажем что вернулись.
        
        await state.set_state(TaskStates.viewing_task)
        
        # Кнопки задачи
        kb = InlineKeyboardMarkup(inline_keyboard=[
             [InlineKeyboardButton(text="🧠 AI инфоповод", callback_data="task_ai_hint")],
             [InlineKeyboardButton(text="✅ Звонок совершен", callback_data=f"task_done:{data.get('inn')}")],
             [InlineKeyboardButton(text="➡️ Следующая", callback_data="task_next")],
             [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
        ])
        
        await message.answer(
            "🔙 Вы вернулись к задаче.",
            reply_markup=kb
        )
        
    elif return_route == 'repeat':
        # Возвращаемся в повторный звонок
        # Скорее всего мы были на этапе ввода комментария или просмотра инфоповода
        await state.set_state(RepeatCallStates.waiting_for_comment)
        
        from bot.keyboards.main import get_cancel_keyboard
        await message.answer(
            "🔙 Вы вернулись к звонку.\n💬 Введите комментарий по результатам:",
            reply_markup=get_cancel_keyboard()
        )
    else:
        from bot.keyboards.main import get_main_menu
        await state.clear()
        await message.answer("Главное меню", reply_markup=get_main_menu())

