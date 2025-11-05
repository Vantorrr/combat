import asyncio
from services.google_sheets import GoogleSheetsService
from config import settings

async def update_all_sheets():
    """Обновить заголовки во всех таблицах"""
    service = GoogleSheetsService()
    
    # Обновляем шаблон
    print(f"Обновляю шаблон таблицы: {settings.manager_sheet_template_id}")
    await service._setup_sheet_headers(settings.manager_sheet_template_id)
    print("✅ Шаблон обновлен")
    
    # Обновляем сводную таблицу
    print(f"Обновляю сводную таблицу: {settings.supervisor_sheet_id}")
    await service._setup_sheet_headers(settings.supervisor_sheet_id)
    print("✅ Сводная таблица обновлена")
    
    print("\n🎉 Все таблицы обновлены!")

if __name__ == "__main__":
    asyncio.run(update_all_sheets())



