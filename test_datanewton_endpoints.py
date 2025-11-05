"""
Тестирование всех эндпоинтов DataNewton API
"""
import asyncio
from services.datanewton_api import datanewton_api
from loguru import logger

# Тестовые ИНН (публичные компании)
TEST_INN = "7707083893"  # ПАО "СБЕРБАНК РОССИИ"
TEST_INN_2 = "7728212268"  # ООО "ЯНДЕКС"
TEST_INN_3 = "1027700132195"  # ПАО "МОСЭНЕРГО" (из документации DataNewton)


async def test_all_endpoints():
    """Тестируем все эндпоинты"""
    
    logger.info("=" * 80)
    logger.info("TESTING DATANEWTON API ENDPOINTS")
    logger.info("=" * 80)
    
    # 1. Базовая информация о компании
    logger.info("\n1. Testing /v1/counterparty (company data)")
    logger.info("-" * 80)
    company_data = await datanewton_api.get_company_by_inn(TEST_INN)
    if company_data:
        logger.success(f"✓ Company found: {company_data.get('name')}")
        logger.info(f"  INN: {company_data.get('inn')}")
        logger.info(f"  OKVED: {company_data.get('okved')}")
        logger.info(f"  Director: {company_data.get('director')}")
        logger.info(f"  Employees: {company_data.get('employees')}")
        logger.info(f"  Bankruptcy: {company_data.get('bankruptcy')}")
    else:
        logger.error("✗ Failed to get company data")
    
    # 2. Финансовые данные
    logger.info("\n2. Testing /v1/finance (financial data)")
    logger.info("-" * 80)
    finance_data = await datanewton_api.get_finance_data(TEST_INN_3)
    logger.info(f"Finance response: {finance_data}")
    if finance_data.get('revenue'):
        logger.success(f"✓ Revenue: {finance_data.get('revenue')}")
        logger.info(f"  Previous year: {finance_data.get('revenue_previous')}")
    else:
        logger.warning("⚠ No finance data available (may require paid tariff)")
    
    # 3. Госконтракты (сначала получаем ОГРН)
    logger.info("\n3. Testing /v1/governmentContractsStat (government contracts)")
    logger.info("-" * 80)
    company_for_contracts = await datanewton_api.get_company_by_inn(TEST_INN_3)
    if company_for_contracts and company_for_contracts.get('ogrn'):
        ogrn = company_for_contracts['ogrn']
        logger.info(f"  OGRN: {ogrn}")
        gov_contracts = await datanewton_api.get_government_contracts(ogrn)
        if gov_contracts:
            logger.success(f"✓ Government contracts total: {gov_contracts}")
        else:
            logger.warning("⚠ No government contracts data or endpoint not available")
    else:
        logger.warning("⚠ Could not get OGRN for government contracts")
    
    # 4. Арбитражные дела
    logger.info("\n4. Testing /v1/arbitration-cases (arbitration cases)")
    logger.info("-" * 80)
    arbitration = await datanewton_api.get_arbitration_data(TEST_INN_2)
    if arbitration:
        logger.success(f"✓ Open arbitration cases: {arbitration}")
    else:
        logger.warning("⚠ No arbitration data or endpoint not available")
    
    # 5. Полные данные
    logger.info("\n5. Testing get_full_company_data (all data combined)")
    logger.info("-" * 80)
    full_data = await datanewton_api.get_full_company_data(TEST_INN_2)
    if full_data:
        logger.success("✓ Full company data retrieved")
        logger.info(f"  Name: {full_data.get('name')}")
        logger.info(f"  Revenue: {full_data.get('revenue')}")
        logger.info(f"  Gov contracts: {full_data.get('gov_contracts')}")
        logger.info(f"  Arbitration: {full_data.get('arbitration')}")
    else:
        logger.error("✗ Failed to get full company data")
    
    logger.info("\n" + "=" * 80)
    logger.info("TESTING COMPLETED")
    logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_all_endpoints())

