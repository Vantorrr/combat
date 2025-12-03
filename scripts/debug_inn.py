import asyncio
import sys
import os

# Add project root to python path
sys.path.append(os.getcwd())

from services.datanewton_api import datanewton_api
from config import settings

async def check():
    inn = "5003116450"
    print(f"🔍 Checking INN: {inn}")
    print(f"🔑 API Key in settings: {settings.datanewton_api_key}")
    
    # Check Finance
    print("\n--- Finance Data ---")
    try:
        fin = await datanewton_api.get_finance_data(inn)
        print(f"Result: {fin}")
    except Exception as e:
        print(f"Error: {e}")

    # Check Full Data (wrapper)
    print("\n--- Full Company Data (Wrapper) ---")
    try:
        full = await datanewton_api.get_full_company_data(inn)
        print(f"Revenue: {full.get('revenue')}")
        print(f"Gov Contracts: {full.get('gov_contracts')}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())


