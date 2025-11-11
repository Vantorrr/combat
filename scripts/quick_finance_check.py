import asyncio
from services.datanewton_api import datanewton_api
from loguru import logger
import sys


async def main(inn: str):
    data = await datanewton_api.get_finance_data(inn)
    logger.info(f"INN={inn} -> {data}")


if __name__ == "__main__":
    inn = sys.argv[1] if len(sys.argv) > 1 else "7728212268"
    asyncio.run(main(inn))


