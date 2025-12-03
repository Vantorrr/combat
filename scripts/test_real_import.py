
import asyncio
from services.datanewton_api import datanewton_api

async def test_real_api_calls():
    # ИНН из файла
    inns = ["8911017010", "8602170734", "602711673797"]
    
    print("--- ЗАПУСК ТЕСТА API НА РЕАЛЬНЫХ ИНН ИЗ CSV ---")
    
    for inn in inns:
        print(f"\n🔍 Проверяем ИНН: {inn}")
        
        # 1. Полные данные (включая gov_contracts внутри)
        try:
            data = await datanewton_api.get_full_company_data(inn)
            if data:
                print(f"✅ DataNewton Full Data: OK")
                print(f"   - Название: {data.get('name')}")
                print(f"   - Госконтракты (gov_contracts): '{data.get('gov_contracts')}'")
                print(f"   - Выручка (revenue): '{data.get('revenue')}'")
                print(f"   - ОКПД (okpd): '{data.get('okpd')}'")
                print(f"   - ОКПД Имя (okpd_name): '{data.get('okpd_name')}'")
                
                if not data.get('gov_contracts'):
                     # Если пусто, попробуем напрямую дернуть статистику, чтобы увидеть ошибку
                     ogrn = data.get('ogrn')
                     if ogrn:
                         print(f"   ⚠️ Пробуем прямой запрос governmentContractsStat для ОГРН {ogrn}...")
                         stat = await datanewton_api.get_government_contracts_stat(inn=inn, ogrn=ogrn)
                         print(f"   -> Результат прямого запроса: {stat}")
                     else:
                         print("   ⚠️ Нет ОГРН, прямой запрос контрактов невозможен.")
            else:
                print("❌ get_full_company_data вернул None (ошибка API или не найдено)")
        except Exception as e:
            print(f"❌ Исключение: {e}")
            
    print("\n--- КОНЕЦ ТЕСТА ---")

if __name__ == "__main__":
    asyncio.run(test_real_api_calls())


