#!/usr/bin/env python3
"""
Скрипт для исправления ИНН с ведущими нулями в сводной таблице

Проблема: ИНН начинающиеся с 0 обрезаются (0123 → 123)
Решение: Добавляем апостроф перед ИНН ('0123) чтобы Google Sheets хранил как текст
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.google_sheets import get_google_sheets_service
from config import settings
from loguru import logger


def main():
    print("🔧 Исправление ИНН в сводной таблице...")
    print("=" * 60)
    
    if not settings.supervisor_sheet_id:
        print("❌ SUPERVISOR_SHEET_ID не указан в настройках")
        return
    
    google_sheets = get_google_sheets_service()
    
    # 1. Читаем данные
    print("\n1️⃣ Читаем данные из таблицы...")
    try:
        result = google_sheets.service.spreadsheets().values().get(
            spreadsheetId=settings.supervisor_sheet_id,
            range='A2:B'  # Читаем только название и ИНН
        ).execute()
        values = result.get('values', [])
        print(f"✅ Найдено {len(values)} строк данных")
    except Exception as e:
        print(f"❌ Ошибка чтения данных: {e}")
        return
    
    if not values:
        print("✅ Таблица пуста, нечего исправлять")
        return
    
    # 2. Ищем ИНН с ведущими нулями
    print("\n2️⃣ Ищем ИНН с ведущими нулями...")
    updates = []
    fixed_count = 0
    
    for i, row in enumerate(values, 2):  # Начинаем со строки 2
        if len(row) > 1:
            inn = str(row[1]).strip()
            
            # Проверяем:
            # 1. ИНН должен быть числом (или строкой из цифр)
            # 2. Длина 9 или 11 (потеряли ведущий ноль)
            # 3. Или уже начинается с 0 но без апострофа
            
            needs_fix = False
            new_inn = inn
            
            # Если длина 9 или 11 - добавляем ведущий ноль
            if inn.isdigit() and len(inn) in [9, 11]:
                new_inn = f"'0{inn}"
                needs_fix = True
                print(f"  Строка {i}: {inn} → 0{inn} (добавлен ведущий 0)")
            
            # Если начинается с 0 но нет апострофа
            elif inn.isdigit() and inn.startswith('0') and not inn.startswith("'"):
                new_inn = f"'{inn}"
                needs_fix = True
                print(f"  Строка {i}: {inn} → '{inn} (добавлен апостроф)")
            
            if needs_fix:
                updates.append({
                    'range': f'B{i}',
                    'values': [[new_inn]]
                })
                fixed_count += 1
    
    # 3. Применяем изменения
    if updates:
        print(f"\n3️⃣ Применяем изменения ({len(updates)} ИНН)...")
        try:
            google_sheets.service.spreadsheets().values().batchUpdate(
                spreadsheetId=settings.supervisor_sheet_id,
                body={
                    'valueInputOption': 'USER_ENTERED',
                    'data': updates
                }
            ).execute()
            print(f"✅ Исправлено {fixed_count} ИНН!")
        except Exception as e:
            print(f"❌ Ошибка применения изменений: {e}")
            return
    else:
        print("\n✅ Все ИНН уже в правильном формате")
    
    print("\n" + "=" * 60)
    print("🎉 ГОТОВО!")
    print("=" * 60)
    print("\n📋 Что было сделано:")
    print(f"  ✅ Исправлено {fixed_count} ИНН с ведущими нулями")
    print("  ✅ Все ИНН теперь сохранены как текст (с апострофом)")


if __name__ == "__main__":
    main()
