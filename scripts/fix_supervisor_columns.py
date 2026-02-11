#!/usr/bin/env python3
"""
Скрипт исправления сводной таблицы (Supervisor Sheet)

Проблемы:
1. Колонка R = Менеджер (должна быть "Дата последнего звонка")
2. Форматирование дат разное (15.2.2026, 1.12.25)

Решение:
1. Убираем колонку "Менеджер" (он есть в комментариях)
2. R = Дата последнего звонка
3. Форматируем даты как ДД.ММ.ГГГГ
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.google_sheets import get_google_sheets_service
from config import settings
from loguru import logger
from datetime import datetime
import re


def parse_date(date_str):
    """Парсит дату в разных форматах и возвращает как ДД.ММ.ГГГГ"""
    if not date_str or not isinstance(date_str, str):
        return ""
    
    date_str = str(date_str).strip()
    
    # Пробуем разные форматы
    formats = [
        "%d.%m.%Y",   # 15.02.2026
        "%d.%m.%y",   # 15.02.26
        "%-d.%-m.%Y", # 1.2.2026 (без ведущих нулей)
        "%-d.%-m.%y", # 1.2.26
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%d.%m.%Y")  # Всегда возвращаем полный формат
        except:
            pass
    
    # Если не распарсилось - пробуем регуляркой
    match = re.match(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', date_str)
    if match:
        day, month, year = match.groups()
        if len(year) == 2:
            year = "20" + year
        return f"{int(day):02d}.{int(month):02d}.{year}"
    
    return date_str  # Возвращаем как есть если не получилось


def main():
    print("🔧 Исправление сводной таблицы...")
    print("=" * 60)
    
    if not settings.supervisor_sheet_id:
        print("❌ SUPERVISOR_SHEET_ID не указан в настройках")
        return
    
    google_sheets = get_google_sheets_service()
    
    # 1. Обновляем заголовки
    print("\n1️⃣ Обновляем заголовки...")
    headers = [
        [
            "Наименование компании",  # A
            "ИНН",  # B
            "ФИО ЛПР",  # C
            "Телефон",  # D
            "Дата звонка будущая",  # E
            "История звонков (все комментарии)",  # F
            "Финансы (выручка позапрошлый год) тыс рублей",  # G
            "Финансы (выручка прошлый год) тыс рублей",  # H
            "Чистая прибыль за прошлый год (тыс рублей)",  # I
            "Капитал и резервы за прошлый год (тыс рублей)",  # J
            "Основные средства за прошлый год (тыс рублей)",  # K
            "Дебеторская задолженность за прошлый год (тыс рублей)",  # L
            "Кредиторская задолженность за прошлый год (тыс рублей)",  # M
            "Госконтракты, сумма заключенных за всё время",  # N
            "ОКВЭД (основной)",  # O
            "Наименование ОКПД",  # P
            "Дата первого звонка",  # Q
            "Дата последнего звонка",  # R (исправлено!)
        ]
    ]
    
    try:
        google_sheets.service.spreadsheets().values().update(
            spreadsheetId=settings.supervisor_sheet_id,
            range='A1:R1',
            valueInputOption='RAW',
            body={'values': headers}
        ).execute()
        print("✅ Заголовки обновлены")
    except Exception as e:
        print(f"❌ Ошибка обновления заголовков: {e}")
        return
    
    # 2. Читаем данные
    print("\n2️⃣ Читаем данные из таблицы...")
    try:
        result = google_sheets.service.spreadsheets().values().get(
            spreadsheetId=settings.supervisor_sheet_id,
            range='A2:S'  # Читаем с запасом (включая старую колонку S если есть)
        ).execute()
        values = result.get('values', [])
        print(f"✅ Найдено {len(values)} строк данных")
    except Exception as e:
        print(f"❌ Ошибка чтения данных: {e}")
        return
    
    if not values:
        print("✅ Таблица пуста, нечего исправлять")
        return
    
    # 3. Исправляем данные
    print("\n3️⃣ Исправляем данные...")
    updates = []
    fixed_count = 0
    
    for i, row in enumerate(values, 2):  # Начинаем со строки 2 (после заголовков)
        row_updates = []
        
        # Исправляем дату будущего звонка (E)
        if len(row) > 4 and row[4]:
            fixed_date = parse_date(row[4])
            if fixed_date != row[4]:
                row_updates.append({
                    'range': f'E{i}',
                    'values': [[fixed_date]]
                })
        
        # Исправляем дату первого звонка (Q - индекс 16)
        if len(row) > 16 and row[16]:
            fixed_date = parse_date(row[16])
            if fixed_date != row[16]:
                row_updates.append({
                    'range': f'Q{i}',
                    'values': [[fixed_date]]
                })
        
        # Колонка R: если там менеджер (текст) - заменяем на дату первого звонка
        if len(row) > 17:
            col_r_value = str(row[17]).strip()
            # Проверяем - это дата или текст (имя менеджера)?
            if col_r_value and not re.match(r'\d{1,2}\.\d{1,2}\.\d{2,4}', col_r_value):
                # Это текст (имя менеджера) - заменяем на дату первого звонка
                first_call_date = row[16] if len(row) > 16 else ""
                if first_call_date:
                    fixed_date = parse_date(first_call_date)
                    row_updates.append({
                        'range': f'R{i}',
                        'values': [[fixed_date]]
                    })
                    print(f"  Строка {i}: '{col_r_value}' → {fixed_date}")
            elif col_r_value:
                # Это дата - просто форматируем
                fixed_date = parse_date(col_r_value)
                if fixed_date != col_r_value:
                    row_updates.append({
                        'range': f'R{i}',
                        'values': [[fixed_date]]
                    })
        
        if row_updates:
            updates.extend(row_updates)
            fixed_count += 1
    
    # 4. Применяем изменения
    if updates:
        print(f"\n4️⃣ Применяем изменения ({len(updates)} ячеек в {fixed_count} строках)...")
        try:
            google_sheets.service.spreadsheets().values().batchUpdate(
                spreadsheetId=settings.supervisor_sheet_id,
                body={
                    'valueInputOption': 'USER_ENTERED',
                    'data': updates
                }
            ).execute()
            print(f"✅ Исправлено {fixed_count} строк!")
        except Exception as e:
            print(f"❌ Ошибка применения изменений: {e}")
            return
    else:
        print("\n✅ Все данные уже в правильном формате")
    
    print("\n" + "=" * 60)
    print("🎉 ГОТОВО!")
    print("=" * 60)
    print("\n📋 Что было сделано:")
    print("  ✅ Заголовки обновлены")
    print(f"  ✅ Даты отформатированы в ДД.ММ.ГГГГ")
    print(f"  ✅ Колонка R = 'Дата последнего звонка'")
    print(f"  ✅ Имена менеджеров убраны (остались в комментариях)")


if __name__ == "__main__":
    main()
