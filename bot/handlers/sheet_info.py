from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from bot.keyboards.main import get_main_menu
from models.database import Manager
from services.google_sheets import get_google_sheets_service
from services.ai_advisor import generate_daily_plan

router = Router()


@router.callback_query(F.data == "my_sheet")
async def show_my_sheet(callback: CallbackQuery, session: AsyncSession):
    """Показать ссылку на таблицу менеджера"""
    user_id = callback.from_user.id
    
    # Получаем менеджера
    result = await session.execute(
        select(Manager).where(Manager.telegram_id == user_id)
    )
    manager = result.scalar_one_or_none()
    
    if not manager:
        await callback.answer("❌ Вы не зарегистрированы в системе", show_alert=True)
        return
    
    if manager.google_sheet_id:
        sheet_url = f"https://docs.google.com/spreadsheets/d/{manager.google_sheet_id}"
        
        await callback.message.answer(
            f"📊 Ваша таблица:\n\n"
            f"[Открыть таблицу]({sheet_url})\n\n"
            f"💡 Совет: добавьте таблицу в закладки для быстрого доступа",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    else:
        await callback.message.answer(
            "❌ У вас еще нет привязанной таблицы.\n"
            "Обратитесь к администратору."
        )
    
    await callback.answer()


@router.callback_query(F.data == "today_calls")
async def show_today_calls(callback: CallbackQuery, session: AsyncSession):
    """Показать список звонков на сегодня"""
    user_id = callback.from_user.id
    
    # Получаем менеджера
    result = await session.execute(
        select(Manager).where(Manager.telegram_id == user_id)
    )
    manager = result.scalar_one_or_none()
    
    if not manager:
        await callback.answer("❌ Вы не зарегистрированы в системе", show_alert=True)
        return
    
    await callback.message.edit_text("🔄 Загружаю список звонков...")
    
    try:
        # Получаем звонки на сегодня из таблицы
        google_sheets_service = get_google_sheets_service()
        today_calls = await google_sheets_service.get_today_calls(manager.google_sheet_id)
        
        if today_calls:
            message_text = "📅 *Звонки на сегодня:*\n\n"
            
            for i, call in enumerate(today_calls, 1):
                message_text += f"{i}. *{call.get('company_name', 'Не указано')}*\n"
                message_text += f"   ИНН: {call.get('inn', 'Не указано')}\n"
                
                contact_name = call.get('contact_name')
                if contact_name:
                    message_text += f"   Контакт: {contact_name}\n"
                
                phone = call.get('phone')
                if phone:
                    message_text += f"   Телефон: {phone}\n"
                
                message_text += "\n"
            
            message_text += f"\nВсего звонков: {len(today_calls)}"
            
            # Клавиатура с AI кнопкой
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧠 Сформировать AI-план (Ядро)", callback_data="ai_daily_plan")],
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
            
            await callback.message.edit_text(
                message_text,
                parse_mode="Markdown",
                reply_markup=kb
            )
        else:
            await callback.message.edit_text(
                "📅 На сегодня запланированных звонков нет.\n\n"
                "Отличная возможность поработать с новыми клиентами! 🚀",
                reply_markup=get_main_menu()
            )
    
    except Exception as e:
        import traceback
        logger.error(f"Error getting today calls: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        await callback.message.edit_text(
            f"❌ Произошла ошибка при загрузке звонков.\n"
            f"Детали: {str(e)[:200]}\n\n"
            "Попробуйте позже или обратитесь к администратору.",
            reply_markup=get_main_menu()
        )
    
    await callback.answer()


@router.callback_query(F.data == "ai_daily_plan")
async def generate_daily_plan_handler(callback: CallbackQuery, session: AsyncSession):
    """Генерация AI-плана на день"""
    user_id = callback.from_user.id
    
    # Получаем менеджера
    result = await session.execute(
        select(Manager).where(Manager.telegram_id == user_id)
    )
    manager = result.scalar_one_or_none()
    
    if not manager:
        await callback.answer("❌ Вы не зарегистрированы", show_alert=True)
        return
        
    await callback.message.edit_text("🧠 Анализирую список клиентов... Это займет 10-20 секунд ⏳")
    
    try:
        google_sheets_service = get_google_sheets_service()
        today_calls = await google_sheets_service.get_today_calls(manager.google_sheet_id)
        
        if not today_calls:
             await callback.message.edit_text(
                "⚠️ Список звонков пуст, нечего анализировать.",
                reply_markup=get_main_menu()
            )
             return

        # Генерируем план
        plan_text = await generate_daily_plan(today_calls)
        
        # Отправляем (разбиваем, если длинный)
        if len(plan_text) > 4000:
            for x in range(0, len(plan_text), 4000):
                 await callback.message.answer(plan_text[x:x+4000])
        else:
            await callback.message.answer(plan_text)
            
        # Возвращаем меню
        await callback.message.answer("Что дальше?", reply_markup=get_main_menu())
        
        # Удаляем сообщение "анализирую"
        try:
            await callback.message.delete() 
        except:
            pass

    except Exception as e:
        logger.error(f"Error generating AI plan: {e}")
        await callback.message.edit_text(
            "❌ Ошибка генерации плана. Попробуйте позже.",
            reply_markup=get_main_menu()
        )
