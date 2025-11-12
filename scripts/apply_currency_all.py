from typing import List
from loguru import logger
from config import settings
from models.database import init_db, get_session, Manager
from services.google_sheets import get_google_sheets_service


def apply_currency(spreadsheet_id: str, columns: List[int]):
    gs = get_google_sheets_service()
    gid = gs._get_first_sheet_gid(spreadsheet_id)
    # переиспользуем внутренний метод
    gs._apply_currency_format(spreadsheet_id, gid, columns)
    logger.info(f"Applied currency format to {spreadsheet_id}")


async def main():
    await init_db(settings.database_url_effective)
    # менеджерские листы
    async for session in get_session():
        result = await session.execute(Manager.__table__.select())
        rows = result.fetchall()
        for row in rows:
            sid = getattr(row, "google_sheet_id", None)
            if sid:
                apply_currency(sid, [6, 7, 8, 9, 10, 11, 12, 14])
        await session.close()
    # сводная
    if settings.supervisor_sheet_id:
        apply_currency(settings.supervisor_sheet_id, [6, 7, 8, 9, 10, 11, 12, 14])


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())


