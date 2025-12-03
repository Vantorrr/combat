
import csv
import io
import asyncio
import random
from datetime import datetime
from services.google_sheets import get_google_sheets_service
from services.datanewton_api import datanewton_api
from loguru import logger

# Target Sheet Config
MANAGER_NAME = "Тест"
SHEET_ID = "1k0ZBeRgcG4JGuhefOfALXhE0Fkocc8dQg1HbYzSshY0"
CSV_FILE = "Книга1 3.csv"

def _format_imported_comments(row):
    """Форматировать комментарии из CSV в единую историю"""
    comments = []
    today = datetime.now().strftime('%d.%m.%y')
    
    # Комментарий 1 (col 6 / G)
    if len(row) > 6 and row[6].strip():
        comments.append(f"{today} - {row[6].strip()}")
    
    return "\n---\n".join(comments) if comments else ""

async def get_data_with_retry(inn, max_retries=5):
    """Fetch data from DataNewton with exponential backoff for 429/timeouts"""
    for attempt in range(max_retries):
        try:
            # Basic delay to be nice
            await asyncio.sleep(1.0) 
            
            data = await datanewton_api.get_full_company_data(inn)
            
            # If we got data, return it
            if data:
                # Check if we got gov contracts (if we expect them)
                # Note: some companies really don't have them, so empty is valid.
                # But if API failed, get_full_company_data might return partial data.
                # For now, assume if we got a dict, it's good.
                return data
            
            # If data is None, it might be a 404 or valid "not found". 
            # But datanewton_api returns None on error too.
            # Let's assume if it returns None, we can't do much.
            return {}
            
        except Exception as e:
            logger.warning(f"Attempt {attempt+1}/{max_retries} failed for INN {inn}: {e}")
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logger.info(f"Waiting {wait_time:.2f}s before retry...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Max retries reached for INN {inn}")
                return {}
    return {}

async def run_import():
    print(f"🚀 Starting robust import for {MANAGER_NAME} into sheet {SHEET_ID}")
    
    google_sheets_service = get_google_sheets_service()
    
    # Read CSV
    with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
        # Auto-detect delimiter
        content = f.read()
        delimiter = ';' if ';' in content.split('\n')[0] else ','
        f.seek(0)
        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)
    
    print(f"📄 Found {len(rows)} rows (including header)")
    
    # Skip header if present
    data_rows = rows[1:] if "ИНН" in rows[0] else rows
    
    success_count = 0
    
    for i, row in enumerate(data_rows, 1):
        try:
            if len(row) < 2:
                print(f"⚠️ Skipping empty row {i}")
                continue
                
            company_name = row[0].strip()
            inn = row[1].strip()
            
            print(f"🔄 [{i}/{len(data_rows)}] Processing {company_name} (INN: {inn})...")
            
            # 1. Fetch Data with Retry
            api_data = {}
            if inn:
                api_data = await get_data_with_retry(inn)
                
            if api_data.get('gov_contracts'):
                print(f"   💰 Gov Contracts: {api_data.get('gov_contracts')}")
            else:
                print(f"   ⚪ Gov Contracts: None")

            # 2. Prepare Data (using smart logic from bot)
            call_data = {
                'company_name': api_data.get('name') or company_name,
                'inn': inn,
                'contact_name': row[2].strip() if len(row) > 2 else '',
                'phone': row[3].strip() if len(row) > 3 else '',
                
                # Date Logic
                'first_call_date': (
                    row[16].strip() if len(row) > 16 and row[16].strip() else (
                        row[4].strip() if len(row) > 4 and row[4].strip() else datetime.now().strftime('%d.%m.%y')
                    )
                ),
                'next_call_date': row[5].strip() if len(row) > 5 else '', # Col F in CSV
                'comment': _format_imported_comments(row),
                
                # Finance Logic
                'revenue': str(api_data.get('revenue') or (row[9].strip() if len(row) > 9 else '')),
                'revenue_previous': str(api_data.get('revenue_previous') or (row[10].strip() if len(row) > 10 else '')),
                'capital': str(api_data.get('capital') or (row[11].strip() if len(row) > 11 else '')),
                'assets': str(api_data.get('assets') or (row[12].strip() if len(row) > 12 else '')),
                'debit': str(api_data.get('debit') or (row[13].strip() if len(row) > 13 else '')),
                'credit': str(api_data.get('credit') or (row[14].strip() if len(row) > 14 else '')),
                'net_profit': str(api_data.get('net_profit') or ''),
                
                'gov_contracts': str(api_data.get('gov_contracts') or (row[18].strip() if len(row) > 18 else '')),
                'okved_main': str(api_data.get('okved') or (row[17].strip() if len(row) > 17 else '')),
                'okpd_name': str(api_data.get('okpd_name') or ''),
            }
            
            # 3. Write to Manager Sheet
            await google_sheets_service.add_new_call(SHEET_ID, call_data)
            
            # 4. Write to Supervisor Sheet
            # await google_sheets_service.update_supervisor_sheet(MANAGER_NAME, call_data)
            # (Skipping supervisor update to save time/tokens for now, assuming manager sheet is priority)
            
            # 5. Cool down to avoid Google Quota issues
            # await asyncio.sleep(1.5) # Слишком долго
            await asyncio.sleep(0.5) # Ускорим немного
            
            success_count += 1
            
        except Exception as e:
            print(f"❌ Error on row {i}: {e}")
            # Continue to next row
            
    print(f"✅ Import finished! Processed {success_count} rows.")

if __name__ == "__main__":
    asyncio.run(run_import())

