from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from loguru import logger

from models.database import get_session, Manager, CallSession
from backend.routers.auth import oauth2_scheme
from backend.security import SECRET_KEY, ALGORITHM
from jose import jwt, JWTError
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api

router = APIRouter(tags=["calls"], prefix="/calls")

# --- Schemas ---
class ValidateInnRequest(BaseModel):
    inn: str

class LookupInnRequest(BaseModel):
    inn: str

class NewCallRequest(BaseModel):
    inn: str
    company_name: str
    contact_name: str
    phone: str
    comment: str
    next_call_date: Optional[str] = ""  # DD.MM.YY
    # DataNewton enrichment data (passed from frontend after lookup)
    company_data: Optional[Dict[str, Any]] = None

class SearchRepeatRequest(BaseModel):
    inn: str

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

@router.post("/validate_inn")
async def validate_inn(
    request: ValidateInnRequest,
    user: Manager = Depends(get_current_user)
):
    """Валидация ИНН: проверка формата и дубликата в таблице"""
    inn = request.inn.strip()
    
    if not inn.isdigit() or len(inn) not in [10, 12]:
        return {"valid": False, "error": "ИНН должен содержать 10 или 12 цифр"}
    
    if not user.google_sheet_id:
        return {"valid": True, "duplicate": False}
    
    # Проверяем дубликат
    try:
        google_sheets = get_google_sheets_service()
        existing = await google_sheets.find_company_by_inn(user.google_sheet_id, inn)
        if existing:
            return {
                "valid": True,
                "duplicate": True,
                "existing_company": existing.get('company_name', 'Неизвестная')
            }
    except Exception as e:
        logger.warning(f"Error checking duplicate: {e}")
    
    return {"valid": True, "duplicate": False}


@router.post("/lookup_inn")
async def lookup_inn(
    request: LookupInnRequest,
    user: Manager = Depends(get_current_user)
):
    """Поиск компании по ИНН через DataNewton API"""
    inn = request.inn.strip()
    
    if not inn.isdigit() or len(inn) not in [10, 12]:
        raise HTTPException(status_code=400, detail="Некорректный ИНН")
    
    try:
        company_data = await datanewton_api.get_full_company_data(inn)
        if company_data and company_data.get('name'):
            return {
                "found": True,
                "company": {
                    "name": company_data.get('name', ''),
                    "inn": inn,
                    "okved": company_data.get('okved', ''),
                    "okved_name": company_data.get('okved_name', ''),
                    "address": company_data.get('address', ''),
                    "director": company_data.get('director', ''),
                    "status": company_data.get('status', ''),
                    "employees": company_data.get('employees', ''),
                    "revenue": company_data.get('revenue', ''),
                    "revenue_previous": company_data.get('revenue_previous', ''),
                    "net_profit": company_data.get('net_profit', ''),
                    "capital": company_data.get('capital', ''),
                    "assets": company_data.get('assets', ''),
                    "debit": company_data.get('debit', ''),
                    "credit": company_data.get('credit', ''),
                    "gov_contracts": company_data.get('gov_contracts', ''),
                    "okpd_name": company_data.get('okpd_name', ''),
                    "email": company_data.get('email', ''),
                    "region": company_data.get('region', ''),
                }
            }
        else:
            return {"found": False, "company": None}
    except Exception as e:
        logger.error(f"DataNewton lookup error: {e}")
        return {"found": False, "company": None, "error": str(e)[:100]}


@router.post("/new")
async def create_new_call(
    request: NewCallRequest,
    user: Manager = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Создать новый звонок (полный flow)"""
    if not user.google_sheet_id:
        raise HTTPException(status_code=400, detail="Google Sheet не подключена")
    
    inn = request.inn.strip()
    company_data = request.company_data or {}
    
    # Формируем комментарий с датой
    today = datetime.now().strftime("%d.%m.%y")
    comment_with_date = f"{today} - {request.comment}" if request.comment else ""
    
    # Сохраняем в БД
    call_session = CallSession(
        manager_id=user.id,
        session_type='new',
        company_inn=inn,
        company_name=request.company_name or company_data.get('name', 'Не указано'),
        contact_name=request.contact_name,
        contact_phone=request.phone,
        comment=comment_with_date,
        next_call_date=datetime.strptime(request.next_call_date, "%d.%m.%y") if request.next_call_date else None
    )
    session.add(call_session)
    await session.commit()
    
    # Подготавливаем данные для Google Sheets
    sheet_data = {
        'company_name': request.company_name or company_data.get('name', 'Не указано'),
        'inn': inn,
        'contact_name': request.contact_name,
        'phone': request.phone,
        'next_call_date': request.next_call_date or '',
        'comment': comment_with_date,
        'revenue': str(company_data.get('revenue', '')),
        'revenue_previous': str(company_data.get('revenue_previous', '')),
        'net_profit': str(company_data.get('net_profit', '')),
        'capital': str(company_data.get('capital', '')),
        'assets': str(company_data.get('assets', '')),
        'debit': str(company_data.get('debit', '')),
        'credit': str(company_data.get('credit', '')),
        'okved': str(company_data.get('okved', '')),
        'okved_main': str(company_data.get('okved', '')),
        'okved_name': str(company_data.get('okved_name', '')),
        'employees': str(company_data.get('employees', '')),
        'address': str(company_data.get('address', '')),
        'director': str(company_data.get('director', '')),
        'status': str(company_data.get('status', '')),
        'email': str(company_data.get('email', '')),
        'gov_contracts': str(company_data.get('gov_contracts', '')),
        'okpd_name': str(company_data.get('okpd_name', '')),
    }
    
    try:
        google_sheets = get_google_sheets_service()
        success = await google_sheets.add_new_call(user.google_sheet_id, sheet_data)
        
        if success:
            await google_sheets.update_supervisor_sheet(user.full_name, sheet_data)
            return {"status": "ok", "message": "Звонок сохранен", "saved_to_sheet": True}
        else:
            return {"status": "ok", "message": "Сохранено локально, ошибка Google Sheets", "saved_to_sheet": False}
    except Exception as e:
        logger.error(f"Error saving new call to sheets: {e}")
        return {"status": "ok", "message": "Сохранено локально", "saved_to_sheet": False}


@router.post("/search_for_repeat")
async def search_for_repeat(
    request: SearchRepeatRequest,
    user: Manager = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Поиск компании для повторного звонка (в БД и Google Sheets)"""
    inn = request.inn.strip()
    
    if not inn.isdigit() or len(inn) not in [10, 12]:
        raise HTTPException(status_code=400, detail="Некорректный ИНН")
    
    company_info = {
        "found": False,
        "source": None,
        "company_name": None,
        "contact_name": None,
        "phone": None,
        "last_comment": None,
    }
    
    # 1. Ищем в локальной БД
    result = await session.execute(
        select(CallSession).where(
            CallSession.manager_id == user.id,
            CallSession.company_inn == inn
        ).order_by(CallSession.created_at.desc())
    )
    existing = result.scalars().first()
    
    if existing:
        company_info = {
            "found": True,
            "source": "database",
            "company_name": existing.company_name,
            "contact_name": existing.contact_name,
            "phone": existing.contact_phone,
            "last_comment": existing.comment,
        }
    
    # 2. Ищем в Google Sheets если нет в БД
    if not existing and user.google_sheet_id:
        try:
            google_sheets = get_google_sheets_service()
            sheet_company = await google_sheets.find_company_by_inn(user.google_sheet_id, inn)
            if sheet_company:
                company_info = {
                    "found": True,
                    "source": "google_sheets",
                    "company_name": sheet_company.get('company_name', 'Не указано'),
                    "contact_name": sheet_company.get('contact_name', ''),
                    "phone": sheet_company.get('phone', ''),
                    "last_comment": sheet_company.get('comment', ''),
                }
        except Exception as e:
            logger.error(f"Error searching Google Sheets: {e}")
    
    return company_info
