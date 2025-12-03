import asyncio
import sys
import os

# Add project root to python path
sys.path.append(os.getcwd())

from aiogram import Bot
from config import settings

async def send_test_report():
    bot = Bot(token=settings.bot_token)
    
    # Пример данных
    fake_missed_count = 3
    fake_manager_name = "Иван Иванов"
    
    msg_admin = (
        f"🧪 *ТЕСТ: Как выглядит отчет о недозвонах*\n\n"
        f"📊 *Контроль недозвонов*\n"
        f"Менеджер: {fake_manager_name}\n"
        f"Пропущено звонков: {fake_missed_count}\n"
        f"- ООО Ромашка (план: 30.11.25)\n"
        f"- ПАО Газпром (план: 29.11.25)\n"
        f"- ИП Сидоров (план: 30.11.25)\n"
    )
    
    print(f"Sending to admins: {settings.admin_ids_list}")
    
    for admin_id in settings.admin_ids_list:
        try:
            await bot.send_message(admin_id, msg_admin, parse_mode="Markdown")
            print(f"Sent to {admin_id}")
        except Exception as e:
            print(f"Failed to send to {admin_id}: {e}")
            
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(send_test_report())


