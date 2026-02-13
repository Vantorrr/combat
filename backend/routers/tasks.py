from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from loguru import logger

from models.database import get_session, Manager, CallSession
from backend.routers.auth import oauth2_scheme
from backend.security import SECRET_KEY, ALGORITHM
from jose import jwt, JWTError
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api

router = APIRouter(tags=["tasks"])

# --- Schemas ---
class Task(BaseModel):
    inn: str
    company_name: str
    contact_name: Optional[str] = ""
    phone: Optional[str] = ""
    last_comment: Optional[str] = ""
    is_overdue: bool = False
    
class CallReport(BaseModel):
    inn: str
    comment: str
    next_call_date: str  # DD.MM.YY
    
class TodayCall(BaseModel):
    inn: str
    company_name: str
    contact_name: Optional[str] = ""
    phone: Optional[str] = ""
    comment: Optional[str] = ""
    next_call_date: Optional[str] = ""

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

@router.get("/tasks", response_model=List[Task])
async def get_tasks(user: Manager = Depends(get_current_user)):
    """Получить список задач для менеджера"""
    if not user.google_sheet_id:
        raise HTTPException(status_code=400, detail="Google Sheet not connected")
        
    google_sheets = get_google_sheets_service()
    
    missed_calls = await google_sheets.get_missed_calls(user.google_sheet_id)
    today_calls = await google_sheets.get_today_calls(user.google_sheet_id)
    
    tasks = []
    
    # Просроченные
    for call in missed_calls:
        details = await google_sheets.find_company_by_inn(user.google_sheet_id, call['inn'])
        if details:
            tasks.append(Task(
                inn=call['inn'],
                company_name=call['company_name'],
                contact_name=details.get('contact_name', ''),
                phone=call['phone'],
                last_comment=details.get('comment', ''),
                is_overdue=True
            ))
            
    # На сегодня
    for call in today_calls:
        tasks.append(Task(
            inn=call['inn'],
            company_name=call['company_name'],
            contact_name=call.get('contact_name', ''),
            phone=call['phone'],
            last_comment=call.get('comment', ''),
            is_overdue=False
        ))
        
    return tasks

@router.post("/report")
async def submit_report(report: CallReport, user: Manager = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    """Отправить отчет о звонке (повторный звонок из задач)"""
    if not user.google_sheet_id:
        raise HTTPException(status_code=400, detail="Google Sheet not connected")
        
    google_sheets = get_google_sheets_service()
    
    # 1. Находим компанию
    company_data = await google_sheets.find_company_by_inn(user.google_sheet_id, report.inn)
    if not company_data:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # 2. Обновляем Google Sheet менеджера
    call_data_for_sheet = {
        'comment': report.comment,
        'next_call_date': report.next_call_date
    }
    
    success = await google_sheets.update_repeat_call(
        user.google_sheet_id,
        report.inn,
        call_data_for_sheet
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update Google Sheet")
    
    # 3. Обновляем финансовые данные из DataNewton
    try:
        fresh = await datanewton_api.get_full_company_data(report.inn)
        if fresh:
            column_updates = {
                'G': fresh.get('revenue_previous', ''),
                'H': fresh.get('revenue', ''),
                'I': fresh.get('net_profit', ''),
                'J': fresh.get('capital', ''),
                'K': fresh.get('assets', ''),
                'L': fresh.get('debit', ''),
                'M': fresh.get('credit', ''),
                'N': fresh.get('gov_contracts', ''),
                'O': fresh.get('okved', ''),
                'P': fresh.get('okpd_name', ''),
            }
            await google_sheets.update_specific_columns(user.google_sheet_id, report.inn, column_updates)
    except Exception as e:
        logger.warning(f"DataNewton refresh on report failed: {e}")
    
    # 4. Обновляем сводную таблицу
    supervisor_data = {
        'company_name': company_data.get('company_name'),
        'inn': report.inn,
        'contact_name': company_data.get('contact_name'),
        'phone': company_data.get('phone'),
        'comment': report.comment,
        'next_call_date': report.next_call_date
    }
    
    await google_sheets.update_supervisor_sheet(user.full_name, supervisor_data)
    
    # 5. Сохраняем в БД
    call_session = CallSession(
        manager_id=user.id,
        session_type='web_repeat',
        company_inn=report.inn,
        company_name=company_data.get('company_name'),
        contact_name=company_data.get('contact_name'),
        contact_phone=company_data.get('phone'),
        comment=report.comment,
        next_call_date=datetime.strptime(report.next_call_date, "%d.%m.%y") if report.next_call_date else None
    )
    session.add(call_session)
    await session.commit()
    
    return {"status": "ok"}


# --- Sheets endpoints ---

@router.get("/sheets/my")
async def get_my_sheet(user: Manager = Depends(get_current_user)):
    """Получить ссылку на таблицу менеджера"""
    if not user.google_sheet_id:
        raise HTTPException(status_code=400, detail="Google Sheet не подключена")
    
    return {
        "url": f"https://docs.google.com/spreadsheets/d/{user.google_sheet_id}",
        "sheet_id": user.google_sheet_id
    }

@router.get("/sheets/today_calls", response_model=List[TodayCall])
async def get_today_calls_list(user: Manager = Depends(get_current_user)):
    """Получить полный список звонков на сегодня"""
    if not user.google_sheet_id:
        raise HTTPException(status_code=400, detail="Google Sheet не подключена")
    
    google_sheets = get_google_sheets_service()
    today_calls = await google_sheets.get_today_calls(user.google_sheet_id)
    
    return [
        TodayCall(
            inn=call['inn'],
            company_name=call['company_name'],
            contact_name=call.get('contact_name', ''),
            phone=call['phone'],
            comment=call.get('comment', ''),
            next_call_date=call.get('next_call_date', '')
        )
        for call in today_calls
    ]
