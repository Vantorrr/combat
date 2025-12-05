import asyncio
import sys
from datetime import datetime
from loguru import logger

# Add project root to path
import os
sys.path.append(os.getcwd())

from services.ai_advisor import generate_ai_notification

# Configure logger
logger.remove()
logger.add(sys.stdout, level="INFO")

async def main():
    logger.info("🚀 Testing AI generation...")
    
    try:
        result = await generate_ai_notification(
            inn="7707083893",  # Sberbank as example
            company_name="ПАО Сбербанк",
            last_comment="Клиент просил перезвонить после праздников.",
            last_call_date=datetime.now(),
            all_comments=["Звонил 1.01", "Звонил 5.01", "Клиент просил перезвонить после праздников."],
            okved_code="64.19",
            okved_name="Денежное посредничество прочее",
            region="Москва",
            revenue="3000000", # 3 млрд
            net_profit="1000000",
            capital="500000",
            assets="10000000",
            debit="200000",
            credit="100000",
            gov_contracts="500000000",
            arbitration_open_count="2",
            arbitration_open_sum="1500000",
            arbitration_last_doc_date="01.12.2024",
            planned_call_date=datetime.now()
        )
        
        print("\n" + "="*50)
        print("RESULT:")
        print("="*50)
        print(result)
        print("="*50)
        
        if "AI модуль пока не подключён" in result or "AI модуль не настроен" in result:
            logger.warning("⚠️  AI module is NOT working (key missing or invalid configuration)")
        else:
            logger.success("✅ AI generation success!")
            
    except Exception as e:
        logger.error(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

