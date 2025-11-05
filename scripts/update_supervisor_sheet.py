#!/usr/bin/env python3
"""
Скрипт для настройки заголовков и форматирования сводной таблицы руководителя
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from services.google_sheets import get_google_sheets_service
import asyncio

async def update_supervisor_sheet():
    """Обновить заголовки сводной таблицы"""
    sheets_service = get_google_sheets_service()
    
    # Заголовки для сводной таблицы (с дополнительной колонкой "Менеджер")
    headers = [[
        "Наименование компании", "ИНН", "ФИО ЛПР", "Телефон", 
        "Дата первого звонка", "Дата звонка будущая", 
        "Комментарий 1 (последний звонок)", "Комментарий 2 (предыдущий звонок)", 
        "Комментарий 3 (предыдущий предыдущего звонка)",
        "Финансы (выручка прошлый год) тыс рублей", 
        "Финансы (выручка позапрошлый год) тыс рублей",
        "Капитал и резервы за прошлый год (тыс рублей)",
        "Основные средства за прошлый год (тыс рублей)",
        "Дебеторская задолженность за прошлый год (тыс рублей)",
        "Кредиторская задолженность за прошлый год (тыс рублей)",
        "Регион(+n часов к Москве)", "ОКВЭД", "ОКВЭД (основной)",
        "Госконтракты, сумма заключенных за всё время", 
        "Арбитражные дела, сумма активных арбитраж", 
        "Банкротство (да/нет)", "Телефон", "Почта", "Менеджер"
    ]]
    
    # Обновляем заголовки
    sheets_service.service.spreadsheets().values().update(
        spreadsheetId=settings.supervisor_sheet_id,
        range='A1:X1',
        valueInputOption='RAW',
        body={'values': headers}
    ).execute()
    
    # Форматируем заголовки и скрываем колонки
    format_request = {
        'requests': [{
            'repeatCell': {
                'range': {
                    'sheetId': 0,
                    'startRowIndex': 0,
                    'endRowIndex': 1
                },
                'cell': {
                    'userEnteredFormat': {
                        'backgroundColor': {'red': 0.8, 'green': 0.8, 'blue': 0.8},
                        'textFormat': {'bold': True},
                        'horizontalAlignment': 'CENTER',
                        'wrapStrategy': 'WRAP'
                    }
                },
                'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,wrapStrategy)'
            }
        }]
    }
    
    # Колонки для скрытия (те же что и у менеджеров)
    hidden_columns = [
        7,  # H - Комментарий 2
        8,  # I - Комментарий 3  
        9,  # J - Финансы (выручка прошлый год)
        10, # K - Финансы (выручка позапрошлый год)
        11, # L - Капитал и резервы
        12, # M - Основные средства
        13, # N - Дебиторская задолженность
        14  # O - Кредиторская задолженность
    ]
    
    for col_index in hidden_columns:
        format_request['requests'].append({
            'updateDimensionProperties': {
                'range': {
                    'sheetId': 0,
                    'dimension': 'COLUMNS',
                    'startIndex': col_index,
                    'endIndex': col_index + 1
                },
                'properties': {
                    'hiddenByUser': True
                },
                'fields': 'hiddenByUser'
            }
        })
    
    sheets_service.service.spreadsheets().batchUpdate(
        spreadsheetId=settings.supervisor_sheet_id,
        body=format_request
    ).execute()
    
    print(f"✅ Сводная таблица обновлена!")
    print(f"   Ссылка: https://docs.google.com/spreadsheets/d/{settings.supervisor_sheet_id}")
    print(f"   - Заголовки добавлены")
    print(f"   - Форматирование применено")
    print(f"   - Скрытые колонки настроены")

if __name__ == "__main__":
    asyncio.run(update_supervisor_sheet())



