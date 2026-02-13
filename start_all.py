"""
Запуск Telegram бота + FastAPI веб-приложения одновременно
Используется для Railway деплоя
"""
import asyncio
import uvicorn
import multiprocessing
import sys
from loguru import logger

def run_bot():
    """Запуск Telegram бота"""
    logger.info("Starting Telegram bot process...")
    import main
    asyncio.run(main.main())

def run_web():
    """Запуск FastAPI приложения"""
    logger.info("Starting FastAPI web process...")
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info"
    )

if __name__ == "__main__":
    logger.info("Starting all services...")
    
    # Запускаем бот и веб в отдельных процессах
    bot_process = multiprocessing.Process(target=run_bot, name="telegram-bot")
    web_process = multiprocessing.Process(target=run_web, name="fastapi-web")
    
    try:
        bot_process.start()
        web_process.start()
        
        logger.info("All services started successfully")
        logger.info(f"Bot PID: {bot_process.pid}")
        logger.info(f"Web PID: {web_process.pid}")
        
        # Ждём завершения обоих процессов
        bot_process.join()
        web_process.join()
        
    except KeyboardInterrupt:
        logger.info("Shutting down all services...")
        bot_process.terminate()
        web_process.terminate()
        bot_process.join()
        web_process.join()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error running services: {e}")
        bot_process.terminate()
        web_process.terminate()
        sys.exit(1)
