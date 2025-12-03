import asyncio
import logging
from sqlalchemy import select
from models.database import AsyncSessionLocal, Manager, init_db
from services.google_sheets import get_google_sheets_service
from config import settings

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_sheet_formatting(sheet_id: str, sheet_name: str):
    """
    Исправляет форматирование в указанной таблице:
    1. Устанавливает локаль ru_RU (чтобы пробел был разделителем тысяч).
    2. Применяет формат '#,##0" ₽"' к финансовым колонкам.
    3. Перезаписывает данные в финансовых колонках, конвертируя текст в числа.
    """
    if not sheet_id:
        return

    service = get_google_sheets_service()
    try:
        # 1. Устанавливаем локаль ru_RU
        service.set_spreadsheet_locale(sheet_id, 'ru_RU')
        logger.info(f"[{sheet_name}] Locale set to ru_RU")

        # Получаем GID первого листа
        gid = service._get_first_sheet_gid(sheet_id)

        # Колонки G(6) - N(13) это финансовые данные + госконтракты
        financial_columns = list(range(6, 14)) # 6,7,8,9,10,11,12,13

        # 2. Применяем формат валюты
        service._apply_currency_format(sheet_id, gid, financial_columns)
        logger.info(f"[{sheet_name}] Currency format applied to cols G-N")

        # 3. Нормализация данных (текст -> число)
        # Читаем диапазон G2:N1000 (с запасом)
        read_range = 'G2:N1000'
        result = service.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=read_range,
            valueRenderOption='UNFORMATTED_VALUE' # Получаем сырые значения
        ).execute()
        
        rows = result.get('values', [])
        if not rows:
            logger.info(f"[{sheet_name}] No data to normalize.")
            return

        cleaned_rows = []
        for row in rows:
            cleaned_row = []
            for cell in row:
                # Пытаемся превратить в число
                if isinstance(cell, str):
                    # Удаляем пробелы, символы валюты, заменяем запятую на точку
                    clean_val = cell.replace(' ', '').replace('₽', '').replace(',', '.').replace('\xa0', '')
                    try:
                        val = float(clean_val)
                        cleaned_row.append(val)
                    except ValueError:
                        cleaned_row.append(cell) # Оставляем как есть, если не число
                else:
                    cleaned_row.append(cell)
            
            # Дополняем строку пустыми значениями до ширины диапазона (8 колонок: G-N)
            while len(cleaned_row) < 8:
                cleaned_row.append("")
            cleaned_rows.append(cleaned_row)

        # Записываем обратно как USER_ENTERED (Google Sheets сам применит формат чисел к числам)
        if cleaned_rows:
            body = {
                'values': cleaned_rows
            }
            service.service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=read_range,
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            logger.info(f"[{sheet_name}] Data normalized and rewritten for {len(cleaned_rows)} rows")

    except Exception as e:
        logger.error(f"[{sheet_name}] Error fixing sheet {sheet_id}: {e}")

async def main():
    # Инициализация БД
    await init_db(settings.database_url_effective)
    
    # Получаем sessionmaker из модуля models.database
    from models.database import AsyncSessionLocal
    
    async with AsyncSessionLocal() as session:
        # 1. Таблицы менеджеров
        result = await session.execute(select(Manager))
        managers = result.scalars().all()
        
        logger.info(f"Found {len(managers)} managers")
        
        for manager in managers:
            if manager.google_sheet_id:
                logger.info(f"Processing manager: {manager.full_name} ({manager.google_sheet_id})")
                await fix_sheet_formatting(manager.google_sheet_id, f"Manager: {manager.full_name}")
            else:
                logger.warning(f"Manager {manager.full_name} has no sheet_id")

        # 2. Таблица супервайзера
        if settings.supervisor_sheet_id:
            logger.info(f"Processing Supervisor sheet ({settings.supervisor_sheet_id})")
            await fix_sheet_formatting(settings.supervisor_sheet_id, "Supervisor")
        else:
            logger.warning("Supervisor sheet ID not configured")

if __name__ == "__main__":
    asyncio.run(main())

