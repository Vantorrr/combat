import asyncio
import os
import sys
from datetime import datetime

sys.path.append(os.getcwd())
from services.google_sheets import get_google_sheets_service

# ID таблицы Чертыковцева (мы его нашли ранее)
SHEET_ID = "1bvdlE9PxgZfGKWzIp2_w3vXN9cK5XJtswpnVP6744sQ"

async def test_fields():
    print("🔍 Проверка чтения расширенных полей для AI Плана...")
    service = get_google_sheets_service()
    
    # Используем обновленный get_today_calls
    calls = await service.get_today_calls(SHEET_ID)
    
    if not calls:
        print("⚠️ На сегодня нет звонков в этой таблице. Не могу проверить поля.")
        # Попробуем просто прочитать первую строку данных, чтобы убедиться в индексах
        res = service.service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='A2:N2' 
        ).execute()
        row = res.get('values', [])[0]
        print(f"📝 Тестовая строка (raw): {row}")
        print(f"   - Компания (A): {row[0]}")
        print(f"   - ИНН (B): {row[1]}")
        print(f"   - Комментарий (F, idx 5): {row[5] if len(row)>5 else 'ПУСТО'}")
        print(f"   - Выручка (H, idx 7): {row[7] if len(row)>7 else 'ПУСТО'}")
        print(f"   - Госконтракты (N, idx 13): {row[13] if len(row)>13 else 'ПУСТО'}")
        return

    print(f"✅ Найдено звонков на сегодня: {len(calls)}")
    first_call = calls[0]
    print("📋 Данные первого звонка (как видит бот):")
    print(f"   - Компания: {first_call.get('company_name')}")
    print(f"   - ИНН: {first_call.get('inn')}")
    print(f"   - Выручка (для AI): {first_call.get('revenue')}")
    print(f"   - Госконтракты (для AI): {first_call.get('gov_contracts')}")
    print(f"   - Комментарий: {first_call.get('comment')}")

    if first_call.get('revenue') is not None:
        print("\n✅ Тест пройден! Бот видит финансовые данные.")
    else:
        print("\n❌ Ошибка! Поле revenue не считалось.")

if __name__ == "__main__":
    asyncio.run(test_fields())



