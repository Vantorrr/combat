from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta
from pydantic import BaseModel

from backend.security import create_access_token, verify_password, ACCESS_TOKEN_EXPIRE_MINUTES
from models.database import get_session, Manager

router = APIRouter(tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class LoginRequest(BaseModel):
    login: str
    password: str


async def _authenticate(login: str, password: str, session: AsyncSession):
    """Общая логика аутентификации."""
    result = await session.execute(select(Manager).where(Manager.login == login))
    user = result.scalar_one_or_none()
    
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.login, "role": user.role, "id": user.id},
        expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer", "role": user.role, "name": user.full_name}


@router.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session)
):
    return await _authenticate(form_data.username, form_data.password, session)


@router.post("/auth/login")
async def login_json(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session)
):
    """JSON-эндпоинт для фронтенда."""
    return await _authenticate(body.login, body.password, session)
