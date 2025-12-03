import asyncio
import os
import sys

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from models import database
from models.database import Manager, init_db
from services.google_sheets import get_google_sheets_service
from config import settings

async def fix_locale_all_sheets():
    """
    Пройтись по всем таблицам (менеджеры + сводная), 
    установить локаль 'ru_RU' (чтобы разделитель тысяч был пробелом),
    и переприменить формат валюты.
    """
    print("🚀 Starting locale fix (ru_RU)...")
    
    # 1. Инициализация БД
    await init_db(settings.database_url_effective)
    sheets_service = get_google_sheets_service()
    
    # 2. Получаем всех менеджеров
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(select(Manager))
        managers = result.scalars().all()
    
    # 3. Список всех ID таблиц для обработки
    sheet_ids = []
    
    # Сводная таблица
    if settings.supervisor_sheet_id:
        sheet_ids.append(("Supervisor Sheet", settings.supervisor_sheet_id))
    
    # Таблицы менеджеров
    for m in managers:
        if m.google_sheet_id:
            sheet_ids.append((f"Manager: {m.full_name}", m.google_sheet_id))
            
    print(f"Found {len(sheet_ids)} sheets to update.")
    
    # 4. Обновляем каждую таблицу
    for name, sheet_id in sheet_ids:
        print(f"Processing {name} ({sheet_id})...")
        try:
            # Устанавливаем локаль
            sheets_service.set_spreadsheet_locale(sheet_id, 'ru_RU')
            
            # Получаем gid первого листа
            gid = sheets_service._get_first_sheet_gid(sheet_id)
            
            # Применяем валютный формат заново
            # Индексы колонок с деньгами: G(6), H(7), I(8), J(9), K(10), L(11), M(12), N(13)
            sheets_service._apply_currency_format(sheet_id, gid, [6, 7, 8, 9, 10, 11, 12, 13])
            
            print(f"✅ Success: {name}")
        except Exception as e:
            print(f"❌ Failed: {name} - {e}")
            
    print("🎉 Done! All sheets updated to Russian locale.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(fix_locale_all_sheets())

