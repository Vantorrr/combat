import asyncio
from datetime import datetime, date
from typing import List, Optional

from loguru import logger
from openai import OpenAI

from config import settings


def _get_openai_client() -> Optional[OpenAI]:
    """Создаём клиента OpenAI, если задан ключ. Иначе возвращаем None (модуль будет неактивен)."""
    api_key = settings.openai_api_key
    if not api_key:
        logger.warning("OPENAI_API_KEY is not configured; AI advisor is disabled")
        return None
    return OpenAI(api_key=api_key)


# Статический список праздников (минимальный набор для MVP)
class Holiday:
    def __init__(self, month: int, day: int, title: str, tags: Optional[List[str]] = None):
        self.month = month
        self.day = day
        self.title = title
        self.tags = tags or []

    def date_for_year(self, year: int) -> date:
        return date(year, self.month, self.day)


HOLIDAYS: List[Holiday] = [
    # Гос праздники
    Holiday(1, 1, "Новый год"),
    Holiday(2, 23, "День защитника Отечества"),
    Holiday(3, 8, "Международный женский день"),
    Holiday(5, 1, "Праздник Весны и Труда"),
    Holiday(5, 9, "День Победы"),
    Holiday(6, 12, "День России"),
    Holiday(11, 4, "День народного единства"),
    # Отраслевые (минимальный набор примеров)
    Holiday(8, 12, "День строителя", tags=["строительство"]),
    Holiday(8, 2, "День железнодорожника", tags=["транспорт", "жд"]),
]


def get_near_holidays(target: date, window_days: int = 7) -> List[str]:
    """Вернуть список праздников в окне +/- window_days от заданной даты."""
    res: List[str] = []
    year = target.year
    for h in HOLIDAYS:
        h_date = h.date_for_year(year)
        delta = abs((h_date - target).days)
        if delta <= window_days:
            res.append(f"{h.title} ({h_date.strftime('%d.%m')})")
    return res


async def generate_ai_notification(
    *,
    inn: str,
    company_name: str,
    last_comment: str,
    last_call_date: Optional[datetime],
    all_comments: List[str],
    okved_code: str | None,
    okved_name: str | None,
    region: str | None,
    planned_call_date: Optional[datetime] = None,
) -> str:
    """
    Сгенерировать полный текст уведомления в формате, который просил заказчик.
    """
    client = _get_openai_client()
    if client is None:
        # Фоллбек: простой текст без нейросети
        logger.warning("AI notification requested, but OpenAI client is not configured")
        last_call_str = last_call_date.strftime("%d.%m.%y") if last_call_date else "неизвестно"
        return (
            f"Звонок сегодня\n"
            f"ИНН: {inn}\n"
            f"Название: {company_name}\n"
            f"Последний звонок: {last_call_str} — {last_comment}\n\n"
            f"Инфоповоды для звонка:\n"
            f"1. Новости отрасли и региона — модуль AI пока не подключён.\n"
            f"2. Праздники ±7 дней — модуль AI пока не подключён.\n"
            f"3. Анализ истории общения — модуль AI пока не подключён."
        )

    # Дата, относительно которой считаем праздники
    base_date = planned_call_date.date() if planned_call_date else date.today()
    near_holidays = get_near_holidays(base_date)

    all_comments_joined = "\n".join(all_comments) if all_comments else last_comment
    okved_part = f"{okved_code} — {okved_name}" if okved_code or okved_name else "неизвестно"
    region_part = region or "регион не указан"
    last_call_str = last_call_date.strftime("%d.%m.%y") if last_call_date else "неизвестно"
    holidays_text = "; ".join(near_holidays) if near_holidays else "нет подходящих праздников"

    system_prompt = (
        "Ты помощник по продажам для B2B-менеджеров. "
        "Говоришь по-русски, коротко, по делу, без воды и без фантазий. "
        "Твоя задача — на основе истории звонков, отрасли (ОКВЭД), региона и ближайших праздников "
        "предложить 3 конкретных инфоповода для следующего звонка.\n\n"
        "Структура ответа строго фиксирована:\n"
        "Звонок сегодня\n"
        "ИНН: ...\n"
        "Название: ...\n"
        "Последний звонок: ДД.ММ.ГГ — ТЕКСТ\n"
        "\n"
        "Инфоповоды для звонка:\n"
        "1. ... (на основе новостей отрасли/общей рыночной логики, без выдуманных фактов)\n"
        "2. ... (с учётом праздников +-7 дней, если они есть)\n"
        "3. ... (глубокий анализ истории комментариев: динамика, переносы, обещания; "
        "используй лучшие практики книжных подходов к продажам — SPIN, Challenger Sale и т.п., "
        "но не обязательно называй их явно).\n\n"
        "НЕ придумывай конкретные несуществующие новости или законы. "
        "Говори общими формулировками: 'на фоне общего роста/спада', 'на фоне ужесточения требований' и т.д."
    )

    user_content = (
        f"ИНН: {inn}\n"
        f"Компания: {company_name}\n"
        f"ОКВЭД: {okved_part}\n"
        f"Регион: {region_part}\n"
        f"Планируемая дата звонка: {base_date.strftime('%d.%m.%Y')}\n"
        f"Ближайшие праздники (+-7 дней): {holidays_text}\n"
        f"\n"
        f"Последний звонок: {last_call_str} — {last_comment}\n"
        f"\n"
        f"История комментариев (от старых к новым):\n"
        f"{all_comments_joined}\n"
    )

    def _call_openai() -> str:
        completion = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.6,
            max_tokens=600,
        )
        return completion.choices[0].message.content.strip()

    try:
        content = await asyncio.to_thread(_call_openai)
        return content
    except Exception as e:
        logger.error(f"Error while calling OpenAI for AI notification: {e}")
        # Фоллбек при ошибке
        return (
            f"Звонок сегодня\n"
            f"ИНН: {inn}\n"
            f"Название: {company_name}\n"
            f"Последний звонок: {last_call_str} — {last_comment}\n\n"
            f"Инфоповоды для звонка:\n"
            f"1. Общий инфоповод на основе ситуации в отрасли и регионе.\n"
            f"2. Праздники около даты звонка: {holidays_text}.\n"
            f"3. Сделайте упор на предыдущие договорённости и аккуратно уточните статус."
        )


