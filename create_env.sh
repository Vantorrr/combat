#!/bin/bash

# Создание .env файла для CRM бота

cat > .env << 'EOF'
# Telegram Bot
BOT_TOKEN=your_bot_token_here

# Google Sheets  
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials.json
MANAGER_SHEET_TEMPLATE_ID=your_template_sheet_id_here
SUPERVISOR_SHEET_ID=your_supervisor_sheet_id_here

# DataNewton API
DATANEWTON_API_KEY=your_datanewton_api_key_here

# Database (для начала используем SQLite)
DATABASE_URL=sqlite+aiosqlite:///./crmbot.db

# Admin Telegram IDs (добавь свой ID)
ADMIN_IDS=your_telegram_id_here

# Scheduler
REMINDER_TIME=09:00
EOF

echo "✅ Файл .env создан!"
echo ""
echo "⚠️  НЕ ЗАБУДЬ:"
echo "1. Вставить токен бота вместо 'your_bot_token_here'"
echo "2. Добавить свой Telegram ID"
echo "3. Добавить ID Google таблиц"
echo "4. Добавить API ключ DataNewton"



