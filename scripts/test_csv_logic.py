
def test_logic():
    # 1. Имитация данных
    # Ситуация: API вернул словарь, но значения в нем None (как при ошибке 403)
    company_api_data = {
        'revenue': None, 
        'gov_contracts': None
    }
    
    # Строка из CSV (индексы условные, как в коде)
    # 0-name, 1-inn, 2-contact, 3-phone, 4-date, 5-next, 6-comm, 7, 8, 9-REV, ..., 18-GOV
    row = [""] * 20
    row[9] = "500000" # Выручка в CSV
    row[18] = "123456" # Госконтракты в CSV
    row[4] = "01.01.2023" # Дата в CSV

    # 2. Логика, которая БЫЛА (примерно, как я предполагаю баг)
    # old_revenue = str(company_api_data.get('revenue', '')) or row[9]
    # Если get возвращает None, str(None) -> "None", и "None" or "500000" -> "None". Ошибка!

    # 3. Логика, которая СЕЙЧАС (мой фикс)
    revenue_new = str(company_api_data.get('revenue') or (row[9].strip() if len(row) > 9 else ''))
    gov_new = str(company_api_data.get('gov_contracts') or (row[18].strip() if len(row) > 18 else ''))
    
    # Логика даты
    date_new = row[4].strip() if len(row) > 4 and row[4].strip() else "СЕГОДНЯ"
    
    # Проверка пустой даты
    row_empty_date = [""] * 20
    row_empty_date[4] = ""
    date_empty_new = row_empty_date[4].strip() if len(row_empty_date) > 4 and row_empty_date[4].strip() else "СЕГОДНЯ"

    print(f"Выручка (ожидаем 500000): {revenue_new}")
    print(f"Госконтракты (ожидаем 123456): {gov_new}")
    print(f"Дата заполненная (ожидаем 01.01.2023): {date_new}")
    print(f"Дата пустая (ожидаем СЕГОДНЯ): {date_empty_new}")

    if revenue_new == "500000" and gov_new == "123456" and date_new == "01.01.2023" and date_empty_new == "СЕГОДНЯ":
        print("✅ ТЕСТ ПРОЙДЕН: Логика работает корректно.")
    else:
        print("❌ ТЕСТ ПРОВАЛЕН")

test_logic()


