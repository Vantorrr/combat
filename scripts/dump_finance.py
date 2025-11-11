import asyncio
import json
import aiohttp
from loguru import logger
from config import settings


async def dump_finance(inn: str):
    url = f"{settings.datanewton_base_url}/finance"
    params = {"key": settings.datanewton_api_key, "inn": inn}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            text = await resp.text()
            logger.info(f"HTTP {resp.status}")
            try:
                data = json.loads(text)
                print(json.dumps(data, ensure_ascii=False, indent=2))
            except Exception:
                print(text)


if __name__ == "__main__":
    import sys
    inn = sys.argv[1] if len(sys.argv) > 1 else "7728212268"
    asyncio.run(dump_finance(inn))


