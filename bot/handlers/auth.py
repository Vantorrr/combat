from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from google_auth_oauthlib.flow import Flow
from loguru import logger
import os
import json
import base64
from pathlib import Path

router = Router()

class AuthStates(StatesGroup):
    waiting_for_code = State()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_oauth_client_config():
    """Получить конфигурацию OAuth клиента из env или файла."""
    client_b64 = os.getenv("GOOGLE_OAUTH_CLIENT_JSON_B64")
    if client_b64:
        try:
            return json.loads(base64.b64decode(client_b64))
        except Exception as e:
            logger.error(f"Failed to decode GOOGLE_OAUTH_CLIENT_JSON_B64: {e}")
    
    if os.path.exists("oauth_client.json"):
        with open("oauth_client.json", "r") as f:
            return json.load(f)
            
    return None

@router.message(Command("auth"))
async def cmd_auth(message: types.Message, state: FSMContext):
    """Начать процесс авторизации Google OAuth."""
    client_config = get_oauth_client_config()
    if not client_config:
        await message.answer("❌ Ошибка: конфигурация OAuth клиента не найдена.")
        return

    # Создаем flow с redirect_uri='urn:ietf:wg:oauth:2.0:oob' для ручного копирования кода
    try:
        flow = Flow.from_client_config(
            client_config=client_config,
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )
        
        auth_url, _ = flow.authorization_url(prompt='consent')
        
        await state.update_data(flow_config=client_config) # Сохраняем конфиг во временном хранилище, так как Flow не сериализуется
        await state.set_state(AuthStates.waiting_for_code)
        
        await message.answer(
            "🔑 **Авторизация Google**\n\n"
            "1. Перейдите по ссылке ниже.\n"
            "2. Авторизуйтесь в нужном аккаунте Google.\n"
            "3. Скопируйте полученный код и отправьте его сюда ответным сообщением.\n\n"
            f"{auth_url}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Auth flow creation failed: {e}")
        await message.answer(f"❌ Ошибка при создании ссылки авторизации: {e}")

@router.message(AuthStates.waiting_for_code)
async def process_auth_code(message: types.Message, state: FSMContext):
    """Обработка кода авторизации."""
    code = message.text.strip()
    data = await state.get_data()
    client_config = data.get('flow_config')
    
    if not client_config:
        await message.answer("❌ Ошибка состояния. Попробуйте /auth заново.")
        await state.clear()
        return

    try:
        flow = Flow.from_client_config(
            client_config=client_config,
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )
        
        # Обмениваем код на токены
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        # Сохраняем token.json
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
        # Также сохраняем как token.b64 для совместимости с нашей логикой восстановления
        b64_str = base64.b64encode(creds.to_json().encode('utf-8')).decode('utf-8')
        with open('token.b64', 'w') as token_b64:
            token_b64.write(b64_str)
            
        await message.answer("✅ **Авторизация успешна!**\nТокен сохранен на сервере.\nТеперь бот должен перезагрузиться или подхватить новый токен.")
        
        # Пытаемся обновить сервис "на лету" (не обязательно сработает для текущих процессов, но для новых - да)
        # Но лучше просто сказать пользователю, что все ок.
        # Можно триггернуть ре-инит сервиса, если очень хочется:
        from services.google_sheets import get_google_sheets_service
        service = get_google_sheets_service()
        # Force re-init logic if we added it (currently __init__ calls _initialize_service)
        # We can manually call _initialize_service again
        try:
            service._initialize_service()
            await message.answer("♻️ Сервис таблиц перезагружен с новыми правами.")
        except Exception as e:
            logger.warning(f"Service re-init warning: {e}")

        await state.clear()
        
    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        await message.answer(f"❌ Ошибка при получении токена: {e}\nПопробуйте /auth заново.")
        await state.clear()

