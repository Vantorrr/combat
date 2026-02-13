# 🚀 Инструкция по развертыванию на Railway

## ✅ Что уже готово
- ✅ Код запушен в GitHub
- ✅ PostgreSQL база развернута на Railway
- ✅ Миграция БД выполнена (колонки login, password_hash, role добавлены)
- ✅ Admin-аккаунт создан: `admin` / `admin123`

---

## 📦 Развертывание на Railway

### 1️⃣ Настройка Web-сервиса

Зайди в Railway Dashboard → твой проект → сервис **web** (или создай новый).

#### a) Подключи GitHub репозиторий
- Settings → Connect to GitHub
- Выбери репозиторий: `Vantorrr/combat`
- Branch: `main`

#### b) Настрой переменные окружения (Environment Variables)

Нажми **Variables** и добавь следующие переменные:

```bash
# Telegram Bot
BOT_TOKEN=твой_токен_бота_от_BotFather

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials.json
MANAGER_SHEET_TEMPLATE_ID=твой_template_id
SUPERVISOR_SHEET_ID=твой_supervisor_sheet_id

# DataNewton API
DATANEWTON_API_KEY=твой_api_ключ
DATANEWTON_BASE_URL=https://api.datanewton.ru/v1

# AI / OpenAI
OPENAI_API_KEY=твой_openai_ключ
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=openai/gpt-4.1-mini

# Database (Railway автоматически создаст $DATABASE_URL при подключении Postgres)
# НЕ НУЖНО прописывать вручную - Railway сам подставит

# Admin IDs
ADMIN_IDS=275997508,твой_telegram_id

# Scheduler
REMINDER_TIMES=10:00,15:00,17:00
REPORT_TIME=19:00
TIMEZONE=Europe/Moscow
```

#### c) Подключи PostgreSQL к web-сервису

- Settings → **Services** → нажми **+** рядом с твоим Postgres-сервисом
- Railway автоматически добавит переменную `$DATABASE_URL`

#### d) Загрузи файлы credentials

Railway требует `credentials.json` и `oauth_client.b64`:

**Вариант 1 (через Railway CLI):**
```bash
railway login
railway link  # выбери свой проект
railway up credentials.json
railway up oauth_client.b64
```

**Вариант 2 (через переменные):**
Преобразуй файлы в base64 и добавь как env-переменные:
```bash
# На Mac/Linux
cat credentials.json | base64 | pbcopy
cat oauth_client.b64 | base64 | pbcopy
```
Добавь переменные:
```
GOOGLE_CREDENTIALS_BASE64=<вставь base64 credentials.json>
OAUTH_CLIENT_BASE64=<вставь base64 oauth_client.b64>
```

И обнови `config.py` чтобы декодировать из env при старте.

#### e) Настрой команду запуска

Settings → **Deploy** → **Start Command**:

```bash
python main.py
```

Или если нужен отдельный web-процесс (Procfile):

Создай/обнови `Procfile`:
```
web: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
bot: python main.py
```

Тогда нужно создать 2 сервиса:
1. **web** (для PWA) - команда: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
2. **bot** (для Telegram бота) - команда: `python main.py`

#### f) Railway автоматически развернет

После сохранения Railway автоматически:
1. Склонит репозиторий
2. Установит зависимости из `requirements.txt`
3. Запустит сервис

---

### 2️⃣ Получи публичный URL

- Settings → **Networking** → **Generate Domain**
- Railway создаст URL вида: `https://твой-сервис.up.railway.app`

**Этот URL** — твой публичный адрес для PWA!

---

## 🔐 Первый вход

1. Открой: `https://твой-сервис.up.railway.app`
2. Логин: `admin`
3. Пароль: `admin123`

---

## 👥 Создание веб-доступа для менеджеров

После входа как admin:

1. **Менеджеры** → выбери менеджера из списка
2. **Создать доступ** → введи логин и пароль
3. Отправь менеджеру:
   - URL: `https://твой-сервис.up.railway.app`
   - Логин: `его_логин`
   - Пароль: `его_пароль`

---

## 🔧 Проверка работы

### Telegram бот
```bash
# Проверь логи в Railway
railway logs --service bot

# Напиши боту /start
# Должен ответить меню
```

### PWA Backend
```bash
# Проверь статус
curl https://твой-сервис.up.railway.app/api/health

# Должно вернуть: {"status":"ok"}
```

### База данных
```bash
# Подключись к Postgres
railway connect postgres

# Проверь менеджеров
SELECT id, full_name, login, role, is_active FROM managers;
```

---

## 🐛 Troubleshooting

### Ошибка подключения к БД
```bash
# Проверь что $DATABASE_URL установлен
railway variables

# Должна быть переменная DATABASE_URL
```

### OAuth токен истек
```bash
# Зайди в Railway → web service → Shell
railway run python scripts/refresh_oauth_token.py

# Вставь новый authorization code
```

### Бот не отвечает
```bash
# Проверь логи
railway logs --service bot

# Проверь что BOT_TOKEN правильный
railway variables | grep BOT_TOKEN
```

---

## 📝 Структура развертывания

```
Railway Project
├── Postgres (БД для всех сервисов)
├── web (FastAPI + PWA frontend)
│   ├── Команда: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
│   ├── Public URL: https://твой-сервис.up.railway.app
│   └── Переменные: $DATABASE_URL, $BOT_TOKEN, и т.д.
└── bot (Telegram бот, опционально отдельный сервис)
    ├── Команда: python main.py
    └── Переменные: те же что у web
```

**Рекомендация:** Держи бот и PWA в **одном сервисе** (запускается `main.py`, который стартует и FastAPI и Telegram бота).

Если нужны отдельные сервисы (для масштабирования), используй 2 сервиса с общими env-переменными.

---

## ✅ Готово!

После этого:
- ✅ Telegram бот работает
- ✅ PWA доступна по URL
- ✅ Менеджеры могут логиниться
- ✅ Все данные в одной PostgreSQL БД

**Важно:** Не забудь отправить менеджерам их логины/пароли для доступа к PWA!
