import csv
import io
import uuid
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from loguru import logger

from models.database import get_session, Manager
from backend.routers.auth import oauth2_scheme
from backend.security import get_password_hash, SECRET_KEY, ALGORITHM
from jose import jwt, JWTError
from config import settings
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api

router = APIRouter(tags=["admin"], prefix="/admin")

# --- In-memory task status store ---
_task_status: Dict[str, Dict[str, Any]] = {}

# --- Schemas ---
class ManagerSchema(BaseModel):
    id: int
    full_name: str
    login: Optional[str] = None
    is_active: bool
    has_telegram: bool
    has_sheet: bool
    telegram_id: Optional[int] = None
    google_sheet_id: Optional[str] = None
    role: Optional[str] = None
    created_at: Optional[str] = None

class CreateUserRequest(BaseModel):
    manager_id: int
    login: str
    password: str

class AddManagerRequest(BaseModel):
    full_name: str
    telegram_id: Optional[int] = None

class UpdateOneCompanyRequest(BaseModel):
    inn: str
    manager_id: int

# --- Dependency ---
async def get_current_admin(token: str = Depends(oauth2_scheme), session: AsyncSession = Depends(get_session)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None or role != "admin":
            raise HTTPException(status_code=403, detail="Not authorized")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    result = await session.execute(select(Manager).where(Manager.login == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# --- Endpoints ---

@router.get("/managers", response_model=List[ManagerSchema])
async def get_managers(admin: Manager = Depends(get_current_admin), session: AsyncSession = Depends(get_session)):
    """Получить список всех менеджеров"""
    result = await session.execute(select(Manager).order_by(Manager.id))
    managers = result.scalars().all()
    
    return [
        ManagerSchema(
            id=m.id,
            full_name=m.full_name,
            login=m.login,
            is_active=m.is_active,
            has_telegram=bool(m.telegram_id),
            has_sheet=bool(m.google_sheet_id),
            telegram_id=m.telegram_id,
            google_sheet_id=m.google_sheet_id,
            role=m.role,
            created_at=m.created_at.strftime('%d.%m.%Y') if m.created_at else None
        )
        for m in managers
    ]

@router.post("/create_access")
async def create_web_access(
    request: CreateUserRequest, 
    admin: Manager = Depends(get_current_admin), 
    session: AsyncSession = Depends(get_session)
):
    """Создать/обновить веб-доступ для менеджера"""
    
    # Проверяем, не занят ли логин другим пользователем
    result = await session.execute(select(Manager).where(Manager.login == request.login))
    existing_login = result.scalar_one_or_none()
    if existing_login and existing_login.id != request.manager_id:
        raise HTTPException(status_code=400, detail="Этот логин уже занят")
        
    # Получаем менеджера
    result = await session.execute(select(Manager).where(Manager.id == request.manager_id))
    manager = result.scalar_one_or_none()
    
    if not manager:
        raise HTTPException(status_code=404, detail="Менеджер не найден")
        
    # Обновляем данные
    manager.login = request.login
    manager.password_hash = get_password_hash(request.password)
    # Если у менеджера не было роли, ставим manager
    if not manager.role:
        manager.role = "manager"
        
    await session.commit()
    
    return {"status": "ok", "message": f"Доступ для {manager.full_name} создан"}


@router.post("/add_manager")
async def add_manager(
    request: AddManagerRequest,
    admin: Manager = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Добавить нового менеджера (создает Google Sheet)"""
    
    # Проверяем дубликат по telegram_id
    if request.telegram_id:
        result = await session.execute(
            select(Manager).where(Manager.telegram_id == request.telegram_id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Менеджер с таким Telegram ID уже существует")
    
    # Создаем Google Sheet
    try:
        google_sheets = get_google_sheets_service()
        sheet_id = await google_sheets.create_manager_sheet(request.full_name)
        
        if not sheet_id:
            raise HTTPException(status_code=500, detail="Не удалось создать Google таблицу")
        
        new_manager = Manager(
            telegram_id=request.telegram_id,
            full_name=request.full_name,
            google_sheet_id=sheet_id,
            is_active=True
        )
        session.add(new_manager)
        await session.commit()
        await session.refresh(new_manager)
        
        return {
            "status": "ok",
            "message": f"Менеджер {request.full_name} добавлен",
            "manager_id": new_manager.id,
            "sheet_id": sheet_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating manager: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)[:200]}")


@router.post("/toggle_manager/{manager_id}")
async def toggle_manager(
    manager_id: int,
    admin: Manager = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Активировать/деактивировать менеджера"""
    result = await session.execute(select(Manager).where(Manager.id == manager_id))
    manager = result.scalar_one_or_none()
    
    if not manager:
        raise HTTPException(status_code=404, detail="Менеджер не найден")
    
    manager.is_active = not manager.is_active
    await session.commit()
    
    status_text = "активирован" if manager.is_active else "деактивирован"
    return {"status": "ok", "message": f"Менеджер {manager.full_name} {status_text}", "is_active": manager.is_active}


@router.delete("/manager/{manager_id}")
async def delete_manager(
    manager_id: int,
    admin: Manager = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Удалить менеджера (только неактивных)"""
    result = await session.execute(select(Manager).where(Manager.id == manager_id))
    manager = result.scalar_one_or_none()
    
    if not manager:
        raise HTTPException(status_code=404, detail="Менеджер не найден")
    
    if manager.is_active:
        raise HTTPException(status_code=400, detail="Нельзя удалить активного менеджера. Сначала деактивируйте.")
    
    manager_name = manager.full_name
    await session.delete(manager)
    await session.commit()
    
    return {"status": "ok", "message": f"Менеджер {manager_name} удален"}


@router.get("/supervisor_sheet")
async def get_supervisor_sheet(admin: Manager = Depends(get_current_admin)):
    """Получить ссылку на сводную таблицу"""
    sheet_id = settings.supervisor_sheet_id
    return {
        "url": f"https://docs.google.com/spreadsheets/d/{sheet_id}",
        "sheet_id": sheet_id
    }


# --- CSV Import ---

def _format_imported_comments(row):
    """Форматировать комментарии из CSV (скопировано из bot/handlers/csv_import.py)"""
    import re
    comments = []
    today = datetime.now().strftime('%d.%m.%y')
    
    if len(row) > 6 and row[6].strip():
        raw_comment = row[6].strip()
        date_match = re.match(r'^\[?(\d{2}[\./-]\d{2}[\./-]\d{2,4})\]?', raw_comment)
        
        if date_match:
            existing_date = date_match.group(1)
            rest_of_comment = raw_comment[len(date_match.group(0)):].strip()
            if rest_of_comment.startswith(('-', ':', '.')):
                rest_of_comment = rest_of_comment.lstrip('-:. ').strip()
            comments.append(f"[{existing_date}] {rest_of_comment}")
        else:
            comments.append(f"[{today}] {raw_comment}")
    
    if len(row) > 7 and row[7].strip():
        comments.append(row[7].strip())
    
    if len(row) > 8 and row[8].strip():
        comments.append(row[8].strip())
    
    return "\n---\n".join(comments) if comments else ""


async def _background_csv_import(task_id: str, data_rows, manager_name: str, sheet_id: str):
    """Background CSV import task"""
    global _task_status
    _task_status[task_id] = {"status": "running", "total": len(data_rows), "processed": 0, "success": 0, "errors": 0}
    
    google_sheets = get_google_sheets_service()
    
    try:
        await google_sheets._setup_sheet_headers(sheet_id)
    except Exception as e:
        logger.warning(f"Headers setup failed: {e}")
    
    for i, row in enumerate(data_rows, 1):
        try:
            if len(row) < 7:
                _task_status[task_id]["errors"] += 1
                _task_status[task_id]["processed"] = i
                continue
            
            inn = row[1].strip()
            if len(inn) == 9:
                inn = "0" + inn
            elif len(inn) == 11:
                inn = "0" + inn
            
            company_name = row[0].strip()
            
            company_api_data = {}
            if inn:
                try:
                    await asyncio.sleep(0.5)
                    api_result = await datanewton_api.get_full_company_data(inn)
                    if api_result:
                        company_api_data = api_result
                except Exception as e:
                    logger.warning(f"API fetch failed for {inn}: {e}")
            
            call_data = {
                'company_name': company_api_data.get('name') or company_name,
                'inn': inn,
                'contact_name': row[2].strip() if len(row) > 2 else '',
                'phone': row[3].strip() if len(row) > 3 else '',
                'first_call_date': (
                    row[16].strip() if len(row) > 16 and row[16].strip() else (
                        row[4].strip() if len(row) > 4 and row[4].strip() else datetime.now().strftime('%d.%m.%y')
                    )
                ),
                'next_call_date': row[5].strip() if len(row) > 5 else '',
                'comment': _format_imported_comments(row),
                'revenue': str(company_api_data.get('revenue') or
                               (row[7].strip() if len(row) > 7 and len(row) > 15 else (row[9].strip() if len(row) > 9 else ''))),
                'revenue_previous': str(company_api_data.get('revenue_previous') or
                                        (row[6].strip() if len(row) > 6 and len(row) > 15 else (row[10].strip() if len(row) > 10 else ''))),
                'capital': str(company_api_data.get('capital') or
                               (row[9].strip() if len(row) > 9 and len(row) > 15 else (row[11].strip() if len(row) > 11 else ''))),
                'assets': str(company_api_data.get('assets') or
                              (row[10].strip() if len(row) > 10 and len(row) > 15 else (row[12].strip() if len(row) > 12 else ''))),
                'debit': str(company_api_data.get('debit') or
                             (row[11].strip() if len(row) > 11 and len(row) > 15 else (row[13].strip() if len(row) > 13 else ''))),
                'credit': str(company_api_data.get('credit') or
                              (row[12].strip() if len(row) > 12 and len(row) > 15 else (row[14].strip() if len(row) > 14 else ''))),
                'net_profit': str(company_api_data.get('net_profit') or
                                  (row[8].strip() if len(row) > 8 and len(row) > 15 else '')),
                'gov_contracts': str(company_api_data.get('gov_contracts') or
                                     (row[13].strip() if len(row) > 13 and len(row) > 15 else (row[18].strip() if len(row) > 18 else ''))),
                'okved_main': str(company_api_data.get('okved') or
                                  (row[14].strip() if len(row) > 14 and len(row) > 15 else (row[17].strip() if len(row) > 17 else ''))),
                'okpd_name': str(company_api_data.get('okpd_name') or
                                 (row[15].strip() if len(row) > 15 and len(row) > 15 else '')),
            }
            
            if await google_sheets.add_new_call(sheet_id, call_data, check_headers=False):
                await asyncio.sleep(1.2)
                await google_sheets.update_supervisor_sheet(manager_name, call_data, check_headers=False)
                await asyncio.sleep(1.2)
                _task_status[task_id]["success"] += 1
            else:
                _task_status[task_id]["errors"] += 1
                
        except Exception as e:
            logger.error(f"CSV row {i} error: {e}")
            _task_status[task_id]["errors"] += 1
        
        _task_status[task_id]["processed"] = i
    
    _task_status[task_id]["status"] = "completed"


@router.post("/import_csv")
async def import_csv(
    file: UploadFile = File(...),
    manager_id: int = Form(...),
    admin: Manager = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Импорт CSV файла для менеджера"""
    
    # Проверяем менеджера
    result = await session.execute(select(Manager).where(Manager.id == manager_id))
    manager = result.scalar_one_or_none()
    
    if not manager or not manager.google_sheet_id:
        raise HTTPException(status_code=404, detail="Менеджер или таблица не найдены")
    
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате CSV")
    
    # Читаем файл
    content = await file.read()
    text = content.decode('utf-8-sig')
    
    delimiter = ';' if ';' in text.split('\n')[0] else ','
    csv_reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(csv_reader)
    
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="Файл пустой или содержит только заголовки")
    
    data_rows = rows[1:] if len(rows[0]) >= 7 else rows
    
    # Запускаем фоновую задачу
    task_id = str(uuid.uuid4())[:8]
    asyncio.create_task(
        _background_csv_import(task_id, data_rows, manager.full_name, manager.google_sheet_id)
    )
    
    return {
        "status": "ok",
        "task_id": task_id,
        "total_rows": len(data_rows),
        "message": f"Импорт запущен для {manager.full_name}"
    }


@router.get("/import_status/{task_id}")
async def get_import_status(task_id: str, admin: Manager = Depends(get_current_admin)):
    """Получить статус фонового импорта"""
    if task_id not in _task_status:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return _task_status[task_id]


# --- DataNewton Update ---

async def _background_datanewton_update(task_id: str, manager_name: str, sheet_id: str):
    """Background DataNewton update task"""
    global _task_status
    _task_status[task_id] = {"status": "running", "total": 0, "processed": 0, "updated": 0, "skipped": 0, "errors": 0}
    
    google_sheets = get_google_sheets_service()
    
    try:
        result = google_sheets.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='A:P'
        ).execute()
        values = result.get('values', [])
        
        if len(values) < 2:
            _task_status[task_id]["status"] = "completed"
            return
        
        total_rows = len(values) - 1
        _task_status[task_id]["total"] = total_rows
        
        for i, row in enumerate(values[1:], 1):
            try:
                inn = row[1].strip() if len(row) > 1 else ""
                if not inn:
                    _task_status[task_id]["skipped"] += 1
                    _task_status[task_id]["processed"] = i
                    continue
                
                needs_update = False
                revenue = row[7].strip() if len(row) > 7 else ""
                if not revenue or revenue == "0" or revenue == "0 ₽":
                    needs_update = True
                gov = row[13].strip() if len(row) > 13 else ""
                if not gov:
                    needs_update = True
                okpd = row[15].strip() if len(row) > 15 else ""
                if not okpd:
                    needs_update = True
                
                if not needs_update:
                    _task_status[task_id]["skipped"] += 1
                    _task_status[task_id]["processed"] = i
                    continue
                
                await asyncio.sleep(0.5)
                fresh_data = await datanewton_api.get_full_company_data(inn)
                
                if fresh_data:
                    column_updates = {
                        'G': fresh_data.get('revenue_previous', ''),
                        'H': fresh_data.get('revenue', ''),
                        'I': fresh_data.get('net_profit', ''),
                        'J': fresh_data.get('capital', ''),
                        'K': fresh_data.get('assets', ''),
                        'L': fresh_data.get('debit', ''),
                        'M': fresh_data.get('credit', ''),
                        'N': fresh_data.get('gov_contracts', ''),
                        'O': fresh_data.get('okved', ''),
                        'P': fresh_data.get('okpd_name', ''),
                    }
                    success = await google_sheets.update_specific_columns(sheet_id, inn, column_updates)
                    if success:
                        _task_status[task_id]["updated"] += 1
                    else:
                        _task_status[task_id]["errors"] += 1
                else:
                    _task_status[task_id]["skipped"] += 1
                    
            except Exception as e:
                logger.error(f"DataNewton update row {i} error: {e}")
                _task_status[task_id]["errors"] += 1
            
            _task_status[task_id]["processed"] = i
        
    except Exception as e:
        logger.error(f"DataNewton update global error: {e}")
        _task_status[task_id]["error_message"] = str(e)[:200]
    
    _task_status[task_id]["status"] = "completed"


@router.post("/update_datanewton/{manager_id}")
async def update_datanewton(
    manager_id: int,
    admin: Manager = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Запустить обновление DataNewton для менеджера"""
    result = await session.execute(select(Manager).where(Manager.id == manager_id))
    manager = result.scalar_one_or_none()
    
    if not manager or not manager.google_sheet_id:
        raise HTTPException(status_code=404, detail="Менеджер или таблица не найдены")
    
    task_id = str(uuid.uuid4())[:8]
    asyncio.create_task(
        _background_datanewton_update(task_id, manager.full_name, manager.google_sheet_id)
    )
    
    return {
        "status": "ok",
        "task_id": task_id,
        "message": f"Обновление запущено для {manager.full_name}"
    }


@router.post("/update_one_company")
async def update_one_company(
    request: UpdateOneCompanyRequest,
    admin: Manager = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
):
    """Обновить данные одной компании по ИНН"""
    inn = request.inn.strip()
    
    if not inn.isdigit() or len(inn) not in [10, 12]:
        raise HTTPException(status_code=400, detail="Некорректный ИНН. Введите 10 или 12 цифр.")
    
    # Получаем менеджера
    result = await session.execute(select(Manager).where(Manager.id == request.manager_id))
    manager = result.scalar_one_or_none()
    
    if not manager or not manager.google_sheet_id:
        raise HTTPException(status_code=404, detail="Менеджер или таблица не найдены")
    
    google_sheets = get_google_sheets_service()
    
    # Проверяем что компания есть в таблице
    company_data = await google_sheets.find_company_by_inn(manager.google_sheet_id, inn)
    if not company_data:
        raise HTTPException(status_code=404, detail=f"Компания с ИНН {inn} не найдена в таблице {manager.full_name}")
    
    # Получаем свежие данные из DataNewton
    fresh_data = await datanewton_api.get_full_company_data(inn)
    if not fresh_data:
        raise HTTPException(status_code=502, detail=f"Не удалось получить данные из DataNewton для ИНН {inn}")
    
    # Обновляем таблицу менеджера
    column_updates = {
        'G': fresh_data.get('revenue_previous', ''),
        'H': fresh_data.get('revenue', ''),
        'I': fresh_data.get('net_profit', ''),
        'J': fresh_data.get('capital', ''),
        'K': fresh_data.get('assets', ''),
        'L': fresh_data.get('debit', ''),
        'M': fresh_data.get('credit', ''),
        'N': fresh_data.get('gov_contracts', ''),
        'O': fresh_data.get('okved', ''),
        'P': fresh_data.get('okpd_name', ''),
    }
    
    success = await google_sheets.update_specific_columns(manager.google_sheet_id, inn, column_updates)
    if not success:
        raise HTTPException(status_code=500, detail="Ошибка при обновлении таблицы менеджера")
    
    # Обновляем сводную
    call_data = {
        'inn': inn,
        'company_name': company_data.get('company_name', ''),
        'contact_name': company_data.get('contact_name', ''),
        'phone': company_data.get('phone', ''),
        'next_call_date': company_data.get('next_call_date', ''),
        'comment': 'Обновлены данные DataNewton',
        'revenue_previous': fresh_data.get('revenue_previous', ''),
        'revenue': fresh_data.get('revenue', ''),
        'net_profit': fresh_data.get('net_profit', ''),
        'capital': fresh_data.get('capital', ''),
        'assets': fresh_data.get('assets', ''),
        'debit': fresh_data.get('debit', ''),
        'credit': fresh_data.get('credit', ''),
        'gov_contracts': fresh_data.get('gov_contracts', ''),
        'okved_main': fresh_data.get('okved', ''),
        'okpd_name': fresh_data.get('okpd_name', ''),
    }
    
    await google_sheets.update_supervisor_sheet(
        manager_name=manager.full_name,
        call_data=call_data,
        check_headers=False
    )
    
    return {
        "status": "ok",
        "message": f"Данные обновлены для ИНН {inn}",
        "company_name": company_data.get('company_name', ''),
        "manager": manager.full_name
    }
