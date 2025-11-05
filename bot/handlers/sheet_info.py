from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from bot.keyboards.main import get_main_menu
from models.database import Manager
from services.google_sheets import get_google_sheets_service

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
                message_text += f"{i}. *{call['company_name']}*\n"
                message_text += f"   ИНН: {call['inn']}\n"
                
                if call['contact_name']:
                    message_text += f"   Контакт: {call['contact_name']}\n"
                
                if call['phone']:
                    message_text += f"   Телефон: {call['phone']}\n"
                
                if call['last_comment']:
                    comment_preview = call['last_comment'][:50] + "..." if len(call['last_comment']) > 50 else call['last_comment']
                    message_text += f"   Последний комментарий: _{comment_preview}_\n"
                
                message_text += "\n"
            
            message_text += f"\nВсего звонков: {len(today_calls)}"
            
            await callback.message.edit_text(
                message_text,
                parse_mode="Markdown",
                reply_markup=get_main_menu()
            )
        else:
            await callback.message.edit_text(
                "📅 На сегодня запланированных звонков нет.\n\n"
                "Отличная возможность поработать с новыми клиентами! 🚀",
                reply_markup=get_main_menu()
            )
    
    except Exception as e:
        logger.error(f"Error getting today calls: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при загрузке звонков.\n"
            "Попробуйте позже или обратитесь к администратору.",
            reply_markup=get_main_menu()
        )
    
    await callback.answer()
