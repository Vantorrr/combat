"""
Скрипт для автоматического обновления динамических данных в Google Sheets
(арбитраж, банкротство, финансы)

Запускать по расписанию (через cron) раз в неделю или по требованию.

Использование:
    python scripts/auto_update_data.py --sheet-id SHEET_ID --columns Q,R

Колонки:
    Q - Арбитражные дела
    R - Банкротство  
    G-H - Финансовые данные (если доступно)
"""
import asyncio
import argparse
from typing import List
from loguru import logger

from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api


async def update_dynamic_data(sheet_id: str, columns: List[str]):
    """
    Обновить динамические данные в таблице
    
    columns: список колонок для обновления (например, ['Q', 'R'])
    """
    sheets = get_google_sheets_service()
    
    # Получаем все данные из таблицы
    result = sheets.service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range='A:W'
    ).execute()
    
    values = result.get('values', [])
    
    if len(values) < 2:
        logger.info("Таблица пуста или содержит только заголовки")
        return
    
    # Обрабатываем каждую строку (пропускаем заголовок)
    updated_count = 0
    for i, row in enumerate(values[1:], start=2):
        if len(row) < 2:
            continue
            
        inn = row[1]  # ИНН в колонке B
        
        if not inn:
            continue
        
        updates = {}
        
        # Определяем какие колонки нужно обновить
        if 'Q' in columns:
            # Обновляем арбитражные дела
            try:
                arbitration_count = await datanewton_api.get_arbitration_data(inn)
                if arbitration_count:
                    updates['Q'] = arbitration_count
                    logger.debug(f"INN {inn}: arbitration = {arbitration_count}")
            except Exception as e:
                logger.warning(f"Failed to get arbitration data for INN {inn}: {e}")
        
        if 'R' in columns:
            # Обновляем статус банкротства
            try:
                company_data = await datanewton_api.get_company_by_inn(inn)
                if company_data and company_data.get('bankruptcy'):
                    updates['R'] = company_data['bankruptcy']
                    logger.debug(f"INN {inn}: bankruptcy = {company_data['bankruptcy']}")
            except Exception as e:
                logger.warning(f"Failed to get bankruptcy data for INN {inn}: {e}")
        
        if 'P' in columns:
            # Обновляем госконтракты (нужен ОГРН)
            try:
                company_data = await datanewton_api.get_company_by_inn(inn)
                if company_data and company_data.get('ogrn'):
                    gov_contracts = await datanewton_api.get_government_contracts(company_data['ogrn'])
                    if gov_contracts:
                        updates['P'] = gov_contracts
                        logger.debug(f"INN {inn}: gov_contracts = {gov_contracts}")
            except Exception as e:
                logger.warning(f"Failed to get government contracts for INN {inn}: {e}")
        
        if updates:
            await sheets.update_specific_columns(sheet_id, inn, updates)
            updated_count += 1
            logger.info(f"Updated row {i} for INN {inn}")
        
        # Небольшая задержка чтобы не перегрузить API
        await asyncio.sleep(0.5)
    
    logger.info(f"Обновлено {updated_count} строк из {len(values) - 1}")


def main():
    parser = argparse.ArgumentParser(description='Auto-update dynamic data in Google Sheets')
    parser.add_argument('--sheet-id', required=True, help='Google Sheet ID')
    parser.add_argument('--columns', nargs='+', default=['Q', 'R'], 
                        help='Columns to update (e.g., Q R)')
    
    args = parser.parse_args()
    
    logger.info(f"Starting auto-update for sheet {args.sheet_id}")
    logger.info(f"Columns to update: {args.columns}")
    
    asyncio.run(update_dynamic_data(args.sheet_id, args.columns))
    
    logger.info("Auto-update completed")


if __name__ == "__main__":
    main()


