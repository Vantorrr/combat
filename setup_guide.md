# CRM Bot - Руководство по настройке

## 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

## 2. Настройка Telegram бота

1. Создайте бота через @BotFather в Telegram
2. Получите токен бота
3. Сохраните токен для использования в .env файле

## 3. Настройка Google Sheets API

1. Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте новый проект или выберите существующий
3. Включите Google Sheets API и Google Drive API
4. Создайте Service Account:
   - В разделе "Credentials" нажмите "Create Credentials" → "Service Account"
   - Заполните данные и создайте аккаунт
   - Создайте ключ в формате JSON и скачайте его
   - Переименуйте файл в `credentials.json` и поместите в корень проекта

5. Создайте шаблон таблицы в Google Sheets:
   - Создайте новую таблицу
   - Настройте заголовки согласно структуре из ТЗ
   - Поделитесь таблицей с email вашего Service Account (находится в credentials.json)
   - Скопируйте ID таблицы из URL

## 4. Настройка DataNewton API

1. Зарегистрируйтесь на [datanewton.ru](https://datanewton.ru)
2. Получите API ключ в личном кабинете

## 5. Создание файла .env

Создайте файл `.env` в корне проекта:

```env
# Telegram Bot
BOT_TOKEN=your_telegram_bot_token_here

# Google Sheets  
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials.json
MANAGER_SHEET_TEMPLATE_ID=your_template_sheet_id_here
SUPERVISOR_SHEET_ID=your_supervisor_sheet_id_here

# DataNewton API
DATANEWTON_API_KEY=your_datanewton_api_key_here

# Database (для начала можно использовать SQLite)
DATABASE_URL=sqlite+aiosqlite:///./crmbot.db

# Admin Telegram IDs (через запятую)
ADMIN_IDS=your_telegram_id_here

# Scheduler
REMINDER_TIME=09:00
```

## 6. Запуск бота

```bash
python main.py
```

## 7. Первоначальная настройка

1. Напишите боту `/start` от имени администратора
2. Используйте меню "Управление менеджерами" для добавления менеджеров
3. При добавлении менеджера:
   - Менеджер должен написать боту `/start`
   - Менеджер должен переслать вам свой Telegram ID
   - Вы вводите этот ID в боте

## Структура таблицы

Таблица автоматически создается со следующими колонками:
- Наименование компании
- ИНН
- ФИО ЛПР
- Телефон
- Дата первого звонка
- Дата звонка будущая
- Комментарии к звонкам (3 последних)
- Финансовые показатели
- ОКВЭД
- И другие поля согласно ТЗ

## Возможные проблемы

1. **Ошибка с Google Sheets API**: Убедитесь, что Service Account имеет доступ к таблице
2. **Бот не отвечает**: Проверьте правильность токена и доступность бота
3. **Ошибка с DataNewton**: Проверьте лимиты API (1000 бесплатных запросов)



