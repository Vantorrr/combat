import asyncio
import sys
from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.database import init_db, get_session, Manager
from bot.handlers import start, new_call, repeat_call, admin, utils, sheet_info, csv_import, ai_advisor, auth, tasks, ai_chat
from services.google_sheets import get_google_sheets_service
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка логирования
logger.remove()
logger.add(sys.stdout, level="INFO", format="{time} {level} {message}")
logger.add("logs/bot.log", rotation="1 day", retention="7 days", level="DEBUG")


async def on_startup(bot: Bot):
    """Действия при запуске бота"""
    logger.info("Bot starting...")
    
    # Инициализация базы данных
    await init_db(settings.database_url_effective)
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

    # Планировщик напоминаний
    try:
        scheduler = AsyncIOScheduler(timezone=settings.timezone)

        async def send_daily_reminders():
            """Рассылка утренних напоминаний о звонках"""
            try:
                google_sheets = get_google_sheets_service()
                # Получаем список менеджеров и шлём напоминания
                async for session in get_session():
                    result = await session.execute(select(Manager))
                    managers = result.scalars().all()
                    for manager in managers:
                        if not manager.google_sheet_id or not manager.telegram_id:
                            continue
                        today_calls = await google_sheets.get_today_calls(manager.google_sheet_id)
                        if today_calls:
                            try:
                                await bot.send_message(
                                    manager.telegram_id,
                                    f"📅 Напоминание: на сегодня запланировано звонков: {len(today_calls)}"
                                )
                            except Exception:
                                pass
                    await session.close()
            except Exception as e:
                logger.warning(f"Reminder job failed: {e}")

        async def send_missed_call_reports():
            """Рассылка отчетов о недозвонах (вечерний отчет)"""
            try:
                logger.info("Starting missed call reports...")
                google_sheets = get_google_sheets_service()
                async for session in get_session():
                    # Получаем всех активных менеджеров
                    result = await session.execute(select(Manager).where(Manager.is_active == True))
                    managers = result.scalars().all()
                    logger.info(f"Found {len(managers)} active managers for missed calls report")
                    
                    for manager in managers:
                        if not manager.google_sheet_id:
                            logger.warning(f"Manager {manager.full_name} has no google_sheet_id, skipping")
                            continue
                            
                        # 1. Проверяем таблицу менеджера на недозвоны
                        try:
                            missed_calls = await google_sheets.get_missed_calls(manager.google_sheet_id)
                            logger.info(f"Manager {manager.full_name}: {len(missed_calls)} missed calls")
                        except Exception as e:
                            logger.error(f"Failed to get missed calls for {manager.full_name}: {e}")
                            continue
                        
                        if not missed_calls:
                            logger.debug(f"No missed calls for {manager.full_name}, skipping notifications")
                            continue
                            
                        # 2. Формируем сообщение для менеджера
                        msg_manager = (
                            f"⚠️ *Отчет о недозвонах*\n\n"
                            f"Сегодня вы пропустили {len(missed_calls)} запланированных звонков:\n"
                        )
                        for call in missed_calls[:10]: # Показываем первые 10
                            msg_manager += f"- {call['company_name']} (план: {call['planned_date']})\n"
                        if len(missed_calls) > 10:
                            msg_manager += f"... и еще {len(missed_calls) - 10} компаний."
                        
                        msg_manager += "\nНе забудьте позвонить им завтра!"
                        
                        # Шлем менеджеру
                        if manager.telegram_id:
                            try:
                                await bot.send_message(manager.telegram_id, msg_manager, parse_mode="Markdown")
                                logger.info(f"Sent missed calls report to manager {manager.full_name}")
                            except Exception as e:
                                logger.warning(f"Could not send report to manager {manager.full_name}: {e}")

                        # 3. Формируем сообщение для админов
                        msg_admin = (
                            f"📊 *Контроль недозвонов*\n"
                            f"Менеджер: {manager.full_name}\n"
                            f"Пропущено звонков: {len(missed_calls)}\n"
                        )
                        
                        # Шлем всем админам
                        for admin_id in settings.admin_ids_list:
                            try:
                                await bot.send_message(admin_id, msg_admin, parse_mode="Markdown")
                                logger.info(f"Sent missed calls report to admin {admin_id} for manager {manager.full_name}")
                            except Exception as e:
                                logger.warning(f"Could not send report to admin {admin_id}: {e}")
                                
                    await session.close()
                logger.info("Missed call reports finished successfully")
            except Exception as e:
                import traceback
                logger.error(f"Missed call report job failed: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")

        # Несколько времен напоминаний в день (утро/день)
        for tm in settings.reminder_times_list:
            try:
                h, m = map(int, tm.split(":"))
                scheduler.add_job(send_daily_reminders, 'cron', hour=h, minute=m)
            except Exception:
                logger.warning(f"Invalid reminder time skipped: {tm}")
        
        # Вечерний отчет о недозвонах
        try:
            rh, rm = map(int, settings.report_time.split(":"))
            scheduler.add_job(send_missed_call_reports, 'cron', hour=rh, minute=rm)
            logger.info(f"Scheduled missed call report at {settings.report_time}")
        except Exception:
            logger.warning(f"Invalid report time: {settings.report_time}")

        scheduler.start()
        logger.info("Scheduler started for daily reminders")
    except Exception as e:
        logger.warning(f"Scheduler not started: {e}")


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
        BotCommand(command="id", description="Получить свой Telegram ID"),
        BotCommand(command="ai_hint", description="AI-инфоповод по компании (по ИНН)"),
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
    dp.include_router(ai_advisor.router)
    dp.include_router(tasks.router)
    dp.include_router(ai_chat.router)
    # dp.include_router(auth.router)  # Auth только для админских целей, скрываем из main
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
