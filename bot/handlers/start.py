from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from bot.keyboards.main import get_main_menu, get_admin_menu
from models.database import Manager
from config import settings

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    logger.info(f"User {user_id} (@{message.from_user.username}) started bot")
    
    # Проверяем, является ли пользователь администратором
    if user_id in settings.admin_ids_list:
        await message.answer(
            "👋 Добро пожаловать, администратор!\n\n"
            "Используйте меню для управления системой:",
            reply_markup=get_admin_menu()
        )
        return
    
    # Проверяем, зарегистрирован ли менеджер
    result = await session.execute(
        select(Manager).where(Manager.telegram_id == user_id)
    )
    manager = result.scalar_one_or_none()
    
    if manager:
        await message.answer(
            f"👋 Привет, {manager.full_name}!\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu()
        )
    else:
        await message.answer(
            "⚠️ Вы не зарегистрированы в системе.\n"
            "Обратитесь к администратору для получения доступа."
        )


@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery, session: AsyncSession):
    """Показать главное меню"""
    user_id = callback.from_user.id
    
    # Проверяем, зарегистрирован ли менеджер
    result = await session.execute(
        select(Manager).where(Manager.telegram_id == user_id)
    )
    manager = result.scalar_one_or_none()
    
    if manager:
        await callback.message.edit_text(
            "Выберите действие:",
            reply_markup=get_main_menu()
        )
    else:
        await callback.message.edit_text(
            "⚠️ Вы не зарегистрированы в системе.\n"
            "Обратитесь к администратору для получения доступа."
        )
    
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    """Отмена текущего действия"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Действие отменено.\n\nВыберите новое действие:",
        reply_markup=get_main_menu()
    )
    await callback.answer()
