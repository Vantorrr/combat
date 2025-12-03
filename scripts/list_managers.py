import asyncio
from sqlalchemy import select
from models import database
from models.database import Manager
from config import settings

async def list_managers():
    await database.init_db(settings.database_url_effective)
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(select(Manager))
        managers = result.scalars().all()
        for m in managers:
            print(f"ID: {m.id}, Name: {m.full_name}, Active: {m.is_active}, Sheet: {m.google_sheet_id}")

if __name__ == "__main__":
    asyncio.run(list_managers())


