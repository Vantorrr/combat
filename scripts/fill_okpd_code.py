"""
Заполнить столбец "ОКПД (основной)" для всех существующих компаний
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import settings
from services.google_sheets import GoogleSheetsService
from services.datanewton_api import DataNewtonAPI
from loguru import logger

async def fill_okpd_for_sheet(gs: GoogleSheetsService, api: DataNewtonAPI, sheet_id: str, sheet_name: str):
    """Заполнить ОКПД для одного листа"""
    try:
        logger.info(f"Processing {sheet_name}...")
        
        # Получаем все данные из листа
        result = gs.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='A2:E'  # A=Название, B=ИНН, C=ФИО, D=Телефон, E=ОКПД (основной)
        ).execute()
        rows = result.get('values', [])
        
        if not rows:
            logger.info(f"No data in {sheet_name}")
            return
        
        updates = []
        for idx, row in enumerate(rows):
            row_num = idx + 2  # Строки начинаются с 2 (1 - заголовок)
            
            # Проверяем, есть ли ИНН
            if len(row) < 2 or not row[1]:
                continue
            
            inn = row[1].strip()
            
            # Проверяем, заполнен ли уже ОКПД
            okpd_current = row[4] if len(row) > 4 else ""
            if okpd_current:
                logger.info(f"Row {row_num}: OKPD already filled for INN {inn}")
                continue
            
            # Получаем данные из DataNewton
            try:
                logger.info(f"Row {row_num}: Fetching OKPD for INN {inn}...")
                company_data = await api.get_full_company_data(inn)
                
                okpd_code = company_data.get('okpd', '')  # Код ОКПД
                
                if okpd_code:
                    updates.append({
                        'range': f'E{row_num}',
                        'values': [[okpd_code]]
                    })
                    logger.info(f"Row {row_num}: OKPD code = {okpd_code}")
                else:
                    logger.warning(f"Row {row_num}: No OKPD found for INN {inn}")
                
                # Небольшая задержка, чтобы не перегружать API
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Row {row_num}: Error fetching data for INN {inn}: {e}")
                continue
        
        # Применяем все обновления одним батчем
        if updates:
            logger.info(f"Updating {len(updates)} rows in {sheet_name}...")
            gs.service.spreadsheets().values().batchUpdate(
                spreadsheetId=sheet_id,
                body={
                    'valueInputOption': 'RAW',
                    'data': updates
                }
            ).execute()
            logger.info(f"✅ {sheet_name}: Updated {len(updates)} rows")
        else:
            logger.info(f"✅ {sheet_name}: No updates needed")
        
    except Exception as e:
        logger.error(f"❌ Error processing {sheet_name}: {e}")

async def main():
    """Заполнить ОКПД для всех листов"""
    gs = GoogleSheetsService()
    api = DataNewtonAPI()
    
    # Получаем все листы менеджеров из БД
    from models import database
    from models.database import Manager
    from sqlalchemy import select
    
    # Инициализируем БД
    await database.init_db(settings.database_url_effective)
    
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(select(Manager))
        managers = result.scalars().all()
        
        logger.info(f"Found {len(managers)} managers")
        
        for manager in managers:
            if manager.google_sheet_id:
                await fill_okpd_for_sheet(gs, api, manager.google_sheet_id, f"Manager: {manager.full_name}")
        
        # Заполняем сводную таблицу
        logger.info("Filling supervisor sheet...")
        await fill_okpd_for_sheet(gs, api, settings.supervisor_sheet_id, "Supervisor Sheet")
    
    logger.info("🎉 All sheets filled!")

if __name__ == "__main__":
    asyncio.run(main())

