from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main import get_cancel_keyboard, get_main_menu
from bot.states.call_states import AIInsightStates
from models.database import Manager, CallSession
from services.ai_advisor import generate_ai_notification
from services.datanewton_api import datanewton_api

router = Router()


@router.message(Command("ai_hint"))
async def ai_hint_start(message: Message, state: FSMContext, session: AsyncSession):
    """Старт AI-инфоподсказки: запрашиваем ИНН компании."""
    user_id = message.from_user.id

    result = await session.execute(select(Manager).where(Manager.telegram_id == user_id))
    manager = result.scalar_one_or_none()

    if not manager:
        await message.answer("❌ Вы не зарегистрированы в системе", reply_markup=get_main_menu())
        return

    await state.update_data(manager_id=manager.id)
    await state.set_state(AIInsightStates.waiting_for_inn)
    await message.answer(
        "🤖 *AI-инфоповод*\n\n"
        "Введите ИНН компании, по которой нужно подготовить подсказку:",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )


@router.message(AIInsightStates.waiting_for_inn)
async def ai_hint_process_inn(message: Message, state: FSMContext, session: AsyncSession):
    """Получаем ИНН, ищем историю по компании и отдаём её в AI."""
    raw = (message.text or "").strip()
    inn = "".join(ch for ch in raw if ch.isdigit())

    if not inn.isdigit() or len(inn) not in [10, 12]:
        await message.answer(
            "❌ Неверный формат ИНН.\n"
            "ИНН должен содержать 10 или 12 цифр.\n\n"
            "Попробуйте еще раз:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    manager_id = data.get("manager_id")

    try:
        result = await session.execute(
            select(CallSession)
            .where(
                CallSession.manager_id == manager_id,
                CallSession.company_inn == inn,
            )
            .order_by(CallSession.created_at.asc())
        )
        sessions = result.scalars().all()
    except Exception as e:
        logger.error(f"[ai_hint] DB error while loading sessions: {e}")
        await message.answer(
            "⚠️ Ошибка при загрузке истории звонков. Попробуйте ещё раз или позже.",
            reply_markup=get_main_menu(),
        )
        await state.clear()
        return

    if not sessions:
        await message.answer(
            "ℹ️ По этому ИНН пока нет истории звонков.\n"
            "Сначала создайте хотя бы один звонок через 'Новый звонок' или 'Повторный звонок'.",
            reply_markup=get_main_menu(),
        )
        await state.clear()
        return

    last_call = sessions[-1]
    all_comments = [s.comment for s in sessions if s.comment]
    last_comment = last_call.comment or "Комментарий отсутствует"
    last_call_date = last_call.created_at
    company_name = last_call.company_name or "Не указано"

    # Пытаемся получить дополнительные данные по компании (ОКВЭД, регион, финансы, арбитражи)
    okved_code = None
    okved_name = None
    region = None
    revenue = None
    revenue_previous = None
    net_profit = None
    capital = None
    assets = None
    debit = None
    credit = None
    gov_contracts = None
    arbitration_open_count = None
    arbitration_open_sum = None
    arbitration_last_doc_date = None
    try:
        company_data = await datanewton_api.get_full_company_data(inn)
        if company_data:
            okved_code = company_data.get("okved")
            okved_name = company_data.get("okved_name")
            region = company_data.get("region")
            revenue = company_data.get("revenue")
            revenue_previous = company_data.get("revenue_previous")
            net_profit = company_data.get("net_profit")
            capital = company_data.get("capital")
            assets = company_data.get("assets")
            debit = company_data.get("debit")
            credit = company_data.get("credit")
            gov_contracts = company_data.get("gov_contracts")
            arbitration_open_count = company_data.get("arbitration_open_count")
            arbitration_open_sum = company_data.get("arbitration_open_sum")
            arbitration_last_doc_date = company_data.get("arbitration_last_doc_date")
            if company_data.get("name"):
                company_name = company_data["name"]
    except Exception as e:
        logger.warning(f"[ai_hint] DataNewton lookup failed: {e}")

    # В качестве планируемой даты звонка берём next_call_date, если есть, иначе сегодня
    planned_call_date: datetime | None = last_call.next_call_date or datetime.now()

    waiting_msg = await message.answer("🧠 Генерирую инфоповоды для звонка, подождите пару секунд...")

    text = await generate_ai_notification(
        inn=inn,
        company_name=company_name,
        last_comment=last_comment,
        last_call_date=last_call_date,
        all_comments=all_comments,
        okved_code=okved_code,
        okved_name=okved_name,
        region=region,
        revenue=revenue,
        revenue_previous=revenue_previous,
        net_profit=net_profit,
        capital=capital,
        assets=assets,
        debit=debit,
        credit=credit,
        gov_contracts=gov_contracts,
        arbitration_open_count=arbitration_open_count,
        arbitration_open_sum=arbitration_open_sum,
        arbitration_last_doc_date=arbitration_last_doc_date,
        planned_call_date=planned_call_date,
    )

    await waiting_msg.edit_text(text)
    await state.clear()


