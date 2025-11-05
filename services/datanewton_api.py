import aiohttp
from typing import Optional, Dict, Any
from loguru import logger
from config import settings


class DataNewtonAPI:
    def __init__(self):
        self.base_url = settings.datanewton_base_url
        self.api_key = settings.datanewton_api_key
        self.headers = {
            "Content-Type": "application/json"
        }
    
    async def get_company_by_inn(self, inn: str) -> Optional[Dict[str, Any]]:
        """
        Получить данные компании по ИНН
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/counterparty"
                params = {
                    "key": self.api_key,
                    "inn": inn,
                    "filters": ["ADDRESS_BLOCK", "MANAGER_BLOCK", "OKVED_BLOCK", "CONTACT_BLOCK", 
                               "WORKERS_COUNT_BLOCK", "NEGATIVE_LISTS_BLOCK"]
                }
                
                logger.info(f"DataNewton request: GET {url} with params: {params}")
                
                async with session.get(url, headers=self.headers, params=params) as response:
                    response_text = await response.text()
                    logger.info(f"DataNewton response status: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"DataNewton data received for INN {inn}")
                        result = self._extract_company_data(data)
                        if result:
                            logger.info(f"Company found: {result.get('name')}")
                        return result
                    else:
                        logger.error(f"DataNewton API error: {response.status}, response: {response_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching company data: {e}")
            return None
    
    def _extract_company_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Извлечь нужные данные из ответа API
        """
        try:
            company = raw_data.get("company", {})
            
            # Получаем основной ОКВЭД
            main_okved = None
            okved_name = None
            for okved in company.get("okveds", []):
                if okved.get("main"):
                    main_okved = okved.get("code")
                    okved_name = okved.get("value")
                    break
            
            # Получаем директора
            director = None
            managers = company.get("managers", [])
            if managers:
                director = managers[0].get("fio")
            
            # Получаем количество сотрудников (берем последний известный год)
            workers_count = ""
            workers_block = raw_data.get("workers_count", {})
            if workers_block and isinstance(workers_block, dict):
                # Берем последний год из словаря
                years = sorted(workers_block.keys(), reverse=True)
                if years:
                    workers_count = workers_block.get(years[0], "")
            
            # Получаем регион
            region = company.get("address", {}).get("region", {}).get("name", "")
            
            # Получаем данные по банкротству из негативных списков
            bankruptcy = "нет"
            negative_lists = raw_data.get("negative_lists", {})
            if negative_lists:
                if negative_lists.get("bankruptcy", {}).get("active", False):
                    bankruptcy = "да"
            
            return {
                "inn": raw_data.get("inn"),
                "ogrn": raw_data.get("ogrn"),  # Нужен для governmentContractsStat
                "name": company.get("company_names", {}).get("short_name", ""),
                "full_name": company.get("company_names", {}).get("full_name", ""),
                "okved": main_okved,
                "okved_name": okved_name,
                "revenue": "",  # Требует отдельный запрос
                "capital": company.get("charter_capital", ""),
                "employees": str(workers_count) if workers_count else "",
                "address": company.get("address", {}).get("line_address", ""),
                "director": director,
                "registration_date": company.get("registration_date", ""),
                "status": company.get("status", {}).get("status_rus_short", ""),
                "region": region,
                "gov_contracts": "",  # Требует отдельный запрос
                "arbitration": "",  # Требует отдельный запрос
                "bankruptcy": bankruptcy
            }
        except Exception as e:
            logger.error(f"Error extracting company data: {e}")
            return {}
    
    async def get_finance_data(self, inn: str) -> Dict[str, Any]:
        """Получить финансовые данные"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/finance"
                params = {
                    "key": self.api_key,
                    "inn": inn
                }
                
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Логируем что пришло от API
                        logger.info(f"Finance API response keys: {list(data.keys())}")
                        
                        # Если только available_count - значит данных нет в ответе
                        if "available_count" in data and len(data) == 1:
                            logger.warning(f"Finance API returns only available_count - data not available on current tariff")
                            return {"revenue": "", "revenue_previous": ""}
                        
                        # Извлекаем выручку из отчетности
                        revenue = ""
                        revenue_previous = ""
                        
                        # Получаем финансовые результаты
                        fin_results = data.get("fin_results", {})
                        if fin_results:
                            years = fin_results.get("years", [])
                            if years:
                                # Берем последний и предпоследний год
                                sorted_years = sorted(years, reverse=True)
                                
                                # Ищем показатели выручки
                                indicators = fin_results.get("indicators", [])
                                for indicator in indicators:
                                    if "Выручка" in indicator.get("name", ""):
                                        sum_data = indicator.get("sum", {})
                                        if sum_data and sorted_years:
                                            revenue_val = sum_data.get(str(sorted_years[0]), "")
                                            if revenue_val:
                                                # Конвертируем в тысячи рублей
                                                revenue = str(int(revenue_val / 1000)) if isinstance(revenue_val, (int, float)) else str(revenue_val)
                                            
                                            if len(sorted_years) > 1:
                                                revenue_prev_val = sum_data.get(str(sorted_years[1]), "")
                                                if revenue_prev_val:
                                                    revenue_previous = str(int(revenue_prev_val / 1000)) if isinstance(revenue_prev_val, (int, float)) else str(revenue_prev_val)
                                            break
                        
                        return {
                            "revenue": revenue,
                            "revenue_previous": revenue_previous
                        }
                    else:
                        logger.warning(f"Finance API returned status {response.status}")
                    return {"revenue": "", "revenue_previous": ""}
        except Exception as e:
            logger.error(f"Error fetching finance data: {e}")
            return {"revenue": "", "revenue_previous": ""}
    
    async def get_government_contracts(self, ogrn: str) -> str:
        """Получить данные по госконтрактам (требует ОГРН)"""
        try:
            if not ogrn:
                logger.warning("OGRN required for government contracts")
                return ""
                
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/governmentContractsStat"
                params = {
                    "key": self.api_key,
                    "ogrn": ogrn,
                    "type": "ALL"  # Все типы контрактов
                }
                
                logger.info(f"Government contracts request: GET {url} with params: {params}")
                
                async with session.get(url, headers=self.headers, params=params) as response:
                    response_text = await response.text()
                    logger.info(f"Government contracts response status: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        logger.debug(f"Government contracts response keys: {list(data.keys())}")
                        
                        # Суммируем все контракты по годам (из suppliers_stat и customers_stat)
                        total_sum = 0
                        
                        # Компания как поставщик
                        suppliers_stat = data.get("suppliers_stat", {}).get("stat", [])
                        if suppliers_stat:
                            total_sum += sum(item.get("sum", 0) for item in suppliers_stat)
                        
                        # Компания как заказчик
                        customers_stat = data.get("customers_stat", {}).get("stat", [])
                        if customers_stat:
                            total_sum += sum(item.get("sum", 0) for item in customers_stat)
                        
                        if total_sum:
                            logger.info(f"Total government contracts sum: {total_sum}")
                            return str(int(total_sum))
                        return ""
                    else:
                        logger.warning(f"Government contracts API returned status {response.status}: {response_text}")
                        return ""
        except Exception as e:
            logger.error(f"Error fetching government contracts: {e}")
            return ""
    
    async def get_arbitration_data(self, inn: str) -> str:
        """Получить данные по арбитражным делам (открытые дела)"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/arbitration-cases"
                params = {
                    "key": self.api_key,
                    "inn": inn,
                    "status": "OPEN",  # Открытые дела
                    "limit": 1000  # Максимум
                }
                
                logger.info(f"Arbitration request: GET {url} with params: {params}")
                
                async with session.get(url, headers=self.headers, params=params) as response:
                    response_text = await response.text()
                    logger.info(f"Arbitration response status: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        logger.debug(f"Arbitration response keys: {list(data.keys())}")
                        
                        # Получаем количество дел (используем правильный ключ)
                        total_cases = data.get("total_cases", 0)
                        if total_cases:
                            logger.info(f"Found {total_cases} open arbitration cases for INN {inn}")
                            return str(total_cases)
                        return "0"
                    else:
                        logger.warning(f"Arbitration API returned status {response.status}: {response_text}")
                        return ""
        except Exception as e:
            logger.error(f"Error fetching arbitration data: {e}")
            return ""
    
    async def get_full_company_data(self, inn: str) -> Optional[Dict[str, Any]]:
        """Получить полные данные компании включая финансы и контракты"""
        # Получаем основную информацию
        company_data = await self.get_company_by_inn(inn)
        if not company_data:
            return None
        
        # Параллельно получаем дополнительные данные (может быть недоступно на бесплатном тарифе)
        try:
            finance_data = await self.get_finance_data(inn)
            company_data.update({
                "revenue": finance_data.get("revenue", ""),
                "revenue_previous": finance_data.get("revenue_previous", "")
            })
        except Exception as e:
            logger.debug(f"Finance data not available: {e}")
            company_data.update({
                "revenue": "",
                "revenue_previous": ""
            })
        
        try:
            ogrn = company_data.get("ogrn", "")
            gov_contracts = await self.get_government_contracts(ogrn)
            company_data["gov_contracts"] = gov_contracts
        except Exception as e:
            logger.debug(f"Government contracts not available: {e}")
            company_data["gov_contracts"] = ""
        
        try:
            arbitration = await self.get_arbitration_data(inn)
            company_data["arbitration"] = arbitration
        except Exception as e:
            logger.debug(f"Arbitration data not available: {e}")
            company_data["arbitration"] = ""
        
        return company_data
    
    async def validate_inn(self, inn: str) -> bool:
        """
        Проверить валидность ИНН через API
        """
        # Базовая проверка длины
        if len(inn) not in [10, 12]:
            return False
            
        # Проверка через API
        company_data = await self.get_company_by_inn(inn)
        return company_data is not None


datanewton_api = DataNewtonAPI()
