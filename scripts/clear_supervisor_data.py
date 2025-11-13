"""
Очистить все данные из сводной таблицы, оставить только заголовок
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import settings
from services.google_sheets import GoogleSheetsService
from loguru import logger

def clear_supervisor_data():
    """Очистить данные из сводной таблицы"""
    try:
        gs = GoogleSheetsService()
        sheet_id = settings.supervisor_sheet_id
        
        logger.info("Clearing supervisor sheet data...")
        
        # Получаем текущие данные
        result = gs.service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range='A:Q'
        ).execute()
        values = result.get('values', [])
        
        if len(values) <= 1:
            logger.info("No data to clear (only headers)")
            return
        
        # Удаляем все строки, кроме заголовка
        rows_to_delete = len(values) - 1
        logger.info(f"Deleting {rows_to_delete} rows...")
        
        gs.service.spreadsheets().values().clear(
            spreadsheetId=sheet_id,
            range='A2:Q'
        ).execute()
        
        logger.info("✅ Supervisor sheet cleared!")
        
    except Exception as e:
        logger.error(f"❌ Error clearing supervisor sheet: {e}")

if __name__ == "__main__":
    clear_supervisor_data()

