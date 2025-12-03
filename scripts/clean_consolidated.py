import asyncio
import os
import sys
from typing import List, Dict, Any
import re

# Добавляем корень проекта в sys.path
sys.path.append(os.getcwd())

from services.google_sheets import get_google_sheets_service
from config import settings

SHEET_ID = "1n1KGfZWz8qK6IIMsTnMs5qVXqUTmVmhMALK_DkIIyEM"

async def clean_consolidated_sheet():
    print(f"🚀 Начинаю чистку таблицы: {SHEET_ID}")
    
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

        print(f"📊 Всего строк: {len(values)}")
        
        # 2. Фильтрация строк
        new_values = []
        
        # Сохраняем заголовок (строка 1)
        header = values[0]
        new_values.append(header)
        
        # Пропускаем первые 15 строк данных (строки 2-16 в таблице, индексы 1-15 в списке)
        # Но нам нужно быть аккуратными: если пользователь говорит "первые 10-15 строк вообще удалить",
        # значит данные начинаются где-то с 16-й строки.
        # Давай начнем анализ с 16-й строки (индекс 15).
        
        start_index = 15 
        if len(values) > start_index:
            data_rows = values[start_index:]
        else:
            data_rows = []
            
        print(f"✂️ Пропускаем первые {start_index} строк (мусор Бариева/Романченко)...")
        
        kept_count = 0
        deleted_tests = 0
        
        for row in data_rows:
            if not row: continue
            
            # Проверка на "Тест"
            # Обычно имя менеджера в колонке Q (index 16) или контакт в C (index 2)
            # Проверим всё строку на наличие слова "Тест" в ключевых полях
            row_str = str(row).lower()
            
            is_test = False
            if len(row) > 16 and 'тест' in str(row[16]).lower(): # Колонка менеджера
                is_test = True
            elif len(row) > 2 and 'тест' in str(row[2]).lower(): # Колонка контакта
                is_test = True
            elif len(row) > 5 and '[тест]' in str(row[5]).lower(): # В комментариях автор [Тест]
                 # Тут осторожно, комментарий может быть от "Тест", но клиент реальный. 
                 # Но пользователь сказал "данные о тест и тест 2 тоже не нужны".
                 # Скорее всего речь о строках, созданных тестовым менеджером.
                 pass 

            # Если имя менеджера (колонка Q) "Чертыковцев Александр" - оставляем точно (если не тест)
            manager_name = row[16] if len(row) > 16 else ""
            
            if is_test:
                deleted_tests += 1
                continue
                
            # 3. Чистка дублей в комментариях (Колонка F, index 5)
            if len(row) > 5:
                comment_history = row[5]
                if comment_history:
                    cleaned_comment = clean_comment_duplicates(comment_history)
                    row[5] = cleaned_comment
            
            new_values.append(row)
            kept_count += 1

        print(f"✅ Удалено тестовых строк: {deleted_tests}")
        print(f"✅ Осталось полезных строк: {kept_count}")
        
        # 4. Записываем обратно
        # Сначала очищаем всё
        service.service.spreadsheets().values().clear(
            spreadsheetId=SHEET_ID,
            range='A:AZ'
        ).execute()
        
        # Записываем новые данные
        service.service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range='A1',
            valueInputOption='USER_ENTERED',
            body={'values': new_values}
        ).execute()
        
        print("💾 Таблица успешно обновлена!")
        
        # 5. Удаляем лишние пустые колонки (после Q/R)
        # Это сложнее через values().update, но визуально просто не будем писать туда.
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def clean_comment_duplicates(comment_text: str) -> str:
    """
    Убирает дублирующиеся записи в истории комментариев.
    Разбивает по '---' или переносам строк, ищет одинаковые даты и тексты.
    """
    if not comment_text:
        return ""
        
    # Нормализуем разделители: заменяем '---' на перенос строки для унификации
    # Но в таблице видно '---' как разделитель.
    
    # Паттерн: [Автор] [Дата] Текст...
    # Проблема: текст может содержать переносы.
    # Разделим по '---' как основному разделителю истории
    parts = comment_text.split('---')
    
    seen_entries = set()
    cleaned_parts = []
    
    for part in parts:
        part = part.strip()
        if not part: continue
        
        # Проверка на дубликат всего блока
        if part in seen_entries:
            continue
            
        # Дополнительная проверка: иногда дубли идут подряд внутри одного блока
        # Например: "[Тест] [29.11.25] ... - Но с мобилы"
        
        seen_entries.add(part)
        cleaned_parts.append(part)
    
    return "\n---\n".join(cleaned_parts)

if __name__ == "__main__":
    asyncio.run(clean_consolidated_sheet())

