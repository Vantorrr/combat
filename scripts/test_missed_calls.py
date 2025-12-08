"""
Скрипт для тестирования функции get_missed_calls
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.google_sheets import get_google_sheets_service
from models.database import init_db, get_session, Manager
from config import settings
from sqlalchemy import select


async def main():
    print("🔍 Тестирование функции get_missed_calls...")
    
    # Инициализируем БД
    await init_db(settings.database_url_effective)
    
    # Получаем всех менеджеров
    async for session in get_session():
        result = await session.execute(select(Manager).where(Manager.is_active == True))
        managers = result.scalars().all()
        
        print(f"\nНайдено менеджеров: {len(managers)}\n")
        
        google_sheets = get_google_sheets_service()
        
        for manager in managers:
            print(f"📊 Менеджер: {manager.full_name}")
            print(f"   Sheet ID: {manager.google_sheet_id}")
            print(f"   Telegram ID: {manager.telegram_id}")
            
            if not manager.google_sheet_id:
                print("   ⚠️ Нет sheet_id, пропускаем\n")
                continue
            
            try:
                missed_calls = await google_sheets.get_missed_calls(manager.google_sheet_id)
                print(f"   ✅ Пропущенных звонков: {len(missed_calls)}")
                
                if missed_calls:
                    print("   Список:")
                    for call in missed_calls[:5]:  # Показываем первые 5
                        print(f"      - {call['company_name']} (ИНН: {call['inn']}, план: {call['planned_date']})")
                    if len(missed_calls) > 5:
                        print(f"      ... и еще {len(missed_calls) - 5}")
                print()
            except Exception as e:
                print(f"   ❌ Ошибка: {e}\n")
                import traceback
                print(traceback.format_exc())
        
        await session.close()
        break


if __name__ == "__main__":
    asyncio.run(main())

