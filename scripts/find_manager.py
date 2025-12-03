
import asyncio
from sqlalchemy import select
from models import database
from models.database import Manager
from config import settings

async def find_manager():
    await database.init_db(settings.database_url_effective)
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(select(Manager).where(Manager.full_name.ilike("%Тест%")))
        managers = result.scalars().all()
        for m in managers:
            print(f"Manager: {m.full_name}, ID: {m.id}, Sheet ID: {m.google_sheet_id}")

if __name__ == "__main__":
    asyncio.run(find_manager())

