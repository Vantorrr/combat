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
            
            # Получаем email из контактов
            email = ""
            contacts = company.get("contacts")
            if contacts and isinstance(contacts, list):
                for contact in contacts:
                    if contact.get("type") == "email":
                        email = contact.get("value", "")
                        break
            
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
                "email": email,
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
                        
                        # Получаем финансовые результаты (строка 2110 - выручка)
                        fin_results = data.get("fin_results", {})
                        if fin_results:
                            # Ищем показатель "Выручка" (код строки 2110)
                            indicators = fin_results.get("indicators", [])
                            for indicator in indicators:
                                indicator_name = indicator.get("name", "")
                                # Ищем конкретно "Выручка" (строка 2110)
                                if indicator_name == "Выручка" or "выручка" in indicator_name.lower():
                                    sum_data = indicator.get("sum", {})
                                    if sum_data:
                                        # Берем конкретно 2024 и 2023
                                        revenue_2024 = sum_data.get("2024", "")
                                        revenue_2023 = sum_data.get("2023", "")
                                        
                                        if revenue_2024:
                                            # Конвертируем в тысячи рублей
                                            revenue = str(int(revenue_2024 / 1000)) if isinstance(revenue_2024, (int, float)) else str(revenue_2024)
                                        
                                        if revenue_2023:
                                            revenue_previous = str(int(revenue_2023 / 1000)) if isinstance(revenue_2023, (int, float)) else str(revenue_2023)
                                        
                                        logger.info(f"Revenue 2024: {revenue}, Revenue 2023: {revenue_previous}")
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

    async def get_government_contracts_stat(self, inn: Optional[str] = None, ogrn: Optional[str] = None) -> Dict[str, Any]:
        """Новый способ: статистика по госконтрактам + топ ОКПД2.
        Возвращает dict: { total_sum, top_okpd2_code, top_okpd2_name }
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/governmentContractsStat"
                params = {"key": self.api_key}
                if ogrn:
                    params["ogrn"] = ogrn
                elif inn:
                    params["inn"] = inn
                
                logger.info(f"GovContractsStat request: GET {url} with params: {params}")
                async with session.get(url, headers=self.headers, params=params) as response:
                    raw_text = await response.text()
                    if response.status != 200:
                        logger.warning(f"governmentContractsStat HTTP {response.status}: {raw_text}")
                        return {"total_sum": "", "top_okpd2_code": "", "top_okpd2_name": ""}
                    data = await response.json()

                    total_sum = 0
                    suppliers_stat = data.get("suppliers_stat", {}).get("stat", [])
                    if suppliers_stat:
                        total_sum += sum(item.get("sum", 0) for item in suppliers_stat)
                    customers_stat = data.get("customers_stat", {}).get("stat", [])
                    if customers_stat:
                        total_sum += sum(item.get("sum", 0) for item in customers_stat)
                    if not total_sum:
                        generic = data.get("stat", []) or data.get("data", []) or []
                        if isinstance(generic, list):
                            total_sum = sum(item.get("sum", 0) for item in generic if isinstance(item, dict))

                    # Находим топ ОКПД2 по сумме
                    candidates = []
                    if suppliers_stat:
                        candidates.extend(suppliers_stat)
                    if customers_stat:
                        candidates.extend(customers_stat)
                    if not candidates:
                        candidates = data.get("stat", []) or data.get("data", []) or []

                    best = None
                    for it in candidates:
                        if not isinstance(it, dict):
                            continue
                        code = it.get("okpd2_code") or it.get("okpd2")
                        if not code:
                            continue
                        s = it.get("sum", 0) or 0
                        if best is None or s > best.get("sum", 0):
                            best = {"code": code, "name": it.get("okpd2_name") or it.get("okpd2_title") or "", "sum": s}

                    return {
                        "total_sum": str(int(total_sum)) if total_sum else "",
                        "top_okpd2_code": (best or {}).get("code", ""),
                        "top_okpd2_name": (best or {}).get("name", ""),
                    }
        except Exception as e:
            logger.error(f"Error fetching governmentContractsStat: {e}")
            return {"total_sum": "", "top_okpd2_code": "", "top_okpd2_name": ""}
    
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

    async def get_arbitration_stats(self, inn: str) -> Dict[str, Any]:
        """Вернуть метрики по арбитражам: open_count, open_sum, last_doc_date (по открытым)."""
        try:
            async with aiohttp.ClientSession() as session:
                # Открытые дела
                url = f"{self.base_url}/arbitration-cases"
                params_open = {"key": self.api_key, "inn": inn, "status": "OPEN", "limit": 1000}
                async with session.get(url, headers=self.headers, params=params_open) as resp_open:
                    data_open = await resp_open.json() if resp_open.status == 200 else {}
                open_list = data_open.get("data", []) if isinstance(data_open, dict) else []
                open_count = data_open.get("total_cases", len(open_list)) or 0
                open_sum = 0
                last_doc_ts = 0
                for case in open_list:
                    try:
                        s = case.get("sum")
                        if isinstance(s, (int, float)):
                            open_sum += s
                        ts = case.get("last_document_date")
                        if isinstance(ts, (int, float)):
                            last_doc_ts = max(last_doc_ts, int(ts))
                    except Exception:
                        continue

                # Преобразуем дату
                last_doc_date = ""
                if last_doc_ts:
                    from datetime import datetime
                    try:
                        # last_document_date приходит в мс
                        dt = datetime.fromtimestamp(last_doc_ts / 1000)
                        last_doc_date = dt.strftime("%d.%m.%y")
                    except Exception:
                        last_doc_date = ""

                return {
                    "arbitration_open_count": str(open_count),
                    "arbitration_open_sum": str(int(open_sum)) if open_sum else "0",
                    "arbitration_last_doc_date": last_doc_date,
                }
        except Exception as e:
            logger.error(f"Error fetching arbitration stats: {e}")
            return {"arbitration_open_count": "0", "arbitration_open_sum": "0", "arbitration_last_doc_date": ""}
    
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
            stat = await self.get_government_contracts_stat(inn=inn, ogrn=ogrn)
            company_data["gov_contracts"] = stat.get("total_sum", "")
            company_data["okpd"] = stat.get("top_okpd2_code", "")
            company_data["okpd_name"] = stat.get("top_okpd2_name", "")
        except Exception as e:
            logger.debug(f"Government contracts not available: {e}")
            company_data["gov_contracts"] = ""
            company_data["okpd"] = ""
            company_data["okpd_name"] = ""
        
        try:
            arb_stats = await self.get_arbitration_stats(inn)
            company_data.update(arb_stats)
            # Для обратной совместимости поле arbitration = количество активных
            company_data["arbitration"] = arb_stats.get("arbitration_open_count", "0")
        except Exception as e:
            logger.debug(f"Arbitration data not available: {e}")
            company_data.update({
                "arbitration": "0",
                "arbitration_open_count": "0",
                "arbitration_open_sum": "0",
                "arbitration_last_doc_date": "",
            })
        
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
