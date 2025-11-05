from aiogram import Router
from aiogram.types import Message, Update
from loguru import logger

router = Router()


@router.message()
async def debug_all_messages(message: Message):
    """Логирование всех входящих сообщений для отладки"""
    logger.info(f"Received message from {message.from_user.id} (@{message.from_user.username}): {message.text}")
