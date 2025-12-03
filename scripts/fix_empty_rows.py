
import asyncio
import aiohttp
import random
from loguru import logger
from services.google_sheets import get_google_sheets_service
from config import settings

# Config
SHEET_ID = "1k0ZBeRgcG4JGuhefOfALXhE0Fkocc8dQg1HbYzSshY0"  # CRM - Тест
API_KEY = settings.datanewton_api_key
BASE_URL = settings.datanewton_base_url

async def fetch_raw_data(inn, session):
    """
    Direct API call that RAISES exceptions on errors, allowing retry.
    """
    # 1. Company Info (for OGRN and Name)
    url_company = f"{BASE_URL}/counterparty"
    params_company = {
        "key": API_KEY,
        "inn": inn,
        "filters": ["ADDRESS_BLOCK", "MANAGER_BLOCK", "OKVED_BLOCK"] # Min necessary
    }
    
    async with session.get(url_company, params=params_company) as resp:
        if resp.status == 429:
            raise ValueError("Rate Limit 429")
        if resp.status != 200:
            text = await resp.text()
            logger.warning(f"Company API error {resp.status}: {text}")
            return None # Skip if hard error
        
        company_json = await resp.json()
        
    ogrn = company_json.get('ogrn')
    
    # 2. Finance
    url_finance = f"{BASE_URL}/finance"
    params_finance = {"key": API_KEY, "inn": inn}
    
    revenue = ""
    revenue_prev = ""
    capital = ""
    assets = ""
    debit = ""
    credit = ""
    net_profit = ""
    
    async with session.get(url_finance, params=params_finance) as resp:
        if resp.status == 429:
            raise ValueError("Rate Limit 429")
        if resp.status == 200:
            fin_data = await resp.json()
            # Extract (simplified logic similar to main code)
            if "fin_results" in fin_data:
                for ind in fin_data["fin_results"].get("indicators", []):
                    code = str(ind.get("code", ""))
                    if code == "2110": # Revenue
                        revenue = str(ind.get("sum", {}).get("2024") or ind.get("sum", {}).get("2023") or "")
                        revenue_prev = str(ind.get("sum", {}).get("2023") or "")
                    if code == "2400": # Net Profit
                        net_profit = str(ind.get("sum", {}).get("2024") or "")
            
            if "balances" in fin_data:
                # Simplified extraction for speed - recursively finding codes
                def find_code(node, target_code):
                    if isinstance(node, dict):
                        if str(node.get("code", "")) == target_code:
                            return str(node.get("sum", {}).get("2024") or "")
                        for k, v in node.items():
                            res = find_code(v, target_code)
                            if res: return res
                    elif isinstance(node, list):
                        for item in node:
                            res = find_code(item, target_code)
                            if res: return res
                    return ""

                capital = find_code(fin_data["balances"], "1300")
                assets = find_code(fin_data["balances"], "1150")
                debit = find_code(fin_data["balances"], "1230")
                credit = find_code(fin_data["balances"], "1520")

    # 3. Gov Contracts
    gov_contracts = ""
    if ogrn:
        url_gov = f"{BASE_URL}/governmentContractsStat"
        params_gov = {"key": API_KEY, "ogrn": ogrn, "type": "ALL"}
        async with session.get(url_gov, params=params_gov) as resp:
            if resp.status == 429:
                raise ValueError("Rate Limit 429")
            if resp.status == 200:
                gov_data = await resp.json()
                total = 0
                # Sum suppliers
                for item in gov_data.get("suppliers_stat", {}).get("stat", []):
                    total += item.get("sum", 0)
                # Sum customers
                for item in gov_data.get("customers_stat", {}).get("stat", []):
                    total += item.get("sum", 0)
                
                if total > 0:
                    gov_contracts = str(int(total))

    return {
        "revenue": revenue,
        "revenue_previous": revenue_prev,
        "capital": capital,
        "assets": assets,
        "debit": debit,
        "credit": credit,
        "net_profit": net_profit,
        "gov_contracts": gov_contracts
    }

async def fix_empty_rows():
    gs = get_google_sheets_service()
    
    print(f"📖 Reading sheet {SHEET_ID}...")
    # Read range A:H to find rows with INN but empty Revenue
    # INN is B (idx 1), Revenue is H (idx 7)
    # Wait, Revenue prev is G (idx 6), Revenue is H (idx 7).
    
    result = gs.service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range='A:N' # Read up to Gov Contracts (N)
    ).execute()
    
    values = result.get('values', [])
    
    print(f"🔍 Scanning {len(values)} rows for missing data...")
    
    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(values):
            if i == 0: continue # Skip header
            
            # Check INN
            inn = row[1].strip() if len(row) > 1 else ""
            if not inn: continue
            
            # Check if Revenue (H, index 7) is empty
            rev = row[7].strip() if len(row) > 7 else ""
            
            # Also check Gov Contracts (N, index 13)
            gov = row[13].strip() if len(row) > 13 else ""
            
            if not rev and not gov:
                print(f"🛠 Fixing row {i+1} (INN: {inn})...")
                
                # Retry loop
                data = None
                retries = 5
                for attempt in range(retries):
                    try:
                        data = await fetch_raw_data(inn, session)
                        break
                    except ValueError: # 429
                        wait = 2 ** attempt + random.uniform(0, 1)
                        print(f"   ⏳ Rate limit (429). Waiting {wait:.1f}s...")
                        await asyncio.sleep(wait)
                    except Exception as e:
                        print(f"   ❌ Error: {e}")
                        break
                
                if data:
                    print(f"   ✅ Got Data: Rev={data['revenue']}, Gov={data['gov_contracts']}")
                    
                    # Update Row
                    # Columns: G=Prev, H=Rev, I=Net, J=Cap, K=Assets, L=Deb, M=Cred, N=Gov
                    updates = [
                        data['revenue_previous'],
                        data['revenue'],
                        data['net_profit'],
                        data['capital'],
                        data['assets'],
                        data['debit'],
                        data['credit'],
                        data['gov_contracts']
                    ]
                    
                    body = {
                        'values': [updates]
                    }
                    
                    gs.service.spreadsheets().values().update(
                        spreadsheetId=SHEET_ID,
                        range=f"G{i+1}:N{i+1}",
                        valueInputOption="USER_ENTERED",
                        body=body
                    ).execute()
                    
                    # Slow down
                    await asyncio.sleep(1.5)
                else:
                    print(f"   ⚠️ Could not fetch data for {inn}")

    print("🏁 Done fixing rows.")

if __name__ == "__main__":
    asyncio.run(fix_empty_rows())


