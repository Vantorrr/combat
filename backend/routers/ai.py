from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from loguru import logger

from models.database import get_session, Manager, CallSession
from backend.routers.auth import oauth2_scheme
from backend.security import SECRET_KEY, ALGORITHM
from jose import jwt, JWTError
from services.google_sheets import get_google_sheets_service
from services.ai_advisor import generate_daily_plan, ask_ai_advisor, generate_ai_notification
from services.datanewton_api import datanewton_api

router = APIRouter(tags=["ai"], prefix="/ai")

# --- Schemas ---
class AIChatRequest(BaseModel):
    question: str
    inn: str
    company_name: Optional[str] = ""
    # Context data passed from frontend
    revenue: Optional[str] = ""
    net_profit: Optional[str] = ""
    gov_contracts: Optional[str] = ""
    region: Optional[str] = ""
    okved_code: Optional[str] = ""
    okved_name: Optional[str] = ""
    last_comment: Optional[str] = ""

# --- Dependency ---
async def get_current_user(token: str = Depends(oauth2_scheme), session: AsyncSession = Depends(get_session)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    result = await session.execute(select(Manager).where(Manager.login == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# --- Endpoints ---

@router.post("/daily_plan")
async def get_daily_plan(user: Manager = Depends(get_current_user)):
    """Генерация AI дневного плана"""
    if not user.google_sheet_id:
        raise HTTPException(status_code=400, detail="Google Sheet не подключена")
    
    try:
        google_sheets = get_google_sheets_service()
        today_calls = await google_sheets.get_today_calls(user.google_sheet_id)
        missed_calls = await google_sheets.get_missed_calls(user.google_sheet_id)
        
        all_calls = []
        for call in missed_calls:
            all_calls.append({**call, "status": "overdue"})
        for call in today_calls:
            all_calls.append({**call, "status": "today"})
        
        if not all_calls:
            return {"plan": "На сегодня запланированных звонков нет. Отличная работа!"}
        
        plan = await generate_daily_plan(all_calls)
        return {"plan": plan}
    except Exception as e:
        logger.error(f"Daily plan error: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка генерации плана: {str(e)[:100]}")


@router.post("/chat")
async def ai_chat(
    request: AIChatRequest,
    user: Manager = Depends(get_current_user)
):
    """AI чат с контекстом компании"""
    context_parts = []
    if request.company_name:
        context_parts.append(f"Компания: {request.company_name}")
    if request.inn:
        context_parts.append(f"ИНН: {request.inn}")
    if request.revenue:
        context_parts.append(f"Выручка: {request.revenue}")
    if request.net_profit:
        context_parts.append(f"Чистая прибыль: {request.net_profit}")
    if request.gov_contracts:
        context_parts.append(f"Госконтракты: {request.gov_contracts}")
    if request.region:
        context_parts.append(f"Регион: {request.region}")
    if request.okved_code:
        context_parts.append(f"ОКВЭД: {request.okved_code}")
    if request.okved_name:
        context_parts.append(f"Наименование ОКВЭД: {request.okved_name}")
    if request.last_comment:
        context_parts.append(f"Последний комментарий: {request.last_comment}")
    
    context_data = "\n".join(context_parts) if context_parts else "Нет данных о компании"
    
    try:
        response = await ask_ai_advisor(request.question, context_data)
        return {"answer": response}
    except Exception as e:
        logger.error(f"AI chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)[:100]}")


@router.get("/hint/{inn}")
async def get_ai_hint(inn: str, user: Manager = Depends(get_current_user)):
    """Получить AI подсказку по ИНН"""
    if not user.google_sheet_id:
        raise HTTPException(status_code=400, detail="Google Sheet не подключена")
        
    google_sheets = get_google_sheets_service()
    company_data = await google_sheets.find_company_by_inn(user.google_sheet_id, inn)
    
    if not company_data:
        raise HTTPException(status_code=404, detail="Компания не найдена")
        
    try:
        fresh = await datanewton_api.get_full_company_data(inn)
    except Exception:
        fresh = {}
        
    def get_val(key_fresh, key_sheet=None):
        return fresh.get(key_fresh) or company_data.get(key_sheet or key_fresh) or ""

    ai_insight = await generate_ai_notification(
        inn=inn,
        company_name=company_data.get('company_name'),
        last_comment=company_data.get('comment'),
        last_call_date=datetime.now(),
        all_comments=[company_data.get('comment')] if company_data.get('comment') else [],
        contact_name=company_data.get('contact_name'),
        planned_call_date=datetime.now(),
        okved_code=get_val('okved', 'okved_main'),
        okved_name=get_val('okved_name', 'okpd_name'),
        region=get_val('region'),
        revenue=get_val('revenue'),
        revenue_previous=get_val('revenue_previous'),
        net_profit=get_val('net_profit'),
        capital=get_val('capital'),
        assets=get_val('assets'),
        debit=get_val('debit'),
        credit=get_val('credit'),
        gov_contracts=get_val('gov_contracts'),
        arbitration_open_count=str(fresh.get('arbitration_open_count') or '0'),
        arbitration_open_sum=str(fresh.get('arbitration_open_sum') or '0'),
        arbitration_last_doc_date=str(fresh.get('arbitration_last_doc_date') or '')
    )
    
    return {"insight": ai_insight}
