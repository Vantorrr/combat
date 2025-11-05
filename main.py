import asyncio
import sys
from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import init_db, get_session
from bot.handlers import start, new_call, repeat_call, admin, utils, sheet_info, csv_import

# Настройка логирования
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time} {level} {message}")
logger.add("logs/bot.log", rotation="1 day", retention="7 days", level="DEBUG")


async def on_startup(bot: Bot):
    """Действия при запуске бота"""
    logger.info("Bot starting...")
    
    # Инициализация базы данных
    await init_db(settings.database_url)
    logger.info("Database initialized")
    
    # Уведомление администраторов о запуске (только тех, кто уже писал боту)
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(
                admin_id,
                "🤖 Бот запущен и готов к работе!"
            )
        except Exception as e:
            logger.debug(f"Admin {admin_id} not notified (probably hasn't started bot yet)")


async def on_shutdown(bot: Bot):
    """Действия при остановке бота"""
    logger.info("Bot shutting down...")
    
    # Уведомление администраторов об остановке
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(
                admin_id,
                "🛑 Бот остановлен."
            )
        except Exception as e:
            logger.debug(f"Admin {admin_id} not notified about shutdown")


async def setup_bot_commands(bot: Bot):
    """Настройка команд бота"""
    from aiogram.types import BotCommand
    
    commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="cancel", description="Отменить текущее действие"),
        BotCommand(command="id", description="Получить свой Telegram ID")
    ]
    await bot.set_my_commands(commands)


def setup_middlewares(dp: Dispatcher):
    """Настройка middleware для внедрения сессии БД"""
    
    async def db_session_middleware(handler, event, data):
        async for session in get_session():
            data["session"] = session
            try:
                return await handler(event, data)
            finally:
                await session.close()
    
    dp.message.middleware(db_session_middleware)
    dp.callback_query.middleware(db_session_middleware)


async def main():
    """Основная функция запуска бота"""
    # Инициализация бота и диспетчера
    bot = Bot(token=settings.bot_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Регистрация роутеров
    dp.include_router(start.router)
    dp.include_router(new_call.router)
    dp.include_router(repeat_call.router)
    dp.include_router(admin.router)
    dp.include_router(utils.router)
    dp.include_router(sheet_info.router)
    dp.include_router(csv_import.router)
    # Debug роутер временно отключен
    # dp.include_router(debug.router)
    
    # Настройка middleware
    setup_middlewares(dp)
    
    # Настройка команд
    await setup_bot_commands(bot)
    
    # Запуск бота
    try:
        await on_startup(bot)
        logger.info("Starting polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await on_shutdown(bot)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
