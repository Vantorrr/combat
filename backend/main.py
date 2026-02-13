from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from contextlib import asynccontextmanager
import os

from config import settings
from models.database import init_db
from backend.routers import auth, tasks, admin, calls, ai

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Backend starting...")
    await init_db(settings.database_url_effective)
    yield
    # Shutdown
    logger.info("Backend shutting down...")

app = FastAPI(title="CRM Bot Backend", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(admin.router)
app.include_router(calls.router)
app.include_router(ai.router)

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

# Frontend (Static Files) - must be last
if not os.path.exists("frontend"):
    os.makedirs("frontend")
    
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
