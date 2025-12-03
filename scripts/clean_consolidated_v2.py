import asyncio
import os
import sys
import re
from typing import List, Dict, Any

# Добавляем корень проекта в sys.path
sys.path.append(os.getcwd())

from services.google_sheets import get_google_sheets_service
from config import settings

SHEET_ID = "1n1KGfZWz8qK6IIMsTnMs5qVXqUTmVmhMALK_DkIIyEM"

def clean_comment_text(text: str) -> str:
    """
    Умная очистка комментариев.
    Убирает полные дубликаты строк.
    Убирает дублирование дат.
    """
    if not text:
        return ""

    # Разбиваем на блоки по '---'
    parts = text.split('---')
    unique_parts = []
    seen_hashes = set()

    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        # Убираем внутренние дубли "Но с мобилы... Но с мобилы"
        # Если строка повторяется подряд
        lines = part.split('\n')
        unique_lines = []
        last_line = ""
        for line in lines:
            clean_line = line.strip()
            if not clean_line: continue
            if clean_line == last_line:
                continue
            unique_lines.append(clean_line)
            last_line = clean_line
        
        clean_part = " ".join(unique_lines)
        
        # Проверка на уникальность всего блока
        # Используем хеш для быстрого сравнения
        part_hash = hash(clean_part)
        if part_hash not in seen_hashes:
            seen_hashes.add(part_hash)
            unique_parts.append(clean_part)

    return "\n---\n".join(unique_parts)

async def clean_consolidated_sheet():
    print(f"🚀 Начинаю ЖЁСТКУЮ чистку таблицы: {SHEET_ID}")
    
    service = get_google_sheets_service()
    try:
        # 1. Читаем данные
        result = service.service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='A:AZ'
        ).execute()
        values = result.get('values', [])
        
        if not values:
            print("❌ Таблица пуста.")
            return

        header = values[0]
        print(f"📊 Всего строк исходно: {len(values)}")
        
        # 2. Пропускаем первые 15 строк мусора
        start_index = 15
        if len(values) > start_index:
            data_rows = values[start_index:]
        else:
            print("⚠️ Мало строк для удаления первых 15.")
            data_rows = values[1:] # Если строк мало, просто берем всё после заголовка

        cleaned_rows = []
        seen_inns = set()
        deleted_tests = 0
        
        # Идем С КОНЦА, чтобы сохранять самые свежие записи для дубликатов ИНН
        # (предполагаем, что новые записи добавляются вниз)
        for row in reversed(data_rows):
            if not row: continue
            
            row_str = str(row).lower()
            
            # ЖЁСТКАЯ проверка на Тест
            if 'тест' in row_str:
                deleted_tests += 1
                continue
                
            # Проверка ИНН (колонка B, index 1)
            inn = row[1].strip() if len(row) > 1 else ""
            
            # Если ИНН уже видели (а мы идем с конца = видели более свежий), пропускаем старый
            if inn and inn in seen_inns:
                continue
            
            if inn:
                seen_inns.add(inn)
            
            # Чистка комментариев (колонка F, index 5)
            if len(row) > 5:
                row[5] = clean_comment_text(row[5])
            
            cleaned_rows.append(row)
            
        # Разворачиваем обратно, чтобы был правильный порядок
        cleaned_rows.reverse()
        
        final_values = [header] + cleaned_rows
        
        print(f"🗑 Удалено 'Тест': {deleted_tests}")
        print(f"✅ Итого строк: {len(final_values)}")
        
        # 3. Перезаписываем
        service.service.spreadsheets().values().clear(
            spreadsheetId=SHEET_ID,
            range='A:AZ'
        ).execute()
        
        service.service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range='A1',
            valueInputOption='USER_ENTERED',
            body={'values': final_values}
        ).execute()
        
        print("💾 Таблица успешно обновлена!")

    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(clean_consolidated_sheet())

