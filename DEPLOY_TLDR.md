# 🚀 Быстрый старт деплоя на Railway

## Что делать ПРЯМО СЕЙЧАС:

### 1. Railway Dashboard → Web Service → Settings

#### **Connect GitHub:**
- Repository: `Vantorrr/combat`
- Branch: `main`

#### **Start Command:**
```
python start_all.py
```

#### **Environment Variables** (нажми "Raw Editor" и вставь все сразу):
```bash
BOT_TOKEN=<твой_токен_от_BotFather>
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials.json
MANAGER_SHEET_TEMPLATE_ID=<твой_template_id>
SUPERVISOR_SHEET_ID=<твой_supervisor_sheet_id>
DATANEWTON_API_KEY=<твой_DataNewton_ключ>
DATANEWTON_BASE_URL=https://api.datanewton.ru/v1
OPENAI_API_KEY=<твой_OpenAI_ключ>
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=openai/gpt-4.1-mini
ADMIN_IDS=275997508
REMINDER_TIMES=10:00,15:00,17:00
REPORT_TIME=19:00
TIMEZONE=Europe/Moscow
```

### 2. Подключи PostgreSQL к сервису

Settings → **Services** → нажми `+` рядом с Postgres
→ Railway автоматом добавит `$DATABASE_URL`

### 3. Загрузи файлы credentials

**Railway CLI:**
```bash
railway login
railway link
railway up credentials.json
railway up oauth_client.b64
```

### 4. Generate Domain

Settings → **Networking** → **Generate Domain**

Получишь URL вида: `https://xxx.up.railway.app`

---

## ✅ Всё! Проверка:

1. **PWA:** `https://твой-домен.up.railway.app`
   - Логин: `admin`
   - Пароль: `admin123`

2. **Telegram бот:** Напиши `/start`

3. **Создай веб-доступ менеджерам:**
   - Админка → Менеджеры → выбери менеджера → Создать доступ

---

## 🔧 Если что-то сломалось:

```bash
# Смотри логи
railway logs

# Проверь переменные
railway variables

# Переподключи БД
railway service link
```

---

**Важно:** `credentials.json` и `oauth_client.b64` должны быть в корне проекта на Railway. Без них Google Sheets не работает.
